"""Scheduler registration (existing v1_jobs): one tick every 5 minutes; no-op unless INSTAGRAM_AUTO_SCHEDULER_ENABLED=true
AND enabled in DB AND connection is CONNECTED (or MOCK while not connected)."""
from v1_jobs import job

from . import engine


@job("instagram_autopilot_tick", 300, "Instagram Autopilot: pubblica lo slot dovuto (idempotente, lock DB)")
async def j_tick():
    r = await engine.tick()
    return {k: v for k, v in r.items() if k in ("status", "error_code", "model_slug", "ig_media_id", "slot_id")}
