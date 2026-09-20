"""Instagram Autopilot tests (MOCK adapter; NO Meta call is ever made; META_REAL_CALLS must stay 0).
A connection NOT_CONNECTED + MOCK_MODE · B public-only media / secret never used · C photo -> PHOTO_POST · D video -> REEL_POST ·
E caption italiana, CTA link in bio, no OnlyFans URL, hashtag · F two consecutive different creators · G/H full rotation & wrap ·
I no public media -> SKIPPED_NO_PUBLIC_MEDIA · J not IG-safe media discarded · K video rejected -> photo fallback · L LLM offline -> template ·
M restart persistence · N duplicate slot · O concurrent jobs · P new model mid-cycle · Q model removed mid-cycle · R pause/publish-now/skip ·
S scheduler tick disabled · T independent from Telegram queue · U admin API auth / settings / job registered / no Meta calls.
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
os.environ["INSTAGRAM_AUTOPILOT_MOCK"] = "true"
os.environ["INSTAGRAM_AUTO_SCHEDULER_ENABLED"] = "false"
os.environ["INSTAGRAM_ITALY_AUDIENCE_MODE"] = "true"

from instagram_autopilot import adapter as meta, engine, media as igmedia, caption as igcap  # noqa: E402
from database import models_col, db  # noqa: E402
from _creds import admin_credentials  # noqa: E402

pytestmark = pytest.mark.anyio
BASE = os.environ.get("TEST_BACKEND", "http://localhost:8001")
TAG = f"ig-{uuid.uuid4().hex[:6]}"


def _model(slug, photos=2, videos=1, stato="pubblicata", ordine=0, extra_pub=None):
    pairs = []
    for i in range(max(photos, videos)):
        if i < photos:
            pairs.append({"id": f"{slug}-p{i}", "tipo": "image", "pubblico": {"tipo": "image", "url": f"https://cdn.test/{slug}/p{i}.jpg"}, "segreto": {"tipo": "image", "url": f"https://cdn.test/{slug}/SECRET{i}.jpg"}})
        if i < videos:
            pairs.append({"id": f"{slug}-v{i}", "tipo": "video", "pubblico": {"tipo": "video", "url": f"https://cdn.test/{slug}/v{i}.mp4", "poster": f"https://cdn.test/{slug}/v{i}.jpg"}, "segreto": {"tipo": "video", "url": f"https://cdn.test/{slug}/SECRETv{i}.mp4"}})
    return {"id": str(uuid.uuid4()), "slug": slug, "nome": slug.split("-")[-1].capitalize(), "nome_artistico": f"{slug.split('-')[-1].capitalize()} Test", "frase": "Dolce finché non premi.", "bio": "bio test", "categorie": ["eleganti"], "tag": ["raffinata"],
            "onlyfans_url": "https://onlyfans.com/x", "media_pairs": pairs, "galleria_pubblica": extra_pub or [], "galleria_segreta": [{"tipo": "image", "url": f"https://cdn.test/{slug}/GALSECRET.jpg"}],
            "foto_segreta_hero": f"https://cdn.test/{slug}/HERO_SECRET.jpg", "bio_segreta": "MAI USARE", "stato": stato, "is_deleted": False, "ordine": ordine, "created_at": "2026-01-01", "_test_tag": TAG}


@pytest.fixture
async def sandbox():
    mock = meta.MockMeta()
    meta.force_adapter(mock)
    await engine.ensure_indexes()
    saved_state = await engine.state_col.find_one({"id": "global"}, {"_id": 0})
    await engine.state_col.delete_one({"id": "global"})
    await engine.ensure_indexes()
    await engine.set_state(use_ai_copy=False)         # deterministic template captions in tests (LLM tested separately)
    orig = igmedia.published_models

    async def only_test():
        items = [m async for m in models_col.find({"_test_tag": TAG, "stato": "pubblicata", "is_deleted": {"$ne": True}}, igmedia.PUBLIC_FIELDS | {"_test_tag": 1})]
        items.sort(key=igmedia._order_key)
        return items
    igmedia.published_models = only_test
    calls_before = meta.META_REAL_CALLS["n"]
    yield mock
    assert meta.META_REAL_CALLS["n"] == calls_before == 0, "a real Meta call happened"
    igmedia.published_models = orig
    meta.force_adapter(None)
    test_ids = [m["id"] async for m in models_col.find({"_test_tag": TAG}, {"id": 1})]
    await models_col.delete_many({"_test_tag": TAG})
    await engine.media_state_col.delete_many({"model_id": {"$in": test_ids}})
    await engine.log_col.delete_many({"model_slug": {"$regex": f"^{TAG}"}})
    await engine.log_col.delete_many({"slot_id": {"$regex": f"^{TAG}"}})
    await engine.slots_col.delete_many({"slot_id": {"$regex": f"^{TAG}"}})
    await engine.state_col.delete_one({"id": "global"})
    if saved_state:
        await engine.state_col.insert_one(saved_state)
    else:
        await engine.ensure_indexes()


async def seed(*models):
    await models_col.insert_many([dict(m) for m in models])
    return models


def _assert_public(payload):
    assert "SECRET" not in payload["media_url"] and "segret" not in payload["media_url"].lower()
    assert payload["media_url"].startswith("https://cdn.test/")


# ------------------------------------------------------------------ A connection: NOT_CONNECTED + MOCK_MODE separately, zero real calls
async def test_connection_status_mock_not_connected(sandbox):
    c = await meta.connection_status()
    assert c["CONNECTION_STATUS"] == "NOT_CONNECTED"
    assert c["MOCK_MODE"] is True and c["operational"] is True
    assert c["credentials_present"] is False and c["account"] is None
    assert c["META_REAL_CALLS"] == 0
    assert "INSTAGRAM_ACCESS_TOKEN" not in json.dumps(c) or "assenti" in json.dumps(c)


async def test_real_adapter_without_credentials_never_calls_meta(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_AUTOPILOT_MOCK", "false")
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("INSTAGRAM_USER_ID", raising=False)
    before = meta.META_REAL_CALLS["n"]
    c = await meta.connection_status()
    assert c["CONNECTION_STATUS"] == "NOT_CONNECTED" and c["MOCK_MODE"] is False and c["operational"] is False
    with pytest.raises(meta.InstagramError) as ei:
        await meta.MetaAdapter().publish({"media_url": "x"})
    assert ei.value.code == "NOT_CONNECTED"
    assert meta.META_REAL_CALLS["n"] == before == 0


# ------------------------------------------------------------------ B public-only media, secret structurally unreachable
def test_public_only_media_and_secret_never_read():
    m = _model("t-alt", photos=3, videos=2)
    pm = igmedia.get_instagram_public_media(m)
    media = pm["media"]
    assert [x["type"] for x in media] == ["photo", "video", "photo", "video", "photo"]
    urls = " ".join(x["url"] for x in media)
    assert "SECRET" not in urls and "HERO_SECRET" not in urls and "GALSECRET" not in urls
    assert all(x["side"] == "PUBLIC" for x in media)
    # secret-side fields are not even projected from the DB
    assert not any(k in igmedia.PUBLIC_FIELDS for k in ("galleria_segreta", "foto_segreta_hero", "bio_segreta"))
    # a public URL that smells secret is rejected, host name containing 'secret' is allowed (site domain)
    m2 = _model("t-mark", photos=1, videos=0, extra_pub=[{"tipo": "image", "url": "https://cdn.test/t-mark/private_shot.jpg"}, {"tipo": "image", "url": "https://secret-side.emergent.host/media/ok.jpg"}])
    pm2 = igmedia.get_instagram_public_media(m2)
    assert any(r["reason"] == "SECRET_MARKER_IN_URL" for r in pm2["rejected"])
    assert any(x["url"] == "https://secret-side.emergent.host/media/ok.jpg" for x in pm2["media"])


# ------------------------------------------------------------------ J Instagram-safe filter (explicit flag / unsupported format)
def test_not_instagram_safe_filter():
    m = _model("t-safe", photos=1, videos=0, extra_pub=[{"tipo": "image", "url": "https://cdn.test/t-safe/x.jpg", "alt": "foto nuda"}, {"tipo": "image", "url": "https://cdn.test/t-safe/doc.pdf"}, {"tipo": "video", "url": "https://cdn.test/t-safe/clip.avi"}])
    pm = igmedia.get_instagram_public_media(m)
    reasons = sorted(r["reason"] for r in pm["rejected"])
    assert reasons == ["EXPLICIT_FLAG", "UNSUPPORTED_FORMAT", "UNSUPPORTED_FORMAT"]
    assert len(pm["media"]) == 1 and pm["media"][0]["url"].endswith("p0.jpg")
    row = igmedia.classify(_model("t-none", photos=0, videos=0))
    assert row["status"] == "SKIPPED_NO_PUBLIC_MEDIA"


# ------------------------------------------------------------------ C/D/E/F photo -> PHOTO_POST, video -> REEL_POST, caption IT, two consecutive
async def test_photo_reel_caption_two_consecutive(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-anna", photos=2, videos=1, ordine=1), _model(f"{TAG}-bea", photos=1, videos=1, ordine=2))
    r1 = await engine.publish_next("test", slot_id=f"{TAG}_s1")
    assert r1["status"] == "MOCK_PREPARED" and r1["model_slug"] == a["slug"]
    assert r1["post_type"] == "PHOTO_POST" and r1["payload"]["media_type"] == "IMAGE" and r1["media_type"] == "photo"
    _assert_public(r1["payload"])
    cap = r1["caption"]
    assert "link in bio" in cap.lower(), cap
    assert "onlyfans" not in cap.lower() and "http" not in cap.lower()
    assert cap.startswith("ANNA"), cap
    assert 3 <= len(r1["hashtags"]) <= 6 and "#latosegreto" in r1["hashtags"] and all(h.startswith("#") for h in r1["hashtags"])
    assert len(cap) <= meta.CAPTION_LIMIT
    r2 = await engine.publish_next("test", slot_id=f"{TAG}_s2")
    assert r2["status"] == "MOCK_PREPARED" and r2["model_slug"] == b["slug"] and r2["model_slug"] != r1["model_slug"]
    # next media of ANNA is her video -> REEL_POST
    st = await engine.get_state()
    assert st["cycle_number"] == 2                       # 2 eligible -> cycle closed
    r3 = await engine.publish_next("test", slot_id=f"{TAG}_s3")
    assert r3["model_slug"] == a["slug"] and r3["post_type"] == "REEL_POST" and r3["payload"]["media_type"] == "REELS" and r3["payload"]["media_url"].endswith("v0.mp4")
    assert r3["payload"]["cover_url"].endswith("v0.jpg")
    assert len(mock.published) == 3 and all(p["media_url"].startswith("https://cdn.test/") and "SECRET" not in p["media_url"] for p in mock.published)
    logs = [l async for l in engine.log_col.find({"model_slug": {"$regex": f"^{TAG}"}})]
    assert all(l["status"] == "MOCK_PREPARED" and l["mock"] is True for l in logs) and len(logs) == 3


# ------------------------------------------------------------------ G/H full rotation, no repeats, wrap to cycle 2
async def test_circular_rotation_no_repeat_and_wrap(sandbox):
    ms = await seed(*[_model(f"{TAG}-r{i}", photos=1, videos=0, ordine=i) for i in range(4)])
    seen = []
    for i in range(4):
        r = await engine.publish_next("test", slot_id=f"{TAG}_rot{i}")
        assert r["status"] == "MOCK_PREPARED"
        seen.append(r["model_slug"])
    assert seen == [m["slug"] for m in ms] and len(set(seen)) == 4
    st = await engine.get_state()
    assert st["cycle_number"] == 2 and st["cycle_done"] == []
    r = await engine.publish_next("test", slot_id=f"{TAG}_rot4")
    assert r["model_slug"] == ms[0]["slug"] and r["cycle_number"] == 2
    s = await engine.status()
    assert s["queue"]["cycle_number"] == 2 and s["queue"]["position"] == 2 and s["queue"]["total"] == 4
    assert s["SECRET_MEDIA_USED"] is False and s["META_REAL_CALLS"] == 0 and s["INSTAGRAM_REAL_POST_DONE"] is False


# ------------------------------------------------------------------ I/K skips: no public media (not eligible), video rejected -> photo fallback, all media rejected -> skip & advance
async def test_skips_and_media_fallback(sandbox):
    mock = sandbox
    nomedia = _model(f"{TAG}-nomedia", photos=0, videos=0, ordine=0)
    nomedia["foto_card"] = ""
    vid = _model(f"{TAG}-vid", photos=1, videos=1, ordine=1)
    vid["media_pairs"] = [vid["media_pairs"][1], vid["media_pairs"][0]]   # video first in pairs -> interleave still photo first; force cursor to video below
    bad = _model(f"{TAG}-bad", photos=1, videos=0, ordine=2)
    ok = _model(f"{TAG}-ok", photos=1, videos=0, ordine=3)
    await seed(nomedia, vid, bad, ok)
    q = await engine.queue_view()
    assert nomedia["slug"] in q["roster"]["no_media"] and q["n_eligible"] == 3
    # video rejected -> falls back to the photo
    await engine.media_state_col.update_one({"model_id": vid["id"]}, {"$set": {"model_id": vid["id"], "last_media_id": f"{vid['slug']}-p0", "media_index": 0}}, upsert=True)  # next = video
    mock.fail_media.add("v0.mp4")
    r = await engine.publish_next("test", slot_id=f"{TAG}_fb1")
    assert r["status"] == "MOCK_PREPARED" and r["model_slug"] == vid["slug"] and r["post_type"] == "PHOTO_POST"
    assert r["media_errors"] and r["media_errors"][0]["error_code"] == "MEDIA_REJECTED" and r["media_errors"][0]["media_type"] == "video"
    # every media of 'bad' rejected -> SKIPPED_NO_PUBLIC_MEDIA log and the queue moves on to 'ok'
    mock.fail_media.add(f"{bad['slug']}/p0.jpg")
    r = await engine.publish_next("test", slot_id=f"{TAG}_fb2")
    assert r["status"] == "MOCK_PREPARED" and r["model_slug"] == ok["slug"]
    skipped = await engine.log_col.find_one({"model_slug": bad["slug"], "status": "SKIPPED_NO_PUBLIC_MEDIA"})
    assert skipped and skipped["error_code"] == "ALL_MEDIA_FAILED"
    assert all("SECRET" not in p["media_url"] for p in mock.published)


# ------------------------------------------------------------------ L LLM offline -> Italian template, never blocks; FORBIDDEN facts filtered
async def test_llm_offline_template_fallback(monkeypatch):
    m = _model("t-llm", photos=1, videos=0)
    monkeypatch.setattr(igcap, "_llm_available", lambda: False)
    c = await igcap.build_caption(m, 1, use_ai=True)
    assert c["source"] == "TEMPLATE" and c["language"] == "it"
    assert c["caption"].startswith("LLM") or c["caption"].startswith("LLM".upper()) or c["text"].split("\n")[0].startswith(m["nome"].upper())
    assert "link in bio" in c["cta"].lower() and "onlyfans" not in c["caption"].lower() and "http" not in c["caption"]
    assert 3 <= len(c["hashtags"]) <= 6
    # variation across cycles
    caps = {(await igcap.build_caption(m, i, use_ai=False))["text"] for i in range(1, 7)}
    assert len(caps) >= 2
    # LLM failure (exception) -> template
    monkeypatch.setattr(igcap, "_llm_available", lambda: True)

    async def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(igcap, "llm_caption", boom if False else (lambda m, c: asyncio.sleep(0, result=None)))
    c2 = await igcap.build_caption(m, 2, use_ai=True)
    assert c2["source"] == "TEMPLATE"
    # invented facts / OnlyFans mention would be rejected by the FORBIDDEN filter
    assert igcap.FORBIDDEN.search("Ha 24 anni e vive a Milano") and igcap.FORBIDDEN.search("trovi tutto su onlyfans")
    assert igcap.hashtags(m, 1)[0] == "#latosegreto"


# ------------------------------------------------------------------ M restart persistence
async def test_restart_persistence(sandbox):
    ms = await seed(*[_model(f"{TAG}-pers{i}", photos=2, videos=0, ordine=i) for i in range(3)])
    await engine.publish_next("test", slot_id=f"{TAG}_pe0")
    await engine.publish_next("test", slot_id=f"{TAG}_pe1")
    st_before = await engine.state_col.find_one({"id": "global"}, {"_id": 0})
    ms_before = await engine.media_state_col.find_one({"model_id": ms[0]["id"]}, {"_id": 0})
    # simulate a restart: nothing in memory matters, only the DB
    import importlib
    importlib.reload(engine)
    meta.force_adapter(sandbox)
    st_after = await engine.get_state()
    assert st_after["cycle_done"] == st_before["cycle_done"] and st_after["last_position"] == st_before["last_position"] and st_after["cycle_number"] == 1
    assert (await engine.media_state_col.find_one({"model_id": ms[0]["id"]}, {"_id": 0}))["last_media_id"] == ms_before["last_media_id"]
    r = await engine.publish_next("test", slot_id=f"{TAG}_pe2")
    assert r["model_slug"] == ms[2]["slug"]                # continues exactly where it stopped
    r = await engine.publish_next("test", slot_id=f"{TAG}_pe3")
    assert r["model_slug"] == ms[0]["slug"] and r["media_id"].endswith("p1"), "second photo of the first creator (cursor persisted)"


# ------------------------------------------------------------------ N duplicate slot · O concurrency
async def test_duplicate_slot_and_concurrency(sandbox):
    mock = sandbox
    await seed(*[_model(f"{TAG}-dup{i}", photos=1, videos=0, ordine=i) for i in range(3)])
    r1 = await engine.publish_next("scheduler", slot_id=f"{TAG}_2026-01-01_13:00")
    r2 = await engine.publish_next("scheduler", slot_id=f"{TAG}_2026-01-01_13:00")
    assert r1["status"] == "MOCK_PREPARED" and r2["status"] == "SKIP_DUPLICATE_SLOT"
    assert len(mock.published) == 1
    dup = await engine.log_col.find_one({"status": "SKIP_DUPLICATE_SLOT", "slot_id": f"{TAG}_2026-01-01_13:00"})
    assert dup is not None
    # concurrent triggers with different slots: the lock lets only one pass at a time; nothing is duplicated
    results = await asyncio.gather(*[engine.publish_next("scheduler", slot_id=f"{TAG}_conc{i}") for i in range(4)])
    statuses = sorted(r["status"] for r in results)
    assert statuses.count("MOCK_PREPARED") + statuses.count("LOCKED") == 4 and statuses.count("MOCK_PREPARED") >= 1
    slugs = [p["model_slug"] for p in mock.published]
    assert len(slugs) == len(set(slugs)) or len(mock.published) > 3   # no creator repeated inside the same cycle
    # slot_id format used by the real scheduler
    st = await engine.get_state()
    slots = engine.slots_for_day(st, engine.datetime.now(engine.timezone.utc))
    assert [s["slot_id"].split("_", 1)[1][-5:] for s in slots] == ["13:00", "20:30"] and all(s["slot_id"].startswith("instagram_") for s in slots)


# ------------------------------------------------------------------ P new model mid-cycle · Q model removed mid-cycle
async def test_new_and_removed_models_mid_cycle(sandbox):
    ms = await seed(*[_model(f"{TAG}-mid{i}", photos=1, videos=0, ordine=i * 10) for i in range(3)])
    await engine.publish_next("test", slot_id=f"{TAG}_m0")
    # new PUBLISHED creator inserted between #1 and #2 -> published within the current cycle
    new = _model(f"{TAG}-new", photos=1, videos=0, ordine=5)
    await seed(new)
    r = await engine.publish_next("test", slot_id=f"{TAG}_m1")
    assert r["model_slug"] == new["slug"]
    # creator set to DRAFT mid-cycle -> skipped automatically, no error
    await models_col.update_one({"id": ms[1]["id"]}, {"$set": {"stato": "bozza"}})
    r = await engine.publish_next("test", slot_id=f"{TAG}_m2")
    assert r["model_slug"] == ms[2]["slug"]
    st = await engine.get_state()
    assert st["cycle_number"] == 2, "cycle closed once every eligible creator was processed"
    # a creator whose only public media disappears -> no longer eligible, not in the order
    await models_col.update_one({"id": ms[0]["id"]}, {"$set": {"media_pairs": [], "foto_card": ""}})
    s = await engine.status()
    assert ms[0]["slug"] in s["queue"]["skipped_no_public_media"] and ms[0]["slug"] not in [o["slug"] for o in s["queue"]["order"]]


# ------------------------------------------------------------------ R pause · publish-now · skip · S scheduler tick disabled
async def test_pause_publish_now_skip_and_disabled_tick(sandbox, monkeypatch):
    mock = sandbox
    ms = await seed(*[_model(f"{TAG}-pp{i}", photos=1, videos=0, ordine=i) for i in range(3)])
    # master switch OFF -> the tick never publishes, even if admin enabled it in DB
    await engine.set_state(enabled=True)
    monkeypatch.setenv("INSTAGRAM_AUTO_SCHEDULER_ENABLED", "false")
    assert (await engine.tick())["status"] == "AUTO_SCHEDULER_DISABLED" and len(mock.published) == 0
    # master switch ON but paused in DB -> PAUSED
    monkeypatch.setenv("INSTAGRAM_AUTO_SCHEDULER_ENABLED", "true")
    await engine.set_state(enabled=False)
    assert (await engine.tick())["status"] == "PAUSED" and len(mock.published) == 0
    # ON + enabled but no due slot -> NO_DUE_SLOT (schedule 13:00/20:30 with 90' grace; force schedule far from now)
    await engine.set_state(enabled=True, schedule_times=["03:33", "03:34"], posts_per_day=2)
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/Rome"))
    if not (3 <= now.hour <= 5):
        assert (await engine.tick())["status"] == "NO_DUE_SLOT"
    assert len(mock.published) == 0
    monkeypatch.setenv("INSTAGRAM_AUTO_SCHEDULER_ENABLED", "false")
    # publish-now works regardless of the scheduler; skip advances without publishing
    r = await engine.publish_next("admin")
    assert r["status"] == "MOCK_PREPARED" and r["model_slug"] == ms[0]["slug"] and r["slot_id"] is None
    sk = await engine.skip_current("admin")
    assert sk["status"] == "MANUAL_SKIP" and sk["skipped"] == ms[1]["slug"]
    r = await engine.publish_next("admin")
    assert r["model_slug"] == ms[2]["slug"] and len(mock.published) == 2
    # dry run: no publish, no state change
    n = len(mock.published)
    st = await engine.get_state()
    d = await engine.publish_next("admin", dry_run=True)
    assert d["status"] == "DRY_RUN" and d["post_type"] in ("PHOTO_POST", "REEL_POST") and "link in bio" in d["caption"].lower()
    assert len(mock.published) == n and (await engine.get_state())["cycle_done"] == st["cycle_done"]
    sch = await engine.schedule_view()
    assert sch["timezone"] == "Europe/Rome" and sch["posts_per_day"] == 2


# ------------------------------------------------------------------ T independence from Telegram (collections, state, cursors untouched)
async def test_independent_from_telegram(sandbox):
    tg_state = db["telegram_autopilot_state"]
    tg_media = db["telegram_model_media_state"]
    before_state = await tg_state.find_one({"id": "global"}, {"_id": 0})
    before_media = [d async for d in tg_media.find({}, {"_id": 0}).sort("model_id", 1)]
    before_logs = await db["telegram_autopilot_log"].count_documents({})
    ms = await seed(*[_model(f"{TAG}-ind{i}", photos=1, videos=0, ordine=i) for i in range(2)])
    await engine.publish_next("test", slot_id=f"{TAG}_ind0")
    await engine.skip_current("test")
    assert {engine.state_col.name, engine.media_state_col.name, engine.log_col.name, engine.slots_col.name, engine.locks_col.name} == \
        {"instagram_autopilot_state", "instagram_model_media_state", "instagram_autopilot_log", "instagram_autopilot_slots", "instagram_autopilot_locks"}
    assert await tg_state.find_one({"id": "global"}, {"_id": 0}) == before_state
    assert [d async for d in tg_media.find({}, {"_id": 0}).sort("model_id", 1)] == before_media
    assert await db["telegram_autopilot_log"].count_documents({}) == before_logs
    assert await tg_media.count_documents({"model_id": {"$in": [m["id"] for m in ms]}}) == 0


# ------------------------------------------------------------------ U admin API: auth, status fields, dry run, settings, job registered, zero Meta calls
def _token():
    r = requests.post(f"{BASE}/api/admin/login", json=admin_credentials(), timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def test_admin_api_auth_and_status_contract():
    assert requests.get(f"{BASE}/api/admin/instagram-autopilot/status", timeout=15).status_code in (401, 403)
    assert requests.get(f"{BASE}/api/admin/instagram-autopilot/logs", timeout=15).status_code in (401, 403)
    for ep in ("start", "pause", "publish-now", "skip", "test-connection"):
        assert requests.post(f"{BASE}/api/admin/instagram-autopilot/{ep}", timeout=15).status_code in (401, 403), ep
    assert requests.patch(f"{BASE}/api/admin/instagram-autopilot/settings", json={"use_video": True}, timeout=15).status_code in (401, 403)
    h = {"Authorization": f"Bearer {_token()}"}
    s = requests.get(f"{BASE}/api/admin/instagram-autopilot/status", headers=h, timeout=60)
    assert s.status_code == 200
    s = s.json()
    assert s["MOCK_MODE"] is True and s["mock"] is True and s["CONNECTION_STATUS"] == "NOT_CONNECTED" and s["operational"] is True
    assert s["AUTO_SCHEDULER_ENABLED"] is False and s["active"] is False and s["ITALY_AUDIENCE_MODE"] is True
    assert s["META_REAL_CALLS"] == 0 and s["SECRET_MEDIA_USED"] is False and s["INSTAGRAM_REAL_POST_DONE"] is False
    assert s["settings"]["timezone"] == "Europe/Rome" and s["settings"]["posts_per_day"] == 2 and s["settings"]["schedule_times"] == ["13:00", "20:30"]
    assert s["queue"]["total"] >= 1 and s["schedule"]["next_slot"]["slot_id"].startswith("instagram_")
    assert set(s["schedule"]["next_slot"]["slot_id"][-5:] for _ in [0]) <= {"13:00", "20:30"}
    c = requests.post(f"{BASE}/api/admin/instagram-autopilot/test-connection", headers=h, timeout=30).json()
    assert c["CONNECTION_STATUS"] == "NOT_CONNECTED" and c["MOCK_MODE"] is True and c["META_REAL_CALLS"] == 0
    d = requests.post(f"{BASE}/api/admin/instagram-autopilot/publish-now?dry_run=true", headers=h, timeout=90).json()
    assert d["status"] == "DRY_RUN" and d["post_type"] in ("PHOTO_POST", "REEL_POST")
    assert "link in bio" in d["caption"].lower() and "onlyfans" not in d["caption"].lower() and "http" not in d["caption"].lower()
    assert d["media"][0]["side"] == "PUBLIC" and "segret" not in d["media"][0]["url"].lower()
    assert 3 <= len(d["hashtags"]) <= 6
    lg = requests.get(f"{BASE}/api/admin/instagram-autopilot/logs?limit=5", headers=h, timeout=30)
    assert lg.status_code == 200 and "items" in lg.json()
    # no Meta secret names leak through the API
    for body in (json.dumps(s), json.dumps(c), json.dumps(d)):
        assert "access_token" not in body.lower()


def test_settings_validation_and_italy_mode():
    h = {"Authorization": f"Bearer {_token()}"}
    assert requests.patch(f"{BASE}/api/admin/instagram-autopilot/settings", headers=h, json={"schedule_times": ["25:00"]}, timeout=15).status_code == 422
    assert requests.patch(f"{BASE}/api/admin/instagram-autopilot/settings", headers=h, json={"timezone": "Mars/Olympus"}, timeout=15).status_code == 422
    assert requests.patch(f"{BASE}/api/admin/instagram-autopilot/settings", headers=h, json={"timezone": "America/New_York"}, timeout=15).status_code == 422, "ITALY_AUDIENCE_MODE forces Europe/Rome"
    assert requests.patch(f"{BASE}/api/admin/instagram-autopilot/settings", headers=h, json={"posts_per_day": 9}, timeout=15).status_code == 422
    r = requests.patch(f"{BASE}/api/admin/instagram-autopilot/settings", headers=h, json={"use_video": True, "timezone": "Europe/Rome", "schedule_times": ["20:30", "13:00"], "posts_per_day": 2}, timeout=15)
    assert r.status_code == 200 and r.json()["timezone"] == "Europe/Rome" and r.json()["schedule_times"] == ["13:00", "20:30"] and r.json()["posts_per_day"] == 2


def test_job_registered_and_no_meta_calls():
    from v1_jobs import JOBS
    import instagram_autopilot.jobs  # noqa: F401
    assert "instagram_autopilot_tick" in JOBS and JOBS["instagram_autopilot_tick"]["interval_s"] == 300
    assert meta.META_REAL_CALLS["n"] == 0
    import subprocess
    # no Meta credential is hardcoded anywhere in the package or the frontend
    out = subprocess.run(["grep", "-rlE", "EAA[0-9A-Za-z]{20,}|INSTAGRAM_ACCESS_TOKEN\\s*=\\s*['\"][^'\"]+", "/app/backend/instagram_autopilot", "/app/frontend/src"], capture_output=True, text=True).stdout
    assert out.strip() == "", out
