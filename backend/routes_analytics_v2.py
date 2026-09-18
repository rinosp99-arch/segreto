"""ADMIN ANALYTICS v2 — backend aggregations for the control-center dashboard.

Reads the existing `analytics_events` collection (legacy `tipo` names, canonical `event`, enrichment fields) WITHOUT renaming,
migrating or deleting anything: old, new and unknown events are all tolerated. All heavy lifting happens in MongoDB
($match on indexed timestamp/tipo/model_slug, $group, $facet, $dateTrunc); the browser only receives compact aggregates.
Metrics that cannot be derived from the data actually tracked are NOT invented: see `NOT_AVAILABLE` (returned by /summary)."""
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from auth import get_current_admin
from database import events_col, models_col

analytics_v2_router = APIRouter(prefix="/api/admin/analytics/v2", tags=["Admin analytics v2"])

# ---------------------------------------------------------------------------------------------------------------------
# Event vocabulary (legacy `tipo` values actually emitted by the site). Unknown values are still counted in /events.
# ---------------------------------------------------------------------------------------------------------------------
EV = {
    "profile_view": ["page_view"],
    "secret_activate": ["secret_activate"],
    "secret_return": ["secret_return"],
    "secret_time": ["secret_time"],
    "cta_view": ["cta_view"],
    "cta_click": ["cta_click"],
    "of_click": ["of_click"],
    "of_global_home": ["of_global_marquee_home_click"],
    "of_global_profile": ["of_global_marquee_profile_click"],
    "swipe_out": ["profile_swipe_next", "profile_swipe_previous"],
    "swipe_in": ["profile_swipe_public", "profile_swipe_secret"],
    "surprise_click": ["home_surprise_click"],
    "surprise_open": ["home_surprise_profile_open"],
    "filmstrip_impression": ["pellicola_impression"],
    "filmstrip_video": ["pellicola_video_view"],
    "filmstrip_click": ["pellicola_click_profilo"],
    "home_toggle": ["home_toggle_secret_on", "home_toggle_secret_off", "home_mobile_toggle_secret", "home_mobile_toggle_public"],
    "home_toggle_on": ["home_toggle_secret_on", "home_mobile_toggle_secret"],
    "landing": ["landing"],
    "message_shown": ["message_shown"],
    "message_open": ["message_open"],
    "teaser_click": ["teaser_finale_click"],
    "article_view": ["article_view"],
    "visit_legacy": ["visit"],
}
SOCIAL_PREFIX = "social_click_"
SECRET_ONLY = {"secret_activate", "secret_time", "secret_return", "cta_view", "cta_click", "message_shown", "message_open", "teaser_finale_click", "profile_swipe_secret"}
PUBLIC_ONLY = {"profile_swipe_public"}

NOT_AVAILABLE = [
    {"metrica": "Visite Home / page view della Home", "evento": "home_view (session_id, path)", "dove": "frontend/src/pages/Home.js (mount)"},
    {"metrica": "Card modella cliccate dalla griglia Home / aperture profilo via card", "evento": "home_card_click {model_slug}", "dove": "frontend/src/components/ModelCard.js"},
    {"metrica": "Categorie / filtri / ricerca usati", "evento": "home_filter {categoria} · home_search {q}", "dove": "frontend/src/pages/Home.js"},
    {"metrica": "Tempo medio sul sito / per profilo", "evento": "heartbeat o page_leave {valore secondi}", "dove": "frontend/src/App.js · ModelProfile.js (cleanup)"},
    {"metrica": "Referrer/URL esterno completo (solo dominio derivato in `source`)", "evento": "già presente: source (enrichment) — referrer completo non salvato", "dove": "backend/v1_tracking.enrich_event"},
    {"metrica": "Media: video visti / slot con più interazioni / completamenti", "evento": "media_view {slot, tipo} · media_complete", "dove": "frontend/src/components/MediaMorph.js"},
    {"metrica": "Ritorno Secret → Public per modella (evento presente solo dal 09/2026)", "evento": "secret_return (già emesso)", "dove": "—"},
    {"metrica": "Click OF dopo swipe / FilmStrip / Sorprendimi", "evento": "of_click.meta.swipes / cta_source: presenti solo per eventi recenti; via FilmStrip/Sorprendimi non attribuiti", "dove": "frontend/src/pages/ModelProfile.js openOnlyFans (aggiungere meta.via)"},
    {"metrica": "Nuove visite vs ritorni", "evento": "first_seen per session/visitor (localStorage id) — non tracciato", "dove": "frontend/src/lib/session.js"},
]

# ---------------------------------------------------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------------------------------------------------
PRESETS = {"oggi", "ieri", "7g", "30g", "mese", "mese_scorso", "custom"}


def period_bounds(range_key: str, date_from: Optional[str], date_to: Optional[str]):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "oggi":
        return today, now
    if range_key == "ieri":
        return today - timedelta(days=1), today
    if range_key in ("7g", "7d"):
        return today - timedelta(days=6), now
    if range_key in ("30g", "30d"):
        return today - timedelta(days=29), now
    if range_key == "mese":
        return today.replace(day=1), now
    if range_key == "mese_scorso":
        first = today.replace(day=1)
        prev_last = first - timedelta(days=1)
        return prev_last.replace(day=1), first
    if range_key == "custom" and date_from:
        try:
            a = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            if a.tzinfo is None:
                a = a.replace(tzinfo=timezone.utc)
            b = datetime.fromisoformat(date_to.replace("Z", "+00:00")) if date_to else now
            if b.tzinfo is None:
                b = b.replace(tzinfo=timezone.utc)
            if b <= a:
                b = a + timedelta(days=1)
            return a, b
        except Exception:
            pass
    return today - timedelta(days=29), now


def build_match(range_key: str, date_from: Optional[str], date_to: Optional[str], model: Optional[str], mode: Optional[str],
                source: Optional[str], fonte: Optional[str], campagna: Optional[str], ref: Optional[str], device: Optional[str]) -> Dict[str, Any]:
    a, b = period_bounds(range_key, date_from, date_to)
    m: Dict[str, Any] = {"timestamp": {"$gte": a.isoformat(), "$lt": b.isoformat()}}
    if model and model != "all":
        m["model_slug"] = model
    if source and source != "all":
        m["source"] = source
    if fonte and fonte != "all":
        m["fonte"] = fonte
    if campagna and campagna != "all":
        m["campagna"] = campagna
    if ref and ref != "all":
        m["ref"] = ref
    if device and device != "all":
        m["device"] = device
    if mode in ("public", "secret"):
        # explicit meta.mode wins; otherwise the event family decides; neutral events (page_view etc.) pass in both modes
        other = "secret" if mode == "public" else "public"
        excluded = SECRET_ONLY if mode == "public" else PUBLIC_ONLY
        m["$and"] = [
            {"$or": [{"meta.mode": {"$exists": False}}, {"meta.mode": None}, {"meta.mode": {"$in": [mode, mode.upper()]}}]},
            {"meta.mode": {"$nin": [other, other.upper()]}},
            {"tipo": {"$nin": list(excluded)}},
        ]
    return m


def _f(range_key: str = Query("30g"), date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
       model: Optional[str] = None, mode: Optional[str] = "all", source: Optional[str] = None, fonte: Optional[str] = None,
       campagna: Optional[str] = None, ref: Optional[str] = None, device: Optional[str] = None):
    return {"range": range_key, "from": date_from, "to": date_to, "model": model, "mode": mode, "source": source, "fonte": fonte, "campagna": campagna, "ref": ref, "device": device}


def match_of(f: dict) -> dict:
    return build_match(f["range"], f["from"], f["to"], f["model"], f["mode"], f["source"], f["fonte"], f["campagna"], f["ref"], f["device"])


def pct(a: float, b: float) -> Optional[float]:
    return round(100.0 * a / b, 1) if b else None


def _n(x) -> int:
    try:
        return int(x or 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------------------------------------------------
# Core aggregations
# ---------------------------------------------------------------------------------------------------------------------
async def counts_by_tipo(match: dict) -> Dict[str, int]:
    out: Dict[str, int] = {}
    async for r in events_col.aggregate([{"$match": match}, {"$group": {"_id": "$tipo", "n": {"$sum": 1}}}]):
        out[str(r["_id"])] = r["n"]
    return out


def sum_ev(counts: Dict[str, int], key: str) -> int:
    return sum(counts.get(t, 0) for t in EV[key])


async def distinct_sessions(match: dict, tipi: Optional[List[str]] = None) -> int:
    m = dict(match)
    if tipi:
        m["tipo"] = {"$in": tipi}
    m["session_id"] = {"$nin": ["", None]}
    r = await events_col.aggregate([{"$match": m}, {"$group": {"_id": "$session_id"}}, {"$count": "n"}]).to_list(1)
    return r[0]["n"] if r else 0


async def avg_valore(match: dict, tipo: str) -> Optional[float]:
    m = dict(match, tipo=tipo, valore={"$type": "number"})
    r = await events_col.aggregate([{"$match": m}, {"$group": {"_id": None, "avg": {"$avg": "$valore"}, "n": {"$sum": 1}}}]).to_list(1)
    return round(r[0]["avg"], 1) if r and r[0].get("avg") is not None else None


async def group_count(match: dict, field: str, tipi: Optional[List[str]] = None, limit: int = 50) -> List[dict]:
    m = dict(match)
    if tipi:
        m["tipo"] = {"$in": tipi}
    rows = []
    async for r in events_col.aggregate([{"$match": m}, {"$group": {"_id": f"${field}", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": limit}]):
        rows.append({"key": r["_id"] if r["_id"] not in (None, "") else "—", "n": r["n"]})
    return rows


async def published_models() -> List[dict]:
    return await models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1, "nome_artistico": 1, "nome": 1, "foto_card": 1}).sort("ordine", 1).to_list(500)


# ---------------------------------------------------------------------------------------------------------------------
# /summary — scorecards, funnel, onlyfans, swipe, secret, home, sources, top events (one call)
# ---------------------------------------------------------------------------------------------------------------------
@analytics_v2_router.get("/summary")
async def summary(f: dict = Depends(_f), admin=Depends(get_current_admin)):
    match = match_of(f)
    counts = await counts_by_tipo(match)
    total_events = sum(counts.values())
    sessions = await distinct_sessions(match)
    sess_profile = await distinct_sessions(match, EV["profile_view"])
    sess_secret = await distinct_sessions(match, EV["secret_activate"])
    sess_of = await distinct_sessions(match, EV["of_click"])
    sess_cta = await distinct_sessions(match, EV["cta_click"])

    profile_views = sum_ev(counts, "profile_view")
    secret = sum_ev(counts, "secret_activate")
    cta_click = sum_ev(counts, "cta_click")
    of_click = sum_ev(counts, "of_click")
    of_global = sum_ev(counts, "of_global_home") + sum_ev(counts, "of_global_profile")
    social = sum(v for k, v in counts.items() if k.startswith(SOCIAL_PREFIX))
    swipes = sum_ev(counts, "swipe_out")
    surprise = sum_ev(counts, "surprise_click")
    filmstrip = sum_ev(counts, "filmstrip_impression") + sum_ev(counts, "filmstrip_video") + sum_ev(counts, "filmstrip_click")
    secret_time_avg = await avg_valore(match, "secret_time")

    scorecard = {
        "sessioni": sessions,                      # distinct session_id with >= 1 event (no dedicated site-visit event exists)
        "visitatori": sessions,                    # same identity: one anonymous session id per visitor (no cross-session visitor id tracked)
        "eventi": total_events,
        "profili_aperti": profile_views,
        "sessioni_con_profilo": sess_profile,
        "secret_attivazioni": secret,
        "secret_rate": pct(sess_secret, sess_profile),
        "cta_click": cta_click,
        "of_click_personali": of_click,
        "of_click_globale": of_global,
        "social_click": social,
        "swipe": swipes,
        "sorprendimi": surprise,
        "filmstrip_interazioni": filmstrip,
        "marquee_click": of_global,
        "ctr_of": pct(of_click, profile_views),
        "ctr_cta": pct(cta_click, secret),
        "profili_per_sessione": round(profile_views / sess_profile, 2) if sess_profile else None,
        "tempo_medio_secret_s": secret_time_avg,
        "tempo_medio_sito_s": None,
        "tempo_medio_profilo_s": None,
    }
    funnel = [
        {"step": "Visita (sessioni)", "n": sessions, "conv_prev": None, "conv_first": 100.0 if sessions else None},
        {"step": "Profilo aperto (sessioni)", "n": sess_profile, "conv_prev": pct(sess_profile, sessions), "conv_first": pct(sess_profile, sessions)},
        {"step": "Lato Segreto attivato (sessioni)", "n": sess_secret, "conv_prev": pct(sess_secret, sess_profile), "conv_first": pct(sess_secret, sessions)},
        {"step": "Click CTA (sessioni)", "n": sess_cta, "conv_prev": pct(sess_cta, sess_secret), "conv_first": pct(sess_cta, sessions)},
        {"step": "Click OnlyFans (sessioni)", "n": sess_of, "conv_prev": pct(sess_of, sess_cta) if sess_cta else pct(sess_of, sess_secret), "conv_first": pct(sess_of, sessions)},
    ]

    # OnlyFans personal: by model / by cta_source / by mode
    of_match = dict(match, tipo={"$in": EV["of_click"]})
    of_by_model = await group_count(match, "model_slug", EV["of_click"])
    of_by_source = await group_count(match, "cta_source", EV["of_click"])
    of_after_swipe = await events_col.count_documents(dict(of_match, **{"meta.swipes": {"$gt": 0}}))
    of_with_journey = await events_col.count_documents(dict(of_match, **{"meta.swipes": {"$exists": True}}))
    # OnlyFans global
    glob_by_model = await group_count(match, "model_slug", EV["of_global_profile"])
    glob_by_mode = await group_count(match, "meta.mode", EV["of_global_home"] + EV["of_global_profile"])
    glob_by_camp = await group_count(match, "meta.campagna", EV["of_global_home"] + EV["of_global_profile"])
    glob_by_fonte = await group_count(match, "meta.fonte", EV["of_global_home"] + EV["of_global_profile"])
    glob_by_hour = []
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["of_global_home"] + EV["of_global_profile"]})},
                                         {"$group": {"_id": {"$substr": ["$timestamp", 11, 2]}, "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]):
        glob_by_hour.append({"ora": r["_id"], "n": r["n"]})

    # swipe
    swipe_in_by_model = await group_count(match, "model_slug", EV["swipe_in"])
    swipe_by_dir = {"next": counts.get("profile_swipe_next", 0), "previous": counts.get("profile_swipe_previous", 0),
                    "arrivi_public": counts.get("profile_swipe_public", 0), "arrivi_secret": counts.get("profile_swipe_secret", 0)}
    sess_swipe = await distinct_sessions(match, EV["swipe_out"])
    # secret per model
    secret_by_model = await group_count(match, "model_slug", EV["secret_activate"])
    # home
    home = {
        "toggle_secret_on": sum_ev(counts, "home_toggle_on"),
        "toggle_totali": sum_ev(counts, "home_toggle"),
        "sorprendimi_click": surprise,
        "sorprendimi_profili_aperti": sum_ev(counts, "surprise_open"),
        "filmstrip_impression": sum_ev(counts, "filmstrip_impression"),
        "filmstrip_video_view": sum_ev(counts, "filmstrip_video"),
        "filmstrip_click_profilo": sum_ev(counts, "filmstrip_click"),
        "marquee_home_click": sum_ev(counts, "of_global_home"),
        "profili_via_swipe": sum_ev(counts, "swipe_in"),
        "landing_da_campagna": sum_ev(counts, "landing"),
    }
    # sources
    by_source = await group_count(match, "source")
    by_device = await group_count(match, "device")
    by_fonte = await group_count(match, "fonte")
    by_campagna = await group_count(match, "campagna")
    sources_detail = []
    async for r in events_col.aggregate([
        {"$match": dict(match, source={"$nin": [None, ""]})},
        {"$group": {"_id": "$source", "sessioni": {"$addToSet": "$session_id"},
                    "profili": {"$sum": {"$cond": [{"$in": ["$tipo", EV["profile_view"]]}, 1, 0]}},
                    "secret": {"$sum": {"$cond": [{"$in": ["$tipo", EV["secret_activate"]]}, 1, 0]}},
                    "of": {"$sum": {"$cond": [{"$in": ["$tipo", EV["of_click"]]}, 1, 0]}}}},
        {"$project": {"sessioni": {"$size": "$sessioni"}, "profili": 1, "secret": 1, "of": 1}}, {"$sort": {"sessioni": -1}}]):
        sources_detail.append({"source": r["_id"], "sessioni": r["sessioni"], "profili": r["profili"], "secret": r["secret"], "of_click": r["of"], "ctr_of": pct(r["of"], r["profili"])})

    # top events (count + last timestamp)
    top_events = []
    async for r in events_col.aggregate([{"$match": match}, {"$group": {"_id": "$tipo", "n": {"$sum": 1}, "last": {"$max": "$timestamp"}}}, {"$sort": {"n": -1}}, {"$limit": 60}]):
        top_events.append({"evento": r["_id"], "n": r["n"], "ultimo": r["last"], "noto": (r["_id"] in {t for v in EV.values() for t in v}) or str(r["_id"]).startswith(SOCIAL_PREFIX)})
    # trend: same-length previous period
    a, b = period_bounds(f["range"], f["from"], f["to"])
    prev_match = dict(match, timestamp={"$gte": (a - (b - a)).isoformat(), "$lt": a.isoformat()})
    prev_counts = await counts_by_tipo(prev_match)
    for te in top_events:
        p = prev_counts.get(te["evento"], 0)
        te["prev"] = p
        te["trend_pct"] = pct(te["n"] - p, p) if p else None

    return {
        "filters": f, "period": {"from": a.isoformat(), "to": b.isoformat()},
        "scorecard": scorecard, "funnel": funnel,
        "onlyfans": {"personali": {"totale": of_click, "per_modella": of_by_model, "per_provenienza": of_by_source, "dopo_swipe": of_after_swipe, "con_attribuzione_swipe": of_with_journey, "sessioni": sess_of},
                     "globale": {"totale": of_global, "home": sum_ev(counts, "of_global_home"), "profili": sum_ev(counts, "of_global_profile"), "per_modella": glob_by_model, "per_modalita": glob_by_mode, "per_campagna": glob_by_camp, "per_fonte": glob_by_fonte, "per_ora": glob_by_hour}},
        "swipe": {"totali": swipes, "sessioni": sess_swipe, "per_direzione": swipe_by_dir, "modelle_raggiunte": swipe_in_by_model, "media_swipe_per_sessione": round(swipes / sess_swipe, 2) if sess_swipe else None, "of_click_dopo_swipe": of_after_swipe},
        "secret": {"attivazioni": secret, "sessioni": sess_secret, "rate_visitatori": pct(sess_secret, sessions), "rate_profili": pct(sess_secret, sess_profile), "per_modella": secret_by_model, "tempo_medio_s": secret_time_avg, "ritorni_public": sum_ev(counts, "secret_return"), "cta_click": cta_click, "of_click": of_click},
        "home": home,
        "sources": {"per_source": by_source, "per_device": by_device, "per_fonte": by_fonte, "per_campagna": by_campagna, "dettaglio": sources_detail},
        "top_events": top_events, "eventi_totali": total_events,
        "not_available": NOT_AVAILABLE,
    }


# ---------------------------------------------------------------------------------------------------------------------
# /models — one row per published model
# ---------------------------------------------------------------------------------------------------------------------
async def per_model_rows(match: dict) -> Dict[str, dict]:
    m = dict(match)
    m.pop("model_slug", None)
    pipeline = [
        {"$match": dict(m, model_slug={"$nin": [None, ""]})},
        {"$group": {
            "_id": "$model_slug",
            "visite": {"$sum": {"$cond": [{"$in": ["$tipo", EV["profile_view"]]}, 1, 0]}},
            "sess_view": {"$addToSet": {"$cond": [{"$in": ["$tipo", EV["profile_view"]]}, "$session_id", None]}},
            "secret": {"$sum": {"$cond": [{"$in": ["$tipo", EV["secret_activate"]]}, 1, 0]}},
            "cta": {"$sum": {"$cond": [{"$in": ["$tipo", EV["cta_click"]]}, 1, 0]}},
            "of": {"$sum": {"$cond": [{"$in": ["$tipo", EV["of_click"]]}, 1, 0]}},
            "social": {"$sum": {"$cond": [{"$regexMatch": {"input": {"$ifNull": ["$tipo", ""]}, "regex": "^social_click_"}}, 1, 0]}},
            "swipe_in": {"$sum": {"$cond": [{"$in": ["$tipo", EV["swipe_in"]]}, 1, 0]}},
            "swipe_out": {"$sum": {"$cond": [{"$in": ["$tipo", EV["swipe_out"]]}, 1, 0]}},
            "via_filmstrip": {"$sum": {"$cond": [{"$in": ["$tipo", EV["filmstrip_click"]]}, 1, 0]}},
            "via_surprise": {"$sum": {"$cond": [{"$in": ["$tipo", EV["surprise_open"]]}, 1, 0]}},
            "marquee": {"$sum": {"$cond": [{"$in": ["$tipo", EV["of_global_profile"]]}, 1, 0]}},
            "secret_time_sum": {"$sum": {"$cond": [{"$and": [{"$eq": ["$tipo", "secret_time"]}, {"$isNumber": "$valore"}]}, "$valore", 0]}},
            "secret_time_n": {"$sum": {"$cond": [{"$and": [{"$eq": ["$tipo", "secret_time"]}, {"$isNumber": "$valore"}]}, 1, 0]}},
            "last": {"$max": "$timestamp"},
        }},
    ]
    out: Dict[str, dict] = {}
    async for r in events_col.aggregate(pipeline):
        uniq = len([s for s in r["sess_view"] if s])
        out[r["_id"]] = {
            "visite": r["visite"], "visitatori_unici": uniq, "secret": r["secret"], "secret_rate": pct(r["secret"], r["visite"]),
            "cta_click": r["cta"], "of_click": r["of"], "ctr_of": pct(r["of"], r["visite"]), "social_click": r["social"],
            "swipe_in": r["swipe_in"], "swipe_out": r["swipe_out"], "via_home": None, "via_filmstrip": r["via_filmstrip"], "via_surprise": r["via_surprise"], "via_swipe": r["swipe_in"],
            "marquee_click": r["marquee"], "tempo_medio_profilo_s": None,
            "tempo_medio_secret_s": round(r["secret_time_sum"] / r["secret_time_n"], 1) if r["secret_time_n"] else None, "ultimo_evento": r["last"],
        }
    return out


@analytics_v2_router.get("/models")
async def models_table(f: dict = Depends(_f), admin=Depends(get_current_admin)):
    match = match_of(f)
    rows = await per_model_rows(match)
    total_views = sum(r["visite"] for r in rows.values()) or 0
    items = []
    for m in await published_models():
        r = rows.get(m["slug"]) or {"visite": 0, "visitatori_unici": 0, "secret": 0, "secret_rate": None, "cta_click": 0, "of_click": 0, "ctr_of": None, "social_click": 0, "swipe_in": 0, "swipe_out": 0,
                                    "via_home": None, "via_filmstrip": 0, "via_surprise": 0, "via_swipe": 0, "marquee_click": 0, "tempo_medio_profilo_s": None, "tempo_medio_secret_s": None, "ultimo_evento": None}
        items.append({"slug": m["slug"], "modella": m.get("nome_artistico") or m.get("nome"), "foto_card": m.get("foto_card"), "quota_traffico": pct(r["visite"], total_views), **r})
    # models that have events but are not published anymore (kept so history is not lost)
    known = {i["slug"] for i in items}
    for slug, r in rows.items():
        if slug not in known:
            items.append({"slug": slug, "modella": slug, "foto_card": None, "quota_traffico": pct(r["visite"], total_views), "non_pubblicata": True, **r})
    return {"filters": f, "items": items, "totale_visite": total_views}


# ---------------------------------------------------------------------------------------------------------------------
# /model/{slug} — detail
# ---------------------------------------------------------------------------------------------------------------------
@analytics_v2_router.get("/model/{slug}")
async def model_detail(slug: str, f: dict = Depends(_f), admin=Depends(get_current_admin)):
    f = dict(f, model=slug)
    match = match_of(f)
    counts = await counts_by_tipo(match)
    views = sum_ev(counts, "profile_view")
    sess_view = await distinct_sessions(match, EV["profile_view"])
    sess_secret = await distinct_sessions(match, EV["secret_activate"])
    secret = sum_ev(counts, "secret_activate")
    of = sum_ev(counts, "of_click")
    cta = sum_ev(counts, "cta_click")
    by_day, by_hour = [], []
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["profile_view"]})}, {"$group": {"_id": {"$substr": ["$timestamp", 0, 10]}, "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]):
        by_day.append({"giorno": r["_id"], "n": r["n"]})
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["profile_view"]})}, {"$group": {"_id": {"$substr": ["$timestamp", 11, 2]}, "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]):
        by_hour.append({"ora": r["_id"], "n": r["n"]})
    of_by_source = await group_count(match, "cta_source", EV["of_click"])
    of_match = dict(match, tipo={"$in": EV["of_click"]})
    of_public = await events_col.count_documents(dict(of_match, **{"meta.mode": {"$in": ["public", "PUBLIC"]}}))
    of_secret_explicit = await events_col.count_documents(dict(of_match, **{"meta.mode": {"$in": ["secret", "SECRET"]}}))
    of_after_swipe = await events_col.count_documents(dict(of_match, **{"meta.swipes": {"$gt": 0}}))
    social = {k[len(SOCIAL_PREFIX):]: v for k, v in counts.items() if k.startswith(SOCIAL_PREFIX)}
    swipe_from, swipe_to = [], []
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["swipe_in"]})}, {"$group": {"_id": "$meta.from", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 20}]):
        swipe_from.append({"slug": r["_id"] or "—", "n": r["n"]})
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["swipe_out"]})}, {"$group": {"_id": "$meta.to", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 20}]):
        swipe_to.append({"slug": r["_id"] or "—", "n": r["n"]})
    m = await models_col.find_one({"slug": slug}, {"_id": 0, "nome_artistico": 1, "nome": 1, "foto_card": 1, "stato": 1})
    last_ev = await events_col.find_one(match, {"_id": 0, "timestamp": 1}, sort=[("timestamp", -1)])
    return {
        "ultimo_evento": (last_ev or {}).get("timestamp"),
        "slug": slug, "modella": (m or {}).get("nome_artistico") or (m or {}).get("nome") or slug, "foto_card": (m or {}).get("foto_card"), "stato": (m or {}).get("stato"),
        "filters": f,
        "traffico": {"visite": views, "visitatori_unici": sess_view, "per_giorno": by_day, "per_ora": by_hour, "per_source": await group_count(match, "source", EV["profile_view"]),
                     "per_device": await group_count(match, "device", EV["profile_view"]), "per_campagna": await group_count(match, "campagna", EV["profile_view"]),
                     "giorno_top": max(by_day, key=lambda x: x["n"])["giorno"] if by_day else None, "ora_top": max(by_hour, key=lambda x: x["n"])["ora"] if by_hour else None,
                     "nuove_vs_ritorni": None},
        "secret": {"attivazioni": secret, "sessioni": sess_secret, "rate": pct(sess_secret, sess_view), "tempo_medio_s": await avg_valore(match, "secret_time"),
                   "ritorni_public": sum_ev(counts, "secret_return"), "public_to_secret_pct": pct(sess_secret, sess_view)},
        "onlyfans": {"cta_click": cta, "of_click": of, "ctr_of": pct(of, views), "da_public": of_public, "da_secret": of - of_public if of else 0, "da_secret_esplicito": of_secret_explicit,
                     "dopo_swipe": of_after_swipe, "dopo_filmstrip": None, "dopo_sorprendimi": None, "dopo_marquee": None, "per_provenienza": of_by_source,
                     "marquee_globale_da_questo_profilo": sum_ev(counts, "of_global_profile")},
        "social": social,
        "swipe": {"arrivi": sum_ev(counts, "swipe_in"), "uscite": sum_ev(counts, "swipe_out"), "arrivi_public": counts.get("profile_swipe_public", 0), "arrivi_secret": counts.get("profile_swipe_secret", 0),
                  "da_quale_modella": swipe_from, "verso_quale_modella": swipe_to, "permanenza_prima_swipe_s": None, "of_click_dopo_swipe": of_after_swipe},
        "media": {"disponibile": False, "nota": "Nessun evento media tracciato nel profilo (vedi not_available)."},
        "eventi": counts,
        "not_available": NOT_AVAILABLE,
    }


# ---------------------------------------------------------------------------------------------------------------------
# /timeseries — several metrics in one call, hour/day/week/month
# ---------------------------------------------------------------------------------------------------------------------
UNIT = {"hour": "hour", "day": "day", "week": "week", "month": "month"}
SERIES = {"visite": None, "profili": EV["profile_view"], "secret": EV["secret_activate"], "of_click": EV["of_click"], "swipe": EV["swipe_out"], "social": None, "marquee": EV["of_global_home"] + EV["of_global_profile"]}


@analytics_v2_router.get("/timeseries")
async def timeseries(granularity: str = "day", f: dict = Depends(_f), admin=Depends(get_current_admin)):
    unit = UNIT.get(granularity, "day")
    match = match_of(f)
    pipeline = [
        {"$match": match},
        {"$addFields": {"_ts": {"$dateFromString": {"dateString": "$timestamp", "onError": None, "onNull": None}}}},
        {"$match": {"_ts": {"$ne": None}}},
        {"$group": {
            "_id": {"$dateTrunc": {"date": "$_ts", "unit": unit, "timezone": "Europe/Rome", **({"startOfWeek": "monday"} if unit == "week" else {})}},
            "visite": {"$addToSet": "$session_id"},
            "profili": {"$sum": {"$cond": [{"$in": ["$tipo", EV["profile_view"]]}, 1, 0]}},
            "secret": {"$sum": {"$cond": [{"$in": ["$tipo", EV["secret_activate"]]}, 1, 0]}},
            "of_click": {"$sum": {"$cond": [{"$in": ["$tipo", EV["of_click"]]}, 1, 0]}},
            "swipe": {"$sum": {"$cond": [{"$in": ["$tipo", EV["swipe_out"]]}, 1, 0]}},
            "social": {"$sum": {"$cond": [{"$regexMatch": {"input": {"$ifNull": ["$tipo", ""]}, "regex": "^social_click_"}}, 1, 0]}},
            "marquee": {"$sum": {"$cond": [{"$in": ["$tipo", EV["of_global_home"] + EV["of_global_profile"]]}, 1, 0]}},
        }},
        {"$project": {"visite": {"$size": {"$filter": {"input": "$visite", "as": "s", "cond": {"$and": [{"$ne": ["$$s", None]}, {"$ne": ["$$s", ""]}]}}}}, "profili": 1, "secret": 1, "of_click": 1, "swipe": 1, "social": 1, "marquee": 1}},
        {"$sort": {"_id": 1}},
    ]
    items = []
    async for r in events_col.aggregate(pipeline):
        ts = r["_id"]
        label = ts.strftime("%d/%m %H:00") if unit == "hour" else ts.strftime("%d/%m") if unit in ("day", "week") else ts.strftime("%m/%Y")
        items.append({"t": ts.isoformat(), "label": label, **{k: r[k] for k in ("visite", "profili", "secret", "of_click", "swipe", "social", "marquee")}})
    return {"granularity": unit, "items": items}


# ---------------------------------------------------------------------------------------------------------------------
# /compare — 2..5 models side by side
# ---------------------------------------------------------------------------------------------------------------------
@analytics_v2_router.get("/compare")
async def compare(slugs: str, f: dict = Depends(_f), admin=Depends(get_current_admin)):
    wanted = [s.strip() for s in slugs.split(",") if s.strip()][:5]
    f = dict(f, model=None)
    rows = await per_model_rows(match_of(f))
    names = {m["slug"]: (m.get("nome_artistico") or m.get("nome")) for m in await published_models()}
    return {"items": [{"slug": s, "modella": names.get(s, s), **(rows.get(s) or {})} for s in wanted]}


# ---------------------------------------------------------------------------------------------------------------------
# /events — recent raw log (anonymised), paginated
# ---------------------------------------------------------------------------------------------------------------------
@analytics_v2_router.get("/events")
async def recent_events(limit: int = 50, skip: int = 0, tipo: Optional[str] = None, f: dict = Depends(_f), admin=Depends(get_current_admin)):
    match = match_of(f)
    if tipo:
        match["tipo"] = tipo
    limit = max(1, min(200, limit))
    total = await events_col.count_documents(match)
    items = []
    async for e in events_col.find(match, {"_id": 0, "id": 1, "timestamp": 1, "tipo": 1, "event": 1, "model_slug": 1, "session_id": 1, "cta_source": 1, "source": 1, "device": 1, "fonte": 1, "campagna": 1, "ref": 1, "valore": 1, "meta": 1, "country": 1}).sort("timestamp", -1).skip(skip).limit(limit):
        sid = e.get("session_id") or ""
        meta = e.get("meta") or {}
        items.append({
            "id": e.get("id"), "timestamp": e.get("timestamp"), "evento": e.get("tipo"), "canonico": e.get("event"), "modella": e.get("model_slug"),
            "mode": meta.get("mode") or ("secret" if e.get("tipo") in SECRET_ONLY else None), "source": e.get("source"), "cta_source": e.get("cta_source"),
            "device": e.get("device"), "fonte": e.get("fonte"), "campagna": e.get("campagna"), "ref": e.get("ref"), "valore": e.get("valore"), "country": e.get("country"),
            "session": (sid[:8] + "…") if len(sid) > 8 else (sid or None),
            "meta": {k: v for k, v in meta.items() if k in ("via", "to", "from", "swipes", "profiles_seen", "direction", "source")},
        })
    return {"items": items, "total": total, "limit": limit, "skip": skip}


@analytics_v2_router.get("/filters")
async def filter_options(f: dict = Depends(_f), admin=Depends(get_current_admin)):
    """Distinct values for the filter dropdowns (within the period): sources, fonti, campagne, ref, devices, event types."""
    match = match_of(dict(f, model=None, mode="all", source=None, fonte=None, campagna=None, ref=None, device=None))
    out = {}
    for key, field in (("sources", "source"), ("fonti", "fonte"), ("campagne", "campagna"), ("ref", "ref"), ("devices", "device"), ("eventi", "tipo")):
        out[key] = [r["key"] for r in await group_count(match, field, limit=100) if r["key"] != "—"]
    out["modelle"] = [{"slug": m["slug"], "nome": m.get("nome_artistico") or m.get("nome")} for m in await published_models()]
    return out


# ---------------------------------------------------------------------------------------------------------------------
# /export.csv — respects filters
# ---------------------------------------------------------------------------------------------------------------------
@analytics_v2_router.get("/export.csv")
async def export_csv(kind: str = "models", slug: Optional[str] = None, f: dict = Depends(_f), admin=Depends(get_current_admin)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    if kind == "models":
        data = await models_table(f, admin)
        cols = ["modella", "slug", "visite", "visitatori_unici", "quota_traffico", "secret", "secret_rate", "cta_click", "of_click", "ctr_of", "social_click", "swipe_in", "swipe_out", "via_filmstrip", "via_surprise", "marquee_click", "tempo_medio_secret_s", "ultimo_evento"]
        w.writerow(cols)
        for it in data["items"]:
            w.writerow([it.get(c) for c in cols])
    elif kind == "summary":
        data = await summary(f, admin)
        w.writerow(["metrica", "valore"])
        for k, v in data["scorecard"].items():
            w.writerow([k, v])
        w.writerow([])
        w.writerow(["funnel_step", "n", "conv_prev_pct", "conv_first_pct"])
        for s in data["funnel"]:
            w.writerow([s["step"], s["n"], s["conv_prev"], s["conv_first"]])
    elif kind == "of_clicks":
        match = match_of(f)
        match["tipo"] = {"$in": EV["of_click"] + EV["of_global_home"] + EV["of_global_profile"]}
        w.writerow(["timestamp", "evento", "modella", "cta_source", "mode", "source", "device", "fonte", "campagna", "ref", "swipes_prima"])
        async for e in events_col.find(match, {"_id": 0}).sort("timestamp", -1).limit(20000):
            meta = e.get("meta") or {}
            w.writerow([e.get("timestamp"), e.get("tipo"), e.get("model_slug"), e.get("cta_source"), meta.get("mode"), e.get("source"), e.get("device"), e.get("fonte") or meta.get("fonte"), e.get("campagna") or meta.get("campagna"), e.get("ref") or meta.get("ref"), meta.get("swipes")])
    elif kind == "campaigns":
        data = await summary(f, admin)
        w.writerow(["source", "sessioni", "profili", "secret", "of_click", "ctr_of"])
        for r in data["sources"]["dettaglio"]:
            w.writerow([r["source"], r["sessioni"], r["profili"], r["secret"], r["of_click"], r["ctr_of"]])
        w.writerow([])
        w.writerow(["campagna", "eventi"])
        for r in data["sources"]["per_campagna"]:
            w.writerow([r["key"], r["n"]])
    elif kind == "model" and slug:
        d = await model_detail(slug, f, admin)
        w.writerow(["sezione", "metrica", "valore"])
        for sec in ("traffico", "secret", "onlyfans", "swipe"):
            for k, v in d[sec].items():
                if not isinstance(v, (list, dict)):
                    w.writerow([sec, k, v])
        for k, v in d["social"].items():
            w.writerow(["social", k, v])
    else:
        w.writerow(["errore", "kind non valido"])
    buf.seek(0)
    name = f"analytics_{kind}{'_' + slug if slug else ''}_{f['range']}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})
