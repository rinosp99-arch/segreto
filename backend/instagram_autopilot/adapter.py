"""Meta / Instagram Graph API adapter (prepared, NOT connected) + mock.

Future env (NOT required now, never hardcoded): INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_USER_ID, INSTAGRAM_APP_ID.
Publishing flow when connected: POST /{ig-user-id}/media (image_url | video_url + media_type=REELS, caption)
  -> poll status_code FINISHED -> POST /{ig-user-id}/media_publish (creation_id). Not executed in this phase.
META_REAL_CALLS counts every real HTTP call to graph.facebook.com (must stay 0 while not connected)."""
import os
from typing import Any, Dict, List, Optional

GRAPH = "https://graph.facebook.com/v21.0"
CAPTION_LIMIT = 2200
HASHTAG_LIMIT = 30
META_REAL_CALLS = {"n": 0}


def mock_enabled() -> bool:
    return os.environ.get("INSTAGRAM_AUTOPILOT_MOCK", "true").lower() in ("1", "true", "yes")


def credentials_present() -> bool:
    return bool(os.environ.get("INSTAGRAM_ACCESS_TOKEN") and os.environ.get("INSTAGRAM_USER_ID"))


def scrub(text: str) -> str:
    t = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    return (text or "").replace(t, "***TOKEN***") if t else (text or "")


class InstagramError(Exception):
    def __init__(self, code: str, description: str = ""):
        super().__init__(f"{code}: {scrub(description)}")
        self.code, self.description = code, scrub(description)


class MetaAdapter:
    """Real adapter skeleton. Every method raises NOT_CONNECTED until credentials exist; even then publishing is a
    two-step container flow that we will enable in the 'Meta connection' phase."""

    async def check(self) -> dict:
        if not credentials_present():
            raise InstagramError("NOT_CONNECTED", "credenziali Meta assenti (INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID)")
        import httpx
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                META_REAL_CALLS["n"] += 1
                r = await c.get(f"{GRAPH}/{os.environ['INSTAGRAM_USER_ID']}", params={"fields": "id,username", "access_token": os.environ["INSTAGRAM_ACCESS_TOKEN"]})
            body = r.json()
        except Exception as e:
            raise InstagramError("API_ERROR", type(e).__name__)
        if "error" in body:
            err = body["error"]
            raise InstagramError("INVALID_TOKEN" if err.get("code") == 190 else "API_ERROR", err.get("message", ""))
        return {"id": body.get("id"), "username": body.get("username")}

    async def publish(self, payload: dict) -> dict:
        raise InstagramError("NOT_CONNECTED", "pubblicazione Meta non abilitata in questa fase")


class MockMeta:
    """Records the exact payload that will be sent to Meta later. Never touches the network."""

    def __init__(self):
        self.published: List[dict] = []
        self.fail_media: set = set()
        self._id = 17800000000

    async def check(self) -> dict:
        return {"id": "mock", "username": "latosegreto"}

    async def publish(self, payload: dict) -> dict:
        if any(s in payload["media_url"] for s in self.fail_media):
            raise InstagramError("MEDIA_REJECTED", f"{payload['post_type']} rejected (mock)")
        if len(payload["caption"]) > CAPTION_LIMIT:
            raise InstagramError("API_ERROR", "caption too long")
        self._id += 1
        self.published.append({**payload, "ig_media_id": str(self._id)})
        return {"id": str(self._id), "mock": True}


_mock = MockMeta()
_forced: Optional[Any] = None


def get_adapter():
    if _forced is not None:
        return _forced
    return _mock if mock_enabled() else MetaAdapter()


def force_adapter(a: Optional[Any]):
    global _forced
    _forced = a


def build_payload(model: dict, item: dict, caption: str, slot_id: Optional[str], cycle: int) -> Dict[str, Any]:
    """The future Meta payload: PHOTO_POST -> feed image; REEL_POST -> reel (video). Public media only (guaranteed upstream)."""
    post_type = "REEL_POST" if item["type"] == "video" else "PHOTO_POST"
    return {"post_type": post_type, "media_type": "REELS" if post_type == "REEL_POST" else "IMAGE", "media_url": item["url"], "cover_url": item.get("poster"), "caption": caption[:CAPTION_LIMIT],
            "model_id": model.get("id"), "model_slug": model.get("slug"), "media_id": item["id"], "slot_id": slot_id, "cycle_number": cycle, "share_to_feed": True, "location_id": None}


def operational(conn: dict) -> bool:
    """The engine may run when Meta is CONNECTED or when MOCK_MODE is on (mock adapter, zero network)."""
    return bool(conn.get("MOCK_MODE")) or conn.get("CONNECTION_STATUS") == "CONNECTED"


async def connection_status() -> dict:
    """CONNECTION_STATUS: NOT_CONNECTED | CONNECTED | INVALID_TOKEN | API_ERROR (never raises).
    MOCK_MODE is reported SEPARATELY: the mock engine can be operational while Meta is still NOT_CONNECTED.
    In MOCK_MODE no network call is ever made (META_REAL_CALLS stays 0)."""
    out = {"CONNECTION_STATUS": "NOT_CONNECTED", "MOCK_MODE": mock_enabled(), "mock": mock_enabled(), "credentials_present": credentials_present(), "account": None, "error": None,
           "META_REAL_CALLS": META_REAL_CALLS["n"], "operational": False}
    if mock_enabled():
        out["error"] = None if credentials_present() else "credenziali Meta assenti: motore in MOCK_MODE, nessuna chiamata reale"
        out["operational"] = True
        return out
    try:
        out["account"] = await MetaAdapter().check()
        out["CONNECTION_STATUS"] = "CONNECTED"
    except InstagramError as e:
        out["CONNECTION_STATUS"], out["error"] = e.code, e.description
    out["META_REAL_CALLS"] = META_REAL_CALLS["n"]
    out["operational"] = operational(out)
    return out
