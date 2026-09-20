"""Scheduler registration (existing v1_jobs): x_autopilot_tick every 5 minutes; no-op unless X_AUTO_SCHEDULER_ENABLED=true
AND enabled in DB AND adapter operational (mock while not connected)."""
from v1_jobs import job

from . import engine


@job("x_autopilot_tick", 300, "X Autopilot: pubblica lo slot dovuto (idempotente, lock DB)")
async def j_tick():
    r = await engine.tick()
    return {k: v for k, v in r.items() if k in ("status", "error_code", "model_slug", "x_post_id", "slot_id", "format")}
