"""Health / alert reconciliation tests (Phase 11 fix found by the real ChatGPT session).

Root causes covered:
- v1_health had its own stale OnlyFans regex (duplicate of the validator rule) -> false `onlyfans_links` critical alerts
- `seo_critical` alert was raised by the SEO job but never resolved when CRITICAL went back to 0
- site-health / recommendations read the last stored health snapshot (possibly stale) and open alerts -> stale FAIL

Run: cd /app && python -m pytest tests/test_health_reconciliation.py -q
"""
import os, sys, uuid, requests, pytest

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

B = os.environ.get("TEST_BACKEND", "http://localhost:8001")
ADMIN = {}
for _line in open("/app/memory/test_credentials.md"):          # never hard-code credentials in tests
    if "email" in _line.lower() and "@" in _line and "email" not in ADMIN:
        ADMIN["email"] = _line.split(":")[-1].strip().strip("`* ")
    if "password" in _line.lower() and "password" not in ADMIN and ":" in _line:
        ADMIN["password"] = _line.split(":", 1)[-1].strip().strip("`* ")

# motor binds its pool to the loop that first touches it: every async test in the repo runs on the ONE
# session-scoped anyio loop (tests/conftest.py) so this module can be combined with the Phase 12 suite.
pytestmark = pytest.mark.anyio


def H():
    tok = requests.post(f"{B}/api/admin/login", json=ADMIN, timeout=20).json()["token"]
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------------------------------------------------------- canonical URL rule
def test_canonical_rule_single_source():
    import v1_models, v1_seo, v1_health
    assert v1_seo.OF_RX is v1_models.OF_RX
    assert not hasattr(v1_health, "OF_RX")                  # no duplicated regex anymore
    assert v1_health.onlyfans_url_status is v1_models.onlyfans_url_status
    st = v1_models.onlyfans_url_status
    assert st("https://onlyfans.com/vanessa_bellaaa/c9") == "ok"          # A
    assert st("https://onlyfans.com/user/trial/abc-123") == "ok"          # B
    assert st("https://onlyfans.com/user?ref=x&c=1") == "ok"              # C
    assert st("https://www.onlyfans.com/user/") == "ok"
    assert st("http://bad-link") == "invalid"                             # D
    assert st("https://onlyfans.com/user/other") == "invalid"
    assert st("") == "missing" and st(None) == "missing"


async def test_global_check_uses_canonical_rule_A_B_C_D():
    from database import models_col
    from v1_health import check_onlyfans_links
    slugs = []

    async def scenario():
        base = {"stato": "pubblicata", "is_deleted": False, "nome": "OF Test", "nome_artistico": "OF Test"}
        docs = [
            {**base, "id": str(uuid.uuid4()), "slug": "of-test-c9", "onlyfans_url": "https://onlyfans.com/u_one/c9"},
            {**base, "id": str(uuid.uuid4()), "slug": "of-test-trial", "onlyfans_url": "https://onlyfans.com/u_two/trial/abc-1"},
            {**base, "id": str(uuid.uuid4()), "slug": "of-test-query", "onlyfans_url": "https://onlyfans.com/u_three?ref=ls"},
        ]
        slugs.extend(d["slug"] for d in docs)
        await models_col.insert_many([dict(d) for d in docs])
        ok = await check_onlyfans_links()
        assert ok["status"] == "ok", ok
        assert ok["check_kind"] == "URL_STRUCTURE" and ok["reachability"].startswith("not_tested") and ok["checked_at"]
        assert not [i for i in ok["items"] if i["slug"] in slugs]
        bad = {**base, "id": str(uuid.uuid4()), "slug": "of-test-bad", "onlyfans_url": "http://bad-link"}
        slugs.append(bad["slug"])
        await models_col.insert_one(dict(bad))
        r = await check_onlyfans_links()
        assert r["status"] == "fail"
        item = next(i for i in r["items"] if i["slug"] == "of-test-bad")
        assert item["code"] == "URL_STRUCTURE_INVALID"
    try:
        await scenario()
    finally:
        await models_col.delete_many({"slug": {"$in": slugs}})


# ---------------------------------------------------------------- reachability != validity (E, F)
def test_reachability_is_not_url_validity_E_F():
    from v1_health import classify_reachability
    assert classify_reachability(403) == "REMOTE_BLOCKED_WARNING"        # E: anti-bot on a valid URL -> warning
    assert classify_reachability(429) == "REMOTE_BLOCKED_WARNING"
    assert classify_reachability(None) == "REMOTE_REACHABILITY_WARNING"  # F: timeout -> warning, never critical URL
    assert classify_reachability(503) == "REMOTE_BLOCKED_WARNING"
    assert classify_reachability(404) == "REMOTE_MISSING"
    assert classify_reachability(200) == "OK" and classify_reachability(301) == "OK"


# ---------------------------------------------------------------- alert reconciliation (G, H, I, J)
async def test_stale_alerts_resolved_and_history_kept_G_H_I_J():
    from database import alerts_col, seo_issues_col
    from v1_health import run_health_checks, raise_alert
    ids = []

    async def scenario():
        # seed STALE critical alerts (as production had them) for conditions that are no longer true
        for key, tipo in (("onlyfans_links", "onlyfans_links"), ("health:onlyfans_links", "health_check"), ("seo_critical", "seo_critical")):
            doc = await raise_alert(tipo, f"stale {key}", "10 link OnlyFans problematici", "critical", "health", None, key, {"items": [{"slug": "x"}] * 10, "source": "test"})
            if doc:
                ids.append(doc["id"])
            else:
                ex = await alerts_col.find_one({"dedupe_key": key, "stato": {"$in": ["open", "acknowledged"]}}, {"_id": 0, "id": 1})
                ids.append(ex["id"])
        n_before = await alerts_col.count_documents({"id": {"$in": ids}})
        assert n_before == 3
        crit_open = await seo_issues_col.count_documents({"status": "open", "severity": "CRITICAL"})
        # current state: run the checks (no self-healing writes)
        rec = await run_health_checks(auto_fix=False)
        of_chk = next(c for c in rec["checks"] if c["name"] == "onlyfans_links")
        assert rec.get("checked_at") and rec.get("source") == "health_check"
        # G: onlyfans alerts resolved when current check is healthy
        if of_chk["status"] == "ok":
            for key in ("onlyfans_links", "health:onlyfans_links"):
                a = await alerts_col.find_one({"dedupe_key": key, "id": {"$in": ids}}, {"_id": 0})
                assert a and a["stato"] == "resolved" and a["resolved_at"] and a["current"] is False, a
            assert "onlyfans_links" in rec["resolved_alerts"] or "health:onlyfans_links" in rec["resolved_alerts"]
        # H: seo_critical resolved when CRITICAL == 0
        if crit_open == 0:
            a = await alerts_col.find_one({"dedupe_key": "seo_critical", "id": {"$in": ids}}, {"_id": 0})
            assert a and a["stato"] == "resolved" and a["resolved_at"], a
        # history preserved: nothing deleted
        assert await alerts_col.count_documents({"id": {"$in": ids}}) == 3
        # I: overall derives from CURRENT checks only
        expected = "fail" if any(c["status"] == "fail" for c in rec["checks"]) else ("warn" if any(c["status"] == "warn" for c in rec["checks"]) else "ok")
        assert rec["overall"] == expected
        return rec
    try:
        rec = await scenario()
        h = H()
        # site-health (AI layer) must agree with the reconciled record and expose current vs historical alerts
        sh = requests.get(f"{B}/api/v1/ai/site-health", headers=h, timeout=60).json()
        d = sh["data"]
        assert d["health_overall"] == rec["overall"] or d["health_refreshed_now"], d["health_overall"]
        assert "alerts_resolved_recent" in d and "health_checked_at" in d and "onlyfans_links" in d
        assert all(a.get("current") is True and a["stato"] in ("open", "acknowledged") for a in d["alerts"])
        assert all(a.get("current") is False and a["resolved_at"] for a in d["alerts_resolved_recent"])
        stale_ids = {a["id"] for a in d["alerts"]} & set(ids)
        of_ok = d["onlyfans_links"].get("status") == "ok"
        if of_ok:
            assert not any(a["dedupe_key"] in ("onlyfans_links", "health:onlyfans_links") for a in d["alerts"]), stale_ids
        # J: recommendations built from the current state: no "link OnlyFans problematici" when the check is ok
        recs = requests.get(f"{B}/api/v1/ai/recommendations?limit=100", headers=h, timeout=120).json()["data"]["items"]
        if of_ok:
            assert not [r for r in recs if "onlyfans_links" in r["problem"]], [r["problem"] for r in recs]
    finally:
        await alerts_col.delete_many({"id": {"$in": ids}})   # remove only the alerts seeded by this test


async def test_alert_documents_expose_timestamps():
    from database import alerts_col
    from v1_health import raise_alert, resolve_alerts
    key = f"test:ts:{uuid.uuid4().hex[:6]}"

    async def scenario():
        doc = await raise_alert("test", "ts", "m", "warning", "health", None, key, {"source": "test"})
        for f in ("created_at", "updated_at", "checked_at", "last_seen", "source", "current", "stato"):
            assert f in doc, f
        await raise_alert("test", "ts", "m2", "warning", "health", None, key, {"items": [1], "source": "test"})
        a = await alerts_col.find_one({"dedupe_key": key, "stato": "open"}, {"_id": 0})
        assert a["occurrences"] == 2 and a["messaggio"] == "m2" and a["meta"]["items"] == [1]   # refreshed with current evidence
        assert await resolve_alerts(key) == 1
        a = await alerts_col.find_one({"dedupe_key": key}, {"_id": 0})
        assert a["stato"] == "resolved" and a["resolved_at"] and a["current"] is False
        await alerts_col.delete_many({"dedupe_key": key})
    await scenario()
