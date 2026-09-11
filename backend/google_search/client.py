"""HTTP client for Search Console APIs: timeout, bounded retry with backoff on 429/5xx, quota handling and a structured
request log in Mongo (google_search_sync_log). Never logs tokens, credentials or full response bodies."""
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, Optional

import httpx
from urllib.parse import quote

from database import google_search_sync_log_col, now_iso
from .auth import access_token, GoogleAuthError, reset_cache

log = logging.getLogger("lato-segreto.google")
SC_V1 = "https://searchconsole.googleapis.com/v1"
WM_V3 = "https://www.googleapis.com/webmasters/v3"
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
MAX_RETRIES = 3


class GoogleApiError(Exception):
    def __init__(self, kind: str, message: str, status: Optional[int] = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.kind, self.status, self.retry_after = kind, status, retry_after


async def _log(entry: Dict[str, Any]):
    try:
        await google_search_sync_log_col.insert_one({"id": str(uuid.uuid4()), "timestamp": now_iso(), **entry})
    except Exception:  # logging must never break the caller
        pass


async def request(method: str, url: str, *, json: Optional[dict] = None, params: Optional[dict] = None, op: str = "", entity: Optional[dict] = None) -> dict:
    """Authenticated request with retry. Raises GoogleApiError(kind in: auth, quota, rate_limit, not_found, forbidden, server, network, invalid)."""
    rid = str(uuid.uuid4())
    t0 = time.time()
    attempt, last_err = 0, None
    while attempt < MAX_RETRIES:
        attempt += 1
        try:
            token = await access_token(force=attempt > 1 and isinstance(last_err, GoogleApiError) and last_err.kind == "auth")
        except GoogleAuthError as e:
            await _log({"request_id": rid, "op": op, "entity": entity, "status": "error", "error_type": "auth", "error": str(e)[:160], "duration_ms": int((time.time() - t0) * 1000), "attempt": attempt})
            raise GoogleApiError("auth", str(e))
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers={"Authorization": f"Bearer {token}", "User-Agent": "LatoSegreto-GoogleSearch/1.0"}) as c:
                r = await c.request(method, url, json=json, params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_err = GoogleApiError("network", type(e).__name__)
            await asyncio.sleep(min(2 ** attempt, 8))
            continue
        dur = int((time.time() - t0) * 1000)
        if r.status_code < 300:
            await _log({"request_id": rid, "op": op, "entity": entity, "status": "ok", "http_status": r.status_code, "duration_ms": dur, "attempt": attempt})
            try:
                return r.json() if r.content else {}
            except Exception:
                return {}
        # error mapping (body summarized, never dumped)
        try:
            body = r.json()
            msg = ((body.get("error") or {}).get("message") or "")[:200]
            reason = ",".join(sorted({(d.get("reason") or "") for d in (body.get("error") or {}).get("errors", []) if isinstance(d, dict)}))[:80]
        except Exception:
            msg, reason = r.text[:200], ""
        if r.status_code == 429 or (r.status_code == 403 and ("quota" in reason.lower() or "rateLimit" in reason or "quota" in msg.lower())):
            ra = int(r.headers.get("Retry-After", "0") or 0)
            last_err = GoogleApiError("quota" if "daily" in msg.lower() or "quota" in reason.lower() else "rate_limit", msg or "quota exceeded", r.status_code, ra)
            await _log({"request_id": rid, "op": op, "entity": entity, "status": "error", "http_status": r.status_code, "error_type": last_err.kind, "error": msg, "duration_ms": dur, "attempt": attempt, "retry_after": ra})
            if last_err.kind == "quota":
                raise last_err
            await asyncio.sleep(min(max(ra, 2 ** attempt), 30))
            continue
        if r.status_code == 401:
            reset_cache()
            last_err = GoogleApiError("auth", msg or "unauthorized", 401)
            await _log({"request_id": rid, "op": op, "entity": entity, "status": "error", "http_status": 401, "error_type": "auth", "error": msg, "duration_ms": dur, "attempt": attempt})
            continue
        kind = {403: "forbidden", 404: "not_found", 400: "invalid"}.get(r.status_code, "server" if r.status_code >= 500 else "invalid")
        await _log({"request_id": rid, "op": op, "entity": entity, "status": "error", "http_status": r.status_code, "error_type": kind, "error": msg, "duration_ms": dur, "attempt": attempt})
        if kind == "server":
            last_err = GoogleApiError(kind, msg, r.status_code)
            await asyncio.sleep(min(2 ** attempt, 8))
            continue
        raise GoogleApiError(kind, msg or f"http {r.status_code}", r.status_code)
    raise last_err or GoogleApiError("server", "retries exhausted")


# ---------------- typed wrappers (one per Google operation) ----------------
def _site(site: str) -> str:
    return quote(site, safe="")


async def list_sites() -> dict:
    return await request("GET", f"{WM_V3}/sites", op="sites.list")


async def list_sitemaps(site: str) -> dict:
    return await request("GET", f"{WM_V3}/sites/{_site(site)}/sitemaps", op="sitemaps.list")


async def submit_sitemap(site: str, feed: str) -> dict:
    return await request("PUT", f"{WM_V3}/sites/{_site(site)}/sitemaps/{quote(feed, safe='')}", op="sitemaps.submit", entity={"feed": feed})


async def inspect_url(site: str, url: str, language: str = "it-IT") -> dict:
    return await request("POST", f"{SC_V1}/urlInspection/index:inspect", json={"inspectionUrl": url, "siteUrl": site, "languageCode": language}, op="urlInspection.inspect", entity={"url": url})


async def search_analytics(site: str, body: dict) -> dict:
    return await request("POST", f"{WM_V3}/sites/{_site(site)}/searchAnalytics/query", json=body, op="searchanalytics.query", entity={"dimensions": body.get("dimensions")})
