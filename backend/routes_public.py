import uuid
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request, Response
from typing import Optional

from database import (
    models_col, categories_col, articles_col, events_col, settings_col, files_col,
    serialize_doc,
)
from schemas import TrackEventIn, TrackBatchIn
from storage import get_object
from auth import decode_token

public_router = APIRouter(prefix="/api")


def _is_admin_request(request: Request) -> bool:
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return False
    token = auth.split(" ", 1)[1].strip()
    return decode_token(token) is not None

PUBLIC_FIELDS = {
    "id", "nome", "nome_artistico", "slug", "frase", "bio", "foto_copertina",
    "foto_card", "foto_card_teaser", "categorie", "tag", "badge", "badge_tipo",
    "seo", "ordine", "data_pubblicazione", "onlyfans_url", "cta_testo",
    "teaser_copy", "social",
}


async def view_counts():
    pipeline = [
        {"$match": {"tipo": "page_view"}},
        {"$group": {"_id": "$model_id", "n": {"$sum": 1}}},
    ]
    out = {}
    async for row in events_col.aggregate(pipeline):
        if row["_id"]:
            out[row["_id"]] = row["n"]
    return out


def public_projection(doc, views=0):
    d = serialize_doc(doc)
    out = {k: d.get(k) for k in PUBLIC_FIELDS}
    # public gallery (images) + public video from pairs
    out["galleria_pubblica"] = d.get("galleria_pubblica", [])
    videos = [pr["pubblico"] for pr in d.get("media_pairs", []) if pr.get("tipo") == "video"]
    out["video_pubblici"] = videos
    out["visite"] = views
    out["has_secret"] = True
    return out


@public_router.get("/models")
async def list_models(
    categoria: Optional[str] = None,
    filtro: str = "tutte",
    q: Optional[str] = None,
    limit: int = 60,
    skip: int = 0,
):
    query = {"stato": "pubblicata"}
    if categoria and categoria != "tutte":
        query["categorie"] = categoria
    if q:
        rx = {"$regex": q.strip(), "$options": "i"}
        query["$or"] = [
            {"nome": rx}, {"nome_artistico": rx}, {"slug": rx}, {"tag": rx},
        ]
    docs = await models_col.find(query, {"_id": 0}).to_list(500)
    vc = await view_counts()
    items = [public_projection(d, vc.get(d["id"], 0)) for d in docs]

    if filtro == "nuove":
        items.sort(key=lambda x: x.get("data_pubblicazione") or "", reverse=True)
    elif filtro in ("piu-viste", "piu_viste"):
        items.sort(key=lambda x: x.get("visite", 0), reverse=True)
    elif filtro in ("in-tendenza", "in_tendenza"):
        items = [x for x in items if x.get("badge") == "IN TENDENZA"] + \
                [x for x in items if x.get("badge") != "IN TENDENZA"]
    else:
        items.sort(key=lambda x: x.get("ordine", 0))

    total = len(items)
    items = items[skip:skip + limit]
    return {"items": items, "total": total}


@public_router.get("/models/{slug}")
async def get_model(slug: str, request: Request):
    doc = await models_col.find_one({"slug": slug, "stato": "pubblicata"}, {"_id": 0})
    anteprima = False
    if not doc and _is_admin_request(request):
        doc = await models_col.find_one({"slug": slug}, {"_id": 0})
        anteprima = bool(doc)
    if not doc:
        raise HTTPException(status_code=404, detail="Modella non trovata")
    vc = await view_counts()
    out = public_projection(doc, vc.get(doc["id"], 0))
    out["anteprima"] = anteprima
    return out


@public_router.get("/models/{slug}/segreto")
async def get_model_secret(slug: str, request: Request):
    doc = await models_col.find_one({"slug": slug, "stato": "pubblicata"}, {"_id": 0})
    if not doc and _is_admin_request(request):
        doc = await models_col.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Modella non trovata")
    d = serialize_doc(doc)
    return {
        "id": d["id"],
        "slug": d["slug"],
        "bio_segreta": d.get("bio_segreta", ""),
        "foto_segreta_hero": d.get("foto_segreta_hero", ""),
        "galleria_segreta": d.get("galleria_segreta", []),
        "media_pairs": d.get("media_pairs", []),
        "tema": d.get("tema", {}),
        "regia": d.get("regia", {}),
        "cta_temporizzata": d.get("cta_temporizzata", {}),
        "social": d.get("social", {}),
        "messaggio_35s": d.get("messaggio_35s", {}),
        "onlyfans_url": d.get("onlyfans_url", ""),
        "cta_testo": d.get("cta_testo", "CONTINUA CON ME"),
        "teaser_copy": d.get("teaser_copy", ""),
    }


@public_router.get("/models/{slug}/correlate")
async def related_models(slug: str, limit: int = 4):
    doc = await models_col.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Modella non trovata")
    cats = doc.get("categorie", [])
    query = {"stato": "pubblicata", "slug": {"$ne": slug}}
    if cats:
        query["categorie"] = {"$in": cats}
    docs = await models_col.find(query, {"_id": 0}).to_list(limit)
    if len(docs) < limit:
        extra = await models_col.find(
            {"stato": "pubblicata", "slug": {"$ne": slug}}, {"_id": 0}
        ).to_list(limit + 5)
        seen = {x["slug"] for x in docs}
        for e in extra:
            if e["slug"] not in seen and len(docs) < limit:
                docs.append(e)
                seen.add(e["slug"])
    return {"items": [public_projection(d) for d in docs[:limit]]}


@public_router.get("/surprise")
async def surprise():
    docs = await models_col.find({"stato": "pubblicata"}, {"_id": 0, "slug": 1, "nome": 1, "foto_card": 1}).to_list(200)
    if not docs:
        raise HTTPException(status_code=404, detail="Nessuna modella disponibile")
    return secrets.choice(docs)


@public_router.get("/categories")
async def list_categories():
    docs = await categories_col.find({"stato": "pubblicata"}, {"_id": 0}).sort("ordine", 1).to_list(200)
    # attach counts
    counts = {}
    async for row in models_col.aggregate([
        {"$match": {"stato": "pubblicata"}},
        {"$unwind": "$categorie"},
        {"$group": {"_id": "$categorie", "n": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = row["n"]
    for d in docs:
        d["conteggio"] = counts.get(d["slug"], 0)
    return {"items": docs}


@public_router.get("/categories/{slug}")
async def get_category(slug: str):
    cat = await categories_col.find_one({"slug": slug, "stato": "pubblicata"}, {"_id": 0})
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria non trovata")
    docs = await models_col.find({"stato": "pubblicata", "categorie": slug}, {"_id": 0}).to_list(200)
    vc = await view_counts()
    return {"categoria": cat, "items": [public_projection(d, vc.get(d["id"], 0)) for d in docs]}


@public_router.get("/articles")
async def list_articles(limit: int = 30):
    docs = await articles_col.find({"stato": "pubblicato"}, {"_id": 0, "contenuto": 0}).sort("data_pubblicazione", -1).to_list(limit)
    return {"items": docs}


@public_router.get("/articles/{slug}")
async def get_article(slug: str):
    doc = await articles_col.find_one({"slug": slug, "stato": "pubblicato"}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Articolo non trovato")
    # attach related models basic info
    related = []
    for ms in doc.get("modelle_correlate", []):
        m = await models_col.find_one({"slug": ms, "stato": "pubblicata"}, {"_id": 0, "nome": 1, "nome_artistico": 1, "slug": 1, "foto_card": 1, "frase": 1, "badge": 1})
        if m:
            related.append(m)
    doc["modelle_correlate_dettaglio"] = related
    return doc


@public_router.get("/settings")
async def public_settings():
    s = await settings_col.find_one({"id": "global"}, {"_id": 0})
    if not s:
        return {"brand_name": "LATO SEGRETO"}
    return {
        "brand_name": s.get("brand_name", "LATO SEGRETO"),
        "site_description": s.get("site_description", ""),
        "footer_contatti": s.get("footer_contatti", ""),
        "global_switch_default": s.get("global_switch_default", "public"),
    }


DEFAULT_PELLICOLA_CFG = {
    "attiva": True,
    "titolo": "IN MOVIMENTO",
    "sottotitolo": "Una foto non racconta tutto.",
    "velocita": 6,
    "max_video_attivi": 8,
    "seconda_fila": False,
    "pausa_su_touch": True,
    "nomi_sempre_visibili": False,
    "inserisci_dopo_n": 10,
}


def _first_pair_video(doc, side):
    """Fallback: first video pair's public/secret url + poster."""
    for pr in doc.get("media_pairs", []):
        if pr.get("tipo") == "video":
            m = pr.get(side) or {}
            return m.get("url", ""), m.get("poster", "")
    return "", ""


@public_router.get("/pellicola")
async def get_pellicola():
    """HOME 'IN MOVIMENTO' film strip: global config + ordered items."""
    s = await settings_col.find_one({"id": "global"}, {"_id": 0}) or {}
    cfg = {**DEFAULT_PELLICOLA_CFG, **(s.get("home_pellicola") or {})}
    # clamp bounds
    try:
        cfg["max_video_attivi"] = max(4, min(12, int(cfg.get("max_video_attivi", 8))))
    except Exception:
        cfg["max_video_attivi"] = 8

    docs = await models_col.find({"stato": "pubblicata"}, {"_id": 0}).to_list(500)
    items = []
    for d in docs:
        ph = d.get("pellicola_home") or {}
        if not ph.get("attiva", True):
            continue
        pub = ph.get("pubblico") or {}
        seg = ph.get("segreto") or {}
        pub_vid, pub_pos = pub.get("video_url", ""), pub.get("poster_url", "")
        seg_vid, seg_pos = seg.get("video_url", ""), seg.get("poster_url", "")
        # fallbacks from media pairs
        if not pub_vid:
            pub_vid, pp = _first_pair_video(d, "pubblico")
            pub_pos = pub_pos or pp
        if not seg_vid:
            seg_vid, sp = _first_pair_video(d, "segreto")
            seg_pos = seg_pos or sp
        # posters fall back to card images if still missing
        pub_pos = pub_pos or d.get("foto_card", "")
        seg_pos = seg_pos or d.get("foto_card_teaser", "") or pub_pos
        if not pub_vid and not seg_vid:
            continue  # nothing to show
        items.append({
            "slug": d.get("slug"),
            "nome_artistico": d.get("nome_artistico") or d.get("nome"),
            "foto_card": d.get("foto_card", ""),
            "priorita": ph.get("priorita", 5),
            "ordine_manuale": ph.get("ordine"),
            "ordine": d.get("ordine", 0),
            "pubblico": {"video_url": pub_vid, "poster_url": pub_pos},
            "segreto": {"video_url": seg_vid or pub_vid, "poster_url": seg_pos},
        })

    def sort_key(x):
        manual = x["ordine_manuale"]
        has_manual = 0 if manual is not None else 1
        return (has_manual, manual if manual is not None else 0, -int(x.get("priorita") or 0), x.get("ordine", 0))

    items.sort(key=sort_key)
    return {"config": cfg, "items": items}


MAX_BATCH = 50
MAX_CLIENT_SKEW_MS = 60 * 60 * 1000       # ts_client offsets beyond 1h are ignored (clock skew)
_BAD_KEYS = {"password", "token", "email", "authorization", "cookie"}


def _clean_meta(meta):
    """Defensive privacy filter: never persist obviously sensitive keys even if a client sends them."""
    if not isinstance(meta, dict):
        return {}
    return {k: v for k, v in meta.items() if str(k).lower() not in _BAD_KEYS and len(str(v)) <= 500}


async def _prepare_event(ev: TrackEventIn, request: Request, received: datetime, sent_at: Optional[int], slug_ids: Optional[dict] = None) -> dict:
    doc = ev.model_dump(exclude_none=True)
    doc["id"] = str(uuid.uuid4())
    doc["meta"] = _clean_meta(doc.get("meta"))
    if doc.get("mode"):
        doc["mode"] = str(doc["mode"]).lower()
    # timestamp: server receipt time, shifted back by the client-side age of the event (keeps batch order; skew-safe)
    ts = received
    if sent_at and doc.get("ts_client"):
        age = sent_at - int(doc["ts_client"])
        if 0 <= age <= MAX_CLIENT_SKEW_MS:
            ts = received - timedelta(milliseconds=age)
    doc["timestamp"] = ts.isoformat()
    if not doc.get("session_id"):
        doc["session_id"] = doc.get("visitor_id") or ""
    if not doc.get("visitor_id") and doc.get("session_id"):
        doc["visitor_id"] = doc["session_id"]
    if not doc.get("model_id") and doc.get("model_slug"):
        if slug_ids is not None:
            if doc["model_slug"] in slug_ids:
                doc["model_id"] = slug_ids[doc["model_slug"]]
        else:
            m = await models_col.find_one({"slug": doc["model_slug"]}, {"_id": 0, "id": 1})
            if m:
                doc["model_id"] = m["id"]
    try:
        from v1_tracking import enrich_event
        enrich_event(doc, request)
    except Exception:
        pass
    return doc


@public_router.post("/track")
async def track_event(ev: TrackEventIn, request: Request):
    doc = await _prepare_event(ev, request, datetime.now(timezone.utc), None)
    await events_col.insert_one(doc)
    return {"ok": True}


@public_router.post("/track/batch")
async def track_batch(batch: TrackBatchIn, request: Request):
    """Batched ingestion used by frontend/src/lib/analytics.js (fetch keepalive / sendBeacon). Max 50 events."""
    events = batch.events[:MAX_BATCH]
    if not events:
        return {"ok": True, "accepted": 0}
    received = datetime.now(timezone.utc)
    slugs = {ev.model_slug for ev in events if ev.model_slug and not ev.model_id}
    slug_ids = {}
    if slugs:
        async for m in models_col.find({"slug": {"$in": list(slugs)}}, {"_id": 0, "id": 1, "slug": 1}):
            slug_ids[m["slug"]] = m["id"]
    docs = [await _prepare_event(ev, request, received, batch.sent_at, slug_ids) for ev in events]
    await events_col.insert_many(docs, ordered=False)
    return {"ok": True, "accepted": len(docs)}


@public_router.get("/redirects/resolve")
async def resolve_redirect(path: str):
    """Safe redirects (e.g. slug changes). Used by the frontend 404 page."""
    from database import redirects_col
    r = await redirects_col.find_one({"from_path": path, "active": True}, {"_id": 0})
    if not r:
        return {"redirect": None}
    await redirects_col.update_one({"id": r["id"]}, {"$inc": {"hits": 1}})
    return {"redirect": r["to_path"], "status_code": r.get("status_code", 301)}


@public_router.get("/uploads/{path:path}")
async def serve_upload(path: str):
    """Public serving of uploaded media (marketing content is public)."""
    record = await files_col.find_one({"storage_path": path, "is_deleted": False}, {"_id": 0})
    if not record:
        raise HTTPException(status_code=404, detail="File non trovato")
    try:
        data, ctype = get_object(path)
    except Exception:
        raise HTTPException(status_code=404, detail="File non disponibile")
    return Response(
        content=data,
        media_type=record.get("content_type", ctype),
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
