"""OnlyFans Autopilot — FEED-ONLY mode tests (Mass DM fully disabled; feed rotation intact)."""
import sys
import pytest

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from of_autopilot import engine  # noqa: E402

pytestmark = pytest.mark.anyio


async def test_feed_only_flag_roundtrip_and_gates():
    before = await engine.get_state()
    prev = bool(before.get("feed_only_mode"))
    try:
        await engine.set_state(feed_only_mode=True)
        assert await engine.feed_only() is True
        # DM retry queue is frozen
        r = await engine.process_dm_queue("test")
        assert r and r.get("status") == "FEED_ONLY_MODE" and r.get("dm_disabled") is True
        # manual DM-only is blocked
        m = await engine.run_dm_only("test")
        assert m.get("status") == "BLOCKED" and m.get("error_code") == "FEED_ONLY_MODE"
        # status exposes the flags
        st = await engine.status()
        assert st["FEED_ONLY_MODE"] is True
        assert st["MASS_DM_AUTOPILOT_ENABLED"] is False
        assert st["DM_RETRY_ENABLED"] is False
        # turning it off re-enables the manual path (still subject to normal guards / empty queue)
        await engine.set_state(feed_only_mode=False)
        assert await engine.feed_only() is False
    finally:
        await engine.set_state(feed_only_mode=prev)


async def test_default_state_has_feed_only_flag():
    assert "feed_only_mode" in engine.DEFAULTS
