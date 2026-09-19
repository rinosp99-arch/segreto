"""Telegram Autopilot tests (mock Telegram; NO real message is ever sent from tests).
A connection · B bot admin · C permissions · D photo · E video · F caption · G OF link · H two consecutive · I/J full rotation & wrap ·
K no OF · L no media · M video fail -> photo fallback · N LLM offline -> template · O restart persistence · P duplicate slot ·
Q concurrent jobs · R new model mid-cycle · S model removed mid-cycle · T pause · U publish-now · V skip · W token never exposed.
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
os.environ["TELEGRAM_AUTOPILOT_MOCK"] = "true"

from telegram_autopilot import client as tg, engine, eligibility, copy as tgcopy  # noqa: E402
from database import models_col  # noqa: E402
from _creds import admin_credentials  # noqa: E402

pytestmark = pytest.mark.anyio
BASE = os.environ.get("TEST_BACKEND", "http://localhost:8001")
TAG = f"tg-{uuid.uuid4().hex[:6]}"
TOKEN_VALUE = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _model(slug, of="https://onlyfans.com/x", photos=2, videos=1, stato="pubblicata", ordine=0):
    pairs = []
    for i in range(max(photos, videos)):
        if i < photos:
            pairs.append({"id": f"{slug}-p{i}", "tipo": "image", "pubblico": {"tipo": "image", "url": f"https://cdn.test/{slug}/p{i}.jpg"}, "segreto": {"tipo": "image", "url": f"https://cdn.test/{slug}/SECRET{i}.jpg"}})
        if i < videos:
            pairs.append({"id": f"{slug}-v{i}", "tipo": "video", "pubblico": {"tipo": "video", "url": f"https://cdn.test/{slug}/v{i}.mp4"}, "segreto": {"tipo": "video", "url": f"https://cdn.test/{slug}/SECRETv{i}.mp4"}})
    return {"id": str(uuid.uuid4()), "slug": slug, "nome": slug.split("-")[-1].capitalize(), "nome_artistico": f"{slug.split('-')[-1].capitalize()} Test", "frase": "Dolce finché non premi.", "bio": "bio test", "categorie": ["eleganti"], "tag": ["raffinata"],
            "onlyfans_url": of, "media_pairs": pairs, "galleria_pubblica": [], "galleria_segreta": [{"tipo": "image", "url": f"https://cdn.test/{slug}/GALSECRET.jpg"}], "stato": stato, "is_deleted": False, "ordine": ordine, "created_at": "2026-01-01", "_test_tag": TAG}


@pytest.fixture
async def sandbox():
    """Isolated DB world: hide real models (mark them non-published via a temp flag is invasive) -> instead we use a dedicated
    set of test models with `ordine` far below real ones and reset engine state before/after."""
    mock = tg.MockTelegram()
    tg.force_client(mock)
    await engine.ensure_indexes()
    saved_state = await engine.state_col.find_one({"id": "global"}, {"_id": 0})
    await engine.state_col.delete_one({"id": "global"})
    await engine.ensure_indexes()
    # test-only eligibility: monkeypatch published_models to return only our test docs
    orig = eligibility.published_models

    async def only_test():
        items = [m async for m in models_col.find({"_test_tag": TAG, "stato": "pubblicata", "is_deleted": {"$ne": True}}, eligibility.PUBLIC_FIELDS | {"_test_tag": 1})]
        items.sort(key=eligibility._order_key)
        return items
    eligibility.published_models = only_test
    engine.roster.__globals__["published_models"] = only_test
    yield mock
    eligibility.published_models = orig
    engine.roster.__globals__["published_models"] = orig
    tg.force_client(None)
    test_ids = [m["id"] async for m in models_col.find({"_test_tag": TAG}, {"id": 1})]
    await models_col.delete_many({"_test_tag": TAG})
    await engine.media_state_col.delete_many({"model_id": {"$in": test_ids}})
    await engine.log_col.delete_many({"model_slug": {"$regex": f"^{TAG}"}})
    await engine.slots_col.delete_many({"slot_id": {"$regex": f"^{TAG}"}})
    await engine.state_col.delete_one({"id": "global"})
    if saved_state:
        await engine.state_col.insert_one(saved_state)
    else:
        await engine.ensure_indexes()


async def seed(*models):
    await models_col.insert_many([dict(m) for m in models])
    return models


# ------------------------------------------------------------------ A/B/C connection, admin, permissions (mock states) + real read-only check
async def test_connection_states(sandbox):
    mock = sandbox
    c = await tg.connection_status()
    assert c["TELEGRAM_CONNECTION_STATUS"] == "CONNECTED" and c["bot_is_admin"] and c["can_post"]
    mock.member_status = "member"
    assert (await tg.connection_status())["TELEGRAM_CONNECTION_STATUS"] == "BOT_NOT_ADMIN"
    mock.member_status, mock.can_post = "administrator", False
    assert (await tg.connection_status())["TELEGRAM_CONNECTION_STATUS"] == "MISSING_PERMISSION"
    mock.can_post = True
    mock.fail_all = "INVALID_TOKEN"
    assert (await tg.connection_status())["TELEGRAM_CONNECTION_STATUS"] == "INVALID_TOKEN"
    mock.fail_all = "CHANNEL_NOT_FOUND"
    assert (await tg.connection_status())["TELEGRAM_CONNECTION_STATUS"] == "CHANNEL_NOT_FOUND"
    mock.fail_all = None


@pytest.mark.skipif(not TOKEN_VALUE, reason="no token configured")
async def test_real_connection_check_is_read_only():
    """Uses the real API but only getMe/getChat/getChatMember (no message)."""
    c = await tg.connection_status(check_real=True)
    assert c["TELEGRAM_CONNECTION_STATUS"] in ("CONNECTED", "BOT_NOT_ADMIN", "MISSING_PERMISSION", "API_ERROR", "CHANNEL_NOT_FOUND")
    assert TOKEN_VALUE not in json.dumps(c)


def test_classify_errors_and_scrub():
    assert tg._classify(401, "Unauthorized") == "INVALID_TOKEN"
    assert tg._classify(400, "Bad Request: chat not found") == "CHANNEL_NOT_FOUND"
    assert tg._classify(400, "Bad Request: not enough rights to send photos") == "MISSING_PERMISSION"
    assert tg._classify(400, "Bad Request: failed to get HTTP URL content") == "MEDIA_REJECTED"
    if TOKEN_VALUE:
        e = tg.TelegramError("API_ERROR", f"https://api.telegram.org/bot{TOKEN_VALUE}/sendPhoto failed")
        assert TOKEN_VALUE not in str(e) and TOKEN_VALUE not in e.description


# ------------------------------------------------------------------ eligibility: OF link, public-only media, alternation
def test_of_link_validation_and_public_media():
    assert eligibility.valid_of_link("https://onlyfans.com/vanessa") == "https://onlyfans.com/vanessa"
    assert eligibility.valid_of_link("onlyfans.com/vanessa") == "https://onlyfans.com/vanessa"
    assert eligibility.valid_of_link("https://www.onlyfans.com/v/") is not None
    for bad in ("https://instagram.com/vanessa", "https://t.me/vanessa", "https://onlyfans.com.evil.com/x", "https://onlyfans.com/", "", None, "https://tiktok.com/@v"):
        assert eligibility.valid_of_link(bad) is None, bad
    m = _model("t-alt", photos=3, videos=2)
    media = eligibility.public_media(m)
    assert [x["type"] for x in media] == ["photo", "video", "photo", "video", "photo"]
    assert all("SECRET" not in x["url"] for x in media), "secret media must never be used"
    only_photos = eligibility.public_media(_model("t-ph", photos=2, videos=0))
    assert [x["type"] for x in only_photos] == ["photo", "photo"]


# ------------------------------------------------------------------ D/E/F/G/H photo, video, caption, OF link, two consecutive
async def test_photo_video_caption_link_two_consecutive(sandbox):
    mock = sandbox
    await seed(_model(f"{TAG}-anna", photos=2, videos=1, ordine=1), _model(f"{TAG}-bea", photos=1, videos=1, ordine=2, of="https://onlyfans.com/bea_real"))
    await engine.set_state(use_ai_copy=False)
    r1 = await engine.publish_next("test")
    assert r1["status"] == "PUBLISHED" and r1["model_slug"] == f"{TAG}-anna" and r1["media_type"] == "photo" and r1["message_id"]
    r2 = await engine.publish_next("test")
    assert r2["status"] == "PUBLISHED" and r2["model_slug"] == f"{TAG}-bea"
    sent = mock.sent[-1]
    assert sent["kind"] == "photo" and "https://onlyfans.com/bea_real" in sent["caption"] and sent["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://onlyfans.com/bea_real"
    assert "Bea" in sent["caption"] and "<b>" in sent["caption"] and len(sent["caption"]) <= tg.CAPTION_LIMIT
    assert any(cta in sent["caption"] for cta in tgcopy.CTAS)
    # media cursor: Anna's second post uses the VIDEO (alternation), then photo 2
    await engine.set_state(cycle_done=[], last_position=-1)
    r3 = await engine.publish_next("test")
    assert r3["model_slug"] == f"{TAG}-anna" and r3["media_type"] == "video" and mock.sent[-1]["kind"] == "video"
    st = await engine.media_state_col.find_one({"model_id": r3["model_id"]}, {"_id": 0})
    assert st["last_media_id"] == r3["media_id"] and len(st["used_media_ids"]) == 2


# ------------------------------------------------------------------ I/J full rotation, wrap to first, no repeats within a cycle
async def test_circular_rotation_no_repeat_and_wrap(sandbox):
    await seed(*[_model(f"{TAG}-m{i}", ordine=i) for i in range(5)])
    await engine.set_state(use_ai_copy=False)
    seq = []
    for _ in range(12):
        r = await engine.publish_next("test")
        assert r["status"] == "PUBLISHED"
        seq.append((r["model_slug"], r["cycle_number"]))
    c1 = [s for s, c in seq if c == 1]
    c2 = [s for s, c in seq if c == 2]
    assert c1 == [f"{TAG}-m{i}" for i in range(5)], "cycle 1: every model once, in order"
    assert c2 == [f"{TAG}-m{i}" for i in range(5)], "cycle 2 restarts from the first"
    assert [s for s, c in seq if c == 3] == [f"{TAG}-m0", f"{TAG}-m1"]
    st = await engine.get_state()
    assert st["cycle_number"] == 3 and len(st["cycle_done"]) == 2


# ------------------------------------------------------------------ K/L no OF, no media, M video fail -> photo fallback, all fail -> SKIPPED_NO_MEDIA
async def test_skips_and_media_fallback(sandbox):
    mock = sandbox
    await seed(_model(f"{TAG}-noof", of="https://instagram.com/x", ordine=1), _model(f"{TAG}-nomedia", photos=0, videos=0, ordine=2),
               _model(f"{TAG}-vidfail", photos=1, videos=1, ordine=3), _model(f"{TAG}-allfail", photos=1, videos=1, ordine=4), _model(f"{TAG}-ok", ordine=5))
    await engine.set_state(use_ai_copy=False)
    q = await engine.queue_view()
    assert q["roster"]["no_of"] == [f"{TAG}-noof"] and q["roster"]["no_media"] == [f"{TAG}-nomedia"] and q["n_eligible"] == 3
    # vidfail: make its video fail and put the cursor so that the video comes first
    await engine.media_state_col.update_one({"model_id": q["eligible"][0]["model_id"]}, {"$set": {"model_id": q["eligible"][0]["model_id"], "last_media_id": f"{TAG}-vidfail-p0", "media_index": 0}}, upsert=True)
    mock.fail_media.add(f"{TAG}-vidfail/v0.mp4")
    r = await engine.publish_next("test")
    assert r["status"] == "PUBLISHED" and r["model_slug"] == f"{TAG}-vidfail" and r["media_type"] == "photo" and r["media_errors"][0]["error_code"] == "MEDIA_REJECTED"
    # allfail: every media rejected -> SKIPPED_NO_MEDIA logged, rotation continues to 'ok' in the same call
    mock.fail_media.update({f"{TAG}-allfail/p0.jpg", f"{TAG}-allfail/v0.mp4"})
    r = await engine.publish_next("test")
    assert r["status"] == "PUBLISHED" and r["model_slug"] == f"{TAG}-ok"
    assert await engine.log_col.find_one({"status": "SKIPPED_NO_MEDIA", "model_slug": f"{TAG}-allfail"})
    assert await engine.log_col.find_one({"status": "PUBLISHED", "model_slug": f"{TAG}-ok"})
    # no infinite loop: with everything failing, one call returns FAILED
    mock.fail_media.update({f"{TAG}-vidfail/", f"{TAG}-ok/"})
    await engine.set_state(cycle_done=[], last_position=-1)
    r = await engine.publish_next("test")
    assert r["status"] == "FAILED" and r["error_code"] == "NO_PUBLISHABLE_MODEL"


# ------------------------------------------------------------------ N LLM offline -> template (never fails)
async def test_llm_offline_template_fallback(monkeypatch):
    monkeypatch.setenv("TELEGRAM_LLM_ENABLED", "false")
    m = _model("vanessa-neri", of="https://onlyfans.com/vanessa")
    m["nome_artistico"], m["nome"] = "Vanessa Neri", "Vanessa"
    cap = await tgcopy.build_caption(m, 2, "https://onlyfans.com/vanessa", use_ai=True)
    assert cap["source"] == "TEMPLATE" and "Vanessa" in cap["text"] and cap["caption"].endswith("https://onlyfans.com/vanessa")
    monkeypatch.setenv("TELEGRAM_LLM_ENABLED", "true")

    async def boom(*a, **k):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(tgcopy, "llm_copy", boom)
    with pytest.raises(RuntimeError):
        await tgcopy.llm_copy(m, 1)
    # build_caption guards through llm_copy's own try/except normally; simulate None return
    monkeypatch.setattr(tgcopy, "llm_copy", lambda *a, **k: asyncio.sleep(0, result=None))
    cap2 = await tgcopy.build_caption(m, 3, "https://onlyfans.com/vanessa", use_ai=True)
    assert cap2["source"] == "TEMPLATE"
    # templates differ across cycles and creators
    assert tgcopy.template_copy(m, 1) != tgcopy.template_copy(m, 2)
    assert tgcopy.template_copy(m, 1) != tgcopy.template_copy(_model("aurora-villa"), 1)
    # caption limit respected
    m["bio"] = "x" * 3000
    monkeypatch.setattr(tgcopy, "template_copy", lambda mm, c: "y" * 2000)
    cap3 = await tgcopy.build_caption(m, 1, "https://onlyfans.com/vanessa", use_ai=False)
    assert len(cap3["caption"]) <= tg.CAPTION_LIMIT and cap3["caption"].endswith("https://onlyfans.com/vanessa")


# ------------------------------------------------------------------ O restart persistence (state is only in DB)
async def test_restart_persistence(sandbox):
    await seed(*[_model(f"{TAG}-r{i}", ordine=i) for i in range(3)])
    await engine.set_state(use_ai_copy=False)
    await engine.publish_next("test")
    await engine.publish_next("test")
    before = await engine.get_state()
    # "restart": drop every in-memory reference; re-read from DB
    import importlib
    importlib.reload(engine)
    tg.force_client(sandbox)
    after = await engine.get_state()
    assert after["cycle_done"] == before["cycle_done"] and after["last_position"] == before["last_position"] and after["cycle_number"] == before["cycle_number"]
    r = await engine.publish_next("test")
    assert r["model_slug"] == f"{TAG}-r2", "continues from the third model, does not restart from the first"


# ------------------------------------------------------------------ P duplicate slot, Q concurrent jobs
async def test_duplicate_slot_and_concurrency(sandbox):
    await seed(*[_model(f"{TAG}-d{i}", ordine=i) for i in range(4)])
    await engine.set_state(use_ai_copy=False)
    slot = f"{TAG}_2026-09-19_10:00"
    r1 = await engine.publish_next("scheduler", slot_id=slot)
    assert r1["status"] == "PUBLISHED"
    r2 = await engine.publish_next("scheduler", slot_id=slot)
    assert r2["status"] == "SKIP_DUPLICATE_SLOT"
    assert await engine.log_col.find_one({"status": "SKIP_DUPLICATE_SLOT", "slot_id": slot})
    # Q: 5 concurrent publishers on a NEW slot -> exactly one publishes, others LOCKED or SKIP_DUPLICATE_SLOT
    slot2 = f"{TAG}_2026-09-19_14:00"
    n_before = await engine.log_col.count_documents({"status": "PUBLISHED", "model_slug": {"$regex": f"^{TAG}-d"}})
    results = await asyncio.gather(*(engine.publish_next("scheduler", slot_id=slot2) for _ in range(5)))
    statuses = sorted(r["status"] for r in results)
    assert statuses.count("PUBLISHED") == 1 and all(s in ("PUBLISHED", "LOCKED", "SKIP_DUPLICATE_SLOT") for s in statuses), statuses
    assert await engine.log_col.count_documents({"status": "PUBLISHED", "model_slug": {"$regex": f"^{TAG}-d"}}) == n_before + 1


# ------------------------------------------------------------------ R new model mid-cycle, S model removed mid-cycle
async def test_new_and_removed_models_mid_cycle(sandbox):
    a, b, c = await seed(_model(f"{TAG}-a", ordine=1), _model(f"{TAG}-b", ordine=2), _model(f"{TAG}-c", ordine=3))
    await engine.set_state(use_ai_copy=False)
    assert (await engine.publish_next("test"))["model_slug"] == f"{TAG}-a"
    assert (await engine.publish_next("test"))["model_slug"] == f"{TAG}-b"
    # R: new published model appears mid-cycle -> published before the cycle closes, cycle not reset
    await seed(_model(f"{TAG}-new", ordine=9))
    got = {(await engine.publish_next("test"))["model_slug"] for _ in range(2)}
    assert got == {f"{TAG}-c", f"{TAG}-new"}
    assert (await engine.get_state())["cycle_number"] == 2
    # S: model set to DRAFT mid-cycle -> skipped automatically; losing OF link -> skipped
    await models_col.update_one({"id": b["id"]}, {"$set": {"stato": "bozza"}})
    await models_col.update_one({"id": c["id"]}, {"$set": {"onlyfans_url": "https://instagram.com/c"}})
    seq = [(await engine.publish_next("test"))["model_slug"] for _ in range(2)]
    assert seq == [f"{TAG}-a", f"{TAG}-new"]
    q = await engine.queue_view()
    assert q["roster"]["no_of"] == [f"{TAG}-c"] and q["n_eligible"] == 2


# ------------------------------------------------------------------ T pause (tick does nothing), U publish-now pipeline == scheduler, V skip
async def test_pause_publish_now_skip(sandbox, monkeypatch):
    await seed(_model(f"{TAG}-x", ordine=1), _model(f"{TAG}-y", ordine=2))
    await engine.set_state(use_ai_copy=False, enabled=False)
    monkeypatch.setenv("TELEGRAM_AUTO_SCHEDULER_ENABLED", "true")
    assert (await engine.tick())["status"] == "PAUSED"
    monkeypatch.setenv("TELEGRAM_AUTO_SCHEDULER_ENABLED", "false")
    await engine.set_state(enabled=True)
    assert (await engine.tick())["status"] == "AUTO_SCHEDULER_DISABLED", "master switch off -> scheduler never publishes"
    # V skip
    r = await engine.skip_current("test")
    assert r["status"] == "MANUAL_SKIP" and r["skipped"] == f"{TAG}-x"
    assert await engine.log_col.find_one({"status": "MANUAL_SKIP", "model_slug": f"{TAG}-x"})
    # U publish-now = same pipeline (publish_next with trigger admin) -> next is y
    r = await engine.publish_next("admin")
    assert r["status"] == "PUBLISHED" and r["model_slug"] == f"{TAG}-y"
    # cycle closed (x skipped counts as processed) -> wraps
    st = await engine.get_state()
    assert st["cycle_number"] == 2 and st["cycle_done"] == []
    # schedule view + due slot logic
    sch = await engine.schedule_view()
    assert sch["posts_per_day"] == 4 and len(sch["today_slots"]) == 4 and sch["timezone"] == "Europe/Rome"


# ------------------------------------------------------------------ W token never exposed (API + frontend bundle + logs)
def _token():
    r = requests.post(f"{BASE}/api/admin/login", json=admin_credentials(), timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def test_admin_api_auth_and_no_token_exposure():
    assert requests.get(f"{BASE}/api/admin/telegram-autopilot/status", timeout=15).status_code in (401, 403)
    for ep in ("start", "pause", "publish-now", "skip", "test-connection"):
        assert requests.post(f"{BASE}/api/admin/telegram-autopilot/{ep}", timeout=15).status_code in (401, 403), ep
    h = {"Authorization": f"Bearer {_token()}"}
    bodies = []
    for ep in ("status", "logs"):
        r = requests.get(f"{BASE}/api/admin/telegram-autopilot/{ep}", headers=h, timeout=30)
        assert r.status_code == 200, ep
        bodies.append(r.text)
    r = requests.post(f"{BASE}/api/admin/telegram-autopilot/test-connection", headers=h, timeout=30)
    assert r.status_code == 200 and r.json()["TELEGRAM_CONNECTION_STATUS"] in ("CONNECTED", "INVALID_TOKEN", "CHANNEL_NOT_FOUND", "BOT_NOT_ADMIN", "MISSING_PERMISSION", "API_ERROR")
    bodies.append(r.text)
    r = requests.post(f"{BASE}/api/admin/telegram-autopilot/publish-now?dry_run=true", headers=h, timeout=60)
    assert r.status_code == 200 and r.json()["status"] == "DRY_RUN" and "onlyfans.com" in r.json()["caption"]
    bodies.append(r.text)
    s = requests.get(f"{BASE}/api/admin/telegram-autopilot/status", headers=h, timeout=30).json()
    assert s["AUTO_SCHEDULER_ENABLED"] is False and s["mock"] is True and s["channel"] == "@latosegreto"
    assert s["queue"]["total"] >= 1 and s["settings"]["schedule_times"] == ["10:00", "14:00", "18:00", "22:00"]
    if TOKEN_VALUE:
        for b in bodies:
            assert TOKEN_VALUE not in b and TOKEN_VALUE.split(":")[1] not in b
        # frontend bundle / source must not contain the token
        import subprocess
        out = subprocess.run(["grep", "-rl", TOKEN_VALUE, "/app/frontend/src", "/app/backend/telegram_autopilot", "/app/tests"], capture_output=True, text=True).stdout
        assert out.strip() == "", f"token found in: {out}"


def test_settings_validation():
    h = {"Authorization": f"Bearer {_token()}"}
    r = requests.patch(f"{BASE}/api/admin/telegram-autopilot/settings", headers=h, json={"schedule_times": ["25:00"]}, timeout=15)
    assert r.status_code == 422
    r = requests.patch(f"{BASE}/api/admin/telegram-autopilot/settings", headers=h, json={"timezone": "Mars/Olympus"}, timeout=15)
    assert r.status_code == 422
    r = requests.patch(f"{BASE}/api/admin/telegram-autopilot/settings", headers=h, json={"posts_per_day": 9}, timeout=15)
    assert r.status_code == 422
    r = requests.patch(f"{BASE}/api/admin/telegram-autopilot/settings", headers=h, json={"use_video": True, "timezone": "Europe/Rome"}, timeout=15)
    assert r.status_code == 200 and r.json()["timezone"] == "Europe/Rome"


def test_job_registered():
    from v1_jobs import JOBS
    import telegram_autopilot.jobs  # noqa: F401
    assert "telegram_autopilot_tick" in JOBS and JOBS["telegram_autopilot_tick"]["interval_s"] == 300


@pytest.mark.skipif(not TOKEN_VALUE, reason="no token configured")
def test_logging_redacts_token():
    """httpx logs the request URL (…/bot<token>/method): the redaction filter must scrub it in msg and args."""
    import io
    import logging
    lg = logging.getLogger("httpx")
    lg.setLevel(logging.INFO)
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    lg.addHandler(h)
    try:
        lg.info('HTTP Request: POST https://api.telegram.org/bot%s/getMe "HTTP/1.1 200 OK"', TOKEN_VALUE)
        lg.info(f"HTTP Request: POST https://api.telegram.org/bot{TOKEN_VALUE}/getChat")
    finally:
        lg.removeHandler(h)
    out = buf.getvalue()
    assert TOKEN_VALUE not in out and "***TOKEN***" in out
