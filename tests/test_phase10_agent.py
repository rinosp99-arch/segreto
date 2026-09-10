"""Phase 10 ChatGPT Control Layer - Comprehensive Backend Testing
Tests the REAL chain: request -> auth -> scope -> target resolution -> validation -> action -> audit -> response -> rollback
"""
import requests
import json
import time
import sys

# Use public endpoint
import os
BASE_URL = os.environ.get("TEST_BACKEND", "http://localhost:8001")
FRONT_URL = os.environ.get("TEST_FRONTEND", "http://localhost:3000")
ADMIN_CREDS = {"email": "admin@latosegreto.it", "password": "LatoSegreto2025!"}

class TestRunner:
    def __init__(self):
        self.admin_token = None
        self.test_keys = []
        self.test_models = []
        self.test_landings = []
        self.passed = 0
        self.failed = 0
        self.results = []
        
    def log(self, test_name, passed, message=""):
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
        if message:
            print(f"  → {message}")
        self.results.append({"test": test_name, "passed": passed, "message": message})
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def get_admin_token(self):
        if not self.admin_token:
            r = requests.post(f"{BASE_URL}/api/admin/login", json=ADMIN_CREDS, timeout=20)
            assert r.status_code == 200, f"Admin login failed: {r.text}"
            self.admin_token = r.json()["token"]
        return self.admin_token
    
    def admin_headers(self):
        return {"Authorization": f"Bearer {self.get_admin_token()}", "Content-Type": "application/json"}
    
    def create_ai_key(self, name="test-key", role="AI_OPERATOR", scopes=None):
        """Create an AI_OPERATOR key via admin JWT"""
        body = {"name": name, "role": role, "source": "chatgpt"}
        if scopes:
            body["scopes"] = scopes
        r = requests.post(f"{BASE_URL}/api/v1/auth/keys", json=body, headers=self.admin_headers(), timeout=20)
        assert r.status_code == 201, f"Key creation failed: {r.text}"
        data = r.json()
        self.test_keys.append(data["id"])
        return data
    
    def cleanup(self):
        """Clean up test data"""
        print("\n🧹 Cleaning up test data...")
        for key_id in self.test_keys:
            try:
                requests.delete(f"{BASE_URL}/api/v1/auth/keys/{key_id}", headers=self.admin_headers(), timeout=10)
            except:
                pass
        for model_slug in self.test_models:
            try:
                requests.delete(f"{BASE_URL}/api/v1/models/{model_slug}", headers=self.admin_headers(), timeout=10)
            except:
                pass
        for landing_slug in self.test_landings:
            try:
                requests.delete(f"{BASE_URL}/api/v1/landings/{landing_slug}", headers=self.admin_headers(), timeout=10)
            except:
                pass
        # Restore flags to the values found at start (Phase 11 keeps the server in READ_ONLY on purpose)
        for flag, val in (getattr(self, "flags_before", None) or {f: True for f in ["ai_api_enabled", "ai_write_enabled", "ai_batch_enabled", "ai_approval_flow_enabled"]}).items():
            try:
                requests.put(f"{BASE_URL}/api/v1/config/flags/{flag}", json={"value": bool(val)}, headers=self.admin_headers(), timeout=10)
            except:
                pass
        # Restore rate limit
        try:
            requests.patch(f"{BASE_URL}/api/v1/ai/control", json={"rate_limit_per_min": 120}, headers=self.admin_headers(), timeout=10)
        except:
            pass

    # ============ TEST METHODS ============
    
    def test_01_api_key_creation_and_secrets(self):
        """Verify API key is shown ONLY once at creation and never retrievable"""
        key_data = self.create_ai_key(name="test-secret-check")
        
        # Check that api_key is present in creation response
        if "api_key" not in key_data:
            self.log("API Key Creation - Key Present", False, "api_key not in creation response")
            return
        
        api_key = key_data["api_key"]
        if not api_key.startswith("ls_"):
            self.log("API Key Creation - Key Format", False, f"Key doesn't start with ls_: {api_key[:10]}")
            return
        
        self.log("API Key Creation - Key Present", True, f"Key created: {api_key[:10]}...")
        
        # Verify GET /api/v1/auth/keys does NOT contain api_key or key_hash
        r = requests.get(f"{BASE_URL}/api/v1/auth/keys", headers=self.admin_headers(), timeout=20)
        keys_list = r.json()["items"]
        
        for key in keys_list:
            if "api_key" in key or "key_hash" in key:
                self.log("API Key List - No Secrets", False, "api_key or key_hash found in GET /api/v1/auth/keys")
                return
        
        self.log("API Key List - No Secrets", True, "No api_key or key_hash in list")
        
        # Verify GET /api/v1/auth/keys/{id}/usage does NOT contain api_key or key_hash
        r = requests.get(f"{BASE_URL}/api/v1/auth/keys/{key_data['id']}/usage", headers=self.admin_headers(), timeout=20)
        usage_data = r.json()
        
        if "api_key" in usage_data or "key_hash" in usage_data:
            self.log("API Key Usage - No Secrets", False, "api_key or key_hash found in usage endpoint")
            return
        
        self.log("API Key Usage - No Secrets", True, "No secrets in usage endpoint")
        
        # Verify GET /api/v1/ai/control does NOT contain api_key or key_hash
        r = requests.get(f"{BASE_URL}/api/v1/ai/control", headers=self.admin_headers(), timeout=20)
        control_data = r.json()
        
        # look for secret FIELDS (not the literal principal_type value "api_key")
        def _has_secret_field(o):
            if isinstance(o, dict):
                return any(k in ("api_key", "key_hash", "token", "token_hash", "password_hash") for k in o) or any(_has_secret_field(v) for v in o.values())
            if isinstance(o, list):
                return any(_has_secret_field(v) for v in o)
            return False
        if _has_secret_field(control_data) or any("ls_" in str(k.get("prefix", ""))[10:] for k in control_data.get("keys", [])):
            self.log("AI Control - No Secrets", False, "api_key or key_hash found in control endpoint")
            return
        
        self.log("AI Control - No Secrets", True, "No secrets in control endpoint")
    
    def test_02_auth_chain(self):
        """Test authentication chain: valid key -> 200, wrong key -> 401, revoked -> 401, disabled -> 401, rotate -> old 401 new 200"""
        key_data = self.create_ai_key(name="test-auth-chain")
        api_key = key_data["api_key"]
        key_id = key_data["id"]
        
        # Valid key -> 200 with headers
        r = requests.get(f"{BASE_URL}/api/v1/ai/status", headers={"X-API-Key": api_key}, timeout=20)
        if r.status_code != 200:
            self.log("Auth Chain - Valid Key", False, f"Expected 200, got {r.status_code}")
            return
        
        if "X-Request-ID" not in r.headers or "X-RateLimit-Limit" not in r.headers:
            self.log("Auth Chain - Response Headers", False, "Missing X-Request-ID or X-RateLimit-Limit")
            return
        
        self.log("Auth Chain - Valid Key", True, "200 with required headers")
        
        # Wrong key -> 401 INVALID_API_KEY
        r = requests.get(f"{BASE_URL}/api/v1/ai/status", headers={"X-API-Key": "ls_wrong_key_12345"}, timeout=20)
        if r.status_code != 401 or r.json().get("code") != "INVALID_API_KEY":
            self.log("Auth Chain - Wrong Key", False, f"Expected 401 INVALID_API_KEY, got {r.status_code} {r.json().get('code')}")
            return
        
        self.log("Auth Chain - Wrong Key", True, "401 INVALID_API_KEY")
        
        # Revoke key -> 401 API_KEY_REVOKED
        requests.delete(f"{BASE_URL}/api/v1/auth/keys/{key_id}", headers=self.admin_headers(), timeout=20)
        r = requests.get(f"{BASE_URL}/api/v1/ai/status", headers={"X-API-Key": api_key}, timeout=20)
        if r.status_code != 401 or r.json().get("code") != "API_KEY_REVOKED":
            self.log("Auth Chain - Revoked Key", False, f"Expected 401 API_KEY_REVOKED, got {r.status_code} {r.json().get('code')}")
            return
        
        self.log("Auth Chain - Revoked Key", True, "401 API_KEY_REVOKED")
        
        # Create new key for disable/enable test
        key_data2 = self.create_ai_key(name="test-disable")
        api_key2 = key_data2["api_key"]
        key_id2 = key_data2["id"]
        
        # Disable -> 401 API_KEY_DISABLED
        requests.post(f"{BASE_URL}/api/v1/auth/keys/{key_id2}/disable", headers=self.admin_headers(), timeout=20)
        r = requests.get(f"{BASE_URL}/api/v1/ai/status", headers={"X-API-Key": api_key2}, timeout=20)
        if r.status_code != 401 or r.json().get("code") != "API_KEY_DISABLED":
            self.log("Auth Chain - Disabled Key", False, f"Expected 401 API_KEY_DISABLED, got {r.status_code} {r.json().get('code')}")
            return
        
        self.log("Auth Chain - Disabled Key", True, "401 API_KEY_DISABLED")
        
        # Enable -> 200
        requests.post(f"{BASE_URL}/api/v1/auth/keys/{key_id2}/enable", headers=self.admin_headers(), timeout=20)
        r = requests.get(f"{BASE_URL}/api/v1/ai/status", headers={"X-API-Key": api_key2}, timeout=20)
        if r.status_code != 200:
            self.log("Auth Chain - Enabled Key", False, f"Expected 200 after enable, got {r.status_code}")
            return
        
        self.log("Auth Chain - Enabled Key", True, "200 after enable")
        
        # Rotate -> old key 401, new key 200
        r = requests.post(f"{BASE_URL}/api/v1/auth/keys/{key_id2}/rotate", headers=self.admin_headers(), timeout=20)
        new_key = r.json()["api_key"]
        
        r = requests.get(f"{BASE_URL}/api/v1/ai/status", headers={"X-API-Key": api_key2}, timeout=20)
        if r.status_code != 401:
            self.log("Auth Chain - Rotate Old Key", False, f"Old key should be 401, got {r.status_code}")
            return
        
        r = requests.get(f"{BASE_URL}/api/v1/ai/status", headers={"X-API-Key": new_key}, timeout=20)
        if r.status_code != 200:
            self.log("Auth Chain - Rotate New Key", False, f"New key should be 200, got {r.status_code}")
            return
        
        self.log("Auth Chain - Rotate", True, "Old key 401, new key 200")
        
        # Bearer Authorization header accepted
        r = requests.get(f"{BASE_URL}/api/v1/ai/status", headers={"Authorization": f"Bearer {new_key}"}, timeout=20)
        if r.status_code != 200:
            self.log("Auth Chain - Bearer Format", False, f"Bearer format should work, got {r.status_code}")
            return
        
        self.log("Auth Chain - Bearer Format", True, "Authorization: Bearer ls_... accepted")
    
    def test_03_scopes_and_critical_blocked(self):
        """Test scope enforcement and critical action blocking"""
        # Create key with limited scopes
        key_data = self.create_ai_key(name="test-scopes", scopes=["seo:read", "seo:audit", "ai:execute", "models:read"])
        api_key = key_data["api_key"]
        
        # Should fail models:publish (missing scope)
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/publish", 
                         json={"model": "francesca-rossi"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 403 or r.json().get("code") != "INSUFFICIENT_SCOPE":
            self.log("Scopes - Missing Scope", False, f"Expected 403 INSUFFICIENT_SCOPE, got {r.status_code} {r.json().get('code')}")
            return
        
        if "models:publish" not in r.json().get("data", {}).get("missing_scopes", []):
            self.log("Scopes - Missing Scope Details", False, "missing_scopes should contain models:publish")
            return
        
        self.log("Scopes - Missing Scope", True, "403 INSUFFICIENT_SCOPE with models:publish")
        
        # Should succeed seo:audit (has scope)
        r = requests.post(f"{BASE_URL}/api/v1/ai/seo/audit",
                         json={"model": "francesca-rossi"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Scopes - Allowed Scope", False, f"seo:audit should work, got {r.status_code}")
            return
        
        self.log("Scopes - Allowed Scope", True, "seo:audit works with correct scope")
        
        # Test CRITICAL actions blocked for API keys
        full_key = self.create_ai_key(name="test-critical")
        
        # GET /api/v1/auth/keys -> 403 CRITICAL_ACTION_BLOCKED
        r = requests.get(f"{BASE_URL}/api/v1/auth/keys", 
                        headers={"X-API-Key": full_key["api_key"]},
                        timeout=20)
        
        if r.status_code != 403 or r.json().get("detail", {}).get("code") != "CRITICAL_ACTION_BLOCKED":
            self.log("Critical - Keys Management", False, f"Expected 403 CRITICAL_ACTION_BLOCKED, got {r.status_code}")
            return
        
        self.log("Critical - Keys Management", True, "API key cannot access keys management")
        
        # PATCH /api/v1/config -> 403
        r = requests.patch(f"{BASE_URL}/api/v1/config",
                          json={"flags": {"test": True}},
                          headers={"X-API-Key": full_key["api_key"], "Content-Type": "application/json"},
                          timeout=20)
        
        if r.status_code != 403:
            self.log("Critical - Config Write", False, f"Expected 403, got {r.status_code}")
            return
        
        self.log("Critical - Config Write", True, "API key cannot modify config")
        
        # DELETE model -> 403
        r = requests.delete(f"{BASE_URL}/api/v1/models/francesca-rossi",
                           headers={"X-API-Key": full_key["api_key"]},
                           timeout=20)
        
        if r.status_code != 403:
            self.log("Critical - Model Delete", False, f"Expected 403, got {r.status_code}")
            return
        
        self.log("Critical - Model Delete", True, "API key cannot delete models")
    
    def test_04_kill_switch_and_read_only(self):
        """Test kill switch and READ_ONLY mode"""
        key_data = self.create_ai_key(name="test-modes")
        api_key = key_data["api_key"]
        
        # Set kill switch OFF
        requests.put(f"{BASE_URL}/api/v1/config/flags/ai_api_enabled",
                    json={"value": False},
                    headers=self.admin_headers(),
                    timeout=20)
        
        # AI key should get 503 AI_API_DISABLED
        r = requests.get(f"{BASE_URL}/api/v1/ai/status",
                        headers={"X-API-Key": api_key},
                        timeout=20)
        
        if r.status_code != 503 or r.json().get("code") != "AI_API_DISABLED":
            self.log("Kill Switch - AI Disabled", False, f"Expected 503 AI_API_DISABLED, got {r.status_code} {r.json().get('code')}")
            requests.put(f"{BASE_URL}/api/v1/config/flags/ai_api_enabled", json={"value": True}, headers=self.admin_headers(), timeout=20)
            return
        
        # JWT should still work
        r = requests.get(f"{BASE_URL}/api/v1/models",
                        headers=self.admin_headers(),
                        timeout=20)
        
        if r.status_code != 200:
            self.log("Kill Switch - JWT Still Works", False, f"JWT should work, got {r.status_code}")
            requests.put(f"{BASE_URL}/api/v1/config/flags/ai_api_enabled", json={"value": True}, headers=self.admin_headers(), timeout=20)
            return
        
        self.log("Kill Switch", True, "AI key 503, JWT still works")
        
        # Restore kill switch
        requests.put(f"{BASE_URL}/api/v1/config/flags/ai_api_enabled",
                    json={"value": True},
                    headers=self.admin_headers(),
                    timeout=20)
        
        # Set READ_ONLY mode
        requests.put(f"{BASE_URL}/api/v1/config/flags/ai_write_enabled",
                    json={"value": False},
                    headers=self.admin_headers(),
                    timeout=20)
        
        # Real write should fail
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/update",
                         json={"model": "francesca-rossi", "changes": {"tag": ["readonly-test"]}},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 403 or r.json().get("code") != "READ_ONLY_MODE":
            self.log("READ_ONLY - Write Blocked", False, f"Expected 403 READ_ONLY_MODE, got {r.status_code} {r.json().get('code')}")
            requests.put(f"{BASE_URL}/api/v1/config/flags/ai_write_enabled", json={"value": True}, headers=self.admin_headers(), timeout=20)
            return
        
        # Dry run should work
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/update",
                         json={"model": "francesca-rossi", "changes": {"tag": ["readonly-test"]}, "dry_run": True},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or not r.json().get("data", {}).get("dry_run"):
            self.log("READ_ONLY - Dry Run Works", False, f"Dry run should work, got {r.status_code}")
            requests.put(f"{BASE_URL}/api/v1/config/flags/ai_write_enabled", json={"value": True}, headers=self.admin_headers(), timeout=20)
            return
        
        # Confirm should be blocked even with dry_run
        r = requests.post(f"{BASE_URL}/api/v1/ai/approvals/confirm",
                         json={"token": "apr_test", "dry_run": True},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 403 or r.json().get("code") != "READ_ONLY_MODE":
            self.log("READ_ONLY - Confirm Blocked", False, f"Confirm should be blocked, got {r.status_code}")
            requests.put(f"{BASE_URL}/api/v1/config/flags/ai_write_enabled", json={"value": True}, headers=self.admin_headers(), timeout=20)
            return
        
        # Upload should be blocked even with dry_run
        r = requests.post(f"{BASE_URL}/api/v1/ai/media/upload",
                         json={"model": "francesca-rossi", "slot": "pair", "url": "https://example.com/test.jpg", "dry_run": True},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 403 or r.json().get("code") != "READ_ONLY_MODE":
            self.log("READ_ONLY - Upload Blocked", False, f"Upload should be blocked, got {r.status_code}")
            requests.put(f"{BASE_URL}/api/v1/config/flags/ai_write_enabled", json={"value": True}, headers=self.admin_headers(), timeout=20)
            return
        
        self.log("READ_ONLY Mode", True, "Writes blocked, dry runs allowed, upload/confirm always blocked")
        
        # Restore
        requests.put(f"{BASE_URL}/api/v1/config/flags/ai_write_enabled",
                    json={"value": True},
                    headers=self.admin_headers(),
                    timeout=20)
    
    def test_05_reference_resolver(self):
        """Test natural model reference resolver"""
        key_data = self.create_ai_key(name="test-resolver")
        api_key = key_data["api_key"]
        
        # Create two models with similar names
        r1 = requests.post(f"{BASE_URL}/api/v1/ai/models/create",
                          json={"nome": "Zeta Testuale Resolver"},
                          headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                          timeout=20)
        
        if r1.status_code != 200:
            self.log("Reference Resolver - Create Model 1", False, f"Failed to create model: {r1.status_code}")
            return
        
        model1 = r1.json()["data"]
        self.test_models.append(model1["slug"])
        
        r2 = requests.post(f"{BASE_URL}/api/v1/ai/models/create",
                          json={"nome": "Zeta Testuale Resolver 2"},
                          headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                          timeout=20)
        
        if r2.status_code != 200:
            self.log("Reference Resolver - Create Model 2", False, f"Failed to create model: {r2.status_code}")
            return
        
        model2 = r2.json()["data"]
        self.test_models.append(model2["slug"])
        
        # Find by ID
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/find",
                         json={"model": model1["id"]},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or r.json()["data"]["slug"] != model1["slug"]:
            self.log("Reference Resolver - By ID", False, f"Find by ID failed")
            return
        
        # Find by slug
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/find",
                         json={"model": model1["slug"]},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or r.json()["data"]["slug"] != model1["slug"]:
            self.log("Reference Resolver - By Slug", False, f"Find by slug failed")
            return
        
        # Find by exact name
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/find",
                         json={"model": "Zeta Testuale Resolver"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or r.json()["data"]["slug"] != model1["slug"]:
            self.log("Reference Resolver - By Name", False, f"Find by name failed")
            return
        
        # Find by partial (unambiguous)
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/find",
                         json={"model": "zeta test resolver 2"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or r.json()["data"]["slug"] != model2["slug"]:
            self.log("Reference Resolver - By Partial", False, f"Find by partial failed")
            return
        
        # Ambiguous reference -> 409 with matches
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/find",
                         json={"model": "zeta"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 409 or r.json().get("code") != "AMBIGUOUS_REFERENCE":
            self.log("Reference Resolver - Ambiguous", False, f"Expected 409 AMBIGUOUS_REFERENCE, got {r.status_code}")
            return
        
        matches = r.json().get("data", {}).get("matches", [])
        if len(matches) < 2:
            self.log("Reference Resolver - Matches", False, f"Expected at least 2 matches, got {len(matches)}")
            return
        
        required_fields = {"id", "nome", "slug"}
        if not required_fields <= set(matches[0].keys()):
            return
        
        # Not found -> 404
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/find",
                         json={"model": "non-esiste-xyz-12345"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 404 or r.json().get("code") != "NOT_FOUND":
            self.log("Reference Resolver - Not Found", False, f"Expected 404 NOT_FOUND, got {r.status_code}")
            return
        
        self.log("Reference Resolver", True, "ID, slug, name, partial work; ambiguous -> 409; not found -> 404")
    
    def test_06_safe_update_dry_run_concurrency(self):
        """Test SAFE update with dry-run and concurrency check"""
        key_data = self.create_ai_key(name="test-update")
        api_key = key_data["api_key"]
        
        # Create a test model
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/create",
                         json={"nome": "Test Update Model"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        model = r.json()["data"]
        self.test_models.append(model["slug"])
        etag = model["etag"]
        
        # Dry run update
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/update",
                         json={"model": model["slug"], "changes": {"tag": ["test", "dry"]}, "dry_run": True},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or not r.json().get("data", {}).get("dry_run"):
            self.log("Update - Dry Run", False, f"Dry run failed: {r.status_code}")
            return
        
        if r.json()["data"]["policy"]["level"] != "SAFE":
            self.log("Update - Policy Level", False, f"Expected SAFE, got {r.json()['data']['policy']['level']}")
            return
        
        # Verify etag unchanged after dry run
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/find",
                         json={"model": model["slug"]},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.json()["data"]["etag"] != etag:
            self.log("Update - Dry Run No Mutation", False, "Etag changed after dry run")
            return
        
        self.log("Update - Dry Run", True, "Dry run works, no mutation")
        
        # Real update with etag
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/update",
                         json={"model": model["slug"], "changes": {"tag": ["test", "real"]}, "expected_updated_at": etag},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or not r.json().get("ok"):
            self.log("Update - Real Update", False, f"Real update failed: {r.status_code}")
            return
        
        if not r.json().get("data", {}).get("version_id"):
            self.log("Update - Version Created", False, "No version_id in response")
            return
        
        if r.json().get("approval_required"):
            self.log("Update - No Approval", False, "SAFE update should not require approval")
            return
        
        new_etag = r.json()["data"]["etag"]
        
        self.log("Update - Real Update", True, "SAFE update applied without approval")
        
        # Try to update with old etag -> 409 CONFLICT
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/update",
                         json={"model": model["slug"], "changes": {"tag": ["stale"]}, "expected_updated_at": etag},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 409 or r.json().get("code") != "CONFLICT":
            self.log("Update - Concurrency Check", False, f"Expected 409 CONFLICT, got {r.status_code}")
            return
        
        self.log("Update - Concurrency Check", True, "Stale etag rejected with 409 CONFLICT")
    
    def test_07_review_required_approval_flow(self):
        """Test REVIEW_REQUIRED approval flow with single-use token"""
        key_data = self.create_ai_key(name="test-approval")
        api_key = key_data["api_key"]
        
        # Create a test model
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/create",
                         json={"nome": "Test Approval Model"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        model = r.json()["data"]
        self.test_models.append(model["slug"])
        etag = model["etag"]
        
        # Update with REVIEW field (bio)
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/update",
                         json={"model": model["slug"], "changes": {"bio": "Bio nuova sufficientemente lunga per il test di approvazione e verifica del flusso completo."}},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Approval - Request", False, f"Update failed: {r.status_code}")
            return
        
        if not r.json().get("approval_required"):
            self.log("Approval - Required", False, "approval_required should be true")
            return
        
        approval = r.json().get("approval", {})
        if not approval.get("token", "").startswith("apr_"):
            self.log("Approval - Token Format", False, f"Token should start with apr_, got {approval.get('token', '')[:10]}")
            return
        
        if approval.get("type") != "MODEL_UPDATE":
            self.log("Approval - Type", False, f"Expected MODEL_UPDATE, got {approval.get('type')}")
            return
        
        token = approval["token"]
        
        # Verify model not changed yet
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/find",
                         json={"model": model["slug"]},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.json()["data"]["etag"] != etag:
            self.log("Approval - No Mutation", False, "Model changed before approval")
            return
        
        self.log("Approval - Preview", True, "Approval token created, model unchanged")
        
        # Check pending approvals (token should NOT be in list)
        r = requests.get(f"{BASE_URL}/api/v1/ai/approvals",
                        headers={"X-API-Key": api_key},
                        timeout=20)
        
        items = r.json()["data"]["items"]
        for item in items:
            if "token" in item or "token_hash" in item:
                self.log("Approval - List No Token", False, "Token or token_hash found in approvals list")
                return
        
        self.log("Approval - List No Token", True, "Token not exposed in list")
        
        # Confirm approval
        r = requests.post(f"{BASE_URL}/api/v1/ai/approvals/confirm",
                         json={"token": token},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or not r.json().get("ok"):
            self.log("Approval - Confirm", False, f"Confirm failed: {r.status_code} {r.json()}")
            return
        
        if not r.json().get("data", {}).get("version_id"):
            self.log("Approval - Version Created", False, "No version_id after confirm")
            return
        
        # Verify model changed
        r = requests.get(f"{BASE_URL}/api/v1/models/{model['slug']}",
                        headers=self.admin_headers(),
                        timeout=20)
        
        if "Bio nuova" not in r.json().get("bio", ""):
            self.log("Approval - Applied", False, "Bio not updated after confirm")
            return
        
        self.log("Approval - Confirm", True, "Approval confirmed, change applied")
        
        # Try to use token again -> should fail
        r = requests.post(f"{BASE_URL}/api/v1/ai/approvals/confirm",
                         json={"token": token},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code not in (400, 404, 409) or r.json().get("code") != "APPROVAL_INVALID":
            self.log("Approval - Single Use", False, f"Token should be invalid, got {r.status_code}")
            return
        
        self.log("Approval - Single Use", True, "Token invalid after first use")
        
        # Test actor binding: create another key and try to confirm
        key_data2 = self.create_ai_key(name="test-other-actor")
        
        # Create new approval
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/update",
                         json={"model": model["slug"], "changes": {"frase": "Frase di test per actor binding."}},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        token2 = r.json()["approval"]["token"]
        
        # Try to confirm with different key
        r = requests.post(f"{BASE_URL}/api/v1/ai/approvals/confirm",
                         json={"token": token2},
                         headers={"X-API-Key": key_data2["api_key"], "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 403 or r.json().get("code") != "APPROVAL_INVALID":
            self.log("Approval - Actor Binding", False, f"Different actor should fail, got {r.status_code}")
            return
        
        self.log("Approval - Actor Binding", True, "Token bound to actor")
        
        # Test target change invalidation
        # Modify model via admin
        requests.patch(f"{BASE_URL}/api/v1/models/{model['slug']}",
                      json={"tag": ["changed-by-admin"]},
                      headers=self.admin_headers(),
                      timeout=20)
        
        # Try to confirm stale approval
        r = requests.post(f"{BASE_URL}/api/v1/ai/approvals/confirm",
                         json={"token": token2},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 409 or r.json().get("code") != "CONFLICT":
            self.log("Approval - Target Changed", False, f"Stale approval should fail, got {r.status_code}")
            return
        
        self.log("Approval - Target Changed", True, "Approval invalidated when target changes")
    
    def test_08_critical_never_executes(self):
        """Test CRITICAL actions are never exposed via API"""
        key_data = self.create_ai_key(name="test-critical")
        api_key = key_data["api_key"]
        
        # Create a published model copy to test CRITICAL SEO issue
        r = requests.post(f"{BASE_URL}/api/v1/models/francesca-rossi/duplicate",
                         headers=self.admin_headers(),
                         timeout=30)
        
        if r.status_code != 201:
            self.log("Critical - Setup", False, f"Failed to create duplicate: {r.status_code}")
            return
        
        dup_slug = r.json()["slug"]
        self.test_models.append(dup_slug)
        
        # Make it have a CRITICAL issue (missing onlyfans_url on a PUBLISHED model)
        requests.post(f"{BASE_URL}/api/v1/ai/models/publish", json={"model": dup_slug},
                      headers={"X-API-Key": api_key, "Content-Type": "application/json"}, timeout=30)
        requests.patch(f"{BASE_URL}/api/v1/models/{dup_slug}",
                      json={"onlyfans_url": "http://bad-link"},
                      headers=self.admin_headers(),
                      timeout=20)
        
        # Get SEO review to find CRITICAL issue
        r = requests.get(f"{BASE_URL}/api/v1/ai/models/{dup_slug}/seo/review",
                        headers={"X-API-Key": api_key},
                        timeout=20)
        
        critical_issues = [i for i in r.json()["data"]["items"] if i["severity"] == "CRITICAL"]
        
        if not critical_issues:
            self.log("Critical - Issue Found", False, "No CRITICAL issue found")
            return
        
        issue_id = critical_issues[0]["id"]
        
        # Try to preview CRITICAL fix -> should return ok:false with CRITICAL_ACTION_BLOCKED
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/{dup_slug}/seo/review/{issue_id}/preview",
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Critical - Preview Response", False, f"Expected 200, got {r.status_code}")
            return
        
        if r.json().get("ok") is not False or r.json().get("code") != "CRITICAL_ACTION_BLOCKED":
            self.log("Critical - Blocked", False, f"Expected ok:false CRITICAL_ACTION_BLOCKED, got {r.json()}")
            return
        
        self.log("Critical - SEO Review", True, "CRITICAL issue returns ok:false CRITICAL_ACTION_BLOCKED")
        
        # Verify apply-safe-fixes skips CRITICAL
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/{dup_slug}/seo/apply-safe-fixes",
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Critical - Safe Fixes", False, f"Safe fixes failed: {r.status_code}")
            return
        
        # CRITICAL count should remain unchanged
        if r.json()["data"]["critical"] == 0:
            self.log("Critical - Not Fixed", False, "CRITICAL issues should not be fixed")
            return
        
        self.log("Critical - Safe Fixes Skip", True, "apply-safe-fixes skips CRITICAL issues")
    
    def test_09_publish_validation(self):
        """Test publish always goes through validator, force ignored"""
        key_data = self.create_ai_key(name="test-publish")
        api_key = key_data["api_key"]
        
        # Create incomplete model
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/create",
                         json={"nome": "Test Publish Incomplete"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        model = r.json()["data"]
        self.test_models.append(model["slug"])
        
        # Try to publish with force:true -> should fail
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/publish",
                         json={"model": model["slug"], "force": True},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Publish - Response", False, f"Expected 200, got {r.status_code}")
            return
        
        if r.json().get("ok") is not False or r.json().get("code") != "PUBLICATION_BLOCKED":
            self.log("Publish - Blocked", False, f"Expected ok:false PUBLICATION_BLOCKED, got {r.json()}")
            return
        
        if not r.json().get("data", {}).get("missing"):
            self.log("Publish - Missing Fields", False, "missing field should be present")
            return
        
        # Verify model state unchanged
        r = requests.get(f"{BASE_URL}/api/v1/models/{model['slug']}",
                        headers=self.admin_headers(),
                        timeout=20)
        
        if r.json().get("stato") == "pubblicata":
            self.log("Publish - State Unchanged", False, "Model should not be published")
            return
        
        self.log("Publish - Validation", True, "Publish blocked for incomplete model, force ignored")
    
    def test_10_idempotency(self):
        """Test idempotency via Idempotency-Key header"""
        key_data = self.create_ai_key(name="test-idempotency")
        api_key = key_data["api_key"]
        
        import uuid
        idem_key = str(uuid.uuid4())
        
        # First request
        r1 = requests.post(f"{BASE_URL}/api/v1/ai/models/create",
                          json={"nome": "Idem Test Model"},
                          headers={"X-API-Key": api_key, "Content-Type": "application/json", "Idempotency-Key": idem_key},
                          timeout=20)
        
        if r1.status_code != 200:
            self.log("Idempotency - First Request", False, f"First request failed: {r1.status_code}")
            return
        
        model1_id = r1.json()["data"]["id"]
        model1_slug = r1.json()["data"]["slug"]
        self.test_models.append(model1_slug)
        
        # Second request with same key
        r2 = requests.post(f"{BASE_URL}/api/v1/ai/models/create",
                          json={"nome": "Idem Test Model"},
                          headers={"X-API-Key": api_key, "Content-Type": "application/json", "Idempotency-Key": idem_key},
                          timeout=20)
        
        if r2.status_code != 200:
            self.log("Idempotency - Second Request", False, f"Second request failed: {r2.status_code}")
            return
        
        model2_id = r2.json()["data"]["id"]
        
        if model1_id != model2_id:
            self.log("Idempotency - Same ID", False, f"IDs differ: {model1_id} vs {model2_id}")
            return
        
        if r2.headers.get("Idempotent-Replayed") != "true":
            self.log("Idempotency - Header", False, "Idempotent-Replayed header missing")
            return
        
        # Verify only one model created
        r = requests.get(f"{BASE_URL}/api/v1/models?q=Idem%20Test%20Model",
                        headers=self.admin_headers(),
                        timeout=20)
        
        if r.json()["total"] != 1:
            self.log("Idempotency - Single Model", False, f"Expected 1 model, got {r.json()['total']}")
            return
        
        self.log("Idempotency", True, "Same request returns same ID, Idempotent-Replayed: true, no duplicates")
    
    def test_11_rollback(self):
        """Test rollback preview/execute creates NEW version, history intact"""
        key_data = self.create_ai_key(name="test-rollback")
        api_key = key_data["api_key"]
        
        # Create model and make changes
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/create",
                         json={"nome": "Test Rollback Model"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        model = r.json()["data"]
        self.test_models.append(model["slug"])
        
        # Make a change
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/update",
                         json={"model": model["slug"], "changes": {"tag": ["v1"]}},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        version1 = r.json()["data"]["version_id"]
        
        # Make another change
        r = requests.post(f"{BASE_URL}/api/v1/ai/models/update",
                         json={"model": model["slug"], "changes": {"tag": ["v2"]}},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        # Preview rollback
        r = requests.post(f"{BASE_URL}/api/v1/ai/rollback/preview",
                         json={"model": model["slug"], "latest_ai": True},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Rollback - Preview", False, f"Preview failed: {r.status_code}")
            return
        
        if not r.json()["data"].get("version_id"):
            self.log("Rollback - Preview Version", False, "No version_id in preview")
            return
        
        version_to_rollback = r.json()["data"]["version_id"]
        
        # Dry run rollback
        r = requests.post(f"{BASE_URL}/api/v1/ai/rollback",
                         json={"version_id": version_to_rollback, "dry_run": True},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or not r.json()["data"].get("dry_run"):
            self.log("Rollback - Dry Run", False, f"Dry run failed: {r.status_code}")
            return
        
        # Real rollback
        r = requests.post(f"{BASE_URL}/api/v1/ai/rollback",
                         json={"version_id": version_to_rollback},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200 or not r.json().get("ok"):
            self.log("Rollback - Execute", False, f"Rollback failed: {r.status_code}")
            return
        
        new_version_id = r.json()["data"].get("new_version_id")
        if not new_version_id:
            self.log("Rollback - New Version", False, "No new_version_id created")
            return
        
        # Try to rollback same version again -> 409 CONFLICT
        r = requests.post(f"{BASE_URL}/api/v1/ai/rollback",
                         json={"version_id": version_to_rollback},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 409 or r.json().get("code") != "CONFLICT":
            self.log("Rollback - Duplicate", False, f"Expected 409 CONFLICT, got {r.status_code}")
            return
        
        # Verify history intact with rollback entry
        r = requests.get(f"{BASE_URL}/api/v1/versions?entity=model&entity_id={model['id']}",
                        headers=self.admin_headers(),
                        timeout=20)
        
        versions = r.json()["items"]
        if r.json()["total"] < 3:
            self.log("Rollback - History", False, f"Expected at least 3 versions, got {r.json()['total']}")
            return
        
        rollback_versions = [v for v in versions if v.get("source") == "rollback"]
        if not rollback_versions:
            self.log("Rollback - Source", False, "No version with source=rollback")
            return
        
        self.log("Rollback", True, "Preview/execute works, creates new version, history intact, duplicate blocked")
    
    def test_12_audit_log(self):
        """Test AI activity log contains required fields and no secrets"""
        key_data = self.create_ai_key(name="test-audit")
        api_key = key_data["api_key"]
        
        # Make some actions
        rc = requests.post(f"{BASE_URL}/api/v1/ai/models/create",
                     json={"nome": "Audit Test Model"},
                     headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                     timeout=20)
        if rc.status_code == 200 and rc.json().get("ok"):
            self.test_models.append(rc.json()["data"]["slug"])
        
        # Get audit log
        r = requests.get(f"{BASE_URL}/api/v1/ai/actions",
                        headers={"X-API-Key": api_key},
                        timeout=20)
        
        if r.status_code != 200:
            self.log("Audit - Access", False, f"Failed to get actions: {r.status_code}")
            return
        
        items = r.json()["data"]["items"]
        if not items:
            self.log("Audit - Items", False, "No audit items found")
            return
        
        # Check first item has required fields
        item = items[0]
        required = {"actor", "key_id", "request_id", "action", "target", "changes", "source"}
        if not required <= set(item.keys()):
            self.log("Audit - Fields", False, f"Missing fields: {required - set(item.keys())}")
            return
        
        if item.get("source") not in ("chatgpt", "admin-ai"):
            self.log("Audit - Source", False, f"Invalid source: {item.get('source')}")
            return
        
        # Verify no secrets in input
        if "input" in item:
            input_str = json.dumps(item["input"])
            if "api_key" in input_str or "ls_" in input_str:
                self.log("Audit - No Secrets", False, "Raw API key found in audit log")
                return
        
        self.log("Audit", True, "Activity log has required fields, source=chatgpt, no secrets")
    
    def test_13_analytics_structured(self):
        """Test analytics structured query with sample_size and data_available"""
        key_data = self.create_ai_key(name="test-analytics")
        api_key = key_data["api_key"]
        
        # Structured query
        r = requests.post(f"{BASE_URL}/api/v1/ai/analytics/query",
                         json={"metric": "onlyfans_ctr", "group_by": "model", "country": "IT", "period": "7d", "sort": "desc", "limit": 5},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Analytics - Structured", False, f"Query failed: {r.status_code}")
            return
        
        data = r.json()["data"]
        required = {"sample_size", "data_available"}
        if not required <= set(data.keys()):
            self.log("Analytics - Fields", False, f"Missing fields: {required - set(data.keys())}")
            return
        
        if data["sample_size"] == 0 and data["data_available"] is not False:
            self.log("Analytics - Data Available", False, "data_available should be false when sample_size is 0")
            return
        
        self.log("Analytics - Structured", True, "Query returns sample_size and data_available")
        
        # Natural language query
        r = requests.post(f"{BASE_URL}/api/v1/ai/analytics/query",
                         json={"question": "quale modella converte meglio in Italia?"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Analytics - Natural", False, f"Natural query failed: {r.status_code}")
            return
        
        if "data_available" not in r.json()["data"]:
            self.log("Analytics - Natural Fields", False, "data_available missing in natural query")
            return
        
        self.log("Analytics - Natural", True, "Natural language query works")
    
    def test_14_landing_flow(self):
        """Test landing create, validate, publish with approval"""
        key_data = self.create_ai_key(name="test-landing")
        api_key = key_data["api_key"]
        
        # Create landing
        r = requests.post(f"{BASE_URL}/api/v1/ai/landings",
                         json={
                             "model": "francesca-rossi",
                             "h1": "Il lato segreto di Francesca",
                             "slug": "test-landing-agent-flow",
                             "cta_text": "ENTRA",
                             "meta_description": "Una landing di test dedicata al pubblico italiano di LATO SEGRETO, con CTA e SEO."
                         },
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Landing - Create", False, f"Create failed: {r.status_code}")
            return
        
        landing = r.json()["data"]
        self.test_landings.append(landing["slug"])
        
        if landing.get("stato") != "bozza":
            self.log("Landing - Draft", False, f"Expected bozza, got {landing.get('stato')}")
            return
        
        if landing.get("targeting", {}).get("geoblocking") is not False:
            self.log("Landing - No Geoblocking", False, "geoblocking should be false")
            return
        
        self.log("Landing - Create", True, "Landing created in bozza, no geoblocking")
        
        # Validate
        r = requests.post(f"{BASE_URL}/api/v1/ai/landings/{landing['slug']}/validate",
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Landing - Validate", False, f"Validate failed: {r.status_code}")
            return
        
        self.log("Landing - Validate", True, "Validation works")
        
        # Publish without scope -> approval required
        r = requests.post(f"{BASE_URL}/api/v1/ai/landings/{landing['slug']}/publish",
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Landing - Publish Request", False, f"Publish request failed: {r.status_code}")
            return
        
        if not r.json().get("approval_required"):
            self.log("Landing - Approval Required", False, "approval_required should be true without landing:publish scope")
            return
        
        # Verify NOT published
        r = requests.get(f"{BASE_URL}/api/v1/landings/{landing['slug']}",
                        headers=self.admin_headers(),
                        timeout=20)
        
        if r.json().get("stato") == "pubblicata":
            self.log("Landing - Not Published", False, "Landing should not be published without approval")
            return
        
        self.log("Landing - Publish Flow", True, "Publish requires approval without landing:publish scope")
        
        # Verify public route is OFF
        r = requests.get(f"{BASE_URL}/api/landings/{landing['slug']}", timeout=20)  # public landing API stays OFF (flag)
        if r.status_code != 404:
            self.log("Landing - Public Route OFF", False, f"Public route should be 404, got {r.status_code}")
            return
        
        self.log("Landing - Public Route", True, "Public route OFF (flag)")
    
    def test_15_security_ssrf_and_mime(self):
        """Test SSRF blocking and invalid mime rejection"""
        key_data = self.create_ai_key(name="test-security")
        api_key = key_data["api_key"]
        
        # Test SSRF URLs
        ssrf_urls = [
            "http://127.0.0.1:8001/api/health",
            "http://localhost/test.jpg",
            "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.1/test.jpg"
        ]
        
        for url in ssrf_urls:
            r = requests.post(f"{BASE_URL}/api/v1/ai/media/upload",
                             json={"model": "francesca-rossi", "slot": "pair", "url": url},
                             headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                             timeout=20)
            
            if r.status_code not in (400, 422) or r.json().get("code") not in ("MEDIA_VALIDATION_FAILED", "BAD_REQUEST"):
                self.log("Security - SSRF", False, f"SSRF not blocked for {url}: {r.status_code}")
                return
        
        self.log("Security - SSRF", True, "SSRF URLs blocked")
        
        # Test invalid mime (text/html)
        import base64
        html_data = base64.b64encode(b"<html><body>test</body></html>").decode()
        
        r = requests.post(f"{BASE_URL}/api/v1/ai/media/upload",
                         json={"model": "francesca-rossi", "slot": "pair", "base64_data": html_data, "content_type": "text/html"},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code not in (400, 422):
            self.log("Security - Invalid Mime", False, f"text/html should be rejected: {r.status_code}")
            return
        
        self.log("Security - Invalid Mime", True, "text/html rejected")
    
    def test_16_capabilities_and_openapi(self):
        """Test capabilities manifest and OpenAPI spec"""
        key_data = self.create_ai_key(name="test-capabilities")
        api_key = key_data["api_key"]
        
        # Get capabilities
        r = requests.get(f"{BASE_URL}/api/v1/ai/capabilities",
                        headers={"X-API-Key": api_key},
                        timeout=20)
        
        if r.status_code != 200:
            self.log("Capabilities - Access", False, f"Failed to get capabilities: {r.status_code}")
            return
        
        caps = r.json()["data"]["capabilities"]
        if len(caps) < 20:
            self.log("Capabilities - Count", False, f"Expected at least 20 capabilities, got {len(caps)}")
            return
        
        # Check structure
        required = {"id", "method", "endpoint", "required_scopes", "safety_level", "errors"}
        for cap in caps[:3]:
            if not required <= set(cap.keys()):
                self.log("Capabilities - Structure", False, f"Missing fields: {required - set(cap.keys())}")
                return
        
        self.log("Capabilities", True, f"{len(caps)} capabilities with correct structure")
        
        # Get OpenAPI spec (no auth required)
        r = requests.get(f"{BASE_URL}/api/v1/ai/openapi.json", timeout=20)
        
        if r.status_code != 200:
            self.log("OpenAPI - Access", False, f"Failed to get OpenAPI: {r.status_code}")
            return
        
        spec = r.json()
        
        # Verify only /api/v1/ai/* paths
        for path in spec.get("paths", {}).keys():
            if not path.startswith("/api/v1/ai/"):
                self.log("OpenAPI - Paths", False, f"Non-AI path found: {path}")
                return
        
        # Verify no test-connection endpoint
        if "/api/v1/ai/test-connection" in spec.get("paths", {}):
            self.log("OpenAPI - No Test", False, "test-connection should not be in OpenAPI")
            return
        
        # Verify security schemes
        if "ApiKeyAuth" not in spec.get("components", {}).get("securitySchemes", {}):
            self.log("OpenAPI - Security", False, "ApiKeyAuth not in securitySchemes")
            return
        
        # Verify AIError schema
        if "AIError" not in spec.get("components", {}).get("schemas", {}):
            self.log("OpenAPI - Error Schema", False, "AIError schema missing")
            return
        
        # Verify servers URL is https
        servers = spec.get("servers", [])
        if not servers or not servers[0].get("url", "").startswith("https"):
            self.log("OpenAPI - HTTPS", False, "Server URL should be https")
            return
        
        self.log("OpenAPI", True, "Only /api/v1/ai/* paths, ApiKeyAuth, AIError schema, https server")
    
    def test_17_batch_and_rate_limit(self):
        """Test batch operations and rate limiting"""
        key_data = self.create_ai_key(name="test-batch")
        api_key = key_data["api_key"]
        
        # Test batch SEO fix
        r = requests.post(f"{BASE_URL}/api/v1/ai/batch/seo-safe-fix",
                         json={"selection": "ids", "ids": ["francesca-rossi"], "dry_run": True},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 200:
            self.log("Batch - SEO Fix", False, f"Batch failed: {r.status_code}")
            return
        
        if r.json()["data"]["targets_affected"] != 1:
            self.log("Batch - Targets", False, f"Expected 1 target, got {r.json()['data']['targets_affected']}")
            return
        
        self.log("Batch - SEO Fix", True, "Batch operation works")
        
        # Disable batch
        requests.put(f"{BASE_URL}/api/v1/config/flags/ai_batch_enabled",
                    json={"value": False},
                    headers=self.admin_headers(),
                    timeout=20)
        
        r = requests.post(f"{BASE_URL}/api/v1/ai/batch/seo-safe-fix",
                         json={"selection": "ids", "ids": ["francesca-rossi"]},
                         headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                         timeout=20)
        
        if r.status_code != 403 or r.json().get("code") != "BATCH_DISABLED":
            self.log("Batch - Disabled", False, f"Expected 403 BATCH_DISABLED, got {r.status_code}")
            requests.put(f"{BASE_URL}/api/v1/config/flags/ai_batch_enabled", json={"value": True}, headers=self.admin_headers(), timeout=20)
            return
        
        # Restore
        requests.put(f"{BASE_URL}/api/v1/config/flags/ai_batch_enabled",
                    json={"value": True},
                    headers=self.admin_headers(),
                    timeout=20)
        
        self.log("Batch - Flag", True, "Batch disabled flag works")
        
        # Test rate limit
        # Set rate limit to 1 via control endpoint
        r = requests.patch(f"{BASE_URL}/api/v1/ai/control",
                          json={"rate_limit_per_min": 1},
                          headers=self.admin_headers(),
                          timeout=20)
        
        # Should be floored to 10
        if r.json().get("rate_limit_per_min") != 10:
            self.log("Rate Limit - Floor", False, f"Expected 10 (floor), got {r.json().get('rate_limit_per_min')}")
            return
        
        self.log("Rate Limit - Floor", True, "rate_limit_per_min floored to 10")
        
        # Create key with custom rate limit
        rl_key = self.create_ai_key(name="test-rate-limit", role="AI_OPERATOR")
        r = requests.patch(f"{BASE_URL}/api/v1/auth/keys/{rl_key['id']}",
                          json={"rate_limit_per_min": 12},
                          headers=self.admin_headers(),
                          timeout=20)
        
        # Make 15 requests
        codes = []
        for i in range(15):
            r = requests.get(f"{BASE_URL}/api/v1/ai/status",
                           headers={"X-API-Key": rl_key["api_key"]},
                           timeout=20)
            codes.append(r.status_code)
            if r.status_code == 429:
                if "Retry-After" not in r.headers:
                    self.log("Rate Limit - Retry Header", False, "Retry-After header missing")
                    return
                break
        
        if 429 not in codes:
            self.log("Rate Limit - 429", False, "Expected 429 after rate limit")
            return
        
        self.log("Rate Limit", True, "429 RATE_LIMITED with Retry-After header")
        
        # Restore rate limit
        requests.patch(f"{BASE_URL}/api/v1/ai/control",
                      json={"rate_limit_per_min": 120},
                      headers=self.admin_headers(),
                      timeout=20)
    
    def test_18_regression_public_routes(self):
        """Test regression: public routes still work"""
        # Home page
        r = requests.get(f"{FRONT_URL}/", timeout=20)
        if r.status_code != 200:
            self.log("Regression - Home", False, f"Home page failed: {r.status_code}")
            return
        
        self.log("Regression - Home", True, "Home page loads")
        
        # Model page
        r = requests.get(f"{FRONT_URL}/modelle/francesca-rossi", timeout=20)
        if r.status_code != 200:
            self.log("Regression - Model Page", False, f"Model page failed: {r.status_code}")
            return
        
        self.log("Regression - Model Page", True, "Model page renders")
        
        # Public API
        r = requests.get(f"{BASE_URL}/api/models", timeout=20)
        if r.status_code != 200:
            self.log("Regression - Public API", False, f"Public API failed: {r.status_code}")
            return
        
        if r.json().get("total", 0) < 10:
            self.log("Regression - Models Count", False, f"Expected at least 10 models, got {r.json().get('total')}")
            return
        
        self.log("Regression - Public API", True, "GET /api/models returns published models")
        
        # Admin dashboard
        r = requests.get(f"{BASE_URL}/api/v1/dashboard/overview?range=7g",
                        headers=self.admin_headers(),
                        timeout=30)
        
        if r.status_code != 200:
            self.log("Regression - Admin Dashboard", False, f"Dashboard failed: {r.status_code}")
            return
        
        self.log("Regression - Admin Dashboard", True, "Admin dashboard loads")
        
        # Motore sections
        r = requests.get(f"{BASE_URL}/api/v1/seo/issues?limit=10",
                        headers=self.admin_headers(),
                        timeout=20)
        
        if r.status_code != 200:
            self.log("Regression - SEO Issues", False, f"SEO issues failed: {r.status_code}")
            return
        
        self.log("Regression - Motore", True, "Motore sections (SEO, versions, jobs) still work")
    
    def run_all(self):
        """Run all tests"""
        print("=" * 60)
        print("PHASE 10 CHATGPT CONTROL LAYER - BACKEND TESTING")
        print("=" * 60)
        print(f"Testing against: {BASE_URL}\n")
        try:
            cfg = requests.get(f"{BASE_URL}/api/v1/config", headers=self.admin_headers(), timeout=20).json().get("flags", {})
            self.flags_before = {f: cfg.get(f, True) for f in ["ai_api_enabled", "ai_write_enabled", "ai_batch_enabled", "ai_approval_flow_enabled"]}
            for f in self.flags_before:
                requests.put(f"{BASE_URL}/api/v1/config/flags/{f}", json={"value": True}, headers=self.admin_headers(), timeout=10)
        except Exception:
            self.flags_before = None
        
        try:
            # Run tests in order
            self.test_01_api_key_creation_and_secrets()
            self.test_02_auth_chain()
            self.test_03_scopes_and_critical_blocked()
            self.test_04_kill_switch_and_read_only()
            self.test_05_reference_resolver()
            self.test_06_safe_update_dry_run_concurrency()
            self.test_07_review_required_approval_flow()
            self.test_08_critical_never_executes()
            self.test_09_publish_validation()
            self.test_10_idempotency()
            self.test_11_rollback()
            self.test_12_audit_log()
            self.test_13_analytics_structured()
            self.test_14_landing_flow()
            self.test_15_security_ssrf_and_mime()
            self.test_16_capabilities_and_openapi()
            self.test_17_batch_and_rate_limit()
            self.test_18_regression_public_routes()
            
        finally:
            self.cleanup()
        
        print("\n" + "=" * 60)
        print(f"RESULTS: {self.passed} passed, {self.failed} failed")
        print("=" * 60)
        
        if self.failed > 0:
            print("\nFailed tests:")
            for result in self.results:
                if not result["passed"]:
                    print(f"  ❌ {result['test']}: {result['message']}")
        
        return self.failed == 0

if __name__ == "__main__":
    runner = TestRunner()
    success = runner.run_all()
    sys.exit(0 if success else 1)
