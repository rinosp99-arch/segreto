"""X (Twitter) real connection — backend only. App credentials from env (X_CONSUMER_KEY / X_CONSUMER_SECRET / X_BEARER_TOKEN, legacy X_API_KEY / X_API_SECRET
accepted), user tokens (OAuth 1.0a access token + secret) obtained with the documented 3-legged flow and stored ENCRYPTED (Fernet, key derived from the
consumer secret) in Mongo `x_autopilot_auth`, or taken from env X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET when present. Nothing here ever creates a post:
only oauth/request_token, oauth/access_token, oauth2/token (app bearer), GET /2/users/me, GET 1.1 account/verify_credentials (access level, READ).
Every HTTP call to X increments adapter.X_REAL_CALLS. Secrets are never returned, never logged (scrub())."""
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl, quote, urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from oauthlib.oauth1 import Client as OAuth1Client

from database import db

X_API = "https://api.x.com"
REQUEST_TOKEN_URL = f"{X_API}/oauth/request_token"
AUTHORIZE_URL = f"{X_API}/oauth/authorize"
ACCESS_TOKEN_URL = f"{X_API}/oauth/access_token"
APP_BEARER_URL = f"{X_API}/oauth2/token"
ME_URL = f"{X_API}/2/users/me"
VERIFY_CREDENTIALS_URL = f"{X_API}/1.1/account/verify_credentials.json"
TIMEOUT = 25.0
PENDING_TTL_S = 15 * 60

auth_col = db["x_autopilot_auth"]
CALLS = {"n": 0, "read": 0}               # "n" = REAL WRITE calls (upload/create) — must stay 0 until the real test; "read" = auth/identity reads
_loaded_secrets: set = set()              # runtime secrets (DB tokens) so scrub() can mask them too


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ env
def consumer_key() -> str:
    return (os.environ.get("X_CONSUMER_KEY") or os.environ.get("X_API_KEY") or "").strip()


def consumer_secret() -> str:
    return (os.environ.get("X_CONSUMER_SECRET") or os.environ.get("X_API_SECRET") or "").strip()


def env_bearer() -> str:
    return (os.environ.get("X_BEARER_TOKEN") or "").strip()


def env_user_token() -> Tuple[str, str]:
    return (os.environ.get("X_ACCESS_TOKEN") or "").strip(), (os.environ.get("X_ACCESS_TOKEN_SECRET") or "").strip()


def app_credentials_present() -> bool:
    return bool(consumer_key() and consumer_secret())


def real_posting_enabled() -> bool:
    """Master write gate for REAL X posts/uploads (default false). Independent from X_AUTOPILOT_MOCK."""
    return os.environ.get("X_REAL_POSTING_ENABLED", "false").lower() in ("1", "true", "yes")


def callback_url(request_headers: Optional[Dict[str, str]] = None) -> str:
    """X_OAUTH_CALLBACK_URL if set, else https://<public host>/api/admin/x-autopilot/auth/callback from the forwarded host."""
    env = (os.environ.get("X_OAUTH_CALLBACK_URL") or "").strip()
    if env:
        return env
    h = {k.lower(): v for k, v in (request_headers or {}).items()}
    host = (h.get("x-forwarded-host") or h.get("host") or "").split(",")[0].strip()
    return f"https://{host}/api/admin/x-autopilot/auth/callback" if host else ""


def mask(value: Optional[str], keep: int = 3) -> Optional[str]:
    if not value:
        return None
    v = str(value)
    return "*" * max(4, len(v) - keep) + v[-keep:]


def all_secret_values() -> set:
    vals = {consumer_secret(), env_bearer(), *env_user_token(), consumer_key()} | set(_loaded_secrets)
    return {v for v in vals if v and len(v) >= 8}


def scrub(text: Any) -> str:
    out = str(text or "")
    for v in sorted(all_secret_values(), key=len, reverse=True):
        out = out.replace(v, "***REDACTED***")
        out = out.replace(quote(v, safe=""), "***REDACTED***")
    return out


class XAuthError(Exception):
    def __init__(self, code: str, description: str = "", status: Optional[int] = None):
        super().__init__(f"{code}: {scrub(description)}")
        self.code, self.description, self.status = code, scrub(description), status


# ------------------------------------------------------------------ encryption at rest (Fernet key derived from the consumer secret; backend only)
def _fernet() -> Fernet:
    if not consumer_secret():
        raise XAuthError("NOT_CONFIGURED", "X_CONSUMER_SECRET assente")
    key = hashlib.sha256(("lato-segreto:x-autopilot:" + consumer_secret()).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(obj: dict) -> str:
    return _fernet().encrypt(json.dumps(obj).encode()).decode()


def decrypt(token: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(token.encode()).decode())
    except InvalidToken:
        raise XAuthError("TOKEN_UNREADABLE", "token cifrato non decifrabile (consumer secret cambiato?)")


# ------------------------------------------------------------------ HTTP (every call counted; errors scrubbed)
async def _http(method: str, url: str, *, headers: Optional[dict] = None, data: Any = None, content: Any = None, json_body: Any = None, files: Any = None,
                params: Optional[dict] = None, timeout: float = TIMEOUT, write: bool = False) -> httpx.Response:
    CALLS["n" if write else "read"] += 1
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            return await c.request(method, url, headers=headers, data=data, content=content, json=json_body, files=files, params=params)
    except httpx.HTTPError as e:
        raise XAuthError("NETWORK_ERROR", f"{type(e).__name__}")


def _oauth1_headers(method: str, url: str, *, token: Optional[str] = None, token_secret: Optional[str] = None, callback: Optional[str] = None,
                    verifier: Optional[str] = None, body: Optional[str] = None, content_type: Optional[str] = None) -> Dict[str, str]:
    """OAuth 1.0a HMAC-SHA1 Authorization header (oauthlib). Form bodies are part of the signature base string, JSON/multipart are not (spec)."""
    if not app_credentials_present():
        raise XAuthError("NOT_CONFIGURED", "X_CONSUMER_KEY / X_CONSUMER_SECRET assenti")
    client = OAuth1Client(consumer_key(), client_secret=consumer_secret(), resource_owner_key=token or None, resource_owner_secret=token_secret or None,
                          callback_uri=callback, verifier=verifier)
    headers = {"Content-Type": content_type} if content_type else {}
    _, signed_headers, _ = client.sign(url, http_method=method, body=body if content_type == "application/x-www-form-urlencoded" else None, headers=headers)
    return {k: v for k, v in signed_headers.items()}


def _error_code(resp: httpx.Response) -> Tuple[str, str]:
    body = resp.text[:300]
    if resp.status_code == 401:
        return "INVALID_TOKEN", body
    if resp.status_code == 403:
        return "FORBIDDEN", body
    if resp.status_code == 429:
        return "RATE_LIMITED", body
    return "API_ERROR", f"HTTP {resp.status_code}: {body}"


# ------------------------------------------------------------------ APP auth (bearer): documented client-credentials exchange, never a write
async def app_auth_check() -> dict:
    """Validates consumer key/secret by obtaining the app bearer (POST oauth2/token, documented) and compares it with X_BEARER_TOKEN.
    Result never includes token values."""
    out = {"X_APP_AUTH_READY": False, "bearer_source": None, "bearer_matches_env": None, "error": None, "checked_at": now_iso()}
    if not app_credentials_present():
        out["error"] = "NOT_CONFIGURED"
        return out
    basic = base64.b64encode(f"{quote(consumer_key(), safe='')}:{quote(consumer_secret(), safe='')}".encode()).decode()
    resp = await _http("POST", APP_BEARER_URL, headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                       content="grant_type=client_credentials")
    if resp.status_code != 200:
        code, detail = _error_code(resp)
        out["error"] = f"{code}: {scrub(detail)}"
        return out
    try:
        bearer = (resp.json() or {}).get("access_token") or ""
    except ValueError:
        bearer = ""
    if not bearer:
        out["error"] = "API_ERROR: bearer assente nella risposta"
        return out
    _loaded_secrets.add(bearer)
    await auth_col.update_one({"id": "app_bearer"}, {"$set": {"id": "app_bearer", "enc": encrypt({"bearer": bearer}), "obtained_at": now_iso()}}, upsert=True)
    out.update(X_APP_AUTH_READY=True, bearer_source="oauth2/token", bearer_matches_env=(bearer == env_bearer()) if env_bearer() else None)
    return out


# ------------------------------------------------------------------ USER auth (OAuth 1.0a 3-legged)
async def start_user_auth(cb_url: str) -> dict:
    """Step 1: POST oauth/request_token (oauth_callback) -> authorize URL. The request-token secret is stored encrypted (pending, 15')."""
    if not cb_url:
        raise XAuthError("CALLBACK_MISSING", "callback URL non determinabile: imposta X_OAUTH_CALLBACK_URL")
    headers = _oauth1_headers("POST", REQUEST_TOKEN_URL, callback=cb_url)
    resp = await _http("POST", REQUEST_TOKEN_URL, headers=headers)
    if resp.status_code != 200:
        code, detail = _error_code(resp)
        low = detail.lower()
        if "callback" in low or "oob" in low or resp.status_code in (401, 403):
            raise XAuthError("CALLBACK_NOT_APPROVED", detail, resp.status_code)
        raise XAuthError(code, detail, resp.status_code)
    data = dict(parse_qsl(resp.text))
    tok, sec, confirmed = data.get("oauth_token"), data.get("oauth_token_secret"), data.get("oauth_callback_confirmed")
    if not tok or not sec or str(confirmed).lower() != "true":
        raise XAuthError("API_ERROR", "request_token incompleto o callback non confermata")
    _loaded_secrets.add(sec)
    await auth_col.update_one({"id": "pending"}, {"$set": {"id": "pending", "oauth_token": tok, "enc": encrypt({"secret": sec}), "callback": cb_url, "created_at": now_iso()}}, upsert=True)
    return {"authorize_url": f"{AUTHORIZE_URL}?{urlencode({'oauth_token': tok})}", "callback": cb_url, "expires_in_s": PENDING_TTL_S}


async def finish_user_auth(oauth_token: str, oauth_verifier: str) -> dict:
    """Step 3 (callback): validates the pending request token, POST oauth/access_token, stores the user token ENCRYPTED, verifies identity (READ)."""
    pend = await auth_col.find_one({"id": "pending"}, {"_id": 0})
    if not pend or pend.get("oauth_token") != oauth_token:
        raise XAuthError("STATE_MISMATCH", "oauth_token non corrisponde alla richiesta in corso")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(pend["created_at"])).total_seconds()
    except (KeyError, ValueError):
        age = PENDING_TTL_S + 1
    if age > PENDING_TTL_S:
        await auth_col.delete_one({"id": "pending"})
        raise XAuthError("EXPIRED", "autorizzazione scaduta: ripeti /auth/start")
    req_secret = decrypt(pend["enc"])["secret"]
    body = urlencode({"oauth_verifier": oauth_verifier})
    headers = _oauth1_headers("POST", ACCESS_TOKEN_URL, token=oauth_token, token_secret=req_secret, verifier=oauth_verifier, body=body,
                              content_type="application/x-www-form-urlencoded")
    resp = await _http("POST", ACCESS_TOKEN_URL, headers=headers, content=body)
    if resp.status_code != 200:
        code, detail = _error_code(resp)
        raise XAuthError(code, detail, resp.status_code)
    data = dict(parse_qsl(resp.text))
    tok, sec = data.get("oauth_token"), data.get("oauth_token_secret")
    if not tok or not sec:
        raise XAuthError("API_ERROR", "access_token incompleto")
    _loaded_secrets.update({tok, sec})
    await auth_col.update_one({"id": "user_token"}, {"$set": {"id": "user_token", "enc": encrypt({"token": tok, "secret": sec}), "user_id": str(data.get("user_id") or ""),
                              "username": data.get("screen_name"), "obtained_at": now_iso(), "source": "oauth1_3legged"}}, upsert=True)
    await auth_col.delete_one({"id": "pending"})
    ident = await identity_check()
    return {"status": "CONNECTED" if ident.get("X_ACCOUNT_CONNECTED") else "TOKEN_SAVED_IDENTITY_FAILED", **{k: v for k, v in ident.items() if k != "error"}, "error": ident.get("error")}


async def load_user_token() -> Tuple[Optional[str], Optional[str], str]:
    """(token, secret, source). Env override first, then the encrypted DB record."""
    t, s = env_user_token()
    if t and s:
        return t, s, "env"
    doc = await auth_col.find_one({"id": "user_token"}, {"_id": 0})
    if not doc:
        return None, None, "none"
    d = decrypt(doc["enc"])
    _loaded_secrets.update({d["token"], d["secret"]})
    return d["token"], d["secret"], "db"


async def user_auth_present() -> bool:
    t, s, _ = await load_user_token()
    return bool(t and s)


async def signed_headers(method: str, url: str, *, body: Optional[str] = None, content_type: Optional[str] = None) -> Dict[str, str]:
    """User-context OAuth 1.0a headers for any X call (used by the real adapter)."""
    t, s, _ = await load_user_token()
    if not (t and s):
        raise XAuthError("NOT_CONNECTED", "token utente X assente: completa /auth/start")
    return _oauth1_headers(method, url, token=t, token_secret=s, body=body, content_type=content_type)


async def identity_check() -> dict:
    """READ: GET /2/users/me (user context) + access level from GET 1.1 account/verify_credentials (x-access-level header). Stores public identity only."""
    out = {"X_ACCOUNT_CONNECTED": False, "X_USERNAME": None, "X_USER_ID_MASKED": None, "X_DISPLAY_NAME": None, "X_USER_AUTH_READY": False,
           "X_WRITE_CAPABILITY_READY": None, "access_level": None, "token_source": None, "error": None, "checked_at": now_iso()}
    t, s, src = await load_user_token()
    out["token_source"] = src
    if not (t and s):
        out["error"] = "NOT_CONNECTED"
        return out
    url = f"{ME_URL}?user.fields=id,name,username"
    resp = await _http("GET", url, headers=_oauth1_headers("GET", url, token=t, token_secret=s))
    if resp.status_code != 200:
        code, detail = _error_code(resp)
        out["error"] = f"{code}: {scrub(detail)}"
        return out
    me = (resp.json() or {}).get("data") or {}
    out.update(X_ACCOUNT_CONNECTED=bool(me.get("id")), X_USERNAME=me.get("username"), X_USER_ID_MASKED=mask(me.get("id")), X_DISPLAY_NAME=me.get("name"), X_USER_AUTH_READY=bool(me.get("id")))
    level = (resp.headers.get("x-access-level") or "").lower()
    if not level:
        r2 = await _http("GET", VERIFY_CREDENTIALS_URL, headers=_oauth1_headers("GET", VERIFY_CREDENTIALS_URL, token=t, token_secret=s))
        level = (r2.headers.get("x-access-level") or "").lower()
        if not level and r2.status_code == 200:
            level = "unknown"
    out["access_level"] = level or None
    out["X_WRITE_CAPABILITY_READY"] = True if level.startswith("read-write") else (False if level in ("read",) else None)
    await auth_col.update_one({"id": "identity"}, {"$set": {"id": "identity", "user_id": str(me.get("id") or ""), "username": me.get("username"), "name": me.get("name"),
                              "access_level": level or None, "checked_at": now_iso()}}, upsert=True)
    return out


async def saved_identity() -> dict:
    doc = await auth_col.find_one({"id": "identity"}, {"_id": 0}) or {}
    return {"X_USERNAME": doc.get("username"), "X_USER_ID_MASKED": mask(doc.get("user_id")), "X_DISPLAY_NAME": doc.get("name"), "access_level": doc.get("access_level"), "checked_at": doc.get("checked_at")}


async def disconnect() -> dict:
    """Forget the stored user token (DB only). Env tokens, if any, are untouched."""
    r = await auth_col.delete_many({"id": {"$in": ["user_token", "pending", "identity"]}})
    return {"deleted": r.deleted_count}


MANUAL_STEP_USER_AUTH = ("X Developer Portal → Projects & Apps → la tua App → 'User authentication settings' → Set up: App permissions = 'Read and write'; "
                         "Type of App = 'Web App, Automated App or Bot'; Callback URI / Redirect URL = <callback>; Website URL = https://secret-side.emergent.host → Save. "
                         "Poi ripeti /auth/start.")
