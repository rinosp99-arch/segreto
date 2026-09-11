"""Deterministic mock adapter (GOOGLE_SEARCH_MOCK=1): lets the whole flow (capabilities, cache, states, sync log) be
tested without Google credentials. Behaviour is derived from the URL so tests are stable."""
import hashlib
from datetime import datetime, timedelta, timezone

_SUBMITTED = {}


def _h(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)


async def list_sites():
    return {"siteEntry": [{"siteUrl": "https://secret-side.emergent.host/", "permissionLevel": "siteFullUser"}]}


async def list_sitemaps(site: str):
    out = []
    for feed, ts in _SUBMITTED.items():
        out.append({"path": feed, "lastSubmitted": ts, "isPending": False, "lastDownloaded": ts, "warnings": "0", "errors": "0", "contents": [{"type": "web", "submitted": "12", "indexed": "9"}]})
    return {"sitemap": out}


async def submit_sitemap(site: str, feed: str):
    _SUBMITTED[feed] = datetime.now(timezone.utc).isoformat()
    return {}


async def inspect_url(site: str, url: str, language: str = "it-IT"):
    """URL containing 'notindexed' -> crawled not indexed; 'blocked' -> robots blocked; 'unknown' -> unknown to Google;
    'error' -> fetch error; everything else -> indexed."""
    now = datetime.now(timezone.utc)
    last = (now - timedelta(hours=_h(url) % 72 + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if "notindexed" in url:
        res = {"verdict": "NEUTRAL", "coverageState": "Crawled - currently not indexed", "robotsTxtState": "ALLOWED", "indexingState": "INDEXING_ALLOWED", "pageFetchState": "SUCCESSFUL", "lastCrawlTime": last, "googleCanonical": url, "userCanonical": url}
    elif "blocked" in url:
        res = {"verdict": "FAIL", "coverageState": "Blocked by robots.txt", "robotsTxtState": "DISALLOWED", "indexingState": "BLOCKED_BY_ROBOTS_TXT", "pageFetchState": "BLOCKED_ROBOTS_TXT"}
    elif "unknown" in url:
        res = {"verdict": "NEUTRAL", "coverageState": "URL is unknown to Google", "robotsTxtState": "ROBOTS_TXT_STATE_UNSPECIFIED", "indexingState": "INDEXING_STATE_UNSPECIFIED", "pageFetchState": "PAGE_FETCH_STATE_UNSPECIFIED"}
    elif "error" in url:
        res = {"verdict": "FAIL", "coverageState": "Server error (5xx)", "robotsTxtState": "ALLOWED", "indexingState": "INDEXING_ALLOWED", "pageFetchState": "SERVER_ERROR", "lastCrawlTime": last}
    else:
        res = {"verdict": "PASS", "coverageState": "Submitted and indexed", "robotsTxtState": "ALLOWED", "indexingState": "INDEXING_ALLOWED", "pageFetchState": "SUCCESSFUL", "lastCrawlTime": last, "googleCanonical": url, "userCanonical": url, "sitemap": [f"{site}api/sitemap.xml"]}
    return {"inspectionResult": {"inspectionResultLink": "https://search.google.com/search-console/inspect?resource_id=mock", "indexStatusResult": res}}


async def search_analytics(site: str, body: dict):
    dims = body.get("dimensions") or []
    pages = [f"{site}", f"{site}modelle/vanessa-bella", f"{site}modelle/alessia-golosa", f"{site}modelle/aurora-bianchini"]
    queries = ["lato segreto", "vanessa bella onlyfans", "modelle italiane premium", "alessia golosa", "aurora bianchini"]
    flt = None
    for g in body.get("dimensionFilterGroups") or []:
        for f in g.get("filters") or []:
            if f.get("dimension") == "page":
                flt = f.get("expression")
    rows = []
    if not dims:
        rows = [{"keys": [], "clicks": 42, "impressions": 1830, "ctr": 42 / 1830, "position": 14.2}]
    elif dims == ["query"]:
        for i, q in enumerate(queries):
            rows.append({"keys": [q], "clicks": 20 - i * 3, "impressions": 600 - i * 90, "ctr": (20 - i * 3) / (600 - i * 90), "position": 6.5 + i * 2.1})
    elif dims == ["page"]:
        for i, p in enumerate(pages):
            if flt and flt not in p:
                continue
            rows.append({"keys": [p], "clicks": 18 - i * 4, "impressions": 700 - i * 120, "ctr": (18 - i * 4) / (700 - i * 120), "position": 8.0 + i * 3})
    elif dims == ["date"]:
        start = datetime.strptime(body["startDate"], "%Y-%m-%d")
        end = datetime.strptime(body["endDate"], "%Y-%m-%d")
        d = start
        while d <= end:
            rows.append({"keys": [d.strftime("%Y-%m-%d")], "clicks": 1 + _h(d.isoformat()) % 4, "impressions": 40 + _h(d.isoformat()) % 50, "ctr": 0.03, "position": 12.0})
            d += timedelta(days=1)
    return {"rows": rows[: body.get("rowLimit", 1000)], "responseAggregationType": "byPage"}
