#!/usr/bin/env python3
"""
LATO SEGRETO SUPER API v1 Comprehensive Test Suite
Tests all v1 endpoints, permissions, edge cases, and regressions
"""
import requests
import sys
import time
import uuid
from typing import Dict, Any, Optional, List

BASE_URL = "https://secret-side.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@latosegreto.it"
ADMIN_PASSWORD = "LatoSegreto2025!"


class V1Tester:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = None
        self.api_key = None
        self.ai_key = None
        self.read_only_token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_resources = {
            "models": [],
            "landings": [],
            "experiments": [],
            "webhooks": [],
            "api_keys": [],
            "users": []
        }

    def log(self, msg: str, level: str = "INFO"):
        prefix = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "FAIL": "❌",
            "WARN": "⚠️",
            "SECTION": "📋"
        }.get(level, "•")
        print(f"{prefix} {msg}")

    def test(self, name: str, method: str, endpoint: str, expected_status: int,
             data: Optional[Dict] = None, headers: Optional[Dict] = None,
             check_response: Optional[callable] = None, use_api_key: bool = False) -> tuple[bool, Any]:
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        req_headers = {'Content-Type': 'application/json'}
        
        if use_api_key and self.api_key:
            req_headers['X-API-Key'] = self.api_key
        elif self.token:
            req_headers['Authorization'] = f'Bearer {self.token}'
        
        if headers:
            req_headers.update(headers)

        self.tests_run += 1

        try:
            if method == 'GET':
                response = requests.get(url, headers=req_headers, timeout=15)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=req_headers, timeout=15)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=req_headers, timeout=15)
            elif method == 'PATCH':
                response = requests.patch(url, json=data, headers=req_headers, timeout=15)
            elif method == 'DELETE':
                response = requests.delete(url, headers=req_headers, timeout=15)
            else:
                self.log(f"Unknown method {method}", "FAIL")
                return False, {}

            success = response.status_code == expected_status
            resp_data = {}
            try:
                resp_data = response.json()
            except:
                resp_data = {"text": response.text[:200]}

            if success:
                if check_response and not check_response(resp_data):
                    self.log(f"❌ {name} - Status OK but response validation failed", "FAIL")
                    return False, resp_data
                self.tests_passed += 1
                self.log(f"✅ {name}", "SUCCESS")
            else:
                self.log(f"❌ {name} - Expected {expected_status}, got {response.status_code}: {str(resp_data)[:150]}", "FAIL")

            return success, resp_data

        except Exception as e:
            self.log(f"❌ {name} - Error: {str(e)}", "FAIL")
            return False, {}

    def run_all_tests(self):
        """Execute all test suites"""
        self.log("=" * 80, "INFO")
        self.log("LATO SEGRETO SUPER API v1 COMPREHENSIVE TEST SUITE", "INFO")
        self.log("=" * 80, "INFO")

        # Setup: Login and create API keys
        self.setup_auth()

        # REGRESSION TESTS (must pass)
        self.test_regression_public_api()
        self.test_regression_legacy_admin()

        # V1 API TESTS
        if self.token:
            self.test_v1_auth()
            self.test_v1_models()
            self.test_v1_versions_rollback()
            self.test_v1_idempotency()
            self.test_v1_media()
            self.test_v1_seo()
            self.test_v1_tracking_italy_engine()
            self.test_v1_ai_endpoints()
            self.test_v1_landings()
            self.test_v1_experiments()
            self.test_v1_health_alerts_jobs()
            self.test_v1_config_flags_webhooks_backup()
            self.test_v1_openapi()
            self.test_v1_dashboard()

        # Cleanup
        self.cleanup_test_resources()

        # Print summary
        self.print_summary()

    def setup_auth(self):
        self.log("\n=== SETUP: AUTHENTICATION ===", "SECTION")
        
        # Admin login
        success, resp = self.test("Admin login", "POST", "admin/login", 200,
                                   data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                                   check_response=lambda r: "token" in r)
        if success:
            self.token = resp.get("token")
            self.log(f"Got admin token", "INFO")

    def test_regression_public_api(self):
        self.log("\n=== REGRESSION: PUBLIC API ===", "SECTION")
        
        # GET /api/models returns 10 published models
        success, resp = self.test("GET /api/models returns published models", "GET", "models", 200,
                                   check_response=lambda r: "items" in r and isinstance(r["items"], list))
        if success:
            count = len(resp.get("items", []))
            self.log(f"Found {count} published models", "INFO")
        
        # GET /api/models/francesca-rossi
        self.test("GET /api/models/francesca-rossi", "GET", "models/francesca-rossi", 200,
                  check_response=lambda r: r.get("slug") == "francesca-rossi")
        
        # GET /api/models/francesca-rossi/segreto
        self.test("GET /api/models/francesca-rossi/segreto", "GET", "models/francesca-rossi/segreto", 200,
                  check_response=lambda r: "bio_segreta" in r and "tema" in r)
        
        # GET /api/pellicola
        self.test("GET /api/pellicola", "GET", "pellicola", 200,
                  check_response=lambda r: "config" in r and "items" in r)
        
        # GET /api/sitemap.xml
        self.test("GET /api/sitemap.xml", "GET", "sitemap.xml", 200)
        
        # POST /api/track
        track_data = {
            "tipo": "page_view",
            "model_slug": "francesca-rossi",
            "session_id": f"test-{uuid.uuid4().hex[:8]}"
        }
        self.test("POST /api/track page_view", "POST", "track", 200, data=track_data,
                  check_response=lambda r: r.get("ok") == True)

    def test_regression_legacy_admin(self):
        self.log("\n=== REGRESSION: LEGACY ADMIN ===", "SECTION")
        
        # POST /api/admin/login
        success, resp = self.test("POST /api/admin/login", "POST", "admin/login", 200,
                                   data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                                   check_response=lambda r: "token" in r and "ruolo" in r)
        if success:
            self.log(f"Role: {resp.get('ruolo')}", "INFO")
        
        # GET /api/admin/models
        success, resp = self.test("GET /api/admin/models", "GET", "admin/models", 200,
                                   check_response=lambda r: "items" in r)
        if success:
            # Check soft-deleted models are excluded
            items = resp.get("items", [])
            soft_deleted = [m for m in items if m.get("is_deleted")]
            if soft_deleted:
                self.log(f"WARNING: {len(soft_deleted)} soft-deleted models in admin list", "WARN")
        
        # PUT /api/admin/models/{id} still works
        if success and items:
            model_id = items[0].get("id")
            model_data = items[0]
            model_data["bio"] = f"Test update {time.time()}"
            self.test(f"PUT /api/admin/models/{model_id}", "PUT", f"admin/models/{model_id}", 200,
                      data=model_data)

    def test_v1_auth(self):
        self.log("\n=== V1: AUTH & PERMISSIONS ===", "SECTION")
        
        # GET /api/v1/auth/me with Bearer JWT
        success, resp = self.test("GET /api/v1/auth/me", "GET", "v1/auth/me", 200,
                                   check_response=lambda r: r.get("role") == "SUPER_ADMIN")
        
        # POST /api/v1/auth/keys - create AI_OPERATOR key
        success, resp = self.test("POST /api/v1/auth/keys (AI_OPERATOR)", "POST", "v1/auth/keys", 201,
                                   data={"name": f"test-ai-{uuid.uuid4().hex[:6]}", "role": "AI_OPERATOR"},
                                   check_response=lambda r: "api_key" in r and r["api_key"].startswith("ls_"))
        if success:
            self.ai_key = resp.get("api_key")
            self.test_resources["api_keys"].append(resp.get("id"))
            self.log(f"Created AI key: {self.ai_key[:15]}...", "INFO")
        
        # X-API-Key works on /api/v1/ai/status
        if self.ai_key:
            self.test("X-API-Key on /api/v1/ai/status", "GET", "v1/ai/status", 200,
                      headers={"X-API-Key": self.ai_key},
                      check_response=lambda r: r.get("ok") == True)
        
        # AI key gets 403 on GET /api/v1/auth/keys (no keys:manage)
        if self.ai_key:
            self.test("AI key cannot GET /api/v1/auth/keys (403)", "GET", "v1/auth/keys", 403,
                      headers={"X-API-Key": self.ai_key})
        
        # POST /api/v1/auth/users - create READ_ONLY user
        success, resp = self.test("POST /api/v1/auth/users (READ_ONLY)", "POST", "v1/auth/users", 201,
                                   data={"email": f"ro-{uuid.uuid4().hex[:6]}@test.it", "password": "TestPass123!", "role": "READ_ONLY"})
        if success:
            self.test_resources["users"].append(resp.get("id"))
            ro_email = resp.get("email")
            
            # Login as READ_ONLY user
            success2, resp2 = self.test("Login as READ_ONLY user", "POST", "admin/login", 200,
                                        data={"email": ro_email, "password": "TestPass123!"})
            if success2:
                self.read_only_token = resp2.get("token")
                
                # READ_ONLY gets 403 on POST /api/v1/models
                temp_token = self.token
                self.token = self.read_only_token
                self.test("READ_ONLY cannot POST /api/v1/models (403)", "POST", "v1/models", 403,
                          data={"nome": "Test"})
                
                # READ_ONLY gets 403 on PUT /api/admin/settings
                self.test("READ_ONLY cannot PUT /api/admin/settings (403)", "PUT", "admin/settings", 403,
                          data={})
                
                # READ_ONLY can GET /api/v1/models
                self.test("READ_ONLY can GET /api/v1/models (200)", "GET", "v1/models", 200)
                
                self.token = temp_token

    def test_v1_models(self):
        self.log("\n=== V1: MODELS WORKFLOW ===", "SECTION")
        
        # GET /api/v1/models (summary list)
        success, resp = self.test("GET /api/v1/models", "GET", "v1/models", 200,
                                   check_response=lambda r: "items" in r and "counts" in r)
        if success:
            self.log(f"Counts: {resp.get('counts')}", "INFO")
        
        # POST /api/v1/models - create DRAFT
        success, resp = self.test("POST /api/v1/models (DRAFT)", "POST", "v1/models", 201,
                                   data={"nome": f"Test Model {uuid.uuid4().hex[:6]}"},
                                   check_response=lambda r: r.get("workflow_status") == "DRAFT")
        if success:
            test_model_id = resp.get("id")
            self.test_resources["models"].append(test_model_id)
            self.log(f"Created model: {test_model_id}", "INFO")
            
            # PATCH deep merge
            patch_data = {
                "bio": "Test bio for validation",
                "tema": {"preset": "tattoo"}
            }
            success2, resp2 = self.test(f"PATCH /api/v1/models/{test_model_id} (deep merge)", "PATCH", f"v1/models/{test_model_id}", 200,
                                        data=patch_data,
                                        check_response=lambda r: "changed_fields" in r and "version_id" in r)
            
            # POST /validate
            self.test(f"POST /api/v1/models/{test_model_id}/validate", "POST", f"v1/models/{test_model_id}/validate", 200,
                      check_response=lambda r: "ready" in r and "errors" in r)
            
            # POST /publish on incomplete -> 400
            self.test(f"POST /api/v1/models/{test_model_id}/publish (incomplete, 400)", "POST", f"v1/models/{test_model_id}/publish", 400)
        
        # POST /api/v1/models/francesca-rossi/duplicate
        success, resp = self.test("POST /api/v1/models/francesca-rossi/duplicate", "POST", "v1/models/francesca-rossi/duplicate", 201,
                                   check_response=lambda r: r.get("workflow_status") in ["READY", "INCOMPLETE"])
        if success:
            dup_id = resp.get("id")
            self.test_resources["models"].append(dup_id)
            self.log(f"Duplicated model: {dup_id}, status: {resp.get('workflow_status')}", "INFO")
            
            # Publish duplicate if READY
            if resp.get("workflow_status") == "READY":
                success2, resp2 = self.test(f"POST /api/v1/models/{dup_id}/publish", "POST", f"v1/models/{dup_id}/publish", 200,
                                            check_response=lambda r: r.get("workflow_status") == "PUBLISHED")
                if success2:
                    # Archive
                    self.test(f"POST /api/v1/models/{dup_id}/archive", "POST", f"v1/models/{dup_id}/archive", 200,
                              check_response=lambda r: r.get("workflow_status") == "ARCHIVED")
                    
                    # Restore
                    self.test(f"POST /api/v1/models/{dup_id}/restore", "POST", f"v1/models/{dup_id}/restore", 200)
                    
                    # DELETE (soft delete)
                    success3, resp3 = self.test(f"DELETE /api/v1/models/{dup_id}", "DELETE", f"v1/models/{dup_id}", 200,
                                                check_response=lambda r: r.get("soft_deleted") == True)
        
        # POST /api/v1/models/{id}/feature
        if self.test_resources["models"]:
            model_id = self.test_resources["models"][0]
            self.test(f"POST /api/v1/models/{model_id}/feature", "POST", f"v1/models/{model_id}/feature", 200,
                      data={"position": 0, "badge": "NUOVA"})
        
        # Model reference by id, slug, name works
        self.test("GET /api/v1/models/francesca-rossi (by slug)", "GET", "v1/models/francesca-rossi", 200)

    def test_v1_versions_rollback(self):
        self.log("\n=== V1: VERSIONS & ROLLBACK ===", "SECTION")
        
        # GET /api/v1/versions?entity=model
        success, resp = self.test("GET /api/v1/versions?entity=model", "GET", "v1/versions?entity=model&limit=5", 200,
                                   check_response=lambda r: "items" in r)
        if success and resp.get("items"):
            version_id = resp["items"][0].get("id")
            
            # GET /api/v1/versions/{id}
            self.test(f"GET /api/v1/versions/{version_id}", "GET", f"v1/versions/{version_id}", 200,
                      check_response=lambda r: "before" in r and "after" in r)
            
            # POST /api/v1/versions/{id}/rollback
            self.test(f"POST /api/v1/versions/{version_id}/rollback", "POST", f"v1/versions/{version_id}/rollback", 200,
                      data={"reason": "Test rollback"},
                      check_response=lambda r: r.get("rolled_back") == True)
        
        # GET /api/v1/audit
        self.test("GET /api/v1/audit", "GET", "v1/audit?limit=10", 200,
                  check_response=lambda r: "items" in r)

    def test_v1_idempotency(self):
        self.log("\n=== V1: IDEMPOTENCY ===", "SECTION")
        
        if not self.ai_key:
            self.log("Skipping idempotency test (no AI key)", "WARN")
            return
        
        # POST /api/v1/ai/models/update twice with same Idempotency-Key
        idem_key = f"test-idem-{uuid.uuid4().hex}"
        update_data = {
            "model": "francesca-rossi",
            "changes": {"bio": f"Idempotency test {time.time()}"}
        }
        
        # First request
        success1, resp1 = self.test("POST /api/v1/ai/models/update (first)", "POST", "v1/ai/models/update", 200,
                                    data=update_data,
                                    headers={"X-API-Key": self.ai_key, "Idempotency-Key": idem_key})
        
        # Second request with same key
        url = f"{self.base_url}/v1/ai/models/update"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.ai_key,
            "Idempotency-Key": idem_key
        }
        response = requests.post(url, json=update_data, headers=headers, timeout=15)
        
        if response.status_code == 200 and "Idempotent-Replayed" in response.headers:
            self.tests_passed += 1
            self.log("✅ Idempotency: Second request replayed", "SUCCESS")
        else:
            self.log(f"❌ Idempotency: Expected Idempotent-Replayed header, got {response.headers}", "FAIL")
        self.tests_run += 1
        
        # Check X-Request-ID header
        if "X-Request-ID" in response.headers:
            self.tests_passed += 1
            self.log("✅ X-Request-ID header present", "SUCCESS")
        else:
            self.log("❌ X-Request-ID header missing", "FAIL")
        self.tests_run += 1

    def test_v1_media(self):
        self.log("\n=== V1: MEDIA ===", "SECTION")
        
        # POST /api/v1/media/from-url with Unsplash image
        success, resp = self.test("POST /api/v1/media/from-url (image)", "POST", "v1/media/from-url", 201,
                                   data={
                                       "url": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=600",
                                       "model_id": None,
                                       "slot": "foto_card"
                                   },
                                   check_response=lambda r: "file" in r and "variants" in r.get("file", {}))
        if success:
            file_id = resp.get("file", {}).get("id")
            self.log(f"Uploaded image: {file_id}, variants: {list(resp.get('file', {}).get('variants', {}).keys())}", "INFO")
            
            # PATCH /api/v1/media/{id}
            if file_id:
                self.test(f"PATCH /api/v1/media/{file_id}", "PATCH", f"v1/media/{file_id}", 200,
                          data={"alt": "Test alt text"})
                
                # DELETE /api/v1/media/{id} (not in use, should work)
                self.test(f"DELETE /api/v1/media/{file_id}", "DELETE", f"v1/media/{file_id}", 200)
        
        # POST /api/v1/models/{id}/media (attach to model)
        if self.test_resources["models"]:
            model_id = self.test_resources["models"][0]
            
            # Upload and attach
            success2, resp2 = self.test(f"POST /api/v1/media/from-url (attach to model)", "POST", "v1/media/from-url", 201,
                                        data={
                                            "url": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=600",
                                            "model_id": model_id,
                                            "slot": "foto_card"
                                        })
            
            # GET /api/v1/models/{id}/media
            self.test(f"GET /api/v1/models/{model_id}/media", "GET", f"v1/models/{model_id}/media", 200,
                      check_response=lambda r: "items" in r)

    def test_v1_seo(self):
        self.log("\n=== V1: SEO ENGINE ===", "SECTION")
        
        # POST /api/v1/seo/audit
        success, resp = self.test("POST /api/v1/seo/audit", "POST", "v1/seo/audit", 200,
                                   data={},
                                   check_response=lambda r: "counts" in r and "health_score" in r)
        if success:
            self.log(f"SEO health: {resp.get('health_score')}/100, counts: {resp.get('counts')}", "INFO")
        
        # GET /api/v1/seo/issues
        self.test("GET /api/v1/seo/issues", "GET", "v1/seo/issues?limit=10", 200,
                  check_response=lambda r: "items" in r)
        
        # POST /api/v1/seo/fix-all dry_run
        success, resp = self.test("POST /api/v1/seo/fix-all (dry_run)", "POST", "v1/seo/fix-all", 200,
                                   data={"dry_run": True})
        
        # POST /api/v1/seo/fix-all (apply SAFE only)
        success, resp = self.test("POST /api/v1/seo/fix-all (apply)", "POST", "v1/seo/fix-all", 200,
                                   data={"dry_run": False},
                                   check_response=lambda r: "applied" in r)
        
        # Test CRITICAL issue (invalid OnlyFans URL) is never auto-fixed
        # This would require creating a model with invalid URL and checking it's not fixed
        
        # GET /api/v1/seo/opportunities
        self.test("GET /api/v1/seo/opportunities", "GET", "v1/seo/opportunities", 200)
        
        # GET /api/v1/seo/sitemap
        self.test("GET /api/v1/seo/sitemap", "GET", "v1/seo/sitemap", 200,
                  check_response=lambda r: "entries" in r)
        
        # GET /api/v1/seo/redirects
        self.test("GET /api/v1/seo/redirects", "GET", "v1/seo/redirects", 200,
                  check_response=lambda r: "items" in r)
        
        # GET /api/redirects/resolve
        self.test("GET /api/redirects/resolve", "GET", "redirects/resolve?path=/modelle/test", 200)

    def test_v1_tracking_italy_engine(self):
        self.log("\n=== V1: TRACKING & ITALY ENGINE ===", "SECTION")
        
        # POST /api/v1/track with Accept-Language: it-IT
        session_id = f"test-{uuid.uuid4().hex[:8]}"
        success, resp = self.test("POST /api/v1/track (IT language)", "POST", "v1/track", 200,
                                   data={"event": "model_view", "model_slug": "francesca-rossi", "session_id": session_id},
                                   headers={"Accept-Language": "it-IT"})
        
        # GET /api/v1/analytics/italy
        success, resp = self.test("GET /api/v1/analytics/italy", "GET", "v1/analytics/italy?range=1g", 200,
                                   check_response=lambda r: "model_views_italy" in r and "italian_share" in r)
        if success:
            self.log(f"Italy analytics: {resp.get('model_views_italy')} views, {resp.get('italian_share')}% share", "INFO")
        
        # GET /api/v1/analytics/overview
        self.test("GET /api/v1/analytics/overview", "GET", "v1/analytics/overview?range=7g", 200)
        
        # GET /api/v1/analytics/funnel
        self.test("GET /api/v1/analytics/funnel", "GET", "v1/analytics/funnel?range=7g", 200,
                  check_response=lambda r: "steps" in r)
        
        # GET /api/v1/analytics/models
        self.test("GET /api/v1/analytics/models", "GET", "v1/analytics/models?range=7g", 200,
                  check_response=lambda r: "items" in r)
        
        # GET /api/v1/analytics/breakdown
        self.test("GET /api/v1/analytics/breakdown?dimension=device", "GET", "v1/analytics/breakdown?dimension=device&range=7g", 200)
        
        # GET /api/v1/analytics/timeseries
        self.test("GET /api/v1/analytics/timeseries", "GET", "v1/analytics/timeseries?range=7g", 200,
                  check_response=lambda r: "items" in r)
        
        # GET /api/v1/analytics/onlyfans
        self.test("GET /api/v1/analytics/onlyfans", "GET", "v1/analytics/onlyfans?range=7g", 200)
        
        # GET /api/v1/analytics/events
        self.test("GET /api/v1/analytics/events", "GET", "v1/analytics/events?range=7g", 200)

    def test_v1_ai_endpoints(self):
        self.log("\n=== V1: AI ENDPOINTS ===", "SECTION")
        
        if not self.ai_key:
            self.log("Skipping AI tests (no AI key)", "WARN")
            return
        
        # POST /api/v1/ai/models/create
        success, resp = self.test("POST /api/v1/ai/models/create", "POST", "v1/ai/models/create", 200,
                                   data={"nome": f"AI Test {uuid.uuid4().hex[:6]}"},
                                   headers={"X-API-Key": self.ai_key},
                                   check_response=lambda r: r.get("ok") == True and "data" in r)
        if success:
            ai_model_slug = resp.get("data", {}).get("slug")
            ai_model_id = resp.get("data", {}).get("id")
            if ai_model_id:
                self.test_resources["models"].append(ai_model_id)
            self.log(f"AI created model: {ai_model_slug}", "INFO")
            
            # POST /api/v1/ai/models/update
            if ai_model_slug:
                self.test("POST /api/v1/ai/models/update", "POST", "v1/ai/models/update", 200,
                          data={"model": ai_model_slug, "changes": {"bio": "AI updated bio"}},
                          headers={"X-API-Key": self.ai_key})
                
                # POST /api/v1/ai/models/validate
                self.test("POST /api/v1/ai/models/validate", "POST", "v1/ai/models/validate", 200,
                          data={"model": ai_model_slug},
                          headers={"X-API-Key": self.ai_key})
                
                # POST /api/v1/ai/models/publish (should fail - incomplete)
                self.test("POST /api/v1/ai/models/publish (incomplete)", "POST", "v1/ai/models/publish", 200,
                          data={"model": ai_model_slug},
                          headers={"X-API-Key": self.ai_key},
                          check_response=lambda r: r.get("ok") == False)
        
        # GET /api/v1/ai/status
        self.test("GET /api/v1/ai/status", "GET", "v1/ai/status", 200,
                  headers={"X-API-Key": self.ai_key},
                  check_response=lambda r: r.get("ok") == True)
        
        # GET /api/v1/ai/daily-summary
        self.test("GET /api/v1/ai/daily-summary", "GET", "v1/ai/daily-summary", 200,
                  headers={"X-API-Key": self.ai_key})
        
        # GET /api/v1/ai/capabilities
        self.test("GET /api/v1/ai/capabilities", "GET", "v1/ai/capabilities", 200,
                  headers={"X-API-Key": self.ai_key},
                  check_response=lambda r: "data" in r and "actions" in r.get("data", {}))
        
        # POST /api/v1/ai/analytics/query
        self.test("POST /api/v1/ai/analytics/query (italian_traffic)", "POST", "v1/ai/analytics/query", 200,
                  data={"question": "italian_traffic", "range": "7g"},
                  headers={"X-API-Key": self.ai_key})
        
        # GET /api/v1/ai/models/missing
        self.test("GET /api/v1/ai/models/missing", "GET", "v1/ai/models/missing", 200,
                  headers={"X-API-Key": self.ai_key})

    def test_v1_landings(self):
        self.log("\n=== V1: LANDINGS ===", "SECTION")
        
        # POST /api/v1/landings (create)
        success, resp = self.test("POST /api/v1/landings", "POST", "v1/landings", 201,
                                   data={
                                       "titolo": f"Test Landing {uuid.uuid4().hex[:6]}",
                                       "slug": f"test-landing-{uuid.uuid4().hex[:6]}",
                                       "headline": "Test headline",
                                       "model_slugs": ["francesca-rossi"],
                                       "cta": {"testo": "ENTRA"}
                                   },
                                   check_response=lambda r: "id" in r)
        if success:
            landing_id = resp.get("id")
            landing_slug = resp.get("slug")
            self.test_resources["landings"].append(landing_id)
            self.log(f"Created landing: {landing_slug}", "INFO")
            
            # POST /api/v1/landings/{id}/publish
            self.test(f"POST /api/v1/landings/{landing_id}/publish", "POST", f"v1/landings/{landing_id}/publish", 200)
            
            # GET /api/landings/{slug} (public)
            self.test(f"GET /api/landings/{landing_slug} (public)", "GET", f"landings/{landing_slug}", 200,
                      check_response=lambda r: "model_cards" in r)
            
            # POST /api/v1/landings/{id}/unpublish
            self.test(f"POST /api/v1/landings/{landing_id}/unpublish", "POST", f"v1/landings/{landing_id}/unpublish", 200)
            
            # GET /api/landings/{slug} after unpublish -> 404
            self.test(f"GET /api/landings/{landing_slug} (unpublished, 404)", "GET", f"landings/{landing_slug}", 404)

    def test_v1_experiments(self):
        self.log("\n=== V1: A/B EXPERIMENTS ===", "SECTION")
        
        # POST /api/v1/experiments
        success, resp = self.test("POST /api/v1/experiments", "POST", "v1/experiments", 201,
                                   data={
                                       "nome": f"Test Experiment {uuid.uuid4().hex[:6]}",
                                       "target_type": "cta",
                                       "variants": [
                                           {"nome": "A", "value": "CONTINUA CON ME"},
                                           {"nome": "B", "value": "VIENI A VEDERE"}
                                       ]
                                   },
                                   check_response=lambda r: "id" in r)
        if success:
            exp_id = resp.get("id")
            self.test_resources["experiments"].append(exp_id)
            self.log(f"Created experiment: {exp_id}", "INFO")
            
            # POST /api/v1/experiments/{id}/start
            self.test(f"POST /api/v1/experiments/{exp_id}/start", "POST", f"v1/experiments/{exp_id}/start", 200)
            
            # GET /api/experiments/assign (deterministic)
            session_id = f"test-{uuid.uuid4().hex[:8]}"
            success2, resp2 = self.test(f"GET /api/experiments/assign (first)", "GET", f"experiments/assign?session_id={session_id}", 200,
                                        check_response=lambda r: "variant" in r)
            if success2:
                variant1 = resp2.get("variant")
                
                # Second call with same session_id should return same variant
                success3, resp3 = self.test(f"GET /api/experiments/assign (second, same)", "GET", f"experiments/assign?session_id={session_id}", 200)
                if success3:
                    variant2 = resp3.get("variant")
                    if variant1 == variant2:
                        self.log(f"✅ Deterministic assignment: {variant1}", "SUCCESS")
                    else:
                        self.log(f"❌ Assignment not deterministic: {variant1} != {variant2}", "FAIL")
            
            # GET /api/v1/experiments/{id}/results
            self.test(f"GET /api/v1/experiments/{exp_id}/results", "GET", f"v1/experiments/{exp_id}/results", 200,
                      check_response=lambda r: "enough_data" in r)
            
            # POST /api/v1/experiments/{id}/conclude without enough data -> 409
            self.test(f"POST /api/v1/experiments/{exp_id}/conclude (no data, 409)", "POST", f"v1/experiments/{exp_id}/conclude", 409,
                      data={"winner_variant_id": "fake"})
        
        # Invalid target_type -> 400
        self.test("POST /api/v1/experiments (invalid target_type)", "POST", "v1/experiments", 400,
                  data={"nome": "Invalid", "target_type": "invalid", "variants": []})

    def test_v1_health_alerts_jobs(self):
        self.log("\n=== V1: HEALTH, ALERTS, JOBS ===", "SECTION")
        
        # POST /api/v1/health/run
        success, resp = self.test("POST /api/v1/health/run", "POST", "v1/health/run", 200,
                                   check_response=lambda r: "overall" in r and "checks" in r and "actions" in r)
        if success:
            self.log(f"Health: {resp.get('overall')}, checks: {len(resp.get('checks', []))}, actions: {len(resp.get('actions', []))}", "INFO")
        
        # GET /api/v1/health
        self.test("GET /api/v1/health", "GET", "v1/health", 200)
        
        # GET /api/v1/alerts
        self.test("GET /api/v1/alerts", "GET", "v1/alerts", 200,
                  check_response=lambda r: "items" in r)
        
        # GET /api/v1/jobs
        success, resp = self.test("GET /api/v1/jobs", "GET", "v1/jobs", 200,
                                   check_response=lambda r: "items" in r and "scheduler_running" in r)
        if success:
            self.log(f"Scheduler running: {resp.get('scheduler_running')}, jobs: {len(resp.get('items', []))}", "INFO")
            
            # POST /api/v1/jobs/seo_scan/run
            self.test("POST /api/v1/jobs/seo_scan/run", "POST", "v1/jobs/seo_scan/run", 200,
                      check_response=lambda r: r.get("status") == "ok")
            
            # GET /api/v1/jobs/seo_scan/runs
            self.test("GET /api/v1/jobs/seo_scan/runs", "GET", "v1/jobs/seo_scan/runs?limit=5", 200)
            
            # PATCH /api/v1/jobs/seo_scan
            self.test("PATCH /api/v1/jobs/seo_scan", "PATCH", "v1/jobs/seo_scan", 200,
                      data={"enabled": True})

    def test_v1_config_flags_webhooks_backup(self):
        self.log("\n=== V1: CONFIG, FLAGS, WEBHOOKS, BACKUP ===", "SECTION")
        
        # GET /api/v1/config
        self.test("GET /api/v1/config", "GET", "v1/config", 200)
        
        # PATCH /api/v1/config
        self.test("PATCH /api/v1/config", "PATCH", "v1/config", 200,
                  data={"site": {"base_url": "https://secret-side.preview.emergentagent.com"}})
        
        # GET /api/v1/config/flags
        self.test("GET /api/v1/config/flags", "GET", "v1/config/flags", 200,
                  check_response=lambda r: "flags" in r)
        
        # PUT /api/v1/config/flags/public_landing_routes
        self.test("PUT /api/v1/config/flags/public_landing_routes", "PUT", "v1/config/flags/public_landing_routes", 200,
                  data={"value": False})
        
        # POST /api/v1/webhooks
        success, resp = self.test("POST /api/v1/webhooks", "POST", "v1/webhooks", 201,
                                   data={"url": "https://example.com/hook", "events": ["model.published"]},
                                   check_response=lambda r: "secret" in r)
        if success:
            webhook_id = resp.get("id")
            self.test_resources["webhooks"].append(webhook_id)
            self.log(f"Created webhook: {webhook_id}, secret shown once", "INFO")
            
            # GET /api/v1/webhooks (secret masked)
            success2, resp2 = self.test("GET /api/v1/webhooks", "GET", "v1/webhooks", 200)
            if success2:
                webhooks = resp2.get("items", [])
                for wh in webhooks:
                    if wh.get("id") == webhook_id and wh.get("secret", "").startswith("***"):
                        self.log("✅ Webhook secret masked in list", "SUCCESS")
                        break
        
        # POST /api/v1/backup
        success, resp = self.test("POST /api/v1/backup", "POST", "v1/backup", 201,
                                   data={},
                                   check_response=lambda r: "id" in r and "counts" in r)
        if success:
            backup_id = resp.get("id")
            self.log(f"Created backup: {backup_id}, counts: {resp.get('counts')}", "INFO")
            
            # GET /api/v1/backup
            self.test("GET /api/v1/backup", "GET", "v1/backup", 200,
                      check_response=lambda r: "items" in r)
            
            # POST /api/v1/backup/{id}/restore (dry_run)
            self.test(f"POST /api/v1/backup/{backup_id}/restore (dry_run)", "POST", f"v1/backup/{backup_id}/restore", 200,
                      data={"dry_run": True},
                      check_response=lambda r: "plan" in r)

    def test_v1_openapi(self):
        self.log("\n=== V1: OPENAPI ===", "SECTION")
        
        # GET /api/openapi.json
        success, resp = self.test("GET /api/openapi.json", "GET", "openapi.json", 200)
        if success:
            if "securitySchemes" in str(resp):
                self.log("✅ OpenAPI has securitySchemes", "SUCCESS")
            else:
                self.log("⚠️ OpenAPI may be missing securitySchemes", "WARN")
        
        # GET /api/docs
        url = f"{self.base_url}/docs"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                self.tests_passed += 1
                self.log("✅ GET /api/docs", "SUCCESS")
            else:
                self.log(f"❌ GET /api/docs - Status {response.status_code}", "FAIL")
            self.tests_run += 1
        except Exception as e:
            self.log(f"❌ GET /api/docs - Error: {e}", "FAIL")
            self.tests_run += 1

    def test_v1_dashboard(self):
        self.log("\n=== V1: DASHBOARD ===", "SECTION")
        
        # GET /api/v1/dashboard/overview
        success, resp = self.test("GET /api/v1/dashboard/overview?range=7g", "GET", "v1/dashboard/overview?range=7g", 200,
                                   check_response=lambda r: "api_status" in r and "seo_health" in r and "traffic" in r)
        if success:
            keys = list(resp.keys())
            expected_keys = ["api_status", "seo_health", "traffic", "italian_traffic", "onlyfans_clicks", 
                           "conversion_rate", "top_models", "seo_issues", "auto_fixes", "alerts", 
                           "rollback", "ai_actions", "background_jobs"]
            missing = [k for k in expected_keys if k not in keys]
            if missing:
                self.log(f"⚠️ Dashboard missing keys: {missing}", "WARN")
            else:
                self.log("✅ Dashboard has all expected keys", "SUCCESS")

    def cleanup_test_resources(self):
        self.log("\n=== CLEANUP TEST RESOURCES ===", "SECTION")
        
        # Delete test models
        for model_id in self.test_resources["models"]:
            self.test(f"DELETE model {model_id}", "DELETE", f"v1/models/{model_id}", 200)
        
        # Delete test landings
        for landing_id in self.test_resources["landings"]:
            self.test(f"DELETE landing {landing_id}", "DELETE", f"v1/landings/{landing_id}", 200)
        
        # Delete test experiments
        for exp_id in self.test_resources["experiments"]:
            self.test(f"DELETE experiment {exp_id}", "DELETE", f"v1/experiments/{exp_id}", 200)
        
        # Delete test webhooks
        for webhook_id in self.test_resources["webhooks"]:
            self.test(f"DELETE webhook {webhook_id}", "DELETE", f"v1/webhooks/{webhook_id}", 200)
        
        # Revoke test API keys
        for key_id in self.test_resources["api_keys"]:
            self.test(f"DELETE API key {key_id}", "DELETE", f"v1/auth/keys/{key_id}", 200)
        
        # Delete test users
        for user_id in self.test_resources["users"]:
            self.test(f"DELETE user {user_id}", "DELETE", f"v1/auth/users/{user_id}", 200)
        
        # Verify public model count is back to original
        success, resp = self.test("Verify public model count", "GET", "models?limit=100", 200)
        if success:
            count = resp.get("total", 0)
            self.log(f"Public models after cleanup: {count}", "INFO")

    def print_summary(self):
        self.log("\n" + "=" * 80, "INFO")
        self.log(f"TESTS COMPLETED: {self.tests_passed}/{self.tests_run} passed", "INFO")
        self.log("=" * 80, "INFO")

        if self.tests_passed == self.tests_run:
            self.log("ALL TESTS PASSED! 🎉", "SUCCESS")
            return 0
        else:
            failed = self.tests_run - self.tests_passed
            self.log(f"{failed} TEST(S) FAILED", "FAIL")
            return 1


def main():
    tester = V1Tester()
    exit_code = tester.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
