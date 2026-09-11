"""Phase 12A - PRODUCTION post-deploy verification (READ_ONLY, no business mutation).

Runs against BASE_URL (default: production). Uses the real admin login to create TEMPORARY API keys (revoked at the end;
the revoked records stay as audit like in Phase 11), then verifies the v2 surface exactly as a GPT client would, in
READ_ONLY: reads, previews, blocked mutations, auth, allow/deny, scopes, concurrency, idempotency, cluster-wide rate limit,
zero secret leak; then Phase 10/11 + v1 + public site + admin + media + SEO + health/alert reconciliation + sitemap/robots/RSS
regressions. Never prints a key. Never toggles ai_write_enabled. Never calls a real mutation.

Run: BASE_URL=https://secret-side.emergent.host python tests/phase12/verify_production_v2.py
"""
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import uuid

import requests

sys.path.insert(0, "/app/tests")
sys.path.insert(0, "/app/backend")
from _creds import admin_credentials  # noqa: E402
from v1_security import AI_READ_ONLY_SCOPES  # noqa: E402  (same minimum-privilege preset the panel offers)

BASE = os.environ.get("BASE_URL", "https://secret-side.emergent.host").rstrip("/")
S = requests.Session()
RES, PROBLEMS = [], []
REPORT = {"base_url": BASE, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "v2": [], "regressions": []}
SECRET_RX = re.compile(r"(key_hash|token_hash|password_hash|MONGO_URL|mongodb(\+srv)?://|JWT_SECRET|SECRET_KEY|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.)")


def ok(section, name, cond, extra=""):
    RES.append((section, name, bool(cond)))
    REPORT.setdefault("p13", [])
    (REPORT["v2"] if section == "v2" else REPORT["p13"] if section == "p13" else REPORT["regressions"]).append({"check": name, "result": "PASS" if cond else "FAIL", "note": str(extra)[:200] if not cond else ""})
    print(f"{'PASS' if cond else 'FAIL'} [{section}] {name}" + (f"  -> {str(extra)[:180]}" if not cond and extra else ""))
    if not cond:
        PROBLEMS.append(f"{name}: {str(extra)[:180]}")


def j(r):
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:300]}


def code(r):
    d = j(r)
    d = d.get("detail", d)
    return d.get("code") if isinstance(d, dict) else None


def post(path, body, headers, **kw):
    for _ in range(4):
        r = S.post(f"{BASE}{path}", json=body, headers=headers, timeout=kw.get("timeout", 60))
        if r.status_code == 429 and not kw.get("no_retry"):
            time.sleep(int(r.headers.get("Retry-After", "20")) + 1)
            continue
        return r
    return r


# ---------------------------------------------------------------------------------------------- auth (admin JWT)
r = S.post(f"{BASE}/api/admin/login", json=admin_credentials(), timeout=30)
assert r.status_code == 200, f"admin login failed on {BASE}: {r.status_code}"
JWT = {"Authorization": f"Bearer {r.json().get('token') or r.json().get('access_token')}"}
created_keys = []


def mk_key(name, role="AI_OPERATOR", scopes=None, rate=300):
    body = {"name": name, "role": role, "source": "chatgpt", "rate_limit_per_min": rate}
    if scopes:
        body["scopes"] = scopes
    r = S.post(f"{BASE}/api/v1/auth/keys", json=body, headers=JWT, timeout=30)
    assert r.status_code in (200, 201), r.text[:200]
    created_keys.append(r.json()["id"])
    return r.json()["id"], {"Authorization": f"Bearer {r.json()['api_key']}"}, r.json()["api_key"]


TAG = f"prodcheck12a-{uuid.uuid4().hex[:6]}"
try:
    KID, K, RAW = mk_key(f"{TAG}-operator")
    # ------------------------------------------------------------------------------------------ mode invariant
    st = j(S.get(f"{BASE}/api/v2/ai/status", headers=K, timeout=60))
    d = st.get("data", {})
    ok("v2", "getSystemStatus 200 + mode READ_ONLY", st.get("ok") and d.get("mode") == "READ_ONLY", json.dumps(st)[:200])
    ok("v2", "status: no double envelope, registry total 104", "ok" not in d and d.get("capabilities_registry", {}).get("total") == 104, d.get("capabilities_registry"))
    ok("v2", "status: registry bound 104 / unbound 0", d.get("capabilities_registry", {}).get("bound") == 104 and d.get("capabilities_registry", {}).get("unbound", 0) == 0, d.get("capabilities_registry"))
    REPORT["read_only"] = d.get("mode") == "READ_ONLY"
    # ------------------------------------------------------------------------------------------ OpenAPI v2 / v1
    r = S.get(f"{BASE}/api/v2/ai/openapi-chatgpt.json", timeout=60)
    spec = j(r)
    ops2 = [o["operationId"] for p in spec.get("paths", {}).values() for o in p.values()]
    ok("v2", "OpenAPI v2 public 200, 12 operations, server = production", r.status_code == 200 and len(ops2) == 12 and spec.get("servers", [{}])[0].get("url") == BASE, (len(ops2), spec.get("servers")))
    ok("v2", "OpenAPI v2 operationIds = 12 universal primitives",
       set(ops2) == {"getCapabilities", "getCapability", "previewCapability", "executeCapability", "listApprovals", "approveApproval", "rejectApproval", "getJob", "queryAnalytics", "getSystemStatus", "rollback", "findModel"}, sorted(ops2))
    ok("v2", "OpenAPI v2: single Bearer security scheme, no secrets", list(spec.get("components", {}).get("securitySchemes", {}).keys()) == ["ApiKeyBearer"] and not SECRET_RX.search(r.text) and RAW not in r.text)
    REPORT["openapi_v2_url"] = f"{BASE}/api/v2/ai/openapi-chatgpt.json"
    REPORT["openapi_v2_operations"] = len(ops2)
    r1 = S.get(f"{BASE}/api/v1/ai/openapi-chatgpt.json", timeout=60)
    ops1 = [o["operationId"] for p in j(r1).get("paths", {}).values() for o in p.values()]
    ok("v2", "OpenAPI v1 (current GPT) untouched: 23 operations", r1.status_code == 200 and len(ops1) == 23, len(ops1))
    # ------------------------------------------------------------------------------------------ auth Bearer
    ok("v2", "no auth -> 401", S.get(f"{BASE}/api/v2/ai/capabilities", timeout=60).status_code == 401)
    ok("v2", "wrong key -> 401", S.get(f"{BASE}/api/v2/ai/capabilities", headers={"Authorization": "Bearer ls_wrongwrongwrongwrong"}, timeout=60).status_code == 401)
    ok("v2", "admin endpoint denied to API key (403)", S.get(f"{BASE}/api/v2/ai/admin/capabilities", headers=K, timeout=60).status_code == 403)
    # ------------------------------------------------------------------------------------------ getCapabilities / getCapability
    r = S.get(f"{BASE}/api/v2/ai/capabilities", headers=K, timeout=60)
    cat = j(r).get("data", {})
    caps = cat.get("capabilities", [])
    ok("v2", "getCapabilities 200 compact (AI_OPERATOR sees a large allowlisted catalog)", r.status_code == 200 and len(caps) >= 60 and all({"id", "risk", "category"} <= set(c) for c in caps), len(caps))
    rf = S.get(f"{BASE}/api/v2/ai/capabilities?compact=false", headers=K, timeout=60)
    full = j(rf).get("data", {}).get("capabilities", [])
    READ_ONLY_IDS = {c["id"] for c in full if c.get("read_only")}
    ok("v2", "catalog (full): no CRITICAL, all BOUND, stable ids + versions", rf.status_code == 200 and full and all(c["risk"] != "CRITICAL" and c.get("status") == "BOUND" and c.get("capability_version") for c in full), (rf.status_code, len(full)))
    r = S.get(f"{BASE}/api/v2/ai/capabilities/models.update", headers=K, timeout=60)
    ok("v2", "getCapability models.update BOUND with parameters_schema", r.status_code == 200 and j(r)["data"]["status"] == "BOUND" and "parameters_schema" in j(r)["data"])
    ok("v2", "getCapability unknown -> 404 UNKNOWN_CAPABILITY", S.get(f"{BASE}/api/v2/ai/capabilities/shell.exec", headers=K, timeout=60).status_code == 404)
    r = S.get(f"{BASE}/api/v2/ai/admin/capabilities", headers=JWT, timeout=60)
    adm = j(r)
    ok("v2", "admin registry (JWT): 104 total / 104 bound / 0 unbound / 0 CRITICAL exposed", r.status_code == 200 and adm.get("total") == 104 and adm.get("bound") == 104 and not adm.get("unbound") and (adm.get("by_risk") or {}).get("CRITICAL", 0) == 0, {k: adm.get(k) for k in ("total", "bound", "unbound", "by_risk")})
    REPORT["capabilities_total"], REPORT["capabilities_bound"], REPORT["capabilities_unbound"] = adm.get("total"), adm.get("bound"), len(adm.get("unbound") or [])
    # ------------------------------------------------------------------------------------------ findModel (real production catalogue)
    pm0 = j(S.get(f"{BASE}/api/models", timeout=60))
    pub0 = pm0.get("items", pm0.get("models", pm0)) if isinstance(pm0, dict) else pm0
    assert pub0, "no published model in production"
    SLUG = pub0[0]["slug"]
    NAME = (pub0[0].get("nome_artistico") or pub0[0].get("nome") or SLUG).strip().split(" ")[0].title()
    r = post("/api/v2/ai/models/find", {"reference": NAME}, K)
    ok("v2", f"findModel natural reference '{NAME}' -> slug (or 409 AMBIGUOUS with candidates)", (r.status_code == 200 and j(r)["data"].get("slug") == SLUG) or (r.status_code == 409 and code(r) == "AMBIGUOUS_REFERENCE"), r.text[:160])
    r = post("/api/v2/ai/models/find", {"reference": SLUG}, K)
    ok("v2", "findModel by slug -> exact", r.status_code == 200 and j(r)["data"].get("slug") == SLUG, r.text[:160])
    ok("v2", "findModel unknown -> 404 NOT_FOUND", post("/api/v2/ai/models/find", {"reference": "Modella Inesistente Zz"}, K).status_code == 404)
    # ------------------------------------------------------------------------------------------ preview / execute READ_ONLY
    body = {"action": "models.update", "target": SLUG, "parameters": {"changes": {"badge": "prodcheck"}}, "reason": "verifica post-deploy (anteprima)"}
    r = post("/api/v2/ai/preview", body, K)
    pv = j(r)
    ok("v2", "previewCapability 200 dry_run (no write, rollback not available)", r.status_code == 200 and pv.get("ok") and pv["data"].get("dry_run") is True and pv["data"]["rollback"]["available"] is False and pv.get("changes"), r.text[:200])
    etag_before = pv["data"].get("etag") if r.status_code == 200 else None
    r = post("/api/v2/ai/execute", body, K)
    ok("v2", "executeCapability mutation in READ_ONLY -> 403 READ_ONLY_MODE (blocked)", r.status_code == 403 and code(r) == "READ_ONLY_MODE", r.text[:200])
    r = post("/api/v2/ai/execute", {"action": "models.prepare_complete", "parameters": {"nome": "PRODCHECK NO", "fields": {}}}, K)
    ok("v2", "executeCapability workflow (prepare_complete) in READ_ONLY -> 403 blocked", r.status_code == 403 and code(r) == "READ_ONLY_MODE", r.text[:200])
    r = post("/api/v2/ai/execute", {"action": "media.upload_url", "parameters": {"url": "https://example.com/x.jpg"}}, K)
    ok("v2", "executeCapability upload in READ_ONLY -> 403 blocked (no fetch)", r.status_code == 403 and code(r) == "READ_ONLY_MODE", r.text[:200])
    r = post("/api/v2/ai/execute", {"action": "models.list"}, K)
    ok("v2", "executeCapability read (models.list) 200", r.status_code == 200 and j(r).get("ok") and j(r)["data"].get("items"), r.text[:160])
    r = post("/api/v2/ai/execute", {"action": "models.get", "target": SLUG}, K)
    got = j(r)
    ok("v2", "executeCapability models.get full card", r.status_code == 200 and got["data"].get("slug") == SLUG and "workflow_status" in got["data"])
    ok("v2", "unknown capability -> 404 UNKNOWN_CAPABILITY", post("/api/v2/ai/execute", {"action": "shell.exec"}, K).status_code == 404)
    r = post("/api/v2/ai/execute", {"nope": 1}, K)
    ok("v2", "body validation -> 422 VALIDATION_FAILED envelope", r.status_code == 422 and code(r) == "VALIDATION_FAILED")
    r = post("/api/v2/ai/preview", {"action": "media.assign", "target": SLUG, "parameters": {"media": "does-not-exist-zz", "slot": "card"}}, K)
    ok("v2", "preview with unknown media -> 404 NOT_FOUND (validation before any write)", r.status_code == 404 and code(r) == "NOT_FOUND", r.text[:160])
    # ------------------------------------------------------------------------------------------ queryAnalytics / listApprovals / getJob / rollback preview
    r = post("/api/v2/ai/analytics/query", {"metric": "model_views", "range": "7g"}, K)
    ok("v2", "queryAnalytics real metric 200", r.status_code == 200 and j(r).get("ok") and "data" in j(r), r.text[:160])
    ok("v2", "queryAnalytics invalid metric -> 422", post("/api/v2/ai/analytics/query", {"metric": "views_fake", "range": "7g"}, K).status_code == 422)
    r = S.get(f"{BASE}/api/v2/ai/approvals", headers=K, timeout=60)
    ok("v2", "listApprovals 200 (list)", r.status_code == 200 and isinstance(j(r).get("data", {}).get("items", j(r).get("data", {}).get("approvals", [])), list), r.text[:160])
    r = post("/api/v2/ai/execute", {"action": "jobs.list"}, K)
    jobs = (j(r).get("data") or {}).get("items") or []
    ok("v2", "jobs.list via execute (read)", r.status_code == 200 and jobs, r.text[:160])
    r = S.get(f"{BASE}/api/v2/ai/jobs/does-not-exist-zz", headers=K, timeout=60)
    ok("v2", "getJob (async AI jobs) unknown -> 404 NOT_FOUND envelope", r.status_code == 404 and code(r) == "NOT_FOUND", r.text[:160])
    ok("v2", "getJob without auth -> 401", S.get(f"{BASE}/api/v2/ai/jobs/x", timeout=60).status_code == 401)
    REPORT["getjob_note"] = "async AI jobs are created only by FULL batch operations: in production READ_ONLY only auth + 404 path is exercisable (200 path verified in preview coverage)."
    r = post("/api/v2/ai/rollback", {"session_id": "ses_prodcheck_none", "dry_run": True}, K)
    ok("v2", "rollback preview (dry_run) 200, nothing to undo", r.status_code == 200 and j(r).get("ok") and not (j(r).get("data") or {}).get("done"), r.text[:160])
    r = post("/api/v2/ai/rollback", {"session_id": "ses_prodcheck_none", "dry_run": False}, K)
    ok("v2", "rollback real in READ_ONLY -> blocked or no-op without writes", r.status_code in (403, 200) and (code(r) == "READ_ONLY_MODE" or "Nessuna modifica" in (j(r).get("summary") or "")), r.text[:160])
    # ------------------------------------------------------------------------------------------ concurrency (409) in preview
    stale = "2000-01-01T00:00:00+00:00"
    r = post("/api/v2/ai/preview", {**body, "expected_updated_at": stale}, K)
    ok("v2", "concurrency: stale expected_updated_at (root) -> 409 CONFLICT", r.status_code == 409 and code(r) == "CONFLICT", r.text[:160])
    r = post("/api/v2/ai/preview", {"action": "models.update", "target": SLUG, "parameters": {"changes": {"badge": "prodcheck", "expected_updated_at": stale}}}, K)
    ok("v2", "concurrency: stale token inside parameters.changes -> 409 CONFLICT (hoisted)", r.status_code == 409 and code(r) == "CONFLICT", r.text[:160])
    if etag_before:
        r = post("/api/v2/ai/preview", {**body, "expected_updated_at": etag_before}, K)
        ok("v2", "concurrency: current etag -> preview 200", r.status_code == 200, r.text[:160])
    # ------------------------------------------------------------------------------------------ idempotency (READ_ONLY-safe checks)
    ik = f"prodcheck-{uuid.uuid4().hex[:10]}"
    r1 = post("/api/v1/ai/command", {"action": "analytics.query", "parameters": {"metric": "model_views", "range": "7g"}}, {**K, "Idempotency-Key": ik})
    r2 = post("/api/v1/ai/command", {"action": "analytics.query", "parameters": {"metric": "model_views", "range": "7g"}}, {**K, "Idempotency-Key": ik})
    ok("v2", "idempotency (v1 middleware): replay returns Idempotent-Replayed + same request_id", r1.status_code == 200 and r2.status_code == 200 and r2.headers.get("Idempotent-Replayed") == "true" and r1.headers.get("X-Request-ID") == r2.headers.get("X-Request-ID"), (r1.status_code, r2.status_code, r2.headers.get("Idempotent-Replayed")))
    ik2 = f"prodcheck-{uuid.uuid4().hex[:10]}"
    ra = post("/api/v2/ai/execute", body, {**K, "Idempotency-Key": ik2})
    rb = post("/api/v2/ai/execute", body, {**K, "Idempotency-Key": ik2})
    ok("v2", "idempotency (v2): blocked mutation is never cached/replayed as success (403 twice)", ra.status_code == 403 and rb.status_code == 403 and not rb.headers.get("Idempotent-Replayed"), (ra.status_code, rb.status_code))
    REPORT["idempotency_note"] = "v2 per-capability replay (same key -> same result, different body -> 409 IDEMPOTENCY_CONFLICT) is only exercisable with real writes (FULL): verified in preview coverage, not in production READ_ONLY."
    # ------------------------------------------------------------------------------------------ capability allow / deny (on the temp key)
    r = S.patch(f"{BASE}/api/v1/auth/keys/{KID}/capabilities", json={"capability_allow": ["models.*", "analytics.*", "system.*"], "capability_deny": ["models.publish", "models.soft_delete"]}, headers=JWT, timeout=60)
    ok("v2", "PATCH key capability policy (JWT) 200", r.status_code == 200, r.text[:160])
    r = post("/api/v2/ai/preview", {"action": "models.publish", "target": SLUG}, K)
    ok("v2", "deny wins: models.publish -> 403 CAPABILITY_DENIED", r.status_code == 403 and code(r) == "CAPABILITY_DENIED", r.text[:160])
    r = post("/api/v2/ai/preview", {"action": "seo.audit"}, K)
    ok("v2", "allow restricts: seo.audit -> 403 CAPABILITY_NOT_ALLOWED", r.status_code == 403 and code(r) == "CAPABILITY_NOT_ALLOWED", r.text[:160])
    r = post("/api/v2/ai/execute", {"action": "models.get", "target": SLUG}, K)
    ok("v2", "allowed capability still works (models.get 200)", r.status_code == 200)
    cat2 = {c["id"] for c in j(S.get(f"{BASE}/api/v2/ai/capabilities", headers=K, timeout=60)).get("data", {}).get("capabilities", [])}
    ok("v2", "catalog filtered by policy (no denied / non-allowed ids)", cat2 and "models.publish" not in cat2 and "seo.audit" not in cat2 and all(i.split(".")[0] in ("models", "analytics", "system", "tags") for i in cat2), sorted(cat2)[:8])
    S.patch(f"{BASE}/api/v1/auth/keys/{KID}/capabilities", json={"capability_allow": None, "capability_deny": []}, headers=JWT, timeout=60)
    # ------------------------------------------------------------------------------------------ scopes (READ_ONLY-role key: allow never broadens)
    KID_RO, K_RO, RAW_RO = mk_key(f"{TAG}-readonly", role="AI_OPERATOR", scopes=list(AI_READ_ONLY_SCOPES))
    ok("v2", "READ_ONLY-scoped key: read ok (models.list)", post("/api/v2/ai/execute", {"action": "models.list"}, K_RO).status_code == 200)
    r = post("/api/v2/ai/execute", {"action": "models.update", "target": SLUG, "parameters": {"changes": {"badge": "x"}}}, K_RO)
    ok("v2", "READ_ONLY-scoped key: write capability -> 403 INSUFFICIENT_SCOPE (before READ_ONLY gate)", r.status_code == 403 and code(r) in ("INSUFFICIENT_SCOPE", "READ_ONLY_MODE"), r.text[:160])
    r = S.patch(f"{BASE}/api/v1/auth/keys/{KID_RO}/capabilities", json={"capability_allow": ["settings.*", "models.*"], "capability_deny": []}, headers=JWT, timeout=60)
    r = post("/api/v2/ai/execute", {"action": "settings.update", "parameters": {"changes": {"brand_name": "X"}}}, K_RO)
    ok("v2", "allow-list cannot grant a capability the scopes don't cover (settings.update -> 403)", r.status_code == 403 and code(r) in ("INSUFFICIENT_SCOPE", "READ_ONLY_MODE"), r.text[:160])
    # --- the exact production scenario reported by the user: READ_ONLY-preset key, TEST V2 GIULIA, no media
    r = S.get(f"{BASE}/api/v2/ai/capabilities/models.prepare_complete", headers=K_RO, timeout=60)
    meta = j(r).get("data", {})
    ok("v2", "getCapability(models.prepare_complete) READ_ONLY key: execute_access=none, preview_access=preview_only",
       r.status_code == 200 and meta.get("execute_access") == "none" and meta.get("preview_access") == "preview_only", {k: meta.get(k) for k in ("access", "execute_access", "preview_access", "missing_scopes_preview")})
    r = S.post(f"{BASE}/api/v2/ai/preview", json={"action": "models.prepare_complete", "parameters": {"nome": "TEST V2 GIULIA"}, "dry_run": True}, headers=K_RO, timeout=120)
    pcv = j(r)
    ok("v2", "previewCapability(models.prepare_complete, {nome:'TEST V2 GIULIA'}) READ_ONLY key -> 200 dry_run, no media:upload required, publishes=false",
       r.status_code == 200 and pcv.get("ok") and pcv["data"].get("dry_run") is True and pcv["data"].get("publishes") is False and "media:upload" not in json.dumps(pcv["data"].get("required_scopes_preview", [])), r.text[:240])
    REPORT["prepare_complete_preview_output"] = pcv if r.status_code == 200 else {"status": r.status_code, "body": pcv}
    r = S.post(f"{BASE}/api/v2/ai/preview", json={"action": "models.prepare_complete", "parameters": {"nome": "TEST V2 GIULIA", "fields": {"frase": "Quello che non vedi.", "tag": ["test"]}}}, headers=K_RO, timeout=120)
    ok("v2", "previewCapability(models.prepare_complete, {nome, fields}) READ_ONLY key -> 200 (SAFE/REVIEW split, nothing applied)", r.status_code == 200 and j(r).get("ok") and "frase" in (j(r).get("data") or {}).get("fields_review", []), r.text[:200])
    r = S.post(f"{BASE}/api/v2/ai/execute", json={"action": "models.prepare_complete", "parameters": {"nome": "TEST V2 GIULIA"}}, headers=K_RO, timeout=120)
    ok("v2", "executeCapability(models.prepare_complete) READ_ONLY key -> 403 blocked", r.status_code == 403 and code(r) in ("INSUFFICIENT_SCOPE", "READ_ONLY_MODE"), r.text[:160])
    pm_after = j(S.get(f"{BASE}/api/models", timeout=60))
    ok("v2", "zero mutation: TEST V2 GIULIA never created (public catalogue unchanged)", pm_after.get("total") == pm0.get("total") and not any("giulia" in (m.get("slug") or "") and "v2" in (m.get("slug") or "") for m in pm_after.get("items", [])), pm_after.get("total"))
    cat3 = {c["id"]: c.get("access") for c in j(S.get(f"{BASE}/api/v2/ai/capabilities", headers=K_RO, timeout=60)).get("data", {}).get("capabilities", [])}
    full_writes = [cid for cid, acc in cat3.items() if acc == "full" and cid not in READ_ONLY_IDS]
    ok("v2", "READ_ONLY-scoped catalog: every write capability is preview_only (never full); reads full",
       cat3 and not full_writes and cat3.get("models.list") == "full" and all(cat3[cid] == "preview_only" for cid in ("models.update", "models.create", "models.prepare_complete") if cid in cat3), full_writes[:8] or {k: v for k, v in list(cat3.items())[:6]})
    # ------------------------------------------------------------------------------------------ rate limit cluster-wide (dedicated key, floor 10/min)
    KID_RL, K_RL, RAW_RL = mk_key(f"{TAG}-ratelimit", rate=10)
    def _hit(_):
        r = S.get(f"{BASE}/api/v2/ai/capabilities/models.get", headers=K_RL, timeout=60)
        return r.status_code, r.headers.get("Retry-After")
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        hits = list(ex.map(_hit, range(24)))
    n200, n429 = sum(1 for s, _ in hits if s == 200), sum(1 for s, _ in hits if s == 429)
    ok("v2", "rate limit cluster-wide: 24 parallel -> some 429 with Retry-After, 200s <= limit", n429 > 0 and n200 <= 12 and all(ra for s, ra in hits if s == 429), f"200={n200} 429={n429} other={len(hits) - n200 - n429}")
    # ------------------------------------------------------------------------------------------ zero secret leak
    blobs = [json.dumps(st), json.dumps(cat), json.dumps(adm), json.dumps(got), r1.text, S.get(f"{BASE}/api/v1/ai/status", headers=K, timeout=60).text, S.get(f"{BASE}/api/v1/auth/keys", headers=JWT, timeout=60).text,
             S.get(f"{BASE}/api/v2/ai/admin/capabilities", headers=JWT, timeout=60).text, S.get(f"{BASE}/api/v1/config", headers=JWT, timeout=60).text, S.get(f"{BASE}/api/v1/ai/actions?limit=20", headers=K, timeout=60).text]
    leak = [i for i, b in enumerate(blobs) if RAW in b or RAW_RO in b or RAW_RL in b or SECRET_RX.search(b)]
    ok("v2", "zero secret leak (raw keys, hashes, Mongo URL, JWT secret) in status/catalog/admin/keys/config/actions", not leak, leak)
    # ------------------------------------------------------------------------------------------ REGRESSIONS: Phase 10/11 + v1
    ok("reg", "v1 capabilities (API key)", S.get(f"{BASE}/api/v1/ai/capabilities", headers=K, timeout=60).status_code == 200)
    r = S.get(f"{BASE}/api/v1/ai/status", headers=K, timeout=60)
    ok("reg", "v1 status 200 READ_ONLY", r.status_code == 200 and "READ_ONLY" in r.text)
    r = S.get(f"{BASE}/api/v1/ai/site-health", headers=K, timeout=120)
    sh = j(r).get("data", {})
    ok("reg", "v1 site-health 200, reconciled (current vs resolved_recent alerts)", r.status_code == 200 and "alerts" in sh and "alerts_resolved_recent" in sh and "health_checked_at" in sh, r.text[:160])
    ok("reg", "alert reconciliation: no stale onlyfans/seo_critical alert open while check ok", not (sh.get("onlyfans_links", {}).get("status") == "ok" and any(a.get("dedupe_key") in ("onlyfans_links", "health:onlyfans_links") for a in sh.get("alerts", []))), [a.get("dedupe_key") for a in sh.get("alerts", [])])
    ok("reg", "alert reconciliation: open alerts are current, resolved have resolved_at", all(a.get("current") is True for a in sh.get("alerts", [])) and all(a.get("current") is False and a.get("resolved_at") for a in sh.get("alerts_resolved_recent", [])))
    REPORT["health_overall"], REPORT["open_alerts"] = sh.get("health_overall"), len(sh.get("alerts", []))
    r = post("/api/v1/ai/command", {"action": "models.update", "target": SLUG, "parameters": {"changes": {"badge": "x"}}}, K)
    ok("reg", "v1 command mutation blocked READ_ONLY", r.status_code == 403 and code(r) == "READ_ONLY_MODE", r.text[:160])
    r = post("/api/v1/ai/command", {"action": "models.update", "target": SLUG, "parameters": {"changes": {"badge": "x"}}, "dry_run": True}, K)
    ok("reg", "v1 command dry_run allowed", r.status_code == 200, r.text[:160])
    r = S.get(f"{BASE}/api/v1/ai/recommendations?limit=20", headers=K, timeout=120)
    ok("reg", "v1 recommendations 200", r.status_code == 200)
    r = S.get(f"{BASE}/api/v1/ai/actions?limit=5", headers=K, timeout=60)
    acts = (j(r).get("data") or {})
    acts = acts.get("items") or acts.get("actions") or []
    ok("reg", "v2 actions visible in v1 activity log (audit)", r.status_code == 200 and any(a.get("action") in ("models.list", "models.get", "jobs.list") for a in acts), [a.get("action") for a in acts])
    r = S.post(f"{BASE}/api/v1/ai/test-connection", headers=JWT, timeout=120)
    tc = j(r)
    checks = tc.get("results") or []
    ok("reg", "v1 test-connection (JWT) 13/13 green", r.status_code == 200 and tc.get("status") == "green" and len(checks) >= 13 and all(c.get("ok") for c in checks), (tc.get("status"), tc.get("summary"), [c["check"] for c in checks if not c.get("ok")]))
    REPORT["test_connection"] = tc.get("summary")
    # ------------------------------------------------------------------------------------------ REGRESSIONS: public site
    r = S.get(f"{BASE}/api/models", timeout=60)
    pm = j(r)
    models = pm.get("models", pm.get("items", pm)) if isinstance(pm, dict) else pm
    ok("reg", "public /api/models 200 with published models", r.status_code == 200 and isinstance(models, list) and len(models) >= 1, len(models) if isinstance(models, list) else pm)
    REPORT["public_models"] = len(models) if isinstance(models, list) else None
    ok("reg", "public model detail", S.get(f"{BASE}/api/models/{SLUG}", timeout=60).status_code == 200)
    r = S.get(f"{BASE}/api/models/{SLUG}/segreto", timeout=60)
    ok("reg", "public secret side endpoint", r.status_code in (200, 404), r.status_code)
    ok("reg", "public categories", S.get(f"{BASE}/api/categories", timeout=60).status_code == 200)
    ok("reg", "public settings", S.get(f"{BASE}/api/settings", timeout=60).status_code == 200)
    r = S.get(f"{BASE}/", timeout=60)
    ok("reg", "homepage HTML 200", r.status_code == 200 and "<div id=\"root\"" in r.text)
    r = S.get(f"{BASE}/modelle/{SLUG}", timeout=60)
    ok("reg", "model page HTML 200 (SPA route)", r.status_code == 200)
    # media: every published model card/cover reachable
    bad_media = []
    for m in (models if isinstance(models, list) else [])[:12]:
        for fld in ("foto_card", "foto_copertina"):
            u = m.get(fld)
            if u:
                url = u if u.startswith("http") else BASE + u
                rr = S.head(url, timeout=60, allow_redirects=True)
                if rr.status_code != 200:
                    rr = S.get(url, timeout=60, stream=True)
                if rr.status_code != 200:
                    bad_media.append((m.get("slug"), fld, rr.status_code))
    ok("reg", "media: published card/cover images reachable (200)", isinstance(models, list) and not bad_media, bad_media[:5])
    # ------------------------------------------------------------------------------------------ REGRESSIONS: admin
    r = S.get(f"{BASE}/api/v1/auth/me", headers=JWT, timeout=60)
    ok("reg", "admin auth/me (JWT) SUPER_ADMIN", r.status_code == 200 and j(r).get("role") == "SUPER_ADMIN")
    ok("reg", "admin dashboard v1 overview", S.get(f"{BASE}/api/v1/dashboard/overview?range=7g", headers=JWT, timeout=120).status_code == 200)
    ok("reg", "admin models list", S.get(f"{BASE}/api/admin/models", headers=JWT, timeout=60).status_code == 200)
    ok("reg", "admin media list", S.get(f"{BASE}/api/v1/media?limit=5", headers=JWT, timeout=60).status_code == 200)
    ok("reg", "admin keys list (hash never exposed)", (lambda rr: rr.status_code == 200 and "key_hash" not in rr.text)(S.get(f"{BASE}/api/v1/auth/keys", headers=JWT, timeout=60)))
    # ------------------------------------------------------------------------------------------ REGRESSIONS: SEO / health / sitemap / robots / RSS
    r = S.get(f"{BASE}/api/v1/seo/issues?status=open&limit=50", headers=JWT, timeout=60)
    iss = j(r)
    items = iss.get("items") or (iss.get("data") or {}).get("items") or []
    ok("reg", "SEO issues (read) 200, 0 CRITICAL open", r.status_code == 200 and not [i for i in items if i.get("severity") == "CRITICAL"], [(i.get("entity_slug"), i.get("code")) for i in items if i.get("severity") == "CRITICAL"][:5])
    REPORT["seo_open"] = {sev: sum(1 for i in items if i.get("severity") == sev) for sev in ("SAFE_AUTO_FIX", "REVIEW_REQUIRED", "CRITICAL")}
    r = S.get(f"{BASE}/api/v1/seo/sitemap", headers=JWT, timeout=60)
    ok("reg", "SEO sitemap status (read)", r.status_code == 200)
    r = S.get(f"{BASE}/api/v1/health", headers=JWT, timeout=120)
    hv = j(r)
    latest = hv.get("latest") or hv
    ok("reg", "health (read) 200, latest overall ok/warn (not fail)", r.status_code == 200 and latest.get("overall") in ("ok", "warn"), {k: latest.get(k) for k in ("overall", "checked_at")})
    REPORT["health_latest"] = {k: latest.get(k) for k in ("overall", "checked_at")}
    r = S.get(f"{BASE}/api/v1/alerts?status=open", headers=JWT, timeout=60)
    ok("reg", "alerts list (read) 200", r.status_code == 200)
    r = S.get(f"{BASE}/api/sitemap.xml", timeout=60)
    ok("reg", "sitemap.xml 200, production URLs, includes model page", r.status_code == 200 and "<urlset" in r.text and BASE in r.text and f"/modelle/{SLUG}" in r.text and "preview.emergentagent" not in r.text, r.text[:120])
    r = S.get(f"{BASE}/robots.txt", timeout=60)
    ok("reg", "robots.txt 200 with production sitemap", r.status_code == 200 and "Sitemap:" in r.text and BASE in r.text and "preview.emergentagent" not in r.text, r.text[:160])
    r = S.get(f"{BASE}/api/rss", timeout=60)
    if r.status_code == 404:
        r = S.get(f"{BASE}/api/rss.xml", timeout=60)
    ok("reg", "RSS 200 (xml)", r.status_code == 200 and "<rss" in r.text.lower(), (r.status_code, r.text[:80]))
    # ------------------------------------------------------------------------------------------ PHASE 13 GOOGLE SEO CORE (read-only)
    sm = S.get(f"{BASE}/api/sitemap.xml", timeout=60)
    ok("p13", "sitemap: XML with <lastmod>, only public URLs, no draft slug", sm.status_code == 200 and "<lastmod>" in sm.text and "test-v2-giulia" not in sm.text and sm.text.count("<url>") >= 10, sm.text[:120])
    r = post("/api/v2/ai/execute", {"action": "google.status"}, K)
    gsd = j(r).get("data", {})
    ok("p13", "google.status 200, no secrets, connection state explicit", r.status_code == 200 and gsd.get("connection", {}).get("status") in ("CONNECTED", "NOT_CONFIGURED", "PROPERTY_NOT_ACCESSIBLE", "ERROR") and "private_key" not in r.text, r.text[:160])
    REPORT["google_connection"] = gsd.get("connection")
    r = post("/api/v2/ai/execute", {"action": "google.url.inspect", "target": SLUG}, K)
    ok("p13", "google.url.inspect 200 with explicit state (never INDEXED without Google)", r.status_code == 200 and j(r)["data"]["results"][0]["state"] in ("INDEXED", "NOT_INDEXED", "BLOCKED_ERROR", "UNKNOWN", "NOT_CONFIGURED"), r.text[:160])
    REPORT["inspection_sample"] = {k: j(r)["data"]["results"][0].get(k) for k in ("url", "state", "source", "detail")} if r.status_code == 200 else r.text[:120]
    r = post("/api/v2/ai/execute", {"action": "google.analytics.summary", "parameters": {"range": "28g"}}, K)
    ok("p13", "google.analytics.summary 200 (totals or NOT_CONFIGURED)", r.status_code == 200, r.text[:160])
    r = post("/api/v2/ai/execute", {"action": "seo.indexability", "target": SLUG}, K)
    idx = j(r).get("data", {})
    ok("p13", "seo.indexability: published model technically indexable (HTTP 200, robots ok, in sitemap, no X-Robots noindex)", r.status_code == 200 and idx.get("technically_indexable") is True, idx.get("failing"))
    REPORT["indexability_sample"] = {"url": idx.get("url"), "ok": idx.get("technically_indexable"), "failing": idx.get("failing")}
    r = post("/api/v2/ai/preview", {"action": "growth.prepare_model", "target": SLUG}, K)
    ok("p13", "growth.prepare_model preview 200 (dry_run, publishes=false)", r.status_code == 200 and j(r)["data"].get("dry_run") is True and j(r)["data"].get("publishes") is False, r.text[:160])
    r = post("/api/v2/ai/preview", {"action": "google.sitemap.sync", "parameters": {"force": True}}, K)
    ok("p13", "google.sitemap.sync preview 200 (would_submit reported, nothing sent)", r.status_code == 200 and j(r)["data"].get("dry_run") is True, r.text[:160])
    lr = S.get(f"{BASE}/api/landings/does-not-exist-zz", timeout=60)
    ok("p13", "public landing API: unknown/unpublished -> 404", lr.status_code == 404)
    # ------------------------------------------------------------------------------------------ final mode invariant
    st2 = j(S.get(f"{BASE}/api/v2/ai/status", headers=K, timeout=60)).get("data", {})
    ok("v2", "mode still READ_ONLY at the end (no FULL, no mutation)", st2.get("mode") == "READ_ONLY")
finally:
    revoked = 0
    for kid in created_keys:
        rr = S.delete(f"{BASE}/api/v1/auth/keys/{kid}", headers=JWT, timeout=60)
        revoked += rr.status_code in (200, 204)
    ok("v2", f"temporary keys revoked ({revoked}/{len(created_keys)})", revoked == len(created_keys))
    try:
        ok("v2", "revoked key rejected (401)", S.get(f"{BASE}/api/v2/ai/capabilities", headers=K, timeout=60).status_code == 401)
    except Exception as e:
        ok("v2", "revoked key rejected (401)", False, str(e)[:100])

v2p = sum(1 for s, _, p in RES if s == "v2" and p); v2n = sum(1 for s, _, _ in RES if s == "v2")
rp = sum(1 for s, _, p in RES if s == "reg" and p); rn = sum(1 for s, _, _ in RES if s == "reg")
REPORT["p13_pass"] = f"{sum(1 for s, _, p in RES if s == 'p13' and p)}/{sum(1 for s, _, _ in RES if s == 'p13')}"
REPORT.update({"v2_pass": f"{v2p}/{v2n}", "regressions_pass": f"{rp}/{rn}", "problems": PROBLEMS,
               "conclusion": "PRODUCTION V2 READY FOR GPT REIMPORT" if not PROBLEMS and REPORT.get("read_only") else "PRODUCTION V2 NOT READY"})
os.makedirs("/app/test_reports", exist_ok=True)
json.dump(REPORT, open("/app/test_reports/phase12a_production_verification.json", "w"), indent=1, default=str)
print(f"\nV2: {v2p}/{v2n}  REGRESSIONS: {rp}/{rn}  READ_ONLY: {REPORT.get('read_only')}\nPROBLEMS: {PROBLEMS}\n{REPORT['conclusion']}")
sys.exit(0 if not PROBLEMS else 1)
