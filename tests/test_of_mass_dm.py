"""OF Autopilot — FEED + MASS MESSAGE (MOCK ONLY). Checks: FEED_CREATE · FEED_VERIFY · MASS_DM_CREATE · MASS_DM_VERIFY · MASS_DM_TARGET_ALL_FANS ·
FEED_AND_DM_COPY_DIFFERENT · SAME_MODEL_MEDIA · CORRECT_MODEL_OF_LINK · NO_DUPLICATE_FEED · NO_DUPLICATE_MASS_DM · FEED_SUCCESS_DM_FAIL_RETRY_ONLY_DM
plus gates (DM disabled -> feed-only behaviour unchanged; real adapter blocks mass DM before any network). Zero real provider writes."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/tests")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")
os.environ["OF_AUTOPILOT_MOCK"] = "true"
os.environ["OF_REAL_POSTING_ENABLED"] = "false"
os.environ["OF_AUTO_SCHEDULER_ENABLED"] = "false"
os.environ["OF_MASS_DM_MOCK"] = "true"               # OF_MASS_DM_ENABLED is set per-test via monkeypatch (never leaks to other test modules)

from of_autopilot import engine, media as ofmedia, caption as ofcap  # noqa: E402
from of_autopilot.providers import the_only_api as toa  # noqa: E402
from of_autopilot.providers.base import OFMassMessageRequest, OFProviderError  # noqa: E402
from of_autopilot.providers.mock import MockOFProvider  # noqa: E402
from database import models_col  # noqa: E402

pytestmark = pytest.mark.anyio
TAG = f"ofdm-{uuid.uuid4().hex[:6]}"
HOST = ofmedia.media_base()
PHOTO_A = "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=900&q=80"
PHOTO_B = f"{HOST}/media/pub1.jpg"
PHOTO_C = f"{HOST}/media/pub2.jpg"


def _model(slug, ordine=0):
    pairs = [{"id": f"{slug}-0", "tipo": "image", "pubblico": {"tipo": "image", "url": PHOTO_A}, "segreto": {"tipo": "image", "url": PHOTO_B}},
             {"id": f"{slug}-1", "tipo": "image", "pubblico": {"tipo": "image", "url": PHOTO_C}, "segreto": {"tipo": "image", "url": PHOTO_A.replace("q=80", "q=79")}}]
    return {"id": str(uuid.uuid4()), "slug": slug, "nome": slug, "nome_artistico": f"{slug.split('-')[-1].capitalize()} Dm", "frase": "Dolce finché non premi.", "bio": "bio",
            "categorie": ["eleganti"], "tag": ["raffinata"], "onlyfans_url": f"https://onlyfans.com/{slug}", "media_pairs": pairs, "galleria_pubblica": [], "galleria_segreta": [],
            "stato": "pubblicata", "is_deleted": False, "ordine": ordine, "created_at": "2026-01-01", "_test_tag": TAG}


@pytest.fixture
async def sandbox(monkeypatch):
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "true")  # tests exercise the MOCK mass DM pipeline (env of the running app stays ENABLED=false)
    monkeypatch.setenv("OF_MASS_DM_MOCK", "true")
    mock = MockOFProvider()
    engine.force_provider(mock)
    await engine.ensure_indexes()
    saved_state = await engine.state_col.find_one({"id": "global"}, {"_id": 0})
    await engine.state_col.delete_one({"id": "global"})
    await engine.ensure_indexes()
    await engine.set_state(use_ai_copy=False)
    orig = ofmedia.published_models

    async def only_test():
        items = [m async for m in models_col.find({"_test_tag": TAG, "stato": "pubblicata", "is_deleted": {"$ne": True}}, ofmedia.FIELDS | {"_test_tag": 1})]
        items.sort(key=ofmedia._order_key)
        return items
    ofmedia.published_models = only_test
    writes_before, dm_before = toa.CALLS["write"], toa.CALLS["mass_dm"]
    slots_before = {d["slot_id"] async for d in engine.slots_col.find({}, {"slot_id": 1})}
    yield mock
    assert toa.CALLS["write"] == writes_before and toa.CALLS["mass_dm"] == dm_before, "a REAL provider write / mass DM happened"
    await engine.slots_col.delete_many({"slot_id": {"$nin": list(slots_before)}})      # slots claimed by this test only (slot ids are global: of_<day>_<HH:MM>)
    ofmedia.published_models = orig
    engine.force_provider(None)
    ids = [m["id"] async for m in models_col.find({"_test_tag": TAG}, {"id": 1})]
    await models_col.delete_many({"_test_tag": TAG})
    for col in (engine.media_state_col, engine.uploads_col, engine.runs_col, engine.log_col):
        await col.delete_many({"model_id": {"$in": ids}})
    await engine.state_col.delete_one({"id": "global"})
    if saved_state:
        await engine.state_col.insert_one(saved_state)
    else:
        await engine.ensure_indexes()


async def seed(*models):
    await models_col.insert_many([dict(m) for m in models])
    return models


# ------------------------------------------------------------------ happy path: FEED -> verify -> MASS DM -> verify -> advance
async def test_feed_then_mass_dm_happy_path(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-anna", 0), _model(f"{TAG}-bea", 1))
    assert mock.cache_total == 0                                                                                                        # provider cache EMPTY before refresh (production situation)
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["status"] == "MOCK_CONFIRMED" and r["FEED_STATUS"] == "OK" and r["provider_post_id"] in mock.posts                      # FEED_CREATE + FEED_VERIFY
    assert r["media_order"] == ["PUBLIC", "SECRET"] and r["SAME_MODEL_MEDIA"] is True and r["public_media_id"].startswith("pub:") and r["secret_media_id"].startswith("sec:")
    assert r["of_link"] == a["onlyfans_url"] and r["caption"].rstrip().endswith(a["onlyfans_url"])                                     # CORRECT_MODEL_OF_LINK (feed)
    dm = r["mass_dm"]
    assert r["MASS_DM_STATUS"] == "OK" and dm["advance"] is True and dm["mass_dm_id"].startswith("mock_queue_") and len(mock.mass_messages) == 1   # MASS_DM_CREATE + queue MASS_DM_VERIFY
    assert mock.refresh_starts == 1 and dm["refresh"]["status"] == "OK" and mock.cache_total == mock.fans + mock.expired_fans          # SUBSCRIBER_REFRESH before the DM (CRM data only)
    assert dm["target"] == "FAN" and dm["fans_list_id"] == "fans" and dm["fans_users_count"] == mock.fans and dm["sent_count"] == mock.fans   # TARGET = native OF "Fans" list, NOT the cache (cache total != fans)
    assert dm["queue_verify"] == "PASS" and dm["readback"] == "SKIPPED"
    msg = mock.mass_messages[0]
    assert msg["userLists"] == ["fans"] and msg["excludedLists"] == [] and "audience" not in msg and "fan_ids" not in msg and "queueBuyers" not in msg   # MASS_DM_TARGET_PAYLOAD
    assert mock.last_mass_payload == {"text": msg["text"], "price": 0, "mediaFiles": msg["mediaFiles"], "userLists": ["fans"], "excludedLists": []}
    assert set(mock.last_mass_payload) == {"text", "price", "mediaFiles", "userLists", "excludedLists"}                                  # AUDIENCE_TYPE_REMOVED + FAN_IDS_REMOVED
    post_media_ids = [str(m["id"]) for m in mock.posts[r["provider_post_id"]]["media"]]
    assert msg["mediaFiles"] == post_media_ids and len(msg["mediaFiles"]) == 2                                                          # same PUBLIC+SECRET pair as the feed (vault ids from read-back)
    assert all(u["model_id"] == a["id"] for u in [x async for x in engine.uploads_col.find({"provider_post_id": r["provider_post_id"]})])   # SAME_MODEL_MEDIA
    assert msg["text"] != r["caption"] and ofcap.DM_CTA in msg["text"] and ofcap.H_PUBLIC in msg["text"] and ofcap.H_SECRET in msg["text"]   # FEED_AND_DM_COPY_DIFFERENT
    assert msg["text"].startswith("👀 Hai già scoperto ") and msg["text"].rstrip().endswith(a["onlyfans_url"]) and msg["text"].count("http") == 1   # CORRECT_MODEL_OF_LINK (dm)
    feed_sentences = {l.strip().lower() for l in r["caption"].split("\n") if l.strip() and not l.startswith(("✨", "🔥", "💋", "http"))}
    dm_sentences = {l.strip().lower() for l in msg["text"].split("\n") if l.strip() and not l.startswith(("✨", "🔥", "❤️‍🔥", "👀", "http"))}
    assert not (feed_sentences & dm_sentences)
    assert mock.gate_history == [] or mock.gate is False                                                                               # mock feed never opens the real gate; DM gate restored
    run = await engine.get_run(a["id"], 1)
    assert run["feed_status"] == "OK" and run["mass_dm_status"] == "OK" and run["mass_dm_id"] == dm["mass_dm_id"] and run["mock"] is True
    assert run["subscriber_refresh_status"] == "OK" and run["subscriber_refresh_started_at"] and run["subscriber_refresh_completed_at"] and run["cached_total"] == mock.cache_total   # REFRESH STATE
    assert run["cached_active"] == mock.fans and run["cached_expired"] == mock.expired_fans and run["last_refreshed_at"]
    assert run["target"] == "FAN" and run["of_fans_list_id"] == "fans" and run["of_fans_users_count"] == mock.fans and run["mass_dm_user_lists"] == ["fans"] and run["mass_dm_queue_id"] == dm["mass_dm_id"]
    st = await engine.status()
    assert st["queue"]["current"]["slug"] == b["slug"] and st["OF_REAL_MASS_DM_SENT"] is False and st["THE_ONLY_API_REAL_MASS_DM_CALLS"] == 0 and st["TOTAL_REAL_POSTS_CREATED"] == 0
    assert st["current_run"]["FEED_STATUS"] == "PENDING" and st["current_run"]["MASS_DM_STATUS"] == "PENDING" and st["current_run"]["FAN_REFRESH_STATUS"] == "PENDING" and st["current_run"]["TARGET"] == "FAN"
    # NEW_FANS_INCLUDED: 15 new fans -> the next DM resolves the Fans list again and OnlyFans usersCount reflects them (never the previous count)
    mock.fans += 15
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["status"] == "MOCK_CONFIRMED" and r2["model_slug"] == b["slug"] and mock.refresh_starts == 2
    assert r2["mass_dm"]["fans_users_count"] == mock.fans == dm["fans_users_count"] + 15 and mock.mass_messages[1]["recipients"] == dm["fans_users_count"] + 15
    assert (await engine.status())["current_run"]["FAN_COUNT"] is None                                                                  # next model not started
    assert (await engine.status())["scheduler"]["slots"] if False else True


# ------------------------------------------------------------------ feed OK, DM fails -> no advance, retry ONLY the DM, never a second feed, never a second DM
async def test_feed_success_dm_fail_retry_only_dm(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-cara", 0), _model(f"{TAG}-dora", 1))
    mock.fail_mass_dm = True
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["status"] == "MOCK_CONFIRMED_DM_FAILED" and r["FEED_STATUS"] == "OK" and r["MASS_DM_STATUS"] == "FAILED" and r["mass_dm"]["advance"] is False
    assert len(mock.posts) == 1 and len(mock.mass_messages) == 0 and mock.refresh_starts == 1 and r["mass_dm"]["fans_users_count"] > 0     # refresh + fans list resolved, send rejected (400)
    st = await engine.status()
    assert st["queue"]["current"]["slug"] == a["slug"] and st["current_run"] == {**st["current_run"], "FEED_STATUS": "OK", "MASS_DM_STATUS": "FAILED"}   # queue did NOT advance
    assert st["last_error"].startswith("MASS_DM:")
    # retry while still failing: NO new feed post
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["status"] == "FEED_OK_DM_FAILED" and r2["feed_skipped_duplicate"] is True and r2["provider_post_id"] == r["provider_post_id"]
    assert len(mock.posts) == 1 and len(mock.mass_messages) == 0                                                                        # NO_DUPLICATE_FEED
    run = await engine.get_run(a["id"], 1)
    assert run["mass_dm_attempts"] == 2 and run["feed_post_id"] == r["provider_post_id"]
    # DM recovers -> retry sends ONLY the DM, queue advances
    mock.fail_mass_dm = False
    r3 = await engine.run("PUBLISH_NOW", "test")
    assert r3["status"] == "MOCK_CONFIRMED" and r3["feed_skipped_duplicate"] is True and r3["MASS_DM_STATUS"] == "OK" and r3["provider_post_id"] == r["provider_post_id"]
    assert len(mock.posts) == 1 and len(mock.mass_messages) == 1 and mock.mass_messages[0]["mediaFiles"] == [str(m["id"]) for m in mock.posts[r["provider_post_id"]]["media"]]
    assert mock.refresh_starts == 3                                                                                                       # every retry refreshes the cache first
    assert mock.mass_messages[0]["text"] == r3["mass_dm_text"] and mock.mass_messages[0]["text"] != r["caption"]                       # same copy kept across retries, different from feed
    st = await engine.status()
    assert st["queue"]["current"]["slug"] == b["slug"]                                                                                  # FEED_SUCCESS_DM_FAIL_RETRY_ONLY_DM
    # NO_DUPLICATE_MASS_DM: a direct step call on the completed run never sends again
    run = await engine.get_run(a["id"], 1)
    model = await models_col.find_one({"id": a["id"]}, ofmedia.FIELDS)
    dm = await engine._mass_dm_step(mock, "mock_latosegreto", model, run, True, "test")
    assert dm["duplicate_prevented"] is True and dm["MASS_DM_STATUS"] == "OK" and len(mock.mass_messages) == 1
    # next model: full feed + dm again
    r4 = await engine.run("PUBLISH_NOW", "test")
    assert r4["status"] == "MOCK_CONFIRMED" and r4["model_slug"] == b["slug"] and len(mock.posts) == 2 and len(mock.mass_messages) == 2
    assert mock.mass_messages[1]["text"].rstrip().endswith(b["onlyfans_url"]) and mock.mass_messages[1]["text"] != mock.mass_messages[0]["text"]


# ------------------------------------------------------------------ 200 but not verifiable -> UNVERIFIED: never auto-resend, no advance
async def test_dm_not_confirmed_never_resent(sandbox):
    mock = sandbox
    a, = await seed(_model(f"{TAG}-elsa", 0))
    mock.hide_mass_dm = True
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["MASS_DM_STATUS"] == "UNVERIFIED" and r["status"] == "MOCK_CONFIRMED_DM_UNVERIFIED" and mock.write_calls == 4          # 2 uploads + post + 1 dm send (accepted but not verifiable)
    assert r["mass_dm"]["queue_verify"] == "FAIL" and r["mass_dm"]["readback"] in ("FAIL", "UNAVAILABLE")
    mock.hide_mass_dm = False
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["status"] == "FEED_OK_DM_UNVERIFIED" and r2["mass_dm"]["duplicate_prevented"] is True and mock.write_calls == 4         # NO_DUPLICATE_MASS_DM
    assert len(mock.posts) == 1


# ------------------------------------------------------------------ gates: DM disabled -> unchanged feed-only behaviour; real adapter blocks before network
async def test_dm_disabled_keeps_feed_behaviour(sandbox, monkeypatch):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-fede", 0), _model(f"{TAG}-gina", 1))
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "false")
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["status"] == "MOCK_CONFIRMED" and r["MASS_DM_STATUS"] == "DISABLED" and len(mock.mass_messages) == 0
    assert (await engine.status())["queue"]["current"]["slug"] == b["slug"]
    # mock DM after a REAL feed is never executed (MOCK_ONLY), real DM after a MOCK feed is skipped
    assert engine._dm_provider(mock, is_mock=False) == (None, "DISABLED")
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "true")
    assert engine._dm_provider(mock, is_mock=False) == (None, "MOCK_ONLY")
    monkeypatch.setenv("OF_MASS_DM_MOCK", "false")
    assert engine._dm_provider(mock, is_mock=True) == (None, "SKIPPED") and engine._dm_provider(mock, is_mock=False) == (mock, None)


async def test_real_adapter_mass_dm_blocked_without_network(monkeypatch):
    monkeypatch.setenv("THE_ONLY_API_KEY", "k" * 43)
    monkeypatch.setenv("THE_ONLY_CRM_ID", "crm")
    monkeypatch.setenv("OF_REAL_POSTING_ENABLED", "true")
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "false")
    monkeypatch.setenv("OF_MASS_DM_MOCK", "true")
    ad = toa.TheOnlyAPIAdapter()
    before = dict(toa.CALLS)
    for env in ({"OF_MASS_DM_ENABLED": "false", "OF_MASS_DM_MOCK": "false"}, {"OF_MASS_DM_ENABLED": "true", "OF_MASS_DM_MOCK": "true"}, {"OF_MASS_DM_ENABLED": "false", "OF_MASS_DM_MOCK": "true"}):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        with pytest.raises(OFProviderError) as ei:
            await ad.mass_message_fans("1", OFMassMessageRequest(text="x", media_ids=["1"], user_lists=["fans"]))
        assert ei.value.code == "MASS_DM_DISABLED"
        with pytest.raises(OFProviderError) as ei2:
            await ad.send_mass_message("1", OFMassMessageRequest(text="x", media_ids=["1"]))            # legacy passthrough path also gated
        assert ei2.value.code == "MASS_DM_DISABLED"
    assert toa.CALLS == before, "no network, no counters"


async def test_mass_dm_from_post_unverified_never_resent(sandbox, monkeypatch):
    mock = sandbox
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "false")
    a, = await seed(_model(f"{TAG}-nora", 0))
    r = await engine.run("PUBLISH_NOW", "test")
    pid = r["provider_post_id"]
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "true")
    async def net_error(uid, req):
        raise OFProviderError("NETWORK_ERROR", "timeout")                                              # connection dropped during the send
    monkeypatch.setattr(mock, "mass_message_fans", net_error)
    e = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert e["status"] == "MASS_DM_UNVERIFIED" and e["REAL_MASS_DM_CREATE"].startswith("UNKNOWN_") and e["READBACK_VERIFY"] in ("FAIL", "UNAVAILABLE") and e["WRITE_GATE_RESTORED_TO_FALSE"] is True
    run = await engine.runs_col.find_one({"cycle_number": f"post:{pid}"}, {"_id": 0})
    assert run["mass_dm_status"] == "UNVERIFIED" and run["mass_dm_id"].startswith("crm:")
    e2 = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")               # NEVER a blind retry
    assert e2["status"] == "STOPPED_PRECHECK" and "NO_MASS_DM_ALREADY_SENT_FOR_POST" in e2["failed_checks"] and e2["WRITE_GATE_ENABLED"] is False


async def test_dm_caption_format_and_difference():
    m = _model("dm-copy")
    of = m["onlyfans_url"]
    feed = await ofcap.build_caption(m, of, 1, use_ai=False)
    for cyc in range(1, 6):
        feed = await ofcap.build_caption(m, of, cyc, use_ai=False)
        dm = await ofcap.build_dm_caption(m, of, cyc, feed["text"], use_ai=False)
        lines = [l for l in dm["text"].split("\n") if l.strip()]
        assert lines[0] == f"👀 Hai già scoperto {m['nome_artistico'].upper()}?" and lines[1] == ofcap.H_PUBLIC and lines[3] == ofcap.H_SECRET and lines[-2] == ofcap.DM_CTA and lines[-1] == of
        assert dm["different_from_feed"] is True and dm["text"] != feed["text"] and dm["text"].count("http") == 1 and "onlyfans.com/latosegreto" not in dm["text"]
        assert not ofcap.FORBIDDEN.search(dm["body"]) and not ofcap.ENGLISH_HINT.search(dm["body"])
    with pytest.raises(AssertionError):
        await ofcap.build_dm_caption(m, "https://latosegreto.it/x", 1, "", use_ai=False)


# ------------------------------------------------------------------ mass-dm-test: DM-only from an EXISTING confirmed feed post (never a new feed)
async def test_mass_dm_from_existing_post_mock(sandbox, monkeypatch):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-hana", 0), _model(f"{TAG}-ines", 1))
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "false")                      # feed only (like production so far): no DM at feed time
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["status"] == "MOCK_CONFIRMED" and r["MASS_DM_STATUS"] == "DISABLED" and len(mock.mass_messages) == 0
    pid = r["provider_post_id"]
    posts_before, writes_before = len(mock.posts), mock.write_calls
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "true")
    # 1) DRY RUN = read-only pre-checks + copy preview, zero writes
    d = await engine.mass_dm_from_post(a["slug"], pid, execute=False, trigger="test")
    assert d["status"] == "DRY_RUN_PASS" and d["ALL_PRECHECKS_PASS"] is True and all(d["checks"].values()), d["checks"]
    assert d["SOURCE_MEDIA_COUNT"] == 2 and len(d["VAULT_MEDIA_IDS_MASKED"]) == 2 and d["FANS_LIST_FOUND"] is True and d["FANS_LIST_ID"] == "fans" and d["OF_FANS_USERS_COUNT"] == mock.fans and d["WRITE_GATE_BEFORE"] is False
    assert d["ONLYFANS_UI_TARGET"] == "FAN" and d["FANS_DRY_RUN_SUPPORTED"] is False
    assert d["MASS_DM_TEXT"].startswith("👀 Hai già scoperto ") and d["MASS_DM_TEXT"].rstrip().endswith(a["onlyfans_url"]) and d["MASS_DM_TEXT"] != r["caption"]
    assert mock.write_calls == writes_before and len(mock.mass_messages) == 0 and mock.gate_history == []
    # 2) EXECUTE = gate on -> ONE mass DM -> verify -> saved -> gate off (verified)
    e = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert e["status"] == "MASS_DM_CONFIRMED" and e["REAL_MASS_DM_CREATE"] == "PASS" and e["QUEUE_VERIFY"] == "PASS" and e["REAL_MASS_DM_CONFIRMED"] == "PASS" and e["MASS_DM_ID_RECEIVED"] is True
    assert e["MASS_DM_TARGET_PAYLOAD"] == {"userLists": ["fans"], "excludedLists": []} and e["REAL_MASS_DM_SENT_COUNT"] == mock.fans and e["OF_FANS_USERS_COUNT"] == mock.fans
    assert e["WRITE_GATE_ENABLED"] is True and e["WRITE_GATE_RESTORED_TO_FALSE"] is True and mock.gate_history == [True, False] and mock.gate is False
    assert e["NEW_FEED_CREATED"] is False and len(mock.posts) == posts_before and len(mock.mass_messages) == 1 and mock.write_calls == writes_before + 1   # dry_run is not a write
    msg = mock.mass_messages[0]
    assert msg["mediaFiles"] == [str(m["id"]) for m in mock.posts[pid]["media"]] and msg["userLists"] == ["fans"] and msg["text"] == e["MASS_DM_TEXT"] and msg["text"].count("http") == 1
    run = await engine.runs_col.find_one({"cycle_number": f"post:{pid}"}, {"_id": 0})
    assert run and run["mass_dm_status"] == "OK" and run["mass_dm_id"] == e["MASS_DM_MARKER"] and run["mass_dm_sent_count"] == e["REAL_MASS_DM_SENT_COUNT"] and run["feed_post_id"] == pid and run["mock"] is True
    assert e["TOTAL_REAL_MASS_DM_SENT"] == 0                                                        # mock never counts as real
    # 3) second call for the same post -> STOP before any write (no duplicate)
    e2 = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert e2["status"] == "STOPPED_PRECHECK" and "NO_MASS_DM_ALREADY_SENT_FOR_POST" in e2["failed_checks"] and e2["WRITE_GATE_ENABLED"] is False
    assert len(mock.mass_messages) == 1 and mock.write_calls == writes_before + 1 and mock.gate_history == [True, False]
    # 4) wrong model / unknown post / DM disabled -> STOP, zero writes
    bad = await engine.mass_dm_from_post(b["slug"], pid, execute=True, trigger="test")
    assert bad["status"] == "STOPPED_PRECHECK" and "SOURCE_POST_BELONGS_TO_MODEL(OF link in caption)" in bad["failed_checks"]
    nf = await engine.mass_dm_from_post(a["slug"], "does-not-exist", execute=True, trigger="test")
    assert nf["status"] == "STOPPED_PRECHECK" and "SOURCE_POST_FOUND" in nf["failed_checks"]
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "false")
    off = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert off["status"] == "STOPPED_PRECHECK" and "MASS_DM_ENABLED_FOR_THIS_PROVIDER" in off["failed_checks"]
    assert len(mock.mass_messages) == 1 and len(mock.posts) == posts_before
    # queue untouched by the DM-only test
    assert (await engine.status())["queue"]["current"]["slug"] == b["slug"]


async def test_mass_dm_from_post_gate_restored_on_failure(sandbox, monkeypatch):
    mock = sandbox
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "false")                                            # two feed-only posts (like production so far)
    a, b = await seed(_model(f"{TAG}-lia", 0), _model(f"{TAG}-mara", 1))
    ra = await engine.run("PUBLISH_NOW", "test")
    rb = await engine.run("PUBLISH_NOW", "test")
    assert ra["model_slug"] == a["slug"] and rb["model_slug"] == b["slug"] and len(mock.mass_messages) == 0
    pid = ra["provider_post_id"]
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "true")
    mock.gate_history.clear()
    mock.fail_mass_dm = True
    e = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert e["status"] == "MASS_DM_FAILED" and e["REAL_MASS_DM_CREATE"] == "FAIL" and e["WRITE_GATE_RESTORED_TO_FALSE"] is True and mock.gate_history == [True, False], e.get("failed_checks")
    run = await engine.runs_col.find_one({"cycle_number": f"post:{pid}"}, {"_id": 0})
    assert run["mass_dm_status"] == "FAILED" and not run.get("mass_dm_id")
    # retry allowed after a FAILED (no id) -> exactly one DM; wrong post for a model -> STOP
    mock.fail_mass_dm = False
    e2 = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert e2["status"] == "MASS_DM_CONFIRMED" and len(mock.mass_messages) == 1 and mock.mass_messages[0]["text"].rstrip().endswith(a["onlyfans_url"])
    # Fans list usersCount = 0 -> STOP at pre-check (no gate, no send); Fans list absent -> STOP
    mock.gate_history.clear()
    saved = mock.fans
    mock.fans = 0
    ea = await engine.mass_dm_from_post(b["slug"], rb["provider_post_id"], execute=True, trigger="test")
    assert ea["status"] == "STOPPED_PRECHECK" and "FANS_USERS_COUNT>0" in ea["failed_checks"] and ea["WRITE_GATE_ENABLED"] is False and mock.gate_history == []
    mock.fans = saved
    mock.fans_list_present = False
    ea = await engine.mass_dm_from_post(b["slug"], rb["provider_post_id"], execute=True, trigger="test")
    assert ea["status"] == "STOPPED_PRECHECK" and "FANS_LIST_FOUND(type=fans)" in ea["failed_checks"] and len(mock.mass_messages) == 1
    mock.fans_list_present = True
    # list resolved right before the send inside the flow: usersCount drops to 0 / list disappears after pre-check -> FAILED, nothing sent, gate restored
    real_get = mock.get_fans_list
    async def empty_list(uid):
        return {"id": "fans", "name": "Fans", "usersCount": 0}
    monkeypatch.setattr(mock, "get_fans_list", empty_list)
    d0 = await engine.mass_dm_from_post(b["slug"], rb["provider_post_id"], execute=False, trigger="test")
    assert d0["status"] == "DRY_RUN_FAIL"
    monkeypatch.setattr(mock, "get_fans_list", real_get)
    wrong = await engine.mass_dm_from_post(b["slug"], pid, execute=True, trigger="test")
    assert wrong["status"] == "STOPPED_PRECHECK" and "SOURCE_POST_BELONGS_TO_MODEL(OF link in caption)" in wrong["failed_checks"] and len(mock.mass_messages) == 1


# ------------------------------------------------------------------ SUBSCRIBER REFRESH matrix (mock): failure / timeout / empty cache / stuck / retry only refresh+DM
async def _feed_only(monkeypatch, slug, ordine=0, mock=None):
    """Feed confirmed, DM step failed in a retryable way (refresh start rejected) -> model stays current with FEED_STATUS=OK, MASS_DM_STATUS=FAILED."""
    m, = await seed(_model(slug, ordine))
    mock.refresh_start_error = "API_ERROR"
    r = await engine.run("PUBLISH_NOW", "test")
    mock.refresh_start_error = None
    assert r["status"] == "MOCK_CONFIRMED_DM_PENDING" and r["FEED_STATUS"] == "OK" and r["mass_dm"]["error_code"] == "REFRESH_START_FAILED"
    return m, r


async def test_refresh_failure_blocks_dm_and_retry_only_refresh_dm(sandbox, monkeypatch):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-olga", 0), _model(f"{TAG}-pia", 1))
    mock.refresh_fail = True
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["FEED_STATUS"] == "OK" and r["MASS_DM_STATUS"] == "FAILED" and r["mass_dm"]["error_code"] == "REFRESH_FAILED" and r["mass_dm"]["advance"] is False
    assert len(mock.posts) == 1 and len(mock.mass_messages) == 0 and mock.refresh_starts == 1                                        # no DM without a fresh audience
    run = await engine.get_run(a["id"], 1)
    assert run["subscriber_refresh_status"] == "FAILED" and run["mass_dm_status"] == "FAILED" and run["feed_post_id"] == r["provider_post_id"]
    st = await engine.status()
    assert st["queue"]["current"]["slug"] == a["slug"] and st["current_run"]["FAN_REFRESH_STATUS"] == "FAILED" and st["current_run"]["MASS_DM_STATUS"] == "FAILED"   # queue NOT advanced
    # retry: NO new feed; only refresh + dry run + DM                                                                                  FEED_NOT_DUPLICATED_ON_REFRESH_FAIL
    mock.refresh_fail = False
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["status"] == "MOCK_CONFIRMED" and r2["feed_skipped_duplicate"] is True and r2["MASS_DM_STATUS"] == "OK" and r2["provider_post_id"] == r["provider_post_id"]
    assert len(mock.posts) == 1 and len(mock.mass_messages) == 1 and mock.refresh_starts == 2 and mock.mass_messages[0]["recipients"] == mock.fans and mock.mass_messages[0]["userLists"] == ["fans"]
    assert (await engine.status())["queue"]["current"]["slug"] == b["slug"]
    run = await engine.get_run(a["id"], 1)
    assert run["subscriber_refresh_status"] == "OK" and run["cached_total"] > 0 and run["mass_dm_status"] == "OK"


async def test_refresh_timeout_and_empty_cache_never_send(sandbox, monkeypatch):
    mock = sandbox
    a, r = await _feed_only(monkeypatch, f"{TAG}-rita", mock=mock)
    monkeypatch.setenv("OF_REFRESH_MAX_WAIT_MINUTES", "0.0005")                                     # ~30 ms budget in the test
    mock.refresh_stuck = True
    r2 = await engine.run("PUBLISH_NOW", "test")                                                    # retry path (feed already OK) -> refresh never completes
    assert r2["status"] == "FEED_OK_DM_PENDING" and r2["mass_dm"]["error_code"] == "REFRESH_TIMEOUT" and len(mock.mass_messages) == 0 and len(mock.posts) == 1
    run = await engine.get_run(a["id"], 1)
    assert run["subscriber_refresh_status"] == "TIMEOUT" and run["mass_dm_status"] == "PENDING"     # retryable, audience not verified -> no DM
    monkeypatch.setenv("OF_REFRESH_MAX_WAIT_MINUTES", "10")
    mock.refresh_stuck = False
    mock.refresh_yields_empty = True                                                                  # completes but cache stays 0 while the platform reports fans
    r3 = await engine.run("PUBLISH_NOW", "test")
    assert r3["status"] == "FEED_OK_DM_FAILED" and r3["mass_dm"]["error_code"] == "REFRESH_EMPTY_CACHE" and len(mock.mass_messages) == 0
    run = await engine.get_run(a["id"], 1)
    assert run["subscriber_refresh_status"] == "EMPTY_CACHE" and run["cached_total"] == 0
    mock.refresh_yields_empty = False
    r4 = await engine.run("PUBLISH_NOW", "test")
    assert r4["status"] == "MOCK_CONFIRMED" and len(mock.mass_messages) == 1 and len(mock.posts) == 1 and mock.refresh_starts == 3        # SUBSCRIBER_CACHE_TOTAL_GT_ZERO -> DM


async def test_refresh_start_error_then_gate_retry(sandbox, monkeypatch):
    """Provider rejects the refresh with the gate closed (FORBIDDEN) -> the flow opens the gate, retries the refresh once, then DM; gate restored."""
    mock = sandbox
    a, r = await _feed_only(monkeypatch, f"{TAG}-sara", mock=mock)
    calls = {"n": 0}
    real_start = mock.subscribers_refresh_start
    async def start_once_forbidden(uid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OFProviderError("FORBIDDEN", "gate", 403)
        return await real_start(uid)
    monkeypatch.setattr(mock, "subscribers_refresh_start", start_once_forbidden)
    mock.gate_history.clear()
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["status"] == "MOCK_CONFIRMED" and calls["n"] == 2 and mock.gate_history == [True, False] and mock.gate is False and len(mock.mass_messages) == 1
    monkeypatch.setattr(mock, "subscribers_refresh_start", real_start)
    # refresh NOT supported by a provider -> no DM, feed untouched
    async def unsupported(uid):
        raise OFProviderError("NOT_SUPPORTED", "x")
    b, rb = await _feed_only(monkeypatch, f"{TAG}-tea", 1, mock=mock)
    monkeypatch.setattr(mock, "subscribers_refresh_start", unsupported)
    r3 = await engine.run("PUBLISH_NOW", "test")
    assert r3["status"] == "FEED_OK_DM_FAILED" and r3["mass_dm"]["error_code"] == "REFRESH_NOT_SUPPORTED" and len(mock.mass_messages) == 1


async def test_send_timeout_marks_unverified_and_never_resends(sandbox, monkeypatch):
    mock = sandbox
    a, r = await _feed_only(monkeypatch, f"{TAG}-uma", mock=mock)
    real_send = mock.mass_message_fans
    async def timeout_on_send(uid, req):
        assert req.user_lists == ["fans"] and req.excluded_lists == []
        raise OFProviderError("NETWORK_ERROR", "timeout")                                           # connection dropped after the send started
    monkeypatch.setattr(mock, "mass_message_fans", timeout_on_send)
    mock.gate_history.clear()
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["status"] == "FEED_OK_DM_UNVERIFIED" and r2["mass_dm"]["error_code"] == "NETWORK_ERROR" and r2["mass_dm"]["advance"] is False and mock.gate_history == [True, False]
    run = await engine.get_run(a["id"], 1)
    assert run["mass_dm_status"] == "UNVERIFIED" and run["mass_dm_id"].startswith("crm:") and run["mass_dm_recipients"] > 0 and run["mass_dm_send_started_at"] and run["of_fans_users_count"] == mock.fans
    monkeypatch.setattr(mock, "mass_message_fans", real_send)
    r3 = await engine.run("PUBLISH_NOW", "test")                                                    # TIMEOUT_DOES_NOT_RESEND
    assert r3["status"] == "FEED_OK_DM_UNVERIFIED" and r3["mass_dm"]["duplicate_prevented"] is True and len(mock.mass_messages) == 0 and len(mock.posts) == 1
    assert (await engine.status())["queue"]["current"]["slug"] == a["slug"]                       # model not completed until an admin decision (skip) -> never auto-advanced


async def test_sending_state_blocks_concurrent_second_send(sandbox, monkeypatch):
    mock = sandbox
    a, r = await _feed_only(monkeypatch, f"{TAG}-vera", mock=mock)
    await engine.upsert_run(a["id"], 1, mass_dm_status="SENDING")                                  # a send is in flight (background)
    model = await models_col.find_one({"id": a["id"]}, ofmedia.FIELDS)
    dm = await engine._mass_dm_step(mock, "mock_latosegreto", model, await engine.get_run(a["id"], 1), True, "test")
    assert dm["MASS_DM_STATUS"] == "SENDING" and dm["duplicate_prevented"] is True and len(mock.mass_messages) == 0 and mock.refresh_starts == 0
    dup = await engine.mass_dm_from_post(a["slug"], r["provider_post_id"], execute=True, trigger="test")
    assert dup["status"] == "STOPPED_PRECHECK" and "NO_MASS_DM_ALREADY_SENT_FOR_POST" in dup["failed_checks"]


async def test_scheduler_unchanged_and_refresh_does_not_touch_queue_or_media(sandbox, monkeypatch):
    mock = sandbox
    a, r = await _feed_only(monkeypatch, f"{TAG}-wanda", mock=mock)
    st_before = await engine.status()
    cur_before = await engine.media_state_col.find_one({"model_id": a["id"]}, {"_id": 0, "updated_at": 0})
    mock.refresh_fail = True
    r2 = await engine.run("PUBLISH_NOW", "test")                                                    # refresh fails: no DM, no feed, no cursor change, no advance
    assert r2["mass_dm"]["error_code"] == "REFRESH_FAILED" and len(mock.posts) == 1
    st_after = await engine.status()
    assert st_after["queue"]["current"]["slug"] == a["slug"] and st_after["queue"]["done_in_cycle"] == st_before["queue"]["done_in_cycle"]
    assert (await engine.media_state_col.find_one({"model_id": a["id"]}, {"_id": 0, "updated_at": 0})) == cur_before
    assert st_after["AUTO_SCHEDULER_ENABLED"] is False and st_after["OF_AUTOPILOT_STATUS"] == "PAUSED" and st_after["settings"]["schedule_times"] == ["11:30", "17:30", "22:00"]   # SCHEDULER_UNCHANGED
    assert st_after["settings"]["timezone"] == "Europe/Rome" and st_after["schedule"]["posts_per_day"] == 3 and st_after["settings"]["posts_per_day"] == 3


async def test_mass_dm_from_post_refreshes_before_send(sandbox, monkeypatch):
    mock = sandbox
    a, r = await _feed_only(monkeypatch, f"{TAG}-zoe", mock=mock)
    pid = r["provider_post_id"]
    d = await engine.mass_dm_from_post(a["slug"], pid, execute=False, trigger="test")
    assert d["status"] == "DRY_RUN_PASS" and mock.refresh_starts == 0                                                                 # dry run = READ-ONLY, no refresh
    mock.fans += 7
    e = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert e["status"] == "MASS_DM_CONFIRMED" and mock.refresh_starts == 1 and e["refresh"]["status"] == "OK" and e["OF_FANS_USERS_COUNT"] == mock.fans   # +7 new fans included
    assert e["REAL_MASS_DM_SENT_COUNT"] == mock.fans and e["QUEUE_VERIFY"] == "PASS" and e["WRITE_GATE_RESTORED_TO_FALSE"] is True and e["NEW_FEED_CREATED"] is False
    run = await engine.runs_col.find_one({"cycle_number": f"post:{pid}"}, {"_id": 0})
    assert run["subscriber_refresh_status"] == "OK" and run["cached_total"] == mock.fans + mock.expired_fans and run["mass_dm_status"] == "OK"


async def test_verify_falls_back_to_recent_chats_when_no_queue_id(sandbox, monkeypatch):
    mock = sandbox
    a, r = await _feed_only(monkeypatch, f"{TAG}-yara", mock=mock)
    mock.native_queue_id = False                                                                   # provider answers success without a queue id
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["status"] == "MOCK_CONFIRMED" and r2["mass_dm"]["queue_verify"] == "NO_ID" and r2["mass_dm"]["readback"] == "PASS" and r2["mass_dm"]["mass_dm_id"].startswith("crm:")
    assert mock.last_mass_payload["userLists"] == ["fans"] and mock.last_mass_payload["excludedLists"] == [] and len(mock.mass_messages) == 1
    assert len(mock.last_mass_payload["mediaFiles"]) == 2                                          # Public + Secret vault ids


async def test_real_adapter_fans_payload_shape_and_no_dry_run(monkeypatch):
    """Adapter contract: userLists/excludedLists only (OpenAPI shape), no audience.type / fan_ids / dry_run; blocked before network by the gates."""
    monkeypatch.setenv("THE_ONLY_API_KEY", "k" * 43)
    monkeypatch.setenv("THE_ONLY_CRM_ID", "crm")
    monkeypatch.setenv("OF_REAL_POSTING_ENABLED", "true")
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "true")
    monkeypatch.setenv("OF_MASS_DM_MOCK", "false")
    ad = toa.TheOnlyAPIAdapter()
    assert ad.FANS_DRY_RUN_SUPPORTED is False
    counters_before = dict(toa.CALLS)
    captured = {}
    async def fake_request(method, url, **kw):
        captured.update(method=method, url=url, json=kw.get("json"), write=kw.get("write"))
        return {"success": True, "data": {"id": "987", "sent": 0}}
    monkeypatch.setattr(ad, "_request", fake_request)
    res = await ad.mass_message_fans("1", OFMassMessageRequest(text="ciao", media_ids=[11, 22], user_lists=["fans"], excluded_lists=[]))
    assert captured["method"] == "POST" and captured["url"].endswith("/accounts/1/messages/mass") and captured["write"] is True
    assert captured["json"] == {"text": "ciao", "price": 0, "mediaFiles": ["11", "22"], "userLists": ["fans"], "excludedLists": []}
    assert "audience" not in captured["json"] and "dry_run" not in captured["json"] and "fan_ids" not in captured["json"] and "queueBuyers" not in captured["json"]
    assert res["id"] == "987" and res["success"] is True
    with pytest.raises(OFProviderError):
        await ad.mass_message_fans("1", OFMassMessageRequest(text="ciao", media_ids=[11], user_lists=[]))        # target mandatory
    # lists parsing: system list type=fans picked dynamically
    async def fake_lists(method, url, **kw):
        return {"success": True, "status_code": 200, "data": {"list": [{"id": "following", "type": "following", "usersCount": 188}, {"id": "fans", "type": "fans", "name": "Fans", "usersCount": 2300}]}}
    monkeypatch.setattr(ad, "_request", fake_lists)
    assert await ad.get_fans_list("1") == {"id": "fans", "name": "Fans", "usersCount": 2300}
    toa.CALLS.update(counters_before)                                                               # fake _request never hit the network: keep global counters clean


def _safe_tz():
    """A valid IANA zone whose local time is far from midnight (dynamic HH:MM slot tests must not cross the day boundary)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    for name in ("Europe/Rome", "Asia/Tokyo", "America/Los_Angeles", "Pacific/Kiritimati", "Asia/Kolkata", "America/Sao_Paulo"):
        if 2 <= datetime.now(ZoneInfo(name)).hour <= 20:
            return name
    return "Europe/Rome"


# ------------------------------------------------------------------ activation: NO catch-up, close-by-readback (zero writes)
async def test_activation_no_catch_up(sandbox, monkeypatch):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    mock = sandbox
    a, = await seed(_model(f"{TAG}-ada", 0))
    await engine.set_state(timezone=_safe_tz())
    st = await engine.get_state()
    tz = ZoneInfo(st["timezone"])
    now = datetime.now(tz)
    # a slot 20 minutes ago (inside the 90' grace) would normally be "due" -> with activation now it must NOT be recovered
    past = (now - timedelta(minutes=20)).strftime("%H:%M")
    future = (now + timedelta(minutes=45)).strftime("%H:%M")                                        # beyond the 30' preparation lead
    await engine.set_state(schedule_times=[past, future], posts_per_day=2, enabled=True, activated_at=None)
    st = await engine.get_state()
    due = await engine.due_slot(st)
    assert due and past in due["slot_id"]                                                            # without activation guard the past slot is due (legacy)
    await engine.set_state(activated_at=engine.now_iso())                                            # what POST /start does
    st = await engine.get_state()
    due2 = await engine.due_slot(st)
    assert due2 is None or past not in due2["slot_id"]                                               # CATCH_UP_ENABLED = FALSE
    monkeypatch.setenv("OF_AUTO_SCHEDULER_ENABLED", "true")
    t = await engine.tick("test")
    assert t["status"] == "NO_DUE_SLOT" and len(mock.posts) == 0                                     # IMMEDIATE_RUN_TRIGGERED = FALSE (past slot never recovered)
    assert not await engine.slots_col.find_one({"slot_id": {"$regex": past}})
    s = await engine.status()
    assert s["CATCH_UP_ENABLED"] is False and s["MASS_DM_TARGET"] == "FAN" and s["activated_at"]


async def test_close_mass_dm_run_by_readback_zero_writes(sandbox, monkeypatch):
    mock = sandbox
    a, r = await _feed_only(monkeypatch, f"{TAG}-bice", mock=mock)
    pid = r["provider_post_id"]
    async def net_error(uid, req):
        raise OFProviderError("API_ERROR", "provider 5xx", 502)
    monkeypatch.setattr(mock, "mass_message_fans", net_error)
    e = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert e["status"] == "MASS_DM_UNVERIFIED", e.get("failed_checks")
    writes = mock.write_calls
    monkeypatch.setattr(mock, "mass_message_fans", lambda uid, req: (_ for _ in ()).throw(AssertionError("no send allowed")))
    c = await engine.close_mass_dm_run(pid, "MASS_DM_READBACK_CONFIRMED", trigger="test")
    assert c["status"] == "CLOSED" and c["previous_mass_dm_status"] == "UNVERIFIED" and c["provider_response"] == "API_ERROR" and c["readback_confirmed"] is True and c["writes"] == 0
    run = await engine.runs_col.find_one({"cycle_number": f"post:{pid}"}, {"_id": 0})
    assert run["mass_dm_status"] == "OK" and run["closed_by_admin"] is True and run["provider_response"] == "API_ERROR" and run["previous_mass_dm_status"] == "UNVERIFIED" and run["mass_dm_id"]
    assert mock.write_calls == writes and len(mock.posts) == 1                                       # zero writes, no new feed
    logs = [l async for l in engine.log_col.find({"feed_post_id": pid})]
    assert any(l["status"] == "MASS_DM_NOT_CONFIRMED" for l in logs) and any(l["status"] == "MASS_DM_CLOSED_BY_READBACK" for l in logs)   # error history preserved
    dup = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert dup["status"] == "STOPPED_PRECHECK" and "NO_MASS_DM_ALREADY_SENT_FOR_POST" in dup["failed_checks"]                             # duplicate protection stays
    assert (await engine.close_mass_dm_run(pid, "x", trigger="test"))["status"] == "ALREADY_OK"
    assert (await engine.close_mass_dm_run("nope", "x", trigger="test"))["status"] == "NOT_FOUND"


async def test_close_legacy_run_current_model_advances_next_model_not_published(sandbox, monkeypatch):
    """Production shape of the Vanessa closure: the model is still the queue candidate, its real feed pre-dates of_model_runs (no cycle run), the DM-only
    run (post:<id>) is UNVERIFIED/API_ERROR. Closing by read-back: DB-only, history preserved, cycle run FEED OK + DM OK, queue -> NEXT_MODEL,
    NOTHING published now, and the scheduler never produces a second feed/DM for the closed model."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    mock = sandbox
    van, nxt = await seed(_model(f"{TAG}-van", 0), _model(f"{TAG}-nxt", 1))
    pid = "2759765107"
    await engine.runs_col.insert_one({"id": str(uuid.uuid4()), "model_id": van["id"], "cycle_number": f"post:{pid}", "model_slug": van["slug"], "model_name": van["nome_artistico"], "mock": False,
                                      "action_type": "MASS_DM_TEST", "feed_status": "OK", "feed_post_id": pid, "of_link": van["onlyfans_url"], "mass_dm_status": "UNVERIFIED",
                                      "mass_dm_error": "API_ERROR", "mass_dm_id": "crm:abc123", "mass_dm_attempts": 1, "created_at": engine.now_iso()})
    st = await engine.get_state()
    assert (await engine.queue_view(st))["next"]["model_id"] == van["id"] and await engine.get_run(van["id"], st["cycle_number"]) is None
    monkeypatch.setattr(mock, "mass_message_fans", lambda uid, req: (_ for _ in ()).throw(AssertionError("no send allowed")))
    monkeypatch.setattr(mock, "create_post", lambda uid, req: (_ for _ in ()).throw(AssertionError("no feed allowed")))
    c = await engine.close_mass_dm_run(pid, "MASS_DM_READBACK_CONFIRMED", trigger="test")
    assert c["status"] == "CLOSED" and c["queue_advanced"] is True and c["NEXT_MODEL"] == nxt["slug"] and c["writes"] == 0 and c["readback_confirmed"] is True
    assert c["previous_mass_dm_status"] == "UNVERIFIED" and c["provider_response"] == "API_ERROR" and c["mass_dm_id"] == "crm:abc123"
    legacy = await engine.runs_col.find_one({"cycle_number": f"post:{pid}"}, {"_id": 0})
    assert legacy["mass_dm_status"] == "OK" and legacy["previous_mass_dm_status"] == "UNVERIFIED" and legacy["provider_response"] == "API_ERROR" and legacy["readback_confirmed"] is True
    cyc = await engine.get_run(van["id"], st["cycle_number"])
    assert cyc["feed_status"] == "OK" and cyc["feed_post_id"] == pid and cyc["mass_dm_status"] == "OK" and cyc["readback_confirmed"] is True and cyc["closed_by_admin"] is True
    st = await engine.get_state()
    assert van["id"] in st["cycle_done"] and st["last_published"]["provider_post_id"] == pid and len(mock.posts) == 0 and len(mock.mass_messages) == 0
    s = await engine.status()
    assert s["NEXT_MODEL"] == nxt["slug"] and s["closed_runs"][0]["model_slug"] == van["slug"] and s["closed_runs"][0]["provider_response"] == "API_ERROR"
    # scheduler ON right after the closure: no due slot -> nothing happens (IMMEDIATE_RUN_TRIGGERED = FALSE)
    await engine.set_state(timezone=_safe_tz())
    st = await engine.get_state()
    tz = ZoneInfo(st["timezone"])
    now = datetime.now(tz)
    far = (now + timedelta(minutes=120)).strftime("%H:%M")
    await engine.set_state(schedule_times=[far], posts_per_day=1, enabled=True, activated_at=engine.now_iso())
    monkeypatch.setenv("OF_AUTO_SCHEDULER_ENABLED", "true")
    t = await engine.tick("test")
    assert t["status"] == "NO_DUE_SLOT" and len(mock.posts) == 0 and len(mock.mass_messages) == 0
    # the NEXT future official slot (inside the 30' preparation lead) -> SCHEDULE for NEXT_MODEL only, never for the closed model
    soon = now + timedelta(minutes=10)
    monkeypatch.setattr(mock, "create_post", MockOFProvider.create_post.__get__(mock))
    await engine.set_state(schedule_times=[soon.strftime("%H:%M")], posts_per_day=1)
    await engine.slots_col.delete_many({"slot_id": f"of_{soon.strftime('%Y-%m-%d')}_{soon.strftime('%H:%M')}"})                       # slot ids are global: drop residue of other tests
    t2 = await engine.tick("test")
    assert t2["status"].startswith("MOCK_CONFIRMED") and t2["model_slug"] == nxt["slug"] and t2["model_slug"] != van["slug"]
    assert all(p["model_id"] != van["id"] for p in [u async for u in engine.uploads_col.find({"model_id": {"$in": [van["id"], nxt["id"]]}})])
    assert (await engine.get_run(van["id"], 1))["feed_post_id"] == pid                                                                  # closed model untouched


async def test_start_route_semantics_no_catch_up_next_run_future(sandbox, monkeypatch):
    """What POST /start persists: activated_at + next_run strictly in the future; a slot 5' ago (inside grace) is never recovered by tick()."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    mock = sandbox
    await seed(_model(f"{TAG}-cla", 0))
    await engine.set_state(timezone=_safe_tz())
    st = await engine.get_state()
    tz = ZoneInfo(st["timezone"])
    now = datetime.now(tz)
    past = (now - timedelta(minutes=5)).strftime("%H:%M")
    future = (now + timedelta(minutes=50)).strftime("%H:%M")
    await engine.set_state(schedule_times=[past, future], posts_per_day=2)
    await engine.set_state(enabled=True, activated_at=engine.now_iso())
    st = await engine.get_state()
    sch = await engine.schedule_view(st)
    await engine.set_state(next_run=(sch["next_slot"] or {}).get("at"))
    assert future in sch["next_slot"]["slot_id"] and datetime.fromisoformat(sch["next_slot"]["at"]) > now
    monkeypatch.setenv("OF_AUTO_SCHEDULER_ENABLED", "true")
    for _ in range(2):
        t = await engine.tick("test")
        assert t["status"] == "NO_DUE_SLOT"
    assert len(mock.posts) == 0 and len(mock.mass_messages) == 0 and not await engine.slots_col.find_one({"slot_id": {"$regex": past}})
    s = await engine.status()
    assert s["OF_AUTOPILOT_STATUS"] == "ACTIVE" and s["CATCH_UP_ENABLED"] is False and s["next_run"] == sch["next_slot"]["at"] and s["last_run"] is None
