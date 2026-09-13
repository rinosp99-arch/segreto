"""Phase 13 - GOOGLE SEO CORE tests (minimal but real).

In-process (GOOGLE_SEARCH_MOCK=1): adapter/service logic — state mapping, inspection cache + budget, sitemap sync debounce,
analytics cache/summary, indexability checklist, sitemap entries rules (draft/noindex/landing flag/lastmod/dedupe).
HTTP (live preview backend, READ_ONLY): public sitemap XML + robots, landing route behind flag, the new capabilities through
the v2 dispatcher with a READ_ONLY-preset key (NOT_CONFIGURED handled gracefully), GPT contract metadata, zero mutation.
"""
import os
import sys
import uuid

import pytest
import requests

os.environ["GOOGLE_SEARCH_MOCK"] = "1"
sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/tests")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")
from database import (models_col, landings_col, config_col, google_search_status_col, google_search_state_col, google_search_analytics_col, versions_col, now_iso)  # noqa: E402
from google_search import service as gs  # noqa: E402
from google_search.config import cfg  # noqa: E402
from v1_seo import sitemap_entries, sitemap_xml  # noqa: E402
from _creds import admin_credentials  # noqa: E402

pytestmark = pytest.mark.anyio
BASE = os.environ.get("TEST_BACKEND", "http://localhost:8001")
TAG = f"p13-{uuid.uuid4().hex[:6]}"


# ------------------------------------------------------------------ unit: state mapping (Google -> our 4 states)
async def test_map_state_never_says_indexed_without_google_confirmation():
    assert gs.map_state({"verdict": "PASS", "coverageState": "Submitted and indexed"}) == "INDEXED"
    assert gs.map_state({"verdict": "NEUTRAL", "coverageState": "Crawled - currently not indexed"}) == "NOT_INDEXED"
    assert gs.map_state({"verdict": "NEUTRAL", "coverageState": "Discovered - currently not indexed"}) == "NOT_INDEXED"
    assert gs.map_state({"verdict": "FAIL", "coverageState": "Blocked by robots.txt", "robotsTxtState": "DISALLOWED"}) == "BLOCKED_ERROR"
    assert gs.map_state({"verdict": "NEUTRAL", "coverageState": "URL is unknown to Google"}) == "UNKNOWN"
    assert gs.map_state({"verdict": "FAIL", "pageFetchState": "SERVER_ERROR", "coverageState": "Server error (5xx)"}) == "BLOCKED_ERROR"
    assert gs.map_state({}) == "UNKNOWN"
    assert gs.map_state({"coverageState": "Indexed, not submitted in sitemap"}) == "INDEXED"


# ------------------------------------------------------------------ service: inspection cache + budget (mock adapter)
async def test_inspection_cache_and_budget():
    assert cfg.mock and gs.configured()
    base = await gs.refresh_public_base()
    url = f"{base}/modelle/{TAG}-notindexed"
    await google_search_status_col.delete_many({"url": {"$regex": TAG}})
    r1 = await gs.inspect(url, entity={"entity_type": "model", "entity_id": TAG, "slug": f"{TAG}-notindexed"})
    assert r1["state"] == "NOT_INDEXED" and r1["cached"] is False and r1["source"] == "google"
    r2 = await gs.inspect(url)
    assert r2["cached"] is True and r2["state"] == "NOT_INDEXED"          # 24h cache: no second Google call
    r3 = await gs.inspect(url, refresh=True)
    assert r3["cached"] is False
    doc = await google_search_status_col.find_one({"url": url}, {"_id": 0})
    assert doc["google"]["coverage_state"] == "Crawled - currently not indexed" and len(doc.get("history", [])) == 1
    # budget exhaustion -> no call, explicit source
    day = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d")
    st = await google_search_state_col.find_one({"id": "global"}, {"_id": 0, "inspections": 1}) or {}
    saved = (st.get("inspections") or {}).get(day, 0)
    await google_search_state_col.update_one({"id": "global"}, {"$set": {f"inspections.{day}": cfg.inspection_daily_budget}}, upsert=True)
    try:
        r4 = await gs.inspect(f"{base}/modelle/{TAG}-other", refresh=True)
        assert r4["source"] == "budget_exhausted" and r4["state"] == "UNKNOWN"
    finally:
        await google_search_state_col.update_one({"id": "global"}, {"$set": {f"inspections.{day}": saved}})
        await google_search_status_col.delete_many({"url": {"$regex": TAG}})
    for kw, exp in (("blocked", "BLOCKED_ERROR"), ("unknown", "UNKNOWN"), ("error", "BLOCKED_ERROR"), ("ok", "INDEXED")):
        r = await gs.inspect(f"{base}/modelle/{TAG}-{kw}", refresh=True)
        assert r["state"] == exp, (kw, r["state"])
    await google_search_status_col.delete_many({"url": {"$regex": TAG}})


# ------------------------------------------------------------------ service: sitemap sync debounce
async def test_sitemap_sync_debounce_and_force():
    saved = await google_search_state_col.find_one({"id": "global"}, {"_id": 0}) or {}
    prev_sync = os.environ.get("GOOGLE_SEARCH_SYNC_ENABLED")
    os.environ["GOOGLE_SEARCH_SYNC_ENABLED"] = "true"     # the preview .env may keep the automatic sync off
    try:
        await google_search_state_col.update_one({"id": "global"}, {"$set": {"sitemap_dirty": True, "sitemap_last_hash": None, "sitemap_last_submitted_at": None}}, upsert=True)
        d = await gs.sitemap_sync(dry_run=True)
        assert d["would_submit"] is True and d["dry_run"] is True and d["urls"] >= 1
        r = await gs.sitemap_sync()
        assert r["submitted"] is True and r["registered"]["path"] == gs.sitemap_url()
        r2 = await gs.sitemap_sync()                       # nothing changed, just submitted -> skipped
        assert not r2.get("submitted") and r2["would_submit"] is False and "identica" in (r2["skipped_reason"] or "")
        await gs.mark_sitemap_dirty("test publish")
        r3 = await gs.sitemap_sync()                       # dirty but within debounce window -> skipped with reason
        assert not r3.get("submitted") and "debounce" in (r3["skipped_reason"] or "")
        r4 = await gs.sitemap_sync(force=True)
        assert r4["submitted"] is True and r4["reason"] == "force"
        st = await gs.status()
        assert st["connection"]["status"] == "CONNECTED" and st["sitemap"]["dirty"] is False and "credentials" in st and "private_key" not in str(st)
        # GOOGLE_SEARCH_SYNC_ENABLED=false governs the AUTOMATIC job only: auto run skipped, explicit manual force=true submits once
        os.environ["GOOGLE_SEARCH_SYNC_ENABLED"] = "false"
        try:
            await gs.mark_sitemap_dirty("test publish 2")
            await google_search_state_col.update_one({"id": "global"}, {"$set": {"sitemap_last_submitted_at": None}})
            r5 = await gs.sitemap_sync()
            assert not r5.get("submitted") and r5["sync_enabled"] is False and "disattivato" in (r5["skipped_reason"] or "")
            r6 = await gs.sitemap_sync(force=True)
            assert r6["submitted"] is True and r6["reason"] == "force" and r6["sync_enabled"] is False
        finally:
            os.environ["GOOGLE_SEARCH_SYNC_ENABLED"] = "true"
    finally:
        if prev_sync is None:
            os.environ.pop("GOOGLE_SEARCH_SYNC_ENABLED", None)
        else:
            os.environ["GOOGLE_SEARCH_SYNC_ENABLED"] = prev_sync
        await google_search_state_col.update_one({"id": "global"}, {"$set": {k: saved.get(k) for k in ("sitemap_dirty", "sitemap_last_hash", "sitemap_last_submitted_at", "sitemap_last_submit_result")}}, upsert=True)


# ------------------------------------------------------------------ service: analytics (cache + summarize + compare)
async def test_analytics_summary_queries_and_cache():
    await google_search_analytics_col.delete_many({})
    r = await gs.analytics([], "28g", compare=True)
    assert r["available"] and r["cached"] is False and r["previous"]["rows"]
    tot = gs.summarize(r["rows"])
    assert tot["clicks"] == 42 and tot["impressions"] == 1830 and 0 < tot["ctr"] < 100 and tot["position"]
    r2 = await gs.analytics([], "28g", compare=False)
    assert r2["cached"] is True
    q = await gs.analytics(["query"], "7g", limit=3)
    assert len(q["rows"]) == 3 and q["rows"][0]["keys"] == ["lato segreto"]
    p = await gs.analytics(["page"], "28g", page_contains="/modelle/vanessa-bella")
    assert all("vanessa-bella" in x["keys"][0] for x in p["rows"])
    await google_search_analytics_col.delete_many({})


# ------------------------------------------------------------------ sitemap rules (draft / noindex / landing flag / lastmod / dedupe)
async def test_sitemap_entries_rules():
    base = "https://example.test"
    pub = await models_col.find_one({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1})
    ids = []
    try:
        for stato, extra in (("bozza", {}), ("archiviata", {}), ("pubblicata", {"seo": {"indexable": False}}), ("pubblicata", {"anteprima": True})):
            i = str(uuid.uuid4())
            ids.append(i)
            await models_col.insert_one({"id": i, "slug": f"{TAG}-{stato}-{len(ids)}", "nome": f"{TAG}", "nome_artistico": TAG, "stato": stato, "updated_at": now_iso(), "is_deleted": False, **extra})
        entries = await sitemap_entries(base)
        locs = [e["loc"] for e in entries]
        assert f"{base}/" in locs and f"{base}/modelle/{pub['slug']}" in locs
        assert not any(TAG in l for l in locs), [l for l in locs if TAG in l]          # draft/archived/noindex/anteprima excluded
        assert len(locs) == len(set(locs))                                              # deduplicated
        me = next(e for e in entries if e["loc"] == f"{base}/modelle/{pub['slug']}")
        assert me.get("lastmod") and len(me["lastmod"]) == 10 and entries[0].get("lastmod")
        xml = sitemap_xml(entries)
        assert xml.startswith('<?xml version="1.0"') and "<lastmod>" in xml and xml.count("<url>") == len(entries)
        # landings only with the flag ON
        cfgd = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
        flag = (cfgd.get("flags") or {}).get("public_landing_routes", False)
        lands = [e for e in entries if e["type"] == "landing"]
        n_pub = await landings_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}})
        assert (len(lands) == 0) if not flag else (len(lands) <= n_pub)
    finally:
        await models_col.delete_many({"id": {"$in": ids}})
        await versions_col.delete_many({"entity_id": {"$in": ids}})


# ------------------------------------------------------------------ service: indexability checklist on a draft vs published
async def test_indexability_checklist():
    pub = await models_col.find_one({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1})
    e = await gs.resolve_entity_url("model", pub["slug"])
    r = await gs.indexability(e, fetch=False)
    codes = {c["code"] for c in r["checks"]}
    assert {"PUBLISHED", "NOINDEX", "ROBOTS_TXT", "IN_SITEMAP", "CANONICAL", "TITLE", "META_DESCRIPTION", "H1", "STRUCTURED_DATA", "INTERNAL_LINKS"} <= codes
    assert next(c for c in r["checks"] if c["code"] == "IN_SITEMAP")["ok"] is True
    i = str(uuid.uuid4())
    await models_col.insert_one({"id": i, "slug": f"{TAG}-draft", "nome": TAG, "nome_artistico": TAG, "stato": "bozza", "updated_at": now_iso(), "is_deleted": False})
    try:
        d = await gs.indexability(await gs.resolve_entity_url("model", f"{TAG}-draft"), fetch=False)
        assert d["technically_indexable"] is False and "PUBLISHED" in d["failing"]
    finally:
        await models_col.delete_many({"id": i})
        await google_search_status_col.delete_many({"slug": f"{TAG}-draft"})


# ------------------------------------------------------------------ HTTP: public sitemap/robots + landing route + capabilities (READ_ONLY key)
def _admin():
    s = requests.Session()
    tok = s.post(f"{BASE}/api/admin/login", json=admin_credentials(), timeout=30).json()["token"]
    return s, {"Authorization": f"Bearer {tok}"}


async def test_http_sitemap_robots_landing_and_capabilities():
    s, J = _admin()
    r = s.get(f"{BASE}/api/sitemap.xml", timeout=30)
    assert r.status_code == 200 and "xml" in r.headers["content-type"] and "<lastmod>" in r.text and "/modelle/" in r.text
    rb = requests.get("https://secret-side.emergent.host/robots.txt", timeout=30).text
    assert "Sitemap:" in rb and "/api/sitemap.xml" in rb and "Disallow: /admin" in rb
    # landing route: published landing reachable only with the flag; draft never
    slugs = [m["slug"] for m in s.get(f"{BASE}/api/models", timeout=30).json()["items"][:2]]
    lr = s.post(f"{BASE}/api/v1/landings", json={"titolo": f"Landing {TAG}", "headline": f"Landing {TAG}", "slug": f"landing-{TAG}", "model_slugs": slugs, "cta": {"testo": "SCOPRI"}, "seo": {"title": f"L {TAG}", "meta_description": "x" * 60}}, headers=J, timeout=30)
    lid = lr.json()["id"]
    from v1_security import AI_READ_ONLY_SCOPES
    kr = s.post(f"{BASE}/api/v1/auth/keys", json={"name": f"test-{TAG}", "role": "AI_OPERATOR", "source": "chatgpt", "scopes": list(AI_READ_ONLY_SCOPES), "rate_limit_per_min": 300}, headers=J, timeout=30).json()
    K = {"Authorization": f"Bearer {kr['api_key']}"}
    flag_before = (s.get(f"{BASE}/api/v1/config/flags", headers=J, timeout=30).json().get("flags") or {}).get("public_landing_routes")
    try:
        assert s.get(f"{BASE}/api/landings/landing-{TAG}", timeout=30).status_code == 404          # draft
        s.post(f"{BASE}/api/v1/landings/{lid}/publish", json={}, headers=J, timeout=30)
        s.put(f"{BASE}/api/v1/config/flags/public_landing_routes", json={"value": False}, headers=J, timeout=30)
        assert s.get(f"{BASE}/api/landings/landing-{TAG}", timeout=30).status_code == 404          # flag OFF
        assert f"/l/landing-{TAG}" not in s.get(f"{BASE}/api/sitemap.xml", timeout=30).text
        s.put(f"{BASE}/api/v1/config/flags/public_landing_routes", json={"value": True}, headers=J, timeout=30)
        pr = s.get(f"{BASE}/api/landings/landing-{TAG}", timeout=30)
        assert pr.status_code == 200 and len(pr.json()["model_cards"]) == 2
        assert f"/l/landing-{TAG}" in s.get(f"{BASE}/api/sitemap.xml", timeout=30).text
        # capabilities via v2 (READ_ONLY key, Google NOT configured on the live backend -> graceful states, never 500)
        def ex(body, path="execute"):
            rr = s.post(f"{BASE}/api/v2/ai/{path}", json=body, headers=K, timeout=120)
            return rr.status_code, rr.json()
        st, j = ex({"action": "google.status"})
        assert st == 200 and j["ok"] and j["data"]["connection"]["status"] in ("NOT_CONFIGURED", "CONNECTED") and "private_key" not in str(j) and j["data"]["public_urls"]["total"] >= 1
        st, j = ex({"action": "google.url.inspect", "target": slugs[0]})
        assert st == 200 and j["data"]["results"][0]["state"] in ("NOT_CONFIGURED", "INDEXED", "NOT_INDEXED", "UNKNOWN", "BLOCKED_ERROR")
        st, j = ex({"action": "google.url.inspect", "parameters": {"landing": f"landing-{TAG}"}})
        assert st == 200 and j["data"]["results"][0]["entity_type"] == "landing"
        st, j = ex({"action": "google.analytics.summary", "target": slugs[0]})
        assert st == 200 and (j["data"].get("totals") or j["data"].get("state") == "NOT_CONFIGURED")
        st, j = ex({"action": "google.analytics.queries", "parameters": {"dimension": "query", "limit": 5}})
        assert st == 200
        st, j = ex({"action": "seo.indexability", "target": slugs[0], "parameters": {"fetch": False}})
        assert st == 200 and {"code", "ok", "detail", "severity"} <= set(j["data"]["checks"][0])
        st, j = ex({"action": "seo.indexability", "parameters": {"landing": f"landing-{TAG}", "fetch": False}})
        assert st == 200 and j["data"]["entity_type"] == "landing" and "IN_SITEMAP" not in j["data"]["failing"]
        st, j = ex({"action": "seo.indexability", "parameters": {"all": True}})
        assert st == 200 and j["data"]["pages"]
        n_ver = await versions_col.count_documents({})
        st, j = ex({"action": "growth.prepare_model", "target": slugs[0]}, "preview")
        assert st == 200 and j["ok"] and j["data"]["dry_run"] is True and j["data"]["publishes"] is False and [x["step"] for x in j["data"]["steps"]][:2] == ["readiness", "seo"]
        st, j = ex({"action": "google.sitemap.sync", "parameters": {"force": True}}, "preview")
        assert st == 200 and j["data"]["dry_run"] is True
        st, j = ex({"action": "google.sitemap.sync", "parameters": {"force": True}})
        assert st == 403                                                                     # READ_ONLY key: real submit needs seo:update (and FULL)
        st, j = ex({"action": "growth.prepare_model", "target": slugs[0]})
        assert st == 403
        assert await versions_col.count_documents({}) == n_ver                              # zero mutation
        # GPT contract metadata for the new capabilities
        for cid in ("google.status", "google.sitemap.sync", "google.url.inspect", "google.analytics.summary", "google.analytics.queries", "seo.indexability", "growth.prepare_model"):
            m = s.get(f"{BASE}/api/v2/ai/capabilities/{cid}", headers=K, timeout=30).json()["data"]
            assert m["status"] == "BOUND" and "request_example" in m and "required_parameters" in m and m["preview_access"] in ("preview_only", "n/a") and m["risk"] == "SAFE", cid
        cat = {c["id"] for c in s.get(f"{BASE}/api/v2/ai/capabilities", headers=K, timeout=30).json()["data"]["capabilities"]}
        assert {"google.status", "google.url.inspect", "google.analytics.summary", "seo.indexability", "growth.prepare_model"} <= cat
    finally:
        s.put(f"{BASE}/api/v1/config/flags/public_landing_routes", json={"value": bool(flag_before)}, headers=J, timeout=30)
        s.delete(f"{BASE}/api/v1/auth/keys/{kr['id']}", headers=J, timeout=30)
        await landings_col.delete_many({"id": lid})
        await versions_col.delete_many({"entity_id": lid})
        await google_search_status_col.delete_many({"slug": f"landing-{TAG}"})
        from database import api_keys_col
        await api_keys_col.delete_many({"id": kr["id"]})
