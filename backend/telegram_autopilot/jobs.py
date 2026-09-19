"""Scheduler registration in the existing v1_jobs scheduler: one tick every 5 minutes; the tick itself is a no-op unless
TELEGRAM_AUTO_SCHEDULER_ENABLED=true (env master switch) AND the admin enabled the autopilot AND Telegram is CONNECTED."""
from v1_jobs import job

from . import engine


@job("telegram_autopilot_tick", 300, "Telegram Autopilot: pubblica lo slot dovuto (idempotente, lock DB)")
async def j_tick():
    r = await engine.tick()
    return {k: v for k, v in r.items() if k in ("status", "error_code", "model_slug", "message_id", "slot_id")}
