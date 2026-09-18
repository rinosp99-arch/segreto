"""Phase 14 - SEO AUTOPILOT (READ_ONLY) tests.

In-process: mode guard (FULL locked, WriteBlocked), text normalisation/intent/clustering determinism, GSC sync with
(a) NOT_CONNECTED, (b) fake connected rows -> non-overwriting idempotent snapshots, (c) zero data, (d) temporary API error,
opportunity rules (positions 5-20, low CTR, decline, cannibalization SAME_QUERY), planner + quality gate (doorway rejection),
crawler parser (broken link detection, noindex), LLM fail-soft + metric stripping + LLM_SUGGESTION labelling,
public snapshot hashing, engine run idempotency and PUBLIC_MUTATIONS=0 on a full deterministic run.
HTTP (live preview backend): admin endpoints require auth; status reports READ_ONLY; execute endpoint -> 423; public
sitemap/robots unchanged after a run (zero mutation, hash compare).
"""
import asyncio
import hashlib
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/tests")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")
os.environ["SEO_AUTOPILOT_MODE"] = "READ_ONLY"

from seo_autopilot import mode, store, gsc_sync, textnorm, intent, clustering, opportunities, planner, crawler, llm, keywords, models_matrix, engine  # noqa: E402
from _creds import admin_credentials  # noqa: E402

pytestmark = pytest.mark.anyio
BASE = os.environ.get("TEST_BACKEND", "http://localhost:8001")
PUBLIC = os.environ.get("SEO_CRAWL_BASE_URL", "https://secret-side.preview.emergentagent.com")
TAG = f"p14-{uuid.uuid4().hex[:6]}"


# ============================================================================================ mode guard
def test_mode_default_and_full_locked(monkeypatch):
    monkeypatch.delenv("SEO_AUTOPILOT_MODE", raising=False)
    assert mode.current_mode() == "READ_ONLY"
    monkeypatch.setenv("SEO_AUTOPILOT_MODE", "FULL")
    assert mode.configured_mode() == "FULL"
    assert mode.current_mode() == "READ_ONLY", "FULL must be downgraded while FULL_LOCKED"
    info = mode.mode_info()
    assert info["downgraded"] is True and info["can_write_public"] is False and info["full_locked"] is True
    with pytest.raises(mode.WriteBlocked):
        mode.require_full("create_landing")
    monkeypatch.setenv("SEO_AUTOPILOT_MODE", "OFF")
    assert mode.is_off()
    monkeypatch.setenv("SEO_AUTOPILOT_MODE", "garbage")
    assert mode.current_mode() == "READ_ONLY"


async def test_write_action_decorator_never_runs_body(monkeypatch):
    monkeypatch.setenv("SEO_AUTOPILOT_MODE", "FULL")
    ran = {"v": False}

    @mode.write_action("update_meta")
    async def executor():
        ran["v"] = True
    with pytest.raises(mode.WriteBlocked):
        await executor()
    assert ran["v"] is False


async def test_engine_off_mode_does_nothing(monkeypatch):
    monkeypatch.setenv("SEO_AUTOPILOT_MODE", "OFF")
    r = await engine.run_gsc_sync("test")
    assert r["status"] == "OFF"


# ============================================================================================ deterministic text / intent / clustering
def test_textnorm_synonyms_and_cluster_key():
    assert textnorm.cluster_key("ragazze OF italiane") == textnorm.cluster_key("modelle OnlyFans italiane") == textnorm.cluster_key("creator onlyfans italiani")
    assert textnorm.cluster_key("ragazze OF") != textnorm.cluster_key("ragazze OF italiane")
    assert textnorm.norm_key("Ragazze  OnlyFans") == textnorm.norm_key("onlyfans ragazze")
    assert textnorm.similarity("Modelle Bionde OnlyFans", "modelle bionde onlyfans italiane") > 0.7
    assert textnorm.similarity("privacy", "modelle bionde") == 0.0


def test_intent_rules():
    names, cats, tags, brand = ["Vanessa Neri", "Sofia Marino"], ["Bionde", "Tatuate"], ["tatuata"], "lato segreto"
    assert intent.classify("lato segreto onlyfans", names, cats, tags, brand)[0] == "BRANDED"
    assert intent.classify("vanessa neri onlyfans", names, cats, tags, brand)[0] == "CREATOR"
    assert intent.classify("come funziona onlyfans", names, cats, tags, brand)[0] == "INFORMATIONAL"
    assert intent.classify("modelle bionde onlyfans", names, cats, tags, brand)[0] == "CATEGORY"
    assert intent.classify("ragazze OF italiane", names, cats, tags, brand)[0] == "DISCOVERY"
    assert intent.classify("onlyfans login", names, cats, tags, brand)[0] == "NAVIGATIONAL"
    # LLM opinion never overrides a confident rule
    assert intent.merge_llm_opinion("DISCOVERY", 0.85, "CATEGORY", 0.99) == ("DISCOVERY", "RULES")
    assert intent.merge_llm_opinion("OTHER", 0.3, "INFORMATIONAL", 0.9) == ("INFORMATIONAL", "LLM_SUGGESTION")


# ============================================================================================ GSC sync
@pytest.fixture
async def clean_snapshots():
    await store.ensure_indexes()
    await store.snapshots_col.delete_many({"source": f"TEST-{TAG}"})
    yield
    await store.snapshots_col.delete_many({"source": f"TEST-{TAG}"})


async def test_gsc_sync_not_connected(monkeypatch):
    async def fake_status():
        return {"GSC_STATUS": "NOT_CONNECTED", "required": ["GOOGLE_SEARCH_ENABLED=true"]}
    monkeypatch.setattr(gsc_sync, "gsc_status", fake_status)
    r = await gsc_sync.sync(run_id=None)
    assert r["GSC_STATUS"] == "NOT_CONNECTED" and r["imported"] == {} and r["errors"] == {}


async def test_gsc_sync_connected_idempotent_and_zero_data(monkeypatch, clean_snapshots):
    async def fake_status():
        return {"GSC_STATUS": "CONNECTED"}
    day = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%d")
    calls = {"n": 0}

    async def fake_fetch(dims, start, end):
        calls["n"] += 1
        if dims == ["date", "query"]:
            return {"available": True, "rows": [{"keys": [day, f"q-{TAG} a"], "clicks": 3, "impressions": 120, "ctr": 0.025, "position": 8.4},
                                                {"keys": [day, f"q-{TAG} b"], "clicks": 0, "impressions": 60, "ctr": 0.0, "position": 14.0}]}
        return {"available": True, "rows": []}   # zero data for other dimension sets
    monkeypatch.setattr(gsc_sync, "gsc_status", fake_status)
    monkeypatch.setattr(gsc_sync, "_fetch", fake_fetch)
    r1 = await gsc_sync.sync(run_id=None, days=3, dim_sets=["query", "page"])
    assert r1["imported"]["query"] == 2 and r1["imported"]["page"] == 0 and r1["skipped"]["query"] == 0
    doc = await store.snapshots_col.find_one({"dims": "query", "query": f"q-{TAG} a"}, {"_id": 0})
    assert doc and doc["ctr"] == 2.5 and doc["impressions"] == 120 and doc["date"] == day
    # second run: same rows -> nothing overwritten, all skipped (history preserved)
    r2 = await gsc_sync.sync(run_id=None, days=3, dim_sets=["query"])
    assert r2["imported"]["query"] == 0 and r2["skipped"]["query"] == 2
    assert await store.snapshots_col.count_documents({"dims": "query", "query": {"$regex": f"^q-{TAG}"}}) == 2
    await store.snapshots_col.delete_many({"query": {"$regex": f"^q-{TAG}"}})


async def test_gsc_sync_temporary_api_error(monkeypatch):
    async def fake_status():
        return {"GSC_STATUS": "CONNECTED"}

    async def fake_fetch(dims, start, end):
        return {"available": False, "state": "ERROR", "error": "HttpError: 503 backendError", "rows": []}
    monkeypatch.setattr(gsc_sync, "gsc_status", fake_status)
    monkeypatch.setattr(gsc_sync, "_fetch", fake_fetch)
    r = await gsc_sync.sync(run_id=None, days=2, dim_sets=["query"])
    assert "query" in r["errors"] and "503" in r["errors"]["query"] and r["imported"] == {}


def test_aggregate_weighted_position_and_ctr():
    rows = [{"query": "a", "clicks": 1, "impressions": 100, "position": 10.0, "date": "d1"}, {"query": "a", "clicks": 3, "impressions": 300, "position": 6.0, "date": "d2"}]
    a = gsc_sync.aggregate(rows, "query")["a"]
    assert a["impressions"] == 400 and a["clicks"] == 4 and a["position"] == 7.0 and a["ctr"] == 1.0 and a["days"] == 2


# ============================================================================================ opportunities / cannibalization / planner
def _cluster(cid, kw, intent_, imps, pos, ctr, page=None, trend="STABLE", can=None, extra=None):
    c = {"cluster_id": cid, "primary_keyword": kw, "intent": intent_, "n_keywords": 1, "keywords": [kw], "secondary_keywords": [], "sources": ["GSC"], "gsc_queries": [],
         "metrics": {"source": "GSC" if imps is not None else "UNKNOWN", "impressions_28": imps, "position_28": pos, "ctr_28": ctr, "impressions_7": imps, "impressions_prev7": 0},
         "trend": {"status": trend}, "current_page": page, "cannibalization": can or {"risk": "LOW", "pages": []}}
    c.update(extra or {})
    return c


@pytest.fixture
async def opp_cleanup():
    yield
    for col in (store.opportunities_col, store.cannibal_col, store.page_map_col, store.proposals_col, store.backlog_col):
        await col.delete_many({"run_id": f"run-{TAG}"})
    await store.log_col.delete_many({"run_id": f"run-{TAG}"})


async def test_opportunity_rules(opp_cleanup):
    matrix = {"summary": {"pubblicate": 10}, "term_index": {"bionde": ["a", "b", "c"]}, "categories": [{"slug": "bionde", "stato": "pubblicata", "n": 3}], "creators": []}
    clusters = [
        _cluster("cA", f"ragazze onlyfans italiane {TAG}", "DISCOVERY", 300, 9.0, 3.0, page=f"{PUBLIC}/"),          # A) HIGH growth
        _cluster("cB", f"modelle bionde onlyfans {TAG}", "CATEGORY", 600, 3.0, 1.0, page=f"{PUBLIC}/categorie/bionde", extra={"category_slug": "bionde"}),  # B) low CTR
        _cluster("cD", f"modelle rosse onlyfans {TAG}", "CATEGORY", 80, 30.0, 0.5),                                   # D) no page, only 0 pertinent creators -> HOLD
        _cluster("cE", f"profili of {TAG}", "DISCOVERY", 100, 12.0, 2.0, page=f"{PUBLIC}/", can={"risk": "HIGH", "pages": [f"{PUBLIC}/", f"{PUBLIC}/categorie/more"]}),  # E)
        _cluster("cU", f"query senza dati {TAG}", "DISCOVERY", None, None, None),                                      # UNKNOWN -> HOLD
    ]
    counts = await opportunities.run_opportunities(f"run-{TAG}", clusters, matrix)
    assert counts["A_GROWTH"] >= 1 and counts["B_SNIPPET"] >= 1 and counts["E_CANNIBALIZATION"] >= 1 and counts["D_NO_PAGE"] >= 2
    a = await store.opportunities_col.find_one({"rule": "A_GROWTH", "cluster_id": "cA"}, {"_id": 0})
    assert a["score"] == "HIGH" and a["suggested_action"] == "UPDATE" and a["executable"] is False and "300" in a["reason"]
    d = await store.opportunities_col.find_one({"rule": "D_NO_PAGE", "cluster_id": "cU"}, {"_id": 0})
    assert d["score"] == "HOLD" and "UNKNOWN" in d["reason"]
    e = await store.opportunities_col.find_one({"rule": "E_CANNIBALIZATION", "cluster_id": "cE"}, {"_id": 0})
    assert e["score"] == "HIGH" and e["suggested_action"] == "MERGE"
    # idempotent: second run same fingerprints, nothing duplicated
    n1 = await store.opportunities_col.count_documents({"run_id": f"run-{TAG}"})
    await opportunities.run_opportunities(f"run-{TAG}", clusters, matrix)
    assert await store.opportunities_col.count_documents({"run_id": f"run-{TAG}"}) == n1
    # decision log has reason + metrics for each
    logs = await store.log_col.count_documents({"run_id": f"run-{TAG}", "kind": "opportunity"})
    assert logs >= n1


async def test_cannibalization_same_query(monkeypatch, opp_cleanup):
    async def fake_window(dims, days, offset=0):
        if dims == "query_page":
            return [{"query": f"ragazze onlyfans {TAG}", "page": f"{PUBLIC}/", "impressions": 60, "clicks": 1, "date": "d"},
                    {"query": f"ragazze onlyfans {TAG}", "page": f"{PUBLIC}/categorie/more", "impressions": 40, "clicks": 0, "date": "d"}]
        return []
    monkeypatch.setattr(opportunities, "window", fake_window)
    r = await opportunities.run_cannibalization(f"run-{TAG}", [])
    assert r["found"] >= 1
    doc = await store.cannibal_col.find_one({"type": "SAME_QUERY", "query": f"ragazze onlyfans {TAG}"}, {"_id": 0})
    assert doc and doc["CANNIBALIZATION_RISK"] == "HIGH" and len(doc["urls"]) == 2 and "urls" in doc and doc["reason"]


async def test_planner_quality_gate_doorway_rejection(opp_cleanup):
    creators = [{"slug": f"c{i}", "nome": f"Creator {i}", "indexable": True, "categorie": ["bionde"], "bio_len": 120} for i in range(4)]
    matrix = {"creators": creators, "categories": [{"slug": "bionde", "stato": "pubblicata", "n": 4}], "term_index": {"bionde": [c["slug"] for c in creators]}, "summary": {"pubblicate": 4}}
    c1 = _cluster(f"p1{TAG}", f"ragazze onlyfans italiane {TAG}", "DISCOVERY", 250, 9.0, 3.0)
    c2 = _cluster(f"p2{TAG}", f"ragazze italiane onlyfans {TAG}", "DISCOVERY", 40, 15.0, 1.0)     # near-identical -> doorway
    c3 = _cluster(f"p3{TAG}", f"modelle bionde onlyfans {TAG}", "CATEGORY", None, None, None, extra={"category_slug": "bionde"})
    for c in (c1, c2, c3):
        await store.page_map_col.update_one({"cluster_id": c["cluster_id"]}, {"$set": {"cluster_id": c["cluster_id"], "primary_keyword": c["primary_keyword"], "intent": c["intent"], "page": None, "inferred_page": None, "page_source": None, "action": "CREATE" if c["metrics"]["source"] == "GSC" else "HOLD", "reason": "test", "run_id": f"run-{TAG}"}}, upsert=True)
    counts = await planner.plan(f"run-{TAG}", [c1, c2, c3], matrix, PUBLIC)
    assert counts["SEO_DRAFT_PROPOSAL"] >= 1 and counts["REJECTED_BY_QUALITY_GATE"] >= 1
    p1 = await store.proposals_col.find_one({"cluster_id": c1["cluster_id"]}, {"_id": 0})
    assert p1["status"] == "SEO_DRAFT_PROPOSAL" and p1["public"] is False and p1["executable"] is False and p1["hold"] is False
    assert p1["proposed_slug"].startswith("ragazze-onlyfans-italiane") and len(p1["creator_pertinenti"]) == 4 and p1["title_proposto"].endswith("| LATO SEGRETO")
    assert all(k in p1 for k in ("search_intent", "primary_keyword", "secondary_keywords", "h1_proposto", "struttura_contenuto", "internal_links_suggeriti", "query_gsc_collegate", "motivo", "rischio_cannibalizzazione", "quality_score"))
    p2 = await store.proposals_col.find_one({"cluster_id": c2["cluster_id"]}, {"_id": 0})
    assert p2["status"] == "REJECTED_BY_QUALITY_GATE" and any(g["check"] == "NO_DOORWAY" and not g["ok"] for g in p2["quality_gate"])
    p3 = await store.proposals_col.find_one({"cluster_id": c3["cluster_id"]}, {"_id": 0})
    assert p3["hold"] is True, "no GSC data -> HOLD (never invented)"
    # proposals never reachable publicly
    assert requests.get(f"{BASE}/api/landings/{p1['proposed_slug']}", timeout=15).status_code in (404, 405)
    assert requests.get(f"{PUBLIC}/l/{p1['proposed_slug']}", timeout=20).status_code in (200, 404) and p1["proposed_slug"] not in requests.get(f"{BASE}/api/sitemap.xml", timeout=15).text


# ============================================================================================ crawler parser
def test_parse_html_and_broken_link_detection():
    html = """<html><head><title>Vanessa | LATO SEGRETO</title><meta name="description" content="d"><meta name="robots" content="noindex">
    <link rel="canonical" href="https://x.test/modelle/vanessa"><script type="application/ld+json">{"@type":"Person"}</script></head>
    <body><h1>Vanessa</h1><a href="/categorie/more">c</a><a href="https://onlyfans.com/x">of</a><img src="a.jpg"><img src="b.jpg" alt="ok"></body></html>"""
    p = crawler.parse_html(html, "https://x.test/modelle/vanessa")
    assert p["title"] == "Vanessa | LATO SEGRETO" and p["h1"] == ["Vanessa"] and p["canonical"].endswith("/modelle/vanessa") and p["robots"] == "noindex"
    assert p["jsonld_types"] == ["Person"] and p["internal_links"] == ["https://x.test/categorie/more"] and p["external_links"] == ["https://onlyfans.com/x"]
    assert p["images"] == 2 and p["images_without_alt"] == 1


async def test_head_ok_detects_broken_link():
    import httpx
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        st, err = await crawler.head_ok(c, f"{BASE}/api/models/non-esiste-{TAG}")
        assert st == 404
        st2, _ = await crawler.head_ok(c, f"{BASE}/api/sitemap.xml")
        assert st2 == 200


def test_duplicates_in_rendered():
    docs = [{"url": "u1", "rendered": {"title": "Same Title", "h1": ["LATO SEGRETO"], "meta_description": "x"}}, {"url": "u2", "rendered": {"title": "Same Title", "h1": ["LATO SEGRETO"], "meta_description": "y"}}]
    codes = {d["code"] for d in crawler.duplicates_in_rendered(docs)}
    assert {"DUPLICATE_TITLE_RENDERED", "DUPLICATE_H1_RENDERED"} <= codes


# ============================================================================================ LLM layer (advisory only, fail-soft)
def test_llm_strip_metric_like_numbers():
    data = {"variants": [{"keyword": "ragazze of", "search_volume": 5000, "impressions": 20, "position": 3, "ctr": 0.5, "motivo": "ok", "intent": "DISCOVERY"}]}
    out = llm._strip_numbers(data)
    v = out["variants"][0]
    assert "search_volume" not in v and "impressions" not in v and "position" not in v and "ctr" not in v and v["keyword"] == "ragazze of"


async def test_llm_unavailable_is_soft(monkeypatch):
    monkeypatch.setenv("SEO_AUTOPILOT_LLM_ENABLED", "false")
    r = await llm.suggest_variants(["ragazze of"], [], [], [])
    assert r["available"] is False and r["source"] == "LLM_SUGGESTION"
    monkeypatch.setenv("SEO_AUTOPILOT_LLM_ENABLED", "true")
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    assert llm.available() is False


async def test_llm_error_is_soft_and_universe_continues(monkeypatch):
    async def boom(*a, **k):
        return {"available": False, "reason": "TimeoutError", "source": "LLM_SUGGESTION"}
    monkeypatch.setattr(llm, "ask_json", boom)
    monkeypatch.setattr(llm, "available", lambda: True)
    matrix = await models_matrix.analyse(None)
    r = await keywords.build_universe(f"run-{TAG}", matrix, use_llm=True)
    assert r["total"] >= len(keywords.SEEDS) and r["llm"]["used"] is False
    k = await store.keywords_col.find_one({"norm": textnorm.norm_key("ragazze OF italiane")}, {"_id": 0})
    assert k and k["search_volume"] == "DATA_SOURCE_UNAVAILABLE" and k["metrics"]["source"] in ("UNKNOWN", "GSC") and "SEED" in k["sources"]


# ============================================================================================ public snapshot + full run (PUBLIC_MUTATIONS = 0)
async def test_public_snapshot_stable_and_detects_change():
    s1 = await store.public_snapshot(None, fetch_http=False)
    s2 = await store.public_snapshot(None, fetch_http=False)
    assert store.diff_snapshots(s1, s2)["public_mutations"] == 0
    fake = {"parts": {**s2["parts"], "models": "changed"}, "hash": "x"}
    d = store.diff_snapshots(s1, fake)
    assert d["public_mutations"] == 1 and d["changed"] == ["models"]


async def test_full_readonly_run_zero_public_mutations_and_idempotent():
    """Deterministic pipeline (LLM off, browser off) twice: PUBLIC_MUTATIONS=0 both times, no duplicated clusters/opportunities."""
    before = await store.public_snapshot(PUBLIC)
    r1 = await engine.run_daily("test", use_llm=False)
    if r1.get("status") == "already_running":
        await asyncio.sleep(20)
        r1 = await engine.run_daily("test", use_llm=False)
    assert r1["status"] in ("ok", "partial") and r1["public_mutations"] == 0 and r1["PUBLIC_MUTATIONS_CHECK"] == "PASS", r1.get("errors")
    n_clusters = await store.clusters_col.count_documents({"stale": {"$ne": True}})
    n_opps = await store.opportunities_col.count_documents({"status": "OPEN"})
    r2 = await engine.run_daily("test", use_llm=False)
    assert r2["public_mutations"] == 0
    assert await store.clusters_col.count_documents({"stale": {"$ne": True}}) == n_clusters
    assert await store.opportunities_col.count_documents({"status": "OPEN"}) == n_opps
    after = await store.public_snapshot(PUBLIC)
    assert store.diff_snapshots(before, after)["public_mutations"] == 0
    # every cluster document has the required fields
    c = await store.clusters_col.find_one({"stale": {"$ne": True}}, {"_id": 0})
    for k in ("cluster_id", "intent", "primary_keyword", "secondary_keywords", "gsc_queries", "metrics", "trend", "current_page", "cannibalization"):
        assert k in c, k
    assert c["metrics"]["source"] in ("GSC", "UNKNOWN")
    # run log records the PUBLIC_MUTATION_CHECK
    assert await store.log_col.find_one({"run_id": r1["id"], "action": "PUBLIC_MUTATION_CHECK", "result": "PASS"})


# ============================================================================================ HTTP: admin API + guard + public integrity
def _token():
    c = admin_credentials()
    r = requests.post(f"{BASE}/api/admin/login", json=c, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_admin_endpoints_require_auth_and_report_read_only():
    assert requests.get(f"{BASE}/api/admin/seo-autopilot/status", timeout=15).status_code in (401, 403)
    h = {"Authorization": f"Bearer {_token()}"}
    s = requests.get(f"{BASE}/api/admin/seo-autopilot/status", headers=h, timeout=30).json()
    assert s["mode"]["mode"] == "READ_ONLY" and s["mode"]["full_locked"] is True and s["mode"]["can_write_public"] is False
    assert s["GSC_STATUS"] in ("CONNECTED", "NOT_CONNECTED", "ERROR")
    assert s["llm"]["source_label"] == "LLM_SUGGESTION" and s["render_budget"]["daily"] <= 30
    assert "today" in s and "clusters" in s["today"] and "blocked_by_quality_gate" in s["today"]
    body = requests.get(f"{BASE}/api/admin/seo-autopilot/status", headers=h, timeout=30).text
    assert "private_key" not in body and "BEGIN PRIVATE" not in body
    for ep in ("opportunities", "clusters", "keywords", "page-map", "proposals", "cannibalization", "backlog", "tech", "render", "adult", "log", "runs", "matrix", "gsc/compare"):
        r = requests.get(f"{BASE}/api/admin/seo-autopilot/{ep}", headers=h, timeout=30)
        assert r.status_code == 200, ep
    cmp = requests.get(f"{BASE}/api/admin/seo-autopilot/gsc/compare?by=query&days=7", headers=h, timeout=30).json()
    assert "volume di ricerca" in cmp["note"]


def test_execute_is_blocked_423():
    h = {"Authorization": f"Bearer {_token()}"}
    r = requests.post(f"{BASE}/api/admin/seo-autopilot/execute/qualsiasi-slug", headers=h, timeout=15)
    assert r.status_code == 423 and "FULL" in r.json()["detail"]
    r = requests.post(f"{BASE}/api/admin/seo-autopilot/run/inesistente", headers=h, timeout=15)
    assert r.status_code == 404


def test_public_resources_unchanged_by_engine():
    """Sitemap (lastmod stripped) + robots + public models JSON are byte-identical before/after a scheduled-style GSC run."""
    import re
    h = {"Authorization": f"Bearer {_token()}"}

    def snap():
        sm = re.sub(r"<lastmod>.*?</lastmod>", "", requests.get(f"{BASE}/api/sitemap.xml", timeout=20).text)
        rb = requests.get(f"{PUBLIC}/robots.txt", timeout=20).text
        models = requests.get(f"{BASE}/api/models", timeout=20).text
        return hashlib.sha256((sm + rb + models).encode()).hexdigest()
    a = snap()
    requests.post(f"{BASE}/api/admin/seo-autopilot/run/gsc_sync", headers=h, timeout=30)
    import time
    for _ in range(20):
        time.sleep(2)
        if not requests.get(f"{BASE}/api/admin/seo-autopilot/status", headers=h, timeout=30).json().get("running"):
            break
    assert snap() == a


def test_jobs_registered_in_scheduler():
    from v1_jobs import JOBS
    import seo_autopilot.jobs  # noqa: F401
    for name, interval in (("seo_ap_tech_health", 6 * 3600), ("seo_ap_gsc_sync", 12 * 3600), ("seo_ap_daily_analysis", 24 * 3600), ("seo_ap_weekly_learning", 7 * 24 * 3600)):
        assert name in JOBS and JOBS[name]["interval_s"] == interval


# ============================================================================================ Phase 14B — technical foundation
async def test_sitemap_includes_articles_index_when_articles_exist():
    from v1_seo import sitemap_entries
    from database import articles_col
    entries = await sitemap_entries("https://x.test")
    has_articles = await articles_col.count_documents({"stato": "pubblicato", "indicizzabile": True}) > 0
    idx = [e for e in entries if e["path"] == "/articoli"]
    assert (len(idx) == 1) == has_articles
    if idx:
        assert idx[0]["type"] == "articles_index" and idx[0]["loc"] == "https://x.test/articoli"
    assert len({e["loc"] for e in entries}) == len(entries), "no duplicates"


def test_foundation_route_rejects_unauthorised_host_and_returns_latest():
    h = {"Authorization": f"Bearer {_token()}"}
    r = requests.post(f"{BASE}/api/admin/seo-autopilot/run/foundation?base=https://evil.example.com", headers=h, timeout=15)
    assert r.status_code == 400
    r = requests.get(f"{BASE}/api/admin/seo-autopilot/foundation", headers=h, timeout=30)
    assert r.status_code == 200
    d = r.json()
    if "rows" in d:
        assert d["verdict"]["BASE_SEO"] in ("INDICIZZABILE", "NON_INDICIZZABILE") and all("INDEXABLE" in row and "GOOGLE_INDEX_STATUS" in row and "orphan_status" in row and "sitemap_status" in row for row in d["rows"])
