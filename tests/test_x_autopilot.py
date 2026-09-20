"""X Autopilot tests (MockXAdapter; NO X call is ever made; X_REAL_CALLS must stay 0).
A eligibility · B public+secret pairing · C PUBLIC first / SECRET second · D Italian copy · E model's own OF link · F bad OF -> skip ·
G no public · H no secret · I X-safe fallback · J two consecutive · K full cycle · L wrap · M new model mid-cycle · N model disabled mid-cycle ·
O public cursor · P secret cursor · Q LLM offline · R restart persistence · S duplicate slot · T concurrency · U pause · V publish-now mock ·
W skip · X Italy Audience Mode · Y zero real X calls  +  PHOTO_PAIR_SINGLE_POST · VIDEO_THREAD_FALLBACK · PUBLIC_FIRST_IN_THREAD ·
THREAD_COUNTS_AS_ONE_ROTATION_ITEM · PARTIAL_THREAD_FAILURE_HANDLED · independence from Telegram/Instagram.
"""
import asyncio
import json
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/tests")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")
os.environ["X_AUTOPILOT_MOCK"] = "true"
os.environ["X_AUTO_SCHEDULER_ENABLED"] = "false"
os.environ["X_ITALY_AUDIENCE_MODE"] = "true"

from x_autopilot import adapter as xapi, engine, media as xmedia, copy as xcopy  # noqa: E402
from database import models_col, db  # noqa: E402
from _creds import admin_credentials  # noqa: E402

pytestmark = pytest.mark.anyio
BASE = os.environ.get("TEST_BACKEND", "http://localhost:8001")
TAG = f"xt-{uuid.uuid4().hex[:6]}"


def _model(slug, pub_photos=2, pub_videos=0, sec_photos=2, sec_videos=0, of=None, stato="pubblicata", ordine=0):
    pairs = []
    n = max(pub_photos + pub_videos, sec_photos + sec_videos)
    for i in range(n):
        pub = {"tipo": "image", "url": f"https://cdn.test/{slug}/pub_p{i}.jpg"} if i < pub_photos else ({"tipo": "video", "url": f"https://cdn.test/{slug}/pub_v{i}.mp4", "poster": f"https://cdn.test/{slug}/pub_v{i}.jpg"} if i < pub_photos + pub_videos else None)
        sec = {"tipo": "image", "url": f"https://cdn.test/{slug}/sec_p{i}.jpg"} if i < sec_photos else ({"tipo": "video", "url": f"https://cdn.test/{slug}/sec_v{i}.mp4"} if i < sec_photos + sec_videos else None)
        pairs.append({"id": f"{slug}-{i}", "tipo": "image", "pubblico": pub or {}, "segreto": sec or {}})
    return {"id": str(uuid.uuid4()), "slug": slug, "nome": slug.split("-")[-1].capitalize(), "nome_artistico": f"{slug.split('-')[-1].capitalize()} Test", "frase": "Dolce finché non premi.", "bio": "bio test",
            "categorie": ["eleganti"], "tag": ["raffinata"], "onlyfans_url": of if of is not None else f"https://onlyfans.com/{slug}", "media_pairs": pairs, "galleria_pubblica": [], "galleria_segreta": [],
            "stato": stato, "is_deleted": False, "ordine": ordine, "created_at": "2026-01-01", "_test_tag": TAG}


@pytest.fixture
async def sandbox():
    mock = xapi.MockXAdapter()
    xapi.force_adapter(mock)
    await engine.ensure_indexes()
    saved_state = await engine.state_col.find_one({"id": "global"}, {"_id": 0})
    await engine.state_col.delete_one({"id": "global"})
    await engine.ensure_indexes()
    await engine.set_state(use_ai_copy=False)
    orig = xmedia.published_models

    async def only_test():
        items = [m async for m in models_col.find({"_test_tag": TAG, "stato": "pubblicata", "is_deleted": {"$ne": True}}, xmedia.FIELDS | {"_test_tag": 1})]
        items.sort(key=xmedia._order_key)
        return items
    xmedia.published_models = only_test
    yield mock
    assert xapi.X_REAL_CALLS["n"] == 0, "a real X call happened"
    xmedia.published_models = orig
    xapi.force_adapter(None)
    test_ids = [m["id"] async for m in models_col.find({"_test_tag": TAG}, {"id": 1})]
    await models_col.delete_many({"_test_tag": TAG})
    await engine.media_state_col.delete_many({"model_id": {"$in": test_ids}})
    await engine.log_col.delete_many({"$or": [{"model_slug": {"$regex": f"^{TAG}"}}, {"slot_id": {"$regex": f"^{TAG}"}}]})
    await engine.slots_col.delete_many({"slot_id": {"$regex": f"^{TAG}"}})
    await engine.state_col.delete_one({"id": "global"})
    if saved_state:
        await engine.state_col.insert_one(saved_state)
    else:
        await engine.ensure_indexes()


async def seed(*models):
    await models_col.insert_many([dict(m) for m in models])
    return models


def _check_post(r, m, fmt=None):
    assert r["status"] == "MOCK_PREPARED", r
    assert r["media_order"] == ["PUBLIC", "SECRET"]
    assert "/pub_" in r["public_media_id"] or r["public_media_id"].startswith("pub:")
    assert r["secret_media_id"].startswith("sec:")
    assert r["of_url"] == m["onlyfans_url"] and r["of_url"] in r["text"]
    assert r["text"].count("http") == 1 and xapi.x_len(r["text"]) <= 280
    if fmt:
        assert r["format"] == fmt


# ------------------------------------------------------------------ A eligibility · F bad OF · G no public · H no secret
def test_eligibility_and_of_validation():
    assert xmedia.valid_of_link("https://onlyfans.com/vanessa") == "https://onlyfans.com/vanessa"
    assert xmedia.valid_of_link("onlyfans.com/vanessa") == "https://onlyfans.com/vanessa"
    for bad in ("", None, "https://onlyfans.com/", "https://latosegreto.it/vanessa", "https://instagram.com/vanessa", "https://t.me/latosegreto", "https://onlyfans.com.evil.io/x", "https://notonlyfans.com/x"):
        assert xmedia.valid_of_link(bad) is None, bad
    assert xmedia.classify(_model("a-ok"))["status"] == "ELIGIBLE"
    assert xmedia.classify(_model("a-nopub", pub_photos=0))["status"] == "SKIPPED_NO_PUBLIC_MEDIA"
    assert xmedia.classify(_model("a-nosec", sec_photos=0))["status"] == "SKIPPED_NO_SECRET_MEDIA"
    assert xmedia.classify(_model("a-noof", of="https://instagram.com/x"))["status"] == "SKIPPED_NO_OF_LINK"
    assert xmedia.classify(_model("a-emptyof", of=""))["status"] == "SKIPPED_NO_OF_LINK"


# ------------------------------------------------------------------ B pairing · I X-safe filter
def test_media_sides_and_x_safe():
    m = _model("b-pair", pub_photos=1, pub_videos=1, sec_photos=1, sec_videos=1)
    m["galleria_segreta"] = [{"tipo": "image", "url": "https://cdn.test/b-pair/gal_nsfw.jpg"}, {"tipo": "image", "url": "https://cdn.test/b-pair/gal_ok.jpg", "x_safe": False}, {"tipo": "image", "url": "https://cdn.test/b-pair/doc.pdf"}, {"tipo": "image", "url": "https://cdn.test/b-pair/fine.jpg"}]
    xm = xmedia.get_x_media(m)
    assert [x["type"] for x in xm["public"]] == ["photo", "video"] and all(x["side"] == "PUBLIC" for x in xm["public"])
    assert [x["type"] for x in xm["secret"]] == ["photo", "photo", "video"] and all(x["side"] == "SECRET" for x in xm["secret"]), "photos first, then videos"
    assert sorted(r["reason"] for r in xm["rejected"]) == ["EXPLICIT_FLAG", "EXPLICIT_MARKER", "UNSUPPORTED_FORMAT"]
    # secret URLs containing 'secret'/'segreto' are of course allowed on X (they ARE the secret side)
    m2 = _model("b-name", sec_photos=0)
    m2["foto_segreta_hero"] = "https://secret-side.emergent.host/media/segreto/hero.jpg"
    assert xmedia.classify(m2)["status"] == "ELIGIBLE"


# ------------------------------------------------------------------ D Italian copy · E OF link · X Italy mode · Q LLM offline
async def test_copy_italian_of_link_and_fallback(monkeypatch):
    m = _model("d-copy")
    monkeypatch.setattr(xcopy, "_llm_available", lambda: False)
    c = await xcopy.build_copy(m, m["onlyfans_url"], 1, use_ai=True, italy=True)
    assert c["source"] == "TEMPLATE" and c["language"] == "it"
    assert m["onlyfans_url"] in c["text"] and c["text"].count("http") == 1
    assert "Lato" in c["text"] and ("Pubblico" in c["text"] or "vedono" in c["text"] or "conoscono" in c["text"] or "luce" in c["text"] or "lati" in c["text"])
    assert "D-COPY TEST" in c["text"] or "D-COPY" in c["text"].upper()
    assert 3 <= len(c["hashtags"]) <= 5 and c["hashtags"][0] == "#LatoSegreto"
    assert c["x_length"] <= 280 and c["reply_text"]
    assert not xcopy.ENGLISH_HINT.search(c["body"]), c["body"]
    # a different template every cycle
    texts = {(await xcopy.build_copy(m, m["onlyfans_url"], i, use_ai=False))["body"] for i in range(1, 7)}
    assert len(texts) >= 5
    # LLM returning None/exception -> template, never fails
    monkeypatch.setattr(xcopy, "_llm_available", lambda: True)
    monkeypatch.setattr(xcopy, "llm_text", lambda m, c, italy=True: asyncio.sleep(0, result=None))
    assert (await xcopy.build_copy(m, m["onlyfans_url"], 2, use_ai=True))["source"] == "TEMPLATE"
    # invented facts / platform mentions rejected by the FORBIDDEN filter
    assert xcopy.FORBIDDEN.search("Ha 24 anni e vive a Milano") and xcopy.FORBIDDEN.search("seguila su instagram")
    # never a foreign OF link: caller must pass the model's own validated link
    with pytest.raises(AssertionError):
        await xcopy.build_copy(m, "https://latosegreto.it/x", 1, use_ai=False)
    # 280 weighted limit holds even with a very long phrase
    m["frase"] = "x" * 70
    m["nome_artistico"] = "Nome Molto Lungo Della Creator Di Prova"
    for i in range(1, 7):
        assert (await xcopy.build_copy(m, m["onlyfans_url"], i, use_ai=False))["x_length"] <= 280


# ------------------------------------------------------------------ C/J/V photo pair SINGLE_POST, PUBLIC first, two consecutive, publish-now mock
async def test_photo_pair_single_post_two_consecutive(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-anna", ordine=1), _model(f"{TAG}-bea", ordine=2))
    r1 = await engine.publish_next("admin")
    _check_post(r1, a, "SINGLE_POST")
    assert r1["model_slug"] == a["slug"] and r1["slot_id"] is None
    p = mock.published[0]
    assert p["kind"] == "MAIN" and p["media_order"] == ["PUBLIC", "SECRET"] and [x["side"] for x in p["media"]] == ["PUBLIC", "SECRET"]
    assert p["media"][0]["url"].endswith("pub_p0.jpg") and p["media"][1]["url"].endswith("sec_p0.jpg") and len(p["media_ids"]) == 2
    assert p["in_reply_to"] is None and a["onlyfans_url"] in p["text"]
    r2 = await engine.publish_next("admin")
    _check_post(r2, b, "SINGLE_POST")
    assert r2["model_slug"] == b["slug"] and r2["model_slug"] != r1["model_slug"]
    assert b["onlyfans_url"] in mock.published[1]["text"] and a["onlyfans_url"] not in mock.published[1]["text"]
    assert len(mock.published) == 2
    logs = [l async for l in engine.log_col.find({"model_slug": {"$regex": f"^{TAG}"}})]
    assert len(logs) == 2 and all(l["status"] == "MOCK_PREPARED" and l["mock"] and l["x_post_id"].startswith("mock_x_") and l["public_media_id"] and l["secret_media_id"] for l in logs)


# ------------------------------------------------------------------ VIDEO_THREAD_FALLBACK · PUBLIC_FIRST_IN_THREAD · THREAD = ONE ROTATION ITEM · PARTIAL failure
async def test_video_thread_fallback_and_partial_failure(sandbox):
    mock = sandbox
    vp = _model(f"{TAG}-vidpub", pub_photos=0, pub_videos=1, sec_photos=1, ordine=1)     # PUBLIC video + SECRET photo
    vs = _model(f"{TAG}-vidsec", pub_photos=1, sec_photos=0, sec_videos=1, ordine=2)     # PUBLIC photo + SECRET video
    vv = _model(f"{TAG}-vidvid", pub_photos=0, pub_videos=1, sec_photos=0, sec_videos=1, ordine=3)
    mixed = _model(f"{TAG}-mixed", pub_photos=1, pub_videos=1, sec_photos=1, sec_videos=1, ordine=4)  # has photos -> photo pair preferred
    await seed(vp, vs, vv, mixed)
    st0 = await engine.get_state()
    r = await engine.publish_next("admin", slot_id=f"{TAG}_t1")
    _check_post(r, vp, "THREAD")
    assert r["public_media_type"] == "video" and r["secret_media_type"] == "photo" and r["x_reply_id"]
    main, reply = mock.published[-2], mock.published[-1]
    assert main["kind"] == "MAIN" and main["media"][0]["side"] == "PUBLIC" and main["media_order"] == ["PUBLIC"] and len(main["media_ids"]) == 1
    assert reply["kind"] == "REPLY" and reply["media"][0]["side"] == "SECRET" and reply["in_reply_to"] == main["x_post_id"]
    assert vp["onlyfans_url"] in main["text"] and "http" not in reply["text"]
    st1 = await engine.get_state()
    assert len(st1["cycle_done"]) == len(st0["cycle_done"]) + 1, "thread counted as ONE rotation item"
    assert await engine.slots_col.count_documents({"slot_id": f"{TAG}_t1"}) == 1
    assert await engine.log_col.count_documents({"slot_id": f"{TAG}_t1"}) == 1
    r = await engine.publish_next("admin")
    _check_post(r, vs, "THREAD")
    assert r["public_media_type"] == "photo" and r["secret_media_type"] == "video"
    r = await engine.publish_next("admin")
    _check_post(r, vv, "THREAD")
    # photo pair preferred when both sides have photos, even though videos exist
    r = await engine.publish_next("admin")
    _check_post(r, mixed, "SINGLE_POST")
    assert r["public_media_type"] == "photo" and r["secret_media_type"] == "photo"
    # PARTIAL: main published, SECRET reply fails -> PARTIAL_FAILED / THREAD_SECRET_FAILED, queue advances once, no duplicate
    mock.fail_reply = True
    n = len(mock.published)
    r = await engine.publish_next("admin", slot_id=f"{TAG}_t2")        # cycle 2 -> vidpub again
    assert r["status"] == "PARTIAL_FAILED" and r["model_slug"] == vp["slug"] and r["format"] == "THREAD"
    assert len(mock.published) == n + 1, "only the main post exists, no uncontrolled retries"
    lg = await engine.log_col.find_one({"slot_id": f"{TAG}_t2"})
    assert lg["status"] == "PARTIAL_FAILED" and lg["error_code"] == "THREAD_SECRET_FAILED" and lg["x_post_id"]
    st2 = await engine.get_state()
    assert vp["id"] in st2["cycle_done"] and st2["cycle_number"] == 2
    mock.fail_reply = False
    r = await engine.publish_next("admin")
    assert r["model_slug"] == vs["slug"], "queue moved on after the partial failure"


# ------------------------------------------------------------------ K/L full cycle + wrap
async def test_full_cycle_and_wrap(sandbox):
    ms = await seed(*[_model(f"{TAG}-r{i}", ordine=i) for i in range(4)])
    seen = [(await engine.publish_next("admin", slot_id=f"{TAG}_c{i}"))["model_slug"] for i in range(4)]
    assert seen == [m["slug"] for m in ms] and len(set(seen)) == 4
    st = await engine.get_state()
    assert st["cycle_number"] == 2 and st["cycle_done"] == [] and st["current_model_id"] == ms[0]["id"]
    r = await engine.publish_next("admin")
    assert r["model_slug"] == ms[0]["slug"] and r["cycle_number"] == 2
    s = await engine.status()
    assert s["queue"]["cycle_number"] == 2 and s["queue"]["position"] == 2 and s["queue"]["total"] == 4 and s["X_REAL_CALLS"] == 0 and s["X_REAL_POST_DONE"] is False


# ------------------------------------------------------------------ O/P two independent cursors (public_1+secret_1, public_2+secret_2, wrap on the shorter list)
async def test_media_cursors_public_and_secret(sandbox):
    m, = await seed(_model(f"{TAG}-cur", pub_photos=3, sec_photos=2))
    pairs = []
    for i in range(6):
        r = await engine.publish_next("admin")
        pairs.append((r["public_media_id"].split(":")[-1], r["secret_media_id"].split(":")[-1]))
    ids = [p["id"] for p in m["media_pairs"]]
    pub_seq = [p[0] for p in pairs]
    sec_seq = [p[1] for p in pairs]
    assert pub_seq == [ids[0], ids[1], ids[2], ids[0], ids[1], ids[2]], pub_seq          # public cursor wraps on 3
    assert sec_seq == [ids[0], ids[1], ids[0], ids[1], ids[0], ids[1]], sec_seq          # secret cursor wraps on 2 (independent)
    assert len(set(pairs)) == 6, "never the same pair while lists have different lengths"
    ms = await engine.media_state_col.find_one({"model_id": m["id"]}, {"_id": 0})
    assert {"public_media_index", "secret_media_index", "last_public_media_id", "last_secret_media_id", "last_published_at", "cycle_last_used"} <= set(ms)
    assert ms["public_media_index"] == 2 and ms["secret_media_index"] == 1 and ms["cycle_last_used"] == 6


# ------------------------------------------------------------------ I fallback: public rejected -> next public; secret rejected -> next secret; none -> skip model, continue
async def test_media_fallbacks_and_skip(sandbox):
    mock = sandbox
    a = _model(f"{TAG}-fa", pub_photos=2, sec_photos=2, ordine=1)
    dead = _model(f"{TAG}-dead", pub_photos=1, sec_photos=1, ordine=2)
    c = _model(f"{TAG}-fc", ordine=3)
    await seed(a, dead, c)
    mock.fail_media.update({f"{a['slug']}/pub_p0.jpg", f"{a['slug']}/sec_p0.jpg", f"{dead['slug']}/sec_p0.jpg"})
    r = await engine.publish_next("admin", slot_id=f"{TAG}_f1")
    _check_post(r, a, "SINGLE_POST")
    assert r["public_media_id"].endswith("-1") and r["secret_media_id"].endswith("-1"), r     # both sides fell back to the second media
    assert len(r["media_errors"]) >= 2
    r = await engine.publish_next("admin", slot_id=f"{TAG}_f2")
    _check_post(r, c)                                                                          # 'dead' skipped automatically, queue continues
    sk = await engine.log_col.find_one({"model_slug": dead["slug"]})
    assert sk["status"] == "SKIPPED_NO_SECRET_MEDIA" and sk["error_code"] == "NO_VALID_PAIR"
    assert (await engine.get_state())["cycle_number"] == 2


# ------------------------------------------------------------------ M new model mid-cycle · N model disabled mid-cycle
async def test_new_and_disabled_models_mid_cycle(sandbox):
    ms = await seed(*[_model(f"{TAG}-mid{i}", ordine=i * 10) for i in range(3)])
    await engine.publish_next("admin")
    new = _model(f"{TAG}-new", ordine=5)                          # inserted between #1 and #2 while we are at position 1
    await seed(new)
    r = await engine.publish_next("admin")
    assert r["model_slug"] == new["slug"], "new PUBLISHED model published inside the current cycle"
    st = await engine.get_state()
    assert st["cycle_number"] == 1 and len(st["cycle_done"]) == 2
    await models_col.update_one({"id": ms[1]["id"]}, {"$set": {"stato": "bozza"}})          # DRAFT mid-cycle
    await models_col.update_one({"id": ms[2]["id"]}, {"$set": {"onlyfans_url": ""}})       # OF removed mid-cycle
    late = _model(f"{TAG}-late", ordine=99)
    await seed(late)
    r = await engine.publish_next("admin")
    assert r["model_slug"] == late["slug"]
    s = await engine.status()
    assert ms[2]["slug"] in s["queue"]["skipped_no_of_link"] and ms[1]["slug"] not in [o["slug"] for o in s["queue"]["order"]]
    assert (await engine.get_state())["cycle_number"] == 2, "cycle closed once all eligible were processed (new included, disabled excluded)"


# ------------------------------------------------------------------ R restart persistence
async def test_restart_persistence(sandbox):
    ms = await seed(*[_model(f"{TAG}-pers{i}", pub_photos=2, sec_photos=3, ordine=i) for i in range(3)])
    await engine.publish_next("admin")
    await engine.publish_next("admin")
    before = await engine.state_col.find_one({"id": "global"}, {"_id": 0})
    import importlib
    importlib.reload(engine)
    xapi.force_adapter(sandbox)
    after = await engine.get_state()
    assert after["cycle_done"] == before["cycle_done"] and after["last_position"] == before["last_position"] and after["cycle_number"] == 1
    r = await engine.publish_next("admin")
    assert r["model_slug"] == ms[2]["slug"]
    r = await engine.publish_next("admin")
    assert r["model_slug"] == ms[0]["slug"] and r["public_media_id"].endswith("-1") and r["secret_media_id"].endswith("-1"), "both cursors persisted"


# ------------------------------------------------------------------ S duplicate slot · T concurrency
async def test_duplicate_slot_and_concurrency(sandbox):
    mock = sandbox
    await seed(*[_model(f"{TAG}-dup{i}", ordine=i) for i in range(3)])
    r1 = await engine.publish_next("scheduler", slot_id=f"{TAG}_2026-01-01_12:30")
    r2 = await engine.publish_next("scheduler", slot_id=f"{TAG}_2026-01-01_12:30")
    assert r1["status"] == "MOCK_PREPARED" and r2["status"] == "SKIP_DUPLICATE_SLOT" and len(mock.published) == 1
    assert await engine.log_col.find_one({"status": "SKIP_DUPLICATE_SLOT", "slot_id": f"{TAG}_2026-01-01_12:30"})
    results = await asyncio.gather(*[engine.publish_next("scheduler", slot_id=f"{TAG}_conc{i}") for i in range(4)])
    statuses = [r["status"] for r in results]
    assert set(statuses) <= {"MOCK_PREPARED", "LOCKED"} and statuses.count("MOCK_PREPARED") >= 1
    slugs = [p["model_slug"] for p in mock.published]
    assert len(slugs) == len(set(slugs)) or len(slugs) > 3, "no model repeated inside the same cycle"
    st = await engine.get_state()
    slots = engine.slots_for_day(st, engine.datetime.now(engine.timezone.utc))
    assert [s["slot_id"][-5:] for s in slots] == ["12:30", "18:30", "22:00"] and all(s["slot_id"].startswith("x_") for s in slots)


# ------------------------------------------------------------------ U pause · W skip · scheduler tick disabled · preview does not mutate
async def test_pause_skip_tick_and_preview(sandbox, monkeypatch):
    mock = sandbox
    ms = await seed(*[_model(f"{TAG}-pp{i}", ordine=i) for i in range(3)])
    await engine.set_state(enabled=True)
    monkeypatch.setenv("X_AUTO_SCHEDULER_ENABLED", "false")
    assert (await engine.tick())["status"] == "AUTO_SCHEDULER_DISABLED" and not mock.published
    monkeypatch.setenv("X_AUTO_SCHEDULER_ENABLED", "true")
    await engine.set_state(enabled=False)
    assert (await engine.tick())["status"] == "PAUSED" and not mock.published
    await engine.set_state(enabled=True, schedule_times=["03:33", "03:34", "03:35"], posts_per_day=3)
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if not (3 <= datetime.now(ZoneInfo("Europe/Rome")).hour <= 5):
        assert (await engine.tick())["status"] == "NO_DUE_SLOT"
    assert not mock.published
    monkeypatch.setenv("X_AUTO_SCHEDULER_ENABLED", "false")
    st = await engine.get_state()
    pv = await engine.preview()
    assert pv["status"] == "PREVIEW" and pv["model_slug"] == ms[0]["slug"] and pv["public"]["side"] == "PUBLIC" and pv["secret"]["side"] == "SECRET"
    assert pv["format"] == "SINGLE_POST" and pv["of_url"] == ms[0]["onlyfans_url"] and pv["of_url"] in pv["text"] and 3 <= len(pv["hashtags"]) <= 5 and pv["slot"]
    assert (await engine.get_state())["cycle_done"] == st["cycle_done"] and not mock.published, "preview never publishes or mutates"
    sk = await engine.skip_current("admin")
    assert sk["status"] == "MANUAL_SKIP" and sk["skipped"] == ms[0]["slug"]
    r = await engine.publish_next("admin")
    assert r["model_slug"] == ms[1]["slug"] and len(mock.published) == 1


# ------------------------------------------------------------------ Independence from Telegram AND Instagram
async def test_independent_from_telegram_and_instagram(sandbox):
    others = ["telegram_autopilot_state", "telegram_model_media_state", "telegram_autopilot_log", "instagram_autopilot_state", "instagram_model_media_state", "instagram_autopilot_log"]
    snap = {c: [d async for d in db[c].find({}, {"_id": 0}).sort("_id", 1)] for c in others}
    await seed(*[_model(f"{TAG}-ind{i}", ordine=i) for i in range(2)])
    await engine.publish_next("admin", slot_id=f"{TAG}_ind0")
    await engine.skip_current("admin")
    assert {engine.state_col.name, engine.media_state_col.name, engine.log_col.name, engine.slots_col.name, engine.locks_col.name} == \
        {"x_autopilot_state", "x_model_media_state", "x_autopilot_log", "x_autopilot_slots", "x_autopilot_locks"}
    for c in others:
        assert [d async for d in db[c].find({}, {"_id": 0}).sort("_id", 1)] == snap[c], c


# ------------------------------------------------------------------ Y adapter without credentials never calls X · admin API contract
async def test_real_adapter_without_credentials(monkeypatch):
    monkeypatch.setenv("X_AUTOPILOT_MOCK", "false")
    for k in xapi.FUTURE_ENV:
        monkeypatch.delenv(k, raising=False)
    c = await xapi.connection_status()
    assert c["CONNECTION_STATUS"] == "NOT_CONNECTED" and c["MOCK_MODE"] is False and c["operational"] is False
    for coro in (xapi.RealXAdapter().upload_media({"url": "x"}), xapi.RealXAdapter().create_post({})):
        with pytest.raises(xapi.XError) as ei:
            await coro
        assert ei.value.code == "NOT_CONNECTED"
    assert xapi.X_REAL_CALLS["n"] == 0
    assert xapi.x_len("ciao https://onlyfans.com/una-url-molto-lunga-che-conta-23") == 5 + 23


def _token():
    r = requests.post(f"{BASE}/api/admin/login", json=admin_credentials(), timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def test_admin_api_auth_status_preview():
    for ep in ("status", "logs"):
        assert requests.get(f"{BASE}/api/admin/x-autopilot/{ep}", timeout=15).status_code in (401, 403)
    for ep in ("start", "pause", "publish-now", "skip", "preview", "test-connection"):
        assert requests.post(f"{BASE}/api/admin/x-autopilot/{ep}", timeout=15).status_code in (401, 403), ep
    assert requests.patch(f"{BASE}/api/admin/x-autopilot/settings", json={"use_ai_copy": True}, timeout=15).status_code in (401, 403)
    h = {"Authorization": f"Bearer {_token()}"}
    s = requests.get(f"{BASE}/api/admin/x-autopilot/status", headers=h, timeout=60)
    assert s.status_code == 200
    s = s.json()
    assert s["MOCK_MODE"] is True and s["CONNECTION_STATUS"] == "NOT_CONNECTED" and s["operational"] is True and s["AUTO_SCHEDULER_ENABLED"] is False and s["active"] is False
    assert s["ITALY_AUDIENCE_MODE"] is True and s["X_REAL_CALLS"] == 0 and s["X_REAL_POST_DONE"] is False
    assert s["settings"]["timezone"] == "Europe/Rome" and s["settings"]["posts_per_day"] == 3 and s["settings"]["schedule_times"] == ["12:30", "18:30", "22:00"]
    assert s["queue"]["total"] >= 1 and s["schedule"]["next_slot"]["slot_id"].startswith("x_") and s["schedule"]["next_slot"]["slot_id"][-5:] in ("12:30", "18:30", "22:00")
    for k in ("skipped_no_public_media", "skipped_no_secret_media", "skipped_no_of_link", "not_x_safe"):
        assert k in s["queue"]
    c = requests.post(f"{BASE}/api/admin/x-autopilot/test-connection", headers=h, timeout=30).json()
    assert c["CONNECTION_STATUS"] == "NOT_CONNECTED" and c["MOCK_MODE"] is True and c["X_REAL_CALLS"] == 0
    p = requests.post(f"{BASE}/api/admin/x-autopilot/preview", headers=h, timeout=120).json()
    assert p["status"] == "PREVIEW" and p["public"]["side"] == "PUBLIC" and p["secret"]["side"] == "SECRET" and p["media_order"] == ["PUBLIC", "SECRET"]
    assert p["format"] in ("SINGLE_POST", "THREAD") and p["of_url"].startswith("https://onlyfans.com/") and p["of_url"] in p["text"] and p["text"].count("http") == 1
    assert 3 <= len(p["hashtags"]) <= 5 and p["x_length"] <= 280 and p["slot"]["slot_id"].startswith("x_")
    for body in (json.dumps(s), json.dumps(c), json.dumps(p)):
        assert "access_token" not in body.lower() and "api_secret" not in body.lower()


def test_settings_validation_and_job():
    h = {"Authorization": f"Bearer {_token()}"}
    u = f"{BASE}/api/admin/x-autopilot/settings"
    assert requests.patch(u, headers=h, json={"schedule_times": ["25:00"]}, timeout=15).status_code == 422
    assert requests.patch(u, headers=h, json={"timezone": "Mars/Olympus"}, timeout=15).status_code == 422
    assert requests.patch(u, headers=h, json={"timezone": "America/New_York"}, timeout=15).status_code == 422
    assert requests.patch(u, headers=h, json={"posts_per_day": 9}, timeout=15).status_code == 422
    r = requests.patch(u, headers=h, json={"timezone": "Europe/Rome", "schedule_times": ["22:00", "12:30", "18:30"], "posts_per_day": 3, "use_ai_copy": True, "italy_audience_mode": True}, timeout=15)
    assert r.status_code == 200 and r.json()["schedule_times"] == ["12:30", "18:30", "22:00"] and r.json()["italy_audience_mode"] is True
    from v1_jobs import JOBS
    import x_autopilot.jobs  # noqa: F401
    assert "x_autopilot_tick" in JOBS and JOBS["x_autopilot_tick"]["interval_s"] == 300
    import subprocess
    out = subprocess.run(["grep", "-rlE", "X_(API_KEY|API_SECRET|ACCESS_TOKEN|ACCESS_TOKEN_SECRET)\\s*=\\s*['\"][^'\"]+", "/app/backend/x_autopilot", "/app/frontend/src"], capture_output=True, text=True).stdout
    assert out.strip() == "", out
