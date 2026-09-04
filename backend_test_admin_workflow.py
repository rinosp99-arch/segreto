#!/usr/bin/env python3
"""
Backend API tests for LATO SEGRETO admin workflow iteration.
Tests: filters, counts, demo/real detection, manual override, readiness, publish blocking, copy-config, draft preview.
"""
import requests
import sys
import json
from datetime import datetime

BASE_URL = "https://secret-side.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@latosegreto.it"
ADMIN_PASSWORD = "LatoSegreto2025!"


class BackendTester:
    def __init__(self):
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures = []

    def log(self, msg):
        print(f"  {msg}")

    def test(self, name, condition, error_msg=""):
        self.tests_run += 1
        if condition:
            self.tests_passed += 1
            self.log(f"✅ {name}")
            return True
        else:
            self.tests_failed += 1
            self.failures.append(f"{name}: {error_msg}")
            self.log(f"❌ {name} - {error_msg}")
            return False

    def login(self):
        print("\n🔐 Testing admin login...")
        try:
            r = requests.post(f"{BASE_URL}/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                self.token = data.get("token")
                self.test("Admin login successful", bool(self.token), f"No token in response: {data}")
                return True
            else:
                self.test("Admin login successful", False, f"Status {r.status_code}: {r.text}")
                return False
        except Exception as e:
            self.test("Admin login successful", False, str(e))
            return False

    def headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def test_admin_models_list(self):
        print("\n📋 Testing GET /api/admin/models (counts, content_status, readiness, stato_operativo)...")
        try:
            r = requests.get(f"{BASE_URL}/admin/models", headers=self.headers(), timeout=10)
            self.test("GET /api/admin/models returns 200", r.status_code == 200, f"Status: {r.status_code}")
            if r.status_code != 200:
                return False

            data = r.json()
            items = data.get("items", [])
            counts = data.get("counts", {})

            self.test("Response has 'items' array", isinstance(items, list), f"items type: {type(items)}")
            self.test("Response has 'counts' object", isinstance(counts, dict), f"counts type: {type(counts)}")

            # Check counts structure
            required_counts = ["tutte", "demo", "reali", "incomplete", "pronte"]
            for k in required_counts:
                self.test(f"counts.{k} present", k in counts, f"Missing key: {k}")

            # Check at least one item has the new fields
            if len(items) > 0:
                m = items[0]
                self.test("Item has 'content_status'", "content_status" in m, f"Keys: {m.keys()}")
                self.test("Item has 'readiness'", "readiness" in m, f"Keys: {m.keys()}")
                self.test("Item has 'stato_operativo'", "stato_operativo" in m, f"Keys: {m.keys()}")

                cs = m.get("content_status", {})
                self.test("content_status has 'is_demo'", "is_demo" in cs, f"Keys: {cs.keys()}")
                self.test("content_status has 'demo_fields'", "demo_fields" in cs, f"Keys: {cs.keys()}")

                rd = m.get("readiness", {})
                self.test("readiness has 'is_ready'", "is_ready" in rd, f"Keys: {rd.keys()}")
                self.test("readiness has 'missing_count'", "missing_count" in rd, f"Keys: {rd.keys()}")
                self.test("readiness has 'missing_required'", "missing_required" in rd, f"Keys: {rd.keys()}")

                op = m.get("stato_operativo")
                self.test("stato_operativo is valid", op in ["pubblicata", "pronta", "incompleta"], f"Value: {op}")

            self.log(f"📊 Counts: TUTTE={counts.get('tutte')}, DEMO={counts.get('demo')}, REALI={counts.get('reali')}, INCOMPLETE={counts.get('incomplete')}, PRONTE={counts.get('pronte')}")
            return True
        except Exception as e:
            self.test("GET /api/admin/models", False, str(e))
            return False

    def test_publish_blocking(self):
        print("\n🚫 Testing publish blocking for incomplete model...")
        try:
            # Create incomplete model
            payload = {
                "nome": f"Test Incomplete {datetime.now().strftime('%H%M%S')}",
                "nome_artistico": "Test Inc",
                "slug": "",
                "frase": "",
                "bio": "",
                "bio_segreta": "",
                "foto_card": "",
                "foto_copertina": "",
                "foto_card_teaser": "",
                "foto_segreta_hero": "",
                "galleria_pubblica": [],
                "galleria_segreta": [],
                "media_pairs": [],
                "categorie": [],
                "tag": [],
                "onlyfans_url": "",
                "stato": "bozza",
                "conferma_maggiorenne": False,
                "content_overrides": {},
                "tema": {},
                "messaggio_35s": {},
                "regia": {},
                "cta_temporizzata": {},
                "social": {},
                "pellicola_home": {},
                "seo": {},
            }
            r = requests.post(f"{BASE_URL}/admin/models", json=payload, headers=self.headers(), timeout=10)
            self.test("Create incomplete model (bozza)", r.status_code == 200, f"Status: {r.status_code}, {r.text}")
            if r.status_code != 200:
                return False

            model = r.json()
            model_id = model.get("id")
            self.log(f"Created model ID: {model_id}")

            # Try to publish incomplete model via PATCH /api/admin/models/{id}/stato
            r2 = requests.patch(f"{BASE_URL}/admin/models/{model_id}/stato", json={"stato": "pubblicata"}, headers=self.headers(), timeout=10)
            self.test("PATCH stato=pubblicata returns 400", r2.status_code == 400, f"Status: {r2.status_code}")

            if r2.status_code == 400:
                detail = r2.json().get("detail", {})
                self.test("detail.message is 'NON PUOI ANCORA PUBBLICARE'", detail.get("message") == "NON PUOI ANCORA PUBBLICARE", f"Message: {detail.get('message')}")
                self.test("detail.missing_required is array", isinstance(detail.get("missing_required"), list), f"Type: {type(detail.get('missing_required'))}")
                self.test("detail.missing_count is number", isinstance(detail.get("missing_count"), int), f"Type: {type(detail.get('missing_count'))}")
                self.log(f"Missing {detail.get('missing_count')} required fields: {detail.get('missing_required', [])[:3]}...")

            # Cleanup
            requests.delete(f"{BASE_URL}/admin/models/{model_id}", headers=self.headers(), timeout=10)
            return True
        except Exception as e:
            self.test("Publish blocking test", False, str(e))
            return False

    def test_manual_override(self):
        print("\n🔧 Testing manual content override (force REALE)...")
        try:
            # Create model with demo URLs but override to 'reale'
            payload = {
                "nome": f"Test Override {datetime.now().strftime('%H%M%S')}",
                "nome_artistico": "Test Ovr",
                "slug": "",
                "frase": "test",
                "bio": "test",
                "bio_segreta": "test",
                "foto_card": "https://images.unsplash.com/photo-1.jpg",
                "foto_copertina": "https://images.pexels.com/photo-2.jpg",
                "foto_card_teaser": "/media/test.jpg",
                "foto_segreta_hero": "https://images.unsplash.com/photo-3.jpg",
                "galleria_pubblica": [],
                "galleria_segreta": [],
                "media_pairs": [],
                "categorie": [],
                "tag": [],
                "onlyfans_url": "https://onlyfans.com/test",
                "stato": "bozza",
                "conferma_maggiorenne": True,
                "content_overrides": {
                    "foto_card": "reale",
                    "foto_copertina": "reale",
                    "foto_card_teaser": "reale",
                    "foto_segreta_hero": "reale",
                    "onlyfans": "reale",
                },
                "tema": {},
                "messaggio_35s": {},
                "regia": {},
                "cta_temporizzata": {},
                "social": {},
                "pellicola_home": {},
                "seo": {},
            }
            r = requests.post(f"{BASE_URL}/admin/models", json=payload, headers=self.headers(), timeout=10)
            self.test("Create model with overrides", r.status_code == 200, f"Status: {r.status_code}")
            if r.status_code != 200:
                return False

            model = r.json()
            model_id = model.get("id")

            # Fetch it back to check content_status
            r2 = requests.get(f"{BASE_URL}/admin/models/{model_id}", headers=self.headers(), timeout=10)
            self.test("GET model with overrides", r2.status_code == 200, f"Status: {r2.status_code}")
            if r2.status_code != 200:
                return False

            model2 = r2.json()
            cs = model2.get("content_status", {})
            self.test("content_status.is_demo is False (overridden to reale)", cs.get("is_demo") == False, f"is_demo: {cs.get('is_demo')}, demo_fields: {cs.get('demo_fields')}")

            # Cleanup
            requests.delete(f"{BASE_URL}/admin/models/{model_id}", headers=self.headers(), timeout=10)
            return True
        except Exception as e:
            self.test("Manual override test", False, str(e))
            return False

    def test_readiness_complete_model(self):
        print("\n✅ Testing readiness for complete demo seed model...")
        try:
            # Get all models and find one that is complete (pubblicata or has all required fields)
            r = requests.get(f"{BASE_URL}/admin/models", headers=self.headers(), timeout=10)
            if r.status_code != 200:
                self.test("GET models for readiness test", False, f"Status: {r.status_code}")
                return False

            items = r.json().get("items", [])
            complete = None
            for m in items:
                rd = m.get("readiness", {})
                if rd.get("is_ready") == True:
                    complete = m
                    break

            if complete:
                self.test("Found complete model with is_ready=true", True)
                self.log(f"Model: {complete.get('nome_artistico')} (ID: {complete.get('id')})")
                rd = complete.get("readiness", {})
                self.test("missing_count is 0", rd.get("missing_count") == 0, f"missing_count: {rd.get('missing_count')}")
                self.test("missing_required is empty", len(rd.get("missing_required", [])) == 0, f"missing_required: {rd.get('missing_required')}")
            else:
                self.log("⚠️  No complete model found in seed data (all models incomplete)")
                self.test("Found complete model", False, "No model with is_ready=true")

            return True
        except Exception as e:
            self.test("Readiness test", False, str(e))
            return False

    def test_copy_config(self):
        print("\n📋 Testing POST /api/admin/models/{id}/copy-config...")
        try:
            # Get two models
            r = requests.get(f"{BASE_URL}/admin/models", headers=self.headers(), timeout=10)
            if r.status_code != 200:
                self.test("GET models for copy-config", False, f"Status: {r.status_code}")
                return False

            items = r.json().get("items", [])
            if len(items) < 2:
                self.log("⚠️  Need at least 2 models for copy-config test")
                self.test("Copy-config test", False, "Not enough models")
                return False

            source = items[0]
            dest = items[1]
            source_id = source.get("id")
            dest_id = dest.get("id")

            self.log(f"Source: {source.get('nome_artistico')} ({source_id})")
            self.log(f"Dest: {dest.get('nome_artistico')} ({dest_id})")

            # Copy config
            r2 = requests.post(f"{BASE_URL}/admin/models/{dest_id}/copy-config", json={"source_id": source_id}, headers=self.headers(), timeout=10)
            self.test("POST copy-config returns 200", r2.status_code == 200, f"Status: {r2.status_code}, {r2.text}")

            if r2.status_code == 200:
                result = r2.json()
                self.test("Response has tema", "tema" in result, f"Keys: {result.keys()}")
                self.test("Response has regia", "regia" in result, f"Keys: {result.keys()}")
                self.test("Response has cta_temporizzata", "cta_temporizzata" in result, f"Keys: {result.keys()}")
                self.test("Response has pellicola_home", "pellicola_home" in result, f"Keys: {result.keys()}")
                # Verify personal content NOT copied (bio, foto_card, onlyfans should remain dest's)
                self.test("bio NOT copied (remains dest's)", result.get("bio") == dest.get("bio"), f"bio changed")
                self.test("foto_card NOT copied", result.get("foto_card") == dest.get("foto_card"), f"foto_card changed")

            return True
        except Exception as e:
            self.test("Copy-config test", False, str(e))
            return False

    def test_draft_preview(self):
        print("\n👁️  Testing draft preview (anteprima) with admin auth...")
        try:
            # Create a draft model
            payload = {
                "nome": f"Test Draft {datetime.now().strftime('%H%M%S')}",
                "nome_artistico": "Test Draft",
                "slug": f"test-draft-{datetime.now().strftime('%H%M%S')}",
                "frase": "test",
                "bio": "test bio",
                "bio_segreta": "test secret",
                "foto_card": "https://images.unsplash.com/photo-1.jpg",
                "foto_copertina": "",
                "foto_card_teaser": "",
                "foto_segreta_hero": "",
                "galleria_pubblica": [],
                "galleria_segreta": [],
                "media_pairs": [],
                "categorie": [],
                "tag": [],
                "onlyfans_url": "https://onlyfans.com/test",
                "stato": "bozza",
                "conferma_maggiorenne": True,
                "content_overrides": {},
                "tema": {},
                "messaggio_35s": {},
                "regia": {},
                "cta_temporizzata": {},
                "social": {},
                "pellicola_home": {},
                "seo": {},
            }
            r = requests.post(f"{BASE_URL}/admin/models", json=payload, headers=self.headers(), timeout=10)
            self.test("Create draft model", r.status_code == 200, f"Status: {r.status_code}")
            if r.status_code != 200:
                return False

            model = r.json()
            slug = model.get("slug")
            model_id = model.get("id")
            self.log(f"Draft slug: {slug}")

            # Try to access without auth (should 404)
            r2 = requests.get(f"{BASE_URL}/models/{slug}", timeout=10)
            self.test("GET /api/models/{slug} (draft, no auth) returns 404", r2.status_code == 404, f"Status: {r2.status_code}")

            # Try with admin auth (should work and return anteprima=true)
            r3 = requests.get(f"{BASE_URL}/models/{slug}", headers=self.headers(), timeout=10)
            self.test("GET /api/models/{slug} (draft, with admin auth) returns 200", r3.status_code == 200, f"Status: {r3.status_code}")
            if r3.status_code == 200:
                data = r3.json()
                self.test("Response has anteprima=true", data.get("anteprima") == True, f"anteprima: {data.get('anteprima')}")

            # Test secret endpoint too
            r4 = requests.get(f"{BASE_URL}/models/{slug}/segreto", timeout=10)
            self.test("GET /api/models/{slug}/segreto (draft, no auth) returns 404", r4.status_code == 404, f"Status: {r4.status_code}")

            r5 = requests.get(f"{BASE_URL}/models/{slug}/segreto", headers=self.headers(), timeout=10)
            self.test("GET /api/models/{slug}/segreto (draft, with admin auth) returns 200", r5.status_code == 200, f"Status: {r5.status_code}")

            # Cleanup
            requests.delete(f"{BASE_URL}/admin/models/{model_id}", headers=self.headers(), timeout=10)
            return True
        except Exception as e:
            self.test("Draft preview test", False, str(e))
            return False

    def test_regression(self):
        print("\n🔄 Testing regression (existing endpoints still work)...")
        try:
            # GET /api/models
            r1 = requests.get(f"{BASE_URL}/models", timeout=10)
            self.test("GET /api/models returns 200", r1.status_code == 200, f"Status: {r1.status_code}")

            # GET /api/pellicola
            r2 = requests.get(f"{BASE_URL}/pellicola", timeout=10)
            self.test("GET /api/pellicola returns 200", r2.status_code == 200, f"Status: {r2.status_code}")

            # GET /api/categories
            r3 = requests.get(f"{BASE_URL}/categories", timeout=10)
            self.test("GET /api/categories returns 200", r3.status_code == 200, f"Status: {r3.status_code}")

            # GET /api/admin/me
            r4 = requests.get(f"{BASE_URL}/admin/me", headers=self.headers(), timeout=10)
            self.test("GET /api/admin/me returns 200", r4.status_code == 200, f"Status: {r4.status_code}")

            return True
        except Exception as e:
            self.test("Regression test", False, str(e))
            return False

    def run_all(self):
        print("=" * 60)
        print("🧪 LATO SEGRETO Backend API Tests - Admin Workflow")
        print("=" * 60)

        if not self.login():
            print("\n❌ Login failed, cannot continue")
            return False

        self.test_admin_models_list()
        self.test_publish_blocking()
        self.test_manual_override()
        self.test_readiness_complete_model()
        self.test_copy_config()
        self.test_draft_preview()
        self.test_regression()

        print("\n" + "=" * 60)
        print(f"📊 RESULTS: {self.tests_passed}/{self.tests_run} passed, {self.tests_failed} failed")
        print("=" * 60)

        if self.failures:
            print("\n❌ FAILURES:")
            for f in self.failures:
                print(f"  - {f}")

        return self.tests_failed == 0


if __name__ == "__main__":
    tester = BackendTester()
    success = tester.run_all()
    sys.exit(0 if success else 1)
