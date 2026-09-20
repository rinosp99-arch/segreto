"""The Only API adapter (https://docs.theonlyapi.com) — panel-scoped base https://theonlyapi.com/api/crm/{crm_id}, auth header X-API-Key ONLY
(never query params, never Bearer). Secrets live in backend env only and are scrubbed from every log record / error message.

Documented endpoints used:
  GET  https://api.theonlyapi.com/api/whoami                     key -> {crm_id, plan}            (auth + CRM scope check)
  GET  {base}/accounts                                            connected accounts {of_user_id, username, platform}
  GET  {base}/accounts/{of_user_id}/polling                       {polling:{enabled, interval_seconds, allow_of_write_actions}}
  GET  {base}/api2/v2/users/me            (header user-id)        live authenticated OnlyFans session -> HEALTHY
  GET  {base}/api2/v2/schedules?limit&offset (header user-id)     {list:[...], hasMore}
  GET  {base}/api2/v2/posts/{post_id}     (header user-id)
  POST {base}/accounts/{of_user_id}/media  (multipart file)       WRITE -> returns complete `media` object (kept whole)
  POST {base}/api2/v2/posts                (header user-id)       WRITE -> body {text, mediaFiles:[<whole media obj>], isScheduled:1, scheduledDate}
  POST {base}/api2/v2/messages/queue        (header user-id)       WRITE -> OnlyFans mass message (queue) {text, mediaFiles:[vault ids], price, queueBuyers:[]=ALL subscribers}
  GET  {base}/api2/v2/messages/queue        (header user-id)       {list:[...], hasMore}  (verification of a mass message by id)
  POST {base}/api2/v2/messages/queue/size   (header user-id)       {size} audience preview for the same queueBuyers (no send)
  POST {base}/accounts/{of_user_id}/messages/mass  (CRM)          {text, price, mediaFiles:[vault ids], audience:{type: all|active|expired}, dry_run}
                                                                  dry_run=true -> {recipients, sent:0, sample} (no send); dry_run=false -> serial send inside the request
  GET  {base}/accounts/{of_user_id}/chats/{fan_id}/messages       read-back of a recipient's conversation (verification)
  Delete scheduled post: NOT documented -> never called (NOT_DOCUMENTED).
Mass message writes are additionally blocked unless OF_MASS_DM_ENABLED=true AND OF_MASS_DM_MOCK=false (MASS_DM_DISABLED, no network).
All WRITE methods are blocked while OF_REAL_POSTING_ENABLED != true and never reach the network. OF_REAL_WRITE_CALLS counts real write HTTP calls."""
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from .base import OFAccount, OFAccountHealth, OFMassMessageRequest, OFMassMessageResult, OFMedia, OFPostRequest, OFPostResult, OFProviderAdapter, OFProviderError

PANEL_HOST = "https://theonlyapi.com"
WHOAMI_URL = "https://api.theonlyapi.com/api/whoami"
TIMEOUT_S = 40.0
CALLS = {"read": 0, "write": 0, "gate": 0, "upload": 0, "create": 0, "mass_dm": 0}   # OF_REAL_WRITE_CALLS = CALLS["write"] (includes gate/upload/create/mass_dm)
MASK = "****"


def api_key() -> str:
    return (os.environ.get("THE_ONLY_API_KEY") or "").strip()


def crm_id() -> str:
    return (os.environ.get("THE_ONLY_CRM_ID") or "").strip()


def configured() -> bool:
    return bool(api_key() and crm_id())


def writes_enabled() -> bool:
    return os.environ.get("OF_REAL_POSTING_ENABLED", "false").lower() in ("1", "true", "yes")


def mass_dm_real_allowed() -> bool:
    """Real mass DM only when explicitly enabled AND not in mock: OF_MASS_DM_ENABLED=true and OF_MASS_DM_MOCK=false."""
    return os.environ.get("OF_MASS_DM_ENABLED", "false").lower() in ("1", "true", "yes") and os.environ.get("OF_MASS_DM_MOCK", "true").lower() not in ("1", "true", "yes")


def scrub(text: Any) -> str:
    """Masks the API key (and the CRM id) wherever they could appear."""
    s = str(text if text is not None else "")
    for secret in (api_key(), crm_id()):
        if secret and secret in s:
            s = s.replace(secret, MASK)
    return s


class _SecretRedactor(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        k = api_key()
        if k:
            if isinstance(record.msg, str) and k in record.msg:
                record.msg = record.msg.replace(k, MASK)
            if record.args and isinstance(record.args, tuple):
                try:
                    record.args = tuple(a.replace(k, MASK) if isinstance(a, str) else (scrub(a) if k in str(a) else a) for a in record.args)
                except Exception:
                    pass
        return True


for _name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection", "uvicorn.error", "uvicorn.access", ""):
    logging.getLogger(_name).addFilter(_SecretRedactor())


def _unwrap(data: Any) -> Any:
    """Passthrough (/api2/v2/*) answers are wrapped as {success, status_code, data}: return the inner OnlyFans payload."""
    if isinstance(data, dict) and "data" in data and "status_code" in data and "success" in data:
        if data.get("success") is False or int(data.get("status_code") or 200) >= 400:
            raise OFProviderError("API_ERROR", f"passthrough status {data.get('status_code')}: {scrub(str(data.get('data')))[:200]}", data.get("status_code"))
        return data["data"]
    return data


def _err_from_response(r: httpx.Response) -> OFProviderError:
    body = scrub(r.text[:300])
    code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 429: "RATE_LIMITED"}.get(r.status_code, "API_ERROR")
    return OFProviderError(code, f"HTTP {r.status_code}: {body}", r.status_code)


def _b(v: Any) -> Optional[bool]:
    return None if v is None else bool(v)


class TheOnlyAPIAdapter(OFProviderAdapter):
    name = "THE_ONLY_API"

    def __init__(self, timeout: float = TIMEOUT_S):
        self.timeout = timeout

    # ------------------------------------------------------------------ plumbing
    @property
    def base(self) -> str:
        return f"{PANEL_HOST}/api/crm/{crm_id()}"

    def _headers(self, of_user_id: Optional[str] = None) -> Dict[str, str]:
        h = {"X-API-Key": api_key(), "Accept": "application/json"}
        if of_user_id:
            h["user-id"] = str(of_user_id)
        return h

    async def _request(self, method: str, url: str, *, of_user_id: Optional[str] = None, write: bool = False, read_post: bool = False, **kw) -> Any:
        if not configured():
            raise OFProviderError("NOT_CONFIGURED", "THE_ONLY_API_KEY / THE_ONLY_CRM_ID assenti")
        if write:
            if not writes_enabled():
                raise OFProviderError("WRITES_DISABLED", "OF_REAL_POSTING_ENABLED=false: nessuna scrittura verso The Only API")
            CALLS["write"] += 1
        else:
            assert method.upper() == "GET" or read_post, "read path must be GET"          # read_post: documented POST that only computes (queue/size)
            CALLS["read"] += 1
        timeout = kw.pop("timeout", self.timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.request(method, url, headers=self._headers(of_user_id), **kw)
        except httpx.HTTPError as e:
            raise OFProviderError("NETWORK_ERROR", scrub(str(e))[:200])
        if r.status_code >= 400:
            raise _err_from_response(r)
        try:
            return r.json()
        except ValueError:
            raise OFProviderError("API_ERROR", "risposta non JSON", r.status_code)

    # ------------------------------------------------------------------ READ
    async def whoami(self) -> Dict[str, Any]:
        """Resolves the key to its panel: proves the key is valid; the returned crm_id must equal THE_ONLY_CRM_ID."""
        return await self._request("GET", WHOAMI_URL)

    async def test_connection(self) -> Dict[str, Any]:
        who = await self.whoami()
        scope_ok = str(who.get("crm_id") or "") == crm_id()
        if not scope_ok:
            raise OFProviderError("FORBIDDEN", "la chiave non appartiene al CRM configurato")
        accounts = await self.list_accounts()
        return {"key_valid": True, "crm_scope": scope_ok, "plan": who.get("plan"), "accounts_count": len(accounts),
                "accounts": [{"username": a.username, "platform": a.platform} for a in accounts]}

    async def list_accounts(self) -> List[OFAccount]:
        data = await self._request("GET", f"{self.base}/accounts")          # never include_session=true (would return sess/proxy)
        out = []
        for a in data.get("accounts") or []:
            out.append(OFAccount(of_user_id=str(a.get("of_user_id") or ""), username=str(a.get("username") or ""), platform=str(a.get("platform") or ""),
                                 raw={k: a.get(k) for k in ("of_user_id", "username", "platform")}))
        return out

    async def get_account(self, of_user_id: str) -> OFAccount:
        for a in await self.list_accounts():
            if a.of_user_id == str(of_user_id):
                return a
        raise OFProviderError("NOT_FOUND", "account non collegato a questo pannello")

    async def get_polling(self, of_user_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"{self.base}/accounts/{of_user_id}/polling")

    async def get_me(self, of_user_id: str) -> Dict[str, Any]:
        """Live authenticated OnlyFans profile through the saved session/proxy: the real health probe (read-only)."""
        return _unwrap(await self._request("GET", f"{self.base}/api2/v2/users/me", of_user_id=of_user_id))

    async def get_account_health(self, of_user_id: str) -> OFAccountHealth:
        polling = {}
        try:
            polling = (await self.get_polling(of_user_id)).get("polling") or {}
        except OFProviderError as e:
            polling = {"_error": e.code}
        try:
            me = await self.get_me(of_user_id)
        except OFProviderError as e:
            return OFAccountHealth("UNHEALTHY", None, _b(polling.get("allow_of_write_actions")), _b(polling.get("enabled", polling.get("polling_enabled"))), f"users/me: {e.code}")
        username = str(me.get("username") or "")
        healthy = bool(username) and str(me.get("id") or "") == str(of_user_id)
        return OFAccountHealth("HEALTHY" if healthy else "UNHEALTHY", username or None, _b(polling.get("allow_of_write_actions")), _b(polling.get("enabled", polling.get("polling_enabled"))),
                               None if healthy else "profilo live non coerente con of_user_id")

    async def get_scheduled_posts(self, of_user_id: str, limit: int = 10, offset: int = 0) -> Dict[str, Any]:
        data = _unwrap(await self._request("GET", f"{self.base}/api2/v2/schedules", of_user_id=of_user_id, params={"limit": limit, "offset": offset}))
        if isinstance(data, list):                       # defensive: normalise to the documented shape
            data = {"list": data, "hasMore": False}
        return {"list": data.get("list") or [], "hasMore": bool(data.get("hasMore"))}

    async def get_post(self, of_user_id: str, post_id: str) -> Dict[str, Any]:
        return _unwrap(await self._request("GET", f"{self.base}/api2/v2/posts/{post_id}", of_user_id=of_user_id))

    # ------------------------------------------------------------------ WRITE (guarded; blocked in this phase)
    async def upload_media(self, of_user_id: str, *, file_name: str, content: bytes, content_type: str) -> OFMedia:
        CALLS["upload"] += 1
        data = await self._request("POST", f"{self.base}/accounts/{of_user_id}/media", write=True, files={"file": (file_name, content, content_type)})
        media = data.get("media") or {}
        if not media.get("processId"):
            raise OFProviderError("API_ERROR", "upload senza media.processId")
        kind = "video" if content_type.startswith("video/") else ("audio" if content_type.startswith("audio/") else ("gif" if content_type == "image/gif" else "photo"))
        return OFMedia(provider_ref=str(media["processId"]), kind=kind, raw=dict(media))      # COMPLETE object, never trimmed

    # ------------------------------------------------------------------ panel write gate (documented PATCH polling)
    async def set_write_gate(self, of_user_id: str, enabled: bool) -> Dict[str, Any]:
        """PATCH /accounts/{of_user_id}/polling {"allow_of_write_actions": bool}. Panel setting only (no proxy/session/credentials).
        Counted as a real write. Requires OF_REAL_POSTING_ENABLED=true."""
        CALLS["gate"] += 1
        return await self._request("PATCH", f"{self.base}/accounts/{of_user_id}/polling", write=True, json={"allow_of_write_actions": bool(enabled)})

    async def get_write_gate(self, of_user_id: str) -> Optional[bool]:
        polling = (await self.get_polling(of_user_id)).get("polling") or {}
        v = polling.get("allow_of_write_actions")
        return None if v is None else bool(v)

    async def upload_media_from_url(self, of_user_id: str, *, source_url: str, file_name: str, kind: str) -> OFMedia:
        """Documented JSON variant of POST /accounts/{of_user_id}/media: {"source_url": "https://..."} -> provider fetches the file server-side."""
        CALLS["upload"] += 1
        data = await self._request("POST", f"{self.base}/accounts/{of_user_id}/media", write=True, json={"source_url": source_url})
        media = data.get("media") or {}
        if not media.get("processId"):
            raise OFProviderError("API_ERROR", "upload senza media.processId")
        return OFMedia(provider_ref=str(media["processId"]), kind=kind, raw=dict(media))      # COMPLETE object, never trimmed

    def _post_body(self, req: OFPostRequest) -> Dict[str, Any]:
        body: Dict[str, Any] = {"text": req.text}
        if req.media:
            body["mediaFiles"] = [dict(m.raw) for m in req.media]                                # whole object under mediaFiles (not `media`)
        if req.scheduled_at:
            body["isScheduled"] = 1
            body["scheduledDate"] = req.scheduled_at                                               # never postedAt
        return body

    def _check_create_limit(self):
        """HARD LIMIT (process-level, in addition to the engine DB-level check): OF_REAL_TEST_MAX_POSTS create calls at most."""
        raw = (os.environ.get("OF_REAL_TEST_MAX_POSTS") or "").strip()
        if raw.isdigit() and CALLS["create"] >= int(raw):
            raise OFProviderError("REAL_TEST_LIMIT", f"limite post reali di test raggiunto ({raw})")

    async def create_post(self, of_user_id: str, req: OFPostRequest) -> OFPostResult:
        self._check_create_limit()
        CALLS["create"] += 1
        data = _unwrap(await self._request("POST", f"{self.base}/api2/v2/posts", of_user_id=of_user_id, write=True, json=self._post_body(req)))
        pid = data.get("id")
        return OFPostResult(post_id=str(pid) if pid is not None else None, scheduled=False, schedule_state="PUBLISHED" if pid is not None else "UNKNOWN", raw=data)

    async def schedule_post(self, of_user_id: str, req: OFPostRequest) -> OFPostResult:
        """CREATE (isScheduled+scheduledDate) -> post id -> GET schedules -> id present ? SCHEDULE_CONFIRMED : SCHEDULE_NOT_CONFIRMED."""
        if not req.scheduled_at:
            raise OFProviderError("API_ERROR", "schedule_post richiede scheduled_at")
        self._check_create_limit()
        CALLS["create"] += 1
        data = _unwrap(await self._request("POST", f"{self.base}/api2/v2/posts", of_user_id=of_user_id, write=True, json=self._post_body(req)))
        pid = data.get("id")
        if pid is None:
            return OFPostResult(None, True, "SCHEDULE_NOT_CONFIRMED", data)
        confirmed = await self.verify_scheduled(of_user_id, str(pid))
        return OFPostResult(str(pid), True, "SCHEDULE_CONFIRMED" if confirmed else "SCHEDULE_NOT_CONFIRMED", data)

    async def delete_scheduled_post(self, of_user_id: str, post_id: str) -> Dict[str, Any]:
        if not writes_enabled():
            raise OFProviderError("WRITES_DISABLED", "OF_REAL_POSTING_ENABLED=false")
        raise OFProviderError("NOT_DOCUMENTED", "The Only API non documenta un endpoint di cancellazione post programmato: nessuna richiesta inviata")

    # ------------------------------------------------------------------ MASS MESSAGE (CRM, documented): /accounts/{id}/messages/mass with audience.type + dry_run
    MASS_SEND_TIMEOUT_S = 3600.0        # the real send is a serial loop inside one HTTP request (up to 5,000 recipients)

    async def mass_message_crm(self, of_user_id: str, req: OFMassMessageRequest, dry_run: bool = True) -> Dict[str, Any]:
        """POST {base}/accounts/{of_user_id}/messages/mass. audience.type from req.audience ('ALL' -> 'all', 'ACTIVE' -> 'active').
        dry_run=True resolves the audience and sends NOTHING -> {success, dry_run, recipients, sent, sample}. dry_run=False = THE real send."""
        self._mass_guard()
        if not req.text and not req.media_ids:
            raise OFProviderError("API_ERROR", "message requires text or mediaFiles")
        a_type = {"ALL": "all", "ACTIVE": "active", "EXPIRED": "expired"}.get(str(req.audience).upper())
        if not a_type:
            raise OFProviderError("NOT_SUPPORTED", "audience.type deve essere all | active | expired")
        body: Dict[str, Any] = {"text": req.text, "price": float(req.price) if (req.price or 0) > 0 else 0, "mediaFiles": [str(x) for x in req.media_ids], "audience": {"type": a_type}, "dry_run": bool(dry_run)}
        url = f"{self.base}/accounts/{of_user_id}/messages/mass"
        if dry_run:
            data = await self._request("POST", url, of_user_id=of_user_id, read_post=True, json=body)          # documented: "Preview only — no messages were sent."
        else:
            CALLS["mass_dm"] += 1
            data = await self._request("POST", url, of_user_id=of_user_id, write=True, json=body, timeout=self.MASS_SEND_TIMEOUT_S)
        data = _unwrap(data) if isinstance(data, dict) and "data" in data and "recipients" not in data else data
        return data if isinstance(data, dict) else {"raw": data}

    async def get_chat_messages(self, of_user_id: str, fan_id: str, limit: int = 20) -> Dict[str, Any]:
        """GET {base}/accounts/{of_user_id}/chats/{fan_id}/messages (read-only) -> conversation page."""
        data = await self._request("GET", f"{self.base}/accounts/{of_user_id}/chats/{fan_id}/messages", of_user_id=of_user_id, params={"limit": limit})
        return _unwrap(data) if isinstance(data, dict) else {"list": data}

    # ------------------------------------------------------------------ MASS MESSAGE (documented OnlyFans passthrough: /api2/v2/messages/queue)
    def _mass_guard(self):
        if not mass_dm_real_allowed():
            raise OFProviderError("MASS_DM_DISABLED", "OF_MASS_DM_ENABLED=false o OF_MASS_DM_MOCK=true: nessun mass message reale")

    @staticmethod
    def _queue_buyers(req: OFMassMessageRequest) -> list:
        if req.audience != "ALL":
            raise OFProviderError("NOT_SUPPORTED", "solo audience ALL (tutti i subscriber) è supportata")
        return []                                                                                    # documented: empty array = all subscribers

    async def mass_message_audience_size(self, of_user_id: str) -> Optional[int]:
        """POST /api2/v2/messages/queue/size {queueBuyers: []} -> {size}. Computes only, sends nothing; still behind the mass DM gate."""
        self._mass_guard()
        data = _unwrap(await self._request("POST", f"{self.base}/api2/v2/messages/queue/size", of_user_id=of_user_id, read_post=True, json={"queueBuyers": []}))
        v = (data or {}).get("size")
        return int(v) if isinstance(v, (int, float, str)) and str(v).isdigit() else None

    async def subscribers_count(self, of_user_id: str) -> Optional[int]:
        """READ: GET /api2/v2/users/me -> subscribersCount (all current subscribers of the account). Works with the write gate closed."""
        me = await self.get_me(of_user_id)
        v = (me or {}).get("subscribersCount")
        return int(v) if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()) else None

    async def get_mass_messages(self, of_user_id: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        data = _unwrap(await self._request("GET", f"{self.base}/api2/v2/messages/queue", of_user_id=of_user_id, params={"limit": limit, "offset": offset}))
        if isinstance(data, list):
            data = {"list": data, "hasMore": False}
        return {"list": data.get("list") or [], "hasMore": bool(data.get("hasMore"))}

    async def send_mass_message(self, of_user_id: str, req: OFMassMessageRequest) -> OFMassMessageResult:
        """POST /api2/v2/messages/queue {text, mediaFiles:[vault ids], price, lockedText:false, queueBuyers:[]} -> created queue item (id) -> GET queue -> id present ? CONFIRMED."""
        self._mass_guard()
        if not req.text and not req.media_ids:
            raise OFProviderError("API_ERROR", "message requires text or mediaFiles")
        body: Dict[str, Any] = {"text": req.text, "mediaFiles": [int(x) if str(x).isdigit() else x for x in req.media_ids], "price": req.price if (req.price or 0) > 0 else None,
                                "lockedText": False, "queueBuyers": self._queue_buyers(req)}
        CALLS["mass_dm"] += 1
        data = _unwrap(await self._request("POST", f"{self.base}/api2/v2/messages/queue", of_user_id=of_user_id, write=True, json=body))
        mid = (data or {}).get("id")
        if mid is None:
            return OFMassMessageResult(None, "MASS_DM_NOT_CONFIRMED", None, data or {})
        confirmed = await self.verify_mass_message(of_user_id, str(mid))
        return OFMassMessageResult(str(mid), "MASS_DM_CONFIRMED" if confirmed else "MASS_DM_NOT_CONFIRMED", None, data)
