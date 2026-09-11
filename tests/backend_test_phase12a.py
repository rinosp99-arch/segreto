"""Phase 12A - Total Site Control API v2 Backend Testing
Tests the universal capability engine under /api/v2/ai/* with 104 capabilities.
Server must stay in READ_ONLY mode throughout.
"""
import requests
import sys
import time
import json
from datetime import datetime

BASE_URL = "https://secret-side.preview.emergentagent.com"
import sys as _sys; _sys.path.insert(0, "/app/tests")
from _creds import admin_credentials as _ac
_C = _ac()
ADMIN_EMAIL = _C.get("email", "")
ADMIN_PASSWORD = _C.get("password", "")

class Phase12ATester:
    def __init__(self):
        self.base_url = BASE_URL
        self.admin_jwt = None
        self.api_key = None
        self.api_key_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = []
        
    def log(self, msg, level="INFO"):
        print(f"[{level}] {msg}")
        
    def test(self, name, method, endpoint, expected_status, headers=None, data=None, json_data=None, params=None):
        """Run a single test"""
        url = f"{self.base_url}{endpoint}"
        h = headers or {}
        self.tests_run += 1
        
        try:
            if method == "GET":
                r = requests.get(url, headers=h, params=params, timeout=30)
            elif method == "POST":
                r = requests.post(url, headers=h, json=json_data, data=data, timeout=30)
            elif method == "PATCH":
                r = requests.patch(url, headers=h, json=json_data, timeout=30)
            elif method == "DELETE":
                r = requests.delete(url, headers=h, timeout=30)
            else:
                raise ValueError(f"Unknown method: {method}")
                
            success = r.status_code == expected_status
            
            if success:
                self.tests_passed += 1
                self.log(f"✅ {name} - Status: {r.status_code}", "PASS")
                return True, r
            else:
                self.tests_failed.append(name)
                self.log(f"❌ {name} - Expected {expected_status}, got {r.status_code}", "FAIL")
                try:
                    self.log(f"   Response: {r.text[:200]}", "FAIL")
                except:
                    pass
                return False, r
                
        except Exception as e:
            self.tests_failed.append(name)
            self.log(f"❌ {name} - Error: {str(e)}", "FAIL")
            return False, None
            
    def admin_login(self):
        """Login as admin and get JWT"""
        self.log("=== Admin Login ===")
        success, r = self.test(
            "Admin Login",
            "POST",
            "/api/admin/login",
            200,
            json_data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        if success and r:
            data = r.json()
            self.admin_jwt = data.get("token")
            self.log(f"Admin JWT obtained (prefix: {self.admin_jwt[:20]}...)")
            return True
        return False
        
    def create_api_key(self):
        """Create temporary AI API key"""
        self.log("\n=== Create Temporary AI API Key ===")
        success, r = self.test(
            "Create AI API Key",
            "POST",
            "/api/v1/auth/keys",
            201,
            headers={"Authorization": f"Bearer {self.admin_jwt}"},
            json_data={
                "name": f"test-phase12a-{int(time.time())}",
                "role": "SUPER_ADMIN",
                "source": "chatgpt"
            }
        )
        if success and r:
            data = r.json()
            self.api_key = data.get("api_key")
            self.api_key_id = data.get("id")
            self.log(f"API Key created: {self.api_key[:15]}... (ID: {self.api_key_id})")
            return True
        return False
        
    def test_v2_capabilities(self):
        """Test GET /api/v2/ai/capabilities"""
        self.log("\n=== Test v2 Capabilities Endpoint ===")
        
        # Test with auth
        success, r = self.test(
            "GET /api/v2/ai/capabilities (with auth)",
            "GET",
            "/api/v2/ai/capabilities",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        if success and r:
            data = r.json()
            if data.get("ok") and data.get("data"):
                caps = data["data"].get("capabilities", [])
                count = data["data"].get("count", 0)
                mode = data["data"].get("mode")
                by_cat = data["data"].get("by_category", {})
                
                self.log(f"   Total capabilities: {count}")
                self.log(f"   Mode: {mode}")
                self.log(f"   By category: {json.dumps(by_cat, indent=2)}")
                
                # Check no CRITICAL capabilities
                critical = [c for c in caps if c.get("risk") == "CRITICAL"]
                if critical:
                    self.log(f"   ❌ Found {len(critical)} CRITICAL capabilities (should be 0)", "FAIL")
                    self.tests_failed.append("No CRITICAL capabilities")
                else:
                    self.log("   ✅ No CRITICAL capabilities listed", "PASS")
                    self.tests_passed += 1
                    
                # Check count is 104
                if count != 104:
                    self.log(f"   ❌ Expected 104 capabilities, got {count}", "FAIL")
                    self.tests_failed.append("104 capabilities count")
                else:
                    self.log("   ✅ Correct count: 104 capabilities", "PASS")
                    self.tests_passed += 1
                    
        # Test without auth (should fail)
        self.test(
            "GET /api/v2/ai/capabilities (no auth)",
            "GET",
            "/api/v2/ai/capabilities",
            401
        )
        
        # Test with wrong key
        self.test(
            "GET /api/v2/ai/capabilities (wrong key)",
            "GET",
            "/api/v2/ai/capabilities",
            401,
            headers={"Authorization": "Bearer ls_wrong_key_12345"}
        )
        
    def test_get_capability(self):
        """Test GET /api/v2/ai/capabilities/{id}"""
        self.log("\n=== Test Get Single Capability ===")
        
        # Test valid capability
        success, r = self.test(
            "GET /api/v2/ai/capabilities/models.update",
            "GET",
            "/api/v2/ai/capabilities/models.update",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        if success and r:
            data = r.json()
            if data.get("ok") and data.get("data"):
                cap = data["data"]
                self.log(f"   Status: {cap.get('status')}")
                self.log(f"   Version: {cap.get('capability_version')}")
                self.log(f"   Has parameters_schema: {bool(cap.get('parameters_schema'))}")
                
                if cap.get("status") != "BOUND":
                    self.log(f"   ❌ Expected status BOUND, got {cap.get('status')}", "FAIL")
                    self.tests_failed.append("models.update BOUND status")
                else:
                    self.log("   ✅ Status is BOUND", "PASS")
                    self.tests_passed += 1
                    
        # Test non-existent capability
        success, r = self.test(
            "GET /api/v2/ai/capabilities/does.not.exist",
            "GET",
            "/api/v2/ai/capabilities/does.not.exist",
            404,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        if success and r:
            data = r.json()
            code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
            if code == "UNKNOWN_CAPABILITY":
                self.log("   ✅ Correct error code: UNKNOWN_CAPABILITY", "PASS")
                self.tests_passed += 1
            else:
                self.log(f"   ❌ Expected code UNKNOWN_CAPABILITY, got {code}", "FAIL")
                self.tests_failed.append("Unknown capability error code")
                
    def test_preview(self):
        """Test POST /api/v2/ai/preview"""
        self.log("\n=== Test Preview Endpoint ===")
        
        # Preview a model update (should work in READ_ONLY)
        success, r = self.test(
            "POST /api/v2/ai/preview models.update",
            "POST",
            "/api/v2/ai/preview",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={
                "action": "models.update",
                "target": "francesca-rossi",
                "parameters": {
                    "changes": {"badge": "Test Preview"}
                }
            }
        )
        if success and r:
            data = r.json()
            if data.get("ok") and data.get("data"):
                dry_run = data["data"].get("dry_run")
                rollback_available = data["data"].get("rollback", {}).get("available", True)
                changes = data.get("changes", [])
                
                self.log(f"   dry_run: {dry_run}")
                self.log(f"   rollback.available: {rollback_available}")
                self.log(f"   changes count: {len(changes)}")
                
                if dry_run is not True:
                    self.log(f"   ❌ Expected dry_run=true, got {dry_run}", "FAIL")
                    self.tests_failed.append("Preview dry_run flag")
                else:
                    self.log("   ✅ dry_run is true", "PASS")
                    self.tests_passed += 1
                    
                # Check that badge field is in changes
                badge_change = any(c.get("field") == "badge" for c in changes)
                if badge_change:
                    self.log("   ✅ Badge change listed in changes", "PASS")
                    self.tests_passed += 1
                else:
                    self.log("   ❌ Badge change not found in changes", "FAIL")
                    self.tests_failed.append("Preview changes list")
                    
    def test_execute_read_only(self):
        """Test POST /api/v2/ai/execute in READ_ONLY mode"""
        self.log("\n=== Test Execute in READ_ONLY Mode ===")
        
        # Try to execute a write (should fail with 403 READ_ONLY_MODE)
        success, r = self.test(
            "POST /api/v2/ai/execute models.update (write in READ_ONLY)",
            "POST",
            "/api/v2/ai/execute",
            403,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={
                "action": "models.update",
                "target": "francesca-rossi",
                "parameters": {
                    "changes": {"badge": "Test Write"}
                }
            }
        )
        if success and r:
            data = r.json()
            code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
            if code == "READ_ONLY_MODE":
                self.log("   ✅ Correct error code: READ_ONLY_MODE", "PASS")
                self.tests_passed += 1
            else:
                self.log(f"   ❌ Expected code READ_ONLY_MODE, got {code}", "FAIL")
                self.tests_failed.append("READ_ONLY_MODE error code")
                
        # Execute a read capability (should work)
        self.test(
            "POST /api/v2/ai/execute models.list (read)",
            "POST",
            "/api/v2/ai/execute",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={"action": "models.list"}
        )
        
        # Execute settings.get (read)
        self.test(
            "POST /api/v2/ai/execute settings.get",
            "POST",
            "/api/v2/ai/execute",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={"action": "settings.get"}
        )
        
        # Execute seo.audit (read)
        self.test(
            "POST /api/v2/ai/execute seo.audit",
            "POST",
            "/api/v2/ai/execute",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={
                "action": "seo.audit",
                "target": "francesca-rossi"
            }
        )
        
    def test_validation_errors(self):
        """Test validation errors"""
        self.log("\n=== Test Validation Errors ===")
        
        # Test unknown capability
        success, r = self.test(
            "POST /api/v2/ai/execute shell.exec (unknown)",
            "POST",
            "/api/v2/ai/execute",
            404,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={"action": "shell.exec"}
        )
        if success and r:
            data = r.json()
            code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
            if code == "UNKNOWN_CAPABILITY":
                self.log("   ✅ Correct error code: UNKNOWN_CAPABILITY", "PASS")
                self.tests_passed += 1
                
        # Test missing action field
        success, r = self.test(
            "POST /api/v2/ai/execute (no action)",
            "POST",
            "/api/v2/ai/execute",
            422,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={}
        )
        if success and r:
            data = r.json()
            code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
            if code == "VALIDATION_FAILED":
                self.log("   ✅ Correct error code: VALIDATION_FAILED", "PASS")
                self.tests_passed += 1
                
        # Test invalid parameters
        success, r = self.test(
            "POST /api/v2/ai/preview invalid params",
            "POST",
            "/api/v2/ai/preview",
            422,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={
                "action": "models.update",
                "target": "francesca-rossi",
                "parameters": {
                    "changes": "not-an-object"
                }
            }
        )
        if success and r:
            data = r.json()
            code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
            if code == "VALIDATION_FAILED":
                self.log("   ✅ Correct error code: VALIDATION_FAILED", "PASS")
                self.tests_passed += 1
                
    def test_optimistic_concurrency(self):
        """Test optimistic concurrency control"""
        self.log("\n=== Test Optimistic Concurrency ===")
        
        success, r = self.test(
            "POST /api/v2/ai/preview with stale expected_updated_at",
            "POST",
            "/api/v2/ai/preview",
            409,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={
                "action": "models.update",
                "target": "francesca-rossi",
                "parameters": {
                    "changes": {"badge": "Test"},
                    "expected_updated_at": "2000-01-01T00:00:00+00:00"
                }
            }
        )
        if success and r:
            data = r.json()
            code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
            if code == "CONFLICT":
                self.log("   ✅ Correct error code: CONFLICT", "PASS")
                self.tests_passed += 1
                
    def test_models_find(self):
        """Test POST /api/v2/ai/models/find"""
        self.log("\n=== Test Models Find ===")
        
        # Find existing model
        success, r = self.test(
            "POST /api/v2/ai/models/find (Francesca)",
            "POST",
            "/api/v2/ai/models/find",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={"reference": "Francesca"}
        )
        if success and r:
            data = r.json()
            if data.get("ok") and data.get("data"):
                slug = data["data"].get("slug")
                if slug == "francesca-rossi":
                    self.log(f"   ✅ Found correct model: {slug}", "PASS")
                    self.tests_passed += 1
                else:
                    self.log(f"   ❌ Expected slug francesca-rossi, got {slug}", "FAIL")
                    self.tests_failed.append("Models find slug")
                    
        # Find non-existent model
        self.test(
            "POST /api/v2/ai/models/find (non-existent)",
            "POST",
            "/api/v2/ai/models/find",
            404,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={"reference": "zzzz-nope"}
        )
        
    def test_status(self):
        """Test GET /api/v2/ai/status"""
        self.log("\n=== Test Status Endpoint ===")
        
        success, r = self.test(
            "GET /api/v2/ai/status",
            "GET",
            "/api/v2/ai/status",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        if success and r:
            data = r.json()
            if data.get("ok") and data.get("data"):
                mode = data["data"].get("mode")
                reg = data["data"].get("capabilities_registry", {})
                total = reg.get("total", 0)
                
                self.log(f"   Mode: {mode}")
                self.log(f"   Total capabilities: {total}")
                
                if mode != "READ_ONLY":
                    self.log(f"   ❌ Expected mode READ_ONLY, got {mode}", "FAIL")
                    self.tests_failed.append("Status mode READ_ONLY")
                else:
                    self.log("   ✅ Mode is READ_ONLY", "PASS")
                    self.tests_passed += 1
                    
                if total != 104:
                    self.log(f"   ❌ Expected 104 capabilities, got {total}", "FAIL")
                    self.tests_failed.append("Status capabilities count")
                else:
                    self.log("   ✅ Correct count: 104", "PASS")
                    self.tests_passed += 1
                    
                # Check no nested 'ok' key (no double envelope)
                if "ok" in data["data"]:
                    self.log("   ❌ Found nested 'ok' key in data (double envelope)", "FAIL")
                    self.tests_failed.append("No double envelope")
                else:
                    self.log("   ✅ No double envelope", "PASS")
                    self.tests_passed += 1
                    
    def test_analytics_query(self):
        """Test POST /api/v2/ai/analytics/query"""
        self.log("\n=== Test Analytics Query ===")
        
        # Valid query
        self.test(
            "POST /api/v2/ai/analytics/query (valid)",
            "POST",
            "/api/v2/ai/analytics/query",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={
                "metric": "model_views",
                "range": "7g"
            }
        )
        
        # Invalid metric
        success, r = self.test(
            "POST /api/v2/ai/analytics/query (invalid metric)",
            "POST",
            "/api/v2/ai/analytics/query",
            422,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={
                "metric": "views"
            }
        )
        if success and r:
            data = r.json()
            code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
            if code == "VALIDATION_FAILED":
                self.log("   ✅ Correct error code: VALIDATION_FAILED", "PASS")
                self.tests_passed += 1
                
    def test_approvals(self):
        """Test GET /api/v2/ai/approvals"""
        self.log("\n=== Test Approvals Endpoint ===")
        
        success, r = self.test(
            "GET /api/v2/ai/approvals",
            "GET",
            "/api/v2/ai/approvals",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        if success and r:
            data = r.json()
            if data.get("ok") and data.get("data"):
                items = data["data"].get("items", [])
                self.log(f"   Pending approvals: {len(items)}")
                self.log("   ✅ Approvals endpoint working", "PASS")
                self.tests_passed += 1
                
    def test_rollback(self):
        """Test POST /api/v2/ai/rollback"""
        self.log("\n=== Test Rollback Endpoint ===")
        
        success, r = self.test(
            "POST /api/v2/ai/rollback (dry_run, non-existent session)",
            "POST",
            "/api/v2/ai/rollback",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={
                "session_id": "ses_nonexistent",
                "dry_run": True
            }
        )
        if success and r:
            data = r.json()
            if data.get("ok"):
                self.log("   ✅ Rollback dry_run working", "PASS")
                self.tests_passed += 1
                
    def test_openapi_chatgpt(self):
        """Test GET /api/v2/ai/openapi-chatgpt.json"""
        self.log("\n=== Test OpenAPI ChatGPT Schema ===")
        
        # Public endpoint, no auth required
        success, r = self.test(
            "GET /api/v2/ai/openapi-chatgpt.json (public)",
            "GET",
            "/api/v2/ai/openapi-chatgpt.json",
            200
        )
        if success and r:
            try:
                schema = r.json()
                openapi_version = schema.get("openapi")
                servers = schema.get("servers", [])
                paths = schema.get("paths", {})
                
                self.log(f"   OpenAPI version: {openapi_version}")
                self.log(f"   Servers: {len(servers)}")
                self.log(f"   Paths: {len(paths)}")
                
                if openapi_version != "3.1.0":
                    self.log(f"   ❌ Expected OpenAPI 3.1.0, got {openapi_version}", "FAIL")
                    self.tests_failed.append("OpenAPI version")
                else:
                    self.log("   ✅ Correct OpenAPI version", "PASS")
                    self.tests_passed += 1
                    
                # Count operations
                operations = []
                for path, methods in paths.items():
                    for method, spec in methods.items():
                        if method in ["get", "post", "put", "patch", "delete"]:
                            op_id = spec.get("operationId")
                            if op_id:
                                operations.append(op_id)
                                
                self.log(f"   Operations: {len(operations)}")
                self.log(f"   Operation IDs: {', '.join(operations[:5])}...")
                
                if len(operations) != 12:
                    self.log(f"   ❌ Expected 12 operations, got {len(operations)}", "FAIL")
                    self.tests_failed.append("OpenAPI operations count")
                else:
                    self.log("   ✅ Correct count: 12 operations", "PASS")
                    self.tests_passed += 1
                    
                # Check expected operation IDs
                expected_ops = {
                    "getCapabilities", "getCapability", "previewCapability", "executeCapability",
                    "listApprovals", "approveApproval", "rejectApproval", "getJob",
                    "queryAnalytics", "getSystemStatus", "rollback", "findModel"
                }
                found_ops = set(operations)
                if expected_ops.issubset(found_ops):
                    self.log("   ✅ All expected operations present", "PASS")
                    self.tests_passed += 1
                else:
                    missing = expected_ops - found_ops
                    self.log(f"   ❌ Missing operations: {missing}", "FAIL")
                    self.tests_failed.append("OpenAPI expected operations")
                    
                # Check servers URL is https
                if servers and servers[0].get("url", "").startswith("https://"):
                    self.log("   ✅ Server URL is https", "PASS")
                    self.tests_passed += 1
                else:
                    self.log("   ❌ Server URL is not https", "FAIL")
                    self.tests_failed.append("OpenAPI server URL https")
                    
                # Check no secrets in schema
                schema_str = json.dumps(schema)
                if "ls_" in schema_str or "key_hash" in schema_str or "token_hash" in schema_str:
                    self.log("   ❌ Found potential secrets in schema", "FAIL")
                    self.tests_failed.append("OpenAPI no secrets")
                else:
                    self.log("   ✅ No secrets in schema", "PASS")
                    self.tests_passed += 1
                    
            except Exception as e:
                self.log(f"   ❌ Error parsing OpenAPI schema: {e}", "FAIL")
                self.tests_failed.append("OpenAPI schema parsing")
                
    def test_secrets_not_leaked(self):
        """Test that secrets are not leaked in responses"""
        self.log("\n=== Test Secrets Not Leaked ===")
        
        # Test status endpoint
        success, r = self.test(
            "GET /api/v2/ai/status (check secrets)",
            "GET",
            "/api/v2/ai/status",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        if success and r:
            text = r.text
            if any(secret in text for secret in ["key_hash", "token_hash", "MONGO_URL", self.api_key]):
                self.log("   ❌ Found secrets in status response", "FAIL")
                self.tests_failed.append("Status secrets leak")
            else:
                self.log("   ✅ No secrets in status response", "PASS")
                self.tests_passed += 1
                
        # Test capabilities endpoint
        success, r = self.test(
            "GET /api/v2/ai/capabilities (check secrets)",
            "GET",
            "/api/v2/ai/capabilities?compact=false",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        if success and r:
            text = r.text
            if any(secret in text for secret in ["key_hash", "token_hash", "MONGO_URL"]):
                self.log("   ❌ Found secrets in capabilities response", "FAIL")
                self.tests_failed.append("Capabilities secrets leak")
            else:
                self.log("   ✅ No secrets in capabilities response", "PASS")
                self.tests_passed += 1
                
    def test_per_key_policy(self):
        """Test per-key capability policies"""
        self.log("\n=== Test Per-Key Capability Policy ===")
        
        # Set capability policy for the key
        success, r = self.test(
            "PATCH /api/v1/auth/keys/{id}/capabilities",
            "PATCH",
            f"/api/v1/auth/keys/{self.api_key_id}/capabilities",
            200,
            headers={"Authorization": f"Bearer {self.admin_jwt}"},
            json_data={
                "capability_allow": ["models.*"],
                "capability_deny": ["models.publish"]
            }
        )
        
        if success:
            # Wait a moment for the policy to take effect
            time.sleep(1)
            
            # Try to preview models.publish (should be denied)
            success, r = self.test(
                "POST /api/v2/ai/preview models.publish (denied)",
                "POST",
                "/api/v2/ai/preview",
                403,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json_data={
                    "action": "models.publish",
                    "target": "francesca-rossi"
                }
            )
            if success and r:
                data = r.json()
                code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
                if code == "CAPABILITY_DENIED":
                    self.log("   ✅ Correct error code: CAPABILITY_DENIED", "PASS")
                    self.tests_passed += 1
                    
            # Try to execute seo.audit (not in allow list, should be denied)
            success, r = self.test(
                "POST /api/v2/ai/execute seo.audit (not allowed)",
                "POST",
                "/api/v2/ai/execute",
                403,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json_data={
                    "action": "seo.audit",
                    "target": "francesca-rossi"
                }
            )
            if success and r:
                data = r.json()
                code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
                if code == "CAPABILITY_NOT_ALLOWED":
                    self.log("   ✅ Correct error code: CAPABILITY_NOT_ALLOWED", "PASS")
                    self.tests_passed += 1
                    
            # Try to execute models.get (should work)
            self.test(
                "POST /api/v2/ai/execute models.get (allowed)",
                "POST",
                "/api/v2/ai/execute",
                200,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json_data={
                    "action": "models.get",
                    "target": "francesca-rossi"
                }
            )
            
            # Check capabilities list is filtered
            success, r = self.test(
                "GET /api/v2/ai/capabilities (filtered)",
                "GET",
                "/api/v2/ai/capabilities",
                200,
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            if success and r:
                data = r.json()
                if data.get("ok") and data.get("data"):
                    caps = data["data"].get("capabilities", [])
                    cap_ids = [c.get("id") for c in caps]
                    
                    # Should have models.* but not models.publish
                    has_models_get = "models.get" in cap_ids
                    has_models_publish = "models.publish" in cap_ids
                    
                    if has_models_get and not has_models_publish:
                        self.log("   ✅ Capabilities correctly filtered", "PASS")
                        self.tests_passed += 1
                    else:
                        self.log("   ❌ Capabilities not correctly filtered", "FAIL")
                        self.tests_failed.append("Capabilities filtering")
                        
            # Reset policy
            self.test(
                "PATCH /api/v1/auth/keys/{id}/capabilities (reset)",
                "PATCH",
                f"/api/v1/auth/keys/{self.api_key_id}/capabilities",
                200,
                headers={"Authorization": f"Bearer {self.admin_jwt}"},
                json_data={
                    "capability_allow": [],
                    "capability_deny": []
                }
            )
            
    def test_admin_governance(self):
        """Test admin governance endpoints"""
        self.log("\n=== Test Admin Governance ===")
        
        # Test with admin JWT (should work)
        success, r = self.test(
            "GET /api/v2/ai/admin/capabilities (admin JWT)",
            "GET",
            "/api/v2/ai/admin/capabilities",
            200,
            headers={"Authorization": f"Bearer {self.admin_jwt}"}
        )
        if success and r:
            data = r.json()
            if data.get("ok") and data.get("data"):
                total = data["data"].get("total", 0)
                bound = data["data"].get("bound", 0)
                unbound = data["data"].get("unbound", [])
                by_risk = data["data"].get("by_risk", {})
                
                self.log(f"   Total: {total}, Bound: {bound}, Unbound: {len(unbound)}")
                self.log(f"   By risk: {json.dumps(by_risk)}")
                
                if total == 104 and bound == 104:
                    self.log("   ✅ Correct counts", "PASS")
                    self.tests_passed += 1
                    
                # Check by_risk
                expected_risk = {"SAFE": 86, "REVIEW_REQUIRED": 11, "CRITICAL": 0}
                if by_risk == expected_risk:
                    self.log("   ✅ Correct risk distribution", "PASS")
                    self.tests_passed += 1
                else:
                    self.log(f"   ❌ Expected {expected_risk}, got {by_risk}", "FAIL")
                    self.tests_failed.append("Admin governance risk distribution")
                    
                # Check keys array doesn't contain key_hash
                keys = data["data"].get("keys", [])
                if keys:
                    if any("key_hash" in k for k in keys):
                        self.log("   ❌ Found key_hash in keys array", "FAIL")
                        self.tests_failed.append("Admin governance key_hash leak")
                    else:
                        self.log("   ✅ No key_hash in keys array", "PASS")
                        self.tests_passed += 1
                        
        # Test with API key (should fail)
        self.test(
            "GET /api/v2/ai/admin/capabilities (API key)",
            "GET",
            "/api/v2/ai/admin/capabilities",
            403,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        
        # Test toggle capability
        success, r = self.test(
            "POST /api/v2/ai/admin/capabilities/toggle (disable)",
            "POST",
            "/api/v2/ai/admin/capabilities/toggle",
            200,
            headers={"Authorization": f"Bearer {self.admin_jwt}"},
            json_data={
                "capability_id": "settings.get",
                "disabled": True
            }
        )
        
        if success:
            time.sleep(1)
            
            # Try to execute settings.get (should be disabled)
            success, r = self.test(
                "POST /api/v2/ai/execute settings.get (disabled)",
                "POST",
                "/api/v2/ai/execute",
                403,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json_data={"action": "settings.get"}
            )
            if success and r:
                data = r.json()
                code = data.get("code") or (data.get("detail", {}) if isinstance(data.get("detail"), dict) else {}).get("code")
                if code == "CAPABILITY_DISABLED":
                    self.log("   ✅ Correct error code: CAPABILITY_DISABLED", "PASS")
                    self.tests_passed += 1
                    
            # Re-enable
            self.test(
                "POST /api/v2/ai/admin/capabilities/toggle (enable)",
                "POST",
                "/api/v2/ai/admin/capabilities/toggle",
                200,
                headers={"Authorization": f"Bearer {self.admin_jwt}"},
                json_data={
                    "capability_id": "settings.get",
                    "disabled": False
                }
            )
            
            time.sleep(1)
            
            # Try again (should work now)
            self.test(
                "POST /api/v2/ai/execute settings.get (re-enabled)",
                "POST",
                "/api/v2/ai/execute",
                200,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json_data={"action": "settings.get"}
            )
            
    def test_v1_regression(self):
        """Test that v1 endpoints still work"""
        self.log("\n=== Test v1 Regression ===")
        
        # Test v1 OpenAPI
        success, r = self.test(
            "GET /api/v1/ai/openapi-chatgpt.json",
            "GET",
            "/api/v1/ai/openapi-chatgpt.json",
            200
        )
        if success and r:
            try:
                schema = r.json()
                paths = schema.get("paths", {})
                operations = []
                for path, methods in paths.items():
                    for method, spec in methods.items():
                        if method in ["get", "post", "put", "patch", "delete"]:
                            op_id = spec.get("operationId")
                            if op_id:
                                operations.append(op_id)
                                
                if len(operations) == 23:
                    self.log("   ✅ v1 has 23 operations", "PASS")
                    self.tests_passed += 1
                else:
                    self.log(f"   ❌ Expected 23 operations, got {len(operations)}", "FAIL")
                    self.tests_failed.append("v1 operations count")
            except:
                pass
                
        # Test v1 capabilities
        self.test(
            "GET /api/v1/ai/capabilities",
            "GET",
            "/api/v1/ai/capabilities",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        
        # Test v1 status
        self.test(
            "GET /api/v1/ai/status",
            "GET",
            "/api/v1/ai/status",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        
        # Test v1 site-health
        self.test(
            "GET /api/v1/ai/site-health",
            "GET",
            "/api/v1/ai/site-health",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        
        # Test v1 command
        self.test(
            "POST /api/v1/ai/command",
            "POST",
            "/api/v1/ai/command",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_data={
                "action": "analytics.query",
                "parameters": {
                    "metric": "model_views",
                    "range": "7g"
                }
            }
        )
        
        # Test public models endpoint
        self.test(
            "GET /api/models",
            "GET",
            "/api/models",
            200
        )
        
        # Test admin keys endpoint
        self.test(
            "GET /api/v1/auth/keys",
            "GET",
            "/api/v1/auth/keys",
            200,
            headers={"Authorization": f"Bearer {self.admin_jwt}"}
        )
        
    def verify_mode_invariant(self):
        """Verify mode is still READ_ONLY at the end"""
        self.log("\n=== Verify Mode Invariant ===")
        
        success, r = self.test(
            "GET /api/v2/ai/status (final check)",
            "GET",
            "/api/v2/ai/status",
            200,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        if success and r:
            data = r.json()
            mode = data.get("data", {}).get("mode")
            if mode == "READ_ONLY":
                self.log("   ✅ Mode is still READ_ONLY", "PASS")
                self.tests_passed += 1
            else:
                self.log(f"   ❌ Mode changed to {mode} (should be READ_ONLY)", "FAIL")
                self.tests_failed.append("Mode invariant")
                
    def revoke_api_key(self):
        """Revoke the temporary API key"""
        self.log("\n=== Revoke API Key ===")
        if self.api_key_id:
            self.test(
                "DELETE /api/v1/auth/keys/{id}",
                "DELETE",
                f"/api/v1/auth/keys/{self.api_key_id}",
                200,
                headers={"Authorization": f"Bearer {self.admin_jwt}"}
            )
            self.log(f"API Key {self.api_key_id} revoked")
            
    def print_summary(self):
        """Print test summary"""
        self.log("\n" + "="*60)
        self.log("TEST SUMMARY")
        self.log("="*60)
        self.log(f"Total tests: {self.tests_run}")
        self.log(f"Passed: {self.tests_passed}")
        self.log(f"Failed: {len(self.tests_failed)}")
        
        if self.tests_failed:
            self.log("\nFailed tests:")
            for test in self.tests_failed:
                self.log(f"  - {test}")
                
        success_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0
        self.log(f"\nSuccess rate: {success_rate:.1f}%")
        
        return len(self.tests_failed) == 0
        
    def run_all_tests(self):
        """Run all tests"""
        self.log("="*60)
        self.log("Phase 12A - Total Site Control API v2 Testing")
        self.log("="*60)
        self.log(f"Base URL: {self.base_url}")
        self.log(f"Started: {datetime.now().isoformat()}")
        self.log("")
        
        try:
            # Setup
            if not self.admin_login():
                self.log("Failed to login as admin, aborting", "ERROR")
                return False
                
            if not self.create_api_key():
                self.log("Failed to create API key, aborting", "ERROR")
                return False
                
            # Run tests
            self.test_v2_capabilities()
            self.test_get_capability()
            self.test_preview()
            self.test_execute_read_only()
            self.test_validation_errors()
            self.test_optimistic_concurrency()
            self.test_models_find()
            self.test_status()
            self.test_analytics_query()
            self.test_approvals()
            self.test_rollback()
            self.test_openapi_chatgpt()
            self.test_secrets_not_leaked()
            self.test_per_key_policy()
            self.test_admin_governance()
            self.test_v1_regression()
            self.verify_mode_invariant()
            
            # Cleanup
            self.revoke_api_key()
            
            # Summary
            return self.print_summary()
            
        except Exception as e:
            self.log(f"Unexpected error: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return False

def _purge_residue():
    """preview hygiene: remove this harness' revoked keys / soft-deleted test entities (never business data)"""
    try:
        import sys as _s2; _s2.path.insert(0, "/app/tests")
        from _cleanup import purge_test_residue as _purge
        print("residue purge:", _purge())
    except Exception as _e:
        print("residue purge skipped:", str(_e)[:100])


if __name__ == "__main__":
    tester = Phase12ATester()
    success = tester.run_all_tests()
    _purge_residue()
    sys.exit(0 if success else 1)
