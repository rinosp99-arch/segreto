"""SEO_AUTOPILOT_MODE: OFF | READ_ONLY | FULL.

- OFF        : the engine does nothing (jobs return immediately).
- READ_ONLY  : analyses everything, writes ONLY to its own seo_ap_* collections, never to public resources.
- FULL       : future. LOCKED in this phase: `FULL_LOCKED = True` makes FULL impossible to activate, even if the env says so
               (the mode degrades to READ_ONLY and the downgrade is recorded). Every write action goes through `require_full()`.
"""
import os

MODES = ("OFF", "READ_ONLY", "FULL")
FULL_LOCKED = True            # phase 14: FULL cannot be enabled by configuration. Flip only in a future, reviewed release.


class WriteBlocked(Exception):
    """Raised by any public write action while SEO_AUTOPILOT_MODE != FULL."""


def configured_mode() -> str:
    """Raw value from the environment (default READ_ONLY)."""
    v = (os.environ.get("SEO_AUTOPILOT_MODE") or "READ_ONLY").strip().upper()
    return v if v in MODES else "READ_ONLY"


def current_mode() -> str:
    """Effective mode. FULL is downgraded to READ_ONLY while FULL_LOCKED."""
    m = configured_mode()
    if m == "FULL" and FULL_LOCKED:
        return "READ_ONLY"
    return m


def mode_info() -> dict:
    m = configured_mode()
    return {"mode": current_mode(), "configured": m, "full_locked": FULL_LOCKED,
            "downgraded": m == "FULL" and FULL_LOCKED, "can_write_public": current_mode() == "FULL"}


def is_off() -> bool:
    return current_mode() == "OFF"


def require_full(action: str):
    """Guard for EVERY public write action (create landing, update metadata, internal links, sitemap, contents...).
    Raises WriteBlocked unless the effective mode is FULL."""
    if current_mode() != "FULL":
        raise WriteBlocked(f"Azione '{action}' bloccata: SEO_AUTOPILOT_MODE={current_mode()} (richiesto FULL; FULL_LOCKED={FULL_LOCKED})")


def write_action(action: str):
    """Decorator for future FULL-mode executors: the body never runs outside FULL."""
    def deco(fn):
        async def wrapper(*a, **kw):
            require_full(action)
            return await fn(*a, **kw)
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return deco
