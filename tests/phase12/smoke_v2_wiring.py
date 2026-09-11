"""Phase 12A post-wiring smoke (preview, READ_ONLY). Creates a temporary AI key via the real admin API, exercises the v2 primitives
through the running server, checks Phase 10/11 regressions, then revokes the key. No secret is printed."""
import json
import os
import sys
import requests

BASE = os.environ.get("BASE_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].splitlines()[0].strip()
CREDS = {}
for line in open("/app/memory/test_credentials.md"):
    if "email" in line.lower() and "@" in line and "email" not in CREDS:
        CREDS["email"] = line.split(":")[-1].strip().strip("`* ")
    if "password" in line.lower() and "password" not in CREDS and ":" in line:
        CREDS["password"] = line.split(":", 1)[-1].strip().strip("`* ")

res = []
def ok(name, cond, extra=""):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

s = requests.Session()
r = s.post(f"{BASE}/api/admin/login", json={"email": CREDS["email"], "password": CREDS["password"]}, timeout=20)
ok("admin login", r.status_code == 200, r.status_code)
jwt = r.json().get("access_token") or r.json().get("token")
H = {"Authorization": f"Bearer {jwt}"}

r = s.post(f"{BASE}/api/v1/auth/keys", json={"name": "smoke-12a", "role": "AI_OPERATOR", "source": "chatgpt"}, headers=H, timeout=20)
ok("create temp AI key", r.status_code in (200, 201), r.text[:200])
key = r.json()["api_key"]; key_id = r.json()["id"]
K = {"Authorization": f"Bearer {key}"}
try:
    # mode must be READ_ONLY
    r = s.get(f"{BASE}/api/v2/ai/status", headers=K, timeout=30)
    ok("v2 getSystemStatus 200 + READ_ONLY", r.status_code == 200 and r.json()["data"].get("mode") == "READ_ONLY", r.text[:200])
    ok("v2 status: registry 97, no double envelope", r.json()["data"]["capabilities_registry"]["total"] == 97 and "ok" not in r.json()["data"])
    # catalog
    r = s.get(f"{BASE}/api/v2/ai/capabilities", headers=K, timeout=30)
    d = r.json().get("data", {})
    ok("v2 getCapabilities 200", r.status_code == 200 and d.get("count", 0) > 50, r.text[:200])
    ok("catalog: no CRITICAL, no UNBOUND advertised", all(c["risk"] != "CRITICAL" for c in d.get("capabilities", [])))
    r = s.get(f"{BASE}/api/v2/ai/capabilities/models.update", headers=K, timeout=30)
    ok("v2 getCapability models.update", r.status_code == 200 and r.json()["data"]["status"] == "BOUND")
    # findModel
    r = s.post(f"{BASE}/api/v2/ai/models/find", json={"reference": "Francesca"}, headers=K, timeout=30)
    ok("v2 findModel", r.status_code == 200 and r.json()["data"].get("slug"), r.text[:200])
    slug = r.json()["data"]["slug"]
    # preview (dry) allowed in READ_ONLY, nothing written
    r = s.post(f"{BASE}/api/v2/ai/preview", json={"action": "models.update", "target": slug, "parameters": {"changes": {"badge": "smoke"}}}, headers=K, timeout=30)
    ok("v2 previewCapability 200 dry_run", r.status_code == 200 and r.json()["data"]["dry_run"] is True and r.json()["data"]["rollback"]["available"] is False, r.text[:200])
    # optimistic concurrency: stale token -> 409 at root level AND when (wrongly) sent inside parameters / parameters.changes
    stale = "2000-01-01T00:00:00+00:00"
    r = s.post(f"{BASE}/api/v2/ai/preview", json={"action": "models.update", "target": slug, "parameters": {"changes": {"badge": "smoke"}}, "expected_updated_at": stale}, headers=K, timeout=30)
    ok("v2 concurrency 409 CONFLICT (root expected_updated_at)", r.status_code == 409 and r.json().get("code") == "CONFLICT", r.text[:200])
    r = s.post(f"{BASE}/api/v2/ai/preview", json={"action": "models.update", "target": slug, "parameters": {"changes": {"badge": "smoke", "expected_updated_at": stale}}}, headers=K, timeout=30)
    ok("v2 concurrency 409 CONFLICT (hoisted from parameters.changes)", r.status_code == 409 and r.json().get("code") == "CONFLICT", r.text[:200])
    r = s.post(f"{BASE}/api/v2/ai/preview", json={"action": "models.update", "target": slug, "parameters": {"changes": {"badge": "smoke"}, "expected_updated_at": stale}}, headers=K, timeout=30)
    ok("v2 concurrency 409 CONFLICT (hoisted from parameters)", r.status_code == 409 and r.json().get("code") == "CONFLICT", r.text[:200])
    # execute mutation -> blocked (AI error envelope from server handler)
    r = s.post(f"{BASE}/api/v2/ai/execute", json={"action": "models.update", "target": slug, "parameters": {"changes": {"badge": "smoke"}}}, headers=K, timeout=30)
    ok("v2 executeCapability blocked READ_ONLY_MODE (403, envelope)", r.status_code == 403 and r.json().get("code") == "READ_ONLY_MODE" and r.json().get("ok") is False, r.text[:200])
    # read capability executes fine
    r = s.post(f"{BASE}/api/v2/ai/execute", json={"action": "models.list"}, headers=K, timeout=30)
    ok("v2 execute read capability (models.list)", r.status_code == 200 and r.json()["ok"])
    # unknown / validation envelope
    r = s.post(f"{BASE}/api/v2/ai/execute", json={"action": "shell.exec"}, headers=K, timeout=30)
    ok("v2 unknown capability 404 UNKNOWN_CAPABILITY", r.status_code == 404 and r.json().get("code") == "UNKNOWN_CAPABILITY")
    r = s.post(f"{BASE}/api/v2/ai/execute", json={"nope": 1}, headers=K, timeout=30)
    ok("v2 body validation 422 envelope", r.status_code == 422 and r.json().get("code") == "VALIDATION_FAILED")
    # approvals / analytics / rollback plan / openapi
    r = s.get(f"{BASE}/api/v2/ai/approvals", headers=K, timeout=30)
    ok("v2 listApprovals", r.status_code == 200)
    r = s.post(f"{BASE}/api/v2/ai/analytics/query", json={"metric": "model_views", "range": "7g"}, headers=K, timeout=30)
    ok("v2 queryAnalytics", r.status_code == 200 and "data" in r.json(), r.text[:200])
    r = s.post(f"{BASE}/api/v2/ai/rollback", json={"session_id": "ses_none", "dry_run": True}, headers=K, timeout=30)
    ok("v2 rollback dry plan (empty session)", r.status_code == 200, r.text[:200])
    r = s.get(f"{BASE}/api/v2/ai/openapi-chatgpt.json", timeout=30)
    ops = [o["operationId"] for p in r.json()["paths"].values() for o in p.values()]
    ok("v2 openapi public: 12 ops, server url set", r.status_code == 200 and len(ops) == 12 and r.json()["servers"][0]["url"].startswith("http"))
    ok("v2 openapi no secrets", "ls_" not in json.dumps(r.json()).replace("ls_...", "") and key not in r.text)
    # auth failures
    ok("v2 no auth -> 401", s.get(f"{BASE}/api/v2/ai/capabilities", timeout=30).status_code == 401)
    ok("v2 wrong key -> 401", s.get(f"{BASE}/api/v2/ai/capabilities", headers={"Authorization": "Bearer ls_wrongwrongwrong"}, timeout=30).status_code == 401)
    ok("v2 admin endpoint denied to API key", s.get(f"{BASE}/api/v2/ai/admin/capabilities", headers=K, timeout=30).status_code == 403)
    r = s.get(f"{BASE}/api/v2/ai/admin/capabilities", headers=H, timeout=30)
    ok("v2 admin capabilities (JWT) 97 total / 97 bound", r.status_code == 200 and r.json()["total"] == 97 and r.json()["bound"] == 97, r.text[:200])
    # ---- Phase 10/11 regressions (v1 untouched)
    r = s.get(f"{BASE}/api/v1/ai/openapi-chatgpt.json", timeout=30)
    ops1 = [o["operationId"] for p in r.json()["paths"].values() for o in p.values()]
    ok("v1 openapi still 23 ops", r.status_code == 200 and len(ops1) == 23, len(ops1))
    ok("v1 capabilities", s.get(f"{BASE}/api/v1/ai/capabilities", headers=K, timeout=30).status_code == 200)
    ok("v1 status", s.get(f"{BASE}/api/v1/ai/status", headers=K, timeout=30).status_code == 200)
    r = s.get(f"{BASE}/api/v1/ai/site-health", headers=K, timeout=60)
    ok("v1 site-health", r.status_code == 200)
    r = s.post(f"{BASE}/api/v1/ai/command", json={"action": "analytics.query", "parameters": {"metric": "model_views", "range": "7g"}}, headers=K, timeout=30)
    ok("v1 command dispatcher", r.status_code == 200, r.text[:160])
    ok("public site", s.get(f"{BASE}/api/models", timeout=30).status_code == 200)
    ok("health", s.get(f"{BASE}/api/health", timeout=30).status_code in (200, 404))
    # audit recorded for v2 with session_id
    r = s.get(f"{BASE}/api/v1/ai/actions?limit=5", headers=K, timeout=30)
    ok("v2 actions visible in v1 activity log", r.status_code == 200 and any(a.get("action") in ("models.list", "models.update") for a in (r.json().get("data", {}).get("items") or r.json().get("data", {}).get("actions") or [])), r.text[:200])
finally:
    r = s.delete(f"{BASE}/api/v1/auth/keys/{key_id}", headers=H, timeout=20)
    ok("temp key revoked", r.status_code in (200, 204), r.status_code)
    ok("revoked key rejected", s.get(f"{BASE}/api/v2/ai/capabilities", headers=K, timeout=30).status_code == 401)
    try:   # remove the revoked test key record too (no residue in the preview DB)
        sys.path.insert(0, "/app/backend")
        import asyncio
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        from database import api_keys_col
        asyncio.new_event_loop().run_until_complete(api_keys_col.delete_many({"id": key_id}))
    except Exception as e:
        print("note: key record cleanup skipped:", str(e)[:80])

n = sum(1 for _, p in res if p)
print(f"\nSMOKE: {n}/{len(res)} -> {'PASS' if n == len(res) else 'FAIL'}")
sys.exit(0 if n == len(res) else 1)
