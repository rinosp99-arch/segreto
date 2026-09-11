"""Service-account access token for the Search Console API (scope: webmasters). Cached until 5 minutes before expiry.
The token and the private key never leave this module (no logging, no API exposure)."""
import asyncio
import time
from typing import Optional

from .config import cfg

SCOPES = ["https://www.googleapis.com/auth/webmasters"]
_cache = {"token": None, "exp": 0.0}
_lock = asyncio.Lock()


class GoogleAuthError(Exception):
    pass


def _fetch_token_sync() -> tuple:
    info = cfg.credentials_info()
    if not info:
        raise GoogleAuthError("credentials_missing")
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except Exception as e:  # pragma: no cover
        raise GoogleAuthError(f"google-auth unavailable: {type(e).__name__}")
    try:
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        creds.refresh(Request())
    except Exception as e:
        raise GoogleAuthError(f"token_refresh_failed: {type(e).__name__}")
    exp = creds.expiry.timestamp() if creds.expiry else time.time() + 3000
    return creds.token, exp


async def access_token(force: bool = False) -> Optional[str]:
    async with _lock:
        if not force and _cache["token"] and _cache["exp"] - time.time() > 300:
            return _cache["token"]
        loop = asyncio.get_running_loop()
        token, exp = await loop.run_in_executor(None, _fetch_token_sync)
        _cache["token"], _cache["exp"] = token, exp
        return token


def reset_cache():
    _cache["token"], _cache["exp"] = None, 0.0
