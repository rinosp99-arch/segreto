"""Phase 15 — SEO AUTOPILOT EXECUTION LAYER tests (the "hands").

Pure logic (article quality gate, meta/text helpers) + DB-backed integration on the workspace DB:
activation (DB-driven FULL, restored afterwards), landing publish from a synthetic proposal through the
EXISTING quality gate, duplicate protection, article-draft quality gate (thin stays draft), production_status
shape. All created entities are uniquely tagged and cleaned up.
"""
import os
import sys
import uuid

import pytest

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from seo_autopilot import executor  # noqa: E402
from database import articles_col, models_col  # noqa: E402
from v1_landings import landings_col  # noqa: E402

pytestmark = pytest.mark.anyio
TAG = f"p15-{uuid.uuid4().hex[:6]}"


# ============================================================ pure logic
def test_text_len_strips_html():
    assert executor._text_len("<p>Ciao <a href='/x'>mondo</a></p>") == len("Ciao mondo")
    assert executor._text_len("") == 0


def test_meta_desc_bounds():
    md = executor._meta_desc("ragazze onlyfans italiane", 10)
    assert 60 <= len(md) <= 168
    short = executor._meta_desc("x", 1)
    assert 60 <= len(short) <= 168


def test_article_gate_pass_and_fail():
    good = {
        "titolo": "Guida", "seo_title": "Guida | LATO SEGRETO",
        "meta_description": "d" * 80, "slug": "guida-valida",
        "contenuto": "<p>" + ("parola " * 120) + "</p>",
        "modelle_correlate": ["martina"], "categorie": ["bionde"], "indicizzabile": True,
    }
    g = executor._article_gate(good, {"martina", "giulia"})
    assert g["passed"], g["failed"]
    thin = {"titolo": "T", "slug": "t", "contenuto": "<p>corto</p>", "modelle_correlate": [], "categorie": [], "indicizzabile": True}
    g2 = executor._article_gate(thin, {"martina"})
    assert not g2["passed"]
    assert "CONTENT_SUFFICIENT" in g2["failed"] and "INTERNAL_LINKS" in g2["failed"] and "CATEGORIES" in g2["failed"]


def test_article_gate_blocks_broken_model_link():
    doc = {"titolo": "T", "seo_title": "T", "meta_description": "d" * 70, "slug": "ok-slug",
           "contenuto": "<p>" + ("x " * 300) + "</p>", "modelle_correlate": ["inesistente"], "categorie": ["c"], "indicizzabile": True}
    g = executor._article_gate(doc, {"martina"})
    assert not g["passed"]
    assert "NO_BROKEN_MODEL_LINK" in g["failed"] and "INTERNAL_LINKS" in g["failed"]


# ============================================================ activation (DB-driven, restored)
async def test_activation_full_switch_restored():
    before = await executor.get_settings()
    try:
        await executor.set_settings({"seo_autopilot_enabled": True, "seo_autopilot_mode": "FULL"})
        assert await executor.full_enabled() is True
        await executor.set_settings({"seo_autopilot_enabled": False, "seo_autopilot_mode": "READ_ONLY"})
        assert await executor.full_enabled() is False
    finally:
        await executor.set_settings({k: before[k] for k in ("seo_autopilot_enabled", "seo_autopilot_mode", "seo_auto_publish", "seo_max_articles_per_day")})


# ============================================================ landing publish + duplicate protection
async def _two_published_models():
    return [m["slug"] async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1}).limit(2)]


async def test_landing_publish_from_proposal_and_duplicate_protection():
    slugs = await _two_published_models()
    if len(slugs) < 2:
        pytest.skip("meno di 2 modelle pubblicate nel DB di workspace")
    proposal = {
        "proposed_slug": f"test-landing-{TAG}",
        "primary_keyword": f"selezione creator test {TAG}",
        "title_proposto": f"Selezione creator test {TAG}",
        "h1_proposto": f"Selezione creator test {TAG}",
        "secondary_keywords": ["creator italiane", "profili"],
        "creator_pertinenti": [{"slug": s, "nome": s} for s in slugs],
        "categorie_pertinenti": [],
    }
    created_slug = None
    try:
        r1 = await executor.publish_landing_from_proposal(proposal)
        assert r1["published"] is True and r1["status"] == "PUBLISHED", r1
        created_slug = r1["landing_slug"]
        doc = await landings_col.find_one({"slug": created_slug}, {"_id": 0})
        assert doc and doc["stato"] == "pubblicata"
        assert (doc.get("seo") or {}).get("indexable") is True
        assert len(doc.get("model_slugs") or []) >= 2
        # duplicate protection on a second identical attempt
        r2 = await executor.publish_landing_from_proposal(proposal)
        assert r2["published"] is False and r2["status"] == "DUPLICATE_PROTECTED", r2
    finally:
        if created_slug:
            await landings_col.delete_many({"slug": created_slug})
        from seo_autopilot.store import proposals_col
        await proposals_col.delete_many({"proposed_slug": proposal["proposed_slug"]})


async def test_landing_blocked_when_insufficient_creators():
    proposal = {"proposed_slug": f"thin-{TAG}", "primary_keyword": "thin", "creator_pertinenti": [{"slug": "does-not-exist-xyz", "nome": "x"}]}
    r = await executor.publish_landing_from_proposal(proposal)
    assert r["published"] is False and r["status"] == "BLOCKED"


# ============================================================ article draft gate (thin stays draft)
async def test_thin_article_draft_stays_bozza():
    aid = str(uuid.uuid4())
    await articles_col.insert_one({"id": aid, "slug": f"thin-art-{TAG}", "stato": "bozza", "titolo": f"Thin {TAG}",
                                   "contenuto": "<p>troppo corto</p>", "categorie": [], "modelle_correlate": [], "indicizzabile": True,
                                   "fonte": "test", "created_at": executor.now_iso()})
    try:
        res = await executor.process_article_drafts()
        doc = await articles_col.find_one({"id": aid}, {"_id": 0})
        assert doc["stato"] == "bozza"  # thin content must NOT be published
        mine = [x for x in res["results"] if x["slug"] == f"thin-art-{TAG}"]
        assert mine and mine[0]["published"] is False
    finally:
        await articles_col.delete_many({"id": aid})


# ============================================================ status shape
async def test_production_status_shape():
    st = await executor.production_status()
    for k in ("SEO_AUTOPILOT_ACTIVE", "AUTO_PUBLISH_ENABLED", "ARTICLE_GENERATOR_ACTIVE", "LANDING_GENERATOR_ACTIVE",
              "MODEL_SEO_ACTIVE", "INTERNAL_LINKING_ACTIVE", "SITEMAP_AUTO_UPDATE", "SEO_SAFE_FIX_ACTIVE",
              "QUALITY_GATE_ACTIVE", "DUPLICATE_PROTECTION_ACTIVE", "TARGET_COUNTRY", "LANGUAGE",
              "MAX_ARTICLES_PER_DAY", "SITEMAP_URLS", "ORPHAN_PAGES", "SEARCH_CONSOLE_CONNECTED", "TOTAL_PUBLISHED_PAGES"):
        assert k in st, f"manca {k}"
    assert st["SITEMAP_AUTO_UPDATE"] is True
    assert st["QUALITY_GATE_ACTIVE"] is True
    assert st["TARGET_COUNTRY"] == "IT" and st["LANGUAGE"] == "it"
