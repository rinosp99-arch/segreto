#!/usr/bin/env python3
"""
LATO SEGRETO Backend API Test Suite
Tests all public, admin, analytics, and integration endpoints
"""
import requests
import sys
import time
from typing import Dict, Any, Optional

BASE_URL = "https://secret-side.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@latosegreto.it"
ADMIN_PASSWORD = "LatoSegreto2025!"
WEBHOOK_KEY = "soro_webhook_7b1e9d4c8a2f4e6b90c1d2e3f4a5b6c7"


class LatoSegretoTester:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_model_slug = None
        self.test_category_slug = None
        self.test_article_slug = None

    def log(self, msg: str, level: str = "INFO"):
        prefix = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "FAIL": "❌",
            "WARN": "⚠️"
        }.get(level, "•")
        print(f"{prefix} {msg}")

    def test(self, name: str, method: str, endpoint: str, expected_status: int,
             data: Optional[Dict] = None, headers: Optional[Dict] = None,
             check_response: Optional[callable] = None) -> tuple[bool, Any]:
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        req_headers = {'Content-Type': 'application/json'}
        if self.token:
            req_headers['Authorization'] = f'Bearer {self.token}'
        if headers:
            req_headers.update(headers)

        self.tests_run += 1
        self.log(f"Testing {name}...", "INFO")

        try:
            if method == 'GET':
                response = requests.get(url, headers=req_headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=req_headers, timeout=10)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=req_headers, timeout=10)
            elif method == 'PATCH':
                response = requests.patch(url, json=data, headers=req_headers, timeout=10)
            elif method == 'DELETE':
                response = requests.delete(url, headers=req_headers, timeout=10)
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
                    self.log(f"FAILED - Status OK but response validation failed", "FAIL")
                    return False, resp_data
                self.tests_passed += 1
                self.log(f"PASSED - Status: {response.status_code}", "SUCCESS")
            else:
                self.log(f"FAILED - Expected {expected_status}, got {response.status_code}: {resp_data}", "FAIL")

            return success, resp_data

        except Exception as e:
            self.log(f"FAILED - Error: {str(e)}", "FAIL")
            return False, {}

    def run_all_tests(self):
        """Execute all test suites"""
        self.log("=" * 60, "INFO")
        self.log("LATO SEGRETO Backend API Test Suite", "INFO")
        self.log("=" * 60, "INFO")

        # 1. Public endpoints
        self.test_public_endpoints()

        # 2. Admin authentication
        self.test_admin_auth()

        # 3. Admin CRUD operations (requires auth)
        if self.token:
            self.test_admin_models()
            self.test_admin_categories()
            self.test_admin_articles()
            self.test_admin_settings()
            self.test_admin_audit()
            self.test_analytics()
            # NEW: Auto-bozza and bulk copy tests
            self.test_auto_bozza_feature()
            self.test_copy_config_bulk_feature()
        else:
            self.log("Skipping admin tests - no auth token", "WARN")

        # 4. Integrations
        self.test_integrations()

        # 5. SEO endpoints
        self.test_seo_endpoints()

        # Print summary
        self.print_summary()

    def test_public_endpoints(self):
        self.log("\n--- PUBLIC ENDPOINTS ---", "INFO")

        # Health check
        self.test("Health check", "GET", "health", 200,
                  check_response=lambda r: r.get("status") == "ok")

        # List models - all filters
        success, resp = self.test("List models (tutte)", "GET", "models?filtro=tutte", 200,
                                   check_response=lambda r: "items" in r and isinstance(r["items"], list))
        if success and resp.get("items"):
            self.test_model_slug = resp["items"][0].get("slug")
            self.log(f"Found test model: {self.test_model_slug}", "INFO")

        self.test("List models (nuove)", "GET", "models?filtro=nuove", 200)
        self.test("List models (piu-viste)", "GET", "models?filtro=piu-viste", 200)
        self.test("List models (in-tendenza)", "GET", "models?filtro=in-tendenza", 200)
        self.test("List models with search", "GET", "models?q=test", 200)

        # Get specific model
        if self.test_model_slug:
            self.test(f"Get model {self.test_model_slug}", "GET", f"models/{self.test_model_slug}", 200,
                      check_response=lambda r: r.get("slug") == self.test_model_slug)

            # Secret side
            self.test(f"Get model secret side", "GET", f"models/{self.test_model_slug}/segreto", 200,
                      check_response=lambda r: "media_pairs" in r and "tema" in r and "messaggio_35s" in r)

            # Related models
            self.test(f"Get related models", "GET", f"models/{self.test_model_slug}/correlate", 200,
                      check_response=lambda r: "items" in r)

        # Surprise
        success, resp = self.test("Surprise endpoint", "GET", "surprise", 200,
                                   check_response=lambda r: "slug" in r)

        # Categories
        success, resp = self.test("List categories", "GET", "categories", 200,
                                   check_response=lambda r: "items" in r)
        if success and resp.get("items"):
            self.test_category_slug = resp["items"][0].get("slug")
            if self.test_category_slug:
                self.test(f"Get category {self.test_category_slug}", "GET", f"categories/{self.test_category_slug}", 200,
                          check_response=lambda r: "categoria" in r and "items" in r)

        # Articles
        success, resp = self.test("List articles", "GET", "articles", 200,
                                   check_response=lambda r: "items" in r)
        if success and resp.get("items"):
            self.test_article_slug = resp["items"][0].get("slug")
            if self.test_article_slug:
                self.test(f"Get article {self.test_article_slug}", "GET", f"articles/{self.test_article_slug}", 200,
                          check_response=lambda r: r.get("slug") == self.test_article_slug)

        # Settings
        self.test("Public settings", "GET", "settings", 200,
                  check_response=lambda r: "brand_name" in r)

        # Track event
        track_data = {
            "tipo": "page_view",
            "model_slug": self.test_model_slug or "test",
            "session_id": "test-session-123"
        }
        self.test("Track page_view event", "POST", "track", 200, data=track_data,
                  check_response=lambda r: r.get("ok") == True)

        # Track secret_activate with valore
        track_secret = {
            "tipo": "secret_activate",
            "model_slug": self.test_model_slug or "test",
            "valore": 5.2,
            "session_id": "test-session-123"
        }
        self.test("Track secret_activate event", "POST", "track", 200, data=track_secret)

        # NEW: Pellicola endpoint
        success, resp = self.test("Get pellicola config and items", "GET", "pellicola", 200,
                                   check_response=lambda r: "config" in r and "items" in r)
        if success:
            config = resp.get("config", {})
            items = resp.get("items", [])
            self.log(f"Pellicola config: attiva={config.get('attiva')}, max_video_attivi={config.get('max_video_attivi')}, items={len(items)}", "INFO")
            
            # Validate config structure
            if not isinstance(config.get("attiva"), bool):
                self.log("Pellicola config.attiva should be boolean", "WARN")
            if not isinstance(config.get("max_video_attivi"), int) or config.get("max_video_attivi", 0) < 4:
                self.log("Pellicola config.max_video_attivi should be int >= 4", "WARN")
            
            # Validate items structure
            for idx, item in enumerate(items[:3]):  # Check first 3 items
                if not item.get("slug"):
                    self.log(f"Pellicola item {idx} missing slug", "WARN")
                if not item.get("pubblico", {}).get("video_url") and not item.get("pubblico", {}).get("poster_url"):
                    self.log(f"Pellicola item {idx} missing pubblico video/poster", "WARN")
                if not item.get("segreto", {}).get("video_url") and not item.get("segreto", {}).get("poster_url"):
                    self.log(f"Pellicola item {idx} missing segreto video/poster", "WARN")

        # NEW: Track pellicola events
        track_pellicola_impression = {
            "tipo": "pellicola_impression",
            "session_id": "test-session-123",
            "cta_source": "pubblico",
            "meta": {"count": 10}
        }
        self.test("Track pellicola_impression event", "POST", "track", 200, data=track_pellicola_impression)

        track_pellicola_video = {
            "tipo": "pellicola_video_view",
            "model_slug": self.test_model_slug or "test",
            "session_id": "test-session-123",
            "cta_source": "pubblico"
        }
        self.test("Track pellicola_video_view event", "POST", "track", 200, data=track_pellicola_video)

        track_pellicola_click = {
            "tipo": "pellicola_click_profilo",
            "model_slug": self.test_model_slug or "test",
            "session_id": "test-session-123",
            "cta_source": "segreto",
            "meta": {"posizione": 0, "modalita": "segreto"}
        }
        self.test("Track pellicola_click_profilo event", "POST", "track", 200, data=track_pellicola_click)

    def test_admin_auth(self):
        self.log("\n--- ADMIN AUTHENTICATION ---", "INFO")

        # Wrong credentials
        self.test("Login with wrong password", "POST", "admin/login", 401,
                  data={"email": ADMIN_EMAIL, "password": "wrongpassword"})

        # Correct credentials
        success, resp = self.test("Login with correct credentials", "POST", "admin/login", 200,
                                   data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                                   check_response=lambda r: "token" in r and "email" in r)
        if success:
            self.token = resp.get("token")
            self.log(f"Got auth token: {self.token[:20]}...", "INFO")

        # Test protected route without token
        temp_token = self.token
        self.token = None
        self.test("Access protected route without token", "GET", "admin/me", 401)
        self.token = temp_token

        # Test /me with token
        if self.token:
            self.test("Get admin profile", "GET", "admin/me", 200,
                      check_response=lambda r: r.get("email") == ADMIN_EMAIL)

    def test_admin_models(self):
        self.log("\n--- ADMIN MODELS CRUD ---", "INFO")

        # List all models
        success, resp = self.test("Admin list models", "GET", "admin/models", 200,
                                   check_response=lambda r: "items" in r)

        # Create model without conferma_maggiorenne (should fail if pubblicata)
        new_model = {
            "nome": "Test Creator",
            "nome_artistico": "TestArtist",
            "slug": "test-creator-api",
            "frase": "Test tagline",
            "bio": "Test bio",
            "stato": "pubblicata",
            "conferma_maggiorenne": False,
            "categorie": [],
            "tag": [],
            "onlyfans_url": "https://onlyfans.com/test",
            "ordine": 999
        }
        self.test("Create model without age confirmation (should fail)", "POST", "admin/models", 400, data=new_model)

        # Create model with conferma_maggiorenne
        new_model["conferma_maggiorenne"] = True
        new_model["stato"] = "bozza"
        success, resp = self.test("Create model as bozza", "POST", "admin/models", 200, data=new_model,
                                   check_response=lambda r: "id" in r)
        test_model_id = resp.get("id") if success else None

        if test_model_id:
            # Get model
            self.test(f"Get model {test_model_id}", "GET", f"admin/models/{test_model_id}", 200,
                      check_response=lambda r: r.get("id") == test_model_id)

            # Update model
            new_model["bio"] = "Updated bio"
            self.test(f"Update model {test_model_id}", "PUT", f"admin/models/{test_model_id}", 200, data=new_model)

            # Try to publish without conferma_maggiorenne
            self.test(f"Publish without age confirmation", "PATCH", f"admin/models/{test_model_id}/stato", 400,
                      data={"stato": "pubblicata"})

            # Update with conferma and publish
            new_model["conferma_maggiorenne"] = True
            self.test(f"Update with age confirmation", "PUT", f"admin/models/{test_model_id}", 200, data=new_model)
            self.test(f"Publish model", "PATCH", f"admin/models/{test_model_id}/stato", 200,
                      data={"stato": "pubblicata"})

            # Delete model
            self.test(f"Delete model {test_model_id}", "DELETE", f"admin/models/{test_model_id}", 200)

        # Test reorder
        self.test("Reorder models", "POST", "admin/models/reorder", 200,
                  data={"order": []})

    def test_admin_categories(self):
        self.log("\n--- ADMIN CATEGORIES CRUD ---", "INFO")

        # List categories
        self.test("Admin list categories", "GET", "admin/categories", 200,
                  check_response=lambda r: "items" in r)

        # Create category
        new_cat = {
            "nome": "Test Category",
            "slug": "test-category-api",
            "descrizione": "Test description",
            "stato": "pubblicata",
            "indicizzabile": True,
            "ordine": 999
        }
        success, resp = self.test("Create category", "POST", "admin/categories", 200, data=new_cat,
                                   check_response=lambda r: "id" in r)
        test_cat_id = resp.get("id") if success else None

        if test_cat_id:
            # Update category
            new_cat["descrizione"] = "Updated description"
            self.test(f"Update category {test_cat_id}", "PUT", f"admin/categories/{test_cat_id}", 200, data=new_cat)

            # Delete category
            self.test(f"Delete category {test_cat_id}", "DELETE", f"admin/categories/{test_cat_id}", 200)

    def test_admin_articles(self):
        self.log("\n--- ADMIN ARTICLES CRUD ---", "INFO")

        # List articles
        self.test("Admin list articles", "GET", "admin/articles", 200,
                  check_response=lambda r: "items" in r)

        # Create article with script tags (should be sanitized)
        new_article = {
            "titolo": "Test Article API",
            "slug": "test-article-api",
            "estratto": "Test excerpt",
            "contenuto": "<p>Test content</p><script>alert('xss')</script>",
            "stato": "bozza",
            "autore": "Test Author",
            "categorie": [],
            "tag": [],
            "keyword_principale": "test",
            "keyword_secondarie": [],
            "seo_title": "Test Article",
            "meta_description": "Test meta",
            "indicizzabile": True
        }
        success, resp = self.test("Create article (script should be sanitized)", "POST", "admin/articles", 200,
                                   data=new_article, check_response=lambda r: "id" in r)
        test_article_id = resp.get("id") if success else None

        if test_article_id:
            # Get article and verify sanitization
            success, resp = self.test(f"Get article {test_article_id}", "GET", f"admin/articles/{test_article_id}", 200)
            if success and "<script>" in resp.get("contenuto", ""):
                self.log("WARNING: Script tag not sanitized!", "WARN")

            # Update article
            new_article["estratto"] = "Updated excerpt"
            self.test(f"Update article {test_article_id}", "PUT", f"admin/articles/{test_article_id}", 200,
                      data=new_article)

            # Delete article
            self.test(f"Delete article {test_article_id}", "DELETE", f"admin/articles/{test_article_id}", 200)

    def test_admin_settings(self):
        self.log("\n--- ADMIN SETTINGS ---", "INFO")

        # Get settings
        success, resp = self.test("Get settings", "GET", "admin/settings", 200)

        # Update settings
        settings_update = {
            "brand_name": "LATO SEGRETO",
            "site_description": "Test description",
            "auto_publish_articles": False
        }
        self.test("Update settings", "PUT", "admin/settings", 200, data=settings_update)

    def test_admin_audit(self):
        self.log("\n--- ADMIN AUDIT LOG ---", "INFO")

        self.test("Get audit log", "GET", "admin/audit?limit=10", 200,
                  check_response=lambda r: "items" in r)

    def test_analytics(self):
        self.log("\n--- ANALYTICS ENDPOINTS ---", "INFO")

        self.test("Analytics overview (oggi)", "GET", "admin/analytics/overview?range=oggi", 200,
                  check_response=lambda r: "visite" in r and "attivazioni" in r)

        self.test("Analytics overview (7g)", "GET", "admin/analytics/overview?range=7g", 200)

        self.test("Analytics funnel", "GET", "admin/analytics/funnel?range=30g", 200,
                  check_response=lambda r: "steps" in r)

        self.test("Analytics models leaderboard", "GET", "admin/analytics/models?range=30g", 200,
                  check_response=lambda r: "items" in r)

        self.test("Analytics timeseries", "GET", "admin/analytics/timeseries?range=30g", 200,
                  check_response=lambda r: "items" in r)

        self.test("Analytics articles", "GET", "admin/analytics/articles?range=30g", 200,
                  check_response=lambda r: "items" in r)

        # Campaign attribution
        self.test("Analytics campaigns (30g)", "GET", "admin/analytics/campaigns?range=30g", 200,
                  check_response=lambda r: "items" in r and "range" in r)
        self.test("Analytics campaigns (7g)", "GET", "admin/analytics/campaigns?range=7g", 200)
        self.test("Analytics campaigns (oggi)", "GET", "admin/analytics/campaigns?range=oggi", 200)

        # NEW: Pellicola analytics
        success, resp = self.test("Analytics pellicola (30g)", "GET", "admin/analytics/pellicola?range=30g", 200,
                                   check_response=lambda r: "impression" in r and "video_view" in r and "click" in r)
        if success:
            self.log(f"Pellicola analytics: impression={resp.get('impression')}, video_view={resp.get('video_view')}, click={resp.get('click')}, ctr={resp.get('ctr')}%", "INFO")
            if "per_modalita" in resp:
                self.log(f"Per modalità: {resp['per_modalita']}", "INFO")
            if "per_modella" in resp and len(resp["per_modella"]) > 0:
                self.log(f"Top modella: {resp['per_modella'][0].get('modella')} with {resp['per_modella'][0].get('click')} clicks", "INFO")

        self.test("Analytics pellicola (7g)", "GET", "admin/analytics/pellicola?range=7g", 200)
        self.test("Analytics pellicola (oggi)", "GET", "admin/analytics/pellicola?range=oggi", 200)

        # Model detail (if we have a model)
        if self.test_model_slug:
            # Get model ID from slug
            success, resp = self.test("Get model for analytics", "GET", f"models/{self.test_model_slug}", 200)
            if success and resp.get("id"):
                model_id = resp["id"]
                self.test(f"Analytics model detail", "GET", f"admin/analytics/model/{model_id}?range=30g", 200,
                          check_response=lambda r: "stats" in r)

    def test_integrations(self):
        self.log("\n--- INTEGRATIONS (WEBHOOK) ---", "INFO")

        # Test without API key
        webhook_article = {
            "titolo": "Test Webhook Article",
            "slug": "test-webhook-article",
            "estratto": "Test excerpt from webhook",
            "contenuto": "<p>Test content</p><script>alert('should be removed')</script>",
            "external_id": "test-webhook-123"
        }
        self.test("Webhook without API key", "POST", "integrations/seo/articles", 401,
                  data=webhook_article)

        # Test with wrong API key
        self.test("Webhook with wrong API key", "POST", "integrations/seo/articles", 401,
                  data=webhook_article, headers={"X-API-Key": "wrong-key"})

        # Test with correct API key
        success, resp = self.test("Webhook with correct API key", "POST", "integrations/seo/articles", 200,
                                   data=webhook_article, headers={"X-API-Key": WEBHOOK_KEY},
                                   check_response=lambda r: r.get("ok") == True and r.get("azione") in ["creato", "aggiornato"])

        if success:
            self.log(f"Webhook result: {resp.get('azione')} - stato: {resp.get('stato')}", "INFO")

    def test_auto_bozza_feature(self):
        self.log("\n--- AUTO-BOZZA SAFETY FEATURE ---", "INFO")
        
        # Get a published model to test with
        success, resp = self.test("Get published models for auto-bozza test", "GET", "admin/models", 200)
        if not success or not resp.get("items"):
            self.log("No models found for auto-bozza test", "WARN")
            return
        
        # Find a published model with complete profile
        published_model = None
        for m in resp["items"]:
            if m.get("stato") == "pubblicata" and m.get("readiness", {}).get("is_ready"):
                published_model = m
                break
        
        if not published_model:
            self.log("No complete published model found for auto-bozza test", "WARN")
            return
        
        model_id = published_model["id"]
        self.log(f"Testing auto-bozza with model: {published_model.get('nome_artistico')} (id: {model_id})", "INFO")
        
        # Get full model data
        success, model_data = self.test(f"Get full model data for {model_id}", "GET", f"admin/models/{model_id}", 200)
        if not success:
            return
        
        # Store original onlyfans_url to restore later
        original_onlyfans = model_data.get("onlyfans_url", "")
        
        # TEST 1: Remove OnlyFans URL (required field) while keeping stato=pubblicata
        self.log("TEST 1: Remove OnlyFans URL from published model", "INFO")
        model_data["onlyfans_url"] = ""
        model_data["stato"] = "pubblicata"
        
        success, resp = self.test("Update published model with missing OnlyFans (should auto-revert to bozza)", 
                                  "PUT", f"admin/models/{model_id}", 200, data=model_data,
                                  check_response=lambda r: r.get("stato") == "bozza" and r.get("_auto", {}).get("type") == "bozza")
        
        if success:
            auto_info = resp.get("_auto", {})
            self.log(f"✓ Auto-bozza triggered: type={auto_info.get('type')}, missing={auto_info.get('missing')}", "SUCCESS")
            
            # Verify the model is now in bozza state
            success2, check_resp = self.test(f"Verify model is now in bozza", "GET", f"admin/models/{model_id}", 200,
                                             check_response=lambda r: r.get("stato") == "bozza")
            if success2:
                self.log("✓ Model successfully reverted to bozza state", "SUCCESS")
        else:
            self.log("✗ Auto-bozza did not trigger as expected", "FAIL")
        
        # Restore the model to published state with complete data
        model_data["onlyfans_url"] = original_onlyfans or "https://onlyfans.com/test"
        model_data["stato"] = "bozza"
        self.test(f"Restore model data", "PUT", f"admin/models/{model_id}", 200, data=model_data)
        self.test(f"Republish model", "PATCH", f"admin/models/{model_id}/stato", 200, data={"stato": "pubblicata"})
        
        # TEST 2: Verify that modifying a published model without removing required fields does NOT trigger auto-bozza
        self.log("TEST 2: Modify published model without removing required fields", "INFO")
        success, model_data = self.test(f"Get model data again", "GET", f"admin/models/{model_id}", 200)
        if success:
            model_data["bio"] = "Updated bio - testing no auto-bozza"
            model_data["stato"] = "pubblicata"
            
            success, resp = self.test("Update published model with complete data (should stay pubblicata)", 
                                      "PUT", f"admin/models/{model_id}", 200, data=model_data,
                                      check_response=lambda r: r.get("stato") == "pubblicata" and "_auto" not in r)
            
            if success:
                self.log("✓ Model stayed published (no auto-bozza triggered)", "SUCCESS")
            else:
                self.log("✗ Unexpected auto-bozza or status change", "FAIL")
        
        # TEST 3: Test auto-pellicola-off (if pellicola is active)
        self.log("TEST 3: Test auto-pellicola-off feature", "INFO")
        success, model_data = self.test(f"Get model data for pellicola test", "GET", f"admin/models/{model_id}", 200)
        if success:
            # Ensure pellicola is active
            if not model_data.get("pellicola_home", {}).get("attiva"):
                model_data["pellicola_home"] = model_data.get("pellicola_home", {})
                model_data["pellicola_home"]["attiva"] = True
                self.test("Activate pellicola", "PUT", f"admin/models/{model_id}", 200, data=model_data)
                time.sleep(0.5)
                success, model_data = self.test(f"Get model data after activating pellicola", "GET", f"admin/models/{model_id}", 200)
            
            # Store original pellicola videos
            original_pel_pub = model_data.get("pellicola_home", {}).get("pubblico", {}).get("video_url", "")
            original_pel_sec = model_data.get("pellicola_home", {}).get("segreto", {}).get("video_url", "")
            
            # Remove ONLY pellicola videos (but keep profile complete with media_pairs videos)
            model_data["pellicola_home"]["pubblico"]["video_url"] = ""
            model_data["pellicola_home"]["segreto"]["video_url"] = ""
            model_data["stato"] = "pubblicata"
            
            # Check if model has video pairs (needed to keep profile complete)
            has_video_pairs = any(p.get("tipo") == "video" for p in model_data.get("media_pairs", []))
            
            if has_video_pairs:
                success, resp = self.test("Remove pellicola videos only (should disable pellicola, keep published)", 
                                          "PUT", f"admin/models/{model_id}", 200, data=model_data)
                
                if success:
                    # Check if pellicola was disabled or if auto-bozza triggered
                    if resp.get("_auto", {}).get("type") == "pellicola_off":
                        self.log(f"✓ Auto-pellicola-off triggered: {resp.get('_auto')}", "SUCCESS")
                        if not resp.get("pellicola_home", {}).get("attiva"):
                            self.log("✓ Pellicola correctly deactivated", "SUCCESS")
                        if resp.get("stato") == "pubblicata":
                            self.log("✓ Model stayed published", "SUCCESS")
                    elif resp.get("stato") == "bozza":
                        self.log("⚠ Model went to bozza (profile may be incomplete without pellicola videos)", "WARN")
                    else:
                        self.log("⚠ No auto action triggered (may be expected if fallback videos exist)", "WARN")
            else:
                self.log("⚠ Model has no video pairs, skipping pellicola-off test", "WARN")
            
            # Restore pellicola videos
            if original_pel_pub or original_pel_sec:
                model_data["pellicola_home"]["pubblico"]["video_url"] = original_pel_pub
                model_data["pellicola_home"]["segreto"]["video_url"] = original_pel_sec
                model_data["pellicola_home"]["attiva"] = True
                self.test("Restore pellicola videos", "PUT", f"admin/models/{model_id}", 200, data=model_data)

    def test_copy_config_bulk_feature(self):
        self.log("\n--- COPY CONFIG BULK FEATURE ---", "INFO")
        
        # Get all models
        success, resp = self.test("Get all models for bulk copy test", "GET", "admin/models", 200)
        if not success or not resp.get("items") or len(resp["items"]) < 2:
            self.log("Need at least 2 models for bulk copy test", "WARN")
            return
        
        models = resp["items"]
        source_model = models[0]
        target_models = models[1:4]  # Use up to 3 targets
        
        source_id = source_model["id"]
        target_ids = [m["id"] for m in target_models]
        
        self.log(f"Source model: {source_model.get('nome_artistico')} (id: {source_id})", "INFO")
        self.log(f"Target models: {[m.get('nome_artistico') for m in target_models]}", "INFO")
        
        # Store original data from targets to verify personal content is NOT copied
        target_originals = {}
        for tid in target_ids:
            success, data = self.test(f"Get target model {tid}", "GET", f"admin/models/{tid}", 200)
            if success:
                target_originals[tid] = {
                    "foto_card": data.get("foto_card"),
                    "onlyfans_url": data.get("onlyfans_url"),
                    "nome_artistico": data.get("nome_artistico"),
                    "bio": data.get("bio"),
                    "media_pairs": data.get("media_pairs", [])
                }
        
        # TEST 1: Copy all sections
        self.log("TEST 1: Copy all config sections (regista, conversione, pellicola)", "INFO")
        bulk_data = {
            "source_id": source_id,
            "target_ids": target_ids,
            "sections": {
                "regista": True,
                "conversione": True,
                "pellicola": True
            }
        }
        
        success, resp = self.test("Bulk copy all sections", "POST", "admin/models/copy-config-bulk", 200, 
                                  data=bulk_data,
                                  check_response=lambda r: r.get("updated") == len(target_ids) and len(r.get("sections", [])) == 3)
        
        if success:
            self.log(f"✓ Bulk copy successful: updated {resp.get('updated')} models, sections: {resp.get('sections')}", "SUCCESS")
            
            # Verify that personal content was NOT copied
            for tid in target_ids:
                success, updated_data = self.test(f"Verify target {tid} personal content unchanged", "GET", f"admin/models/{tid}", 200)
                if success and tid in target_originals:
                    orig = target_originals[tid]
                    if updated_data.get("foto_card") == orig["foto_card"]:
                        self.log(f"✓ foto_card unchanged for {tid}", "SUCCESS")
                    else:
                        self.log(f"✗ foto_card was changed for {tid}", "FAIL")
                    
                    if updated_data.get("onlyfans_url") == orig["onlyfans_url"]:
                        self.log(f"✓ onlyfans_url unchanged for {tid}", "SUCCESS")
                    else:
                        self.log(f"✗ onlyfans_url was changed for {tid}", "FAIL")
                    
                    if updated_data.get("nome_artistico") == orig["nome_artistico"]:
                        self.log(f"✓ nome_artistico unchanged for {tid}", "SUCCESS")
                    else:
                        self.log(f"✗ nome_artistico was changed for {tid}", "FAIL")
        
        # TEST 2: Copy only regista section
        self.log("TEST 2: Copy only regista section", "INFO")
        bulk_data_regista = {
            "source_id": source_id,
            "target_ids": [target_ids[0]],
            "sections": {
                "regista": True,
                "conversione": False,
                "pellicola": False
            }
        }
        
        success, resp = self.test("Bulk copy regista only", "POST", "admin/models/copy-config-bulk", 200, 
                                  data=bulk_data_regista,
                                  check_response=lambda r: r.get("updated") == 1 and r.get("sections") == ["regista"])
        
        if success:
            self.log(f"✓ Regista-only copy successful", "SUCCESS")
        
        # TEST 3: Validation - no sections selected (should fail)
        self.log("TEST 3: Validation - no sections selected", "INFO")
        bulk_data_invalid = {
            "source_id": source_id,
            "target_ids": target_ids,
            "sections": {
                "regista": False,
                "conversione": False,
                "pellicola": False
            }
        }
        
        success, resp = self.test("Bulk copy with no sections (should fail)", "POST", "admin/models/copy-config-bulk", 400, 
                                  data=bulk_data_invalid)
        
        if success:
            self.log("✓ Validation correctly rejected empty sections", "SUCCESS")
        
        # TEST 4: Validation - source not found (should fail)
        self.log("TEST 4: Validation - source not found", "INFO")
        bulk_data_bad_source = {
            "source_id": "nonexistent-id-12345",
            "target_ids": target_ids,
            "sections": {
                "regista": True,
                "conversione": False,
                "pellicola": False
            }
        }
        
        success, resp = self.test("Bulk copy with invalid source (should fail)", "POST", "admin/models/copy-config-bulk", 404, 
                                  data=bulk_data_bad_source)
        
        if success:
            self.log("✓ Validation correctly rejected invalid source", "SUCCESS")
        
        # TEST 5: Source in target list (should be ignored)
        self.log("TEST 5: Source in target list (should be ignored)", "INFO")
        bulk_data_self = {
            "source_id": source_id,
            "target_ids": [source_id] + target_ids[:1],  # Include source in targets
            "sections": {
                "regista": True,
                "conversione": False,
                "pellicola": False
            }
        }
        
        success, resp = self.test("Bulk copy with source in targets (should ignore source)", "POST", "admin/models/copy-config-bulk", 200, 
                                  data=bulk_data_self,
                                  check_response=lambda r: r.get("updated") == 1)  # Should only update 1 target, not source
        
        if success:
            self.log(f"✓ Source correctly ignored in target list: updated {resp.get('updated')} models", "SUCCESS")

    def test_seo_endpoints(self):
        self.log("\n--- SEO ENDPOINTS ---", "INFO")

        # Sitemap
        success, resp = self.test("Sitemap XML", "GET", "sitemap.xml", 200)
        if success and isinstance(resp.get("text"), str):
            if "<?xml" in resp["text"] and "<urlset" in resp["text"]:
                self.log("Sitemap XML is valid", "SUCCESS")
            else:
                self.log("Sitemap XML may be invalid", "WARN")

        # Robots.txt
        success, resp = self.test("Robots.txt", "GET", "robots.txt", 200)
        if success and isinstance(resp.get("text"), str):
            if "User-agent:" in resp["text"] and "Sitemap:" in resp["text"]:
                self.log("Robots.txt is valid", "SUCCESS")
            else:
                self.log("Robots.txt may be invalid", "WARN")

        # RSS
        success, resp = self.test("RSS XML", "GET", "rss.xml", 200)
        if success and isinstance(resp.get("text"), str):
            if "<?xml" in resp["text"] and "<rss" in resp["text"]:
                self.log("RSS XML is valid", "SUCCESS")
            else:
                self.log("RSS XML may be invalid", "WARN")

    def print_summary(self):
        self.log("\n" + "=" * 60, "INFO")
        self.log(f"TESTS COMPLETED: {self.tests_passed}/{self.tests_run} passed", "INFO")
        self.log("=" * 60, "INFO")

        if self.tests_passed == self.tests_run:
            self.log("ALL TESTS PASSED! 🎉", "SUCCESS")
            return 0
        else:
            failed = self.tests_run - self.tests_passed
            self.log(f"{failed} TEST(S) FAILED", "FAIL")
            return 1


def main():
    tester = LatoSegretoTester()
    exit_code = tester.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
