"""SUPER API v1 - LANDING PAGE ENGINE.

Landings are data-only for now (public JSON endpoint ready). The public frontend route
(/l/{slug}) is prepared behind the feature flag `landings.public_routes` so nothing
changes on the current site until explicitly enabled.
"""
import uuid
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from database import landings_col, models_col, config_col, now_iso, serialize_doc
from sanitize import slugify, sanitize_html
from v1_security import require, actor_of, request_id_of
from v1_versioning import record_version, audit_log

landings_router = APIRouter(prefix="/api/v1/landings", tags=["Landings"])
public_landings_router = APIRouter(prefix="/api/landings", tags=["Landings"])


class LandingIn(BaseModel):
    model_config = ConfigDict(extra='allow')
    titolo: str
    slug: Optional[str] = ""
    headline: str = ""
    subtitle: str = ""
    hero: Dict[str, Any] = Field(default_factory=lambda: {"media_url": "", "media_tipo": "image", "poster": "", "overlay": "vignetta"})
    media: List[Dict[str, Any]] = []
    model_slugs: List[str] = []           # model cards to show (order preserved)
    cta: Dict[str, Any] = Field(default_factory=lambda: {"testo": "SCOPRI IL LATO SEGRETO", "url": "/", "stile": "gold", "posizione": "hero"})
    faq: List[Dict[str, str]] = []        # [{domanda, risposta}]
    seo: Dict[str, Any] = Field(default_factory=lambda: {"title": "", "meta_description": "", "canonical": "", "robots": "index,follow", "og_image": "", "structured_data_type": "WebPage", "keywords": [], "indexable": True})
    analytics: Dict[str, Any] = Field(default_factory=lambda: {"campaign": "", "utm_source": "", "goal_event": "onlyfans_click"})
    experiment_id: Optional[str] = None
    tema: Dict[str, Any] = Field(default_factory=lambda: {"modalita": "pubblico"})  # pubblico | segreto
    stato: str = "bozza"
    reason: Optional[str] = None


async def unique_slug(base: str, exclude_id: Optional[str] = None) -> str:
    base = slugify(base)
    slug, i = base, 2
    while True:
        ex = await landings_col.find_one({"slug": slug}, {"_id": 0, "id": 1})
        if not ex or ex.get("id") == exclude_id:
            return slug
        slug = f"{base}-{i}"
        i += 1


def validate_landing(doc: dict) -> dict:
    errors, warnings = [], []
    if not (doc.get("headline") or doc.get("titolo")):
        errors.append({"code": "HEADLINE_MISSING", "message": "Headline mancante"})
    if not (doc.get("cta") or {}).get("testo"):
        errors.append({"code": "CTA_MISSING", "message": "CTA mancante"})
    if not doc.get("model_slugs") and not (doc.get("hero") or {}).get("media_url"):
        warnings.append({"code": "NO_CONTENT", "message": "Nessuna modella e nessun media hero"})
    seo = doc.get("seo") or {}
    if not seo.get("title"):
        warnings.append({"code": "SEO_TITLE_MISSING", "message": "SEO title mancante (fix automatico disponibile)"})
    if not seo.get("meta_description"):
        warnings.append({"code": "SEO_META_DESCRIPTION_MISSING", "message": "Meta description mancante (fix automatico disponibile)"})
    return {"ready": not errors, "errors": errors, "warnings": warnings}


async def validate_landing_full(doc: dict) -> dict:
    """Pre-publication checks: SEO, duplicate content, slug collision, canonical, CTA, target models, media, accessibility, index status, internal links."""
    base = validate_landing(doc)
    checks = []
    def chk(code, ok, msg, level="error"):
        checks.append({"code": code, "ok": bool(ok), "message": msg, "level": level if not ok else "ok"})
    seo = doc.get("seo") or {}
    t = seo.get("title") or ""
    md = seo.get("meta_description") or ""
    chk("SEO_TITLE", bool(t), "SEO title presente" if t else "SEO title mancante", "warning")
    chk("SEO_TITLE_LENGTH", 0 < len(t) <= 65 if t else False, f"SEO title {len(t)} caratteri (max 65)", "warning")
    chk("META_DESCRIPTION", bool(md), "Meta description presente" if md else "Meta description mancante", "warning")
    chk("META_DESCRIPTION_LENGTH", 60 <= len(md) <= 170 if md else False, f"Meta description {len(md)} caratteri (60-170)", "warning")
    chk("CANONICAL", bool(seo.get("canonical")) or True, "Canonical " + (seo.get("canonical") or "(derivato dall'URL)"), "info")
    chk("INDEX_STATUS", True, f"indexable={seo.get('indexable', True)} robots={seo.get('robots', 'index,follow')}", "info")
    chk("CTA", bool((doc.get("cta") or {}).get("testo")), "CTA presente" if (doc.get("cta") or {}).get("testo") else "CTA mancante")
    # target models
    slugs = doc.get("model_slugs") or []
    published = []
    missing = []
    for sl in slugs:
        m = await models_col.find_one({"slug": sl, "is_deleted": {"$ne": True}}, {"_id": 0, "stato": 1})
        (published if m and m.get("stato") == "pubblicata" else missing).append(sl)
    chk("TARGET_MODELS", not slugs or not missing, f"{len(published)} modelle pubblicate" + (f", non pubblicate/inesistenti: {missing}" if missing else ""), "warning" if slugs else "info")
    chk("INTERNAL_LINKS", len(slugs) >= 1, f"{len(slugs)} collegamenti interni a modelle", "warning")
    hero = doc.get("hero") or {}
    chk("MEDIA", bool(hero.get("media_url")) or bool(slugs), "Media hero presente" if hero.get("media_url") else "Nessun media hero (usa le card modelle)", "warning")
    chk("ACCESSIBILITY_ALT", (not hero.get("media_url")) or bool(hero.get("alt")), "ALT hero " + ("presente" if hero.get("alt") else "mancante"), "warning")
    # duplicate content / slug collision
    dup = await landings_col.find_one({"id": {"$ne": doc.get("id")}, "is_deleted": {"$ne": True}, "$or": [{"headline": doc.get("headline")}, {"seo.title": t}] if t or doc.get("headline") else [{"_none": 1}]}, {"_id": 0, "slug": 1})
    chk("DUPLICATE_CONTENT", dup is None, "Nessun duplicato" if dup is None else f"Headline/SEO title duplicati con landing '{dup['slug']}'", "warning")
    coll = await models_col.find_one({"slug": doc.get("slug")}, {"_id": 0, "id": 1})
    chk("SLUG_COLLISION", coll is None, "Slug libero" if coll is None else "Slug coincide con una modella (confusione URL)", "warning")
    errors = [c for c in checks if not c["ok"] and c["level"] == "error"] + [{"code": e["code"], "message": e["message"], "level": "error", "ok": False} for e in base["errors"]]
    warnings = [c for c in checks if not c["ok"] and c["level"] == "warning"]
    score = max(0, 100 - len(errors) * 20 - len(warnings) * 7)
    return {"ready": not errors, "publishable": not errors, "score": score, "errors": errors, "warnings": warnings, "checks": checks}


async def resolve_landing(ref: str) -> dict:
    doc = await landings_col.find_one({"$or": [{"id": ref}, {"slug": slugify(ref)}], "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        import re
        doc = await landings_col.find_one({"titolo": {"$regex": f"^{re.escape(ref)}$", "$options": "i"}, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Landing '{ref}' non trovata"})
    return doc


def _enrich(doc: dict) -> dict:
    out = serialize_doc(doc)
    out["validation"] = validate_landing(out)
    out["workflow_status"] = "PUBLISHED" if out.get("stato") == "pubblicata" else ("READY" if out["validation"]["ready"] else "DRAFT")
    out["public_url"] = f"/l/{out.get('slug')}"
    return out


async def create_landing(data: dict, principal: dict, request: Optional[Request]) -> dict:
    body = LandingIn(**data).model_dump()
    reason = body.pop("reason", None) or "Creazione landing"
    body["slug"] = await unique_slug(body.get("slug") or body["titolo"])
    body["id"] = str(uuid.uuid4())
    body["created_at"] = body["updated_at"] = now_iso()
    body["is_deleted"] = False
    body["created_by"] = actor_of(principal)
    for f in body.get("faq") or []:
        f["risposta"] = sanitize_html(f.get("risposta", ""))
    if body["stato"] == "pubblicata" and not validate_landing(body)["ready"]:
        body["stato"] = "bozza"
    if not (body.get("seo") or {}).get("title"):
        body.setdefault("seo", {})["title"] = f"{body.get('headline') or body['titolo']} | LATO SEGRETO"
    await landings_col.insert_one(body)
    await record_version("landing", body["id"], None, body, actor_of(principal), source=principal.get("source", "manual"), reason=reason, request_id=request_id_of(request))
    await audit_log(actor_of(principal), "create", "landing", body["id"], {}, request_id_of(request), principal.get("source", "manual"))
    return _enrich(await landings_col.find_one({"id": body["id"]}, {"_id": 0}))


async def patch_landing(doc: dict, changes: dict, principal: dict, request: Optional[Request], reason: str = "") -> dict:
    from v1_models import deep_merge
    allowed = set(LandingIn.model_fields.keys()) - {"reason"}
    changes = {k: v for k, v in (changes or {}).items() if k in allowed}
    if not changes:
        raise HTTPException(status_code=400, detail="Nessun campo modificabile")
    merged = deep_merge(doc, changes)
    if "slug" in changes and changes["slug"]:
        merged["slug"] = await unique_slug(changes["slug"], exclude_id=doc["id"])
    else:
        merged["slug"] = doc["slug"]
    for f in merged.get("faq") or []:
        f["risposta"] = sanitize_html(f.get("risposta", ""))
    if merged.get("stato") == "pubblicata" and not validate_landing(merged)["ready"]:
        raise HTTPException(status_code=400, detail={"message": "Landing non pubblicabile", "errors": validate_landing(merged)["errors"]})
    merged["updated_at"] = now_iso()
    await landings_col.replace_one({"id": doc["id"]}, merged)
    ver = await record_version("landing", doc["id"], doc, merged, actor_of(principal), source=principal.get("source", "manual"), reason=reason or "Aggiornamento landing", request_id=request_id_of(request))
    if merged["slug"] != doc["slug"]:
        from v1_seo import ensure_redirect
        await ensure_redirect(f"/l/{doc['slug']}", f"/l/{merged['slug']}", actor_of(principal), "slug_change")
    out = _enrich(merged)
    out["version_id"] = ver.get("id")
    out["changed_fields"] = ver.get("changed_fields", [])
    return out


async def set_landing_state(doc: dict, stato: str, principal: dict, request: Optional[Request]) -> dict:
    if stato == "pubblicata":
        v = validate_landing(doc)
        if not v["ready"]:
            raise HTTPException(status_code=400, detail={"message": "Landing non pubblicabile", "errors": v["errors"]})
    new_doc = {**doc, "stato": stato, "updated_at": now_iso()}
    if stato == "pubblicata" and not doc.get("data_pubblicazione"):
        new_doc["data_pubblicazione"] = now_iso()
    await landings_col.replace_one({"id": doc["id"]}, new_doc)
    ver = await record_version("landing", doc["id"], doc, new_doc, actor_of(principal), source=principal.get("source", "manual"), reason=f"stato:{stato}", request_id=request_id_of(request))
    out = _enrich(new_doc)
    out["version_id"] = ver.get("id")
    return out


# ---------------- ROUTES ----------------
@landings_router.get("")
async def list_landings(stato: Optional[str] = None, principal=Depends(require("landings:read"))):
    q: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if stato:
        q["stato"] = stato
    docs = await landings_col.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": [_enrich(d) for d in docs], "total": len(docs)}


@landings_router.post("", status_code=201)
async def create(body: LandingIn, request: Request, principal=Depends(require("landings:write"))):
    return await create_landing(body.model_dump(), principal, request)


@landings_router.get("/{landing_id}")
async def get_landing(landing_id: str, principal=Depends(require("landings:read"))):
    return _enrich(await resolve_landing(landing_id))


@landings_router.patch("/{landing_id}")
async def patch(landing_id: str, body: Dict[str, Any], request: Request, principal=Depends(require("landings:write"))):
    doc = await resolve_landing(landing_id)
    reason = body.pop("reason", "") if isinstance(body, dict) else ""
    return await patch_landing(doc, body, principal, request, reason)


@landings_router.post("/{landing_id}/publish")
async def publish(landing_id: str, request: Request, principal=Depends(require("landings:publish"))):
    return await set_landing_state(await resolve_landing(landing_id), "pubblicata", principal, request)


@landings_router.post("/{landing_id}/unpublish")
async def unpublish(landing_id: str, request: Request, principal=Depends(require("landings:publish"))):
    return await set_landing_state(await resolve_landing(landing_id), "bozza", principal, request)


@landings_router.delete("/{landing_id}")
async def soft_delete(landing_id: str, request: Request, principal=Depends(require("landings:write"))):
    doc = await resolve_landing(landing_id)
    new_doc = {**doc, "is_deleted": True, "deleted_at": now_iso(), "stato": "bozza"}
    await landings_col.replace_one({"id": doc["id"]}, new_doc)
    ver = await record_version("landing", doc["id"], doc, new_doc, actor_of(principal), source=principal.get("source", "manual"), reason="Soft delete", request_id=request_id_of(request))
    return {"ok": True, "soft_deleted": True, "version_id": ver.get("id")}


# ---------------- PUBLIC (published only) ----------------
@public_landings_router.get("/{slug}")
async def public_landing(slug: str):
    # Phase 10: public landing routes stay OFF until the flag public_landing_routes is enabled by a human admin
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    if not (cfg.get("flags") or {}).get("public_landing_routes", False):
        raise HTTPException(status_code=404, detail="Landing non trovata")
    doc = await landings_col.find_one({"slug": slug, "stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Landing non trovata")
    from routes_public import public_projection
    cards = []
    for s in doc.get("model_slugs") or []:
        m = await models_col.find_one({"slug": s, "stato": "pubblicata"}, {"_id": 0})
        if m:
            cards.append(public_projection(m))
    out = serialize_doc(doc)
    out["model_cards"] = cards
    return out
