"""PHASE 11 - GPT Action simulation (READ_ONLY session) against a LATO SEGRETO deployment.

Simulates EXACTLY what a ChatGPT GPT Action does: HTTPS calls with `Authorization: Bearer <key>` to the operations
declared in /api/v1/ai/openapi-chatgpt.json, and verifies the real chain
  auth -> scope -> resolver -> validation -> action/preview -> audit -> response
plus ZERO business-data mutation (hash of business collections before/after) and secret hygiene.

Usage:  python tests/phase11_gpt_simulation.py            (TEST_BACKEND / TEST_PUBLIC_HOST optional)
Leaves the server in READ_ONLY mode (as required for the first real connection). Creates and revokes its own keys.
Never prints a full API key.
"""
import os, sys, json, uuid, hashlib, asyncio, requests

B = os.environ.get("TEST_BACKEND", "http://localhost:8001")
HOST = os.environ.get("TEST_PUBLIC_HOST", "secret-side.preview.emergentagent.com")
REMOTE = os.environ.get("TEST_REMOTE", "0") == "1" or B.startswith("https://")   # production: no direct Mongo access -> API-based checks
ADMIN_TOKEN = None
import sys as _sys; _sys.path.insert(0, "/app/tests")
from _creds import admin_credentials as _ac
ADMIN = _ac()
BUSINESS = ["models", "files", "landings", "categories", "articles", "settings", "redirects"]
OUT = "/app/test_reports/phase11_simulation.json"
R = []  # matrix rows


def row(test, ok, detail, **kw):
    R.append({"test": test, "result": "PASS" if ok else "FAIL", "detail": detail, **kw})
    print(f"{'PASS' if ok else 'FAIL':4} | {test:<44} | {detail}")


def mask(k):
    return (k[:10] + "…" + "*" * 6) if k else ""


def admin_token():
    r = requests.post(f"{B}/api/admin/login", json=ADMIN, timeout=20); r.raise_for_status()
    return r.json()["token"]


def api_hash():
    """Remote (production) variant: hash of business data as seen through the admin API."""
    A = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    out = {}
    for name, path in (("models", "/api/v1/models?limit=500"), ("landings", "/api/v1/landings?limit=500"), ("files", "/api/v1/media?limit=1000"),
                       ("categories", "/api/categories"), ("articles", "/api/admin/articles"), ("settings", "/api/admin/settings"), ("redirects", "/api/redirects/resolve?path=/x")):
        try:
            r = requests.get(f"{B}{path}", headers=A, timeout=60)
            body = r.json() if r.status_code == 200 else {"status": r.status_code}
        except Exception as e:
            body = {"err": str(e)}
        out[name] = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return out


async def db_hash():
    if REMOTE:
        return api_hash()
    from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
    from motor.motor_asyncio import AsyncIOMotorClient
    c = AsyncIOMotorClient(os.environ["MONGO_URL"]); db = c[os.environ["DB_NAME"]]
    out = {}
    for name in BUSINESS:
        docs = await db[name].find({}, {"_id": 0}).sort("id", 1).to_list(100000)
        out[name] = hashlib.sha256(json.dumps(docs, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return out


async def db_find(col, q):
    if REMOTE:
        A = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        if col == "ai_requests":
            items = requests.get(f"{B}/api/v1/ai/control", headers=A, timeout=60).json().get("requests", [])
        else:
            items = requests.get(f"{B}/api/v1/ai/actions?limit=100", headers=A, timeout=60).json().get("data", {}).get("items", [])
        return [i for i in items if all(i.get(k) == v for k, v in q.items())]
    from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
    from motor.motor_asyncio import AsyncIOMotorClient
    c = AsyncIOMotorClient(os.environ["MONGO_URL"]); db = c[os.environ["DB_NAME"]]
    return await db[col].find(q, {"_id": 0}).to_list(50)


async def db_scan_secret(raw):
    if REMOTE:
        # production: scan everything the API can return about keys/activity/config for the raw key
        A = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        hits = []
        for path in ("/api/v1/auth/keys", "/api/v1/ai/control", "/api/v1/ai/actions?limit=200", "/api/v1/config", "/api/v1/audit?limit=200", "/api/v1/health"):
            try:
                if raw in requests.get(f"{B}{path}", headers=A, timeout=60).text:
                    hits.append(path)
            except Exception:
                pass
        return hits
    from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
    from motor.motor_asyncio import AsyncIOMotorClient
    c = AsyncIOMotorClient(os.environ["MONGO_URL"]); db = c[os.environ["DB_NAME"]]
    hits = []
    for name in await db.list_collection_names():
        async for d in db[name].find({}, {"_id": 0}):
            if raw in json.dumps(d, default=str):
                hits.append(name)
    return hits


def main():
    global ADMIN_TOKEN
    tok = admin_token(); ADMIN_TOKEN = tok
    print(f"Target: {B} (remote={REMOTE})")
    A = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    HDR = {"Host": HOST, "X-Forwarded-Proto": "https"}

    # ---- STEP 11: force READ_ONLY server-side (and leave it) ----
    c = requests.patch(f"{B}/api/v1/ai/control", json={"ai_api_enabled": True, "ai_write_enabled": False}, headers=A, timeout=20).json()
    row("READ_ONLY forzato server-side", c["mode"] == "READ_ONLY" and c["flags"]["ai_write_enabled"] is False, f"mode={c['mode']} flags={c['flags']}")
    ro_scopes = c["setup"]["read_only_scopes"]

    # ---- key with READ_ONLY scopes (simulates the production key; revoked at the end) ----
    k = requests.post(f"{B}/api/v1/auth/keys", json={"name": "ChatGPT Production READ_ONLY (simulazione)", "role": "AI_OPERATOR", "source": "chatgpt", "scopes": ro_scopes}, headers=A, timeout=20).json()
    KEY, KID = k["api_key"], k["id"]
    G = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", **HDR}   # <- exactly what a GPT Action sends
    row("Chiave READ_ONLY creata (mostrata una volta)", KEY.startswith("ls_") and "api_key" in k, f"prefix {mask(KEY)} scopes={len(ro_scopes)}")

    def gpt(method, path, body=None, headers=None, params=None):
        h = {**G, **(headers or {})}
        r = requests.request(method, f"{B}{path}", json=body, headers=h, params=params, timeout=60)
        try:
            return r, r.json()
        except Exception:
            return r, {}

    # ---- STEP 12: kill switch ----
    requests.patch(f"{B}/api/v1/ai/control", json={"ai_api_enabled": False}, headers=A, timeout=20)
    r, j = gpt("GET", "/api/v1/ai/status")
    ks_ok = r.status_code == 503 and j.get("code") == "AI_API_DISABLED"
    legacy = requests.get(f"{B}/api/admin/models", headers=A, timeout=20).status_code
    requests.patch(f"{B}/api/v1/ai/control", json={"ai_api_enabled": True}, headers=A, timeout=20)
    r2, j2 = gpt("GET", "/api/v1/ai/status")
    usage = requests.get(f"{B}/api/v1/auth/keys/{KID}/usage", headers=A, timeout=20).json()
    row("Kill switch OFF -> 503 AI_API_DISABLED", ks_ok, f"status={r.status_code} code={j.get('code')} request_id={j.get('request_id','')[:8]}")
    row("Kill switch: API legacy JWT continuano", legacy == 200, f"GET /api/admin/models -> {legacy}")
    row("Kill switch: audit (error_count chiave, log richiesta)", usage.get("error_count", 0) >= 1 and usage.get("last_error_status") == 503, f"error_count={usage.get('error_count')} last_error_status={usage.get('last_error_status')}")
    row("Kill switch ON -> risposta normale", r2.status_code == 200 and j2["data"]["ai"]["mode"] == "READ_ONLY", f"status={r2.status_code} mode={j2['data']['ai']['mode']}")

    ctrl0 = requests.get(f"{B}/api/v1/ai/control", headers=A, timeout=20).json()
    h0 = asyncio.run(db_hash())

    # ---- STEP 19: first prompt "Controlla lo stato della piattaforma" ----
    rid = f"gpt-sim-{uuid.uuid4().hex[:8]}"
    r, j = gpt("GET", "/api/v1/ai/site-health", headers={"X-Request-ID": rid})
    row("STEP19 site-health (Controlla lo stato)", r.status_code == 200 and j["ok"] and "models" in j["data"], f"{j.get('summary','')[:90]}", request_id=rid)
    row("X-Request-ID coerente response/header", r.headers.get("X-Request-ID") == rid and j["request_id"] == rid, f"header={r.headers.get('X-Request-ID')} body={j['request_id']}")
    r, j = gpt("GET", "/api/v1/ai/capabilities")
    row("capabilities per la chiave", r.status_code == 200 and j["data"]["mode"] == "READ_ONLY" and len(j["data"]["capabilities"]) > 10, f"{len(j['data']['capabilities'])} capacità, mode {j['data']['mode']}, preview_only={len([c for c in j['data']['capabilities'] if c.get('access')=='preview_only'])}")

    # ---- TEST A: "Controlla <modella>" (resolve -> health) - model chosen from the REAL catalog of this deployment ----
    r, j = gpt("GET", "/api/v1/ai/models")
    catalog = j["data"]["items"] if r.status_code == 200 else []
    pub = [m for m in catalog if m.get("workflow_status") in ("PUBLISHED", "ERROR", "READY")] or catalog
    target = pub[0]
    first_name = (target.get("nome_artistico") or target.get("nome") or target["slug"]).strip().split(" ")[0]
    r, j = gpt("POST", "/api/v1/ai/models/find", {"model": first_name})
    if r.status_code == 409:  # first name ambiguous in this catalog -> use the full name
        r, j = gpt("POST", "/api/v1/ai/models/find", {"model": (target.get("nome_artistico") or target.get("nome")).strip()})
    ok_a = r.status_code == 200 and j["data"]["slug"] == target["slug"]
    slug = j.get("data", {}).get("slug") or target["slug"]
    print(f"     target model: '{first_name}' -> {slug} (catalogo: {len(catalog)} modelle)")
    rid_a = f"gpt-A-{uuid.uuid4().hex[:6]}"
    r, j = gpt("GET", f"/api/v1/ai/models/{slug}/health", headers={"X-Request-ID": rid_a})
    row(f"TEST A resolve '{first_name}' + model health", ok_a and r.status_code == 200 and j["ok"] and j["data"]["publication"]["workflow_status"], f"{j.get('summary','')[:100]}", request_id=rid_a)
    logged = asyncio.run(db_find("ai_requests", {"request_id": rid_a}))
    row("TEST A richiesta nel log (actor/key/request_id/status/durata)", bool(logged) and logged[0]["key_id"] == KID and logged[0]["status"] == 200 and "duration_ms" in logged[0] and logged[0]["kind"] == "read", f"{ {k: logged[0][k] for k in ('actor','status','duration_ms','kind','path')} if logged else 'MISSING'}")

    # ---- TEST B: SEO audit ----
    rid_b = f"gpt-B-{uuid.uuid4().hex[:6]}"
    r, j = gpt("POST", "/api/v1/ai/seo/audit", {"model": slug}, headers={"X-Request-ID": rid_b})
    d = j.get("data", {})
    row("TEST B SEO audit (score, SAFE/REVIEW/CRITICAL)", r.status_code == 200 and j["ok"] and "seo_score" in d and "counts" in d, f"score={d.get('seo_score')} counts={d.get('counts')}", request_id=rid_b)
    act = asyncio.run(db_find("ai_actions", {"request_id": rid_b}))
    row("TEST B audit action con stesso request_id", bool(act) and act[0]["action"] == "seo.audit" and act[0]["key_id"] == KID and act[0]["source"] == "chatgpt", f"{ {k: act[0][k] for k in ('actor','action','ok','source')} if act else 'MISSING'}")

    # ---- TEST C: safe fix in READ_ONLY -> only dry_run works ----
    r, j = gpt("POST", f"/api/v1/ai/models/{slug}/seo/apply-safe-fixes")
    blocked_c = r.status_code == 403 and j.get("code") in ("READ_ONLY_MODE", "INSUFFICIENT_SCOPE")
    r2, j2 = gpt("POST", f"/api/v1/ai/models/{slug}/seo/apply-safe-fixes", params={"dry_run": "true"})
    row("TEST C safe-fix reale bloccato", blocked_c, f"status={r.status_code} code={j.get('code')}")
    row("TEST C safe-fix dry_run -> anteprima", r2.status_code == 200 and j2["ok"] and j2["data"]["dry_run"] is True and "would_fix" in j2["data"], f"would_fix={j2.get('data',{}).get('would_fix')} score_before={j2.get('data',{}).get('seo_score_before')}")

    # ---- TEST D: analytics Italy 7d ----
    q = {"metric": "onlyfans_ctr", "group_by": "model", "country": "IT", "period": "7d", "sort": "desc", "limit": 10}
    r, j = gpt("POST", "/api/v1/ai/analytics/query", q)
    d = j.get("data", {})
    row("TEST D analytics strutturata IT 7d", r.status_code == 200 and j["ok"] and "sample_size" in d and "data_available" in d, f"sample_size={d.get('sample_size')} data_available={d.get('data_available')} rows={len(d.get('rows', d.get('items', [])) or [])} limitations={d.get('limitations')}")

    # ---- TEST E: daily summary ----
    r, j = gpt("GET", "/api/v1/ai/daily-summary")
    d = j.get("data", {})
    row("TEST E daily summary", r.status_code == 200 and j["ok"] and all(k in d for k in ("today", "last_7d", "top_models_7d", "seo_issues", "alerts", "backup", "limitations")), j.get("summary", "")[:110])

    # ---- TEST F: recommendations ----
    r, j = gpt("GET", "/api/v1/ai/recommendations")
    items = j.get("data", {}).get("items", [])
    row("TEST F recommendations deterministiche", r.status_code == 200 and j["ok"] and all({"priority", "automatic", "capability_id"} <= set(i) for i in items), f"{len(items)} raccomandazioni: {j.get('summary','')[:80]}")

    # ---- TEST G: publish blocked ----
    r, j = gpt("POST", "/api/v1/ai/models/publish", {"model": slug})
    blocked_g = r.status_code == 403 and j.get("code") in ("READ_ONLY_MODE", "INSUFFICIENT_SCOPE")
    r2, j2 = gpt("POST", "/api/v1/ai/models/publish", {"model": slug, "dry_run": True})
    row("TEST G publish reale bloccato", blocked_g, f"status={r.status_code} code={j.get('code')}")
    row("TEST G publish dry_run = solo readiness", r2.status_code == 200 and (j2.get("code") == "PUBLICATION_BLOCKED" or "già online" in j2.get("summary", "") or j2["data"].get("dry_run")), j2.get("summary", "")[:100])

    # ---- TEST H: upload blocked (even with dry_run) ----
    r, j = gpt("POST", "/api/v1/ai/media/upload", {"model": slug, "slot": "pair", "url": "https://example.com/x.jpg", "dry_run": True})
    row("TEST H upload bloccato anche con dry_run", r.status_code == 403 and j.get("code") in ("READ_ONLY_MODE", "INSUFFICIENT_SCOPE"), f"status={r.status_code} code={j.get('code')}")

    # ---- TEST I: approval preview (REVIEW_REQUIRED) without confirming ----
    r, j = gpt("GET", f"/api/v1/ai/models/{slug}/seo/review")
    rev = [i for i in j.get("data", {}).get("items", []) if i["severity"] == "REVIEW_REQUIRED"]
    if rev:
        r, j = gpt("POST", f"/api/v1/ai/models/{slug}/seo/review/{rev[0]['id']}/preview", {"proposed_value": rev[0].get("suggested_value") or "Francesca Rossi | LATO SEGRETO"})
        ap = j.get("approval") or {}
        ok_i = r.status_code == 200 and j.get("approval_required") and ap.get("token", "").startswith("apr_") and ap.get("expires_at") and "before" in ap and "after" in ap
        row("TEST I approval preview (token, before/after, TTL)", ok_i, f"type={ap.get('type')} expires={ap.get('expires_at','')[:16]} field={j.get('changes',[{}])[0].get('field') if j.get('changes') else None}")
        pend = gpt("GET", "/api/v1/ai/approvals")[1]["data"]["items"]
        row("TEST I approvazione pending senza token esposto", any(p.get("type") == "SEO_REVIEW" and "token" not in p and "token_hash" not in p for p in pend), f"{len(pend)} pending")
        # confirm must be blocked in READ_ONLY (never confirmed in this session)
        r, j = gpt("POST", "/api/v1/ai/approvals/confirm", {"token": ap.get("token", "apr_x")})
        row("TEST I confirm bloccato in READ_ONLY", r.status_code == 403 and j.get("code") == "READ_ONLY_MODE", f"status={r.status_code} code={j.get('code')}")
    else:
        # create a REVIEW proposal via model update preview (bio) - approval flow is prepared but nothing applied
        r, j = gpt("POST", "/api/v1/ai/models/update", {"model": slug, "changes": {"bio": "Bio di anteprima per la sessione READ_ONLY."}, "dry_run": True})
        pol = (j.get("data") or {}).get("policy") or {}
        row("TEST I anteprima REVIEW_REQUIRED (update dry_run)", r.status_code == 200 and pol.get("level") == "REVIEW_REQUIRED" and (j.get("data") or {}).get("approval_required"), f"level={pol.get('level')} fields={pol.get('review_fields')} code={j.get('code')}")

    # ---- ambiguous / not found ----
    # ambiguous reference: a word shared by >= 2 names in THIS catalog (fallback: 2-letter prefix shared)
    import collections, re as _re
    words = collections.Counter(w for m in catalog for w in set(_re.findall(r"[a-z]{3,}", ((m.get("nome_artistico") or "") + " " + (m.get("nome") or "")).lower())))
    amb = next((w for w, n in words.most_common() if n >= 2), None)
    if not amb:
        pref = collections.Counter((m.get("nome_artistico") or m.get("nome") or "")[:2].lower() for m in catalog)
        amb = next((w for w, n in pref.most_common() if n >= 2 and w.strip()), "a")
    r, j = gpt("POST", "/api/v1/ai/models/find", {"model": amb})
    row(f"AMBIGUOUS_REFERENCE mostra alternative ('{amb}')", r.status_code == 409 and j.get("code") == "AMBIGUOUS_REFERENCE" and len(j["data"]["matches"]) >= 2, f"matches={[m['nome'] for m in j.get('data',{}).get('matches',[])]}")
    r, j = gpt("POST", "/api/v1/ai/models/find", {"model": "modella-inesistente-xyz"})
    row("NOT_FOUND per modella inesistente", r.status_code == 404 and j.get("code") == "NOT_FOUND", f"status={r.status_code} code={j.get('code')} (nessun profilo inventato)")

    # ---- idempotency on dry-run ----
    ik = str(uuid.uuid4())
    body = {"model": slug, "changes": {"tag": ["idem-sim"]}, "dry_run": True}
    r1, j1 = gpt("POST", "/api/v1/ai/models/update", body, headers={"Idempotency-Key": ik})
    r2, j2 = gpt("POST", "/api/v1/ai/models/update", body, headers={"Idempotency-Key": ik})
    row("Idempotency-Key replay identico", r1.status_code == 200 and r2.headers.get("Idempotent-Replayed") == "true" and j1["request_id"] == j2["request_id"], f"replayed={r2.headers.get('Idempotent-Replayed')} same_request_id={j1['request_id'] == j2['request_id']}")

    # ---- scope negative (temporary key) ----
    k2 = requests.post(f"{B}/api/v1/auth/keys", json={"name": "sim-scope-min", "role": "AI_OPERATOR", "scopes": ["ai:execute", "system:status"]}, headers=A, timeout=20).json()
    r = requests.post(f"{B}/api/v1/ai/models/find", json={"model": slug}, headers={"Authorization": f"Bearer {k2['api_key']}", **HDR}, timeout=20)
    row("INSUFFICIENT_SCOPE con chiave a scope minimo", r.status_code == 403 and r.json()["code"] == "INSUFFICIENT_SCOPE" and "models:read" in r.json()["data"]["missing_scopes"], f"missing={r.json().get('data',{}).get('missing_scopes')}")
    requests.delete(f"{B}/api/v1/auth/keys/{k2['id']}", headers=A, timeout=20)
    r = requests.get(f"{B}/api/v1/ai/status", headers={"Authorization": f"Bearer {k2['api_key']}", **HDR}, timeout=20)
    row("API_KEY_REVOKED (chiave temporanea)", r.status_code == 401 and r.json()["code"] == "API_KEY_REVOKED", f"status={r.status_code}")
    r = requests.get(f"{B}/api/v1/ai/status", headers=HDR, timeout=20)
    row("AUTH_REQUIRED senza chiave", r.status_code == 401 and r.json()["code"] == "AUTH_REQUIRED", f"status={r.status_code}")
    r = requests.get(f"{B}/api/v1/ai/status", headers={"Authorization": "Bearer ls_wrong", **HDR}, timeout=20)
    row("INVALID_API_KEY con chiave errata", r.status_code == 401 and r.json()["code"] == "INVALID_API_KEY", f"status={r.status_code}")

    # ---- rate limit (controlled, temporary key) ----
    k3 = requests.post(f"{B}/api/v1/auth/keys", json={"name": "sim-rate", "role": "AI_OPERATOR", "scopes": ["ai:execute", "system:status"], "rate_limit_per_min": 12}, headers=A, timeout=20).json()
    codes = [requests.get(f"{B}/api/v1/ai/status", headers={"Authorization": f"Bearer {k3['api_key']}", **HDR}, timeout=20) for _ in range(15)]
    lim = [x for x in codes if x.status_code == 429]
    row("Rate limit 429 + Retry-After (chiave temp 12/min)", bool(lim) and lim[0].headers.get("Retry-After") and lim[0].json()["code"] == "RATE_LIMITED", f"429={len(lim)}/15 retry_after={lim[0].headers.get('Retry-After') if lim else None}")
    requests.delete(f"{B}/api/v1/auth/keys/{k3['id']}", headers=A, timeout=20)

    # ---- zero mutation & metrics & activity ----
    h1 = asyncio.run(db_hash())
    row("ZERO MUTATION collezioni business (hash before/after)", h0 == h1, ", ".join(f"{k}:{'=' if h0[k]==h1[k] else 'CHANGED'}" for k in BUSINESS))
    ctrl1 = requests.get(f"{B}/api/v1/ai/control", headers=A, timeout=20).json()
    m0, m1 = ctrl0["metrics"]["counters"], ctrl1["metrics"]["counters"]
    row("Metriche AI incrementate", m1["requests"] > m0["requests"] and m1["errors"] > m0["errors"] and m1["rate_limited"] > m0["rate_limited"] and m1["mutations"] == m0["mutations"], f"requests +{m1['requests']-m0['requests']} errors +{m1['errors']-m0['errors']} 429 +{m1['rate_limited']-m0['rate_limited']} mutations +{m1['mutations']-m0['mutations']} p50={ctrl1['metrics']['last_hour']['p50_ms']} p95={ctrl1['metrics']['last_hour']['p95_ms']}")
    reqs = [x for x in ctrl1["requests"] if x["key_id"] == KID]
    row("Attività pannello: richieste della chiave visibili", len(reqs) >= 10 and all("request_id" in x and "duration_ms" in x for x in reqs), f"{len(reqs)} richieste visibili (kind: {sorted({x['kind'] for x in reqs})})")
    row("Pannello: last_used_at aggiornato, chiave non leggibile", any(k["id"] == KID and k.get("last_used_at") and "key_hash" not in k and "api_key" not in k for k in ctrl1["keys"]), "solo prefix + metadati")
    row("Pannello: status connected / mode READ_ONLY", ctrl1["status"] == "connected" and ctrl1["mode"] == "READ_ONLY", f"status={ctrl1['status']} mode={ctrl1['mode']}")

    # ---- secret leak scan ----
    hits = asyncio.run(db_scan_secret(KEY))
    row("Chiave in chiaro assente da TUTTE le collection", not hits, f"hits={hits or 'NONE'}")
    logs = ""
    for f in ("/var/log/supervisor/backend.out.log", "/var/log/supervisor/backend.err.log", "/var/log/supervisor/frontend.out.log", "/var/log/supervisor/frontend.err.log"):
        try:
            logs += open(f, errors="ignore").read()[-2_000_000:]
        except Exception:
            pass
    row("Chiave assente dai log supervisor", KEY not in logs, "backend/frontend out+err" if not REMOTE else "log locali (produzione: log non accessibili, verifica tramite API sopra)")
    # frontend bundle / docs
    docs = "".join(open(f, errors="ignore").read() for f in ("/app/CHATGPT_API.md", "/app/SUPER_API.md", "/app/plan.md") if os.path.exists(f))
    row("Chiave assente da docs", KEY not in docs, "CHATGPT_API.md, SUPER_API.md, plan.md")

    # ---- cleanup: revoke simulation key; leave READ_ONLY ON ----
    requests.delete(f"{B}/api/v1/auth/keys/{KID}", headers=A, timeout=20)
    r = requests.get(f"{B}/api/v1/ai/status", headers={"Authorization": f"Bearer {KEY}", **HDR}, timeout=20)
    row("Chiave di simulazione revocata", r.status_code == 401, f"status={r.status_code}")
    final = requests.get(f"{B}/api/v1/ai/control", headers=A, timeout=20).json()
    row("Stato finale: AI ON, mode READ_ONLY", final["flags"]["ai_api_enabled"] and final["mode"] == "READ_ONLY", f"flags={final['flags']}")

    passed = len([x for x in R if x["result"] == "PASS"])
    print(f"\nRESULTS: {passed}/{len(R)} PASS")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"backend": B, "public_host": HOST, "mode_left": final["mode"], "key_prefix_masked": mask(KEY), "results": R, "passed": passed, "total": len(R), "db_hash_before": h0, "db_hash_after": h1}, open(OUT, "w"), indent=1, ensure_ascii=False)
    return 0 if passed == len(R) else 1


def _purge_residue():
    """preview hygiene: remove this harness' revoked keys / soft-deleted test entities (never business data)"""
    try:
        import sys as _s2; _s2.path.insert(0, "/app/tests")
        from _cleanup import purge_test_residue as _purge
        print("residue purge:", _purge())
    except Exception as _e:
        print("residue purge skipped:", str(_e)[:100])


if __name__ == "__main__":
    _rc = main()
    _purge_residue()
    sys.exit(_rc)
