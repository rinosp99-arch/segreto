"""ADMIN ANALYTICS v2 — backend aggregations for the control-center dashboard.

Reads `analytics_events` (legacy `tipo` names + the common schema written by frontend/src/lib/analytics.js) WITHOUT
renaming, migrating or deleting anything: old, new and unknown events are all tolerated. All heavy lifting happens in
MongoDB ($match on indexed timestamp/tipo/model_slug/visit_id, $group, $facet, $dateTrunc); the browser only receives
compact aggregates. Metrics that cannot be derived from the data actually tracked are NOT invented (see NOT_AVAILABLE).

DEFINITIONS
- visita (visit)      : distinct `visit_id` (30 min inactivity / new tab / campaign landing). Legacy events without
                        visit_id count as one visit per legacy session_id ("legacy:<session_id>").
- visitatore (visitor): distinct `visitor_id` (anonymous persistent id; == legacy session_id).
- ENGAGED (funnel)    : a visit on a profile with at least one of: video_start, profile_scroll_50+, profile_engaged >= 10s,
                        or any downstream action (secret / cta click / OF click).
- funnel chiuso       : every step requires the previous ones inside the same visit -> drop-off is exact.
- CTA impression      : cta_impression (new) ∪ cta_view (legacy gallery) ∪ message_shown (legacy envelope).
  Every CTA in the profile leads to OnlyFans, so "OF impressions" == CTA impressions.
- swipe IN            : swipe/nav events whose to_model is the creator (no separate arrival event).
"""
import csv
import io
from collections import Counter
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
EV: Dict[str, List[str]] = {
    "profile_view": ["page_view"],
    "home_view": ["home_view"],
    "card_impression": ["home_model_card_impression"],
    "card_click": ["home_model_card_click", "model_card_click"],
    "search": ["home_search_use"],
    "filter": ["home_filter_use"],
    "category": ["home_category_click"],
    "secret_activate": ["secret_activate"],
    "secret_return": ["secret_return"],
    "secret_time": ["secret_time"],
    "cta_impression": ["cta_impression", "cta_view", "message_shown"],
    "cta_click": ["cta_click"],
    "cta_dismiss": ["cta_dismiss"],
    "message_open": ["message_open"],
    "teaser_click": ["teaser_finale_click"],
    "of_click": ["of_click"],
    "of_global_impression": ["of_global_marquee_impression"],
    "of_global_home": ["of_global_marquee_home_click"],
    "of_global_profile": ["of_global_marquee_profile_click"],
    "swipe_gesture": ["profile_swipe_next", "profile_swipe_previous"],
    "swipe_button": ["profile_nav_next_click", "profile_nav_prev_click"],
    "swipe_out": ["profile_swipe_next", "profile_swipe_previous", "profile_nav_next_click", "profile_nav_prev_click"],
    "swipe_in_legacy": ["profile_swipe_public", "profile_swipe_secret"],
    "surprise_click": ["home_surprise_click"],
    "surprise_open": ["home_surprise_profile_open"],
    "filmstrip_impression": ["pellicola_impression"],
    "filmstrip_video": ["pellicola_video_view"],
    "filmstrip_click": ["pellicola_click_profilo"],
    "home_toggle": ["home_toggle_secret_on", "home_toggle_secret_off", "home_mobile_toggle_secret", "home_mobile_toggle_public"],
    "home_toggle_on": ["home_toggle_secret_on", "home_mobile_toggle_secret"],
    "landing": ["landing"],
    "video_impression": ["video_impression"],
    "video_start": ["video_start"],
    "video_25": ["video_25"],
    "video_50": ["video_50"],
    "video_75": ["video_75"],
    "video_complete": ["video_complete"],
    "video_replay": ["video_replay"],
    "scroll_25": ["profile_scroll_25"],
    "scroll_50": ["profile_scroll_50"],
    "scroll_75": ["profile_scroll_75"],
    "scroll_100": ["profile_scroll_100"],
    "engaged": ["profile_engaged"],
    "interazione": ["interazione"],
    "article_view": ["article_view"],
    "visit_legacy": ["visit"],
}
SOCIAL_PREFIX = "social_click_"
KNOWN = {t for v in EV.values() for t in v}
SECRET_ONLY = {"secret_activate", "secret_time", "secret_return", "cta_view", "message_shown", "message_open", "teaser_finale_click", "profile_swipe_secret"}
PUBLIC_ONLY = {"profile_swipe_public"}
VIDEO_STEPS = ["video_impression", "video_start", "video_25", "video_50", "video_75", "video_complete", "video_replay"]
ENGAGED_TIPI = ["video_start", "profile_scroll_50", "profile_scroll_75", "profile_scroll_100", "secret_activate", "cta_click", "of_click"]
ENTRY_LABELS = {"home_card": "Card Home", "filmstrip": "FilmStrip", "surprise": "Sorprendimi", "swipe": "Swipe (gesto)", "swipe_button": "Swipe (pulsante)", "related_models": "Correlate", "direct_profile": "Diretto", "campaign": "Campagna", "search": "Ricerca", "category": "Categoria", "landing": "Landing"}

NOT_AVAILABLE = [
    {"metrica": "Eventi precedenti al 18/09/2026: visit_id, entry_source, impression, video, scroll, engaged time", "evento": "presenti solo dal rilascio del tracking v2 — i periodi precedenti mostrano '—' o valori parziali", "dove": "—"},
    {"metrica": "Referrer/URL esterno completo", "evento": "solo dominio (source) — scelta privacy", "dove": "lib/analytics.js externalReferrerHost"},
    {"metrica": "Impression foto (solo video tracciati)", "evento": "media_impression per le foto: non emesso per evitare rumore", "dove": "components/MediaMorph.js"},
    {"metrica": "Dismiss della CTA temporizzata", "evento": "la barra non ha un pulsante di chiusura: cta_dismiss esiste solo per il messaggio (busta)", "dove": "pages/ModelProfile.js"},
    {"metrica": "Città / regione", "evento": "solo paese da header CDN o lingua (nessun IP salvato)", "dove": "backend/v1_tracking._geo"},
]

# visit / visitor keys that also work for legacy events
VISIT_KEY = {"$ifNull": ["$visit_id", {"$concat": ["legacy:", {"$ifNull": ["$session_id", ""]}]}]}
VISITOR_KEY = {"$ifNull": ["$visitor_id", "$session_id"]}
MODE_EXPR = {"$toLower": {"$ifNull": ["$mode", {"$ifNull": ["$meta.mode", ""]}]}}

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
                source: Optional[str], fonte: Optional[str], campagna: Optional[str], ref: Optional[str], device: Optional[str],
                entry: Optional[str] = None) -> Dict[str, Any]:
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
    if entry and entry != "all":
        m["entry_source"] = entry
    if mode in ("public", "secret"):
        # explicit `mode` (new) or meta.mode (legacy) wins; otherwise the event family decides; neutral events pass in both modes
        other = "secret" if mode == "public" else "public"
        excluded = SECRET_ONLY if mode == "public" else PUBLIC_ONLY
        m["$and"] = [
            {"$or": [{"mode": {"$in": [mode, mode.upper()]}}, {"$and": [{"mode": {"$in": [None, ""]}}, {"$or": [{"meta.mode": {"$exists": False}}, {"meta.mode": None}, {"meta.mode": {"$in": [mode, mode.upper()]}}]}]}]},
            {"mode": {"$nin": [other, other.upper()]}},
            {"meta.mode": {"$nin": [other, other.upper()]}},
            {"tipo": {"$nin": list(excluded)}},
        ]
    return m


def _f(range_key: str = Query("30g"), date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
       model: Optional[str] = None, mode: Optional[str] = "all", source: Optional[str] = None, fonte: Optional[str] = None,
       campagna: Optional[str] = None, ref: Optional[str] = None, device: Optional[str] = None, entry: Optional[str] = None):
    return {"range": range_key, "from": date_from, "to": date_to, "model": model, "mode": mode, "source": source, "fonte": fonte, "campagna": campagna, "ref": ref, "device": device, "entry": entry}


def match_of(f: dict) -> dict:
    return build_match(f["range"], f["from"], f["to"], f["model"], f["mode"], f["source"], f["fonte"], f["campagna"], f["ref"], f["device"], f.get("entry"))


def pct(a: float, b: float) -> Optional[float]:
    return round(100.0 * a / b, 1) if b else None


def _avg(s, n) -> Optional[float]:
    return round(s / n, 1) if n else None


def _n(x) -> int:
    try:
        return int(x or 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------------------------------------------------
# Core aggregations
# ---------------------------------------------------------------------------------------------------------------------
def _cnt(tipi: List[str]) -> dict:
    return {"$sum": {"$cond": [{"$in": ["$tipo", tipi]}, 1, 0]}}


def _set_if(tipi: List[str], key_expr) -> dict:
    return {"$addToSet": {"$cond": [{"$in": ["$tipo", tipi]}, key_expr, None]}}


def _sum_if(tipi: List[str], field: str) -> dict:
    return {"$sum": {"$cond": [{"$and": [{"$in": ["$tipo", tipi]}, {"$isNumber": field}]}, field, 0]}}


def _n_if(tipi: List[str], field: str) -> dict:
    return {"$sum": {"$cond": [{"$and": [{"$in": ["$tipo", tipi]}, {"$isNumber": field}]}, 1, 0]}}


def _size(field: str) -> dict:
    return {"$size": {"$filter": {"input": f"${field}", "as": "s", "cond": {"$and": [{"$ne": ["$$s", None]}, {"$ne": ["$$s", ""]}, {"$ne": ["$$s", "legacy:"]}]}}}}


async def counts_by_tipo(match: dict) -> Dict[str, int]:
    out: Dict[str, int] = {}
    async for r in events_col.aggregate([{"$match": match}, {"$group": {"_id": "$tipo", "n": {"$sum": 1}}}]):
        out[str(r["_id"])] = r["n"]
    return out


def sum_ev(counts: Dict[str, int], key: str) -> int:
    return sum(counts.get(t, 0) for t in EV[key])


async def distinct_keys(match: dict, key_expr, tipi: Optional[List[str]] = None) -> int:
    m = dict(match)
    if tipi:
        m["tipo"] = {"$in": tipi}
    r = await events_col.aggregate([{"$match": m}, {"$group": {"_id": key_expr}}, {"$match": {"_id": {"$nin": [None, "", "legacy:"]}}}, {"$count": "n"}]).to_list(1)
    return r[0]["n"] if r else 0


async def avg_valore(match: dict, tipi: List[str]) -> Optional[float]:
    m = dict(match, tipo={"$in": tipi}, valore={"$type": "number"})
    r = await events_col.aggregate([{"$match": m}, {"$group": {"_id": None, "avg": {"$avg": "$valore"}}}]).to_list(1)
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
# Closed funnel per visit (PROFILE VIEW -> ENGAGED -> SECRET -> CTA IMPRESSION -> CTA CLICK -> OF CLICK)
# ---------------------------------------------------------------------------------------------------------------------
FUNNEL_STEPS = [("view", "Profilo aperto"), ("engaged", "Engaged"), ("secret", "Lato Segreto"), ("cta_imp", "CTA vista"), ("cta_click", "CTA click"), ("of", "Click OnlyFans")]


async def visit_funnel(match: dict) -> List[dict]:
    """One row per visit with boolean flags, reduced in Mongo; closed funnel + drop-off computed here."""
    m = dict(match)
    m["model_slug"] = m.get("model_slug") or {"$nin": [None, ""]}
    pipeline = [
        {"$match": m},
        {"$group": {
            "_id": VISIT_KEY,
            "view": {"$max": {"$cond": [{"$in": ["$tipo", EV["profile_view"]]}, 1, 0]}},
            "eng": {"$max": {"$cond": [{"$or": [{"$in": ["$tipo", ENGAGED_TIPI]}, {"$and": [{"$eq": ["$tipo", "profile_engaged"]}, {"$gte": [{"$ifNull": ["$valore", 0]}, 10]}]}]}, 1, 0]}},
            "secret": {"$max": {"$cond": [{"$in": ["$tipo", EV["secret_activate"]]}, 1, 0]}},
            "cta_imp": {"$max": {"$cond": [{"$in": ["$tipo", EV["cta_impression"]]}, 1, 0]}},
            "cta_click": {"$max": {"$cond": [{"$in": ["$tipo", EV["cta_click"]]}, 1, 0]}},
            "of": {"$max": {"$cond": [{"$in": ["$tipo", EV["of_click"]]}, 1, 0]}},
        }},
        {"$match": {"_id": {"$nin": [None, "", "legacy:"]}}},
        {"$group": {
            "_id": None,
            "view": {"$sum": "$view"},
            "engaged_raw": {"$sum": "$eng"}, "secret_raw": {"$sum": "$secret"}, "cta_imp_raw": {"$sum": "$cta_imp"}, "cta_click_raw": {"$sum": "$cta_click"}, "of_raw": {"$sum": "$of"},
            # closed: each step requires all previous ones (secret implies engaged; OF implies cta click etc. are NOT assumed)
            "engaged": {"$sum": {"$cond": [{"$and": [{"$eq": ["$view", 1]}, {"$eq": ["$eng", 1]}]}, 1, 0]}},
            "secret": {"$sum": {"$cond": [{"$and": [{"$eq": ["$view", 1]}, {"$eq": ["$eng", 1]}, {"$eq": ["$secret", 1]}]}, 1, 0]}},
            "cta_imp": {"$sum": {"$cond": [{"$and": [{"$eq": ["$view", 1]}, {"$eq": ["$eng", 1]}, {"$eq": ["$secret", 1]}, {"$eq": ["$cta_imp", 1]}]}, 1, 0]}},
            "cta_click": {"$sum": {"$cond": [{"$and": [{"$eq": ["$view", 1]}, {"$eq": ["$eng", 1]}, {"$eq": ["$secret", 1]}, {"$eq": ["$cta_imp", 1]}, {"$eq": ["$cta_click", 1]}]}, 1, 0]}},
            "of": {"$sum": {"$cond": [{"$and": [{"$eq": ["$view", 1]}, {"$eq": ["$eng", 1]}, {"$eq": ["$secret", 1]}, {"$eq": ["$cta_imp", 1]}, {"$eq": ["$cta_click", 1]}, {"$eq": ["$of", 1]}]}, 1, 0]}},
        }},
    ]
    r = (await events_col.aggregate(pipeline).to_list(1) or [{}])[0]
    steps = []
    prev = None
    for key, label in FUNNEL_STEPS:
        n = _n(r.get(key))
        raw = _n(r.get(f"{key}_raw", r.get(key)))
        steps.append({"step": label, "key": key, "n": n, "n_raw": raw, "prosegue_pct": pct(n, prev) if prev is not None else None,
                      "abbandona_pct": (round(100 - pct(n, prev), 1) if prev else None) if prev is not None else None,
                      "dal_primo_pct": pct(n, steps[0]["n"]) if steps else (100.0 if n else None)})
        prev = n
    return steps


# ---------------------------------------------------------------------------------------------------------------------
# Paths (aggregated journeys) — bounded: last N visits with a visit_id
# ---------------------------------------------------------------------------------------------------------------------
TOKEN_TIPI = ["home_view", "home_model_card_click", "pellicola_click_profilo", "home_surprise_profile_open", "home_search_use", "page_view", "secret_activate",
              "profile_swipe_next", "profile_swipe_previous", "profile_nav_next_click", "profile_nav_prev_click", "of_click", "of_global_marquee_home_click", "of_global_marquee_profile_click", "landing"]


def _token(e: dict) -> Optional[str]:
    t = e.get("t")
    if t == "home_view":
        return "HOME"
    if t == "landing":
        return "CAMPAGNA"
    if t == "home_model_card_click":
        return "CARD"
    if t == "pellicola_click_profilo":
        return "FILMSTRIP"
    if t == "home_surprise_profile_open":
        return "SORPRENDIMI"
    if t == "home_search_use":
        return "RICERCA" if (e.get("esito") == "selezione") else None
    if t == "page_view":
        return (e.get("m") or "profilo").upper()
    if t == "secret_activate":
        return "SECRET"
    if t in ("profile_swipe_next", "profile_swipe_previous"):
        return "SWIPE"
    if t in ("profile_nav_next_click", "profile_nav_prev_click"):
        return "SWIPE ‹›"
    if t == "of_click":
        return "OF"
    if t in ("of_global_marquee_home_click", "of_global_marquee_profile_click"):
        return "OF GLOBALE"
    return None


async def top_paths(match: dict, limit: int = 15, max_visits: int = 5000) -> dict:
    m = dict(match, tipo={"$in": TOKEN_TIPI}, visit_id={"$nin": [None, ""]})
    m.pop("model_slug", None)
    pipeline = [
        {"$match": m},
        {"$sort": {"visit_id": 1, "timestamp": 1, "seq": 1}},
        {"$group": {"_id": "$visit_id", "ev": {"$push": {"t": "$tipo", "m": "$model_slug", "esito": "$meta.esito"}}, "last": {"$max": "$timestamp"}}},
        {"$sort": {"last": -1}}, {"$limit": max_visits},
    ]
    counter: Counter = Counter()
    with_of: Counter = Counter()
    n_visits = 0
    async for r in events_col.aggregate(pipeline, allowDiskUse=True):
        n_visits += 1
        toks: List[str] = []
        for e in r["ev"]:
            tok = _token(e)
            if tok and (not toks or toks[-1] != tok):
                toks.append(tok)
        if not toks:
            continue
        if len(toks) > 8:
            toks = toks[:7] + ["…", toks[-1]]
        key = " → ".join(toks)
        counter[key] += 1
        if "OF" in toks or "OF GLOBALE" in toks:
            with_of[key] += 1
    items = [{"percorso": k, "n": v, "of": with_of.get(k, 0), "quota_pct": pct(v, n_visits)} for k, v in counter.most_common(limit)]
    return {"items": items, "visite_analizzate": n_visits, "limite_visite": max_visits}


# ---------------------------------------------------------------------------------------------------------------------
# Per-device comparison (same metrics side by side)
# ---------------------------------------------------------------------------------------------------------------------
async def device_compare(match: dict) -> List[dict]:
    rows = []
    async for r in events_col.aggregate([
        {"$match": dict(match, device={"$nin": [None, ""]})},
        {"$group": {"_id": "$device", "visite": {"$addToSet": VISIT_KEY}, "profili": _cnt(EV["profile_view"]), "secret": _cnt(EV["secret_activate"]),
                    "cta_imp": _cnt(EV["cta_impression"]), "cta": _cnt(EV["cta_click"]), "of": _cnt(EV["of_click"]), "of_glob": _cnt(EV["of_global_home"] + EV["of_global_profile"]),
                    "swipe": _cnt(EV["swipe_out"]), "vstart": _cnt(EV["video_start"]), "vcomplete": _cnt(EV["video_complete"]),
                    "eng_s": _sum_if(EV["engaged"], "$valore"), "eng_n": _n_if(EV["engaged"], "$valore")}},
        {"$project": {"visite": _size("visite"), "profili": 1, "secret": 1, "cta_imp": 1, "cta": 1, "of": 1, "of_glob": 1, "swipe": 1, "vstart": 1, "vcomplete": 1, "eng_s": 1, "eng_n": 1}},
        {"$sort": {"visite": -1}},
    ]):
        rows.append({"device": r["_id"], "visite": r["visite"], "profili": r["profili"], "secret": r["secret"], "secret_rate": pct(r["secret"], r["profili"]),
                     "cta_impressions": r["cta_imp"], "cta_click": r["cta"], "ctr_cta": pct(r["cta"], r["cta_imp"]), "of_click": r["of"], "ctr_of": pct(r["of"], r["profili"]),
                     "of_global_click": r["of_glob"], "swipe": r["swipe"], "video_start": r["vstart"], "video_complete": r["vcomplete"], "video_completion_pct": pct(r["vcomplete"], r["vstart"]),
                     "engaged_medio_s": _avg(r["eng_s"], r["eng_n"])})
    return rows


async def entry_sources(match: dict) -> List[dict]:
    """How visitors reach profiles (page_view.entry_source) and what each entry converts to inside the same visit."""
    m = dict(match)
    pv = dict(m, tipo={"$in": EV["profile_view"]})
    rows = []
    async for r in events_col.aggregate([{"$match": pv}, {"$group": {"_id": "$entry_source", "n": {"$sum": 1}, "visite": {"$addToSet": VISIT_KEY}}}, {"$project": {"n": 1, "visite": _size("visite")}}, {"$sort": {"n": -1}}]):
        rows.append({"entry_source": r["_id"] or "sconosciuto (legacy)", "label": ENTRY_LABELS.get(r["_id"], r["_id"] or "Sconosciuto (legacy)"), "profili": r["n"], "visite": r["visite"]})
    # downstream per entry_source (events carry the entry_source of the current profile)
    down: Dict[str, dict] = {}
    async for r in events_col.aggregate([{"$match": dict(m, entry_source={"$nin": [None, ""]})},
                                         {"$group": {"_id": "$entry_source", "secret": _cnt(EV["secret_activate"]), "of": _cnt(EV["of_click"]), "cta": _cnt(EV["cta_click"])}}]):
        down[r["_id"]] = r
    for row in rows:
        d = down.get(row["entry_source"], {})
        row.update({"secret": _n(d.get("secret")), "cta_click": _n(d.get("cta")), "of_click": _n(d.get("of")), "secret_rate": pct(_n(d.get("secret")), row["profili"]), "ctr_of": pct(_n(d.get("of")), row["profili"])})
    return rows


async def video_by_slot(match: dict) -> List[dict]:
    rows = []
    async for r in events_col.aggregate([
        {"$match": dict(match, tipo={"$in": VIDEO_STEPS})},
        {"$group": {"_id": {"slot": "$slot", "mode": MODE_EXPR}, **{s: {"$sum": {"$cond": [{"$eq": ["$tipo", s]}, 1, 0]}} for s in VIDEO_STEPS}}},
        {"$sort": {"_id.mode": 1, "_id.slot": 1}},
    ]):
        imp, start, comp = r["video_impression"], r["video_start"], r["video_complete"]
        rows.append({"slot": r["_id"].get("slot"), "mode": r["_id"].get("mode") or "—", **{s: r[s] for s in VIDEO_STEPS},
                     "start_pct": pct(start, imp), "p50_pct": pct(r["video_50"], start), "complete_pct": pct(comp, start), "complete_su_impression_pct": pct(comp, imp)})
    return rows


async def cta_by_type(match: dict) -> List[dict]:
    rows = []
    async for r in events_col.aggregate([
        {"$match": dict(match, tipo={"$in": EV["cta_impression"] + EV["cta_click"] + EV["cta_dismiss"] + EV["of_click"]})},
        {"$addFields": {"_ct": {"$ifNull": ["$cta_type", {"$switch": {"branches": [
            {"case": {"$eq": ["$tipo", "message_shown"]}, "then": "message"},
            {"case": {"$eq": ["$tipo", "cta_view"]}, "then": "gallery"},
            {"case": {"$eq": ["$cta_source", "of_click_gallery"]}, "then": "gallery"},
            {"case": {"$eq": ["$cta_source", "of_click_timed"]}, "then": "timed"},
            {"case": {"$eq": ["$cta_source", "of_click_message"]}, "then": "message"},
            {"case": {"$eq": ["$cta_source", "of_click_sticky"]}, "then": "sticky"},
        ], "default": "altro"}}]}}},
        {"$group": {"_id": "$_ct", "impressions": _cnt(EV["cta_impression"]), "click": _cnt(EV["cta_click"]), "dismiss": _cnt(EV["cta_dismiss"]), "of": _cnt(EV["of_click"]),
                    "secs_s": _sum_if(EV["cta_click"], "$valore"), "secs_n": _n_if(EV["cta_click"], "$valore")}},
        {"$sort": {"click": -1}},
    ]):
        rows.append({"cta_type": r["_id"], "impressions": r["impressions"], "click": r["click"], "dismiss": r["dismiss"], "of_click": r["of"], "ctr": pct(r["click"], r["impressions"]), "secondi_medi_al_click": _avg(r["secs_s"], r["secs_n"])})
    return rows


async def scroll_distribution(match: dict) -> dict:
    c = await counts_by_tipo(dict(match, tipo={"$in": EV["scroll_25"] + EV["scroll_50"] + EV["scroll_75"] + EV["scroll_100"] + EV["profile_view"]}))
    views = sum_ev(c, "profile_view")
    return {"profili": views, **{k: {"n": sum_ev(c, k), "pct": pct(sum_ev(c, k), views)} for k in ("scroll_25", "scroll_50", "scroll_75", "scroll_100")}}


async def engaged_stats(match: dict) -> dict:
    r = (await events_col.aggregate([
        {"$match": dict(match, tipo={"$in": EV["engaged"]}, valore={"$type": "number"})},
        {"$group": {"_id": None, "n": {"$sum": 1}, "tot": {"$sum": "$valore"}, "pub": {"$sum": {"$ifNull": ["$meta.public_s", 0]}}, "sec": {"$sum": {"$ifNull": ["$meta.secret_s", 0]}},
                    "sec_n": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$meta.secret_s", 0]}, 0]}, 1, 0]}},
                    "scroll": {"$avg": "$meta.max_scroll"}, "ge10": {"$sum": {"$cond": [{"$gte": ["$valore", 10]}, 1, 0]}}, "ge30": {"$sum": {"$cond": [{"$gte": ["$valore", 30]}, 1, 0]}}, "ge60": {"$sum": {"$cond": [{"$gte": ["$valore", 60]}, 1, 0]}}}},
    ]).to_list(1) or [{}])[0]
    n = _n(r.get("n"))
    return {"profili_misurati": n, "engaged_medio_s": _avg(r.get("tot", 0), n), "public_medio_s": _avg(r.get("pub", 0), n), "secret_medio_s": _avg(r.get("sec", 0), _n(r.get("sec_n"))),
            "scroll_medio_pct": round(r["scroll"], 1) if r.get("scroll") is not None else None,
            "oltre_10s": {"n": _n(r.get("ge10")), "pct": pct(_n(r.get("ge10")), n)}, "oltre_30s": {"n": _n(r.get("ge30")), "pct": pct(_n(r.get("ge30")), n)}, "oltre_60s": {"n": _n(r.get("ge60")), "pct": pct(_n(r.get("ge60")), n)}}


async def swipe_in_by_model(match: dict, limit: int = 50) -> List[dict]:
    m = dict(match, tipo={"$in": EV["swipe_out"]})
    m.pop("model_slug", None)
    rows = []
    async for r in events_col.aggregate([{"$match": m}, {"$group": {"_id": {"$ifNull": ["$to_model", "$meta.to"]}, "n": {"$sum": 1}}}, {"$match": {"_id": {"$nin": [None, ""]}}}, {"$sort": {"n": -1}}, {"$limit": limit}]):
        rows.append({"slug": r["_id"], "n": r["n"]})
    return rows


# ---------------------------------------------------------------------------------------------------------------------
# /summary
# ---------------------------------------------------------------------------------------------------------------------
@analytics_v2_router.get("/summary")
async def summary(f: dict = Depends(_f), admin=Depends(get_current_admin)):
    match = match_of(f)
    counts = await counts_by_tipo(match)
    total_events = sum(counts.values())
    visits = await distinct_keys(match, VISIT_KEY)
    visitors = await distinct_keys(match, VISITOR_KEY)
    visits_profile = await distinct_keys(match, VISIT_KEY, EV["profile_view"])
    visits_secret = await distinct_keys(match, VISIT_KEY, EV["secret_activate"])
    visits_of = await distinct_keys(match, VISIT_KEY, EV["of_click"])

    profile_views = sum_ev(counts, "profile_view")
    secret = sum_ev(counts, "secret_activate")
    cta_imp = sum_ev(counts, "cta_impression")
    cta_click = sum_ev(counts, "cta_click")
    of_click = sum_ev(counts, "of_click")
    of_global_imp = sum_ev(counts, "of_global_impression")
    of_global = sum_ev(counts, "of_global_home") + sum_ev(counts, "of_global_profile")
    social = sum(v for k, v in counts.items() if k.startswith(SOCIAL_PREFIX))
    swipes = sum_ev(counts, "swipe_out")
    vstart, vcomplete = sum_ev(counts, "video_start"), sum_ev(counts, "video_complete")
    eng = await engaged_stats(match)
    funnel = await visit_funnel(match)

    scorecard = {
        "visite": visits, "visitatori": visitors, "sessioni": visits, "eventi": total_events,
        "home_view": sum_ev(counts, "home_view"),
        "profili_aperti": profile_views, "visite_con_profilo": visits_profile,
        "profili_per_visita": round(profile_views / visits_profile, 2) if visits_profile else None,
        "engaged_visite": next((s["n"] for s in funnel if s["key"] == "engaged"), 0),
        "secret_attivazioni": secret, "secret_rate": pct(visits_secret, visits_profile),
        "cta_impressions": cta_imp, "cta_click": cta_click, "ctr_cta": pct(cta_click, cta_imp),
        "of_impressions": cta_imp, "of_click_personali": of_click, "ctr_of": pct(of_click, profile_views), "ctr_of_su_impression": pct(of_click, cta_imp),
        "of_global_impressions": of_global_imp, "of_click_globale": of_global, "ctr_of_globale": pct(of_global, of_global_imp), "marquee_click": of_global,
        "social_click": social, "swipe": swipes, "swipe_per_visita": round(swipes / visits_profile, 2) if visits_profile else None,
        "video_start": vstart, "video_complete": vcomplete, "video_completion_pct": pct(vcomplete, vstart),
        "engaged_medio_s": eng["engaged_medio_s"], "secret_engaged_medio_s": eng["secret_medio_s"], "scroll_medio_pct": eng["scroll_medio_pct"],
        "tempo_medio_secret_s": await avg_valore(match, EV["secret_time"]),
        "sorprendimi": sum_ev(counts, "surprise_click"), "ricerche": sum_ev(counts, "search"), "filtri": sum_ev(counts, "filter"), "categorie": sum_ev(counts, "category"),
        "visite_con_of": visits_of,
    }

    of_match = dict(match, tipo={"$in": EV["of_click"]})
    of_by_model = await group_count(match, "model_slug", EV["of_click"])
    of_by_source = await group_count(match, "cta_source", EV["of_click"])
    of_by_entry = await group_count(match, "entry_source", EV["of_click"])
    of_after_swipe = await events_col.count_documents(dict(of_match, **{"meta.swipes": {"$gt": 0}}))
    of_after_gesture = await events_col.count_documents(dict(of_match, **{"meta.last_nav_input": "gesture"}))
    of_after_button = await events_col.count_documents(dict(of_match, **{"meta.last_nav_input": {"$in": ["button", "keyboard"]}}))
    of_profiles_seen = (await events_col.aggregate([{"$match": dict(of_match, **{"meta.profiles_seen": {"$type": "number"}})}, {"$group": {"_id": None, "avg": {"$avg": "$meta.profiles_seen"}}}]).to_list(1) or [{}])[0].get("avg")

    glob_tipi = EV["of_global_home"] + EV["of_global_profile"]
    glob_by_model = await group_count(match, "model_slug", EV["of_global_profile"])
    glob_by_mode = await group_count(match, "meta.mode", glob_tipi)
    glob_by_camp = await group_count(match, "meta.campagna", glob_tipi)
    glob_by_fonte = await group_count(match, "meta.fonte", glob_tipi)
    glob_by_entry = await group_count(match, "entry_source", EV["of_global_profile"])
    glob_by_hour = []
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": glob_tipi})}, {"$group": {"_id": {"$substr": ["$timestamp", 11, 2]}, "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]):
        glob_by_hour.append({"ora": r["_id"], "n": r["n"]})
    glob_imp_home, glob_imp_profile = 0, 0
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["of_global_impression"]})}, {"$group": {"_id": "$placement", "n": {"$sum": 1}}}]):
        if r["_id"] == "profile":
            glob_imp_profile += r["n"]
        else:
            glob_imp_home += r["n"]

    swipe_in = await swipe_in_by_model(match)
    swipe_by_dir = {"next": counts.get("profile_swipe_next", 0) + counts.get("profile_nav_next_click", 0), "previous": counts.get("profile_swipe_previous", 0) + counts.get("profile_nav_prev_click", 0),
                    "gesture": sum_ev(counts, "swipe_gesture"), "button": sum_ev(counts, "swipe_button")}
    visits_swipe = await distinct_keys(match, VISIT_KEY, EV["swipe_out"])
    secret_by_model = await group_count(match, "model_slug", EV["secret_activate"])

    home = {
        "home_view": sum_ev(counts, "home_view"), "card_impressions": sum_ev(counts, "card_impression"), "card_click": sum_ev(counts, "card_click"),
        "card_ctr": pct(sum_ev(counts, "card_click"), sum_ev(counts, "card_impression")),
        "toggle_secret_on": sum_ev(counts, "home_toggle_on"), "toggle_totali": sum_ev(counts, "home_toggle"),
        "ricerche": sum_ev(counts, "search"), "filtri": sum_ev(counts, "filter"), "categorie": sum_ev(counts, "category"),
        "sorprendimi_click": sum_ev(counts, "surprise_click"), "sorprendimi_profili_aperti": sum_ev(counts, "surprise_open"),
        "filmstrip_impression": sum_ev(counts, "filmstrip_impression"), "filmstrip_video_view": sum_ev(counts, "filmstrip_video"), "filmstrip_click_profilo": sum_ev(counts, "filmstrip_click"),
        "marquee_home_impression": glob_imp_home, "marquee_home_click": sum_ev(counts, "of_global_home"), "marquee_home_ctr": pct(sum_ev(counts, "of_global_home"), glob_imp_home),
        "landing_da_campagna": sum_ev(counts, "landing"),
        "card_top": await group_count(match, "model_slug", EV["card_click"], limit=10),
        "filtri_usati": await group_count(match, "meta.filtro", EV["filter"], limit=10),
        "categorie_cliccate": await group_count(match, "meta.categoria", EV["category"], limit=10),
    }
    by_source = await group_count(match, "source")
    by_device = await group_count(match, "device")
    by_fonte = await group_count(match, "fonte")
    by_campagna = await group_count(match, "campagna")
    sources_detail = []
    async for r in events_col.aggregate([
        {"$match": dict(match, source={"$nin": [None, ""]})},
        {"$group": {"_id": "$source", "visite": {"$addToSet": VISIT_KEY}, "profili": _cnt(EV["profile_view"]), "secret": _cnt(EV["secret_activate"]), "of": _cnt(EV["of_click"])}},
        {"$project": {"visite": _size("visite"), "profili": 1, "secret": 1, "of": 1}}, {"$sort": {"visite": -1}}]):
        sources_detail.append({"source": r["_id"], "sessioni": r["visite"], "visite": r["visite"], "profili": r["profili"], "secret": r["secret"], "of_click": r["of"], "ctr_of": pct(r["of"], r["profili"])})

    top_events = []
    async for r in events_col.aggregate([{"$match": match}, {"$group": {"_id": "$tipo", "n": {"$sum": 1}, "last": {"$max": "$timestamp"}}}, {"$sort": {"n": -1}}, {"$limit": 80}]):
        top_events.append({"evento": r["_id"], "n": r["n"], "ultimo": r["last"], "noto": (r["_id"] in KNOWN) or str(r["_id"]).startswith(SOCIAL_PREFIX)})
    a, b = period_bounds(f["range"], f["from"], f["to"])
    prev_counts = await counts_by_tipo(dict(match, timestamp={"$gte": (a - (b - a)).isoformat(), "$lt": a.isoformat()}))
    for te in top_events:
        p = prev_counts.get(te["evento"], 0)
        te["prev"] = p
        te["trend_pct"] = pct(te["n"] - p, p) if p else None

    return {
        "filters": f, "period": {"from": a.isoformat(), "to": b.isoformat()},
        "scorecard": scorecard, "funnel": funnel,
        "entry_sources": await entry_sources(match),
        "percorsi": await top_paths(match),
        "device_compare": await device_compare(match),
        "engaged": eng, "scroll": await scroll_distribution(match),
        "video": {"totali": {s: sum_ev(counts, s) for s in VIDEO_STEPS}, "per_slot": await video_by_slot(match)},
        "cta": {"per_tipo": await cta_by_type(match), "impressions": cta_imp, "click": cta_click, "dismiss": sum_ev(counts, "cta_dismiss"), "ctr": pct(cta_click, cta_imp)},
        "onlyfans": {"personali": {"totale": of_click, "impressions": cta_imp, "ctr": pct(of_click, cta_imp), "per_modella": of_by_model, "per_provenienza": of_by_source, "per_entry_source": of_by_entry,
                                   "dopo_swipe": of_after_swipe, "dopo_gesture": of_after_gesture, "dopo_pulsante": of_after_button,
                                   "profili_medi_prima_del_click": round(of_profiles_seen, 2) if of_profiles_seen is not None else None, "visite": visits_of},
                     "globale": {"totale": of_global, "impressions": of_global_imp, "ctr": pct(of_global, of_global_imp), "home": sum_ev(counts, "of_global_home"), "profili": sum_ev(counts, "of_global_profile"),
                                 "impressions_home": glob_imp_home, "impressions_profili": glob_imp_profile, "ctr_home": pct(sum_ev(counts, "of_global_home"), glob_imp_home), "ctr_profili": pct(sum_ev(counts, "of_global_profile"), glob_imp_profile),
                                 "per_modella": glob_by_model, "per_modalita": glob_by_mode, "per_campagna": glob_by_camp, "per_fonte": glob_by_fonte, "per_entry_source": glob_by_entry, "per_ora": glob_by_hour}},
        "swipe": {"totali": swipes, "visite": visits_swipe, "sessioni": visits_swipe, "per_direzione": swipe_by_dir, "modelle_raggiunte": swipe_in,
                  "media_swipe_per_visita": round(swipes / visits_swipe, 2) if visits_swipe else None, "media_swipe_per_sessione": round(swipes / visits_swipe, 2) if visits_swipe else None,
                  "of_click_dopo_swipe": of_after_swipe, "of_dopo_gesture": of_after_gesture, "of_dopo_pulsante": of_after_button, "profili_medi_prima_di_of": round(of_profiles_seen, 2) if of_profiles_seen is not None else None},
        "secret": {"attivazioni": secret, "visite": visits_secret, "sessioni": visits_secret, "rate_visitatori": pct(visits_secret, visits), "rate_profili": pct(visits_secret, visits_profile), "per_modella": secret_by_model,
                   "tempo_medio_s": scorecard["tempo_medio_secret_s"], "engaged_medio_s": eng["secret_medio_s"], "ritorni_public": sum_ev(counts, "secret_return"), "cta_click": cta_click, "of_click": of_click},
        "home": home,
        "sources": {"per_source": by_source, "per_device": by_device, "per_fonte": by_fonte, "per_campagna": by_campagna, "dettaglio": sources_detail},
        "top_events": top_events, "eventi_totali": total_events,
        "not_available": NOT_AVAILABLE,
    }


# ---------------------------------------------------------------------------------------------------------------------
# /models — one row per published model (all sortable columns)
# ---------------------------------------------------------------------------------------------------------------------
EMPTY_ROW = {"visite": 0, "visite_uniche": 0, "visitatori_unici": 0, "engaged": 0, "engaged_rate": None, "secret": 0, "secret_rate": None, "cta_impressions": 0, "cta_click": 0, "ctr_cta": None,
             "of_impressions": 0, "of_click": 0, "ctr_of": None, "ctr_of_su_impression": None, "social_click": 0, "swipe_in": 0, "swipe_out": 0, "video_start": 0, "video_complete": 0, "video_completion_pct": None,
             "scroll_50_pct": None, "scroll_medio_pct": None, "engaged_medio_s": None, "secret_engaged_medio_s": None, "tempo_medio_secret_s": None, "marquee_click": 0, "marquee_impressions": 0,
             "via_home": 0, "via_filmstrip": 0, "via_surprise": 0, "via_swipe": 0, "via_search": 0, "via_category": 0, "via_related": 0, "via_direct": 0, "via_campaign": 0, "ultimo_evento": None}


async def per_model_rows(match: dict) -> Dict[str, dict]:
    m = dict(match)
    m.pop("model_slug", None)
    ent = lambda v: {"$sum": {"$cond": [{"$and": [{"$in": ["$tipo", EV["profile_view"]]}, {"$eq": ["$entry_source", v]}]}, 1, 0]}}  # noqa: E731
    pipeline = [
        {"$match": dict(m, model_slug={"$nin": [None, ""]})},
        {"$group": {
            "_id": "$model_slug",
            "visite": _cnt(EV["profile_view"]),
            "visits": _set_if(EV["profile_view"], VISIT_KEY),
            "visitors": _set_if(EV["profile_view"], VISITOR_KEY),
            "eng_visits": {"$addToSet": {"$cond": [{"$or": [{"$in": ["$tipo", ENGAGED_TIPI]}, {"$and": [{"$eq": ["$tipo", "profile_engaged"]}, {"$gte": [{"$ifNull": ["$valore", 0]}, 10]}]}]}, VISIT_KEY, None]}},
            "secret": _cnt(EV["secret_activate"]),
            "cta_imp": _cnt(EV["cta_impression"]), "cta": _cnt(EV["cta_click"]), "of": _cnt(EV["of_click"]),
            "social": {"$sum": {"$cond": [{"$regexMatch": {"input": {"$ifNull": ["$tipo", ""]}, "regex": "^social_click_"}}, 1, 0]}},
            "swipe_out": _cnt(EV["swipe_out"]),
            "vstart": _cnt(EV["video_start"]), "vcomplete": _cnt(EV["video_complete"]),
            "scroll50": _cnt(EV["scroll_50"]),
            "eng_s": _sum_if(EV["engaged"], "$valore"), "eng_n": _n_if(EV["engaged"], "$valore"),
            "sec_eng_s": _sum_if(EV["engaged"], "$meta.secret_s"), "sec_eng_n": {"$sum": {"$cond": [{"$and": [{"$in": ["$tipo", EV["engaged"]]}, {"$gt": [{"$ifNull": ["$meta.secret_s", 0]}, 0]}]}, 1, 0]}},
            "scroll_s": _sum_if(EV["engaged"], "$meta.max_scroll"), "scroll_n": _n_if(EV["engaged"], "$meta.max_scroll"),
            "marquee": _cnt(EV["of_global_profile"]), "marquee_imp": _cnt(EV["of_global_impression"]),
            "secret_time_sum": _sum_if(EV["secret_time"], "$valore"), "secret_time_n": _n_if(EV["secret_time"], "$valore"),
            "via_home": ent("home_card"), "via_filmstrip": ent("filmstrip"), "via_surprise": ent("surprise"), "via_swipe": {"$sum": {"$cond": [{"$and": [{"$in": ["$tipo", EV["profile_view"]]}, {"$in": ["$entry_source", ["swipe", "swipe_button"]]}]}, 1, 0]}},
            "via_search": ent("search"), "via_category": ent("category"), "via_related": ent("related_models"), "via_direct": ent("direct_profile"), "via_campaign": ent("campaign"),
            "last": {"$max": "$timestamp"},
        }},
        {"$project": {"visite": 1, "visits": _size("visits"), "visitors": _size("visitors"), "eng_visits": _size("eng_visits"), "secret": 1, "cta_imp": 1, "cta": 1, "of": 1, "social": 1, "swipe_out": 1, "vstart": 1, "vcomplete": 1, "scroll50": 1,
                      "eng_s": 1, "eng_n": 1, "sec_eng_s": 1, "sec_eng_n": 1, "scroll_s": 1, "scroll_n": 1, "marquee": 1, "marquee_imp": 1, "secret_time_sum": 1, "secret_time_n": 1,
                      "via_home": 1, "via_filmstrip": 1, "via_surprise": 1, "via_swipe": 1, "via_search": 1, "via_category": 1, "via_related": 1, "via_direct": 1, "via_campaign": 1, "last": 1}},
    ]
    swipe_in = {r["slug"]: r["n"] for r in await swipe_in_by_model(m, limit=500)}
    out: Dict[str, dict] = {}
    async for r in events_col.aggregate(pipeline, allowDiskUse=True):
        out[r["_id"]] = {
            "visite": r["visite"], "visite_uniche": r["visits"], "visitatori_unici": r["visitors"], "engaged": r["eng_visits"], "engaged_rate": pct(r["eng_visits"], r["visits"]),
            "secret": r["secret"], "secret_rate": pct(r["secret"], r["visite"]),
            "cta_impressions": r["cta_imp"], "cta_click": r["cta"], "ctr_cta": pct(r["cta"], r["cta_imp"]),
            "of_impressions": r["cta_imp"], "of_click": r["of"], "ctr_of": pct(r["of"], r["visite"]), "ctr_of_su_impression": pct(r["of"], r["cta_imp"]),
            "social_click": r["social"], "swipe_in": swipe_in.get(r["_id"], 0), "swipe_out": r["swipe_out"],
            "video_start": r["vstart"], "video_complete": r["vcomplete"], "video_completion_pct": pct(r["vcomplete"], r["vstart"]),
            "scroll_50_pct": pct(r["scroll50"], r["visite"]), "scroll_medio_pct": _avg(r["scroll_s"], r["scroll_n"]),
            "engaged_medio_s": _avg(r["eng_s"], r["eng_n"]), "secret_engaged_medio_s": _avg(r["sec_eng_s"], r["sec_eng_n"]), "tempo_medio_secret_s": _avg(r["secret_time_sum"], r["secret_time_n"]),
            "marquee_click": r["marquee"], "marquee_impressions": r["marquee_imp"],
            "via_home": r["via_home"], "via_filmstrip": r["via_filmstrip"], "via_surprise": r["via_surprise"], "via_swipe": r["via_swipe"], "via_search": r["via_search"], "via_category": r["via_category"], "via_related": r["via_related"], "via_direct": r["via_direct"], "via_campaign": r["via_campaign"],
            "ultimo_evento": r["last"],
        }
    return out


@analytics_v2_router.get("/models")
async def models_table(f: dict = Depends(_f), admin=Depends(get_current_admin)):
    match = match_of(f)
    rows = await per_model_rows(match)
    total_views = sum(r["visite"] for r in rows.values()) or 0
    items = []
    for m in await published_models():
        r = rows.get(m["slug"]) or dict(EMPTY_ROW)
        items.append({"slug": m["slug"], "modella": m.get("nome_artistico") or m.get("nome"), "foto_card": m.get("foto_card"), "quota_traffico": pct(r["visite"], total_views), **r})
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
    visits = await distinct_keys(match, VISIT_KEY, EV["profile_view"])
    visitors = await distinct_keys(match, VISITOR_KEY, EV["profile_view"])
    visits_secret = await distinct_keys(match, VISIT_KEY, EV["secret_activate"])
    secret = sum_ev(counts, "secret_activate")
    of = sum_ev(counts, "of_click")
    cta = sum_ev(counts, "cta_click")
    cta_imp = sum_ev(counts, "cta_impression")
    by_day, by_hour = [], []
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["profile_view"]})}, {"$group": {"_id": {"$substr": ["$timestamp", 0, 10]}, "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]):
        by_day.append({"giorno": r["_id"], "n": r["n"]})
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["profile_view"]})}, {"$group": {"_id": {"$substr": ["$timestamp", 11, 2]}, "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]):
        by_hour.append({"ora": r["_id"], "n": r["n"]})
    of_hour = []
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["of_click"]})}, {"$group": {"_id": {"$substr": ["$timestamp", 11, 2]}, "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]):
        of_hour.append({"ora": r["_id"], "n": r["n"]})
    of_match = dict(match, tipo={"$in": EV["of_click"]})
    of_public = await events_col.count_documents(dict(of_match, **{"$or": [{"mode": "public"}, {"meta.mode": {"$in": ["public", "PUBLIC"]}}]}))
    of_after_swipe = await events_col.count_documents(dict(of_match, **{"meta.swipes": {"$gt": 0}}))
    of_after_gesture = await events_col.count_documents(dict(of_match, **{"meta.last_nav_input": "gesture"}))
    of_after_button = await events_col.count_documents(dict(of_match, **{"meta.last_nav_input": {"$in": ["button", "keyboard"]}}))
    social = {k[len(SOCIAL_PREFIX):]: v for k, v in counts.items() if k.startswith(SOCIAL_PREFIX)}
    social_mode = await group_count(match, "mode", [k for k in counts if k.startswith(SOCIAL_PREFIX)]) if social else []
    # swipe: OUT from this model (events of this model) / IN to this model (to_model == slug, any origin model)
    swipe_to = []
    async for r in events_col.aggregate([{"$match": dict(match, tipo={"$in": EV["swipe_out"]})}, {"$group": {"_id": {"$ifNull": ["$to_model", "$meta.to"]}, "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 20}]):
        swipe_to.append({"slug": r["_id"] or "—", "n": r["n"]})
    m_in = dict(match, tipo={"$in": EV["swipe_out"]})
    m_in.pop("model_slug", None)
    m_in["$or"] = [{"to_model": slug}, {"meta.to": slug}]
    swipe_from, swipe_in_n, swipe_in_gesture, swipe_in_button = [], 0, 0, 0
    async for r in events_col.aggregate([{"$match": m_in}, {"$group": {"_id": "$model_slug", "n": {"$sum": 1}, "g": _cnt(EV["swipe_gesture"]), "b": _cnt(EV["swipe_button"])}}, {"$sort": {"n": -1}}]):
        swipe_in_n += r["n"]; swipe_in_gesture += r["g"]; swipe_in_button += r["b"]
        if len(swipe_from) < 20:
            swipe_from.append({"slug": r["_id"] or "—", "n": r["n"]})
    m = await models_col.find_one({"slug": slug}, {"_id": 0, "nome_artistico": 1, "nome": 1, "foto_card": 1, "stato": 1})
    last_ev = await events_col.find_one(match, {"_id": 0, "timestamp": 1}, sort=[("timestamp", -1)])
    eng = await engaged_stats(match)
    return {
        "ultimo_evento": (last_ev or {}).get("timestamp"),
        "slug": slug, "modella": (m or {}).get("nome_artistico") or (m or {}).get("nome") or slug, "foto_card": (m or {}).get("foto_card"), "stato": (m or {}).get("stato"),
        "filters": f,
        "funnel": await visit_funnel(match),
        "entry_sources": await entry_sources(match),
        "device_compare": await device_compare(match),
        "traffico": {"visite": views, "visite_uniche": visits, "visitatori_unici": visitors, "per_giorno": by_day, "per_ora": by_hour, "of_per_ora": of_hour,
                     "per_source": await group_count(match, "source", EV["profile_view"]), "per_device": await group_count(match, "device", EV["profile_view"]),
                     "per_campagna": await group_count(match, "campagna", EV["profile_view"]), "per_fonte": await group_count(match, "fonte", EV["profile_view"]),
                     "giorno_top": max(by_day, key=lambda x: x["n"])["giorno"] if by_day else None, "ora_top": max(by_hour, key=lambda x: x["n"])["ora"] if by_hour else None},
        "engaged": eng, "scroll": await scroll_distribution(match),
        "secret": {"attivazioni": secret, "visite": visits_secret, "sessioni": visits_secret, "rate": pct(visits_secret, visits), "public_to_secret_pct": pct(visits_secret, visits),
                   "tempo_medio_s": await avg_valore(match, EV["secret_time"]), "engaged_medio_s": eng["secret_medio_s"], "ritorni_public": sum_ev(counts, "secret_return"),
                   "secondi_medi_prima_attivazione": await avg_valore(match, EV["secret_activate"])},
        "cta": {"per_tipo": await cta_by_type(match), "impressions": cta_imp, "click": cta, "dismiss": sum_ev(counts, "cta_dismiss"), "ctr": pct(cta, cta_imp)},
        "onlyfans": {"impressions": cta_imp, "cta_click": cta, "of_click": of, "ctr_of": pct(of, views), "ctr_of_su_impression": pct(of, cta_imp), "da_public": of_public, "da_secret": of - of_public if of else 0,
                     "dopo_swipe": of_after_swipe, "dopo_gesture": of_after_gesture, "dopo_pulsante": of_after_button, "per_provenienza": await group_count(match, "cta_source", EV["of_click"]),
                     "per_entry_source": await group_count(match, "entry_source", EV["of_click"]), "per_device": await group_count(match, "device", EV["of_click"]),
                     "marquee_globale_impressions": sum_ev(counts, "of_global_impression"), "marquee_globale_da_questo_profilo": sum_ev(counts, "of_global_profile"),
                     "marquee_ctr": pct(sum_ev(counts, "of_global_profile"), sum_ev(counts, "of_global_impression"))},
        "social": social, "social_per_mode": social_mode,
        "swipe": {"arrivi": swipe_in_n, "arrivi_gesture": swipe_in_gesture, "arrivi_pulsante": swipe_in_button, "uscite": sum_ev(counts, "swipe_out"), "uscite_gesture": sum_ev(counts, "swipe_gesture"), "uscite_pulsante": sum_ev(counts, "swipe_button"),
                  "da_quale_modella": swipe_from, "verso_quale_modella": swipe_to, "secondi_medi_prima_di_uscire": await avg_valore(match, EV["swipe_out"]), "of_click_dopo_swipe": of_after_swipe},
        "media": {"disponibile": sum(sum_ev(counts, s) for s in VIDEO_STEPS) > 0, "totali": {s: sum_ev(counts, s) for s in VIDEO_STEPS}, "per_slot": await video_by_slot(match)},
        "eventi": counts,
        "not_available": NOT_AVAILABLE,
    }


# ---------------------------------------------------------------------------------------------------------------------
# /timeseries — several metrics in one call, hour/day/week/month
# ---------------------------------------------------------------------------------------------------------------------
UNIT = {"hour": "hour", "day": "day", "week": "week", "month": "month"}
TS_KEYS = ("visite", "profili", "secret", "cta_imp", "of_click", "swipe", "social", "marquee", "video_start", "home")


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
            "visite": {"$addToSet": VISIT_KEY},
            "profili": _cnt(EV["profile_view"]), "secret": _cnt(EV["secret_activate"]), "cta_imp": _cnt(EV["cta_impression"]), "of_click": _cnt(EV["of_click"]),
            "swipe": _cnt(EV["swipe_out"]),
            "social": {"$sum": {"$cond": [{"$regexMatch": {"input": {"$ifNull": ["$tipo", ""]}, "regex": "^social_click_"}}, 1, 0]}},
            "marquee": _cnt(EV["of_global_home"] + EV["of_global_profile"]), "video_start": _cnt(EV["video_start"]), "home": _cnt(EV["home_view"]),
        }},
        {"$project": {"visite": _size("visite"), **{k: 1 for k in TS_KEYS if k != "visite"}}},
        {"$sort": {"_id": 1}},
    ]
    items = []
    async for r in events_col.aggregate(pipeline):
        ts = r["_id"]
        label = ts.strftime("%d/%m %H:00") if unit == "hour" else ts.strftime("%d/%m") if unit in ("day", "week") else ts.strftime("%m/%Y")
        items.append({"t": ts.isoformat(), "label": label, **{k: r[k] for k in TS_KEYS}})
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
# /events — recent raw log (anonymised), paginated · /visit/{id} — one journey
# ---------------------------------------------------------------------------------------------------------------------
RAW_META_KEYS = ("via", "to", "from", "swipes", "profiles_seen", "direction", "source", "position", "input", "last_nav_input", "public_s", "secret_s", "max_scroll", "esito", "filtro", "categoria", "media_mode", "dur")


def _anon_event(e: dict) -> dict:
    sid = e.get("session_id") or ""
    vid = e.get("visit_id") or ""
    meta = e.get("meta") or {}
    return {
        "id": e.get("id"), "timestamp": e.get("timestamp"), "evento": e.get("tipo"), "canonico": e.get("event"), "modella": e.get("model_slug"),
        "mode": e.get("mode") or meta.get("mode") or ("secret" if e.get("tipo") in SECRET_ONLY else None), "entry_source": e.get("entry_source"), "path": e.get("path"), "seq": e.get("seq"),
        "source": e.get("source"), "cta_source": e.get("cta_source"), "cta_type": e.get("cta_type"), "slot": e.get("slot"), "input": e.get("input"), "from_model": e.get("from_model"), "to_model": e.get("to_model"), "platform": e.get("platform"), "placement": e.get("placement"),
        "device": e.get("device"), "fonte": e.get("fonte"), "campagna": e.get("campagna"), "ref": e.get("ref"), "valore": e.get("valore"), "country": e.get("country"),
        "session": (sid[:8] + "…") if len(sid) > 8 else (sid or None), "visit": (vid[:8] + "…") if len(vid) > 8 else (vid or None), "visit_id": vid or None,
        "meta": {k: v for k, v in meta.items() if k in RAW_META_KEYS},
    }


RAW_PROJ = {"_id": 0, "id": 1, "timestamp": 1, "tipo": 1, "event": 1, "model_slug": 1, "session_id": 1, "visit_id": 1, "cta_source": 1, "cta_type": 1, "slot": 1, "input": 1, "from_model": 1, "to_model": 1, "platform": 1, "placement": 1,
            "source": 1, "device": 1, "fonte": 1, "campagna": 1, "ref": 1, "valore": 1, "meta": 1, "country": 1, "mode": 1, "entry_source": 1, "path": 1, "seq": 1}


@analytics_v2_router.get("/events")
async def recent_events(limit: int = 50, skip: int = 0, tipo: Optional[str] = None, f: dict = Depends(_f), admin=Depends(get_current_admin)):
    match = match_of(f)
    if tipo:
        match["tipo"] = tipo
    limit = max(1, min(200, limit))
    total = await events_col.count_documents(match)
    items = [_anon_event(e) async for e in events_col.find(match, RAW_PROJ).sort("timestamp", -1).skip(skip).limit(limit)]
    return {"items": items, "total": total, "limit": limit, "skip": skip}


@analytics_v2_router.get("/visit/{visit_id}")
async def visit_journey(visit_id: str, admin=Depends(get_current_admin)):
    """All events of ONE anonymous visit in order (journey reconstruction). Max 500 events."""
    items = [_anon_event(e) async for e in events_col.find({"visit_id": visit_id}, RAW_PROJ).sort([("timestamp", 1), ("seq", 1)]).limit(500)]
    toks = []
    for e in items:
        tok = _token({"t": e["evento"], "m": e["modella"], "esito": (e.get("meta") or {}).get("esito")})
        if tok and (not toks or toks[-1] != tok):
            toks.append(tok)
    return {"visit_id": visit_id, "items": items, "percorso": " → ".join(toks), "n": len(items)}


@analytics_v2_router.get("/filters")
async def filter_options(f: dict = Depends(_f), admin=Depends(get_current_admin)):
    """Distinct values for the filter dropdowns (within the period): sources, fonti, campagne, ref, devices, entry sources, event types."""
    match = match_of(dict(f, model=None, mode="all", source=None, fonte=None, campagna=None, ref=None, device=None, entry=None))
    out = {}
    for key, field in (("sources", "source"), ("fonti", "fonte"), ("campagne", "campagna"), ("ref", "ref"), ("devices", "device"), ("entry_sources", "entry_source"), ("eventi", "tipo")):
        out[key] = [r["key"] for r in await group_count(match, field, limit=100) if r["key"] != "—"]
    out["modelle"] = [{"slug": m["slug"], "nome": m.get("nome_artistico") or m.get("nome")} for m in await published_models()]
    out["entry_labels"] = ENTRY_LABELS
    return out


# ---------------------------------------------------------------------------------------------------------------------
# /export.csv — respects filters
# ---------------------------------------------------------------------------------------------------------------------
MODEL_COLS = ["modella", "slug", "visite", "visite_uniche", "visitatori_unici", "quota_traffico", "engaged", "engaged_rate", "secret", "secret_rate", "cta_impressions", "cta_click", "ctr_cta", "of_impressions", "of_click", "ctr_of", "ctr_of_su_impression",
              "social_click", "swipe_in", "swipe_out", "video_start", "video_complete", "video_completion_pct", "scroll_50_pct", "scroll_medio_pct", "engaged_medio_s", "secret_engaged_medio_s", "tempo_medio_secret_s",
              "marquee_impressions", "marquee_click", "via_home", "via_filmstrip", "via_surprise", "via_swipe", "via_search", "via_category", "via_related", "via_direct", "via_campaign", "ultimo_evento"]


@analytics_v2_router.get("/export.csv")
async def export_csv(kind: str = "models", slug: Optional[str] = None, f: dict = Depends(_f), admin=Depends(get_current_admin)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    if kind == "models":
        data = await models_table(f, admin)
        w.writerow(MODEL_COLS)
        for it in data["items"]:
            w.writerow([it.get(c) for c in MODEL_COLS])
    elif kind == "summary":
        data = await summary(f, admin)
        w.writerow(["metrica", "valore"])
        for k, v in data["scorecard"].items():
            w.writerow([k, v])
        w.writerow([])
        w.writerow(["funnel_step", "n", "n_grezzo", "prosegue_pct", "abbandona_pct", "dal_primo_pct"])
        for s in data["funnel"]:
            w.writerow([s["step"], s["n"], s["n_raw"], s["prosegue_pct"], s["abbandona_pct"], s["dal_primo_pct"]])
        w.writerow([])
        w.writerow(["entry_source", "profili", "visite", "secret", "of_click", "ctr_of"])
        for r in data["entry_sources"]:
            w.writerow([r["entry_source"], r["profili"], r["visite"], r["secret"], r["of_click"], r["ctr_of"]])
        w.writerow([])
        w.writerow(["percorso", "visite", "con_of", "quota_pct"])
        for r in data["percorsi"]["items"]:
            w.writerow([r["percorso"], r["n"], r["of"], r["quota_pct"]])
    elif kind == "of_clicks":
        match = match_of(f)
        match["tipo"] = {"$in": EV["of_click"] + EV["of_global_home"] + EV["of_global_profile"]}
        w.writerow(["timestamp", "evento", "modella", "cta_source", "cta_type", "mode", "entry_source", "source", "device", "fonte", "campagna", "ref", "swipes_prima", "profili_prima", "ultimo_input_nav", "secondi_dal_profilo"])
        async for e in events_col.find(match, {"_id": 0}).sort("timestamp", -1).limit(20000):
            meta = e.get("meta") or {}
            w.writerow([e.get("timestamp"), e.get("tipo"), e.get("model_slug"), e.get("cta_source"), e.get("cta_type"), e.get("mode") or meta.get("mode"), e.get("entry_source"), e.get("source"), e.get("device"),
                        e.get("fonte") or meta.get("fonte"), e.get("campagna") or meta.get("campagna"), e.get("ref") or meta.get("ref"), meta.get("swipes"), meta.get("profiles_seen"), meta.get("last_nav_input"), e.get("valore")])
    elif kind == "campaigns":
        data = await summary(f, admin)
        w.writerow(["source", "visite", "profili", "secret", "of_click", "ctr_of"])
        for r in data["sources"]["dettaglio"]:
            w.writerow([r["source"], r["visite"], r["profili"], r["secret"], r["of_click"], r["ctr_of"]])
        w.writerow([])
        w.writerow(["campagna", "eventi"])
        for r in data["sources"]["per_campagna"]:
            w.writerow([r["key"], r["n"]])
    elif kind == "model" and slug:
        d = await model_detail(slug, f, admin)
        w.writerow(["sezione", "metrica", "valore"])
        for sec in ("traffico", "secret", "onlyfans", "swipe", "engaged", "cta"):
            for k, v in d[sec].items():
                if not isinstance(v, (list, dict)):
                    w.writerow([sec, k, v])
        for k, v in d["social"].items():
            w.writerow(["social", k, v])
        w.writerow([])
        w.writerow(["funnel_step", "n", "n_grezzo", "prosegue_pct", "abbandona_pct"])
        for s in d["funnel"]:
            w.writerow([s["step"], s["n"], s["n_raw"], s["prosegue_pct"], s["abbandona_pct"]])
        w.writerow([])
        w.writerow(["video_slot", "mode", *VIDEO_STEPS, "start_pct", "complete_pct"])
        for r in d["media"]["per_slot"]:
            w.writerow([r["slot"], r["mode"], *[r[s] for s in VIDEO_STEPS], r["start_pct"], r["complete_pct"]])
    else:
        w.writerow(["errore", "kind non valido"])
    buf.seek(0)
    name = f"analytics_{kind}{'_' + slug if slug else ''}_{f['range']}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})
