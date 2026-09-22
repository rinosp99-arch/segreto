"""Telegram Bot API client (httpx) + mock. The token lives only in this process' env and never leaves it:
every error message is scrubbed of the token before being stored or returned."""
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

API = "https://api.telegram.org"
CAPTION_LIMIT = 1024
URL_PHOTO_MAX = 5 * 1024 * 1024        # sendPhoto by URL
URL_VIDEO_MAX = 20 * 1024 * 1024       # sendVideo by URL
UPLOAD_MAX = 50 * 1024 * 1024          # multipart upload


def token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def channel() -> str:
    return os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()


def mock_enabled() -> bool:
    return os.environ.get("TELEGRAM_AUTOPILOT_MOCK", "true").lower() in ("1", "true", "yes")


def scrub(text: str) -> str:
    t = token()
    return (text or "").replace(t, "***TOKEN***") if t else (text or "")


class _TokenRedactor(logging.Filter):
    """httpx/httpcore log the full request URL (which contains /bot<token>/): redact it in every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        t = token()
        if t:
            if isinstance(record.msg, str) and t in record.msg:
                record.msg = record.msg.replace(t, "***TOKEN***")
            if record.args:
                try:
                    record.args = tuple(a.replace(t, "***TOKEN***") if isinstance(a, str) else (scrub(str(a)) if t in str(a) else a) for a in record.args) if isinstance(record.args, tuple) else record.args
                except Exception:
                    pass
        return True


for _name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection", "uvicorn.error", "uvicorn.access", ""):
    logging.getLogger(_name).addFilter(_TokenRedactor())


class TelegramError(Exception):
    def __init__(self, code: str, description: str = "", status: Optional[int] = None, retry_after: Optional[int] = None):
        super().__init__(f"{code}: {scrub(description)}")
        self.code, self.description, self.status, self.retry_after = code, scrub(description), status, retry_after


class TelegramClient:
    """Thin real client. All calls: POST https://api.telegram.org/bot<token>/<method>."""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout

    def _url(self, method: str) -> str:
        return f"{API}/bot{token()}/{method}"

    async def call(self, method: str, data: Optional[dict] = None, files: Optional[dict] = None) -> Any:
        if not token():
            raise TelegramError("INVALID_TOKEN", "TELEGRAM_BOT_TOKEN non configurato")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as c:
                r = await c.post(self._url(method), data=data if files else None, json=None if files else (data or {}), files=files)
        except httpx.TimeoutException:
            raise TelegramError("TIMEOUT", f"{method} timeout")
        except httpx.HTTPError as e:
            raise TelegramError("API_ERROR", f"{method}: {type(e).__name__}")
        try:
            body = r.json()
        except Exception:
            raise TelegramError("API_ERROR", f"{method}: risposta non JSON (HTTP {r.status_code})", r.status_code)
        if not body.get("ok"):
            desc = body.get("description", "")
            code = _classify(r.status_code, desc)
            raise TelegramError(code, desc, r.status_code, (body.get("parameters") or {}).get("retry_after"))
        return body.get("result")

    async def get_me(self) -> dict:
        return await self.call("getMe")

    async def get_chat(self, chat_id: str) -> dict:
        return await self.call("getChat", {"chat_id": chat_id})

    async def get_chat_member(self, chat_id: str, user_id: int) -> dict:
        return await self.call("getChatMember", {"chat_id": chat_id, "user_id": user_id})

    async def get_updates(self, limit: int = 100) -> list:
        return await self.call("getUpdates", {"limit": limit, "timeout": 0}) or []

    async def send_photo(self, chat_id: str, photo, caption: str, reply_markup: Optional[dict] = None, filename: str = "photo.jpg") -> dict:
        return await self._send_media("sendPhoto", "photo", chat_id, photo, caption, reply_markup, filename, {})

    async def send_video(self, chat_id: str, video, caption: str, reply_markup: Optional[dict] = None, filename: str = "video.mp4") -> dict:
        return await self._send_media("sendVideo", "video", chat_id, video, caption, reply_markup, filename, {"supports_streaming": True})

    async def _send_media(self, method, field, chat_id, media, caption, reply_markup, filename, extra) -> dict:
        import json
        payload = {"chat_id": chat_id, "caption": caption[:CAPTION_LIMIT], "parse_mode": "HTML", **extra}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup) if isinstance(media, (bytes, bytearray)) else reply_markup
        if isinstance(media, (bytes, bytearray)):
            payload = {k: (json.dumps(v) if isinstance(v, (dict, bool)) and k != "reply_markup" else v) for k, v in payload.items()}
            payload["supports_streaming"] = "true" if extra.get("supports_streaming") else None
            payload = {k: v for k, v in payload.items() if v is not None}
            return await self.call(method, payload, files={field: (filename, bytes(media))})
        payload[field] = media
        return await self.call(method, payload)


def _classify(status: int, desc: str) -> str:
    d = (desc or "").lower()
    if status == 401 or "unauthorized" in d:
        return "INVALID_TOKEN"
    if "chat not found" in d or "channel not found" in d:
        return "CHANNEL_NOT_FOUND"
    if "not enough rights" in d or "need administrator rights" in d or "have no rights" in d:
        return "MISSING_PERMISSION"
    if "bot is not a member" in d or "bot was kicked" in d or "bot is not a member of the channel" in d:
        return "BOT_NOT_ADMIN"
    if status == 429:
        return "RATE_LIMITED"
    if "wrong file identifier" in d or "failed to get http url content" in d or "wrong type of the web page content" in d or "file is too big" in d or "photo_invalid_dimensions" in d or "video_file_invalid" in d or "wrong padding" in d:
        return "MEDIA_REJECTED"
    return "API_ERROR"


class MockTelegram:
    """Preview/test double. Records every call, never touches the network. `fail_media` = set of URL substrings that fail."""

    def __init__(self):
        self.sent: List[dict] = []
        self.fail_media: set = set()
        self.fail_all: Optional[str] = None
        self.me = {"id": 8887754816, "is_bot": True, "username": "latosegreto_bot", "first_name": "Lato Segreto"}
        self.member_status = "administrator"
        self.can_post = True
        self._mid = 1000

    async def get_me(self):
        if self.fail_all == "INVALID_TOKEN":
            raise TelegramError("INVALID_TOKEN", "Unauthorized", 401)
        return dict(self.me)

    async def get_chat(self, chat_id):
        if self.fail_all == "CHANNEL_NOT_FOUND":
            raise TelegramError("CHANNEL_NOT_FOUND", "Bad Request: chat not found", 400)
        return {"id": -1001234567890, "type": "channel", "title": "LATO SEGRETO", "username": chat_id.lstrip("@")}

    async def get_chat_member(self, chat_id, user_id):
        return {"status": self.member_status, "can_post_messages": self.can_post, "user": self.me}

    async def get_updates(self, limit=100):
        return []

    async def send_photo(self, chat_id, photo, caption, reply_markup=None, filename="photo.jpg"):
        return await self._send("photo", chat_id, photo, caption, reply_markup)

    async def send_video(self, chat_id, video, caption, reply_markup=None, filename="video.mp4"):
        return await self._send("video", chat_id, video, caption, reply_markup)

    async def _send(self, kind, chat_id, media, caption, reply_markup):
        ref = media if isinstance(media, str) else f"<bytes:{len(media)}>"
        if any(s in ref for s in self.fail_media):
            raise TelegramError("MEDIA_REJECTED", f"Bad Request: {kind} rejected (mock)", 400)
        if len(caption) > CAPTION_LIMIT:
            raise TelegramError("API_ERROR", "Bad Request: caption is too long", 400)
        self._mid += 1
        msg = {"message_id": self._mid, "chat": {"id": -1001234567890, "username": chat_id.lstrip("@")}, "caption": caption, kind: {"file_id": f"mock-{kind}-{self._mid}"}, "reply_markup": reply_markup}
        self.sent.append({"kind": kind, "media": ref, "caption": caption, "reply_markup": reply_markup, "message_id": self._mid})
        return msg


_mock_singleton = MockTelegram()
_forced: Optional[Any] = None


def get_client():
    """Real client unless TELEGRAM_AUTOPILOT_MOCK=true (preview) or a test forced a double."""
    if _forced is not None:
        return _forced
    return _mock_singleton if mock_enabled() else TelegramClient()


def force_client(c: Optional[Any]):
    global _forced
    _forced = c


async def connection_status(check_real: bool = False, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """TELEGRAM_CONNECTION_STATUS: CONNECTED | INVALID_TOKEN | CHANNEL_NOT_FOUND | BOT_NOT_ADMIN | MISSING_PERMISSION | API_ERROR.
    `check_real=True` uses the REAL API even in mock mode (read-only calls: getMe/getChat/getChatMember).
    `chat_id` overrides the env channel (e.g. permanent NUMERIC id for a private channel)."""
    target = str(chat_id or channel() or "").strip()
    out: Dict[str, Any] = {"TELEGRAM_CONNECTION_STATUS": "API_ERROR", "channel": target or None, "mock": mock_enabled() and not check_real, "bot": None, "chat": None, "bot_is_admin": False, "can_post": False, "error": None}
    if not token():
        out.update(TELEGRAM_CONNECTION_STATUS="INVALID_TOKEN", error="TELEGRAM_BOT_TOKEN non configurato")
        return out
    if not target:
        out.update(TELEGRAM_CONNECTION_STATUS="CHANNEL_NOT_FOUND", error="TELEGRAM_CHANNEL_ID non configurato")
        return out
    c = TelegramClient(timeout=20) if check_real else get_client()
    try:
        me = await c.get_me()
        out["bot"] = {"username": me.get("username"), "id": me.get("id")}
    except TelegramError as e:
        out.update(TELEGRAM_CONNECTION_STATUS=e.code if e.code in ("INVALID_TOKEN",) else "API_ERROR", error=e.description)
        return out
    try:
        chat = await c.get_chat(target)
        out["chat"] = {"title": chat.get("title"), "username": chat.get("username"), "type": chat.get("type"), "id": chat.get("id")}
    except TelegramError as e:
        out.update(TELEGRAM_CONNECTION_STATUS="CHANNEL_NOT_FOUND" if e.code in ("CHANNEL_NOT_FOUND", "BOT_NOT_ADMIN") else e.code if e.code == "INVALID_TOKEN" else "API_ERROR", error=e.description)
        return out
    try:
        m = await c.get_chat_member(target, me["id"])
    except TelegramError as e:
        out.update(TELEGRAM_CONNECTION_STATUS="BOT_NOT_ADMIN" if e.code in ("BOT_NOT_ADMIN", "MISSING_PERMISSION", "CHANNEL_NOT_FOUND") else "API_ERROR", error=e.description)
        return out
    status = m.get("status")
    out["bot_is_admin"] = status in ("administrator", "creator")
    out["can_post"] = bool(m.get("can_post_messages", status == "creator"))
    if not out["bot_is_admin"]:
        out.update(TELEGRAM_CONNECTION_STATUS="BOT_NOT_ADMIN", error=f"il bot è '{status}' nel canale, deve essere amministratore")
    elif not out["can_post"]:
        out.update(TELEGRAM_CONNECTION_STATUS="MISSING_PERMISSION", error="al bot manca il permesso 'Pubblica messaggi'")
    else:
        out["TELEGRAM_CONNECTION_STATUS"] = "CONNECTED"
    return out



async def resolve_channels_via_updates() -> Dict[str, Any]:
    """Discover the permanent NUMERIC chat_id of channels the bot can see, using getUpdates (channel_post / my_chat_member / message).
    Read-only. Returns {"ok", "channels": [{id,title,type,username}], "count"}. Works only if there are recent updates and no webhook."""
    out: Dict[str, Any] = {"ok": False, "channels": [], "count": 0, "error": None}
    if not token():
        out["error"] = "TELEGRAM_BOT_TOKEN non configurato"
        return out
    c = TelegramClient(timeout=20)
    try:
        updates = await c.get_updates(limit=100)
    except TelegramError as e:
        out["error"] = f"{e.code}: {e.description}"
        return out
    seen: Dict[Any, dict] = {}
    for u in (updates or []):
        for key in ("channel_post", "edited_channel_post", "my_chat_member", "chat_member", "message"):
            obj = u.get(key) if isinstance(u, dict) else None
            chat = (obj or {}).get("chat") if isinstance(obj, dict) else None
            if isinstance(chat, dict) and chat.get("type") in ("channel", "supergroup"):
                seen[chat.get("id")] = {"id": chat.get("id"), "title": chat.get("title"), "type": chat.get("type"), "username": chat.get("username")}
    out.update(ok=True, channels=list(seen.values()), count=len(seen))
    return out
