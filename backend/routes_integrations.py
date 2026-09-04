import os
import uuid
from fastapi import APIRouter, HTTPException, Header
from typing import Optional

from database import articles_col, settings_col, audit_col, now_iso
from schemas import WebhookArticleIn
from sanitize import sanitize_html, slugify

integrations_router = APIRouter(prefix="/api/integrations")

SEO_WEBHOOK_KEY = os.environ.get("SEO_WEBHOOK_KEY", "")


def _check_key(x_api_key: Optional[str]):
    if not SEO_WEBHOOK_KEY:
        raise HTTPException(status_code=503, detail="Integrazione non configurata")
    if not x_api_key or x_api_key != SEO_WEBHOOK_KEY:
        raise HTTPException(status_code=401, detail="API key non valida")


@integrations_router.post("/seo/articles")
async def receive_article(
    body: WebhookArticleIn,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Secure endpoint for future SEO platforms (e.g. Soro).
    Content is sanitized. Default: arrives as BOZZA (auto-publish OFF)."""
    _check_key(x_api_key)

    settings = await settings_col.find_one({"id": "global"}, {"_id": 0}) or {}
    auto_publish = bool(settings.get("auto_publish_articles", False))

    data = body.model_dump()
    slug = slugify(data.get("slug") or data["titolo"])
    contenuto = sanitize_html(data.get("contenuto", ""))

    # dedupe by external_id first, then slug
    existing = None
    if data.get("external_id"):
        existing = await articles_col.find_one({"external_id": data["external_id"]})
    if not existing:
        existing = await articles_col.find_one({"slug": slug})

    doc_common = {
        "titolo": data["titolo"],
        "estratto": data.get("estratto", ""),
        "contenuto": contenuto,
        "immagine_principale": data.get("immagine_principale", ""),
        "autore": data.get("autore", "Soro SEO"),
        "categorie": data.get("categorie", []),
        "tag": data.get("tag", []),
        "keyword_principale": data.get("keyword_principale", ""),
        "keyword_secondarie": data.get("keyword_secondarie", []),
        "seo_title": data.get("seo_title", "") or data["titolo"],
        "meta_description": data.get("meta_description", "") or data.get("estratto", ""),
        "external_id": data.get("external_id"),
        "fonte": "webhook",
        "data_aggiornamento": now_iso(),
        "indicizzabile": True,
    }

    if existing:
        # update, keep publication state unless auto_publish forces publish
        upd = dict(doc_common)
        if auto_publish and existing.get("stato") != "pubblicato":
            upd["stato"] = "pubblicato"
            upd["data_pubblicazione"] = now_iso()
        await articles_col.update_one({"id": existing["id"]}, {"$set": upd})
        await audit_col.insert_one({
            "id": str(uuid.uuid4()), "actor": "webhook:soro", "action": "update",
            "entity": "article", "entity_id": existing["id"],
            "meta": {"auto_publish": auto_publish}, "timestamp": now_iso(),
        })
        return {"ok": True, "azione": "aggiornato", "id": existing["id"], "stato": upd.get("stato", existing.get("stato")), "auto_publish": auto_publish}

    new_id = str(uuid.uuid4())
    doc = {
        "id": new_id, "slug": slug,
        "stato": "pubblicato" if auto_publish else "bozza",
        "immagini_interne": [], "canonical": "", "alt_text": data["titolo"],
        "og_image": data.get("immagine_principale", ""), "internal_links": [],
        "cta": {}, "modelle_correlate": [],
        "data_pubblicazione": now_iso() if auto_publish else None,
        "created_at": now_iso(),
        **doc_common,
    }
    await articles_col.insert_one(doc)
    await audit_col.insert_one({
        "id": str(uuid.uuid4()), "actor": "webhook:soro", "action": "create",
        "entity": "article", "entity_id": new_id,
        "meta": {"auto_publish": auto_publish}, "timestamp": now_iso(),
    })
    return {"ok": True, "azione": "creato", "id": new_id, "stato": doc["stato"], "auto_publish": auto_publish}
