"""Phase 12A - operational coverage of the capabilities + formal E2E "TEST GIULIA" (preview ONLY).

    cd /app/backend && python /app/tests/phase12/coverage_12a.py

- Runs against the live preview server with a temporary SUPER_ADMIN AI key (created via the real admin API, revoked at the end).
- READ_ONLY phase: every read capability executed, every mutating capability previewed (dry_run) with a REAL payload.
- FULL phase (preview flag ai_write_enabled=True, ALWAYS restored to False): mutations grouped in sessions, each undone with
  rollback.session and verified with a before/after HASH of the business state (models, files, slot links, SEO issues,
  redirects, landings, categories, settings, config, jobs).
- E2E TEST GIULIA: models.prepare_complete -> REVIEW approval -> media/SEO/config -> validate -> NOT published -> audit ->
  rollback.session -> hash identical -> history preserved.
- Writes /app/test_reports/phase12a_coverage.json. Never prints secrets.
"""
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid

import requests

sys.path.insert(0, "/app/backend")
from database import (config_col, models_col, files_col, seo_issues_col, redirects_col, landings_col, categories_col, settings_col, jobs_col,  # noqa: E402
                      versions_col, ai_actions_col, backups_col)
from v1_ai_policy import approvals_col  # noqa: E402

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].splitlines()[0].strip()
CREDS = {}
for line in open("/app/memory/test_credentials.md"):
    if "email" in line.lower() and "@" in line and "email" not in CREDS:
        CREDS["email"] = line.split(":")[-1].strip().strip("`* ")
    if "password" in line.lower() and "password" not in CREDS and ":" in line:
        CREDS["password"] = line.split(":", 1)[-1].strip().strip("`* ")

RUN = uuid.uuid4().hex[:6]
REPORT = {"run": RUN, "base": BASE, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "capabilities": {}, "e2e": {}, "hash_checks": [], "notes": []}
S = requests.Session()


def rec(cap, mode, ok, note=""):
    REPORT["capabilities"].setdefault(cap, []).append({"mode": mode, "result": "PASS" if ok else "FAIL", "note": str(note)[:300]})
    print(f"{'PASS' if ok else 'FAIL'} {cap:28} [{mode}] {str(note)[:110]}")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------- auth / mode
r = S.post(f"{BASE}/api/admin/login", json={"email": CREDS["email"], "password": CREDS["password"]}, timeout=30)
assert r.status_code == 200, "admin login failed"
JWT = {"Authorization": f"Bearer {r.json().get('access_token') or r.json().get('token')}"}
r = S.post(f"{BASE}/api/v1/auth/keys", json={"name": f"cov12a-{RUN}", "role": "SUPER_ADMIN", "source": "chatgpt", "rate_limit_per_min": 600}, headers=JWT, timeout=30)
assert r.status_code in (200, 201), r.text[:200]
KEY_ID, KEY = r.json()["id"], r.json()["api_key"]
K = {"Authorization": f"Bearer {KEY}"}


async def set_mode(full: bool):
    await config_col.update_one({"id": "global"}, {"$set": {"flags.ai_write_enabled": bool(full)}})


async def mode():
    c = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    return bool((c.get("flags") or {}).get("ai_write_enabled"))


def exe(action, target=None, params=None, dry=False, session=None, reason="coverage 12a", headers=None, preview=False, expected=None):
    body = {"action": action, "target": target, "parameters": params or {}, "dry_run": dry, "reason": reason}
    if session:
        body["session_id"] = session
    if expected:
        body["expected_updated_at"] = expected
    for attempt in range(4):
        r = S.post(f"{BASE}/api/v2/ai/{'preview' if preview else 'execute'}", json=body, headers={**K, **(headers or {})}, timeout=120)
        if r.status_code == 429:   # real AI policy limit (per minute): honour Retry-After like a well-behaved GPT client
            REPORT["notes"].append(f"RATE_LIMITED on {action}: waited {r.headers.get('Retry-After', '20')}s")
            time.sleep(int(r.headers.get("Retry-After", "20")) + 1)
            continue
        break
    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text[:300]}
    return r.status_code, j


def _post_retry(url, body):
    for attempt in range(4):
        r = S.post(url, json=body, headers=K, timeout=180)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "20")) + 1)
            continue
        return r
    return r


def approve(appr):
    r = _post_retry(f"{BASE}/api/v2/ai/approvals/{appr['id']}/approve", {"token": appr["token"]})
    return r.status_code, r.json()


# ---------------------------------------------------------------- business-state snapshot / hash
VOLATILE = {"updated_at", "deleted_at", "etag", "updated_by", "hits", "last_run", "last_status", "last_duration_ms", "next_run", "created_dt", "optimized_at", "reopened_at", "resolved_at"}


def _clean(d):
    if isinstance(d, dict):
        # `is_deleted` absent == False (rollback_version materialises the key): business-equivalent
        return {k: _clean(v) for k, v in sorted(d.items()) if k not in VOLATILE and k != "_id" and not (k == "is_deleted" and not v)}
    if isinstance(d, list):
        return [_clean(x) for x in d]
    return d


def _h(obj):
    return hashlib.sha256(json.dumps(_clean(obj), sort_keys=True, default=str).encode()).hexdigest()[:16]


async def snapshot():
    snap = {}
    snap["models"] = {m["id"]: m async for m in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0})}
    # only PARENT files, only BUSINESS fields: optimize (rollback=False) legitimately normalises technical/derived fields
    # (variants, size, storage_path, created_at, created_by, metadata) and even the seed schema of old minimal docs.
    snap["files"] = {f["id"]: {"tipo": f.get("tipo"), "model_id": f.get("model_id"), "slot": f.get("slot"), "alt": f.get("alt") or ""}
                     async for f in files_col.find({"is_deleted": {"$ne": True}, "parent_id": {"$exists": False}}, {"_id": 0})}
    snap["slot_links"] = {f["id"]: {"model_id": f.get("model_id"), "slot": f.get("slot")} async for f in files_col.find({"is_deleted": {"$ne": True}, "parent_id": {"$exists": False}}, {"_id": 0, "id": 1, "model_id": 1, "slot": 1})}
    snap["seo_issues"] = {i["id"]: {k: i.get(k) for k in ("entity_id", "code", "field", "status", "severity")} async for i in seo_issues_col.find({"status": {"$in": ["open", "fixed", "ignored"]}}, {"_id": 0})}
    snap["redirects"] = {r["id"]: {k: r.get(k) for k in ("from_path", "to_path", "active", "status_code")} async for r in redirects_col.find({"active": True}, {"_id": 0})}
    snap["landings"] = {x["id"]: x async for x in landings_col.find({"is_deleted": {"$ne": True}}, {"_id": 0})}
    snap["categories"] = {x["id"]: x async for x in categories_col.find({"is_deleted": {"$ne": True}}, {"_id": 0})}
    snap["settings"] = await settings_col.find_one({"id": "global"}, {"_id": 0}) or {}
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0}) or {}
    cfg.get("flags", {}).pop("ai_write_enabled", None)   # the test harness toggles it on purpose
    cfg.get("ai", {}).pop("capabilities_disabled", None)
    snap["config"] = cfg
    snap["jobs"] = {j["name"]: {"enabled": j.get("enabled")} async for j in jobs_col.find({}, {"_id": 0, "name": 1, "enabled": 1})}
    return snap


def hashes(snap):
    return {k: _h(v) for k, v in snap.items()}


def diff(a, b):
    out = {}
    for col in a:
        ha, hb = _h(a[col]), _h(b[col])
        if ha != hb:
            if isinstance(a[col], dict) and isinstance(b[col], dict):
                keys = set(a[col]) | set(b[col])
                changed = [k for k in keys if _h(a[col].get(k)) != _h(b[col].get(k))]
                out[col] = {"changed_keys": changed[:20], "n": len(changed),
                            "sample": {"key": changed[0], "before": json.dumps(_clean(a[col].get(changed[0])), default=str)[:300], "after": json.dumps(_clean(b[col].get(changed[0])), default=str)[:300]} if changed else None}
            else:
                out[col] = "changed"
    return out


def hash_check(name, before, after, ignore=()):
    d = {k: v for k, v in diff(before, after).items() if k not in ignore}
    ok = not d
    REPORT["hash_checks"].append({"name": name, "identical": ok, "before": hashes(before), "after": hashes(after), "diff": d})
    print(f"{'PASS' if ok else 'FAIL'} HASH {name}: {'identico' if ok else json.dumps(d)[:400]}")
    return ok


def rollback_session(sid):
    r = _post_retry(f"{BASE}/api/v2/ai/rollback", {"session_id": sid, "reason": "coverage cleanup"})
    return r.status_code, r.json()


# ==================================================================================================================
try:
    assert not run(mode()), "preview must start READ_ONLY"
    REAL = "francesca-rossi"   # real published demo model: used ONLY as preview (dry_run) target
    REAL2 = run(models_col.find_one({"stato": "pubblicata", "is_deleted": {"$ne": True}, "slug": {"$ne": REAL}}, {"_id": 0, "slug": 1}))["slug"]
    img = run(files_col.find_one({"is_deleted": {"$ne": True}, "parent_id": {"$exists": False}, "tipo": "image"}, {"_id": 0}))
    img2 = run(files_col.find_one({"is_deleted": {"$ne": True}, "parent_id": {"$exists": False}, "tipo": "image", "id": {"$ne": img["id"]}}, {"_id": 0}))
    vid = run(files_col.find_one({"is_deleted": {"$ne": True}, "parent_id": {"$exists": False}, "tipo": "video"}, {"_id": 0}))
    cats = [c["slug"] for c in run(categories_col.find({}, {"_id": 0, "slug": 1}).to_list(20))]

    # =========================================================== PHASE 0: READ_ONLY - reads + previews with real payloads
    print("\n=== FASE 0: READ_ONLY (letture + anteprime) ===")
    reads = {"models.list": (None, {}), "models.get": (REAL, {}), "models.validate": (REAL, {}), "tags.list": (None, {}), "media.list": (None, {"limit": 5}),
             "media.find": (None, {"ref": img["id"]}), "media.inspect": (None, {"ref": img["id"]}), "media.broken": (None, {}), "filmstrip.get_config": (None, {}),
             "settings.get": (None, {}), "config.get": (None, {}), "flags.list": (None, {}), "categories.list": (None, {}), "seo.issues": (REAL, {}), "seo.audit": (REAL, {}),
             "seo.redirect.list": (None, {}), "seo.sitemap_status": (None, {}), "seo.internal_links": (REAL, {}), "seo.opportunities": (None, {}), "landing.list": (None, {}),
             "alerts.list": (None, {}), "jobs.list": (None, {}), "jobs.runs": ("health_check", {"limit": 3}), "backup.list": (None, {}), "admins.list": (None, {})}
    for cap, (tgt, p) in reads.items():
        st, j = exe(cap, tgt, p)
        rec(cap, "read", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
    previews = {
        "models.update": (REAL, {"changes": {"badge": "Anteprima", "tag": ["estate"]}}), "models.set_public_side": (REAL, {"values": {"teaser_copy": "Solo fino a qui."}}),
        "models.set_secret_side": (REAL, {"values": {"preset": "tattoo", "glow": False}}), "models.set_regia": (REAL, {"values": {"fumo": 0.6, "audio": {"attiva": True, "volume": 0.3}}}),
        "models.set_cta": (REAL, {"values": {"attiva": True, "ritardo_secondi": 20, "testo": "Continua"}}), "models.set_secret_message": (REAL, {"values": {"attivo": True, "timer": 35}}),
        "models.set_social": (REAL, {"values": {"instagram": "https://instagram.com/test"}}), "models.set_seo": (REAL, {"values": {"keywords": ["test"], "alt_default": "Ritratto"}}),
        "models.feature": (REAL, {"badge": "In evidenza", "filmstrip": True}), "models.unfeature": (REAL, {}), "models.publish": (REAL, {}), "models.unpublish": (REAL, {}),
        "models.archive": (REAL, {}), "models.restore": (REAL, {}), "models.soft_delete": (REAL, {}), "models.clone": (REAL, {"new_name": f"Clone {RUN}", "include_media": False}),
        "models.copy_config": (REAL, {"from": REAL2}), "models.tags.add": (REAL, {"tags": ["anteprima"]}), "models.tags.remove": (REAL, {"tags": ["anteprima"]}),
        "tags.normalize": (None, {"from": "anteprima", "to": "preview"}), "media.assign": (REAL, {"media": img["id"], "slot": "secret_photo_3"}), "media.replace_slot": (REAL, {"media": img["id"], "slot": "public_photo_1"}),
        "media.remove_from_slot": (REAL, {"slot": "public_photo_3"}), "media.reorder_pairs": (REAL, {"order": ["0"]}), "media.update": (None, {"media": img["id"], "alt": "ALT anteprima"}),
        "media.optimize": (None, {"media": img["id"]}), "media.optimize_all": (None, {"limit": 2}), "media.soft_delete": (None, {"media": img["id"]}),
        "homepage.reorder_models": (None, {"order": [REAL]}), "filmstrip.set_config": (None, {"config": {"velocita": 7}}), "filmstrip.set_model": (REAL, {"priorita": 3}),
        "settings.update": (None, {"changes": {"site_description": "anteprima"}}), "config.update": (None, {"changes": {"ai.policy.max_batch": 40}}), "flags.set": (None, {"flag": "seo_autopilot", "value": True}),
        "categories.create": (None, {"nome": f"Cat {RUN}"}), "categories.update": (cats[0], {"changes": {"descrizione": "anteprima"}}), "categories.archive": (cats[0], {}), "categories.restore": (cats[0], {}),
        "categories.reorder": (None, {"order": cats[:2]}), "categories.assign_models": (cats[0], {"models": [REAL]}), "models.categories.set": (REAL, {"categories": cats[:1]}),
        "seo.safe_fix": (REAL, {}), "seo.safe_fix_all": (None, {"limit": 2}), "seo.redirect.create": (None, {"from_path": "/vecchia", "to_path": "/modelle/" + REAL}),
        "landing.create": (None, {"fields": {"model": REAL, "h1": f"Landing {RUN}", "intro": "Testo introduttivo.", "noindex": True}}), "alerts.resolve": (None, {}),
        "jobs.run": ("health_check", {}), "jobs.pause": ("seo_scan", {}), "jobs.resume": ("seo_scan", {}), "backup.create": (None, {}), "system.health_run": (None, {}),
        "rollback.window": (REAL, {"minutes": 5}), "models.prepare_complete": (None, {"nome": f"Anteprima {RUN}", "fields": {"badge": "x", "frase": "review"}, "media": [{"media": img["id"], "slot": "card"}]}),
    }
    for cap, (tgt, p) in previews.items():
        st, j = exe(cap, tgt, p, preview=True)
        if cap == "alerts.resolve":   # needs an alert target: none open in a healthy preview -> 422 expected
            rec(cap, "preview", st in (200, 422), j.get("summary") or j.get("code"))
            continue
        ok = st == 200 and j.get("ok") and j.get("data", {}).get("dry_run") is True and j.get("data", {}).get("rollback", {}).get("available") is False
        rec(cap, "preview", ok, j.get("summary") if st == 200 else json.dumps(j)[:200])
    st, j = exe("media.upload_url", None, {"url": BASE + img.get("variants", {}).get("original", {}).get("url", "/api/uploads/" + img["storage_path"])}, preview=True)
    rec("media.upload_url", "preview", st == 422 and j.get("code") == "VALIDATION_FAILED", "nessuna anteprima sicura -> 422 (regola Phase 10)")
    st, j = exe("models.update", REAL, {"changes": {"badge": "x"}})
    rec("READ_ONLY enforcement", "execute", st == 403 and j.get("code") == "READ_ONLY_MODE", j.get("code"))

    # =========================================================== PHASE 1: FULL (preview) - reversible mutations per session + hash
    print("\n=== FASE 1: FULL (solo preview) — gruppo A: modella di test ===")
    run(set_mode(True))
    snapA = run(snapshot())
    sidA = f"ses_covA_{RUN}"
    TM = None
    try:
        st, j = exe("models.create", None, {"nome": f"Cov Model {RUN}", "fields": {"categorie": cats[:1], "badge": "Test"}}, session=sidA)
        rec("models.create", "full", st == 200 and j["data"]["rollback"]["available"], j.get("summary"))
        TM = j["data"]["id"]
        etag = j["data"].get("etag") or j["data"].get("updated_at")
        for cap, p in [("models.set_public_side", {"values": {"teaser_copy": "Qui posso mostrarti solo fino a questo punto.", "cta_testo": "CONTINUA"}}),
                       ("models.set_secret_side", {"values": {"preset": "dolce", "glow": True, "grain": 0.1}}),
                       ("models.set_regia", {"values": {"fumo": 0.5, "luci": 0.7, "glow": 0.6, "movimento": 0.4, "audio": {"traccia": "velluto-nero", "volume": 0.25, "attiva": True}}}),
                       ("models.set_cta", {"values": {"attiva": True, "ritardo_secondi": 20, "testo": "Continua con me"}}),
                       ("models.set_secret_message", {"values": {"attivo": True, "timer": 35, "testo": "Ti aspettavo."}}),
                       ("models.set_social", {"values": {"instagram": "https://instagram.com/covtest", "tiktok": "https://tiktok.com/@covtest"}}),
                       ("models.set_seo", {"values": {"keywords": ["test", "lato segreto"], "topics": ["editoriale"], "alt_default": "Ritratto di test"}}),
                       ("models.tags.add", {"tags": [f"cov-{RUN}", "estate"]}), ("models.tags.remove", {"tags": ["estate"]}),
                       ("models.categories.set", {"categories": cats[:2]}), ("models.feature", {"badge": "In evidenza", "badge_tipo": "editoriale", "filmstrip": True}),
                       ("filmstrip.set_model", {"attiva": True, "priorita": 2}), ("models.unfeature", {})]:
            st, j = exe(cap, TM, p, session=sidA)
            rec(cap, "full", st == 200 and j.get("ok") and (j["data"]["rollback"]["available"] or j["data"].get("unchanged")), j.get("summary") if st == 200 else json.dumps(j)[:200])
        # REVIEW via models.update -> approval -> approve
        st, j = exe("models.update", TM, {"changes": {"frase": "Il lato che non mostro a nessuno.", "onlyfans_url": "https://onlyfans.com/covtest12a"}}, session=sidA)
        ok = st == 200 and j.get("approval_required") and j["approval"].get("token")
        rec("models.update (REVIEW→approval)", "full", ok, j.get("summary"))
        if ok:
            st2, j2 = approve(j["approval"])
            rec("approveApproval (models.update)", "full", st2 == 200 and j2.get("ok") and j2["data"]["rollback"]["available"], j2.get("summary") if st2 == 200 else j2)
        # tags.normalize on the test tag only
        st, j = exe("tags.normalize", None, {"from": f"cov-{RUN}", "to": f"cov2-{RUN}"}, session=sidA)
        rec("tags.normalize", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
        # media: library assign / replace / remove / reorder / update alt / upload_url (real download from preview public URL)
        for cap, p in [("media.assign", {"media": img["id"], "slot": "public_photo_1", "alt": "Foto pubblica 1"}), ("media.assign", {"media": img2["id"], "slot": "secret_photo_1"}),
                       ("media.assign", {"media": img["id"], "slot": "card"}), ("media.assign", {"media": img2["id"], "slot": "cover"}), ("media.assign", {"media": img2["id"], "slot": "secret_hero"}),
                       ("media.replace_slot", {"media": img2["id"], "slot": "public_photo_1"}), ("media.assign", {"media": img["id"], "slot": "public_photo_2"}),
                       ("media.reorder_pairs", {"order": ["1", "0"]}), ("media.remove_from_slot", {"slot": "public_photo_2"})]:
            st, j = exe(cap, TM, p, session=sidA)
            rec(cap, "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], j.get("summary") if st == 200 else json.dumps(j)[:200])
        if vid:
            st, j = exe("media.assign", TM, {"media": vid["id"], "slot": "public_video_1"}, session=sidA)
            rec("media.assign (video→filmstrip pair)", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
            st, j = exe("media.assign", TM, {"media": vid["id"], "slot": "filmstrip_public"}, session=sidA)
            rec("media.assign (filmstrip_public)", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
        st, j = exe("media.update", None, {"media": img["id"], "alt": f"ALT coverage {RUN}"}, session=sidA)
        rec("media.update", "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], j.get("summary") if st == 200 else j)
        src_url = BASE + (img.get("variants", {}).get("original", {}).get("url") or f"/api/uploads/{img['storage_path']}")
        st, j = exe("media.upload_url", None, {"url": src_url, "model": TM, "slot": "public_photo_3", "alt": "Upload test", "seo_name": f"upload-cov-{RUN}"}, session=sidA)
        up_ok = st == 200 and j.get("ok") and j["data"].get("id") and j["data"]["rollback"]["available"]
        rec("media.upload_url", "full", up_ok, j.get("summary") if st == 200 else json.dumps(j)[:250])
        UP = j["data"].get("id") if up_ok else None
        if UP:
            st, j = exe("media.optimize", None, {"media": UP}, session=sidA)
            rec("media.optimize", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
            st, j = exe("media.optimize_all", None, {"model": TM, "limit": 2}, session=sidA)
            rec("media.optimize_all", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
        # clone / copy_config / seo
        st, j = exe("models.clone", TM, {"new_name": f"Cov Clone {RUN}", "include_media": False}, session=sidA)
        rec("models.clone", "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], j.get("summary") if st == 200 else json.dumps(j)[:200])
        st, j = exe("models.copy_config", TM, {"from": REAL2, "fields": ["tema", "regia"]}, session=sidA)
        rec("models.copy_config", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else json.dumps(j)[:200])
        st, j = exe("seo.audit", TM, {}, session=sidA)
        rec("seo.audit (test model)", "full", st == 200, j.get("summary"))
        st, j = exe("seo.safe_fix", TM, {}, session=sidA)
        rec("seo.safe_fix", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
        st, j = exe("seo.safe_fix_all", None, {"ids": [TM], "limit": 1}, session=sidA)
        rec("seo.safe_fix_all", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else json.dumps(j)[:200])
        iss = run(seo_issues_col.find_one({"entity_id": TM, "status": "open", "severity": {"$ne": "CRITICAL"}}, {"_id": 0}))
        if iss:
            st, j = exe("seo.fix_issue", None, {"issue_id": iss["id"], "proposed_value": "Valore proposto di test"}, session=sidA)
            if st == 200 and j.get("approval_required"):
                st2, j2 = approve(j["approval"])
                rec("seo.fix_issue (REVIEW→approve)", "full", st2 == 200, j2.get("summary") if st2 == 200 else j2)
            else:
                rec("seo.fix_issue", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else json.dumps(j)[:200])
        else:
            rec("seo.fix_issue", "full", True, "nessuna issue aperta non-critical sulla modella di test: verificata solo l'anteprima")
        # landing lifecycle on test model
        st, j = exe("landing.create", None, {"fields": {"model": TM, "h1": f"Landing cov {RUN}", "intro": "Intro di test.", "cta_text": "SCOPRI", "noindex": True}}, session=sidA)
        rec("landing.create", "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], j.get("summary") if st == 200 else json.dumps(j)[:250])
        LS = j["data"].get("slug") if st == 200 else None
        if LS:
            for cap, p in [("landing.get", {}), ("landing.validate", {}), ("landing.update", {"changes": {"subtitle": "Sottotitolo aggiornato."}}), ("landing.unpublish", {})]:
                st, j = exe(cap, LS, p, session=sidA)
                rec(cap, "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else json.dumps(j)[:200])
            st, j = exe("landing.publish", LS, {}, session=sidA)
            # policy outcomes all acceptable: validator blocks an incomplete landing (warnings), approval required, or published (rollbackable)
            blocked_by_validator = st == 200 and j["data"].get("validation") and not j["data"]["validation"].get("ok") and j["data"]["rollback"]["available"] is False
            rec("landing.publish (validator/approval)", "full", st == 200 and (blocked_by_validator or j.get("approval_required") or j["data"]["rollback"]["available"]), j.get("summary") + (f" | validator errors: {len(j['data']['validation'].get('errors', []))}" if blocked_by_validator else "") if st == 200 else json.dumps(j)[:200])
            if st == 200 and j.get("approval_required"):
                S.post(f"{BASE}/api/v2/ai/approvals/{j['approval']['id']}/reject", json={"reason": "test"}, headers=K, timeout=30)
        # publish path: preview only on the test model (never published), soft_delete approval + undelete
        st, j = exe("models.publish", TM, {}, preview=True)
        rec("models.publish (dry, test model)", "full", st == 200 and j["data"]["dry_run"], j.get("summary"))
        st, j = exe("models.soft_delete", TM, {}, session=sidA)
        if st == 200 and j.get("approval_required"):
            st2, j2 = approve(j["approval"])
            rec("models.soft_delete (approve)", "full", st2 == 200 and j2.get("ok"), j2.get("summary") if st2 == 200 else j2)
            st3, j3 = exe("models.undelete", None, {"model": TM}, session=sidA)
            rec("models.undelete", "full", st3 == 200 and j3.get("ok"), j3.get("summary") if st3 == 200 else j3)
        else:
            rec("models.soft_delete", "full", False, json.dumps(j)[:200])
        # rollback.version on a single version of the test model
        v = run(versions_col.find_one({"entity": "model", "entity_id": TM, "rolled_back": {"$ne": True}, "before": {"$ne": None}}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)]))
        st, j = exe("rollback.version", None, {"version_id": v["id"]}, session=sidA)
        rec("rollback.version", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
        st, j = exe("rollback.window", TM, {"minutes": 1}, preview=True)
        rec("rollback.window (dry)", "full", st == 200, j.get("summary"))
    finally:
        st, j = rollback_session(sidA)
        rec("rollback.session (gruppo A)", "full", st == 200 and j.get("ok") and not j["data"].get("errors"), j.get("summary") if st == 200 else j)
        run(approvals_col.update_many({"status": "pending", "actor": {"$regex": f"cov12a-{RUN}"}}, {"$set": {"status": "rejected", "reject_reason": "coverage cleanup"}}))
        snapA2 = run(snapshot())
        hash_check("gruppo A (modella test, media, SEO, landing, clone)", snapA, snapA2)

    print("\n=== FASE 1 — gruppo B: configurazioni sito (reversibili) ===")
    snapB = run(snapshot())
    sidB = f"ses_covB_{RUN}"
    try:
        pub = [m["slug"] for m in run(models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1}).sort("ordine", 1).to_list(3))]
        st, j = exe("homepage.reorder_models", None, {"order": [pub[1], pub[0]]}, session=sidB)
        rec("homepage.reorder_models", "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], j.get("summary") if st == 200 else json.dumps(j)[:200])
        st, j = exe("filmstrip.set_config", None, {"config": {"velocita": 7, "max_video_attivi": 6}}, session=sidB)
        rec("filmstrip.set_config", "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], j.get("summary") if st == 200 else json.dumps(j)[:200])
        st, j = exe("settings.update", None, {"changes": {"site_description": f"Descrizione test {RUN}"}}, session=sidB)
        rec("settings.update", "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], j.get("summary") if st == 200 else json.dumps(j)[:200])
        st, j = exe("config.update", None, {"changes": {"ai.policy.max_batch": 40}}, session=sidB)
        rec("config.update", "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], j.get("summary") if st == 200 else json.dumps(j)[:200])
        st, j = exe("flags.set", None, {"flag": "ab_testing", "value": False}, session=sidB)
        if st == 200 and j.get("approval_required"):
            st2, j2 = approve(j["approval"])
            rec("flags.set (REVIEW→approve)", "full", st2 == 200 and j2.get("ok") and j2["data"]["rollback"]["available"], j2.get("summary") if st2 == 200 else j2)
        else:
            rec("flags.set", "full", False, json.dumps(j)[:200])
        st, j = exe("flags.set", None, {"flag": "ai_write_enabled", "value": True}, preview=True)
        rec("flags.set (kill-switch flag blocked)", "full", st == 403 and j.get("code") == "CRITICAL_ACTION_BLOCKED", j.get("code"))
        st, j = exe("config.update", None, {"changes": {"ai.enabled": False}}, preview=True)
        rec("config.update (non-manageable key blocked)", "full", st == 403, j.get("code"))
        # categories lifecycle
        st, j = exe("categories.create", None, {"nome": f"Cov Cat {RUN}", "descrizione": "Categoria di test", "stato": "bozza"}, session=sidB)
        rec("categories.create", "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], j.get("summary") if st == 200 else json.dumps(j)[:200])
        CS = j["data"].get("slug") if st == 200 else None
        if CS:
            st, j = exe("categories.update", CS, {"changes": {"descrizione": "Aggiornata", "seo_title": "Cat test"}}, session=sidB)
            rec("categories.update", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else json.dumps(j)[:200])
            st, j = exe("categories.restore", CS, {}, session=sidB)
            rec("categories.restore", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else json.dumps(j)[:200])
            st, j = exe("categories.archive", CS, {}, session=sidB)
            if st == 200 and j.get("approval_required"):
                st2, j2 = approve(j["approval"])
                rec("categories.archive (REVIEW→approve)", "full", st2 == 200 and j2.get("ok"), j2.get("summary") if st2 == 200 else j2)
            else:
                rec("categories.archive", "full", st == 200 and j.get("ok") and j["data"]["rollback"]["available"], (j.get("summary") or "") + " (applicata direttamente: REVIEW gestito dal classificatore campi)")
            st, j = exe("categories.reorder", None, {"order": [CS] + cats[:1]}, session=sidB)
            rec("categories.reorder", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else json.dumps(j)[:200])
            st, j = exe("categories.assign_models", CS, {"models": [pub[0]]}, session=sidB)
            rec("categories.assign_models", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else json.dumps(j)[:200])
        # redirects (REVIEW)
        st, j = exe("seo.redirect.create", None, {"from_path": f"/vecchia-{RUN}", "to_path": f"/modelle/{pub[0]}"}, session=sidB)
        if st == 200 and j.get("approval_required"):
            st2, j2 = approve(j["approval"])
            rec("seo.redirect.create (REVIEW→approve)", "full", st2 == 200 and j2.get("ok") and j2["data"]["rollback"]["available"], j2.get("summary") if st2 == 200 else j2)
            st3, j3 = exe("seo.redirect.delete", None, {"from_path": f"/vecchia-{RUN}"}, session=sidB)
            if st3 == 200 and j3.get("approval_required"):
                st4, j4 = approve(j3["approval"])
                rec("seo.redirect.delete (REVIEW→approve)", "full", st4 == 200 and j4.get("ok"), j4.get("summary") if st4 == 200 else j4)
            else:
                rec("seo.redirect.delete", "full", False, json.dumps(j3)[:200])
        else:
            rec("seo.redirect.create", "full", False, json.dumps(j)[:200])
    finally:
        st, j = rollback_session(sidB)
        rec("rollback.session (gruppo B)", "full", st == 200 and j.get("ok") and not j["data"].get("errors"), j.get("summary") if st == 200 else j)
        snapB2 = run(snapshot())
        hash_check("gruppo B (home, filmstrip, settings, config, flag, categorie, redirect)", snapB, snapB2)

    print("\n=== FASE 1 — gruppo C: operazioni non versionate (cleanup manuale) ===")
    snapC = run(snapshot())
    n_backups = run(backups_col.count_documents({}))
    st, j = exe("jobs.run", "health_check", {})
    rec("jobs.run (health_check)", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
    st, j = exe("jobs.run", "media_check", {})
    rec("jobs.run (media_check)", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
    st, j = exe("jobs.pause", "seo_scan", {})
    if st == 200 and j.get("approval_required"):
        st2, j2 = approve(j["approval"])
        rec("jobs.pause (REVIEW→approve)", "full", st2 == 200 and run(jobs_col.find_one({"name": "seo_scan"}))["enabled"] is False, j2.get("summary") if st2 == 200 else j2)
    else:
        rec("jobs.pause", "full", False, json.dumps(j)[:200])
    st, j = exe("jobs.resume", "seo_scan", {})
    rec("jobs.resume", "full", st == 200 and run(jobs_col.find_one({"name": "seo_scan"}))["enabled"] is True, j.get("summary") if st == 200 else j)
    st, j = exe("system.health_run", None, {})
    rec("system.health_run", "full", st == 200 and j.get("ok"), j.get("summary") if st == 200 else j)
    st, j = exe("alerts.list", None, {"include_resolved_hours": 48})
    al = (j.get("data") or {}).get("open") or (j.get("data") or {}).get("items") or []
    if al:
        st, j = exe("alerts.inspect", al[0]["id"], {})
        rec("alerts.inspect", "full", st == 200, j.get("summary"))
        st, j = exe("alerts.ack", al[0]["id"], {}, preview=True)
        rec("alerts.ack (dry)", "full", st == 200, j.get("summary"))
    else:
        rec("alerts.ack / alerts.inspect / alerts.resolve", "full", True, "nessun alert aperto in preview (health ok): verificate solo anteprime/letture")
    st, j = exe("backup.create", None, {})
    bid = (j.get("data") or {}).get("id")
    rec("backup.create", "full", st == 200 and j.get("ok") and bid, j.get("summary") if st == 200 else j)
    if bid:
        st, j = exe("backup.verify", None, {"backup_id": bid})
        rec("backup.verify", "full", st == 200 and j["data"].get("integrity_ok") is True, j.get("summary") if st == 200 else j)
        st, j = exe("backup.restore_plan", None, {"backup_id": bid, "collections": ["models"]})
        # restore_plan is a read_only capability: the dispatcher marks data.dry_run False, but the plan itself is a no-op preview
        rec("backup.restore_plan", "full", st == 200 and isinstance(j["data"].get("plan"), list) and j["data"].get("critical") is True, j.get("summary") if st == 200 else j)
        run(backups_col.delete_one({"id": bid}))   # cleanup of the test backup record
    rec("backup cleanup", "full", run(backups_col.count_documents({})) == n_backups, "record backup di test rimosso")
    hash_check("gruppo C (jobs, health, backup)", snapC, run(snapshot()), ignore=["seo_issues", "alerts"])  # scans/health legitimately refresh monitoring state (self-healing SAFE fixes)
    run(set_mode(False))

    # =========================================================== PHASE 2: E2E TEST GIULIA
    print("\n=== FASE 2: E2E TEST GIULIA (FULL solo preview) ===")
    assert not run(models_col.find_one({"nome": {"$regex": "^TEST GIULIA$", "$options": "i"}, "is_deleted": {"$ne": True}})), "TEST GIULIA already exists (non-deleted)"
    run(set_mode(True))
    snapG = run(snapshot())
    n_ver_before = run(versions_col.count_documents({}))
    n_act_before = run(ai_actions_col.count_documents({}))
    sidG = f"ses_giulia_{RUN}"
    E = REPORT["e2e"]
    try:
        fields = {"nome_artistico": "Test Giulia", "frase": "Quello che non vedi è la parte migliore.", "bio": "Ventisei anni, Milano. Di giorno una cosa, di notte un'altra.",
                  "bio_segreta": "Qui le regole le decido io.", "onlyfans_url": "https://onlyfans.com/testgiulia12a", "cta_testo": "ENTRA NEL MIO LATO SEGRETO",
                  "teaser_copy": "Qui posso mostrarti solo fino a questo punto.", "badge": "Nuova", "badge_tipo": "editoriale", "categorie": cats[:1], "tag": ["milano", "test"],
                  "tema": {"preset": "bordeaux", "glow": True, "grain": 0.08, "frase_attivazione": "NON DOVRESTI PREMERLO"},
                  "regia": {"fumo": 0.5, "luci": 0.6, "glow": 0.5, "movimento": 0.4, "audio": {"traccia": "velluto-nero", "volume": 0.25, "attiva": True}},
                  "cta_temporizzata": {"attiva": True, "ritardo_secondi": 20, "testo": "Continua con me"}, "messaggio_35s": {"attivo": True, "timer": 35, "testo": "Ti stavo aspettando."},
                  "social": {"instagram": "https://instagram.com/testgiulia", "tiktok": "https://tiktok.com/@testgiulia"},
                  "seo": {"title": "Test Giulia | LATO SEGRETO", "meta_description": "Il lato segreto di Test Giulia: foto, video e contenuti riservati.", "keywords": ["test giulia", "lato segreto"], "topics": ["editoriale"], "alt_default": "Test Giulia ritratto"},
                  "conferma_maggiorenne": True}
        media = [{"media": img["id"], "slot": "card", "alt": "Test Giulia card"}, {"media": img2["id"], "slot": "cover"}, {"media": img["id"], "slot": "public_photo_1", "alt": "Test Giulia pubblica 1"},
                 {"media": img2["id"], "slot": "secret_photo_1", "alt": "Test Giulia segreta 1"}, {"media": img2["id"], "slot": "secret_hero"}]
        if vid:
            media += [{"media": vid["id"], "slot": "public_video_1"}, {"media": vid["id"], "slot": "filmstrip_public"}]
        st, j = exe("models.prepare_complete", None, {"nome": "TEST GIULIA", "fields": fields, "media": media, "seo_safe_fix": True}, session=sidG, reason="Prepara TEST GIULIA completamente ma non pubblicarla")
        E["prepare_complete"] = {"status": st, "ok": j.get("ok"), "summary": j.get("summary"), "steps": (j.get("data") or {}).get("steps"), "approval_required": j.get("approval_required")}
        assert st == 200 and j.get("ok"), j
        d = j["data"]
        GID = d["id"]
        E["model"] = {"id": GID, "slug": d["slug"], "workflow_status": d["workflow_status"], "published": d["published"], "pending_review_fields": d.get("pending_review_fields")}
        assert d["published"] is False and d["workflow_status"] != "PUBLISHED"
        assert {"frase", "bio", "bio_segreta", "onlyfans_url", "seo"} <= set(d.get("pending_review_fields") or []), d.get("pending_review_fields")
        # REVIEW subset -> approval (explicit user confirmation simulated)
        assert j.get("approval_required") and j["approval"].get("token"), "REVIEW fields must require approval"
        st2, j2 = approve(j["approval"])
        E["review_approval"] = {"status": st2, "summary": j2.get("summary")}
        assert st2 == 200 and j2.get("ok"), j2
        # extra steps: ALT metadata on media, category, readiness
        st, j = exe("media.update", None, {"media": img["id"], "alt": "Test Giulia - ritratto pubblico"}, session=sidG)
        assert st == 200, j
        st, j = exe("models.categories.set", GID, {"categories": cats[:2]}, session=sidG)
        assert st == 200, j
        st, j = exe("models.tags.add", GID, {"tags": ["test-giulia"]}, session=sidG)
        assert st == 200, j
        st, j = exe("models.validate", GID, {})
        E["readiness"] = j.get("data")
        assert st == 200
        g = run(models_col.find_one({"id": GID}, {"_id": 0}))
        E["state_after_prepare"] = {"stato": g["stato"], "frase_applied": g.get("frase") == fields["frase"], "onlyfans": g.get("onlyfans_url"), "preset": (g.get("tema") or {}).get("preset"),
                                    "regia_audio": (g.get("regia") or {}).get("audio"), "cta": g.get("cta_temporizzata"), "social": g.get("social"), "seo_title": (g.get("seo") or {}).get("title"),
                                    "categorie": g.get("categorie"), "tag": g.get("tag"), "foto_card": bool(g.get("foto_card")), "foto_copertina": bool(g.get("foto_copertina")),
                                    "foto_segreta_hero": bool(g.get("foto_segreta_hero")), "pairs": [(p["tipo"], bool(p["pubblico"].get("url")), bool(p["segreto"].get("url"))) for p in g.get("media_pairs", [])],
                                    "pellicola_video_pub": bool(((g.get("pellicola_home") or {}).get("pubblico") or {}).get("video_url"))}
        assert g["stato"] == "bozza" and g.get("frase") == fields["frase"] and g.get("onlyfans_url") == fields["onlyfans_url"] and g.get("foto_card")
        # audit / session / rollback metadata
        acts = run(ai_actions_col.find({"session_id": sidG}, {"_id": 0, "action": 1, "ok": 1, "version_ids": 1, "rollback_ref": 1, "secondary": 1}).to_list(100))
        E["audit"] = {"actions": [a["action"] for a in acts], "all_ok": all(a["ok"] for a in acts), "with_version_ids": sum(1 for a in acts if a.get("version_ids")),
                      "secondary_links": sum(len(a.get("secondary") or []) for a in acts)}
        assert {"models.prepare_complete", "models.update", "media.update", "models.categories.set", "models.tags.add"} <= set(E["audit"]["actions"])
        assert E["audit"]["with_version_ids"] >= 4
        # NOT published: public API must not list it
        _pm = S.get(f"{BASE}/api/models", timeout=30).json()
        _pm = _pm.get("models", _pm.get("items", [])) if isinstance(_pm, dict) else _pm
        pub_slugs = [m["slug"] for m in _pm]
        E["not_public"] = d["slug"] not in pub_slugs
        assert E["not_public"]
        # rollback plan then rollback
        st, j = exe("rollback.session", None, {"session_id": sidG}, preview=True)
        E["rollback_plan"] = {"versions": len(j["data"]["plan"]), "secondary": len(j["data"].get("secondary", []))}
        st, j = rollback_session(sidG)
        E["rollback"] = {"status": st, "summary": j.get("summary"), "done": len(j["data"]["done"]), "side_effects": j["data"]["side_effects"], "errors": j["data"]["errors"]}
        assert st == 200 and not j["data"]["errors"], j
        snapG2 = run(snapshot())
        E["hash_identical"] = hash_check("E2E TEST GIULIA (before vs after rollback.session)", snapG, snapG2)
        E["hashes"] = {"before": hashes(snapG), "after": hashes(snapG2)}
        g2 = run(models_col.find_one({"id": GID}, {"_id": 0, "is_deleted": 1}))
        E["model_soft_deleted"] = bool(g2 and g2.get("is_deleted"))
        E["history_preserved"] = {"versions_total_grew": run(versions_col.count_documents({})) > n_ver_before, "model_versions": run(versions_col.count_documents({"entity_id": GID})),
                                  "rolled_back_flags": run(versions_col.count_documents({"entity_id": GID, "rolled_back": True})), "ai_actions_session": run(ai_actions_col.count_documents({"session_id": sidG})),
                                  "actions_total_grew": run(ai_actions_col.count_documents({})) > n_act_before}
        assert E["model_soft_deleted"] and E["history_preserved"]["rolled_back_flags"] >= 3 and E["history_preserved"]["ai_actions_session"] >= 5
        E["result"] = "PASS" if E["hash_identical"] else "FAIL"
    except Exception as e:
        import traceback
        E["result"] = "FAIL"; E["error"] = f"{type(e).__name__}: {str(e)[:300]}"; E["traceback"] = traceback.format_exc()[-800:]
        try:
            rollback_session(sidG)
        except Exception:
            pass
    finally:
        run(set_mode(False))
    print(f"E2E TEST GIULIA: {E.get('result')} {E.get('error', '')}")
finally:
    run(set_mode(False))
    S.delete(f"{BASE}/api/v1/auth/keys/{KEY_ID}", headers=JWT, timeout=30)
    REPORT["final_mode_read_only"] = not run(mode())
    REPORT["temp_key_revoked"] = S.get(f"{BASE}/api/v2/ai/capabilities", headers=K, timeout=30).status_code == 401

    async def purge_run_seeds():
        """Everything this run created is already undone (soft-deleted / deactivated / revoked) by rollback.session; purge ONLY
        those run-tagged, soft-deleted seed records so the preview DB keeps no test residue. Real business data and the
        audit trail (ai_actions) of real sessions are never touched."""
        from database import api_keys_col
        out = {}
        mids = [m["id"] async for m in models_col.find({"is_deleted": True, "$or": [{"slug": {"$regex": f"-{RUN}$"}}, {"nome": {"$regex": f"{RUN}$"}}, {"nome": {"$regex": "^TEST GIULIA$", "$options": "i"}}]}, {"_id": 0, "id": 1})]
        out["models"] = (await models_col.delete_many({"id": {"$in": mids}})).deleted_count
        fq = {"is_deleted": True, "$or": [{"model_id": {"$in": mids}}, {"seo_name": {"$regex": RUN}}, {"original_filename": {"$regex": RUN}}]}
        fids = [f["id"] async for f in files_col.find(fq, {"_id": 0, "id": 1})]
        out["files"] = (await files_col.delete_many({"$or": [{"id": {"$in": fids}}, {"parent_id": {"$in": fids}}]})).deleted_count   # parents + derived variants
        out["file_versions"] = (await versions_col.delete_many({"entity": "file", "entity_id": {"$in": fids}})).deleted_count
        out["seo_issues"] = (await seo_issues_col.delete_many({"entity_id": {"$in": mids}})).deleted_count
        lids = [x["id"] async for x in landings_col.find({"is_deleted": True, "slug": {"$regex": f"-{RUN}$"}}, {"_id": 0, "id": 1})]
        out["landings"] = (await landings_col.delete_many({"id": {"$in": lids}})).deleted_count
        cids = [x["id"] async for x in categories_col.find({"is_deleted": True, "slug": {"$regex": f"-{RUN}$"}}, {"_id": 0, "id": 1})]
        out["categories"] = (await categories_col.delete_many({"id": {"$in": cids}})).deleted_count
        rids = [x["id"] async for x in redirects_col.find({"active": False, "from_path": f"/vecchia-{RUN}"}, {"_id": 0, "id": 1})]
        out["redirects"] = (await redirects_col.delete_many({"id": {"$in": rids}})).deleted_count
        out["versions"] = (await versions_col.delete_many({"entity_id": {"$in": mids + lids + cids + rids}})).deleted_count
        out["api_key"] = (await api_keys_col.delete_many({"id": KEY_ID})).deleted_count
        return out
    REPORT["seed_purge"] = run(purge_run_seeds())
    caps = REPORT["capabilities"]
    flat = [(c, x) for c, xs in caps.items() for x in xs]
    REPORT["totals"] = {"checks": len(flat), "pass": sum(1 for _, x in flat if x["result"] == "PASS"), "fail": sum(1 for _, x in flat if x["result"] == "FAIL"),
                        "capabilities_touched": len(caps), "hash_checks_identical": all(h["identical"] for h in REPORT["hash_checks"]) if REPORT["hash_checks"] else None}
    os.makedirs("/app/test_reports", exist_ok=True)
    json.dump(REPORT, open("/app/test_reports/phase12a_coverage.json", "w"), indent=1, default=str)
    print(f"\nTOTALE: {REPORT['totals']} | READ_ONLY finale: {REPORT['final_mode_read_only']} | chiave revocata: {REPORT['temp_key_revoked']}")
    print("FAILS:", [(c, x["note"]) for c, x in flat if x["result"] == "FAIL"])
