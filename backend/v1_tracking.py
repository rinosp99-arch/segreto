"""SUPER API v1 - TRACKING + ITALY ENGINE + CONVERSION ANALYTICS.

- Canonical event names (model_view, secret_side_open, ... ) coexist with legacy `tipo`
  so the existing dashboards keep working.
- Every event is enriched with device / source / geo (country/region/city) derived from
  request headers (CDN/proxy geo headers, Accept-Language fallback). No geoblocking.
- Filters everywhere: range, country, region, city, device, source, landing, model.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qs
from fastapi import APIRouter, Depends, Request, Query
from pydantic import BaseModel, ConfigDict

from database import events_col, models_col, now_iso, analytics_daily_col
from v1_security import require, rate_limit, DEFAULT_LIMIT_PUBLIC

tracking_router = APIRouter(prefix="/api/v1", tags=["Tracking & Analytics"])

# canonical <-> legacy mapping
CANONICAL_EVENTS = [
    "visit", "model_view", "secret_side_open", "secret_side_complete", "cta_view", "cta_click", "onlyfans_click",
    "instagram_click", "tiktok_click", "telegram_click", "video_play", "video_complete", "gallery_interaction",
    "timer_trigger", "landing_view", "scroll_depth", "article_view", "pellicola_impression", "pellicola_click",
    "experiment_exposure", "message_open", "home_surprise_click", "secret_return",
]
LEGACY_TO_CANONICAL = {
    "page_view": "model_view", "secret_activate": "secret_side_open", "secret_time": "secret_side_complete",
    "of_click": "onlyfans_click", "cta_click": "cta_click", "landing": "landing_view", "interazione": "gallery_interaction",
    "message_shown": "timer_trigger", "message_open": "message_open", "pellicola_video_view": "video_play",
    "pellicola_impression": "pellicola_impression", "pellicola_click_profilo": "pellicola_click", "article_view": "article_view",
    "teaser_finale_click": "cta_click", "home_surprise_click": "home_surprise_click", "home_surprise_profile_open": "model_view",
    "secret_return": "secret_return",
}
CANONICAL_TO_LEGACY = {
    "model_view": "page_view", "secret_side_open": "secret_activate", "secret_side_complete": "secret_time", "onlyfans_click": "of_click",
    "cta_click": "cta_click", "landing_view": "landing", "gallery_interaction": "interazione", "timer_trigger": "message_shown",
    "video_play": "pellicola_video_view", "pellicola_impression": "pellicola_impression", "pellicola_click": "pellicola_click_profilo",
    "article_view": "article_view", "message_open": "message_open",
}
IT_REGIONS = {"lombardia", "lazio", "campania", "sicilia", "veneto", "emilia-romagna", "piemonte", "puglia", "toscana", "calabria", "sardegna", "liguria", "marche", "abruzzo", "friuli-venezia giulia", "trentino-alto adige", "umbria", "basilicata", "molise", "valle d'aosta"}


# ---------------- enrichment ----------------
def _device(ua: str) -> str:
    u = (ua or "").lower()
    if "ipad" in u or "tablet" in u or ("android" in u and "mobile" not in u):
        return "tablet"
    if "mobi" in u or "iphone" in u or "android" in u:
        return "mobile"
    if "bot" in u or "crawl" in u or "spider" in u:
        return "bot"
    return "desktop"


def _os(ua: str) -> str:
    u = (ua or "").lower()
    for k, v in (("iphone", "ios"), ("ipad", "ios"), ("android", "android"), ("windows", "windows"), ("mac os", "macos"), ("linux", "linux")):
        if k in u:
            return v
    return "other"


def _browser(ua: str) -> str:
    u = (ua or "").lower()
    if "edg/" in u:
        return "edge"
    if "chrome" in u and "safari" in u:
        return "chrome"
    if "safari" in u and "chrome" not in u:
        return "safari"
    if "firefox" in u:
        return "firefox"
    return "other"


def _source(referrer: str, fonte: Optional[str], page_url: str) -> str:
    if fonte:
        return str(fonte).lower()
    q = parse_qs(urlparse(page_url or "").query)
    if q.get("utm_source"):
        return q["utm_source"][0].lower()
    if q.get("fonte"):
        return q["fonte"][0].lower()
    host = (urlparse(referrer or "").hostname or "").lower()
    if not host:
        return "direct"
    for k in ("instagram", "tiktok", "t.me", "telegram", "google", "bing", "twitter", "x.com", "facebook", "reddit", "onlyfans", "youtube", "duckduckgo"):
        if k in host:
            return {"t.me": "telegram", "x.com": "twitter"}.get(k, k)
    return "referral"


def _geo(request: Request) -> Dict[str, Any]:
    h = request.headers
    country = (h.get("cf-ipcountry") or h.get("x-country-code") or h.get("x-vercel-ip-country") or h.get("cloudfront-viewer-country") or h.get("x-geo-country") or h.get("x-appengine-country") or "").upper()
    region = h.get("cf-region") or h.get("x-vercel-ip-country-region") or h.get("x-geo-region") or h.get("x-appengine-region") or ""
    city = h.get("cf-ipcity") or h.get("x-vercel-ip-city") or h.get("x-geo-city") or h.get("x-appengine-city") or ""
    source = "header" if country and country not in ("XX", "T1") else ""
    if not source:
        country = ""
        al = (h.get("accept-language") or "").lower()
        if al.startswith("it") or ",it" in al or "it-it" in al:
            country, source = "IT", "language"
    return {"country": country or "UNKNOWN", "region": region or "", "city": city or "", "source": source or "none", "is_italy": country == "IT"}


def enrich_event(doc: dict, request: Request) -> dict:
    ua = request.headers.get("user-agent", "")
    page_url = (doc.get("meta") or {}).get("url") or request.headers.get("referer") or ""
    ref = doc.get("referrer") or (doc.get("meta") or {}).get("referrer") or ""
    parsed = urlparse(page_url) if page_url else None
    doc["device"] = _device(ua)
    doc["os"] = _os(ua)
    doc["browser"] = _browser(ua)
    doc["source"] = _source(ref, doc.get("fonte"), page_url)
    doc["geo"] = _geo(request)
    doc["country"] = doc["geo"]["country"]
    doc["path"] = doc.get("path") or (parsed.path if parsed else ((doc.get("meta") or {}).get("path") or ""))
    doc["landing"] = (doc.get("meta") or {}).get("landing") or doc.get("landing") or ""
    q = parse_qs(parsed.query) if parsed else {}
    utm = {k[4:]: v[0] for k, v in q.items() if k.startswith("utm_")}
    if utm:
        doc["utm"] = utm
        doc.setdefault("campagna", utm.get("campaign"))
    if doc.get("tipo") and not doc.get("event"):
        doc["event"] = LEGACY_TO_CANONICAL.get(doc["tipo"], doc["tipo"])
    if doc.get("event") and not doc.get("tipo"):
        doc["tipo"] = CANONICAL_TO_LEGACY.get(doc["event"], doc["event"])
    if doc.get("event") == "model_view" and not doc.get("model_id") and not doc.get("model_slug"):
        doc["event"] = "visit"
    return doc


# ---------------- public v1 track ----------------
class TrackV1(BaseModel):
    model_config = ConfigDict(extra='allow')
    event: str
    model_id: Optional[str] = None
    model_slug: Optional[str] = None
    page_id: Optional[str] = None
    landing_id: Optional[str] = None
    session_id: str = ""
    source: Optional[str] = None
    campaign: Optional[str] = None
    cta_source: Optional[str] = None
    value: Optional[float] = None
    experiment_id: Optional[str] = None
    variant_id: Optional[str] = None
    meta: Dict[str, Any] = {}


@tracking_router.post("/track")
async def track_v1(ev: TrackV1, request: Request):
    ip = request.client.host if request.client else "anon"
    rate_limit(f"pub:{ip}", DEFAULT_LIMIT_PUBLIC)
    if ev.event not in CANONICAL_EVENTS and ev.event not in LEGACY_TO_CANONICAL:
        return {"ok": False, "error": "evento non riconosciuto", "allowed": CANONICAL_EVENTS}
    doc = ev.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["timestamp"] = now_iso()
    if doc.get("campaign"):
        doc["campagna"] = doc["campaign"]
    if doc.get("source"):
        doc["fonte"] = doc["source"]
    if doc.get("value") is not None:
        doc["valore"] = doc["value"]
    if doc["event"] in LEGACY_TO_CANONICAL:
        doc["tipo"] = doc["event"]
        doc["event"] = LEGACY_TO_CANONICAL[doc["event"]]
    if not doc.get("model_id") and doc.get("model_slug"):
        m = await models_col.find_one({"slug": doc["model_slug"]}, {"_id": 0, "id": 1})
        if m:
            doc["model_id"] = m["id"]
    enrich_event(doc, request)
    await events_col.insert_one(doc)
    return {"ok": True}


# ---------------- analytics helpers ----------------
def cutoff(range_key: str) -> Optional[str]:
    now = datetime.now(timezone.utc)
    if range_key in ("oggi", "today"):
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    m = re.match(r"^(\d+)(g|d)$", range_key or "")
    if m:
        return (now - timedelta(days=int(m.group(1)))).isoformat()
    if range_key in ("ieri", "yesterday"):
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return None


def build_match(range: str = "30g", country: Optional[str] = None, region: Optional[str] = None, city: Optional[str] = None,
                device: Optional[str] = None, source: Optional[str] = None, model_id: Optional[str] = None, landing: Optional[str] = None,
                campaign: Optional[str] = None) -> dict:
    match: Dict[str, Any] = {}
    cut = cutoff(range)
    if cut:
        match["timestamp"] = {"$gte": cut}
    if range in ("ieri", "yesterday"):
        match["timestamp"]["$lt"] = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if country:
        match["geo.country"] = country.upper() if country.upper() != "OTHER" else {"$nin": ["IT", "UNKNOWN"]}
    if region:
        match["geo.region"] = {"$regex": re.escape(region), "$options": "i"}
    if city:
        match["geo.city"] = {"$regex": re.escape(city), "$options": "i"}
    if device:
        match["device"] = device
    if source:
        match["source"] = source
    if model_id:
        match["model_id"] = model_id
    if landing:
        match["$or"] = [{"landing": landing}, {"landing_id": landing}, {"path": landing}]
    if campaign:
        match["campagna"] = campaign
    return match


async def counts_by(match: dict, field: str = "event") -> Dict[str, int]:
    out: Dict[str, int] = {}
    async for r in events_col.aggregate([{"$match": match}, {"$group": {"_id": f"${field}", "n": {"$sum": 1}}}]):
        out[r["_id"] or "unknown"] = r["n"]
    return out


async def sessions_count(match: dict, event: Optional[str] = None) -> int:
    m = dict(match)
    if event:
        m["$or"] = [{"event": event}, {"tipo": CANONICAL_TO_LEGACY.get(event, event)}]
    r = await events_col.aggregate([{"$match": m}, {"$group": {"_id": "$session_id"}}, {"$count": "n"}]).to_list(1)
    return r[0]["n"] if r else 0


def _ev_match(match: dict, event: str) -> dict:
    legacy = CANONICAL_TO_LEGACY.get(event, event)
    return {**match, "$or": [{"event": event}, {"tipo": legacy}]}


async def funnel_for(match: dict) -> dict:
    visits = await sessions_count(match)
    model_views = await events_col.count_documents(_ev_match(match, "model_view"))
    secret = await events_col.count_documents(_ev_match(match, "secret_side_open"))
    cta_view = await events_col.count_documents(_ev_match(match, "cta_view"))
    of = await events_col.count_documents(_ev_match(match, "onlyfans_click"))
    steps = [
        {"step": "VISIT", "label": "Visite (sessioni)", "value": visits},
        {"step": "MODEL_VIEW", "label": "Profili visti", "value": model_views},
        {"step": "SECRET_SIDE_OPEN", "label": "Lato Segreto aperto", "value": secret},
        {"step": "CTA_VIEW", "label": "CTA vista", "value": cta_view},
        {"step": "ONLYFANS_CLICK", "label": "Click OnlyFans", "value": of},
    ]
    top = steps[0]["value"] or 1
    for i, s in enumerate(steps):
        s["percent_of_top"] = round(s["value"] / top * 100, 1)
        prev = steps[i - 1]["value"] if i else s["value"]
        s["step_conversion"] = round(s["value"] / prev * 100, 1) if prev else 0.0
    return {"steps": steps, "conversion_rate": round(of / model_views * 100, 2) if model_views else 0.0,
            "activation_rate": round(secret / model_views * 100, 1) if model_views else 0.0}


async def model_kpis(model_id: str, match: dict) -> dict:
    m = {**match, "model_id": model_id}
    views = await events_col.count_documents(_ev_match(m, "model_view"))
    secret = await events_col.count_documents(_ev_match(m, "secret_side_open"))
    cta = await events_col.count_documents(_ev_match(m, "cta_click"))
    of = await events_col.count_documents(_ev_match(m, "onlyfans_click"))
    it_views = await events_col.count_documents({**_ev_match(m, "model_view"), "geo.country": "IT"})
    it_of = await events_col.count_documents({**_ev_match(m, "onlyfans_click"), "geo.country": "IT"})
    src = await counts_by(_ev_match(m, "model_view"), "source")
    return {"visits": views, "secret_opens": secret, "cta_clicks": cta, "onlyfans_clicks": of,
            "activation_rate": round(secret / views * 100, 1) if views else 0.0,
            "ctr": round(cta / views * 100, 1) if views else 0.0,
            "conversion_rate": round(of / views * 100, 2) if views else 0.0,
            "italian_visits": it_views, "italian_share": round(it_views / views * 100, 1) if views else 0.0,
            "italian_onlyfans_clicks": it_of, "traffic_sources": src}


# ---------------- ANALYTICS ROUTES ----------------
FilterDeps = dict(range="30g", country=None, region=None, city=None, device=None, source=None, model_id=None, landing=None, campaign=None)


def filters(range: str = "30g", country: Optional[str] = None, region: Optional[str] = None, city: Optional[str] = None,
            device: Optional[str] = None, source: Optional[str] = None, model_id: Optional[str] = None, landing: Optional[str] = None,
            campaign: Optional[str] = None) -> dict:
    return build_match(range, country, region, city, device, source, model_id, landing, campaign)


@tracking_router.get("/analytics/overview")
async def overview(match: dict = Depends(filters), principal=Depends(require("analytics:read"))):
    f = await funnel_for(match)
    it = await funnel_for({**match, "geo.country": "IT"})
    total_events = await events_col.count_documents(match)
    devices = await counts_by(_ev_match(match, "model_view"), "device")
    sources = await counts_by(_ev_match(match, "model_view"), "source")
    countries = await counts_by(_ev_match(match, "model_view"), "geo.country")
    return {"filters": match, "funnel": f, "italy": {"funnel": it, "share_of_model_views": round((it["steps"][1]["value"] / (f["steps"][1]["value"] or 1)) * 100, 1)},
            "events_total": total_events, "devices": devices, "sources": sources, "countries": countries}


@tracking_router.get("/analytics/funnel")
async def funnel(match: dict = Depends(filters), principal=Depends(require("analytics:read"))):
    return {"filters": match, **(await funnel_for(match))}


@tracking_router.get("/analytics/models")
async def models_leaderboard(match: dict = Depends(filters), sort: str = "conversion_rate", limit: int = 50, principal=Depends(require("analytics:read"))):
    rows = []
    async for m in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1, "nome_artistico": 1, "foto_card": 1, "stato": 1}):
        k = await model_kpis(m["id"], match)
        rows.append({**m, **k})
    key = sort if sort in ("conversion_rate", "visits", "onlyfans_clicks", "activation_rate", "ctr", "italian_visits") else "conversion_rate"
    rows.sort(key=lambda r: (r[key], r["visits"]), reverse=True)
    best = next((r for r in rows if r["onlyfans_clicks"] > 0), None)
    return {"filters": match, "items": rows[:limit], "best_converting": best, "note": "conversion_rate = click OnlyFans / profili visti"}


@tracking_router.get("/analytics/models/{model_id}")
async def model_dashboard(model_id: str, match: dict = Depends(filters), principal=Depends(require("analytics:read"))):
    from v1_models import resolve_model
    doc = await resolve_model(model_id, include_deleted=True)
    k = await model_kpis(doc["id"], match)
    f = await funnel_for({**match, "model_id": doc["id"]})
    cta_sources = await counts_by({**match, "model_id": doc["id"], "$or": [{"event": "onlyfans_click"}, {"tipo": "of_click"}]}, "cta_source")
    regions = await counts_by({**_ev_match({**match, "model_id": doc["id"]}, "model_view"), "geo.country": "IT"}, "geo.region")
    return {"model": {"id": doc["id"], "slug": doc["slug"], "nome": doc.get("nome_artistico")}, "kpis": k, "funnel": f, "cta_sources": cta_sources, "italian_regions": regions}


@tracking_router.get("/analytics/breakdown")
async def breakdown(dimension: str = Query("country", description="country|region|city|device|source|landing|model|browser|os|campaign"),
                    event: str = "model_view", match: dict = Depends(filters), limit: int = 30, principal=Depends(require("analytics:read"))):
    field = {"country": "geo.country", "region": "geo.region", "city": "geo.city", "device": "device", "source": "source", "landing": "landing",
             "model": "model_id", "browser": "browser", "os": "os", "campaign": "campagna", "path": "path"}.get(dimension)
    if not field:
        return {"error": "dimensione non valida"}
    m = _ev_match(match, event)
    rows = []
    async for r in events_col.aggregate([{"$match": m}, {"$group": {"_id": f"${field}", "n": {"$sum": 1}, "sessions": {"$addToSet": "$session_id"}}}, {"$project": {"n": 1, "sessions": {"$size": "$sessions"}}}, {"$sort": {"n": -1}}, {"$limit": limit}]):
        rows.append({"key": r["_id"] or "unknown", "events": r["n"], "sessions": r["sessions"]})
    if dimension == "model":
        names = {m2["id"]: m2.get("nome_artistico") for m2 in await models_col.find({}, {"_id": 0, "id": 1, "nome_artistico": 1}).to_list(2000)}
        for r in rows:
            r["label"] = names.get(r["key"], r["key"])
    return {"dimension": dimension, "event": event, "items": rows}


@tracking_router.get("/analytics/italy")
async def italy(match: dict = Depends(filters), principal=Depends(require("analytics:read"))):
    """ITALY ENGINE summary: Italian vs other traffic, regions, cities, devices, top models (no geoblocking)."""
    all_views = await events_col.count_documents(_ev_match(match, "model_view"))
    it_match = {**match, "geo.country": "IT"}
    it_views = await events_col.count_documents(_ev_match(it_match, "model_view"))
    unknown = await events_col.count_documents({**_ev_match(match, "model_view"), "geo.country": "UNKNOWN"})
    regions = await counts_by(_ev_match(it_match, "model_view"), "geo.region")
    cities = await counts_by(_ev_match(it_match, "model_view"), "geo.city")
    devices = await counts_by(_ev_match(it_match, "model_view"), "device")
    sources = await counts_by(_ev_match(it_match, "model_view"), "source")
    geo_sources = await counts_by(_ev_match(match, "model_view"), "geo.source")
    f = await funnel_for(it_match)
    top = []
    async for r in events_col.aggregate([{"$match": _ev_match(it_match, "onlyfans_click")}, {"$group": {"_id": "$model_id", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 10}]):
        m = await models_col.find_one({"id": r["_id"]}, {"_id": 0, "slug": 1, "nome_artistico": 1})
        if m:
            top.append({**m, "italian_onlyfans_clicks": r["n"]})
    return {"filters": match, "model_views_total": all_views, "model_views_italy": it_views, "italian_share": round(it_views / all_views * 100, 1) if all_views else 0.0,
            "unknown_geo": unknown, "geo_detection_sources": geo_sources, "regions": regions, "cities": cities, "devices": devices, "sources": sources,
            "funnel_italy": f, "top_models_italy": top,
            "note": "Geo da header CDN/proxy quando presenti; fallback Accept-Language=it (geo.source='language'). Nessun geoblocking."}


@tracking_router.get("/analytics/timeseries")
async def timeseries(match: dict = Depends(filters), principal=Depends(require("analytics:read"))):
    series: Dict[str, Dict[str, Any]] = {}
    async for r in events_col.aggregate([{"$match": match}, {"$group": {"_id": {"g": {"$substr": ["$timestamp", 0, 10]}, "e": {"$ifNull": ["$event", "$tipo"]}, "it": {"$eq": ["$geo.country", "IT"]}}, "n": {"$sum": 1}}}]):
        g = r["_id"]["g"]
        s = series.setdefault(g, {"giorno": g, "model_view": 0, "secret_side_open": 0, "onlyfans_click": 0, "cta_click": 0, "model_view_it": 0, "onlyfans_click_it": 0})
        e = LEGACY_TO_CANONICAL.get(r["_id"]["e"], r["_id"]["e"])
        if e in s:
            s[e] += r["n"]
        if r["_id"]["it"] and f"{e}_it" in s:
            s[f"{e}_it"] += r["n"]
    return {"items": sorted(series.values(), key=lambda x: x["giorno"])}


@tracking_router.get("/analytics/events")
async def events_catalog(principal=Depends(require("analytics:read"))):
    return {"canonical_events": CANONICAL_EVENTS, "legacy_mapping": LEGACY_TO_CANONICAL, "recorded_fields": ["model_id", "page_id", "landing", "source", "campagna/utm", "device", "os", "browser", "geo.country", "geo.region", "geo.city", "timestamp", "session_id"]}


@tracking_router.get("/analytics/onlyfans")
async def onlyfans_funnel(match: dict = Depends(filters), principal=Depends(require("analytics:read"))):
    """OnlyFans conversion engine: clicks by model, by source, by campaign/UTM, link health."""
    by_model = []
    async for r in events_col.aggregate([{"$match": _ev_match(match, "onlyfans_click")}, {"$group": {"_id": "$model_id", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]):
        m = await models_col.find_one({"id": r["_id"]}, {"_id": 0, "slug": 1, "nome_artistico": 1, "onlyfans_url": 1})
        by_model.append({"model_id": r["_id"], "slug": (m or {}).get("slug"), "nome": (m or {}).get("nome_artistico"), "clicks": r["n"], "onlyfans_url": (m or {}).get("onlyfans_url")})
    by_source = await counts_by(_ev_match(match, "onlyfans_click"), "source")
    by_campaign = await counts_by(_ev_match(match, "onlyfans_click"), "campagna")
    by_cta = await counts_by(_ev_match(match, "onlyfans_click"), "cta_source")
    from v1_models import OF_RX
    broken = []
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "onlyfans_url": 1}):
        if not m.get("onlyfans_url") or not OF_RX.match(m["onlyfans_url"].strip()):
            broken.append(m)
    return {"filters": match, "by_model": by_model, "by_source": by_source, "by_campaign": by_campaign, "by_cta_placement": by_cta, "broken_links": broken}


# ---------------- daily aggregation (used by analytics_sync job) ----------------
async def aggregate_day(day: str):
    start, end = f"{day}T00:00:00", f"{day}T23:59:59.999999"
    pipeline = [{"$match": {"timestamp": {"$gte": start, "$lte": end}}},
                {"$group": {"_id": {"model_id": "$model_id", "country": {"$ifNull": ["$geo.country", "UNKNOWN"]}, "e": {"$ifNull": ["$event", "$tipo"]}}, "n": {"$sum": 1}}}]
    rows: Dict[tuple, Dict[str, int]] = {}
    async for r in events_col.aggregate(pipeline):
        k = (r["_id"].get("model_id") or "-", r["_id"]["country"])
        e = LEGACY_TO_CANONICAL.get(r["_id"]["e"], r["_id"]["e"])
        rows.setdefault(k, {})[e] = rows.get(k, {}).get(e, 0) + r["n"]
    for (mid, country), ev in rows.items():
        await analytics_daily_col.update_one({"giorno": day, "model_id": mid, "country": country}, {"$set": {"events": ev, "updated_at": now_iso()}}, upsert=True)
    return len(rows)
