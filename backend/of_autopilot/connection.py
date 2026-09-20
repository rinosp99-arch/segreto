"""READ-ONLY connection service: discovery of the single expected OnlyFans account, health, schedules access.
Persists the discovered of_user_id server-side (collection of_autopilot_connection) — never the API key.
STOP rule: if the panel does not contain exactly one OnlyFans account named EXPECTED_USERNAME -> ACCOUNT_MISMATCH / AMBIGUOUS_ACCOUNTS."""
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db

from .providers.base import OFProviderAdapter, OFProviderError
from .providers import the_only_api as toa

conn_col = db["of_autopilot_connection"]
EXPECTED_USERNAME = os.environ.get("OF_EXPECTED_USERNAME", "latosegreto").strip().lower()
EXPECTED_PLATFORM = "onlyfans"
_forced: Optional[OFProviderAdapter] = None


def provider_name() -> str:
    return os.environ.get("OF_PROVIDER", "the_only_api").strip().lower()


def connection_enabled() -> bool:
    return os.environ.get("OF_CONNECTION_ENABLED", "true").lower() in ("1", "true", "yes")


def real_posting_enabled() -> bool:
    return toa.writes_enabled()


def auto_scheduler_enabled() -> bool:
    return os.environ.get("OF_AUTO_SCHEDULER_ENABLED", "false").lower() in ("1", "true", "yes")


def get_adapter() -> OFProviderAdapter:
    if _forced is not None:
        return _forced
    if provider_name() == "the_only_api":
        return toa.TheOnlyAPIAdapter()
    raise OFProviderError("NOT_CONFIGURED", f"OF_PROVIDER sconosciuto: {provider_name()}")


def force_adapter(a: Optional[OFProviderAdapter]):
    global _forced
    _forced = a


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _mask_id(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    return v if len(v) <= 4 else f"{'*' * (len(v) - 3)}{v[-3:]}"


async def saved() -> Dict[str, Any]:
    return await conn_col.find_one({"id": "global"}, {"_id": 0}) or {}


async def of_user_id() -> Optional[str]:
    """Auto-discovered id: server-side state first, then env THE_ONLY_OF_USER_ID (never asked to the user)."""
    st = await saved()
    return st.get("of_user_id") or (os.environ.get("THE_ONLY_OF_USER_ID") or "").strip() or None


async def discover(check_schedules: bool = True) -> Dict[str, Any]:
    """All READ-ONLY. Returns the public-safe connection document and persists it."""
    doc: Dict[str, Any] = {"id": "global", "PROVIDER": "THE_ONLY_API" if provider_name() == "the_only_api" else provider_name().upper(), "CONNECTION_STATUS": "NOT_CONNECTED", "ACCOUNT_STATUS": "UNKNOWN",
                           "ACCOUNT_USERNAME": None, "PLATFORM": None, "of_user_id": None, "of_user_id_masked": None, "key_valid": False, "crm_scope": False,
                           "schedules_read": None, "scheduled_count_sample": None, "write_actions_allowed": None, "error": None, "checked_at": now_iso(),
                           "OF_REAL_POSTING_ENABLED": real_posting_enabled(), "OF_AUTO_SCHEDULER_ENABLED": auto_scheduler_enabled(), "OF_REAL_WRITE_CALLS": toa.CALLS["write"]}
    if not connection_enabled():
        doc["error"] = "OF_CONNECTION_ENABLED=false"
        return await _persist(doc)
    if not toa.configured():
        doc["error"] = "credenziali provider assenti"
        return await _persist(doc)
    adapter = get_adapter()
    try:
        tc = await adapter.test_connection()                                   # whoami + accounts
        doc["key_valid"], doc["crm_scope"] = True, bool(tc.get("crm_scope"))
        accounts = await adapter.list_accounts()
        of_accounts = [a for a in accounts if a.platform == EXPECTED_PLATFORM]
        matches = [a for a in of_accounts if a.username.lower() == EXPECTED_USERNAME]
        doc["accounts_seen"] = [{"username": a.username, "platform": a.platform} for a in accounts]
        if len(matches) != 1 or len(of_accounts) != 1:
            doc["CONNECTION_STATUS"] = "ERROR"
            doc["error"] = "AMBIGUOUS_ACCOUNTS" if len(of_accounts) > 1 or len(matches) > 1 else "ACCOUNT_MISMATCH"
            return await _persist(doc)                                        # STOP: no further action
        acc = matches[0]
        doc.update({"CONNECTION_STATUS": "CONNECTED", "ACCOUNT_USERNAME": acc.username, "PLATFORM": acc.platform, "of_user_id": acc.of_user_id, "of_user_id_masked": _mask_id(acc.of_user_id)})
        health = await adapter.get_account_health(acc.of_user_id)
        doc["ACCOUNT_STATUS"] = health.status
        doc["write_actions_allowed"] = health.write_actions_allowed
        doc["health_detail"] = health.detail
        if health.username and health.username.lower() != EXPECTED_USERNAME:
            doc["ACCOUNT_STATUS"], doc["error"] = "UNHEALTHY", "ACCOUNT_MISMATCH (sessione live)"
        if check_schedules:
            try:
                page = await adapter.get_scheduled_posts(acc.of_user_id, limit=10, offset=0)
                doc["schedules_read"], doc["scheduled_count_sample"] = True, len(page.get("list") or [])
            except OFProviderError as e:
                doc["schedules_read"], doc["error"] = False, f"schedules: {e.code}"
    except OFProviderError as e:
        doc["CONNECTION_STATUS"] = "NOT_CONNECTED" if e.code in ("UNAUTHORIZED", "NOT_CONFIGURED") else "ERROR"
        doc["error"] = e.code
    doc["OF_REAL_WRITE_CALLS"] = toa.CALLS["write"]
    return await _persist(doc)


async def _persist(doc: Dict[str, Any]) -> Dict[str, Any]:
    await conn_col.update_one({"id": "global"}, {"$set": {**doc, "updated_at": now_iso()}}, upsert=True)
    return public_view(doc)


def public_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    """What Admin/API may see: no credentials, of_user_id masked."""
    return {"PROVIDER": "The Only API" if doc.get("PROVIDER") == "THE_ONLY_API" else doc.get("PROVIDER"), "CONNECTION_STATUS": doc.get("CONNECTION_STATUS", "NOT_CONNECTED"),
            "ACCOUNT_STATUS": doc.get("ACCOUNT_STATUS", "UNKNOWN"), "ACCOUNT_USERNAME": doc.get("ACCOUNT_USERNAME"), "PLATFORM": doc.get("PLATFORM"),
            "OF_USER_ID_DISCOVERED": bool(doc.get("of_user_id")), "of_user_id_masked": doc.get("of_user_id_masked"), "key_valid": doc.get("key_valid", False), "crm_scope": doc.get("crm_scope", False),
            "schedules_read": doc.get("schedules_read"), "scheduled_count_sample": doc.get("scheduled_count_sample"), "write_actions_allowed": doc.get("write_actions_allowed"),
            "REAL_POSTING": "ON" if real_posting_enabled() else "OFF", "AUTO_SCHEDULER": "ON" if auto_scheduler_enabled() else "OFF",
            "OF_REAL_POSTING_ENABLED": real_posting_enabled(), "OF_AUTO_SCHEDULER_ENABLED": auto_scheduler_enabled(), "OF_REAL_WRITE_CALLS": toa.CALLS["write"],
            "error": doc.get("error"), "checked_at": doc.get("checked_at")}


async def status(refresh: bool = False) -> Dict[str, Any]:
    st = await saved()
    if refresh or not st:
        return await discover()
    return public_view(st)
