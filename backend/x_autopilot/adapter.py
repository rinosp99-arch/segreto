"""X API adapters: MockXAdapter (operational, zero network) + RealXAdapter (OAuth 1.0a user context, api.x.com v2).

Env (backend only, never hardcoded, never logged): X_CONSUMER_KEY / X_CONSUMER_SECRET / X_BEARER_TOKEN (legacy X_API_KEY / X_API_SECRET accepted),
optional X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET (else the encrypted user token obtained via /auth/start lives in Mongo `x_autopilot_auth`),
X_REAL_POSTING_ENABLED (write gate, default false), X_AUTOPILOT_MOCK (default true).
Real flow: v2 chunked media upload (POST /2/media/upload/initialize -> /{id}/append -> /{id}/finalize -> STATUS) -> POST /2/tweets {text, media.media_ids}
-> optional reply POST /2/tweets {reply.in_reply_to_tweet_id}. X constraint: one post holds up to 4 PHOTOS or 1 VIDEO, never mixed ->
photo+photo = SINGLE_POST with 2 media (PUBLIC first, SECRET second); any video = THREAD (main post PUBLIC, immediate reply SECRET).
X_REAL_CALLS counts every real HTTP call to api.x.com (shared counter with xauth)."""
import asyncio
import json
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx

from . import xauth

X_API = "https://api.x.com/2"
X_MEDIA_UPLOAD = f"{X_API}/media/upload"
TEXT_LIMIT = 280
URL_WEIGHT = 23                 # every URL counts 23 chars on X (t.co)
X_REAL_CALLS = xauth.CALLS      # {"n": real WRITE calls, "read": auth/identity reads} — single shared counter
FUTURE_ENV = ("X_CONSUMER_KEY", "X_CONSUMER_SECRET", "X_BEARER_TOKEN", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "X_USER_ID")
CHUNK = 4 * 1024 * 1024
LIMITS = {"photo": 5 * 1024 * 1024, "video": 512 * 1024 * 1024}
PHOTO_MIME = ("image/jpeg", "image/png", "image/webp")
VIDEO_MIME = ("video/mp4", "video/quicktime")


def mock_enabled() -> bool:
    return os.environ.get("X_AUTOPILOT_MOCK", "true").lower() in ("1", "true", "yes")


def credentials_present() -> bool:
    """App credentials present (consumer key + secret). User-level token is reported separately (xauth.user_auth_present)."""
    return xauth.app_credentials_present()


def scrub(text: str) -> str:
    return xauth.scrub(text)


class XError(Exception):
    def __init__(self, code: str, description: str = ""):
        super().__init__(f"{code}: {scrub(description)}")
        self.code, self.description = code, scrub(description)


async def real_posts_created():
    from . import engine
    return await engine.log_col.count_documents({"mock": {"$ne": True}, "x_post_id": {"$nin": [None, ""]}, "status": {"$in": ["PUBLISHED", "PARTIAL_FAILED"]}})


async def validate_media_source(item: dict) -> dict:
    """READ-ONLY pre-check on our own storage (HEAD/GET headers): reachable, MIME compatible with X, size within X limits. No X call."""
    url, kind = item.get("url") or "", item.get("type") or "photo"
    out = {"ok": False, "url_ok": url.startswith("https://"), "mime": None, "bytes": None, "reason": None}
    if not out["url_ok"]:
        out["reason"] = "URL_NOT_HTTPS"
        return out
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
            r = await c.head(url)
            if r.status_code >= 400 or not r.headers.get("content-type"):
                r = await c.get(url, headers={"Range": "bytes=0-0"})
    except httpx.HTTPError as e:
        out["reason"] = f"UNREACHABLE_{type(e).__name__}"
        return out
    if r.status_code >= 400:
        out["reason"] = f"HTTP_{r.status_code}"
        return out
    mime = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    size = r.headers.get("content-length")
    if r.headers.get("content-range"):
        size = r.headers["content-range"].split("/")[-1]
    out["mime"], out["bytes"] = mime, int(size) if size and size.isdigit() else None
    allowed = VIDEO_MIME if kind == "video" else PHOTO_MIME
    if mime not in allowed:
        out["reason"] = "MIME_NOT_SUPPORTED"
        return out
    if out["bytes"] is not None and out["bytes"] > LIMITS[kind]:
        out["reason"] = "TOO_LARGE"
        return out
    out["ok"] = True
    return out


class RealXAdapter:
    """OAuth 1.0a user context against api.x.com. READ: check(). WRITE (upload/create) only when X_REAL_POSTING_ENABLED=true AND a user token exists."""
    name = "REAL"

    async def check(self) -> dict:
        if not credentials_present():
            raise XError("NOT_CONNECTED", "credenziali app X assenti")
        ident = await xauth.identity_check()
        if not ident.get("X_ACCOUNT_CONNECTED"):
            err = ident.get("error") or "NOT_CONNECTED"
            raise XError("INVALID_TOKEN" if err.startswith("INVALID_TOKEN") else "NOT_CONNECTED", err)
        return {"id": ident["X_USER_ID_MASKED"], "username": ident["X_USERNAME"], "name": ident["X_DISPLAY_NAME"], "access_level": ident.get("access_level")}

    async def _get(self, url: str) -> httpx.Response:
        try:
            return await xauth._http("GET", url, headers=await xauth.signed_headers("GET", url))
        except xauth.XAuthError as e:
            raise XError(e.code, e.description)

    async def credits_probe(self) -> dict:
        """ONE READ in user context on the v2 posts endpoint (same product as the write): 402 -> CREDITS_DEPLETED (STOP before any write)."""
        r = await self._get(f"{X_API}/tweets/20?tweet.fields=id")
        if r.status_code == 200:
            return {"ok": True, "status": 200, "error": None}
        code, detail = xauth._error_code(r)
        return {"ok": False, "status": r.status_code, "error": code, "detail": xauth.scrub(detail)[:200]}

    async def read_post(self, post_id: str) -> dict:
        """READ back a post: id, text, author_id, attached media keys/types, expanded URLs."""
        url = f"{X_API}/tweets/{post_id}?tweet.fields=author_id,text,attachments,entities,created_at&expansions=attachments.media_keys,author_id&media.fields=type,media_key&user.fields=username"
        r = await self._get(url)
        if r.status_code != 200:
            self._raise(r, "READ_POST")
        return r.json() or {}

    async def recent_posts(self, user_id: str, n: int = 5) -> list:
        url = f"{X_API}/users/{user_id}/tweets?max_results={max(5, min(n, 10))}&tweet.fields=text,created_at,attachments"
        r = await self._get(url)
        if r.status_code != 200:
            self._raise(r, "READ_RECENT")
        return (r.json() or {}).get("data") or []

    def _write_allowed(self):
        if not credentials_present():
            raise XError("NOT_CONNECTED", "credenziali app X assenti")
        if not xauth.real_posting_enabled():
            raise XError("WRITES_DISABLED", "X_REAL_POSTING_ENABLED=false: nessuna scrittura verso X")

    async def _post(self, url: str, *, json_body: Any = None, files: Any = None, data: Any = None) -> httpx.Response:
        ct = "application/json" if json_body is not None else None
        headers = await xauth.signed_headers("POST", url, content_type=ct)
        try:
            return await xauth._http("POST", url, headers=headers, json_body=json_body, files=files, data=data, timeout=120.0, write=True)
        except xauth.XAuthError as e:
            raise XError(e.code, e.description)

    @staticmethod
    def _raise(resp: httpx.Response, stage: str):
        code, detail = xauth._error_code(resp)
        raise XError(code, f"{stage}: {detail}")

    @staticmethod
    def _media_id(payload: dict) -> Optional[str]:
        d = payload.get("data") if isinstance(payload, dict) else None
        d = d if isinstance(d, dict) else payload
        mid = d.get("id") or d.get("media_id_string") or d.get("media_id")
        return str(mid) if mid is not None else None

    async def upload_media(self, item: dict) -> str:
        """v2 chunked upload (initialize/append/finalize/status). Returns the X media id. Validates MIME/size on our storage first."""
        self._write_allowed()
        val = await validate_media_source(item)
        if not val["ok"]:
            raise XError("MEDIA_REJECTED", f"{val['reason']} ({item.get('type')}, {item.get('side')})")
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as c:
                r = await c.get(item["url"])
        except httpx.HTTPError as e:
            raise XError("MEDIA_REJECTED", f"download fallito: {type(e).__name__}")
        if r.status_code >= 400:
            raise XError("MEDIA_REJECTED", f"download HTTP {r.status_code}")
        content = r.content
        kind = item.get("type") or "photo"
        if len(content) > LIMITS[kind]:
            raise XError("MEDIA_REJECTED", "TOO_LARGE")
        mime = val["mime"]
        category = "tweet_video" if kind == "video" else "tweet_image"
        init = await self._post(f"{X_MEDIA_UPLOAD}/initialize", json_body={"media_type": mime, "total_bytes": len(content), "media_category": category})
        if init.status_code not in (200, 201, 202):
            self._raise(init, "INIT")
        mid = self._media_id(init.json())
        if not mid:
            raise XError("API_ERROR", "INIT senza media id")
        for i in range(0, len(content), CHUNK):
            seg = i // CHUNK
            ap = await self._post(f"{X_MEDIA_UPLOAD}/{mid}/append", data={"segment_index": str(seg)}, files={"media": (f"chunk{seg}", content[i:i + CHUNK], mime)})
            if ap.status_code not in (200, 201, 204):
                self._raise(ap, f"APPEND_{seg}")
        fin = await self._post(f"{X_MEDIA_UPLOAD}/{mid}/finalize")
        if fin.status_code not in (200, 201):
            self._raise(fin, "FINALIZE")
        info = ((fin.json() or {}).get("data") or fin.json() or {}).get("processing_info") if fin.text else None
        waited = 0.0
        while isinstance(info, dict) and info.get("state") in ("pending", "in_progress") and waited < 180:
            delay = float(info.get("check_after_secs") or 3)
            await asyncio.sleep(delay)
            waited += delay
            url = f"{X_MEDIA_UPLOAD}?command=STATUS&media_id={mid}"
            try:
                st = await xauth._http("GET", url, headers=await xauth.signed_headers("GET", url))
            except xauth.XAuthError as e:
                raise XError(e.code, e.description)
            if st.status_code != 200:
                self._raise(st, "STATUS")
            info = ((st.json() or {}).get("data") or st.json() or {}).get("processing_info")
        if isinstance(info, dict) and info.get("state") == "failed":
            raise XError("MEDIA_REJECTED", f"processing failed: {json.dumps(info.get('error') or {})[:120]}")
        return mid

    async def create_post(self, payload: dict) -> dict:
        """POST /2/tweets {text, media.media_ids, reply.in_reply_to_tweet_id}. Counted as a REAL post."""
        self._write_allowed()
        body: Dict[str, Any] = {"text": payload.get("text") or ""}
        if payload.get("media_ids"):
            body["media"] = {"media_ids": [str(m) for m in payload["media_ids"]]}
        if payload.get("in_reply_to"):
            body["reply"] = {"in_reply_to_tweet_id": str(payload["in_reply_to"])}
        resp = await self._post(f"{X_API}/tweets", json_body=body)
        if resp.status_code not in (200, 201):
            self._raise(resp, "CREATE")
        data = (resp.json() or {}).get("data") or {}
        if not data.get("id"):
            raise XError("API_ERROR", "CREATE senza id")
        return {"id": str(data["id"]), "text": data.get("text")}


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
    """CONNECTION_STATUS: NOT_CONNECTED | CONNECTED | INVALID_TOKEN | API_ERROR (REAL adapter, READ: GET /2/users/me). MOCK_MODE reported SEPARATELY."""
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


async def real_connection_report(live: bool = True, sample_media: Optional[List[dict]] = None) -> dict:
    """READ-ONLY report of the REAL X connection (independent from MOCK_MODE): app auth, user auth, identity, write capability, media readiness.
    Never creates a post, never uploads. live=False uses the saved identity only (no X call)."""
    app = await xauth.app_auth_check() if live else {"X_APP_AUTH_READY": None, "error": "not checked"}
    user_present = await xauth.user_auth_present()
    ident = await xauth.identity_check() if (live and user_present) else {**await xauth.saved_identity(), "X_ACCOUNT_CONNECTED": False, "X_USER_AUTH_READY": False, "X_WRITE_CAPABILITY_READY": None, "error": None if user_present else "NOT_CONNECTED"}
    media_checks = []
    for it in (sample_media or [])[:2]:
        v = await validate_media_source(it)
        media_checks.append({"side": it.get("side"), "type": it.get("type"), **{k: v[k] for k in ("ok", "mime", "bytes", "reason")}})
    media_ready = bool(media_checks) and all(m["ok"] for m in media_checks)
    write_ready = ident.get("X_WRITE_CAPABILITY_READY")
    missing = "NONE"
    if not live:
        missing = "NOT_CHECKED: esegui la verifica live" if not ident.get("X_USERNAME") else "NONE"
    elif not app.get("X_APP_AUTH_READY"):
        missing = "APP_CREDENTIALS_INVALID: verifica X_CONSUMER_KEY / X_CONSUMER_SECRET"
    elif not user_present:
        missing = "USER_AUTH_REQUIRED: apri l'URL di /auth/start e autorizza l'account"
    elif not ident.get("X_ACCOUNT_CONNECTED"):
        missing = f"USER_TOKEN_INVALID: {ident.get('error')}"
    elif write_ready is False:
        missing = "APP_PERMISSIONS_READ_ONLY: " + xauth.MANUAL_STEP_USER_AUTH
    return {"X_PROVIDER": "X API v2 (OAuth 1.0a user context)", "X_CONNECTION_READY": bool(app.get("X_APP_AUTH_READY") and ident.get("X_ACCOUNT_CONNECTED")),
            "X_APP_AUTH_READY": app.get("X_APP_AUTH_READY"), "app_auth": {k: app.get(k) for k in ("bearer_source", "bearer_matches_env", "error")},
            "X_USER_AUTH_READY": bool(ident.get("X_USER_AUTH_READY")), "X_USER_AUTH_PRESENT": user_present, "token_source": ident.get("token_source"),
            "X_ACCOUNT_CONNECTED": bool(ident.get("X_ACCOUNT_CONNECTED")), "X_USERNAME": ident.get("X_USERNAME"), "X_USER_ID_MASKED": ident.get("X_USER_ID_MASKED"),
            "X_DISPLAY_NAME": ident.get("X_DISPLAY_NAME"), "X_WRITE_CAPABILITY_READY": write_ready, "access_level": ident.get("access_level"), "identity_error": ident.get("error"),
            "X_MEDIA_UPLOAD_READY": bool(ident.get("X_ACCOUNT_CONNECTED") and write_ready and media_ready), "media_checks": media_checks,
            "X_POST_CREATE_READY": bool(ident.get("X_ACCOUNT_CONNECTED") and write_ready), "X_THREAD_READY": bool(ident.get("X_ACCOUNT_CONNECTED") and write_ready),
            "X_REAL_POSTING_ENABLED": xauth.real_posting_enabled(), "X_AUTOPILOT_MOCK": mock_enabled(), "X_REAL_CALLS": X_REAL_CALLS["n"], "X_REAL_READ_CALLS": X_REAL_CALLS["read"],
            "REAL_X_POSTS_CREATED": await real_posts_created(), "MISSING_MANUAL_STEP": missing, "checked_at": xauth.now_iso()}
