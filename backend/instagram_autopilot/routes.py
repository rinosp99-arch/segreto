"""Admin API /api/admin/instagram-autopilot/* (existing admin JWT). No Meta credentials are ever returned."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_admin

from . import adapter as meta
from . import engine

router = APIRouter(prefix="/api/admin/instagram-autopilot", tags=["Instagram Autopilot"])


class Settings(BaseModel):
    posts_per_day: Optional[int] = Field(None, ge=1, le=12)
    schedule_times: Optional[List[str]] = None
    timezone: Optional[str] = None
    use_photo: Optional[bool] = None
    use_video: Optional[bool] = None
    use_ai_copy: Optional[bool] = None


@router.get("/status")
async def status(admin=Depends(get_current_admin)):
    return await engine.status()


@router.post("/test-connection")
async def test_connection(admin=Depends(get_current_admin)):
    return await meta.connection_status()


@router.post("/start")
async def start(admin=Depends(get_current_admin)):
    conn = await meta.connection_status()
    if not conn["operational"]:
        raise HTTPException(409, f"Instagram non connesso: {conn['CONNECTION_STATUS']}")
    await engine.set_state(enabled=True)
    return {"enabled": True, "AUTO_SCHEDULER_ENABLED": engine.auto_scheduler_enabled(), "mock": meta.mock_enabled(), "MOCK_MODE": meta.mock_enabled(), "CONNECTION_STATUS": conn["CONNECTION_STATUS"],
            "note": None if engine.auto_scheduler_enabled() else "Master switch INSTAGRAM_AUTO_SCHEDULER_ENABLED=false: lo scheduler resta fermo"}


@router.post("/pause")
async def pause(admin=Depends(get_current_admin)):
    await engine.set_state(enabled=False)
    return {"enabled": False}


@router.post("/publish-now")
async def publish_now(dry_run: bool = False, admin=Depends(get_current_admin)):
    conn = await meta.connection_status()
    if not conn["operational"] and not dry_run:
        raise HTTPException(409, f"Instagram non connesso: {conn['CONNECTION_STATUS']}")
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
    if "schedule_times" in upd:
        for t in upd["schedule_times"]:
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t or ""):
                raise HTTPException(422, f"orario non valido: {t}")
        upd["schedule_times"] = sorted(set(upd["schedule_times"]))
        upd.setdefault("posts_per_day", len(upd["schedule_times"]))
    if "timezone" in upd:
        from zoneinfo import ZoneInfo
        from .caption import italy_mode
        try:
            ZoneInfo(upd["timezone"])
        except Exception:
            raise HTTPException(422, "timezone non valida")
        if italy_mode() and upd["timezone"] != "Europe/Rome":
            raise HTTPException(422, "ITALY_AUDIENCE_MODE attivo: timezone obbligatoria Europe/Rome")
    if "posts_per_day" in upd:
        st = await engine.get_state()
        times = upd.get("schedule_times", st["schedule_times"])
        if upd["posts_per_day"] > len(times):
            raise HTTPException(422, f"servono {upd['posts_per_day']} orari, ne hai {len(times)}")
    if not upd:
        raise HTTPException(422, "nessuna impostazione")
    await engine.set_state(**upd)
    st = await engine.get_state()
    return {k: st[k] for k in ("posts_per_day", "schedule_times", "timezone", "use_photo", "use_video", "use_ai_copy")}


@router.get("/logs")
async def logs(limit: int = Query(50, le=300), admin=Depends(get_current_admin)):
    return {"items": [x async for x in engine.log_col.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)]}
