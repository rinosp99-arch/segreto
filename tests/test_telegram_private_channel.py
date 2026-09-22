"""Telegram Autopilot — PRIVATE CHANNEL fix (numeric chat_id override) tests. Env-independent (forced mock client)."""
import os
import sys
import pytest

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from telegram_autopilot import client as tg  # noqa: E402
from telegram_autopilot import engine  # noqa: E402

pytestmark = pytest.mark.anyio
NUM = "-1001234567890"


async def test_resolved_target_prefers_numeric_override():
    before = await engine.get_state()
    try:
        await engine.set_state(channel_id=None, private_channel_mode=False)
        assert (await engine.resolved_target()) == (tg.channel() or "").strip()   # falls back to env
        await engine.set_state(channel_id=NUM, private_channel_mode=True)
        assert (await engine.resolved_target()) == NUM                            # numeric override wins
    finally:
        await engine.set_state(channel_id=before.get("channel_id"), private_channel_mode=bool(before.get("private_channel_mode")))


async def test_status_reports_private_numeric_target():
    before = await engine.get_state()
    prev_mock = os.environ.get("TELEGRAM_AUTOPILOT_MOCK")
    os.environ["TELEGRAM_AUTOPILOT_MOCK"] = "true"
    tg.force_client(tg.MockTelegram())
    try:
        await engine.set_state(channel_id=NUM, private_channel_mode=True)
        st = await engine.status()
        assert st["channel"] == NUM
        assert st["TELEGRAM_CHAT_ID"] == NUM
        assert st["TELEGRAM_TARGET_TYPE"] == "NUMERIC_CHAT_ID"
        assert st["TELEGRAM_PRIVATE_CHANNEL_MODE"] is True
        # mock connection resolves the numeric id as an admin channel that can post
        conn = await tg.connection_status(chat_id=NUM)
        assert conn["TELEGRAM_CONNECTION_STATUS"] == "CONNECTED"
        assert (conn["chat"] or {}).get("type") == "channel"
        assert conn["bot_is_admin"] is True and conn["can_post"] is True
    finally:
        tg.force_client(None)
        if prev_mock is None:
            os.environ.pop("TELEGRAM_AUTOPILOT_MOCK", None)
        else:
            os.environ["TELEGRAM_AUTOPILOT_MOCK"] = prev_mock
        await engine.set_state(channel_id=before.get("channel_id"), private_channel_mode=bool(before.get("private_channel_mode")))


async def test_resolve_channels_via_updates_shape():
    prev_mock = os.environ.get("TELEGRAM_AUTOPILOT_MOCK")
    os.environ["TELEGRAM_AUTOPILOT_MOCK"] = "true"
    tg.force_client(tg.MockTelegram())
    try:
        res = await tg.resolve_channels_via_updates()
        assert set(["ok", "channels", "count"]).issubset(res.keys())
    finally:
        tg.force_client(None)
        if prev_mock is None:
            os.environ.pop("TELEGRAM_AUTOPILOT_MOCK", None)
        else:
            os.environ["TELEGRAM_AUTOPILOT_MOCK"] = prev_mock


async def test_default_state_has_private_channel_fields():
    assert "channel_id" in engine.DEFAULTS and "private_channel_mode" in engine.DEFAULTS
