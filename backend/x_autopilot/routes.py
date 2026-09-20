"""Admin API /api/admin/x-autopilot/* (existing admin JWT). No X credentials are ever returned."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_admin

from . import adapter as xapi
from . import engine

router = APIRouter(prefix="/api/admin/x-autopilot", tags=["X Autopilot"])
SETTING_KEYS = ("posts_per_day", "schedule_times", "timezone", "use_ai_copy", "italy_audience_mode")


class Settings(BaseModel):
    posts_per_day: Optional[int] = Field(None, ge=1, le=12)
    schedule_times: Optional[List[str]] = None
    timezone: Optional[str] = None
    use_ai_copy: Optional[bool] = None
    italy_audience_mode: Optional[bool] = None


@router.get("/status")
async def status(admin=Depends(get_current_admin)):
    return await engine.status()


@router.post("/test-connection")
async def test_connection(admin=Depends(get_current_admin)):
    return await xapi.connection_status()


@router.post("/start")
async def start(admin=Depends(get_current_admin)):
    conn = await xapi.connection_status()
    if not conn["operational"]:
        raise HTTPException(409, f"X non connessa: {conn['CONNECTION_STATUS']}")
    await engine.set_state(enabled=True)
    return {"enabled": True, "AUTO_SCHEDULER_ENABLED": engine.auto_scheduler_enabled(), "MOCK_MODE": xapi.mock_enabled(), "CONNECTION_STATUS": conn["CONNECTION_STATUS"],
            "note": None if engine.auto_scheduler_enabled() else "Master switch X_AUTO_SCHEDULER_ENABLED=false: lo scheduler resta fermo"}


@router.post("/pause")
async def pause(admin=Depends(get_current_admin)):
    await engine.set_state(enabled=False)
    return {"enabled": False}


@router.post("/preview")
async def preview(admin=Depends(get_current_admin)):
    return await engine.preview()


@router.post("/publish-now")
async def publish_now(dry_run: bool = False, admin=Depends(get_current_admin)):
    conn = await xapi.connection_status()
    if not conn["operational"] and not dry_run:
        raise HTTPException(409, f"X non connessa: {conn['CONNECTION_STATUS']}")
    r = await engine.publish_next("admin", dry_run=dry_run)
    if r.get("status") == "LOCKED":
        raise HTTPException(409, "Pubblicazione già in corso")
    return r


@router.post("/skip")
async def skip(admin=Depends(get_current_admin)):
    return await engine.skip_current("admin")


@router.patch("/settings")
async def settings(body: Settings, admin=Depends(get_current_admin)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if not upd:
        raise HTTPException(422, "nessuna impostazione")
    st = await engine.get_state()
    italy = upd.get("italy_audience_mode", engine.italy_mode(st))
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
    tz = upd.get("timezone", st["timezone"])
    if italy and tz != "Europe/Rome":
        if "timezone" in upd:
            raise HTTPException(422, "ITALY_AUDIENCE_MODE attivo: timezone obbligatoria Europe/Rome")
        upd["timezone"] = "Europe/Rome"                     # turning Italy mode on re-aligns the timezone
    if "posts_per_day" in upd:
        times = upd.get("schedule_times", st["schedule_times"])
        if upd["posts_per_day"] > len(times):
            raise HTTPException(422, f"servono {upd['posts_per_day']} orari, ne hai {len(times)}")
    await engine.set_state(**upd)
    st = await engine.get_state()
    return {**{k: st[k] for k in SETTING_KEYS if k != "italy_audience_mode"}, "italy_audience_mode": engine.italy_mode(st)}


@router.get("/logs")
async def logs(limit: int = Query(50, le=300), admin=Depends(get_current_admin)):
    return {"items": [x async for x in engine.log_col.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)]}
