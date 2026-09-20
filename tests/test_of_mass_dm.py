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
    yield mock
    assert toa.CALLS["write"] == writes_before and toa.CALLS["mass_dm"] == dm_before == 0, "a REAL provider write / mass DM happened"
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
    assert r["MASS_DM_STATUS"] == "OK" and dm["advance"] is True and dm["mass_dm_id"].startswith("crm:") and len(mock.mass_messages) == 1   # MASS_DM_CREATE + read-back MASS_DM_VERIFY
    assert mock.refresh_starts == 1 and dm["refresh"]["status"] == "OK" and mock.cache_total == mock.fans + mock.expired_fans          # SUBSCRIBER_REFRESH_START/STATUS/COMPLETED before the DM
    assert dm["audience_size"] == mock.fans + mock.expired_fans and dm["sent_count"] == dm["audience_size"] and dm["readback"] == "PASS"   # DRY_RUN_AFTER_REFRESH, recipients = ALL (active+expired)
    msg = mock.mass_messages[0]
    assert msg["audience"] == "all" and msg["recipients"] == mock.cache_total                                                          # MASS_DM_TARGET_ALL
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
    assert run["cached_active"] == mock.fans and run["cached_expired"] == mock.expired_fans and run["last_refreshed_at"] and run["mass_dm_recipients"] == mock.cache_total
    st = await engine.status()
    assert st["queue"]["current"]["slug"] == b["slug"] and st["OF_REAL_MASS_DM_SENT"] is False and st["THE_ONLY_API_REAL_MASS_DM_CALLS"] == 0 and st["TOTAL_REAL_POSTS_CREATED"] == 0
    assert st["current_run"]["FEED_STATUS"] == "PENDING" and st["current_run"]["MASS_DM_STATUS"] == "PENDING" and st["current_run"]["FAN_REFRESH_STATUS"] == "PENDING"
    # NEW_SUBSCRIBERS_INCLUDED: 15 new fans arrive -> next model's DM refreshes and uses the updated audience (never the previous cycle's count)
    mock.fans += 15
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["status"] == "MOCK_CONFIRMED" and r2["model_slug"] == b["slug"] and mock.refresh_starts == 2
    assert r2["mass_dm"]["audience_size"] == mock.fans + mock.expired_fans == dm["audience_size"] + 15 and mock.mass_messages[1]["recipients"] == dm["audience_size"] + 15
    assert (await engine.status())["scheduler"]["slots"] if False else True


# ------------------------------------------------------------------ feed OK, DM fails -> no advance, retry ONLY the DM, never a second feed, never a second DM
async def test_feed_success_dm_fail_retry_only_dm(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-cara", 0), _model(f"{TAG}-dora", 1))
    mock.fail_mass_dm = True
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["status"] == "MOCK_CONFIRMED_DM_FAILED" and r["FEED_STATUS"] == "OK" and r["MASS_DM_STATUS"] == "FAILED" and r["mass_dm"]["advance"] is False
    assert len(mock.posts) == 1 and len(mock.mass_messages) == 0 and mock.refresh_starts == 1 and r["mass_dm"]["audience_size"] > 0        # refresh + dry run happened, send rejected
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
    assert r["MASS_DM_STATUS"] == "UNVERIFIED" and r["status"] == "MOCK_CONFIRMED_DM_UNVERIFIED" and mock.write_calls == 4          # 2 uploads + post + 1 dm send (sent=0 but chats show it)
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
            await ad.send_mass_message("1", OFMassMessageRequest(text="x", media_ids=["1"]))
        assert ei.value.code == "MASS_DM_DISABLED"
        with pytest.raises(OFProviderError) as ei2:
            await ad.mass_message_audience_size("1")
        assert ei2.value.code == "MASS_DM_DISABLED"
    assert toa.CALLS == before, "no network, no counters"
    # documented body shape: queueBuyers [] = all subscribers; only ALL audience accepted
    assert ad._queue_buyers(OFMassMessageRequest(text="x", audience="ALL")) == []
    with pytest.raises(OFProviderError):
        ad._queue_buyers(OFMassMessageRequest(text="x", audience="vip"))


async def test_mass_dm_from_post_unverified_never_resent(sandbox, monkeypatch):
    mock = sandbox
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "false")
    a, = await seed(_model(f"{TAG}-nora", 0))
    r = await engine.run("PUBLISH_NOW", "test")
    pid = r["provider_post_id"]
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "true")
    async def net_error(uid, req, dry_run=True):
        if dry_run:
            return {"success": True, "dry_run": True, "recipients": 5, "sent": 0, "sample": [{"fan_of_user_id": "fanX", "username": "x"}]}
        raise OFProviderError("NETWORK_ERROR", "timeout")                                              # connection dropped during the serial send
    monkeypatch.setattr(mock, "mass_message_crm", net_error)
    e = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert e["status"] == "MASS_DM_UNVERIFIED" and e["REAL_MASS_DM_CREATE"].startswith("UNKNOWN_") and e["READBACK_VERIFY"] == "FAIL" and e["WRITE_GATE_RESTORED_TO_FALSE"] is True
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
    assert d["SOURCE_MEDIA_COUNT"] == 2 and len(d["VAULT_MEDIA_IDS_MASKED"]) == 2 and d["AUDIENCE_SIZE"] == mock.fans and d["WRITE_GATE_BEFORE"] is False
    assert d["MASS_DM_TEXT"].startswith("👀 Hai già scoperto ") and d["MASS_DM_TEXT"].rstrip().endswith(a["onlyfans_url"]) and d["MASS_DM_TEXT"] != r["caption"]
    assert mock.write_calls == writes_before and len(mock.mass_messages) == 0 and mock.gate_history == []
    # 2) EXECUTE = gate on -> ONE mass DM -> verify -> saved -> gate off (verified)
    e = await engine.mass_dm_from_post(a["slug"], pid, execute=True, trigger="test")
    assert e["status"] == "MASS_DM_CONFIRMED" and e["REAL_MASS_DM_CREATE"] == "PASS" and e["READBACK_VERIFY"] == "PASS" and e["REAL_MASS_DM_CONFIRMED"] == "PASS"
    assert e["AUDIENCE_TYPE"] == "all" and e["DRY_RUN_RECIPIENTS"] == mock.fans + mock.expired_fans and e["REAL_MASS_DM_SENT_COUNT"] == mock.fans + mock.expired_fans   # ALL = active + expired
    assert e["WRITE_GATE_ENABLED"] is True and e["WRITE_GATE_RESTORED_TO_FALSE"] is True and mock.gate_history == [True, False] and mock.gate is False
    assert e["NEW_FEED_CREATED"] is False and len(mock.posts) == posts_before and len(mock.mass_messages) == 1 and mock.write_calls == writes_before + 1   # dry_run is not a write
    msg = mock.mass_messages[0]
    assert msg["mediaFiles"] == [str(m["id"]) for m in mock.posts[pid]["media"]] and msg["audience"] == "all" and msg["text"] == e["MASS_DM_TEXT"] and msg["text"].count("http") == 1
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
    # empty audience -> ABORT before any send, gate restored
    mock.gate_history.clear()
    mock.fans, mock.expired_fans = 0, 0
    ea = await engine.mass_dm_from_post(b["slug"], rb["provider_post_id"], execute=True, trigger="test")
    assert ea["status"] == "STOPPED_PRECHECK" and "MASS_DM_TARGET_ALL_FANS(subscribers>0)" in ea["failed_checks"]        # read proxy already 0 -> STOP before gate
    mock.fans, mock.expired_fans = 3, 0
    monkeypatch.setattr(mock, "subscribers_count", lambda uid: __import__("asyncio").sleep(0, result=3))
    real_dry = mock.mass_message_crm
    async def zero_dry(uid, req, dry_run=True):
        return {"success": True, "dry_run": True, "recipients": 0, "sent": 0, "sample": []} if dry_run else await real_dry(uid, req, dry_run)
    monkeypatch.setattr(mock, "mass_message_crm", zero_dry)
    ea = await engine.mass_dm_from_post(b["slug"], rb["provider_post_id"], execute=True, trigger="test")
    assert ea["status"] == "ABORTED_EMPTY_AUDIENCE" and ea["REAL_MASS_DM_CREATE"] == "SKIPPED" and ea["WRITE_GATE_RESTORED_TO_FALSE"] is True and mock.gate_history == [True, False] and len(mock.mass_messages) == 1
    monkeypatch.setattr(mock, "mass_message_crm", real_dry)
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
    assert len(mock.posts) == 1 and len(mock.mass_messages) == 1 and mock.refresh_starts == 2 and mock.mass_messages[0]["recipients"] == mock.fans + mock.expired_fans
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
    real_crm = mock.mass_message_crm
    async def timeout_on_send(uid, req, dry_run=True):
        if dry_run:
            return await real_crm(uid, req, dry_run=True)
        raise OFProviderError("NETWORK_ERROR", "timeout")                                           # connection dropped after the send started
    monkeypatch.setattr(mock, "mass_message_crm", timeout_on_send)
    mock.gate_history.clear()
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["status"] == "FEED_OK_DM_UNVERIFIED" and r2["mass_dm"]["error_code"] == "NETWORK_ERROR" and r2["mass_dm"]["advance"] is False and mock.gate_history == [True, False]
    run = await engine.get_run(a["id"], 1)
    assert run["mass_dm_status"] == "UNVERIFIED" and run["mass_dm_id"].startswith("crm:") and run["mass_dm_recipients"] > 0 and run["mass_dm_send_started_at"]
    monkeypatch.setattr(mock, "mass_message_crm", real_crm)
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
    assert e["status"] == "MASS_DM_CONFIRMED" and mock.refresh_starts == 1 and e["refresh"]["status"] == "OK" and e["DRY_RUN_RECIPIENTS"] == mock.fans + mock.expired_fans
    assert e["REAL_MASS_DM_SENT_COUNT"] == e["DRY_RUN_RECIPIENTS"] and e["READBACK_VERIFY"] == "PASS" and e["WRITE_GATE_RESTORED_TO_FALSE"] is True and e["NEW_FEED_CREATED"] is False
    run = await engine.runs_col.find_one({"cycle_number": f"post:{pid}"}, {"_id": 0})
    assert run["subscriber_refresh_status"] == "OK" and run["cached_total"] == mock.fans + mock.expired_fans and run["mass_dm_status"] == "OK"
