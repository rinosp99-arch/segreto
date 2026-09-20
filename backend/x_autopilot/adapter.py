"""X API adapters: MockXAdapter (operational, zero network) + RealXAdapter (skeleton, NOT operational until credentials).

Future env (NOT required now, never hardcoded, never invented): X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_USER_ID.
Future real flow: media upload (v1.1 media/upload, chunked for video) -> POST /2/tweets {text, media.media_ids} -> optional reply
POST /2/tweets {text, media, reply.in_reply_to_tweet_id}. X constraint: one post holds up to 4 PHOTOS or 1 VIDEO, never mixed ->
photo+photo = SINGLE_POST with 2 media (PUBLIC first, SECRET second); any video = THREAD (main post PUBLIC, immediate reply SECRET).
X_REAL_CALLS counts every real HTTP call to api.x.com / upload.twitter.com (must stay 0 while not connected)."""
import os
import uuid
from typing import Any, Dict, List, Optional

X_API = "https://api.x.com/2"
X_UPLOAD = "https://upload.twitter.com/1.1/media/upload.json"
TEXT_LIMIT = 280
URL_WEIGHT = 23                 # every URL counts 23 chars on X (t.co)
X_REAL_CALLS = {"n": 0}
FUTURE_ENV = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "X_USER_ID")


def mock_enabled() -> bool:
    return os.environ.get("X_AUTOPILOT_MOCK", "true").lower() in ("1", "true", "yes")


def credentials_present() -> bool:
    return all(os.environ.get(k) for k in FUTURE_ENV[:4])


def scrub(text: str) -> str:
    out = text or ""
    for k in FUTURE_ENV:
        v = os.environ.get(k, "")
        if v:
            out = out.replace(v, "***SECRET***")
    return out


class XError(Exception):
    def __init__(self, code: str, description: str = ""):
        super().__init__(f"{code}: {scrub(description)}")
        self.code, self.description = code, scrub(description)


class RealXAdapter:
    """Skeleton: raises NOT_CONNECTED until the credentials exist. Even with credentials, publishing will be enabled only
    in the 'X connection' phase (OAuth 1.0a user context). Never makes a network call in this phase."""
    name = "REAL"

    async def check(self) -> dict:
        if not credentials_present():
            raise XError("NOT_CONNECTED", "credenziali X assenti")
        raise XError("NOT_CONNECTED", "RealXAdapter non ancora operativo (fase di collegamento X)")

    async def upload_media(self, item: dict) -> str:
        raise XError("NOT_CONNECTED", "upload media non disponibile: X non collegata")

    async def create_post(self, payload: dict) -> dict:
        raise XError("NOT_CONNECTED", "pubblicazione non disponibile: X non collegata")


class MockXAdapter:
    """Records the complete payload (SINGLE_POST or THREAD) without any network activity.
    Test knobs: fail_media (substrings of media URLs to reject at upload), fail_reply (simulate a failed SECRET reply)."""
    name = "MOCK"

    def __init__(self):
        self.published: List[dict] = []
        self.uploads: List[dict] = []
        self.fail_media: set = set()
        self.fail_reply: bool = False

    async def check(self) -> dict:
        return {"id": "mock", "username": "latosegreto (mock)"}

    async def upload_media(self, item: dict) -> str:
        url = item.get("url") or ""
        if not url or any(f in url for f in self.fail_media):
            raise XError("MEDIA_REJECTED", f"media non caricabile ({item.get('type')}, {item.get('side')})")
        mid = f"mock_media_{uuid.uuid4().hex[:10]}"
        self.uploads.append({"media_id": mid, "url": url, "type": item.get("type"), "side": item.get("side")})
        return mid

    async def create_post(self, payload: dict) -> dict:
        if payload.get("in_reply_to") and self.fail_reply:
            raise XError("API_ERROR", "mock: risposta del thread rifiutata")
        pid = f"mock_x_{uuid.uuid4().hex[:12]}"
        self.published.append({**payload, "x_post_id": pid})
        return {"id": pid}


_forced: Optional[Any] = None


def get_adapter():
    if _forced is not None:
        return _forced
    return MockXAdapter() if mock_enabled() else RealXAdapter()


def force_adapter(a: Optional[Any]):
    global _forced
    _forced = a


def x_len(text: str) -> int:
    """Weighted X length: every URL counts URL_WEIGHT."""
    import re
    urls = re.findall(r"https?://\S+", text or "")
    stripped = re.sub(r"https?://\S+", "", text or "")
    return len(stripped) + URL_WEIGHT * len(urls)


def post_format(pub: dict, sec: dict) -> str:
    """X rule: photos can share one post (max 4); a video must be alone -> THREAD whenever a video is involved."""
    return "SINGLE_POST" if pub["type"] == "photo" and sec["type"] == "photo" else "THREAD"


def build_payloads(model: dict, pub: dict, sec: dict, text: str, reply_text: str, slot_id: Optional[str], cycle: int) -> Dict[str, Any]:
    """Main post always carries the PUBLIC media first. SINGLE_POST: media_order [PUBLIC, SECRET]. THREAD: reply with SECRET."""
    fmt = post_format(pub, sec)
    main = {"kind": "MAIN", "text": text, "media": [pub] + ([sec] if fmt == "SINGLE_POST" else []), "media_order": ["PUBLIC", "SECRET"] if fmt == "SINGLE_POST" else ["PUBLIC"],
            "model_slug": model.get("slug"), "slot_id": slot_id, "cycle_number": cycle, "in_reply_to": None}
    reply = None
    if fmt == "THREAD":
        reply = {"kind": "REPLY", "text": reply_text, "media": [sec], "media_order": ["SECRET"], "model_slug": model.get("slug"), "slot_id": slot_id, "cycle_number": cycle, "in_reply_to": "<main>"}
    assert main["media"][0]["side"] == "PUBLIC"
    return {"format": fmt, "main": main, "reply": reply}


def operational(conn: dict) -> bool:
    return bool(conn.get("MOCK_MODE")) or conn.get("CONNECTION_STATUS") == "CONNECTED"


async def connection_status() -> dict:
    """CONNECTION_STATUS: NOT_CONNECTED | CONNECTED | INVALID_TOKEN | API_ERROR. MOCK_MODE reported SEPARATELY (never shown as connected)."""
    out = {"CONNECTION_STATUS": "NOT_CONNECTED", "MOCK_MODE": mock_enabled(), "mock": mock_enabled(), "credentials_present": credentials_present(), "account": None, "error": None,
           "X_REAL_CALLS": X_REAL_CALLS["n"], "operational": False}
    if mock_enabled():
        out["error"] = None if credentials_present() else "credenziali X assenti: motore in MOCK_MODE, nessuna chiamata reale"
        out["operational"] = True
        return out
    try:
        out["account"] = await RealXAdapter().check()
        out["CONNECTION_STATUS"] = "CONNECTED"
    except XError as e:
        out["CONNECTION_STATUS"], out["error"] = e.code, e.description
    out["X_REAL_CALLS"] = X_REAL_CALLS["n"]
    out["operational"] = operational(out)
    return out
