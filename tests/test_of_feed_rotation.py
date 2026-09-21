# ruff: noqa: F811
"""OF Autopilot — ROTATION INVARIANT (hotfix duplicate Valeria): max ONE feed per model+cycle; FEED cursor independent from the MASS DM;
DM lives in a separate retry queue; duplicate guard BEFORE any upload/write; new cycle only when every eligible model has FEED_CONSUMED.
The 10 mandatory scenarios + reconcile. MockOFProvider only: zero network, zero real writes."""
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/tests")
from test_of_mass_dm import sandbox, seed, _model, TAG, _safe_tz  # noqa: E402,F401
from of_autopilot import engine  # noqa: E402
from of_autopilot.providers.base import OFProviderError  # noqa: E402

pytestmark = pytest.mark.anyio


async def _cycle():
    return (await engine.get_state())["cycle_number"]


async def _feeds_for(model_id):
    return await engine.log_col.count_documents({"model_id": model_id, "status": {"$in": ["MOCK_CONFIRMED", "SCHEDULE_UNVERIFIED", "POST_UNVERIFIED", "FEED_UNVERIFIED"]}})


# 1. Feed A PASS + DM PASS -> next slot Feed B
async def test_1_feed_a_dm_ok_then_feed_b(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-r1a", 0), _model(f"{TAG}-r1b", 1))
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["model_slug"] == a["slug"] and r["FEED_STATUS"] == "OK" and r["MASS_DM_STATUS"] == "OK" and r["FEED_CONSUMED"] is True
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["model_slug"] == b["slug"] and len(mock.posts) == 2 and await _feeds_for(a["id"]) == 1


# 2. Feed A PASS + DM FAIL -> next slot Feed B; DM of A retried SEPARATELY (DM-only)
async def test_2_feed_a_dm_fail_then_feed_b_and_dm_only_retry(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-r2a", 0), _model(f"{TAG}-r2b", 1))
    mock.fail_mass_dm = True
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["model_slug"] == a["slug"] and r["FEED_STATUS"] == "OK" and r["MASS_DM_STATUS"] == "FAILED" and r["FEED_CONSUMED"] is True
    st = await engine.status()
    assert st["NEXT_FEED_MODEL"] == b["slug"] and st["LAST_FEED_MODEL"] == a["slug"] and st["dm_queue"][0]["model_slug"] == a["slug"]
    mock.fail_mass_dm = False
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["model_slug"] == b["slug"] and r2["MASS_DM_STATUS"] == "OK" and len(mock.posts) == 2 and len(mock.mass_messages) == 1
    d = await engine.run_dm_only("test", model_slug=a["slug"])
    assert d["status"] == "DM_OK" and d["feed_skipped_duplicate"] is True and d["provider_post_id"] == r["provider_post_id"]
    assert len(mock.posts) == 2 and len(mock.mass_messages) == 2 and mock.mass_messages[1]["mediaFiles"] == [str(m["id"]) for m in mock.posts[r["provider_post_id"]]["media"]]
    assert await engine.dm_queue_view() == [] and await _feeds_for(a["id"]) == 1


# 3. Feed A PASS + DM PENDING -> A cannot be re-published in this cycle
async def test_3_dm_pending_blocks_second_feed(sandbox):
    mock = sandbox
    a, b, c = await seed(_model(f"{TAG}-r3a", 0), _model(f"{TAG}-r3b", 1), _model(f"{TAG}-r3c", 2))
    mock.refresh_start_error = "API_ERROR"
    r = await engine.run("PUBLISH_NOW", "test")
    mock.refresh_start_error = None
    assert r["model_slug"] == a["slug"] and r["MASS_DM_STATUS"] == "PENDING" and r["FEED_CONSUMED"] is True
    cyc = r["cycle_number"]
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["model_slug"] == b["slug"] and (await engine.queue_view())["next"]["model_id"] == c["id"]
    assert await engine.log_col.count_documents({"model_id": a["id"], "cycle_number": cyc, "status": "MOCK_CONFIRMED"}) == 1
    assert (await engine.get_run(a["id"], cyc))["mass_dm_status"] == "PENDING" and a["id"] in (await engine.get_state())["cycle_done"]


# 4. Feed A PASS + DM UNVERIFIED -> A cannot be re-published (and the DM is never re-sent)
async def test_4_dm_unverified_blocks_second_feed(sandbox, monkeypatch):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-r4a", 0), _model(f"{TAG}-r4b", 1))
    async def timeout_send(uid, req):
        raise OFProviderError("NETWORK_ERROR", "timeout")
    real = mock.mass_message_fans
    monkeypatch.setattr(mock, "mass_message_fans", timeout_send)
    r = await engine.run("PUBLISH_NOW", "test")
    monkeypatch.setattr(mock, "mass_message_fans", real)
    assert r["model_slug"] == a["slug"] and r["MASS_DM_STATUS"] == "UNVERIFIED" and r["FEED_CONSUMED"] is True
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["model_slug"] == b["slug"] and await _feeds_for(a["id"]) == 1
    assert (await engine.run_dm_only("test", model_slug=a["slug"]))["error_code"] == "UNVERIFIED_NEVER_RESENT" and len(mock.mass_messages) == 1


# 5. backend restart after Feed A (state only in DB) -> next Feed B
async def test_5_restart_after_feed_a(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-r5a", 0), _model(f"{TAG}-r5b", 1))
    mock.fail_mass_dm = True
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["model_slug"] == a["slug"] and r["MASS_DM_STATUS"] == "FAILED"
    await engine.locks_col.delete_many({})                                                      # process restart: in-memory nothing, locks gone
    st = await engine.get_state()                                                                  # everything re-read from Mongo
    q = await engine.queue_view(st)
    assert q["next"]["model_id"] == b["id"] and engine.feed_consumed(await engine.get_run(a["id"], st["cycle_number"]))
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["model_slug"] == b["slug"] and await _feeds_for(a["id"]) == 1


# 6. double scheduler tick on the same slot -> ONE Feed A
async def test_6_double_tick_same_slot_one_feed(sandbox, monkeypatch):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-r6a", 0), _model(f"{TAG}-r6b", 1))
    await engine.set_state(timezone=_safe_tz())
    st = await engine.get_state()
    now = datetime.now(ZoneInfo(st["timezone"]))
    soon = now + timedelta(minutes=10)
    slot_id = f"of_{soon.strftime('%Y-%m-%d')}_{soon.strftime('%H:%M')}"
    await engine.slots_col.delete_many({"slot_id": slot_id})
    await engine.set_state(schedule_times=[soon.strftime("%H:%M")], posts_per_day=1, enabled=True, activated_at=engine.now_iso())
    monkeypatch.setenv("OF_AUTO_SCHEDULER_ENABLED", "true")
    t1 = await engine.tick("test")
    t2 = await engine.tick("test")
    assert t1["status"] == "MOCK_CONFIRMED" and t1["model_slug"] == a["slug"] and t2["status"] == "NO_DUE_SLOT"
    assert len(mock.posts) == 1 and await _feeds_for(a["id"]) == 1
    await engine.slots_col.delete_many({"slot_id": slot_id})


# 7. next slot -> Feed B, never A
async def test_7_next_slot_feed_b_never_a(sandbox, monkeypatch):
    mock = sandbox
    a, b, c = await seed(_model(f"{TAG}-r7a", 0), _model(f"{TAG}-r7b", 1), _model(f"{TAG}-r7c", 2))
    mock.fail_mass_dm = True                                                                       # every DM fails: the FEED rotation must not care
    for expected in (a, b, c):
        r = await engine.run("SCHEDULE", "scheduler", slot_id=f"{TAG}_s7_{expected['slug']}", scheduled_at="2030-01-01T11:30:00+01:00")
        assert r["model_slug"] == expected["slug"] and r["MASS_DM_STATUS"] in ("PENDING", "FAILED")
    assert [await _feeds_for(m["id"]) for m in (a, b, c)] == [1, 1, 1] and len(mock.posts) == 3 and len(mock.mass_messages) == 0
    assert [x["model_slug"] for x in await engine.dm_queue_view()] == [a["slug"], b["slug"], c["slug"]]


# 8. whole cycle completed -> new cycle_id -> only then A is eligible again
async def test_8_new_cycle_rotation(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-r8a", 0), _model(f"{TAG}-r8b", 1))
    mock.fail_mass_dm = True
    c1 = await _cycle()
    r1 = await engine.run("PUBLISH_NOW", "test")
    assert r1["model_slug"] == a["slug"] and await _cycle() == c1
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["model_slug"] == b["slug"] and await _cycle() == c1 + 1                              # all consumed -> new cycle
    r3 = await engine.run("PUBLISH_NOW", "test")
    assert r3["model_slug"] == a["slug"] and r3["cycle_number"] == c1 + 1                          # A back ONLY in the new cycle
    assert await engine.log_col.count_documents({"model_id": a["id"], "status": "MOCK_CONFIRMED", "cycle_number": c1}) == 1
    assert (await engine.get_run(a["id"], c1))["mass_dm_status"] == "FAILED" and (await engine.get_run(a["id"], c1 + 1))["feed_consumed"] is True   # per-cycle runs


# 9. Skip after Feed A already published -> A stays consumed, DM stays PENDING, next Feed B
async def test_9_skip_after_feed_keeps_consumed_and_dm_pending(sandbox):
    mock = sandbox
    a, b, c = await seed(_model(f"{TAG}-r9a", 0), _model(f"{TAG}-r9b", 1), _model(f"{TAG}-r9c", 2))
    mock.refresh_start_error = "API_ERROR"
    r = await engine.run("PUBLISH_NOW", "test")
    mock.refresh_start_error = None
    assert r["model_slug"] == a["slug"] and r["MASS_DM_STATUS"] == "PENDING"
    await engine.skip_current("test")                                                              # admin "Salta" on the CURRENT candidate (B)
    st = await engine.get_state()
    run_a = await engine.get_run(a["id"], 1)
    assert run_a["feed_consumed"] is True and run_a["feed_status"] == "OK" and run_a["mass_dm_status"] == "PENDING"        # skip never means "DM completed"
    assert a["id"] in st["cycle_done"] and [x["model_slug"] for x in await engine.dm_queue_view()] == [a["slug"]]
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["model_slug"] != a["slug"] and await _feeds_for(a["id"]) == 1


# 10. duplicate guard blocks BEFORE any upload/provider write
async def test_10_duplicate_guard_before_write(sandbox, monkeypatch):
    mock = sandbox
    a, b, c = await seed(_model(f"{TAG}-r10a", 0), _model(f"{TAG}-r10b", 1), _model(f"{TAG}-r10c", 2))
    st = await engine.get_state()
    # legacy/corrupted state: A has a consumed run but is still the queue candidate (cycle_done empty)
    await engine.upsert_run(a["id"], st["cycle_number"], model_slug=a["slug"], model_name=a["nome_artistico"], mock=True, feed_status="OK", feed_consumed=True, feed_post_id="mock_of_existing", mass_dm_status="PENDING")
    def boom(*a, **k):
        raise AssertionError("upload/write attempted for a consumed model")
    real_upload = mock.upload_media
    monkeypatch.setattr(mock, "upload_media", boom)
    r = await engine.run("PUBLISH_NOW", "test")
    # the slot continued with B (guard consumed A first) -> restore upload for B assertion via a second run
    assert r["status"] in ("BLOCKED_DUPLICATE_FEED", "UPLOAD_FAILED") or r.get("model_slug") == b["slug"]
    assert await engine.log_col.count_documents({"model_id": a["id"], "status": "BLOCKED_DUPLICATE_FEED"}) == 1
    assert a["id"] in (await engine.get_state())["cycle_done"] and await _feeds_for(a["id"]) == 0
    monkeypatch.setattr(mock, "upload_media", real_upload)
    # SENDING marker alone (crash right after the marker, before the provider answered) also blocks
    st = await engine.get_state()
    await engine.upsert_run(b["id"], st["cycle_number"], model_slug=b["slug"], model_name=b["nome_artistico"], mock=True, feed_status="SENDING", feed_consumed=True)
    if b["id"] not in st["cycle_done"]:
        monkeypatch.setattr(mock, "upload_media", boom)
        r2 = await engine.run("PUBLISH_NOW", "test")
        assert r2["status"] == "BLOCKED_DUPLICATE_FEED" or r2.get("model_slug") != b["slug"]
    assert engine.feed_consumed({"feed_status": "SENDING"}) and engine.feed_consumed({"feed_status": "UNVERIFIED"}) and not engine.feed_consumed({"feed_status": "FAILED", "feed_consumed": False})


# 5xx / timeout on the create -> FEED_UNVERIFIED, consumed, next slot B; 4xx -> FAILED, not consumed, retry allowed
async def test_create_5xx_consumes_4xx_does_not(sandbox):
    mock = sandbox
    a, b, c = await seed(_model(f"{TAG}-r11a", 0), _model(f"{TAG}-r11b", 1), _model(f"{TAG}-r11c", 2))
    mock.fail_create, mock.fail_create_status = True, 502
    r = await engine.run("PUBLISH_NOW", "test")
    assert r["status"] == "FEED_UNVERIFIED" and r["FEED_CONSUMED"] is True and r["model_slug"] == a["slug"]
    cyc = r["cycle_number"]
    mock.fail_create = False
    r2 = await engine.run("PUBLISH_NOW", "test")
    assert r2["model_slug"] == b["slug"] and len(mock.posts) == 1                                  # A never re-created in this cycle
    mock.fail_create, mock.fail_create_status = True, 422
    r3 = await engine.run("PUBLISH_NOW", "test")
    assert r3["status"] == "FAILED" and r3["model_slug"] == c["slug"] and (await engine.get_run(c["id"], cyc))["feed_consumed"] is False
    mock.fail_create = False
    r4 = await engine.run("PUBLISH_NOW", "test")
    assert r4["model_slug"] == c["slug"] and r4["status"] == "MOCK_CONFIRMED"                     # retry allowed after a definitive 4xx
    assert (await engine.get_run(a["id"], cyc))["feed_status"] == "UNVERIFIED" and await engine.log_col.count_documents({"model_id": a["id"], "cycle_number": cyc}) == 1


# reconcile (production repair): existing post becomes the canonical consumed feed; duplicate recorded; DM stays PENDING; queue -> next model
async def test_reconcile_feed_db_only(sandbox, monkeypatch):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-rca", 0), _model(f"{TAG}-rcb", 1))
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "false")
    r = await engine.run("PUBLISH_NOW", "test")                                                   # feed exists on the provider
    pid = r["provider_post_id"]
    dup = await engine.run("PUBLISH_NOW", "test")                                                 # (B) just to have another existing post id to mark as duplicate
    await engine.runs_col.delete_many({"model_id": a["id"]})                                      # simulate the legacy state: no run for A, A back as candidate
    await engine.set_state(cycle_done=[], last_position=0)
    monkeypatch.setenv("OF_MASS_DM_ENABLED", "true")
    writes = mock.write_calls
    rc = await engine.reconcile_feed(a["slug"], pid, duplicate_post_ids=[dup["provider_post_id"], "missing-post"], slot_id="of_x_09:30", trigger="test")
    assert rc["status"] == "RECONCILED" and rc["CANONICAL_FEED_POST_ID"] == pid and rc["FEED_CONSUMED"] is True and rc["MASS_DM_STATUS"] == "PENDING" and rc["writes"] == 0
    assert rc["duplicates"][0] == {**rc["duplicates"][0], "post_id": dup["provider_post_id"], "status": "DUPLICATE_EXISTING", "exists": True} and rc["duplicates"][1]["exists"] is False
    assert rc["NEXT_FEED_MODEL"] == b["slug"] and mock.write_calls == writes
    run = await engine.get_run(a["id"], rc["cycle_number"])
    assert run["feed_status"] == "OK" and run["feed_consumed"] is True and run["canonical_feed_post_id"] == pid and len(run["feed_media_ids"]) == 2
    assert (await engine.reconcile_feed(b["slug"], pid, trigger="test"))["error_code"] == "OF_LINK_NOT_IN_POST"                    # wrong model -> refused
    assert (await engine.reconcile_feed(a["slug"], "nope", trigger="test"))["status"] == "FAILED"
    # the DM queue now serves A (DM-only from the canonical post), never a new feed
    d = await engine.run_dm_only("test", model_slug=a["slug"])
    assert d["status"] == "DM_OK" and d["provider_post_id"] == pid and mock.mass_messages[-1]["mediaFiles"] == [str(m["id"]) for m in mock.posts[pid]["media"]]
    assert await engine.log_col.count_documents({"model_id": a["id"], "status": "MOCK_CONFIRMED"}) == 1
