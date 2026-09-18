"""Business-level Google Search functions. Every Google call goes through client.py (or mock.py when GOOGLE_SEARCH_MOCK=1).
Nothing here can block the public site: all functions return structured results/errors, never raise to the caller."""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from database import (google_search_status_col, google_search_analytics_col, google_search_state_col, google_search_sync_log_col,
                      models_col, landings_col, categories_col, config_col, now_iso, now_dt)
from .config import cfg

STATES = ("INDEXED", "NOT_INDEXED", "BLOCKED_ERROR", "UNKNOWN", "NOT_INSPECTED", "NOT_CONFIGURED")


def _adapter():
    if cfg.mock:
        from . import mock as m
        return m
    from . import client as c
    return c


def configured() -> bool:
    return cfg.mock or (cfg.enabled and cfg.credentials_info() is not None)


_base_cache = {"v": None, "at": 0.0}


def public_base() -> str:
    """Canonical public origin: config site.base_url (if set) else the Search Console property origin. Cached 60s (sync accessor)."""
    return _base_cache["v"] or cfg.public_base


async def refresh_public_base() -> str:
    import time
    if time.time() - _base_cache["at"] > 60:
        c = await config_col.find_one({"id": "global"}, {"_id": 0, "site": 1}) or {}
        _base_cache["v"] = ((c.get("site") or {}).get("base_url") or "").rstrip("/") or cfg.public_base
        _base_cache["at"] = time.time()
    return _base_cache["v"]


def sitemap_url() -> str:
    return f"{public_base()}/api/sitemap.xml"


def _err(e: Exception) -> dict:
    from .client import GoogleApiError
    if isinstance(e, GoogleApiError):
        return {"error_type": e.kind, "message": str(e)[:200], "http_status": e.status, "retry_after": e.retry_after}
    return {"error_type": "internal", "message": f"{type(e).__name__}"[:200]}


# ================================================================== STATUS
async def status() -> dict:
    """Connection + property + sitemap sync state + inspection budget. Never returns credentials."""
    await refresh_public_base()
    state = await google_search_state_col.find_one({"id": "global"}, {"_id": 0}) or {}
    out = {"enabled": cfg.enabled, "mock": cfg.mock, "configured": configured(), "property": cfg.property_url, "public_base": public_base(),
           "sitemap_url": sitemap_url(), "features": {"sitemap_sync": cfg.sync_enabled, "inspection": cfg.inspection_enabled, "analytics": cfg.analytics_enabled},
           "credentials": cfg.credentials_summary(), "sitemap": {"dirty": bool(state.get("sitemap_dirty")), "dirty_reason": state.get("sitemap_dirty_reason"),
                                                                 "last_submitted_at": state.get("sitemap_last_submitted_at"), "last_submit_result": state.get("sitemap_last_submit_result"),
                                                                 "last_hash": state.get("sitemap_last_hash")},
           "inspection_budget": {"daily_budget": cfg.inspection_daily_budget, "used_today": await _inspections_today(), "cache_hours": cfg.inspection_cache_hours},
           "connection": {"status": "NOT_CONFIGURED", "detail": None}, "url_states": await _state_counts(), "checked_at": now_iso()}
    if not configured():
        out["connection"]["detail"] = "Imposta GOOGLE_SEARCH_ENABLED=true e GOOGLE_SEARCH_CREDENTIALS_JSON (service account) sul server; aggiungi l'email del service account come utente della proprietà Search Console"
        return out
    try:
        sites = await _adapter().list_sites()
        entries = sites.get("siteEntry") or []
        mine = next((s for s in entries if s.get("siteUrl") == cfg.property_url), None)
        out["connection"] = {"status": "CONNECTED" if mine else "PROPERTY_NOT_ACCESSIBLE", "permission": (mine or {}).get("permissionLevel"),
                             "detail": None if mine else f"Il service account non vede la proprietà {cfg.property_url}: aggiungilo come utente (Completo) in Search Console", "properties_visible": len(entries)}
        out["last_error"] = await _last_error()
    except Exception as e:
        out["connection"] = {"status": "ERROR", **_err(e)}
    return out


async def _last_error() -> Optional[dict]:
    d = await google_search_sync_log_col.find_one({"status": "error"}, {"_id": 0, "timestamp": 1, "op": 1, "error_type": 1, "error": 1}, sort=[("timestamp", -1)])
    return d


async def _state_counts() -> dict:
    out = {s: 0 for s in STATES if s not in ("NOT_CONFIGURED",)}
    async for d in google_search_status_col.find({}, {"_id": 0, "google.state": 1}):
        st = ((d.get("google") or {}).get("state")) or "NOT_INSPECTED"
        out[st] = out.get(st, 0) + 1
    return out


# ================================================================== SITEMAP SYNC (debounced)
from .state import mark_sitemap_dirty  # noqa: E402,F401  (leaf module: keeps mutation paths free of this service layer)


async def _sitemap_hash() -> str:
    from v1_seo import sitemap_entries
    entries = await sitemap_entries(await refresh_public_base())
    return hashlib.sha256("|".join(sorted(e["loc"] for e in entries)).encode()).hexdigest()[:16], len(entries)


async def sitemap_sync(force: bool = False, dry_run: bool = False) -> dict:
    """Submit the sitemap to Search Console only when useful: dirty flag or content hash changed, and not more often than
    the debounce window (unless force). Returns what was (or would be) done + Google's registered sitemap status."""
    state = await google_search_state_col.find_one({"id": "global"}, {"_id": 0}) or {}
    h, n = await _sitemap_hash()
    last = state.get("sitemap_last_submitted_at")
    recent = False
    if last:
        try:
            recent = datetime.now(timezone.utc) - datetime.fromisoformat(last) < timedelta(hours=cfg.sitemap_debounce_hours)
        except Exception:
            recent = False
    changed = h != state.get("sitemap_last_hash")
    reason = "force" if force else ("sitemap_changed" if changed else ("dirty_flag" if state.get("sitemap_dirty") else None))
    if reason and recent and not force:
        reason_skip = f"debounce: ultimo invio {last} (< {cfg.sitemap_debounce_hours}h)"
    else:
        reason_skip = None if reason else "nessuna modifica: sitemap identica all'ultimo invio"
    out = {"sitemap_url": sitemap_url(), "urls": n, "hash": h, "changed": changed, "dirty": bool(state.get("sitemap_dirty")), "would_submit": bool(reason and not reason_skip),
           "reason": reason, "skipped_reason": reason_skip, "dry_run": dry_run, "configured": configured(), "sync_enabled": cfg.sync_enabled}
    if dry_run or not out["would_submit"]:
        if configured():
            out["registered"] = await _registered_sitemap()
        return out
    # sync_enabled governs the AUTOMATIC job only; an explicit manual request (force=true via the capability) may submit once.
    if not configured() or (not cfg.sync_enabled and not force):
        out.update({"submitted": False, "skipped_reason": "Search Console non configurata o sync automatico disattivato (usa force=true per un invio manuale)"})
        return out
    try:
        await _adapter().submit_sitemap(cfg.property_url, sitemap_url())
        await google_search_state_col.update_one({"id": "global"}, {"$set": {"sitemap_dirty": False, "sitemap_dirty_reason": None, "sitemap_last_submitted_at": now_iso(),
                                                                              "sitemap_last_hash": h, "sitemap_last_submit_result": "ok"}}, upsert=True)
        out.update({"submitted": True, "submitted_at": now_iso(), "registered": await _registered_sitemap()})
    except Exception as e:
        err = _err(e)
        await google_search_state_col.update_one({"id": "global"}, {"$set": {"sitemap_last_submit_result": f"error:{err['error_type']}"}}, upsert=True)
        out.update({"submitted": False, "error": err})
    return out


async def _registered_sitemap() -> Optional[dict]:
    try:
        lst = await _adapter().list_sitemaps(cfg.property_url)
        for s in lst.get("sitemap") or []:
            if s.get("path") == sitemap_url():
                return {k: s.get(k) for k in ("path", "lastSubmitted", "lastDownloaded", "isPending", "warnings", "errors", "contents")}
        return {"path": sitemap_url(), "registered": False, "others": [s.get("path") for s in (lst.get("sitemap") or [])][:5]}
    except Exception as e:
        return {"error": _err(e)}


# ================================================================== URL INSPECTION (cached, budgeted)
def map_state(res: dict) -> str:
    """Google inspection result -> our 4 states. INDEXED only when Google says so (verdict PASS / coverage 'indexed')."""
    if not res:
        return "UNKNOWN"
    cov = (res.get("coverageState") or "").lower()
    verdict = res.get("verdict")
    fetch = res.get("pageFetchState") or ""
    idx = res.get("indexingState") or ""
    robots = res.get("robotsTxtState") or ""
    if verdict == "PASS" or ("indexed" in cov and "not indexed" not in cov):
        return "INDEXED"
    if robots == "DISALLOWED" or idx.startswith("BLOCKED") or fetch in ("BLOCKED_ROBOTS_TXT", "SERVER_ERROR", "NOT_FOUND", "ACCESS_DENIED", "REDIRECT_ERROR", "SOFT_404", "BLOCKED_4XX", "INTERNAL_CRAWL_ERROR", "INVALID_URL") or verdict == "FAIL":
        return "BLOCKED_ERROR"
    if "unknown to google" in cov or not cov:
        return "UNKNOWN"
    if "not indexed" in cov or "discovered" in cov or "crawled" in cov or "excluded" in cov or "duplicate" in cov or verdict == "NEUTRAL":
        return "NOT_INDEXED"
    return "UNKNOWN"


async def _inspections_today() -> int:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    st = await google_search_state_col.find_one({"id": "global"}, {"_id": 0, "inspections": 1}) or {}
    return int(((st.get("inspections") or {}).get(day)) or 0)


async def _count_inspection():
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await google_search_state_col.update_one({"id": "global"}, {"$inc": {f"inspections.{day}": 1}}, upsert=True)


async def resolve_entity_url(entity_type: str, ref: str) -> Optional[dict]:
    """model|landing|category|home + slug/id -> {url, entity_type, entity_id, slug, published, indexable}."""
    base = await refresh_public_base()
    if entity_type == "home":
        return {"url": f"{base}/", "entity_type": "home", "entity_id": "home", "slug": "", "published": True, "indexable": True}
    col, path = {"model": (models_col, "modelle"), "landing": (landings_col, "l"), "category": (categories_col, "categorie")}.get(entity_type, (None, None))
    if col is None:
        return None
    doc = await col.find_one({"is_deleted": {"$ne": True}, "$or": [{"id": ref}, {"slug": ref}]}, {"_id": 0, "id": 1, "slug": 1, "stato": 1, "seo": 1, "anteprima": 1, "indicizzabile": 1})
    if not doc:
        return None
    seo = doc.get("seo") or {}
    indexable = seo.get("indexable", True) is not False and "noindex" not in (seo.get("robots") or "").lower() and not doc.get("anteprima") and doc.get("indicizzabile", True) is not False
    return {"url": f"{base}/{path}/{doc['slug']}", "entity_type": entity_type, "entity_id": doc["id"], "slug": doc["slug"], "published": doc.get("stato") == "pubblicata", "indexable": indexable}


async def inspect(url: str, entity: Optional[dict] = None, refresh: bool = False) -> dict:
    """Cached URL Inspection. Returns {url, state, google{...}, cached, inspected_at} — state is derived ONLY from Google."""
    doc = await google_search_status_col.find_one({"url": url}, {"_id": 0}) or {}
    g = doc.get("google") or {}
    fresh = False
    if g.get("last_inspection_at") and not refresh:
        try:
            fresh = datetime.now(timezone.utc) - datetime.fromisoformat(g["last_inspection_at"]) < timedelta(hours=cfg.inspection_cache_hours)
        except Exception:
            fresh = False
    if fresh:
        return {"url": url, "state": g.get("state", "UNKNOWN"), "google": g, "cached": True, "source": "cache"}
    if not configured() or not cfg.inspection_enabled:
        return {"url": url, "state": "NOT_CONFIGURED", "google": g or None, "cached": bool(g), "source": "none",
                "detail": "URL Inspection non disponibile: Search Console non configurata (o inspection disattivata)"}
    if await _inspections_today() >= cfg.inspection_daily_budget:
        return {"url": url, "state": g.get("state", "UNKNOWN") if g else "UNKNOWN", "google": g or None, "cached": bool(g), "source": "budget_exhausted",
                "detail": f"Budget giornaliero di ispezioni esaurito ({cfg.inspection_daily_budget}); riprova domani o usa la cache"}
    try:
        raw = await _adapter().inspect_url(cfg.property_url, url)
        await _count_inspection()
        res = (raw.get("inspectionResult") or {}).get("indexStatusResult") or {}
        state = map_state(res)
        g_new = {"state": state, "verdict": res.get("verdict"), "coverage_state": res.get("coverageState"), "indexing_state": res.get("indexingState"),
                 "robots_txt_state": res.get("robotsTxtState"), "page_fetch_state": res.get("pageFetchState"), "google_canonical": res.get("googleCanonical"),
                 "user_canonical": res.get("userCanonical"), "last_crawl_time": res.get("lastCrawlTime"), "in_sitemaps": res.get("sitemap") or [],
                 "referring_urls": (res.get("referringUrls") or [])[:5], "crawled_as": res.get("crawledAs"), "inspection_link": (raw.get("inspectionResult") or {}).get("inspectionResultLink"),
                 "last_inspection_at": now_iso()}
        hist = ({"at": g["last_inspection_at"], "state": g.get("state"), "coverage_state": g.get("coverage_state")} if g.get("last_inspection_at") else None)
        upd = {"$set": {"url": url, "google": g_new, "updated_at": now_iso(), **({"entity_type": entity["entity_type"], "entity_id": entity["entity_id"], "slug": entity.get("slug")} if entity else {})},
               "$setOnInsert": {"created_at": now_iso()}}
        if hist:
            upd["$push"] = {"history": {"$each": [hist], "$slice": -30}}
        await google_search_status_col.update_one({"url": url}, upd, upsert=True)
        return {"url": url, "state": state, "google": g_new, "cached": False, "source": "google", "previous_state": g.get("state")}
    except Exception as e:
        err = _err(e)
        return {"url": url, "state": g.get("state", "UNKNOWN") if g else "UNKNOWN", "google": g or None, "cached": bool(g), "source": "error", "error": err,
                "detail": "Google non ha risposto: stato dalla cache se disponibile, altrimenti UNKNOWN"}


# ================================================================== SEARCH ANALYTICS (cached)
RANGES = {"7g": 7, "7d": 7, "28g": 28, "28d": 28, "3m": 90, "90g": 90, "90d": 90}


def _range(range_: Optional[str], start: Optional[str], end: Optional[str]) -> tuple:
    if start and end:
        return start, end
    days = RANGES.get((range_ or "28g").lower(), 28)
    end_d = datetime.now(timezone.utc).date() - timedelta(days=3)   # Search Console data has ~3 days delay
    start_d = end_d - timedelta(days=days - 1)
    return start_d.isoformat(), end_d.isoformat()


async def analytics(dimensions: List[str], range_: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None,
                    page: Optional[str] = None, page_contains: Optional[str] = None, limit: int = 25, compare: bool = False) -> dict:
    """Search Analytics with a 6h cache. `page` = exact URL filter, `page_contains` = path fragment filter."""
    if not configured() or not cfg.analytics_enabled:
        return {"available": False, "state": "NOT_CONFIGURED", "detail": "Search Analytics non disponibile: Search Console non configurata", "rows": []}
    s, e = _range(range_, start, end)
    body: Dict[str, Any] = {"startDate": s, "endDate": e, "dimensions": dimensions, "rowLimit": max(1, min(int(limit or 25), 250)), "dataState": "all"}
    if page or page_contains:
        body["dimensionFilterGroups"] = [{"filters": [{"dimension": "page", "operator": "equals" if page else "contains", "expression": page or page_contains}]}]
    key = hashlib.sha256(repr(sorted(body.items())).encode()).hexdigest()[:20]
    cached = await google_search_analytics_col.find_one({"key": key}, {"_id": 0})
    if cached and (datetime.now(timezone.utc) - cached["created_dt"].replace(tzinfo=timezone.utc)) < timedelta(hours=6):
        data = cached["data"]
        data["cached"] = True
    else:
        try:
            raw = await _adapter().search_analytics(cfg.property_url, body)
            rows = [{"keys": r.get("keys", []), "clicks": r.get("clicks", 0), "impressions": r.get("impressions", 0), "ctr": round((r.get("ctr") or 0) * 100, 2), "position": round(r.get("position") or 0, 1)} for r in raw.get("rows") or []]
            data = {"available": True, "start": s, "end": e, "dimensions": dimensions, "filter": page or page_contains, "rows": rows, "cached": False}
            await google_search_analytics_col.update_one({"key": key}, {"$set": {"key": key, "data": data, "created_dt": now_dt(), "created_at": now_iso()}}, upsert=True)
        except Exception as ex:
            return {"available": False, "state": "ERROR", "error": _err(ex), "start": s, "end": e, "rows": []}
    if compare and not dimensions:
        try:
            d0, d1 = datetime.fromisoformat(s), datetime.fromisoformat(e)
            span = (d1 - d0).days + 1
            ps, pe = (d0 - timedelta(days=span)).date().isoformat(), (d0 - timedelta(days=1)).date().isoformat()
            prev = await analytics([], None, ps, pe, page, page_contains, limit, False)
            data["previous"] = {"start": ps, "end": pe, "rows": prev.get("rows", [])}
        except Exception:
            pass
    return data


def summarize(rows: List[dict]) -> dict:
    clicks = sum(r["clicks"] for r in rows)
    imps = sum(r["impressions"] for r in rows)
    pos = round(sum(r["position"] * r["impressions"] for r in rows) / imps, 1) if imps else None
    return {"clicks": clicks, "impressions": imps, "ctr": round(clicks / imps * 100, 2) if imps else 0.0, "position": pos}


# ================================================================== TECHNICAL INDEXABILITY (our side, no Google quota)
async def indexability(entity: dict, fetch: bool = True) -> dict:
    """Technical checklist for one public URL: HTTP status, robots.txt, noindex, canonical, sitemap inclusion, title/meta/H1,
    structured data pertinence, internal links. Uses DB fields (the SPA renders them client-side) + one HTTP HEAD/GET."""
    from v1_seo import sitemap_entries
    url = entity["url"]
    checks: List[dict] = []

    def add(code, ok, detail, severity="HIGH"):
        checks.append({"code": code, "ok": bool(ok), "detail": detail, "severity": "INFO" if ok else severity})

    doc = None
    if entity["entity_type"] == "model":
        doc = await models_col.find_one({"id": entity["entity_id"]}, {"_id": 0})
    elif entity["entity_type"] == "landing":
        doc = await landings_col.find_one({"id": entity["entity_id"]}, {"_id": 0})
    elif entity["entity_type"] == "category":
        doc = await categories_col.find_one({"id": entity["entity_id"]}, {"_id": 0})
    seo = (doc or {}).get("seo") or {}
    add("PUBLISHED", entity.get("published"), "pagina pubblicata" if entity.get("published") else "non pubblicata: non raggiungibile pubblicamente (bozza/archiviata)")
    add("NOINDEX", entity.get("indexable"), "index,follow" if entity.get("indexable") else "noindex o anteprima: esclusa dall'indice per scelta")
    http_status, final_url, redirected = None, url, False
    if fetch and entity.get("published"):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True, headers={"User-Agent": "LatoSegreto-Indexability/1.0"}) as c:
                r = await c.get(url)
                http_status, final_url, redirected = r.status_code, str(r.url), len(r.history) > 0
                xr = r.headers.get("x-robots-tag", "")
                add("HTTP_200", r.status_code == 200, f"HTTP {r.status_code}" + (f" (redirect → {final_url})" if redirected else ""))
                add("X_ROBOTS_TAG", "noindex" not in xr.lower(), f"X-Robots-Tag: {xr or 'assente'}", "CRITICAL")
                add("HTML_SHELL", "<div id=\"root\"" in r.text and "<title" in r.text, "shell HTML SPA servita (meta dinamici applicati dal client: Google renderizza JS)", "MEDIUM")
        except Exception as e:
            add("HTTP_200", False, f"fetch fallito: {type(e).__name__}")
    # robots.txt (public)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as c:
            rb = await c.get(f"{public_base()}/robots.txt")
        path = url[len(public_base()):] or "/"
        disallowed = any(line.split(":", 1)[1].strip() and path.startswith(line.split(":", 1)[1].strip()) for line in rb.text.splitlines() if line.lower().startswith("disallow:"))
        add("ROBOTS_TXT", rb.status_code == 200 and not disallowed, "robots.txt consente la scansione" if not disallowed else "robots.txt blocca questo percorso", "CRITICAL")
        add("ROBOTS_SITEMAP", "sitemap:" in rb.text.lower() and "/api/sitemap.xml" in rb.text, "robots.txt dichiara la sitemap", "MEDIUM")
    except Exception as e:
        add("ROBOTS_TXT", False, f"robots.txt non leggibile: {type(e).__name__}", "MEDIUM")
    entries = await sitemap_entries(await refresh_public_base())
    in_sitemap = any(e["loc"] == url for e in entries)
    add("IN_SITEMAP", in_sitemap or not (entity.get("published") and entity.get("indexable")), "presente nella sitemap" if in_sitemap else ("assente dalla sitemap" if entity.get("published") and entity.get("indexable") else "non attesa in sitemap (non pubblica/noindex)"), "HIGH")
    # canonical
    canon = (seo.get("canonical") or "").strip() or url
    add("CANONICAL", canon.rstrip("/") == url.rstrip("/") or canon.startswith(public_base()), f"canonical: {canon}" + ("" if canon.rstrip("/") == url.rstrip("/") else " (diverso dall'URL: verifica che sia voluto)"), "MEDIUM")
    if doc is not None:
        title = seo.get("title") or ""
        desc = seo.get("meta_description") or ""
        h1 = (doc.get("nome_artistico") or doc.get("headline") or doc.get("titolo") or doc.get("nome") or "")
        add("TITLE", 10 <= len(title) <= 65, f"title {len(title)} caratteri" if title else "title SEO mancante (fallback: nome | LATO SEGRETO)", "MEDIUM")
        add("META_DESCRIPTION", 50 <= len(desc) <= 160, f"meta description {len(desc)} caratteri" if desc else "meta description mancante (fallback: bio)", "MEDIUM")
        add("H1", bool(h1), f"H1: {h1[:60]}" if h1 else "H1 mancante", "HIGH")
        if entity["entity_type"] == "model":
            add("STRUCTURED_DATA", bool(doc.get("nome_artistico") and (doc.get("bio") or desc)), "JSON-LD schema.org/Person con name/description/image (nessun rating/prezzo inventato)", "LOW")
            add("OG_IMAGE", bool(seo.get("og_image") or doc.get("foto_card")), "og:image presente" if (seo.get("og_image") or doc.get("foto_card")) else "og:image mancante (carica la foto card)", "LOW")
            cats = doc.get("categorie") or []
            related = await models_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}, "id": {"$ne": doc["id"]}, "categorie": {"$in": cats}}) if cats else 0
            linked_landings = await landings_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}, "model_slugs": doc.get("slug")})
            add("INTERNAL_LINKS", bool(cats) and (related > 0 or linked_landings > 0), f"categorie {len(cats)}, modelle correlate {related}, landing collegate {linked_landings}, link dalla Home (griglia + FilmStrip)", "MEDIUM")
        if entity["entity_type"] == "landing":
            add("STRUCTURED_DATA", True, f"JSON-LD {seo.get('structured_data_type') or 'WebPage'}", "LOW")
            add("INTERNAL_LINKS", bool(doc.get("model_slugs")), f"modelle collegate: {len(doc.get('model_slugs') or [])}", "MEDIUM")
    failing = [c for c in checks if not c["ok"]]
    blocking = [c for c in failing if c["severity"] in ("CRITICAL", "HIGH")]
    result = {"url": url, "entity_type": entity["entity_type"], "entity_id": entity["entity_id"], "slug": entity.get("slug"), "http_status": http_status, "redirected": redirected,
              "technically_indexable": entity.get("published") and entity.get("indexable") and not blocking, "checks": checks, "failing": [c["code"] for c in failing], "checked_at": now_iso()}
    try:
        await google_search_status_col.update_one({"url": url}, {"$set": {"url": url, "entity_type": entity["entity_type"], "entity_id": entity["entity_id"], "slug": entity.get("slug"),
                                                                            "indexability": {k: result[k] for k in ("http_status", "technically_indexable", "failing", "checked_at")}, "updated_at": now_iso()},
                                                                   "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
    except Exception:
        pass
    return result


async def public_entities() -> List[dict]:
    """All URLs that are (or should be) public + indexable, with their persisted Google state (for overviews)."""
    await refresh_public_base()
    out = []
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1, "seo": 1, "anteprima": 1, "nome_artistico": 1}):
        e = await resolve_entity_url("model", m["slug"])
        if e:
            e["label"] = m.get("nome_artistico")
            out.append(e)
    cfgd = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    if (cfgd.get("flags") or {}).get("public_landing_routes"):
        async for l in landings_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1, "seo": 1, "titolo": 1}):
            e = await resolve_entity_url("landing", l["slug"])
            if e:
                e["label"] = l.get("titolo")
                out.append(e)
    states = {d["url"]: (d.get("google") or {}) for d in await google_search_status_col.find({}, {"_id": 0, "url": 1, "google": 1}).to_list(2000)}
    for e in out:
        g = states.get(e["url"]) or {}
        e["google_state"] = g.get("state") or "NOT_INSPECTED"
        e["last_inspection_at"] = g.get("last_inspection_at")
        e["last_crawl_time"] = g.get("last_crawl_time")
    return out
