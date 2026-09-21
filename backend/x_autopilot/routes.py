"""Admin API /api/admin/x-autopilot/* (existing admin JWT). No X credentials are ever returned."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from auth import get_current_admin

from . import adapter as xapi
from . import engine, realtest, xauth

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


# ------------------------------------------------------------------ REAL X connection (READ-ONLY checks + OAuth 1.0a 3-legged). No token is ever returned.
@router.get("/connection")
async def connection(live: bool = True, admin=Depends(get_current_admin)):
    """READ-ONLY: app auth (oauth2/token), user auth + identity (GET /2/users/me), write capability (x-access-level), sample media pre-check. Never posts."""
    sample = None
    try:
        p = await engine.preview()
        if p.get("public") and p.get("secret"):
            sample = [p["public"], p["secret"]]
    except Exception:                                            # noqa: BLE001 — preview problems must not hide the connection report
        sample = None
    return await xapi.real_connection_report(live=live, sample_media=sample)


@router.post("/auth/start")
async def auth_start(request: Request, admin=Depends(get_current_admin)):
    """OAuth 1.0a step 1: request token -> authorize URL (the admin opens it; X redirects to /auth/callback)."""
    cb = xauth.callback_url(dict(request.headers))
    try:
        r = await xauth.start_user_auth(cb)
    except xauth.XAuthError as e:
        detail = {"error": e.code, "detail": e.description, "callback": cb}
        if e.code == "CALLBACK_NOT_APPROVED":
            detail["MISSING_MANUAL_STEP"] = xauth.MANUAL_STEP_USER_AUTH.replace("<callback>", cb)
        raise HTTPException(409, detail)
    return {"status": "AUTHORIZE_URL_READY", **r}


@router.get("/auth/callback")
async def auth_callback(oauth_token: Optional[str] = None, oauth_verifier: Optional[str] = None, denied: Optional[str] = None):
    """OAuth 1.0a step 3 (X redirects the browser here, no JWT): validate pending token, exchange, store encrypted, verify identity, redirect to the admin page."""
    if denied or not (oauth_token and oauth_verifier):
        return RedirectResponse(url="/admin/x-autopilot?x_auth=denied", status_code=302)
    try:
        r = await xauth.finish_user_auth(oauth_token, oauth_verifier)
    except xauth.XAuthError as e:
        return RedirectResponse(url=f"/admin/x-autopilot?x_auth=error&code={e.code}", status_code=302)
    return RedirectResponse(url=f"/admin/x-autopilot?x_auth={'ok' if r.get('status') == 'CONNECTED' else 'saved'}&user={r.get('X_USERNAME') or ''}", status_code=302)


# ------------------------------------------------------------------ FIRST CONTROLLED REAL POST (hard cap 1, idempotent, READ-verified)
@router.post("/real-test")
async def real_test(execute: bool = False, admin=Depends(get_current_admin)):
    """execute=false -> READ-ONLY dry run (gates, account, credits probe, candidate PHOTO+PHOTO, media pre-check, copy). execute=true -> the ONE real post."""
    r = await realtest.real_test_post("admin", execute=execute)
    if r.get("status") == "LOCKED":
        raise HTTPException(409, "Pubblicazione già in corso")
    return r


@router.get("/real-test")
async def real_test_last(admin=Depends(get_current_admin)):
    return {"last_run": await realtest.last_run(), "REAL_X_POSTS_CREATED": await xapi.real_posts_created(), "runs_started": await realtest.real_runs_started()}


@router.post("/real-test/verify")
async def real_test_verify(admin=Depends(get_current_admin)):
    """READ-ONLY re-verification of the last real run (never resends)."""
    return await realtest.verify_last("admin")


@router.get("/auth/status")
async def auth_status(admin=Depends(get_current_admin)):
    """No X call: is a user token stored? which account (saved identity)? pending authorization?"""
    pend = await xauth.auth_col.find_one({"id": "pending"}, {"_id": 0, "created_at": 1, "callback": 1})
    return {"X_USER_AUTH_PRESENT": await xauth.user_auth_present(), "identity": await xauth.saved_identity(), "pending": pend, "X_REAL_POSTING_ENABLED": xauth.real_posting_enabled(),
            "X_AUTOPILOT_MOCK": xapi.mock_enabled(), "REAL_X_POSTS_CREATED": await xapi.real_posts_created()}


@router.post("/auth/disconnect")
async def auth_disconnect(admin=Depends(get_current_admin)):
    return await xauth.disconnect()


@router.post("/start")
async def start(admin=Depends(get_current_admin)):
    conn = await xapi.connection_status()
    if not conn["operational"]:
        raise HTTPException(409, f"X non connessa: {conn['CONNECTION_STATUS']}")
    # Activation is DB-only: enabled + activated_at (no catch-up boundary) + next_run. NO run, NO tick, NO write here: the first post happens at the next FUTURE slot.
    await engine.set_state(enabled=True, activated_at=engine.now_iso())
    st = await engine.get_state()
    sch = await engine.schedule_view(st)
    await engine.set_state(next_run=(sch["next_slot"] or {}).get("at"))
    return {"enabled": True, "AUTO_SCHEDULER_ENABLED": engine.auto_scheduler_enabled(), "MOCK_MODE": xapi.mock_enabled(), "CONNECTION_STATUS": conn["CONNECTION_STATUS"],
            "activated_at": st.get("activated_at"), "next_run": (sch["next_slot"] or {}).get("at"), "CATCH_UP_ENABLED": False, "IMMEDIATE_RUN_TRIGGERED": False,
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
