"""Admin API /api/admin/of-autopilot/* (existing admin JWT). Never returns credentials. No route can enable real posting."""
import asyncio
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_admin

from . import connection, engine

router = APIRouter(prefix="/api/admin/of-autopilot", tags=["OnlyFans Autopilot"])


class MassDmTest(BaseModel):
    model_slug: str
    provider_post_id: str
    execute: bool = False               # False = READ-ONLY dry run (pre-checks + copy preview). True = the ONE real/mock mass message
    background: bool = False            # True = run the execute in a background task (the real send can take minutes) and poll GET /mass-dm-test/{post_id}


class Settings(BaseModel):
    posts_per_day: Optional[int] = Field(None, ge=1, le=12)
    schedule_times: Optional[List[str]] = None
    timezone: Optional[str] = None
    use_ai_copy: Optional[bool] = None


@router.get("/connection")
async def get_connection(admin=Depends(get_current_admin)):
    return await connection.status(refresh=False)


@router.post("/test-connection")
async def test_connection(admin=Depends(get_current_admin)):
    """READ-ONLY discovery again (whoami, accounts, polling, users/me, schedules)."""
    return await connection.status(refresh=True)


@router.get("/status")
async def status(admin=Depends(get_current_admin)):
    return await engine.status()


@router.get("/preview")
async def preview(admin=Depends(get_current_admin)):
    return await engine.preview()


@router.post("/start")
async def start(admin=Depends(get_current_admin)):
    ready = await engine.readiness()
    if not ready["operational"]:
        raise HTTPException(409, f"OF Autopilot non operativo: {ready['reason']}")
    await engine.set_state(enabled=True, activated_at=engine.now_iso())          # NO catch-up: only slots strictly after this instant are ever prepared
    st = await engine.get_state()
    sch = await engine.schedule_view(st)
    await engine.set_state(next_run=(sch["next_slot"] or {}).get("at"))
    return {"enabled": True, "AUTO_SCHEDULER_ENABLED": engine.auto_scheduler_enabled(), "MOCK_MODE": engine.mock_enabled(), "activated_at": st.get("activated_at"),
            "CATCH_UP_ENABLED": False, "IMMEDIATE_RUN_TRIGGERED": False, "next_run": (sch["next_slot"] or {}).get("at"),
            "note": None if engine.auto_scheduler_enabled() else "Master switch OF_AUTO_SCHEDULER_ENABLED=false: lo scheduler resta fermo"}


@router.post("/pause")
async def pause(admin=Depends(get_current_admin)):
    await engine.set_state(enabled=False)
    return {"enabled": False}


@router.post("/publish-now")
async def publish_now(admin=Depends(get_current_admin)):
    """PUBBLICA ORA = immediate post (MOCK in this phase). Never schedules to the next slot."""
    ready = await engine.readiness()
    if not ready["operational"]:
        raise HTTPException(409, f"OF Autopilot non operativo: {ready['reason']}")
    r = await engine.run("PUBLISH_NOW", "admin")
    if r.get("status") == "LOCKED":
        raise HTTPException(409, "Pubblicazione già in corso")
    return r


@router.post("/mass-dm-test")
async def mass_dm_test(body: MassDmTest, admin=Depends(get_current_admin)):
    """DM-only test from an EXISTING confirmed feed post: never a new feed, never another model, hard cap 1 real mass DM, gate restored in finally."""
    if body.execute and body.background:
        if str(body.provider_post_id) in engine.MASS_DM_JOBS and not engine.MASS_DM_JOBS[str(body.provider_post_id)].get("finished_at"):
            raise HTTPException(409, "Invio già in corso")
        engine.MASS_DM_JOBS[str(body.provider_post_id)] = {"status": "RUNNING", "started_at": engine.now_iso()}
        asyncio.create_task(engine.mass_dm_from_post_background(body.model_slug.strip().lower(), body.provider_post_id, "admin"))
        return {"status": "STARTED", "poll": f"/api/admin/of-autopilot/mass-dm-test/{body.provider_post_id}"}
    r = await engine.mass_dm_from_post(body.model_slug.strip().lower(), body.provider_post_id, execute=body.execute, trigger="admin")
    if r.get("status") == "LOCKED":
        raise HTTPException(409, "Pubblicazione già in corso")
    return r


class CloseRun(BaseModel):
    reason: str = "MASS_DM_READBACK_CONFIRMED"


@router.post("/mass-dm-test/{post_id}/close")
async def mass_dm_close(post_id: str, body: CloseRun, admin=Depends(get_current_admin)):
    """Admin decision, ZERO provider writes: a mass DM left UNVERIFIED (provider error after the send) but confirmed by real read-back is closed as OK.
    Keeps provider_response / error history and the duplicate protection (marker stays)."""
    r = await engine.close_mass_dm_run(post_id, body.reason, trigger="admin")
    if r.get("status") == "NOT_FOUND":
        raise HTTPException(404, "Run non trovata")
    return r


@router.get("/mass-dm-test/{post_id}")
async def mass_dm_test_status(post_id: str, admin=Depends(get_current_admin)):
    """READ-ONLY: outcome of a (background) mass-dm-test for a post + the durable of_model_runs state."""
    return await engine.mass_dm_job_view(post_id)


@router.post("/skip")
async def skip(admin=Depends(get_current_admin)):
    return await engine.skip_current("admin")


@router.patch("/settings")
async def settings(body: Settings, admin=Depends(get_current_admin)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if not upd:
        raise HTTPException(422, "nessuna impostazione")
    st = await engine.get_state()
    if "schedule_times" in upd:
        for t in upd["schedule_times"]:
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t or ""):
                raise HTTPException(422, f"orario non valido: {t}")
        upd["schedule_times"] = sorted(set(upd["schedule_times"]))
        upd.setdefault("posts_per_day", len(upd["schedule_times"]))
    if "timezone" in upd:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(upd["timezone"])
        except Exception:
            raise HTTPException(422, "timezone non valida")
    if "posts_per_day" in upd and upd["posts_per_day"] > len(upd.get("schedule_times", st["schedule_times"])):
        raise HTTPException(422, f"servono {upd['posts_per_day']} orari")
    await engine.set_state(**upd)
    st = await engine.get_state()
    return {k: st[k] for k in ("posts_per_day", "schedule_times", "timezone", "use_ai_copy")}


@router.get("/logs")
async def logs(limit: int = Query(50, le=300), admin=Depends(get_current_admin)):
    return {"items": [x async for x in engine.log_col.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)]}


@router.get("/uploads")
async def uploads(limit: int = Query(50, le=300), admin=Depends(get_current_admin)):
    return {"items": [x async for x in engine.uploads_col.find({}, {"_id": 0, "provider_media_object": 0}).sort("created_at", -1).limit(limit)]}
