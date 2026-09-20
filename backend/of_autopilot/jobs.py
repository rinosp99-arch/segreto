"""Scheduler registration (existing v1_jobs): of_autopilot_tick every 5 minutes; no-op unless OF_AUTO_SCHEDULER_ENABLED=true
AND enabled in DB AND readiness (MOCK, or CONNECTED+HEALTHY+OF_REAL_POSTING_ENABLED)."""
from v1_jobs import job

from . import engine


@job("of_autopilot_tick", 300, "OnlyFans Autopilot: programma lo slot dovuto (idempotente, lock DB, verify schedule)")
async def j_tick():
    r = await engine.tick()
    return {k: v for k, v in r.items() if k in ("status", "error_code", "model_slug", "provider_post_id", "slot_id")}
