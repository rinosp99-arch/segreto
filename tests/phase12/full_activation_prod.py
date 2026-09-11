"""Phase 12A - FULL BUSINESS ACCESS activation check in PRODUCTION (user-authorized).

Steps (all through the public API, admin JWT + a TEMPORARY FULL key that is revoked at the end; the definitive
'ChatGPT Production FULL' key is created by the admin in /admin/motore so the raw key is displayed once to a human only):
 1. temporary key with the FULL business preset (AI_OPERATOR_SCOPES + landing:publish) -> catalog: 97 capabilities, all execute_access=full
 2. ai_write_enabled=true (mode FULL); READ_ONLY key stays active
 3. REAL creation of TEST V2 GIULIA via models.prepare_complete (draft, never published, no media), REVIEW fields approved
 4. verifications: admin presence, not public, actor, audit, session_id, rollback available (dry_run plan only), 10 real models untouched
 5. FULL key really usable: reads executed + previews on the draft for a representative set of business capabilities
Never prints a key. Never touches the 10 real models. No rollback (the user keeps/deletes the draft manually).
"""
import hashlib
import json
import os
import sys
import time
import uuid

import requests

sys.path.insert(0, "/app/tests")
sys.path.insert(0, "/app/backend")
from _creds import admin_credentials  # noqa: E402
from v1_security import AI_OPERATOR_SCOPES  # noqa: E402

BASE = os.environ.get("BASE_URL", "https://secret-side.emergent.host").rstrip("/")
S = requests.Session()
RES, REPORT = [], {"base": BASE, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
NAME = "TEST V2 GIULIA"
SID = f"ses_full_activation_{uuid.uuid4().hex[:8]}"


def ok(name, cond, extra=""):
    RES.append({"check": name, "result": "PASS" if cond else "FAIL", "note": str(extra)[:300]})
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  -> {str(extra)[:220]}" if not cond and extra else ""))


def j(r):
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:300]}


def code(r):
    d = j(r).get("detail", j(r))
    return d.get("code") if isinstance(d, dict) else None


def post(path, body, headers, retries=3):
    for _ in range(retries):
        r = S.post(f"{BASE}{path}", json=body, headers=headers, timeout=180)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "20")) + 1)
            continue
        return r
    return r


r = S.post(f"{BASE}/api/admin/login", json=admin_credentials(), timeout=30)
assert r.status_code == 200, "admin login failed"
JWT = {"Authorization": f"Bearer {r.json().get('token') or r.json().get('access_token')}"}


def admin_models():
    am = j(S.get(f"{BASE}/api/admin/models", headers=JWT, timeout=60))
    return am.get("items", am) if isinstance(am, dict) else am


def real_models_hash():
    items = [m for m in admin_models() if m.get("slug") in REAL_SLUGS]
    return hashlib.sha256(json.dumps(sorted(items, key=lambda m: m["slug"]), sort_keys=True, default=str).encode()).hexdigest()[:16]


pm0 = j(S.get(f"{BASE}/api/models", timeout=60))
public0 = sorted(m["slug"] for m in pm0.get("items", []))
REAL_SLUGS = set(m.get("slug") for m in admin_models())
REPORT["real_models_before"] = sorted(REAL_SLUGS)
h0 = real_models_hash()
assert len(REAL_SLUGS) == 10, REAL_SLUGS

SCOPES = list(AI_OPERATOR_SCOPES) + ["landing:publish"]
REPORT["full_scopes"] = SCOPES
r = S.post(f"{BASE}/api/v1/auth/keys", json={"name": "ChatGPT Production FULL (verifica Emergent, temporanea)", "role": "AI_OPERATOR", "source": "chatgpt", "scopes": SCOPES, "rate_limit_per_min": 120}, headers=JWT, timeout=30)
assert r.status_code in (200, 201), r.text[:200]
KID, K = r.json()["id"], {"Authorization": f"Bearer {r.json()['api_key']}"}
ok("temporary FULL key created with the FULL business preset (47 scopes, role AI_OPERATOR)", len(SCOPES) == 47 and set(r.json().get("scopes") or SCOPES) == set(SCOPES), len(r.json().get("scopes") or []))
try:
    # ------------------------------------------------------------------ 1. catalog visibility in FULL preset
    cat = j(S.get(f"{BASE}/api/v2/ai/capabilities?compact=false", headers=K, timeout=60)).get("data", {})
    caps = cat.get("capabilities", [])
    not_full = [(c["id"], c.get("missing_scopes_execute")) for c in caps if c.get("execute_access") != "full"]
    REPORT["capabilities_visible"] = len(caps)
    REPORT["capabilities_not_full"] = not_full
    REPORT["by_risk"] = {k: sum(1 for c in caps if c["risk"] == k) for k in ("SAFE", "REVIEW_REQUIRED", "CRITICAL")}
    REPORT["review_required"] = sorted(c["id"] for c in caps if c["risk"] == "REVIEW_REQUIRED")
    ok("FULL key sees all 97 registry capabilities, every one execute_access=full, 0 CRITICAL exposed", len(caps) == 97 and not not_full and REPORT["by_risk"]["CRITICAL"] == 0, (len(caps), not_full[:5]))
    adm = j(S.get(f"{BASE}/api/v2/ai/admin/capabilities", headers=JWT, timeout=60))
    ok("registry 97 bound / 0 unbound", adm.get("bound") == 97 and not adm.get("unbound"))
    # CRITICAL surface stays out even for FULL: not in registry -> UNKNOWN_CAPABILITY; security flags refused
    for act in ("backup.restore", "models.hard_delete", "keys.create", "users.create", "shell.exec", "config.set_secret"):
        rr = post("/api/v2/ai/preview", {"action": act, "parameters": {}}, K)
        ok(f"CRITICAL/non-business '{act}' not exposed (404 UNKNOWN_CAPABILITY)", rr.status_code == 404, rr.text[:120])
    rr = post("/api/v2/ai/preview", {"action": "flags.set", "parameters": {"flag": "ai_write_enabled", "value": False}}, K)
    ok("security flag ai_write_enabled not manageable by AI even in FULL preset", rr.status_code in (400, 403, 422) and "ai_write_enabled" in rr.text, rr.text[:160])
    # ------------------------------------------------------------------ 2. activate FULL (mode)
    rr = S.patch(f"{BASE}/api/v1/ai/control", json={"ai_write_enabled": True}, headers=JWT, timeout=60)
    ok("PATCH ai_write_enabled=true (JWT, audited)", rr.status_code == 200, rr.text[:160])
    st = j(S.get(f"{BASE}/api/v2/ai/status", headers=K, timeout=60)).get("data", {})
    ok("getSystemStatus mode=FULL", st.get("mode") == "FULL", st.get("mode"))
    REPORT["mode_after"] = st.get("mode")
    # ------------------------------------------------------------------ 3. REAL TEST V2 GIULIA (draft)
    cats = j(S.get(f"{BASE}/api/categories", timeout=60))
    cats = cats.get("items", cats) if isinstance(cats, dict) else cats
    cat_slug = next((c.get("slug") for c in cats if c.get("slug")), None)
    fields = {"nome_artistico": "Test V2 Giulia", "frase": "Quello che non vedi è la parte migliore.", "bio": "Ventisei anni, Milano. Di giorno una cosa, di notte un'altra.",
              "bio_segreta": "Qui le regole le decido io.", "onlyfans_url": "https://onlyfans.com/testv2giulia", "cta_testo": "ENTRA NEL MIO LATO SEGRETO",
              "teaser_copy": "Qui posso mostrarti solo fino a questo punto.", "badge": "Nuova", "badge_tipo": "editoriale", "tag": ["milano", "test-v2"],
              "tema": {"preset": "bordeaux", "glow": True, "grain": 0.08, "frase_attivazione": "NON DOVRESTI PREMERLO"},
              "regia": {"fumo": 0.5, "luci": 0.6, "glow": 0.5, "movimento": 0.4, "audio": {"traccia": "velluto-nero", "volume": 0.25, "attiva": True}},
              "cta_temporizzata": {"attiva": True, "ritardo_secondi": 20, "testo": "Continua con me"}, "messaggio_35s": {"attivo": True, "timer": 35, "testo": "Ti stavo aspettando."},
              "social": {"instagram": "https://instagram.com/testv2giulia"},
              "seo": {"title": "Test V2 Giulia | LATO SEGRETO", "meta_description": "Il lato segreto di Test V2 Giulia: foto, video e contenuti riservati.", "keywords": ["test v2 giulia", "lato segreto"], "topics": ["editoriale"], "alt_default": "Test V2 Giulia ritratto"}}
    if cat_slug:
        fields["categorie"] = [cat_slug]
    body = {"action": "models.prepare_complete", "parameters": {"nome": NAME, "fields": fields, "seo_safe_fix": True}, "session_id": SID, "reason": "Primo test FULL: crea TEST V2 GIULIA completa e lasciala in bozza"}
    rr = post("/api/v2/ai/preview", body, K)
    pv = j(rr)
    ok("preview before execute (FULL key) -> 200, would_create, publishes=false", rr.status_code == 200 and pv.get("ok") and pv["data"]["would_create"] and pv["data"]["publishes"] is False, rr.text[:200])
    REPORT["preview_plan"] = pv.get("data", {}).get("plan")
    rr = post("/api/v2/ai/execute", body, K)
    ex = j(rr)
    REPORT["execute_summary"] = ex.get("summary")
    ok("EXECUTE models.prepare_complete -> 200, draft created, published=false", rr.status_code == 200 and ex.get("ok") and ex["data"].get("published") is False and ex["data"].get("id"), rr.text[:300])
    MID, SLUG = ex.get("data", {}).get("id"), ex.get("data", {}).get("slug")
    REPORT["draft"] = {"id": MID, "slug": SLUG, "stato": ex.get("data", {}).get("stato"), "workflow_status": ex.get("data", {}).get("workflow_status"), "fields_applied": ex.get("data", {}).get("fields_applied"), "fields_pending_approval": ex.get("data", {}).get("fields_pending_approval")}
    ok("rollback metadata available for the session", ex.get("data", {}).get("rollback", {}).get("available") is True and ex["data"]["rollback"].get("undo"), ex.get("data", {}).get("rollback"))
    # REVIEW fields -> approval proposal -> approve (same key, token)
    if ex.get("approval_required") and ex.get("approval", {}).get("token"):
        ap = ex["approval"]
        rr = post(f"/api/v2/ai/approvals/{ap['id']}/approve", {"token": ap["token"]}, K)
        ok("REVIEW fields approved via approveApproval (token) -> applied", rr.status_code == 200 and j(rr).get("ok"), rr.text[:200])
        REPORT["approval"] = {"id": ap["id"], "fields": ap.get("fields") or ap.get("changes"), "result": j(rr).get("summary")}
    else:
        ok("REVIEW fields approval proposal present (frase/onlyfans_url are REVIEW)", False, ex.get("approval_required"))
    # ------------------------------------------------------------------ 4. verifications
    am = admin_models()
    draft = next((m for m in am if m.get("id") == MID or m.get("slug") == SLUG), None)
    ok("draft present in admin", bool(draft), SLUG)
    ok("draft NOT published (stato bozza)", draft and draft.get("stato") == "bozza", draft and draft.get("stato"))
    pm1 = j(S.get(f"{BASE}/api/models", timeout=60))
    public1 = sorted(m["slug"] for m in pm1.get("items", []))
    ok("public site unchanged (same 10 published slugs, draft not public)", public1 == public0 and SLUG not in public1 and pm1.get("total") == pm0.get("total"), (pm1.get("total"), SLUG in public1))
    ok("public detail of the draft -> 404", S.get(f"{BASE}/api/models/{SLUG}", timeout=60).status_code == 404)
    ok("10 real models untouched (admin docs hash identical)", real_models_hash() == h0)
    acts = j(S.get(f"{BASE}/api/v1/ai/actions?limit=30", headers=K, timeout=60)).get("data", {})
    acts = acts.get("items") or acts.get("actions") or []
    mine = [a for a in acts if a.get("session_id") == SID]
    ok("audit present: actions with session_id, actor = FULL key, prepare_complete + approval", mine and all("ChatGPT Production FULL" in str(a.get("actor")) for a in mine) and any(a.get("action") == "models.prepare_complete" for a in mine), [(a.get("action"), a.get("actor"), a.get("ok")) for a in mine][:6])
    REPORT["audit_sample"] = [{"action": a.get("action"), "actor": a.get("actor"), "ok": a.get("ok"), "session_id": a.get("session_id"), "request_id": a.get("request_id")} for a in mine][:8]
    rr = post("/api/v2/ai/rollback", {"session_id": SID, "dry_run": True}, K)
    rb = j(rr)
    ok("rollback available (dry_run plan only, NOT executed)", rr.status_code == 200 and rb.get("ok") and (rb.get("data", {}).get("versions") or rb.get("data", {}).get("plan") or rb.get("data", {}).get("would_undo") or rb.get("data", {}).get("count")), rr.text[:200])
    REPORT["rollback_plan"] = {k: rb.get("data", {}).get(k) for k in ("dry_run", "count", "versions", "would_undo", "secondary") if k in rb.get("data", {})}
    ok("draft still present after rollback preview", any(m.get("id") == MID for m in admin_models()))
    vers = j(S.get(f"{BASE}/api/v1/models/{MID}/versions", headers=JWT, timeout=60))
    ok("version history recorded for the draft", (vers.get("total") or len(vers.get("items", vers) if isinstance(vers, (list, dict)) else [])) >= 1, str(vers)[:120])
    # ------------------------------------------------------------------ 5. FULL key really usable (reads executed; writes previewed on the draft only)
    reads = [("models.list", None, {}), ("models.get", SLUG, {}), ("models.validate", SLUG, {}), ("media.list", None, {"limit": 5}), ("filmstrip.get_config", None, {}), ("settings.get", None, {}),
             ("config.get", None, {}), ("flags.list", None, {}), ("categories.list", None, {}), ("tags.list", None, {}), ("seo.audit", SLUG, {}), ("seo.issues", None, {"limit": 5}), ("seo.sitemap_status", None, {}),
             ("seo.redirect.list", None, {}), ("landing.list", None, {}), ("alerts.list", None, {}), ("jobs.list", None, {}), ("backup.list", None, {}), ("admins.list", None, {}), ("media.broken", None, {})]
    fails = []
    for act, tgt, prm in reads:
        rr = post("/api/v2/ai/execute", {"action": act, "target": tgt, "parameters": prm}, K)
        if rr.status_code != 200 or not j(rr).get("ok"):
            fails.append((act, rr.status_code, rr.text[:80]))
    ok(f"FULL key executes {len(reads)} read/business capabilities (200)", not fails, fails)
    previews = [("models.update", SLUG, {"changes": {"badge": "Anteprima"}}), ("models.set_seo", SLUG, {"values": {"title": "Test V2 Giulia | LATO SEGRETO"}}), ("models.set_cta", SLUG, {"values": {"attiva": True, "ritardo_secondi": 25, "testo": "Continua"}}), ("models.publish", SLUG, {}),
                ("models.feature", SLUG, {}), ("models.clone", SLUG, {"nome": "Clone anteprima"}), ("homepage.reorder_models", None, {"order": public0[:3]}), ("filmstrip.set_config", None, {"config": {"velocita": 1}}),
                ("categories.create", None, {"nome": "Anteprima Cat"}), ("seo.safe_fix", SLUG, {}), ("seo.internal_links", SLUG, {}), ("landing.create", None, {"fields": {"model": SLUG, "h1": "Landing anteprima", "noindex": True}}),
                ("settings.update", None, {"changes": {"brand_name": "LATO SEGRETO"}}), ("system.health_run", None, {}), ("backup.create", None, {}), ("models.unpublish", public0[0], {}), ("media.optimize_all", None, {})]
    pf = []
    for act, tgt, prm in previews:
        rr = post("/api/v2/ai/preview", {"action": act, "target": tgt, "parameters": prm}, K)
        d = j(rr)
        if rr.status_code != 200 or not d.get("ok") or (d.get("data") or {}).get("rollback", {}).get("available") is True:   # a preview never produces rollback versions
            pf.append((act, rr.status_code, rr.text[:80]))
    ok(f"FULL key previews {len(previews)} write capabilities (200 dry_run, nothing written)", not pf, pf)
    ok("10 real models still untouched after previews", real_models_hash() == h0)
    ok("public site still unchanged", sorted(m["slug"] for m in j(S.get(f"{BASE}/api/models", timeout=60)).get("items", [])) == public0)
finally:
    rr = S.delete(f"{BASE}/api/v1/auth/keys/{KID}", headers=JWT, timeout=30)
    ok("temporary FULL key revoked", rr.status_code in (200, 204))
    ks = j(S.get(f"{BASE}/api/v1/auth/keys", headers=JWT, timeout=60))
    active = [k["name"] for k in ks.get("items", ks) if k.get("active") and not k.get("revoked_at")]
    REPORT["active_keys"] = active
    if BASE.endswith("emergent.host"):
        ok("READ_ONLY key still active (fallback)", "ChatGPT Production READ_ONLY" in active, active)
    c = j(S.get(f"{BASE}/api/v1/ai/control", headers=JWT, timeout=60))
    d = c.get("data", c)
    REPORT["flags_after"] = {k: v for k, v in (d.get("flags") or {}).items() if str(k).startswith("ai_")}
    ok("ai_write_enabled=true left active (per user decision)", REPORT["flags_after"].get("ai_write_enabled") is True, REPORT["flags_after"])

n = sum(1 for x in RES if x["result"] == "PASS")
REPORT.update({"checks": RES, "pass": f"{n}/{len(RES)}", "conclusion": "FULL BUSINESS CONTROL READY: YES" if n == len(RES) else "FULL BUSINESS CONTROL READY: NO"})
json.dump(REPORT, open("/app/test_reports/phase12a_full_activation_prod.json", "w"), indent=1, default=str)
print(f"\n{n}/{len(RES)}  {REPORT['conclusion']}")
sys.exit(0 if n == len(RES) else 1)
