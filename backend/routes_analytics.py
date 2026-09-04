from datetime import datetime, timedelta, timezone
from builtins import range as _range
from fastapi import APIRouter, Depends
from typing import Optional

from database import events_col, models_col, articles_col
from auth import get_current_admin

analytics_router = APIRouter(prefix="/api/admin/analytics")


def cutoff_for(range_key: str) -> Optional[str]:
    now = datetime.now(timezone.utc)
    if range_key == "oggi":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_key in ("7g", "7d"):
        start = now - timedelta(days=7)
    elif range_key in ("30g", "30d"):
        start = now - timedelta(days=30)
    else:
        return None
    return start.isoformat()


async def counts_by_type(match: dict):
    out = {}
    async for row in events_col.aggregate([
        {"$match": match},
        {"$group": {"_id": "$tipo", "n": {"$sum": 1}}},
    ]):
        out[row["_id"]] = row["n"]
    return out


async def avg_valore(match: dict, tipo: str):
    async for row in events_col.aggregate([
        {"$match": {**match, "tipo": tipo, "valore": {"$ne": None}}},
        {"$group": {"_id": None, "avg": {"$avg": "$valore"}}},
    ]):
        return round(row.get("avg") or 0, 1)
    return 0


async def distinct_sessions(match: dict):
    vals = await events_col.distinct("session_id", {**match, "tipo": "page_view"})
    return len([v for v in vals if v])


async def model_stats(model_id: str, base_match: dict):
    match = {**base_match, "model_id": model_id}
    c = await counts_by_type(match)
    visite = c.get("page_view", 0)
    attivazioni = c.get("secret_activate", 0)
    click_of = c.get("of_click", 0)
    return {
        "visite": visite,
        "unici": await distinct_sessions(match),
        "attivazioni": attivazioni,
        "perc_attivazione": round(attivazioni / visite * 100, 1) if visite else 0,
        "tempo_medio_attivazione": await avg_valore(match, "secret_activate"),
        "tempo_medio_segreto": await avg_valore(match, "secret_time"),
        "interazioni": c.get("interazione", 0),
        "messaggi_mostrati": c.get("message_shown", 0),
        "messaggi_aperti": c.get("message_open", 0),
        "click_cta": c.get("cta_click", 0),
        "click_of": click_of,
        "ctr_of": round(click_of / visite * 100, 1) if visite else 0,
    }


@analytics_router.get("/overview")
async def overview(range: str = "oggi", admin=Depends(get_current_admin)):
    cut = cutoff_for(range)
    match = {"timestamp": {"$gte": cut}} if cut else {}
    c = await counts_by_type(match)
    visite = c.get("page_view", 0)
    attivazioni = c.get("secret_activate", 0)
    click_of = c.get("of_click", 0)

    # per-model to find best
    models = await models_col.find({}, {"_id": 0, "id": 1, "nome_artistico": 1, "slug": 1, "foto_card": 1}).to_list(500)
    best_visite = None
    best_ctr = None
    for m in models:
        st = await model_stats(m["id"], match)
        row = {**m, **st}
        if st["visite"] > 0:
            if best_visite is None or st["visite"] > best_visite["visite"]:
                best_visite = row
            if best_ctr is None or st["ctr_of"] > best_ctr["ctr_of"]:
                best_ctr = row
    return {
        "range": range,
        "visite": visite,
        "attivazioni": attivazioni,
        "perc_attivazione": round(attivazioni / visite * 100, 1) if visite else 0,
        "click_of": click_of,
        "ctr_medio": round(click_of / visite * 100, 1) if visite else 0,
        "messaggi_aperti": c.get("message_open", 0),
        "modella_top_visite": best_visite,
        "modella_top_ctr": best_ctr,
    }


@analytics_router.get("/funnel")
async def funnel(range: str = "30g", model_id: Optional[str] = None, admin=Depends(get_current_admin)):
    cut = cutoff_for(range)
    match = {}
    if cut:
        match["timestamp"] = {"$gte": cut}
    if model_id:
        match["model_id"] = model_id
    c = await counts_by_type(match)
    steps = [
        {"nome": "Visita", "valore": c.get("page_view", 0)},
        {"nome": "Lato Segreto", "valore": c.get("secret_activate", 0)},
        {"nome": "Interazione", "valore": c.get("interazione", 0)},
        {"nome": "Messaggio", "valore": c.get("message_open", 0)},
        {"nome": "Click OnlyFans", "valore": c.get("of_click", 0)},
    ]
    top = steps[0]["valore"] or 1
    for s in steps:
        s["percentuale"] = round(s["valore"] / top * 100, 1)
    # conversion between consecutive steps
    for i in _range(1, len(steps)):
        prev = steps[i - 1]["valore"] or 1
        steps[i]["conversione"] = round(steps[i]["valore"] / prev * 100, 1)
    steps[0]["conversione"] = 100.0
    return {"range": range, "steps": steps}


@analytics_router.get("/models")
async def leaderboard(range: str = "30g", admin=Depends(get_current_admin)):
    cut = cutoff_for(range)
    match = {"timestamp": {"$gte": cut}} if cut else {}
    models = await models_col.find({}, {"_id": 0, "id": 1, "nome_artistico": 1, "slug": 1, "foto_card": 1, "stato": 1, "badge": 1}).sort("ordine", 1).to_list(500)
    rows = []
    for m in models:
        st = await model_stats(m["id"], match)
        rows.append({**m, **st})
    rows.sort(key=lambda r: r["visite"], reverse=True)
    return {"range": range, "items": rows}


@analytics_router.get("/model/{model_id}")
async def model_detail(model_id: str, range: str = "30g", admin=Depends(get_current_admin)):
    cut = cutoff_for(range)
    match = {"timestamp": {"$gte": cut}} if cut else {}
    st = await model_stats(model_id, match)
    m = await models_col.find_one({"id": model_id}, {"_id": 0, "nome_artistico": 1, "slug": 1})
    # cta source breakdown
    sources = {}
    async for row in events_col.aggregate([
        {"$match": {**match, "model_id": model_id, "tipo": "of_click"}},
        {"$group": {"_id": "$cta_source", "n": {"$sum": 1}}},
    ]):
        sources[row["_id"] or "sconosciuto"] = row["n"]
    return {"modella": m, "stats": st, "sorgenti_of": sources}


@analytics_router.get("/timeseries")
async def timeseries(range: str = "30g", admin=Depends(get_current_admin)):
    cut = cutoff_for(range) or (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    match = {"timestamp": {"$gte": cut}}
    series = {}
    async for row in events_col.aggregate([
        {"$match": match},
        {"$group": {
            "_id": {"giorno": {"$substr": ["$timestamp", 0, 10]}, "tipo": "$tipo"},
            "n": {"$sum": 1},
        }},
    ]):
        day = row["_id"]["giorno"]
        tipo = row["_id"]["tipo"]
        series.setdefault(day, {"giorno": day, "visite": 0, "attivazioni": 0, "click_of": 0})
        if tipo == "page_view":
            series[day]["visite"] = row["n"]
        elif tipo == "secret_activate":
            series[day]["attivazioni"] = row["n"]
        elif tipo == "of_click":
            series[day]["click_of"] = row["n"]
    return {"items": sorted(series.values(), key=lambda x: x["giorno"])}


@analytics_router.get("/campaigns")
async def campaigns(range: str = "30g", admin=Depends(get_current_admin)):
    cut = cutoff_for(range)
    match = {"ref": {"$nin": [None, ""]}}
    if cut:
        match["timestamp"] = {"$gte": cut}
    agg = {}
    async for r in events_col.aggregate([
        {"$match": match},
        {"$group": {"_id": {"ref": "$ref", "fonte": "$fonte", "campagna": "$campagna", "tipo": "$tipo"}, "n": {"$sum": 1}}},
    ]):
        k = (r["_id"].get("ref"), r["_id"].get("fonte") or "diretta", r["_id"].get("campagna") or "-")
        agg.setdefault(k, {})[r["_id"]["tipo"]] = r["n"]
    # map ref (slug) -> nome
    names = {}
    async for m in models_col.find({}, {"_id": 0, "slug": 1, "nome_artistico": 1}):
        names[m["slug"]] = m["nome_artistico"]
    items = []
    for (ref, fonte, campagna), c in agg.items():
        aperture = c.get("page_view", 0)
        of = c.get("of_click", 0)
        items.append({
            "modella": names.get(ref, ref), "ref": ref, "fonte": fonte, "campagna": campagna,
            "visite": c.get("landing", 0),
            "aperture_profilo": aperture,
            "attivazioni": c.get("secret_activate", 0),
            "click_of": of,
            "ctr_of": round(of / aperture * 100, 1) if aperture else 0,
        })
    items.sort(key=lambda x: x["aperture_profilo"], reverse=True)
    return {"range": range, "items": items}


@analytics_router.get("/articles")
async def article_stats(range: str = "30g", admin=Depends(get_current_admin)):
    cut = cutoff_for(range)
    match = {"tipo": "article_view"}
    if cut:
        match["timestamp"] = {"$gte": cut}
    counts = {}
    async for row in events_col.aggregate([
        {"$match": match},
        {"$group": {"_id": "$article_id", "n": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = row["n"]
    arts = await articles_col.find({}, {"_id": 0, "id": 1, "titolo": 1, "slug": 1, "stato": 1}).to_list(300)
    rows = [{**a, "visite": counts.get(a["id"], 0)} for a in arts]
    rows.sort(key=lambda r: r["visite"], reverse=True)
    return {"items": rows}
