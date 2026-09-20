"""Admin API /api/admin/of-autopilot/* — READ-ONLY in this phase. Never returns credentials."""
from fastapi import APIRouter, Depends

from auth import get_current_admin

from . import connection

router = APIRouter(prefix="/api/admin/of-autopilot", tags=["OnlyFans Autopilot"])


@router.get("/connection")
async def get_connection(admin=Depends(get_current_admin)):
    return await connection.status(refresh=False)


@router.post("/test-connection")
async def test_connection(admin=Depends(get_current_admin)):
    """Runs the READ-ONLY discovery again (whoami, accounts, polling, users/me, schedules)."""
    return await connection.status(refresh=True)
