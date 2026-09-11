"""SUPER API v1 - MODEL MANAGEMENT.

Workflow status: DRAFT -> INCOMPLETE -> READY -> PUBLISHED -> ARCHIVED (+ ERROR).
Underlying storage keeps the legacy `stato` (bozza|pubblicata|disattivata|archiviata) so the
public site and the existing admin keep working untouched.
"""
import re
import uuid
import copy
from typing import Optional, Any, Dict
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from pydantic import BaseModel, ConfigDict

from database import models_col, categories_col, now_iso, serialize_doc
from schemas import ModelIn
from sanitize import slugify
from content_status import compute_readiness, compute_content_status
from v1_security import require, actor_of, request_id_of
from v1_versioning import record_version, audit_log

models_router = APIRouter(prefix="/api/v1/models", tags=["Models"])

# CANONICAL OnlyFans URL rule (single source of truth: validator, model-health, SEO engine, global health, tracking all import this).
# Accepts https://onlyfans.com/<user>, /<user>/c<N> (tracking), /<user>/trial/<code>, optional query string.
OF_RX = re.compile(r"^https://(www\.)?onlyfans\.com/[A-Za-z0-9_.\-]+(/(c\d+|trial/[A-Za-z0-9_\-]+))?/?(\?[A-Za-z0-9_=&%.\-]*)?$")


def onlyfans_url_status(url) -> str:
    """'ok' | 'missing' | 'invalid' - structural check only (no HTTP: OnlyFans blocks server-side bots; reachability is never
    treated as URL validity)."""
    u = (url or "").strip()
    if not u:
        return "missing"
    return "ok" if OF_RX.match(u) else "invalid"
REQUIRED_CODES = {
    "Creator maggiorenne confermata": "AGE_CONFIRMATION_MISSING",
    "Nome": "NAME_MISSING",
    "Slug (URL)": "SLUG_MISSING",
    "Foto card Home": "CARD_PHOTO_MISSING",
    "3 foto Lato Pubblico": "PUBLIC_PHOTOS_LT_3",
    "3 foto Lato Segreto": "SECRET_PHOTOS_LT_3",
    "Video pubblico 1": "PUBLIC_VIDEO_MISSING",
    "Video segreto 1": "SECRET_VIDEO_MISSING",
    "Claim": "CLAIM_MISSING",
    "Descrizione pubblica": "PUBLIC_BIO_MISSING",
    "Descrizione Lato Segreto": "SECRET_BIO_MISSING",
    "Link OnlyFans": "ONLYFANS_URL_MISSING",
    "Video Pellicola pubblico": "PELLICOLA_PUBLIC_VIDEO_MISSING",
    "Video Pellicola segreto": "PELLICOLA_SECRET_VIDEO_MISSING",
}


# ---------------- helpers ----------------
def _nz(v) -> bool:
    return bool(v and str(v).strip())


def _has_any_content(doc: dict) -> bool:
    if _nz(doc.get("bio")) or _nz(doc.get("bio_segreta")) or _nz(doc.get("foto_card")):
        return True
    for pr in doc.get("media_pairs") or []:
        if _nz((pr.get("pubblico") or {}).get("url")) or _nz((pr.get("segreto") or {}).get("url")):
            return True
    return False


def validate_model(doc: dict) -> dict:
    """Return {ready, status, errors[], warnings[]}. Errors = blocking, warnings = non blocking."""
    rd = compute_readiness(doc)
    errors, warnings = [], []
    for c in rd["checklist"]:
        if c["required"] and not c["ok"]:
            errors.append({"code": REQUIRED_CODES.get(c["label"], "REQUIRED_MISSING"), "field": c["label"], "message": f"Manca: {c['label']}"})
        elif not c["required"] and not c["ok"]:
            warnings.append({"code": "OPTIONAL_MISSING", "field": c["label"], "message": f"Opzionale non compilato: {c['label']}"})
    of = doc.get("onlyfans_url") or ""
    if of and not OF_RX.match(of.strip()):
        errors.append({"code": "ONLYFANS_URL_INVALID", "field": "onlyfans_url", "message": "Il link OnlyFans non è nel formato https://onlyfans.com/<username>"})
    seo = doc.get("seo") or {}
    if not _nz(seo.get("title")):
        warnings.append({"code": "SEO_TITLE_MISSING", "field": "seo.title", "message": "SEO title mancante (fix automatico disponibile)"})
    if not _nz(seo.get("meta_description")):
        warnings.append({"code": "SEO_META_DESCRIPTION_MISSING", "field": "seo.meta_description", "message": "Meta description mancante (fix automatico disponibile)"})
    if not _nz(seo.get("og_image")):
        warnings.append({"code": "SEO_OG_IMAGE_MISSING", "field": "seo.og_image", "message": "Immagine OpenGraph mancante"})
    for i, pr in enumerate(doc.get("media_pairs") or []):
        for side in ("pubblico", "segreto"):
            m = pr.get(side) or {}
            if _nz(m.get("url")) and not _nz(m.get("alt")):
                warnings.append({"code": "ALT_MISSING", "field": f"media_pairs[{i}].{side}.alt", "message": f"ALT mancante su media {i + 1} ({side})"})
    cs = compute_content_status(doc)
    if cs["is_demo"]:
        warnings.append({"code": "DEMO_CONTENT", "field": "media", "message": f"Contenuti demo presenti: {', '.join(cs['demo_fields'][:4])}"})
    ready = len(errors) == 0
    return {"ready": ready, "status": workflow_status(doc, ready), "errors": errors, "warnings": warnings,
            "missing_required": rd["missing_required"], "missing_count": len(errors)}


def workflow_status(doc: dict, ready: Optional[bool] = None) -> str:
    if doc.get("is_deleted"):
        return "DELETED"
    stato = doc.get("stato")
    if stato == "archiviata":
        return "ARCHIVED"
    if ready is None:
        ready = compute_readiness(doc)["is_ready"] and not (doc.get("onlyfans_url") and not OF_RX.match(str(doc.get("onlyfans_url")).strip()))
    if stato == "pubblicata":
        return "PUBLISHED" if ready else "ERROR"
    if ready:
        return "READY"
    return "INCOMPLETE" if _has_any_content(doc) else "DRAFT"


def enrich(doc: dict) -> dict:
    out = serialize_doc(doc)
    v = validate_model(out)
    out["workflow_status"] = v["status"]
    out["validation"] = {"ready": v["ready"], "errors": v["errors"], "warnings": v["warnings"]}
    out["content_status"] = compute_content_status(out)
    return out


def summary(doc: dict) -> dict:
    v = validate_model(doc)
    return {
        "id": doc.get("id"), "nome": doc.get("nome"), "nome_artistico": doc.get("nome_artistico"), "slug": doc.get("slug"),
        "stato": doc.get("stato"), "workflow_status": v["status"], "ready": v["ready"],
        "errors_count": len(v["errors"]), "warnings_count": len(v["warnings"]),
        "categorie": doc.get("categorie", []), "badge": doc.get("badge"), "ordine": doc.get("ordine", 0),
        "foto_card": doc.get("foto_card", ""), "onlyfans_url": doc.get("onlyfans_url", ""),
        "updated_at": doc.get("updated_at"), "data_pubblicazione": doc.get("data_pubblicazione"),
        "pellicola_attiva": (doc.get("pellicola_home") or {}).get("attiva", False),
    }


async def unique_slug(base: str, exclude_id: Optional[str] = None) -> str:
    base = slugify(base)
    slug, i = base, 2
    while True:
        ex = await models_col.find_one({"slug": slug}, {"_id": 0, "id": 1})
        if not ex or ex.get("id") == exclude_id:
            return slug
        slug = f"{base}-{i}"
        i += 1


async def resolve_model(ref: str, include_deleted: bool = False) -> dict:
    """Find a model by id, slug or (artistic) name - case insensitive. Non-deleted matches always win."""
    if include_deleted:
        try:
            return await _resolve_model(ref, False)
        except HTTPException as e:
            if e.status_code != 404:
                raise
    return await _resolve_model(ref, include_deleted)


async def _resolve_model(ref: str, include_deleted: bool) -> dict:
    if not ref:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED", "message": "Riferimento modella mancante"})
    q_del = {} if include_deleted else {"is_deleted": {"$ne": True}}
    doc = await models_col.find_one({"id": ref, **q_del}, {"_id": 0})
    if not doc:
        doc = await models_col.find_one({"slug": slugify(ref), **q_del}, {"_id": 0})
    if not doc:
        rx = {"$regex": f"^{re.escape(ref.strip())}$", "$options": "i"}
        cands = await models_col.find({"$or": [{"nome": rx}, {"nome_artistico": rx}], **q_del}, {"_id": 0}).to_list(5)
        if len(cands) == 1:
            doc = cands[0]
        elif len(cands) > 1:
            raise HTTPException(status_code=409, detail={"code": "AMBIGUOUS_REFERENCE", "message": "Riferimento ambiguo: più modelle corrispondono", "candidates": [summary(c) for c in cands]})
    if not doc:
        rx = {"$regex": re.escape(ref.strip()), "$options": "i"}
        cands = await models_col.find({"$or": [{"nome": rx}, {"nome_artistico": rx}, {"slug": rx}], **q_del}, {"_id": 0}).to_list(5)
        if len(cands) == 1:
            doc = cands[0]
        elif len(cands) > 1:
            raise HTTPException(status_code=409, detail={"code": "AMBIGUOUS_REFERENCE", "message": "Riferimento ambiguo: più modelle corrispondono", "candidates": [summary(c) for c in cands]})
    if not doc:
        # token-prefix match: every word of the reference is a prefix of the corresponding word of the name
        # ("zeta test resolver 2" -> "Zeta Testuale Resolver 2"), unambiguous only
        toks = [t for t in re.split(r"[\s\-_]+", ref.strip().lower()) if t]
        if toks:
            first = {"$regex": f"^{re.escape(toks[0])}", "$options": "i"}
            pool = await models_col.find({"$or": [{"nome": first}, {"nome_artistico": first}], **q_del}, {"_id": 0}).to_list(50)
            def _tok_match(name: str) -> bool:
                nt = [t for t in re.split(r"[\s\-_]+", (name or "").lower()) if t]
                return len(nt) == len(toks) and all(n.startswith(t) for t, n in zip(toks, nt))
            cands = [c for c in pool if _tok_match(c.get("nome_artistico")) or _tok_match(c.get("nome"))]
            if len(cands) == 1:
                doc = cands[0]
            elif len(cands) > 1:
                raise HTTPException(status_code=409, detail={"code": "AMBIGUOUS_REFERENCE", "message": "Riferimento ambiguo: più modelle corrispondono", "candidates": [summary(c) for c in cands]})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Modella '{ref}' non trovata"})
    return doc


def deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            out[k] = deep_merge(base.get(k), v) if k in base else v
        return out
    return patch


ALLOWED_FIELDS = set(ModelIn.model_fields.keys())
PROTECTED_FIELDS = {"id", "created_at", "is_deleted", "deleted_at"}


def _normalize_new_doc(data: dict) -> dict:
    """Validate & normalize via ModelIn (keeps unknown keys out)."""
    m = ModelIn(**{k: v for k, v in data.items() if k in ALLOWED_FIELDS})
    return m.model_dump()


async def create_model(data: dict, principal: dict, request: Optional[Request], reason: str = "") -> dict:
    src = principal.get("source", "manual")
    body = _normalize_new_doc(data)
    if body.get("stato") not in ("bozza", "pubblicata", "disattivata"):
        body["stato"] = "bozza"
    body["slug"] = await unique_slug(body.get("slug") or body["nome"])
    if not _nz(body.get("nome_artistico")):
        body["nome_artistico"] = body["nome"]
    body["id"] = str(uuid.uuid4())
    body["created_at"] = body["updated_at"] = now_iso()
    body["is_deleted"] = False
    body["created_by"] = actor_of(principal)
    v = validate_model(body)
    if body["stato"] == "pubblicata":
        if not v["ready"]:
            body["stato"] = "bozza"
        else:
            body["data_pubblicazione"] = now_iso()
    if not (body.get("seo") or {}).get("title"):
        body.setdefault("seo", {})["title"] = f"{body['nome_artistico']} | LATO SEGRETO"
    await models_col.insert_one(body)
    rid = request_id_of(request)
    await record_version("model", body["id"], None, body, actor_of(principal), source=src, reason=reason or "Creazione modella", request_id=rid)
    await audit_log(actor_of(principal), "create", "model", body["id"], {"nome": body["nome"]}, rid, src)
    doc = await models_col.find_one({"id": body["id"]}, {"_id": 0})
    return enrich(doc)


def check_precondition(doc: dict, expected_updated_at: Optional[str]):
    """Optimistic concurrency: 409 CONFLICT if the record changed since the caller read it."""
    if expected_updated_at and doc.get("updated_at") and expected_updated_at != doc.get("updated_at"):
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "La modella è stata modificata da qualcun altro: rileggi lo stato e riprova",
                                                     "current_updated_at": doc.get("updated_at"), "expected_updated_at": expected_updated_at})


async def patch_model(doc: dict, changes: dict, principal: dict, request: Optional[Request], reason: str = "", source: Optional[str] = None,
                      dry_run: bool = False, expected_updated_at: Optional[str] = None) -> dict:
    src = source or principal.get("source", "manual")
    check_precondition(doc, expected_updated_at)
    changes = {k: v for k, v in (changes or {}).items() if k in ALLOWED_FIELDS and k not in PROTECTED_FIELDS}
    if not changes:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED", "message": "Nessun campo modificabile nella richiesta"})
    merged = deep_merge(doc, changes)
    # type-validate merged document
    try:
        normalized = ModelIn(**{k: v for k, v in merged.items() if k in ALLOWED_FIELDS}).model_dump()
    except Exception as e:  # pydantic validation error
        raise HTTPException(status_code=422, detail=f"Dati non validi: {e}")
    new_doc = {**doc, **normalized}
    if "slug" in changes and _nz(changes["slug"]):
        new_doc["slug"] = await unique_slug(changes["slug"], exclude_id=doc["id"])
    else:
        new_doc["slug"] = doc["slug"]
    # publication safety: a published model that becomes not-ready falls back to bozza (never a broken public page)
    auto = None
    if new_doc.get("stato") == "pubblicata":
        v = validate_model(new_doc)
        if not v["ready"]:
            if doc.get("stato") == "pubblicata":
                new_doc["stato"] = "bozza"
                auto = {"type": "auto_bozza", "errors": v["errors"]}
            else:
                raise HTTPException(status_code=400, detail={"message": "NON PUOI ANCORA PUBBLICARE", "errors": v["errors"]})
        elif not doc.get("data_pubblicazione"):
            new_doc["data_pubblicazione"] = now_iso()
    if dry_run:
        from v1_versioning import diff_fields
        changed = diff_fields(serialize_doc(doc), serialize_doc(new_doc))
        out = enrich(new_doc)
        return {"dry_run": True, "id": doc["id"], "slug": new_doc["slug"], "changed_fields": changed,
                "before": {k: doc.get(k) for k in changed}, "proposed_after": {k: new_doc.get(k) for k in changed},
                "workflow_status_before": workflow_status(doc), "workflow_status_after": out["workflow_status"], "validation": out["validation"],
                "auto": auto, "etag": doc.get("updated_at")}
    new_doc["updated_at"] = now_iso()
    await models_col.replace_one({"id": doc["id"]}, new_doc)
    rid = request_id_of(request)
    ver = await record_version("model", doc["id"], doc, new_doc, actor_of(principal), source=src, reason=reason or "Aggiornamento modella", request_id=rid)
    await audit_log(actor_of(principal), "update", "model", doc["id"], {"changed": ver.get("changed_fields", []), "auto": auto}, rid, src)
    # slug change -> safe redirect (+ sitemap re-submit scheduled)
    if new_doc["slug"] != doc["slug"]:
        from v1_seo import ensure_redirect
        await ensure_redirect(f"/modelle/{doc['slug']}", f"/modelle/{new_doc['slug']}", actor_of(principal), "slug_change")
        from google_search.service import mark_sitemap_dirty
        await mark_sitemap_dirty(f"slug change {doc['slug']} -> {new_doc['slug']}")
    elif new_doc.get("stato") == "pubblicata" and ((new_doc.get("seo") or {}).get("indexable") != (doc.get("seo") or {}).get("indexable") or (new_doc.get("seo") or {}).get("canonical") != (doc.get("seo") or {}).get("canonical")):
        from google_search.service import mark_sitemap_dirty
        await mark_sitemap_dirty(f"seo indexable/canonical change {doc['slug']}")
    out = enrich(new_doc)
    out["version_id"] = ver.get("id")
    out["changed_fields"] = ver.get("changed_fields", [])
    out["etag"] = new_doc["updated_at"]
    if auto:
        out["_auto"] = auto
    return out


async def transition(doc: dict, action: str, principal: dict, request: Optional[Request], reason: str = "", force: bool = False, dry_run: bool = False) -> dict:
    """publish | unpublish | archive | restore. `force` NEVER bypasses readiness."""
    src = principal.get("source", "manual")
    new_doc = copy.deepcopy(doc)
    if action == "publish":
        v = validate_model(doc)
        if not v["ready"]:
            raise HTTPException(status_code=400, detail={"code": "PUBLICATION_BLOCKED", "message": "NON PUOI ANCORA PUBBLICARE", "errors": v["errors"], "warnings": v["warnings"], "missing": [e["field"] for e in v["errors"]]})
        new_doc["stato"] = "pubblicata"
        if not new_doc.get("data_pubblicazione"):
            new_doc["data_pubblicazione"] = now_iso()
    elif action == "unpublish":
        new_doc["stato"] = "bozza"
    elif action == "archive":
        new_doc["stato_precedente"] = doc.get("stato")
        new_doc["stato"] = "archiviata"
        new_doc["archived_at"] = now_iso()
    elif action == "restore":
        prev = doc.get("stato_precedente") or "bozza"
        if doc.get("is_deleted"):
            new_doc["is_deleted"] = False
            new_doc.pop("deleted_at", None)
            new_doc["stato"] = doc.get("stato") if doc.get("stato") != "archiviata" else "bozza"
        else:
            new_doc["stato"] = "bozza" if prev == "archiviata" else prev
        if new_doc["stato"] == "pubblicata" and not validate_model(new_doc)["ready"]:
            new_doc["stato"] = "bozza"
        new_doc.pop("archived_at", None)
        new_doc.pop("stato_precedente", None)
    else:
        raise HTTPException(status_code=400, detail="Azione non valida")
    if dry_run:
        return {"dry_run": True, "id": doc["id"], "slug": doc["slug"], "nome_artistico": doc.get("nome_artistico"), "action": action,
                "before": {"stato": doc.get("stato"), "workflow_status": workflow_status(doc)}, "proposed_after": {"stato": new_doc["stato"], "workflow_status": workflow_status(new_doc)},
                "changed_fields": ["stato"], "validation": validate_model(new_doc), "workflow_status": workflow_status(new_doc), "public_url": f"/modelle/{doc['slug']}" if new_doc["stato"] == "pubblicata" else None}
    new_doc["updated_at"] = now_iso()
    await models_col.replace_one({"id": doc["id"]}, new_doc)
    if new_doc.get("stato") != doc.get("stato") and "pubblicata" in (new_doc.get("stato"), doc.get("stato")):
        from google_search.service import mark_sitemap_dirty
        await mark_sitemap_dirty(f"model {doc['slug']} {doc.get('stato')} -> {new_doc.get('stato')}")
    rid = request_id_of(request)
    ver = await record_version("model", doc["id"], doc, new_doc, actor_of(principal), source=src, reason=reason or action, request_id=rid)
    await audit_log(actor_of(principal), action, "model", doc["id"], {}, rid, src)
    if action == "publish":
        from v1_config import emit_event
        await emit_event("model.published", {"model_id": doc["id"], "slug": new_doc["slug"], "actor": actor_of(principal)})
    out = enrich(new_doc)
    out["version_id"] = ver.get("id")
    return out


# ---------------- Pydantic bodies ----------------
class ModelCreateBody(BaseModel):
    model_config = ConfigDict(extra='allow')
    nome: str
    reason: Optional[str] = None


class ActionBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    reason: Optional[str] = ""
    force: bool = False


class FeatureBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    position: Optional[int] = 0        # 0 = first card of the Home grid
    badge: Optional[str] = None        # e.g. "IN TENDENZA", "NUOVA", "SCELTA DEL GIORNO"
    pellicola: Optional[bool] = None   # feature also in "IN MOVIMENTO"
    pellicola_priorita: Optional[int] = None
    reason: Optional[str] = ""


# ---------------- ROUTES ----------------
@models_router.get("")
async def list_models(
    status: Optional[str] = Query(None, description="DRAFT|INCOMPLETE|READY|PUBLISHED|ARCHIVED|ERROR"),
    stato: Optional[str] = None, categoria: Optional[str] = None, q: Optional[str] = None,
    include_deleted: bool = False, limit: int = 100, skip: int = 0, full: bool = False,
    principal=Depends(require("models:read")),
):
    query: Dict[str, Any] = {}
    if not include_deleted:
        query["is_deleted"] = {"$ne": True}
    if stato:
        query["stato"] = stato
    if categoria:
        query["categorie"] = categoria
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"nome": rx}, {"nome_artistico": rx}, {"slug": rx}, {"tag": rx}]
    docs = await models_col.find(query, {"_id": 0}).sort("ordine", 1).to_list(1000)
    items = [enrich(d) if full else summary(d) for d in docs]
    if status:
        items = [i for i in items if i["workflow_status"] == status.upper()]
    counts: Dict[str, int] = {}
    for i in items:
        counts[i["workflow_status"]] = counts.get(i["workflow_status"], 0) + 1
    total = len(items)
    return {"items": items[skip:skip + limit], "total": total, "counts": counts}


@models_router.get("/{model_id}")
async def get_model(model_id: str, principal=Depends(require("models:read"))):
    doc = await resolve_model(model_id, include_deleted=True)
    return enrich(doc)


@models_router.post("", status_code=201)
async def create(body: ModelCreateBody, request: Request, principal=Depends(require("models:write"))):
    data = body.model_dump()
    reason = data.pop("reason", None) or ""
    return await create_model(data, principal, request, reason)


@models_router.patch("/{model_id}")
async def patch(model_id: str, body: Dict[str, Any], request: Request, principal=Depends(require("models:write"))):
    doc = await resolve_model(model_id)
    reason = (body or {}).pop("reason", "") if isinstance(body, dict) else ""
    if isinstance(body, dict) and "stato" in body and body["stato"] == "pubblicata" and doc.get("stato") != "pubblicata":
        # publishing through PATCH requires the publish scope
        if "models:publish" not in principal.get("scopes", []) and "*" not in principal.get("scopes", []):
            raise HTTPException(status_code=403, detail="Serve lo scope models:publish per pubblicare")
    return await patch_model(doc, body, principal, request, reason)


@models_router.delete("/{model_id}")
async def soft_delete(model_id: str, request: Request, principal=Depends(require("models:delete"))):
    doc = await resolve_model(model_id)
    new_doc = {**doc, "is_deleted": True, "deleted_at": now_iso(), "updated_at": now_iso(),
               "stato_precedente": doc.get("stato"), "stato": "archiviata"}
    await models_col.replace_one({"id": doc["id"]}, new_doc)
    rid = request_id_of(request)
    ver = await record_version("model", doc["id"], doc, new_doc, actor_of(principal), source=principal.get("source", "manual"), reason="Soft delete", request_id=rid)
    await audit_log(actor_of(principal), "soft_delete", "model", doc["id"], {}, rid)
    return {"ok": True, "id": doc["id"], "soft_deleted": True, "version_id": ver.get("id"), "restore_with": f"POST /api/v1/models/{doc['id']}/restore"}


@models_router.post("/{model_id}/validate")
async def validate(model_id: str, principal=Depends(require("models:read"))):
    doc = await resolve_model(model_id, include_deleted=True)
    v = validate_model(doc)
    return {"id": doc["id"], "slug": doc["slug"], "nome": doc.get("nome_artistico") or doc.get("nome"), **v}


@models_router.post("/{model_id}/publish")
async def publish(model_id: str, request: Request, body: ActionBody = ActionBody(), principal=Depends(require("models:publish"))):
    doc = await resolve_model(model_id)
    return await transition(doc, "publish", principal, request, body.reason or "", body.force)


@models_router.post("/{model_id}/unpublish")
async def unpublish(model_id: str, request: Request, body: ActionBody = ActionBody(), principal=Depends(require("models:publish"))):
    doc = await resolve_model(model_id)
    return await transition(doc, "unpublish", principal, request, body.reason or "")


@models_router.post("/{model_id}/archive")
async def archive(model_id: str, request: Request, body: ActionBody = ActionBody(), principal=Depends(require("models:write"))):
    doc = await resolve_model(model_id)
    return await transition(doc, "archive", principal, request, body.reason or "")


@models_router.post("/{model_id}/restore")
async def restore(model_id: str, request: Request, body: ActionBody = ActionBody(), principal=Depends(require("models:write"))):
    doc = await resolve_model(model_id, include_deleted=True)
    return await transition(doc, "restore", principal, request, body.reason or "")


@models_router.post("/{model_id}/duplicate", status_code=201)
async def duplicate(model_id: str, request: Request, body: ActionBody = ActionBody(), principal=Depends(require("models:write"))):
    doc = await resolve_model(model_id, include_deleted=True)
    data = {k: v for k, v in doc.items() if k in ALLOWED_FIELDS}
    data["nome"] = f"{doc.get('nome')} (copia)"
    data["nome_artistico"] = f"{doc.get('nome_artistico') or doc.get('nome')} (copia)"
    data["slug"] = f"{doc.get('slug')}-copia"
    data["stato"] = "bozza"
    data["data_pubblicazione"] = None
    data["ordine"] = int(doc.get("ordine", 0)) + 1
    data["media_pairs"] = [{**pr, "id": str(uuid.uuid4())} for pr in (doc.get("media_pairs") or [])]
    out = await create_model(data, principal, request, body.reason or f"Duplicato da {doc.get('slug')}")
    out["duplicated_from"] = doc["id"]
    return out


@models_router.post("/{model_id}/feature")
async def feature(model_id: str, body: FeatureBody, request: Request, principal=Depends(require("models:write"))):
    """'Metti questa modella in homepage': move to the top of the grid, set a badge, optionally feature in IN MOVIMENTO."""
    doc = await resolve_model(model_id)
    changes: Dict[str, Any] = {}
    pos = body.position if body.position is not None else 0
    if body.badge is not None:
        changes["badge"] = body.badge or None
    if body.pellicola is not None or body.pellicola_priorita is not None:
        ph = dict(doc.get("pellicola_home") or {})
        if body.pellicola is not None:
            ph["attiva"] = bool(body.pellicola)
        if body.pellicola_priorita is not None:
            ph["priorita"] = max(1, min(10, int(body.pellicola_priorita)))
        changes["pellicola_home"] = ph
    # reorder: shift others
    others = await models_col.find({"id": {"$ne": doc["id"]}, "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "ordine": 1}).sort("ordine", 1).to_list(1000)
    order_ids = [o["id"] for o in others]
    pos = max(0, min(pos, len(order_ids)))
    order_ids.insert(pos, doc["id"])
    for idx, mid in enumerate(order_ids):
        await models_col.update_one({"id": mid}, {"$set": {"ordine": idx}})
    changes["ordine"] = pos
    doc = await models_col.find_one({"id": doc["id"]}, {"_id": 0})
    out = await patch_model(doc, changes, principal, request, body.reason or "Messa in evidenza in Home")
    out["home_position"] = pos
    out["published"] = doc.get("stato") == "pubblicata"
    if doc.get("stato") != "pubblicata":
        out["note"] = "La modella non è pubblicata: apparirà in Home solo dopo la pubblicazione."
    return out


@models_router.get("/{model_id}/versions")
async def model_versions(model_id: str, limit: int = 30, principal=Depends(require("versions:read"))):
    from v1_versioning import list_versions
    doc = await resolve_model(model_id, include_deleted=True)
    return await list_versions("model", doc["id"], limit)


@models_router.get("/meta/categories")
async def categories_meta(principal=Depends(require("models:read"))):
    docs = await categories_col.find({}, {"_id": 0, "nome": 1, "slug": 1, "stato": 1}).sort("ordine", 1).to_list(200)
    return {"items": docs}
