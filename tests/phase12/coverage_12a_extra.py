"""Phase 12A - supplemental REAL coverage for the capabilities the main harness (coverage_12a.py) could not exercise
with a valid payload because preview had no suitable data (no deleted media, no open alert, no open SEO issue to ignore).

Covered here with real payloads (preview only, FULL toggled on and ALWAYS restored to READ_ONLY):
- media.restore        : soft-delete a test upload through the real service, restore it via capability, rollback.session
- filmstrip.reorder    : reorder the real FilmStrip (published models), verify pellicola_home.ordine, rollback.session
- alerts.inspect       : seeded test alert (real v1_health.raise_alert), read detail + history
- alerts.ack / resolve : ack the seeded alert; manual resolve -> REVIEW approval -> resolved; history kept; seed removed
- seo.ignore_issue     : seeded open SEO issue on a test entity -> preview -> REVIEW approval -> ignored; seed removed

Business-state hash (same rules as coverage_12a) must be identical before/after. No secret is printed.
Run: cd /app && python tests/phase12/coverage_12a_extra.py
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
sys.path.insert(0, "/app/tests")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")
from database import config_col, models_col, files_col, alerts_col, seo_issues_col, versions_col, ai_actions_col, settings_col, now_iso  # noqa: E402
from _creds import admin_credentials  # noqa: E402

BASE = os.environ.get("BASE_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].splitlines()[0].strip()
RUN = uuid.uuid4().hex[:6]
S = requests.Session()
RES = []
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def run(coro):
    return LOOP.run_until_complete(coro)


def rec(cap, ok, note=""):
    RES.append({"capability": cap, "result": "PASS" if ok else "FAIL", "note": str(note)[:300]})
    print(f"{'PASS' if ok else 'FAIL'} {cap:34} {str(note)[:120]}")


VOLATILE = {"updated_at", "deleted_at", "etag", "updated_by", "hits", "last_run", "last_status", "last_duration_ms", "next_run", "optimized_at", "reopened_at", "resolved_at"}


def _clean(d):
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in sorted(d.items()) if k not in VOLATILE and k != "_id" and not (k == "is_deleted" and not v)}
    if isinstance(d, list):
        return [_clean(x) for x in d]
    return d


def _h(o):
    return hashlib.sha256(json.dumps(_clean(o), sort_keys=True, default=str).encode()).hexdigest()[:16]


async def snapshot():
    return {"models": _h({m["id"]: m async for m in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0})}),
            "files": _h({f["id"]: {k: f.get(k) for k in ("model_id", "slot", "alt", "seo_name", "is_deleted")} async for f in files_col.find({"parent_id": None}, {"_id": 0})}),
            "settings": _h(await settings_col.find_one({"id": "global"}, {"_id": 0}) or {}),
            "alerts_open": _h([a["dedupe_key"] async for a in alerts_col.find({"stato": {"$in": ["open", "acknowledged"]}}, {"_id": 0, "dedupe_key": 1})]),
            "seo_open": _h(sorted([i["id"] async for i in seo_issues_col.find({"status": "open"}, {"_id": 0, "id": 1})]))}


async def set_mode(full):
    await config_col.update_one({"id": "global"}, {"$set": {"flags.ai_write_enabled": bool(full)}})


async def mode():
    c = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    return bool((c.get("flags") or {}).get("ai_write_enabled"))


# ---------------------------------------------------------------- auth
creds = admin_credentials()
r = S.post(f"{BASE}/api/admin/login", json=creds, timeout=30)
assert r.status_code == 200, "admin login failed"
JWT = {"Authorization": f"Bearer {r.json().get('access_token') or r.json().get('token')}"}
r = S.post(f"{BASE}/api/v1/auth/keys", json={"name": f"cov12a-extra-{RUN}", "role": "SUPER_ADMIN", "source": "chatgpt", "rate_limit_per_min": 600}, headers=JWT, timeout=30)
assert r.status_code in (200, 201), r.text[:200]
KEY_ID, K = r.json()["id"], {"Authorization": f"Bearer {r.json()['api_key']}"}


def exe(action, target=None, params=None, dry=False, session=None, preview=False, reason="coverage 12a extra"):
    body = {"action": action, "target": target, "parameters": params or {}, "dry_run": dry, "reason": reason}
    if session:
        body["session_id"] = session
    for _ in range(4):
        r = S.post(f"{BASE}/api/v2/ai/{'preview' if preview else 'execute'}", json=body, headers=K, timeout=120)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "20")) + 1)
            continue
        break
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:300]}


def approve(appr):
    r = S.post(f"{BASE}/api/v2/ai/approvals/{appr['id']}/approve", json={"token": appr["token"]}, headers=K, timeout=120)
    return r.status_code, r.json()


def rollback(sid):
    return exe("rollback.session", None, {"session_id": sid})


assert run(mode()) is False, "preview must start READ_ONLY"
snap0 = run(snapshot())
n_ver0, n_act0 = run(versions_col.count_documents({})), run(ai_actions_col.count_documents({}))
seeded_alert_ids, seeded_issue_id, upload_id = [], None, None
run(set_mode(True))
try:
    # ============================================================ media.restore (real soft delete -> restore -> rollback)
    sid = f"ses_extra_media_{RUN}"
    png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    st, j = exe("media.upload_url", None, {"base64_data": png, "content_type": "image/png", "filename": f"extra-{RUN}.png", "alt": "coverage extra", "seo_name": f"extra-{RUN}"}, session=sid)
    rec("media.upload_url (base64 seed)", st == 200 and j.get("ok"), j.get("summary") if st == 200 else json.dumps(j)[:200])
    if st == 200 and j.get("ok"):
        upload_id = j["data"]["id"]
        st, j = exe("media.soft_delete", None, {"media": upload_id}, session=sid)
        if st == 200 and j.get("approval_required"):
            st, j = approve(j["approval"])
        rec("media.soft_delete (REVIEW→approve)", st == 200 and j.get("ok") and run(files_col.find_one({"id": upload_id}, {"_id": 0, "is_deleted": 1}))["is_deleted"] is True, j.get("summary") if st == 200 else json.dumps(j)[:200])
        st, j = exe("media.restore", None, {"media": upload_id}, preview=True)
        rec("media.restore (preview)", st == 200 and j.get("ok") and j["data"].get("dry_run") is True, j.get("summary") if st == 200 else json.dumps(j)[:200])
        st, j = exe("media.restore", None, {"media": upload_id}, session=sid)
        f = run(files_col.find_one({"id": upload_id}, {"_id": 0, "is_deleted": 1, "deleted_at": 1}))
        rec("media.restore", st == 200 and j.get("ok") and f and not f.get("is_deleted") and not f.get("deleted_at") and j["data"].get("id") == upload_id and j.get("data") is not None,
            j.get("summary") if st == 200 else json.dumps(j)[:200])
        st, j = rollback(sid)
        f = run(files_col.find_one({"id": upload_id}, {"_id": 0, "is_deleted": 1}))
        rec("rollback.session (media: upload undone)", st == 200 and j.get("ok") and not j["data"]["errors"] and f and f.get("is_deleted") is True, j.get("summary") if st == 200 else json.dumps(j)[:200])

    # ============================================================ filmstrip.reorder (real published models)
    sid = f"ses_extra_fs_{RUN}"
    pub = [m["slug"] for m in run(models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1}).sort("ordine", 1).to_list(20))]
    order = list(reversed(pub[:3]))
    st, j = exe("filmstrip.reorder", None, {"order": order}, preview=True)
    rec("filmstrip.reorder (preview)", st == 200 and j.get("ok") and j["data"]["order"] == order and len(j.get("changes", [])) == 3, j.get("summary") if st == 200 else json.dumps(j)[:200])
    st, j = exe("filmstrip.reorder", None, {"order": order}, session=sid)
    after = {m["slug"]: (m.get("pellicola_home") or {}).get("ordine") for m in run(models_col.find({"slug": {"$in": order}}, {"_id": 0, "slug": 1, "pellicola_home": 1}).to_list(10))}
    rec("filmstrip.reorder", st == 200 and j.get("ok") and all(after[s] == i for i, s in enumerate(order)) and j["data"]["rollback"]["available"] is True, f"{j.get('summary')} -> ordine {after}" if st == 200 else json.dumps(j)[:200])
    st, j = rollback(sid)
    rec("rollback.session (filmstrip)", st == 200 and j.get("ok") and not j["data"]["errors"] and run(snapshot())["models"] == snap0["models"], j.get("summary") if st == 200 else json.dumps(j)[:200])

    # ============================================================ alerts.inspect / ack / resolve (seeded test alert, real raise_alert)
    from v1_health import raise_alert
    key = f"test:extra:{RUN}"
    a = run(raise_alert("test", f"extra {RUN}", "alert di test coverage 12a", "warning", "health", None, key, {"source": "test"}))
    seeded_alert_ids.append(a["id"])
    st, j = exe("alerts.inspect", key)
    rec("alerts.inspect", st == 200 and j.get("ok") and j["data"]["dedupe_key"] == key and isinstance(j["data"].get("history"), list) and len(j["data"]["history"]) >= 1, j.get("summary") if st == 200 else json.dumps(j)[:200])
    st, j = exe("alerts.ack", a["id"], {}, preview=True)
    rec("alerts.ack (preview)", st == 200 and j.get("ok") and j["data"].get("dry_run") is True, j.get("summary") if st == 200 else json.dumps(j)[:200])
    st, j = exe("alerts.ack", a["id"], {})
    cur = run(alerts_col.find_one({"id": a["id"]}, {"_id": 0, "stato": 1, "acknowledged_at": 1}))
    rec("alerts.ack", st == 200 and j.get("ok") and cur["stato"] == "acknowledged" and cur.get("acknowledged_at"), j.get("summary") if st == 200 else json.dumps(j)[:200])
    st, j = exe("alerts.resolve", a["id"], {}, preview=True)
    rec("alerts.resolve (preview)", st == 200 and j.get("ok") and j["data"].get("dry_run") is True, j.get("summary") if st == 200 else json.dumps(j)[:200])
    st, j = exe("alerts.resolve", a["id"], {})
    if st == 200 and j.get("approval_required"):
        st, j = approve(j["approval"])
    cur = run(alerts_col.find_one({"id": a["id"]}, {"_id": 0, "stato": 1, "resolved_at": 1, "current": 1}))
    rec("alerts.resolve (REVIEW→approve)", st == 200 and j.get("ok") and cur["stato"] == "resolved" and cur.get("resolved_at") and cur.get("current") is False, j.get("summary") if st == 200 else json.dumps(j)[:200])
    rec("alerts history kept", run(alerts_col.count_documents({"id": {"$in": seeded_alert_ids}})) == 1, "alert risolto ma non cancellato")

    # ============================================================ seo.ignore_issue (seeded open issue on a test entity id)
    seeded_issue_id = f"seoi_extra_{RUN}"
    run(seo_issues_col.insert_one({"id": seeded_issue_id, "entity": "model", "entity_id": f"test-entity-{RUN}", "entity_slug": f"test-{RUN}", "code": "META_DESCRIPTION_MISSING", "severity": "REVIEW_REQUIRED",
                                   "status": "open", "message": "issue di test coverage 12a", "created_at": now_iso(), "updated_at": now_iso(), "source": "test"}))
    st, j = exe("seo.ignore_issue", None, {"issue_id": seeded_issue_id}, preview=True)
    rec("seo.ignore_issue (preview)", st == 200 and j.get("ok") and j["data"].get("dry_run") is True and j["data"]["issue"]["id"] == seeded_issue_id, j.get("summary") if st == 200 else json.dumps(j)[:200])
    st, j = exe("seo.ignore_issue", None, {"issue_id": seeded_issue_id})
    rec("seo.ignore_issue requires approval", st == 200 and j.get("approval_required") is True and j.get("approval", {}).get("token"), j.get("summary") if st == 200 else json.dumps(j)[:200])
    if st == 200 and j.get("approval_required"):
        st, j = approve(j["approval"])
    cur = run(seo_issues_col.find_one({"id": seeded_issue_id}, {"_id": 0, "status": 1, "ignored_at": 1}))
    rec("seo.ignore_issue (REVIEW→approve)", st == 200 and j.get("ok") and cur["status"] == "ignored" and cur.get("ignored_at"), j.get("summary") if st == 200 else json.dumps(j)[:200])
    st, j = exe("seo.ignore_issue", None, {"issue_id": "does-not-exist"}, preview=True)
    rec("seo.ignore_issue unknown -> 404", st == 404 and j.get("code") == "NOT_FOUND", json.dumps(j)[:120])
finally:
    # ---------------------------------------------------------- cleanup of seeds only (never business data), READ_ONLY restored
    run(set_mode(False))
    if seeded_alert_ids:
        run(alerts_col.delete_many({"id": {"$in": seeded_alert_ids}}))
    if seeded_issue_id:
        run(seo_issues_col.delete_many({"id": seeded_issue_id}))
    if upload_id:   # the test upload was undone by rollback (soft-deleted); remove the seed record + its variants + versions
        run(files_col.delete_many({"$or": [{"id": upload_id}, {"parent_id": upload_id}]}))
        run(versions_col.delete_many({"entity": "file", "entity_id": upload_id}))
    r = S.delete(f"{BASE}/api/v1/auth/keys/{KEY_ID}", headers=JWT, timeout=30)
    rec("temp key revoked", r.status_code in (200, 204), r.status_code)
    from database import api_keys_col
    run(api_keys_col.delete_many({"id": KEY_ID}))   # revoked test key record removed: no residue
    rec("final mode READ_ONLY", run(mode()) is False)

snap1 = run(snapshot())
rec("HASH business state identical", snap0 == snap1, {k: (snap0[k] == snap1[k]) for k in snap0})
rec("audit/history grew (kept)", run(versions_col.count_documents({})) >= n_ver0 and run(ai_actions_col.count_documents({})) > n_act0)

n = sum(1 for x in RES if x["result"] == "PASS")
out = {"run": RUN, "checks": len(RES), "pass": n, "fail": len(RES) - n, "results": RES}
json.dump(out, open("/app/test_reports/phase12a_coverage_extra.json", "w"), indent=1)
print(f"\nEXTRA: {n}/{len(RES)} -> {'PASS' if n == len(RES) else 'FAIL'}")
sys.exit(0 if n == len(RES) else 1)
