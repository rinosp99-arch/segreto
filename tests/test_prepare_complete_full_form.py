"""models.prepare_complete — FULL FORM contract (fix definitivo).
    cd /app && python -m pytest tests/test_prepare_complete_full_form.py -q -p no:cacheprovider

Controlled fixture only (name prefixed ZZTEST PREPARE ...), preview Mongo, READ_ONLY restored, draft rolled back and purged.
Proves, through the real HTTP contract (parameters.nome + parameters.fields + parameters.seo_safe_fix=true), that ONE call fills
every non-media field: SAFE applied immediately, REVIEW fully prepared in ONE approval, SEO safe fixes applied, readiness truthful.
"""
import os
import sys
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

sys.path.insert(0, "/app/backend")
os.environ.setdefault("TESTING", "1")

import v1_capabilities as C  # noqa: E402
from database import api_keys_col, config_col, models_col, versions_col, ai_actions_col, seo_issues_col, now_iso  # noqa: E402
from v1_security import hash_key, generate_api_key  # noqa: E402
from v1_ai_policy import approvals_col  # noqa: E402
from v1_prepare_fields import EXAMPLE_FIELDS_FULL, PREPARE_FIELDS_SCHEMA  # noqa: E402

pytestmark = pytest.mark.anyio
TAG = uuid.uuid4().hex[:6]
NAME = f"ZZTEST PREPARE FULL {TAG}"
SID = f"ses_zztest_prepare_{TAG}"
_keys = []


def _app():
    app = FastAPI()
    app.include_router(C.caps_router)
    return app


async def _mk_key():
    raw = generate_api_key()
    doc = {"id": str(uuid.uuid4()), "name": f"zztest-prepare-{TAG}", "role": "AI_OPERATOR", "key_hash": hash_key(raw), "prefix": raw[:10], "expires_at": None,
           "scopes": ["ai:execute", "models:read", "models:create", "models:update", "models:validate", "seo:audit", "seo:safe_fix", "rollback:read", "rollback:execute"],
           "rate_limit_per_min": 600, "ip_allowlist": [], "source": "chatgpt", "created_at": now_iso(), "created_by": "pytest", "active": True, "uses": 0,
           "request_count": 0, "error_count": 0, "last_ip": None, "revoked_at": None, "disabled_at": None, "capability_allow": None, "capability_deny": []}
    await api_keys_col.insert_one(doc)
    _keys.append(doc["id"])
    return raw


async def _mode():
    c = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    return bool((c.get("flags") or {}).get("ai_write_enabled", False))


async def _set_mode(full: bool):
    await config_col.update_one({"id": "global"}, {"$set": {"flags.ai_write_enabled": bool(full)}}, upsert=True)


async def _others_snapshot():
    return {m["id"]: (m.get("updated_at"), m.get("stato")) async for m in models_col.find({"nome": {"$not": {"$regex": "^ZZTEST"}}}, {"_id": 0, "id": 1, "updated_at": 1, "stato": 1})}


def _get(d, path):
    for p in path.split("."):
        d = (d or {}).get(p)
    return d


@pytest.fixture(scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        yield c
    await _set_mode(False)
    await api_keys_col.delete_many({"id": {"$in": _keys}})
    await models_col.delete_many({"nome": NAME})
    await versions_col.delete_many({"reason": {"$regex": TAG}})
    await approvals_col.delete_many({"target.nome": NAME})
    await seo_issues_col.delete_many({"entity_label": NAME})


# Payload = the documented full example WITHOUT seo.meta_description (proves the derivation into the approval) + blocked fields on purpose
FIELDS = {k: (dict(v) if isinstance(v, dict) else v) for k, v in EXAMPLE_FIELDS_FULL.items()}
FIELDS["seo"] = {k: v for k, v in EXAMPLE_FIELDS_FULL["seo"].items() if k != "meta_description"}
FIELDS["nome_artistico"] = NAME.title()
FIELDS["slug"] = f"zztest-prepare-{TAG}"
FIELDS["stato"] = "pubblicata"                  # must be dropped (never publishes)
FIELDS["conferma_maggiorenne"] = True           # must be dropped (real data)
FIELDS["foto_card"] = "https://example.com/x.jpg"   # media -> dropped
FIELDS["seo"]["og_image"] = "https://example.com/og.jpg"   # media -> dropped
FIELDS["regia"]["inventato"] = 1                # unknown key -> dropped (regia is a free dict in the DB)
FIELDS["onlyfans_url"] = ""                     # empty -> dropped (never invented)

SAFE_EXPECTED = ["cta_testo", "teaser_copy", "categorie", "tag", "badge", "badge_tipo", "tema.preset", "tema.colore_primario", "tema.colore_secondario", "tema.grain", "tema.glow",
                 "tema.frase_attivazione", "tema.testo_dopo_click", "tema.effetti_touch", "regia.preset", "regia.fumo", "regia.luci", "regia.glow", "regia.movimento",
                 "regia.audio.ambiente", "regia.audio.traccia", "regia.audio.volume_ambiente", "regia.audio.volume_effetto",
                 "cta_temporizzata.attivo", "cta_temporizzata.ritardo", "cta_temporizzata.testo_intro", "cta_temporizzata.testo_pulsante",
                 "messaggio_35s.attivo", "messaggio_35s.timer", "messaggio_35s.testo", "messaggio_35s.cta_testo", "pellicola_home.attiva", "pellicola_home.priorita",
                 "seo.alt_default", "seo.keywords", "seo.topics", "seo.structured_data_type"]
REVIEW_EXPECTED = ["nome_artistico", "slug", "frase", "bio", "bio_segreta", "seo.title", "seo.robots", "seo.indexable"]
DROPPED_EXPECTED = {"stato", "conferma_maggiorenne", "foto_card", "seo.og_image", "regia.inventato", "onlyfans_url"}


async def test_01_get_capability_exposes_explicit_fields_schema_and_full_example(client):
    raw = await _mk_key()
    r = await client.get("/api/v2/ai/capabilities/models.prepare_complete", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    fs = d["parameters_schema"]["properties"]["fields"]
    assert fs["type"] == "object" and fs is not None and fs["properties"] == PREPARE_FIELDS_SCHEMA["properties"]
    props = fs["properties"]
    # every non-media form field is declared with type + description; nested objects have explicit sub-properties; enums/ranges where applicable
    for k in ("frase", "cta_testo", "bio", "bio_segreta", "teaser_copy", "categorie", "tag", "badge", "tema", "regia", "cta_temporizzata", "messaggio_35s", "pellicola_home", "seo", "social", "slug", "nome_artistico", "onlyfans_url", "ordine", "badge_tipo"):
        assert k in props and props[k].get("type") and props[k].get("description"), k
    assert set(props["tema"]["properties"]) >= {"preset", "colore_primario", "colore_secondario", "grain", "glow", "frase_attivazione", "testo_dopo_click", "effetti_touch"}
    assert set(props["regia"]["properties"]) == {"preset", "fumo", "luci", "glow", "movimento", "audio"} and props["regia"]["properties"]["fumo"]["maximum"] == 100
    assert set(props["cta_temporizzata"]["properties"]) == {"attivo", "ritardo", "testo_intro", "testo_pulsante"}
    assert set(props["seo"]["properties"]) == {"title", "meta_description", "alt_default", "canonical", "robots", "indexable", "keywords", "topics", "og_title", "og_description", "structured_data_type"}
    assert "og_image" not in props["seo"]["properties"] and "foto_card" not in props and "media_pairs" not in props and "stato" not in props and "conferma_maggiorenne" not in props
    assert props["badge"]["enum"] == [None, "NUOVA", "IN TENDENZA", "PIÙ VISTA", "SCELTA DEL GIORNO"] and props["tema"]["properties"]["preset"]["enum"] == ["bordeaux", "tattoo", "dolce", "sportiva", "cosplay"]
    # complete example_parameters + request_example
    ex = d["example_parameters"]
    assert ex["nome"] and ex["seo_safe_fix"] is True and set(ex["fields"]) >= {"frase", "bio", "bio_segreta", "tema", "regia", "cta_temporizzata", "messaggio_35s", "seo", "categorie", "tag", "badge", "teaser_copy", "cta_testo"}
    assert d["request_example"]["parameters"] == ex and d["required_parameters"] == ["nome"]


async def test_02_preview_is_read_only_and_splits_by_path(client):
    raw = await _mk_key()
    n0 = await models_col.count_documents({})
    r = await client.post("/api/v2/ai/preview", json={"action": "models.prepare_complete", "parameters": {"nome": NAME, "fields": FIELDS, "seo_safe_fix": True}, "dry_run": True}, headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["dry_run"] is True and d["would_create"] is True and d["publishes"] is False
    assert set(d["fields_safe_paths"]) == set(SAFE_EXPECTED), sorted(set(d["fields_safe_paths"]) ^ set(SAFE_EXPECTED))
    assert set(d["fields_review_paths"]) == set(REVIEW_EXPECTED), sorted(set(d["fields_review_paths"]) ^ set(REVIEW_EXPECTED))
    assert {x["path"] for x in d["fields_dropped"]} == DROPPED_EXPECTED
    # seo.keywords SAFE and seo.title REVIEW live in the SAME object: path-level split, not root-level
    assert "seo" in d["fields_safe"] and "seo" in d["fields_review"]
    # derived meta description prepared in the review proposal (from the proposed bio), never a placeholder from an empty bio
    assert d["review_prepared_values"]["seo"]["meta_description"].startswith(f"Scopri {NAME.title()}:") and len(d["review_prepared_values"]["seo"]["meta_description"]) <= 160
    assert await models_col.count_documents({}) == n0 and await models_col.count_documents({"nome": NAME}) == 0


async def test_03_execute_fills_the_whole_non_media_form_in_one_session(client):
    raw = await _mk_key()
    assert await _mode() is False
    others0 = await _others_snapshot()
    pub0 = await models_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}})
    await _set_mode(True)
    try:
        body = {"action": "models.prepare_complete", "parameters": {"nome": NAME, "fields": FIELDS, "seo_safe_fix": True}, "session_id": SID, "reason": "zztest full form"}
        r = await client.post("/api/v2/ai/execute", json=body, headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 200, r.text
        out = r.json()
        d = out["data"]
        assert out["ok"] and d["published"] is False and d["session_id"] == SID and d["workflow_status"] in ("DRAFT", "INCOMPLETE")
        mid = d["id"]
        doc = await models_col.find_one({"id": mid}, {"_id": 0})
        assert doc and doc["stato"] == "bozza" and doc["conferma_maggiorenne"] is False and doc["onlyfans_url"] == "" and not doc.get("foto_card")
        # --- every SAFE path is applied with the exact value
        assert set(d["fields_applied"]) == set(SAFE_EXPECTED), sorted(set(d["fields_applied"]) ^ set(SAFE_EXPECTED))
        for p in SAFE_EXPECTED:
            assert _get(doc, p) == _get(FIELDS, p), (p, _get(doc, p))
        assert "inventato" not in doc["regia"]
        # --- every REVIEW path is fully prepared in ONE approval (plus derived meta/og description), nothing applied yet
        assert out.get("approval_required") and out["approval"]["capability"] == "models.update"
        prepared = out["approval"]["prepared_values"]
        assert set(d["fields_review_pending"]) == set(REVIEW_EXPECTED) | {"seo.meta_description", "seo.og_description"}
        for p in REVIEW_EXPECTED:
            assert _get(prepared, p) == _get(FIELDS, p), p
        for p in ("nome_artistico", "slug", "frase", "bio", "bio_segreta", "seo.title"):
            assert _get(doc, p) != _get(FIELDS, p), ("REVIEW applied without approval", p)
        assert prepared["seo"]["meta_description"].startswith(f"Scopri {NAME.title()}:")
        assert await approvals_col.count_documents({"status": "pending", "payload.target": mid}) == 1
        # --- SEO safe fix actually ran on the fresh draft (audit + fix): canonical, og_title, robots default; meta deferred to the approval
        seo_step = next(s for s in d["steps"] if s["step"].startswith("seo."))
        assert seo_step["fixes"] >= 1 and {x["code"] for x in seo_step["fixed"]} >= {"MISSING_CANONICAL", "MISSING_OG_TITLE"}, seo_step
        assert any(x["field"] == "seo.meta_description" for x in seo_step["deferred_to_review"])
        assert doc["seo"]["canonical"].endswith(f"/modelle/{doc['slug']}") and doc["seo"]["og_title"] == doc["seo"]["title"] and doc["seo"]["robots"] == "index,follow"
        assert doc["seo"]["keywords"] == FIELDS["seo"]["keywords"] and doc["seo"]["alt_default"] == FIELDS["seo"]["alt_default"]
        # --- truthful readiness: only media / real data / pending review may be missing; NO text left unfilled
        b = d["readiness_breakdown"]
        assert b["missing_text_not_provided"] == [], b
        assert set(b["missing_media"]) == {"Foto card Home", "3 foto Lato Pubblico", "3 foto Lato Segreto", "Video pubblico 1", "Video segreto 1", "Video Pellicola pubblico", "Video Pellicola segreto"}
        assert set(b["missing_real_data"]) == {"Link OnlyFans", "Creator maggiorenne confermata"}
        assert {x["field"] for x in b["pending_review"]} >= {"frase", "bio", "bio_segreta", "slug", "seo.title", "seo.meta_description"}
        assert b["seo"]["og_image"] == "MISSING_MEDIA" and b["seo"]["canonical"] == "SET" and b["seo"]["meta_description"] == "PENDING_REVIEW"
        assert {x["path"] for x in d["fields_dropped"]} == DROPPED_EXPECTED
        # --- one session, audit + rollback metadata
        acts = await ai_actions_col.find({"session_id": SID}, {"_id": 0, "action": 1, "ok": 1}).to_list(50)
        assert acts and all(a["action"] == "models.prepare_complete" and a["ok"] for a in acts)
        assert d["rollback"]["available"] and len(d["rollback"]["version_ids"]) == len(set(d["rollback"]["version_ids"])) >= 3
        for vid in d["rollback"]["version_ids"]:
            assert await versions_col.count_documents({"id": vid, "entity_id": mid}) == 1
        # --- approve: REVIEW values land, SAFE values stay, still a draft
        r = await client.post(f"/api/v2/ai/approvals/{out['approval']['id']}/approve", json={"token": out["approval"]["token"]}, headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 200, r.text
        doc = await models_col.find_one({"id": mid}, {"_id": 0})
        for p in REVIEW_EXPECTED:
            assert _get(doc, p) == _get(FIELDS, p), p
        for p in SAFE_EXPECTED:
            assert _get(doc, p) == _get(FIELDS, p), ("SAFE lost after approval", p)
        assert doc["seo"]["meta_description"] == prepared["seo"]["meta_description"] and doc["seo"]["canonical"] and doc["stato"] == "bozza"
        from v1_models import validate_model
        v = validate_model(doc)
        assert {e["field"] for e in v["errors"]} == set(b["missing_media"]) | set(b["missing_real_data"]), v["errors"]
        # --- no side effects: other models untouched, published count unchanged, draft not public
        assert await _others_snapshot() == others0
        assert await models_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}}) == pub0
        # --- rollback the whole session: draft soft-deleted, history kept
        r = await client.post("/api/v2/ai/rollback", json={"session_id": SID}, headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 200 and not r.json()["data"]["errors"], r.text
        assert (await models_col.find_one({"id": mid}, {"_id": 0, "is_deleted": 1}) or {}).get("is_deleted") is True
        assert await versions_col.count_documents({"entity_id": mid}) >= 3
        assert await _others_snapshot() == others0
    finally:
        await _set_mode(False)
    assert await _mode() is False
