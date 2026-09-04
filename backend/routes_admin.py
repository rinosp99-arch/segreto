import uuid
from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File

from typing import Optional

from database import (
    models_col, categories_col, articles_col, settings_col, admins_col, audit_col,
    files_col, now_iso, serialize_doc,
)
from auth import (
    get_current_admin, verify_password, create_token, check_rate_limit,
    reset_rate_limit, hash_password,
)
from schemas import ModelIn, CategoryIn, ArticleIn, SettingsIn, LoginIn
from sanitize import sanitize_html, slugify
from storage import put_object, APP_NAME
from content_status import compute_content_status, full_status, compute_readiness


def _assert_publishable(data):
    """Raise 400 with structured detail if REQUIRED fields are missing for publication."""
    rd = compute_readiness(data)
    if not rd["is_ready"]:
        raise HTTPException(status_code=400, detail={
            "message": "NON PUOI ANCORA PUBBLICARE",
            "missing_required": rd["missing_required"],
            "missing_count": rd["missing_count"],
        })

admin_router = APIRouter(prefix="/api/admin")

ALLOWED_IMG = {"image/jpeg", "image/png", "image/webp", "image/avif", "image/gif"}
ALLOWED_VID = {"video/mp4", "video/webm", "video/quicktime"}
MAX_BYTES = 60 * 1024 * 1024  # 60MB
EXT_MAP = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/avif": "avif", "image/gif": "gif", "video/mp4": "mp4",
    "video/webm": "webm", "video/quicktime": "mov",
}


async def audit(actor, action, entity, entity_id, meta=None):
    await audit_col.insert_one({
        "id": str(uuid.uuid4()), "actor": actor, "action": action,
        "entity": entity, "entity_id": entity_id, "meta": meta or {},
        "timestamp": now_iso(),
    })


# ---------------- AUTH ----------------
@admin_router.post("/login")
async def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip)
    admin = await admins_col.find_one({"email": body.email.lower().strip()})
    if not admin or not verify_password(body.password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    reset_rate_limit(ip)
    token = create_token(admin["id"], admin["email"], admin.get("ruolo", "amministratore"))
    return {"token": token, "email": admin["email"], "ruolo": admin.get("ruolo", "amministratore")}


@admin_router.get("/me")
async def me(admin=Depends(get_current_admin)):
    return {"email": admin.get("email"), "ruolo": admin.get("ruolo")}


@admin_router.post("/change-password")
async def change_password(body: dict, admin=Depends(get_current_admin)):
    new_pw = (body or {}).get("password", "")
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="La password deve avere almeno 8 caratteri")
    await admins_col.update_one({"id": admin["sub"]}, {"$set": {"password_hash": hash_password(new_pw)}})
    await audit(admin["email"], "change_password", "admin", admin["sub"])
    return {"ok": True}


# ---------------- UPLOAD (Emergent object storage) ----------------
@admin_router.post("/upload")
async def upload_media(file: UploadFile = File(...), admin=Depends(get_current_admin)):
    ctype = file.content_type or ""
    if ctype not in ALLOWED_IMG and ctype not in ALLOWED_VID:
        raise HTTPException(status_code=400, detail=f"Tipo file non consentito: {ctype}")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File troppo grande (max 60MB)")
    ext = EXT_MAP.get(ctype, "bin")
    path = f"{APP_NAME}/uploads/{uuid.uuid4().hex}.{ext}"
    try:
        result = put_object(path, data, ctype)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Errore di archiviazione: {e}")
    stored_path = result.get("path", path)
    tipo = "video" if ctype in ALLOWED_VID else "image"
    await files_col.insert_one({
        "id": str(uuid.uuid4()),
        "storage_path": stored_path,
        "original_filename": file.filename,
        "content_type": ctype,
        "size": result.get("size", len(data)),
        "tipo": tipo,
        "is_deleted": False,
        "created_at": now_iso(),
    })
    return {"url": f"/api/uploads/{stored_path}", "tipo": tipo, "size": result.get("size", len(data))}


# ---------------- MODELS CRUD ----------------
@admin_router.get("/models")
async def admin_list_models(stato: Optional[str] = None, admin=Depends(get_current_admin)):
    query = {}
    if stato:
        query["stato"] = stato
    docs = await models_col.find(query, {"_id": 0}).sort("ordine", 1).to_list(500)
    items = serialize_doc(docs)
    counts = {"tutte": len(items), "demo": 0, "reali": 0, "incomplete": 0, "pronte": 0}
    for it in items:
        fs = full_status(it)
        it["content_status"] = fs["content_status"]
        it["readiness"] = {"is_ready": fs["readiness"]["is_ready"], "missing_count": fs["readiness"]["missing_count"], "missing_required": fs["readiness"]["missing_required"]}
        it["stato_operativo"] = fs["stato_operativo"]
        if fs["content_status"]["is_demo"]:
            counts["demo"] += 1
        else:
            counts["reali"] += 1
        if fs["stato_operativo"] == "incompleta":
            counts["incomplete"] += 1
        if fs["readiness"]["is_ready"] and it.get("stato") != "pubblicata":
            counts["pronte"] += 1
    return {"items": items, "counts": counts, "demo_totale": counts["demo"], "totale": counts["tutte"]}


@admin_router.get("/models/{model_id}")
async def admin_get_model(model_id: str, admin=Depends(get_current_admin)):
    doc = await models_col.find_one({"id": model_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Modella non trovata")
    out = serialize_doc(doc)
    out.update(full_status(out))
    return out


async def _unique_slug(base, exclude_id=None):
    base = slugify(base)
    slug = base
    i = 2
    while True:
        existing = await models_col.find_one({"slug": slug})
        if not existing or existing.get("id") == exclude_id:
            return slug
        slug = f"{base}-{i}"
        i += 1


@admin_router.post("/models")
async def admin_create_model(body: ModelIn, admin=Depends(get_current_admin)):
    data = body.model_dump()
    if data["stato"] == "pubblicata":
        _assert_publishable(data)
    data["slug"] = await _unique_slug(data.get("slug") or data["nome"])
    data["id"] = str(uuid.uuid4())
    data["created_at"] = now_iso()
    data["updated_at"] = now_iso()
    if data["stato"] == "pubblicata" and not data.get("data_pubblicazione"):
        data["data_pubblicazione"] = now_iso()
    await models_col.insert_one(data)
    await audit(admin["email"], "create", "model", data["id"], {"nome": data["nome"]})
    return serialize_doc({k: v for k, v in data.items() if k != "_id"})


@admin_router.put("/models/{model_id}")
async def admin_update_model(model_id: str, body: ModelIn, admin=Depends(get_current_admin)):
    existing = await models_col.find_one({"id": model_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Modella non trovata")
    data = body.model_dump()
    if data.get("slug"):
        data["slug"] = await _unique_slug(data["slug"], exclude_id=model_id)
    else:
        data["slug"] = existing["slug"]
    was_published = existing.get("stato") == "pubblicata"
    if data["stato"] == "pubblicata":
        if not was_published:
            # transition draft -> published: hard block if incomplete
            _assert_publishable(data)
    data["updated_at"] = now_iso()
    if data["stato"] == "pubblicata" and not existing.get("data_pubblicazione"):
        data["data_pubblicazione"] = now_iso()

    # --- AUTO-BOZZA / AUTO-PELLICOLA safety (only for already-published models being edited) ---
    auto = None
    if was_published and data["stato"] == "pubblicata":
        rd = compute_readiness(data)
        if not rd["profile_ready"]:
            data["stato"] = "bozza"
            auto = {"type": "bozza", "missing": rd["profile_missing"]}
        elif (data.get("pellicola_home") or {}).get("attiva") and not rd["pellicola_ready"]:
            data["pellicola_home"]["attiva"] = False
            auto = {"type": "pellicola_off", "missing": rd["pellicola_missing"]}

    await models_col.update_one({"id": model_id}, {"$set": data})
    if auto and auto["type"] == "bozza":
        await audit(admin["email"], "auto_bozza", "model", model_id, {"missing": auto["missing"]})
    elif auto and auto["type"] == "pellicola_off":
        await audit(admin["email"], "auto_pellicola_off", "model", model_id, {"missing": auto["missing"]})
    else:
        await audit(admin["email"], "update", "model", model_id)
    doc = await models_col.find_one({"id": model_id}, {"_id": 0})
    out = serialize_doc(doc)
    out.update(full_status(out))
    if auto:
        out["_auto"] = auto
    return out


@admin_router.patch("/models/{model_id}/stato")
async def admin_set_status(model_id: str, body: dict, admin=Depends(get_current_admin)):
    stato = (body or {}).get("stato")
    if stato not in ("bozza", "pubblicata", "disattivata"):
        raise HTTPException(status_code=400, detail="Stato non valido")
    existing = await models_col.find_one({"id": model_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Modella non trovata")
    if stato == "pubblicata":
        _assert_publishable(existing)
    upd = {"stato": stato, "updated_at": now_iso()}
    if stato == "pubblicata" and not existing.get("data_pubblicazione"):
        upd["data_pubblicazione"] = now_iso()
    await models_col.update_one({"id": model_id}, {"$set": upd})
    await audit(admin["email"], f"stato:{stato}", "model", model_id)
    return {"ok": True, "stato": stato}


@admin_router.delete("/models/{model_id}")
async def admin_delete_model(model_id: str, admin=Depends(get_current_admin)):
    res = await models_col.delete_one({"id": model_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Modella non trovata")
    await audit(admin["email"], "delete", "model", model_id)
    return {"ok": True}


@admin_router.post("/models/reorder")
async def admin_reorder(body: dict, admin=Depends(get_current_admin)):
    order = (body or {}).get("order", [])  # list of ids in new order
    for idx, mid in enumerate(order):
        await models_col.update_one({"id": mid}, {"$set": {"ordine": idx}})
    await audit(admin["email"], "reorder", "model", "-")
    return {"ok": True}


@admin_router.post("/models/{model_id}/copy-config")
async def admin_copy_config(model_id: str, body: dict, admin=Depends(get_current_admin)):
    """Copy ONLY configuration (no personal media/text) from a source model."""
    source_id = (body or {}).get("source_id")
    src = await models_col.find_one({"id": source_id}, {"_id": 0})
    dst = await models_col.find_one({"id": model_id}, {"_id": 0})
    if not src or not dst:
        raise HTTPException(status_code=404, detail="Modella non trovata")

    upd = {}
    # secret theme (full config, no personal media)
    upd["tema"] = src.get("tema", {})
    # regia (fumo/luci/glow/movimento + suoni)
    upd["regia"] = src.get("regia", {})
    # timed CTA (timer/copy/style)
    upd["cta_temporizzata"] = src.get("cta_temporizzata", {})
    upd["cta_testo"] = src.get("cta_testo", dst.get("cta_testo", "CONTINUA CON ME"))
    # 35s message: only timing/copy/CTA, NOT personal media (foto/video)
    src_msg = src.get("messaggio_35s", {}) or {}
    dst_msg = dst.get("messaggio_35s", {}) or {}
    upd["messaggio_35s"] = {
        **dst_msg,
        "attivo": src_msg.get("attivo", dst_msg.get("attivo", True)),
        "timer": src_msg.get("timer", dst_msg.get("timer", 35)),
        "cta_testo": src_msg.get("cta_testo", dst_msg.get("cta_testo", "CONTINUA CON ME")),
    }
    # pellicola settings: only flags (mostra/priorita/ordine), NOT media urls
    src_ph = src.get("pellicola_home", {}) or {}
    dst_ph = dst.get("pellicola_home", {}) or {}
    upd["pellicola_home"] = {
        **dst_ph,
        "attiva": src_ph.get("attiva", dst_ph.get("attiva", True)),
        "priorita": src_ph.get("priorita", dst_ph.get("priorita", 5)),
    }
    upd["updated_at"] = now_iso()
    await models_col.update_one({"id": model_id}, {"$set": upd})
    await audit(admin["email"], "copy_config", "model", model_id, {"from": source_id})
    doc = await models_col.find_one({"id": model_id}, {"_id": 0})
    out = serialize_doc(doc)
    out.update(full_status(out))
    return out


def _config_patch(src, dst, sections):
    """Build a $set patch copying ONLY selected config sections (never personal content)."""
    upd = {}
    if sections.get("regista"):
        upd["tema"] = src.get("tema", {})
        upd["regia"] = src.get("regia", {})
    if sections.get("conversione"):
        upd["cta_temporizzata"] = src.get("cta_temporizzata", {})
        upd["cta_testo"] = src.get("cta_testo", dst.get("cta_testo", "CONTINUA CON ME"))
        src_msg = src.get("messaggio_35s", {}) or {}
        dst_msg = dst.get("messaggio_35s", {}) or {}
        upd["messaggio_35s"] = {
            **dst_msg,
            "attivo": src_msg.get("attivo", dst_msg.get("attivo", True)),
            "timer": src_msg.get("timer", dst_msg.get("timer", 35)),
            "cta_testo": src_msg.get("cta_testo", dst_msg.get("cta_testo", "CONTINUA CON ME")),
        }
    if sections.get("pellicola"):
        src_ph = src.get("pellicola_home", {}) or {}
        dst_ph = dst.get("pellicola_home", {}) or {}
        upd["pellicola_home"] = {
            **dst_ph,
            "attiva": src_ph.get("attiva", dst_ph.get("attiva", True)),
            "priorita": src_ph.get("priorita", dst_ph.get("priorita", 5)),
        }
    return upd


@admin_router.post("/models/copy-config-bulk")
async def admin_copy_config_bulk(body: dict, admin=Depends(get_current_admin)):
    """Apply selected CONFIG sections from a source model to many targets.
    Never touches personal content (media/testi/onlyfans/social/seo/analytics)."""
    source_id = (body or {}).get("source_id")
    target_ids = (body or {}).get("target_ids", []) or []
    sections = (body or {}).get("sections", {}) or {}
    src = await models_col.find_one({"id": source_id}, {"_id": 0})
    if not src:
        raise HTTPException(status_code=404, detail="Modella sorgente non trovata")
    if not any(sections.get(s) for s in ("regista", "conversione", "pellicola")):
        raise HTTPException(status_code=400, detail="Seleziona almeno una sezione da copiare")
    updated = []
    for tid in target_ids:
        if tid == source_id:
            continue
        dst = await models_col.find_one({"id": tid}, {"_id": 0})
        if not dst:
            continue
        upd = _config_patch(src, dst, sections)
        upd["updated_at"] = now_iso()
        await models_col.update_one({"id": tid}, {"$set": upd})
        updated.append(tid)
    copied_sections = [s for s in ("regista", "conversione", "pellicola") if sections.get(s)]
    await audit(admin["email"], "copy_config_bulk", "model", source_id, {
        "targets": updated, "count": len(updated), "sections": copied_sections,
    })
    return {"updated": len(updated), "sections": copied_sections}


# ---------------- CATEGORIES CRUD ----------------
@admin_router.get("/categories")
async def admin_list_categories(admin=Depends(get_current_admin)):
    docs = await categories_col.find({}, {"_id": 0}).sort("ordine", 1).to_list(200)
    return {"items": docs}


@admin_router.post("/categories")
async def admin_create_category(body: CategoryIn, admin=Depends(get_current_admin)):
    data = body.model_dump()
    data["slug"] = slugify(data.get("slug") or data["nome"])
    if await categories_col.find_one({"slug": data["slug"]}):
        raise HTTPException(status_code=400, detail="Slug categoria gi\u00e0 esistente")
    data["id"] = str(uuid.uuid4())
    data["created_at"] = now_iso()
    await categories_col.insert_one(data)
    await audit(admin["email"], "create", "category", data["id"])
    return serialize_doc({k: v for k, v in data.items() if k != "_id"})


@admin_router.put("/categories/{cat_id}")
async def admin_update_category(cat_id: str, body: CategoryIn, admin=Depends(get_current_admin)):
    existing = await categories_col.find_one({"id": cat_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria non trovata")
    data = body.model_dump()
    data["slug"] = slugify(data.get("slug") or data["nome"])
    await categories_col.update_one({"id": cat_id}, {"$set": data})
    await audit(admin["email"], "update", "category", cat_id)
    doc = await categories_col.find_one({"id": cat_id}, {"_id": 0})
    return serialize_doc(doc)


@admin_router.delete("/categories/{cat_id}")
async def admin_delete_category(cat_id: str, admin=Depends(get_current_admin)):
    res = await categories_col.delete_one({"id": cat_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Categoria non trovata")
    await audit(admin["email"], "delete", "category", cat_id)
    return {"ok": True}


# ---------------- ARTICLES CRUD ----------------
@admin_router.get("/articles")
async def admin_list_articles(admin=Depends(get_current_admin)):
    docs = await articles_col.find({}, {"_id": 0}).sort("created_at", -1).to_list(300)
    return {"items": serialize_doc(docs)}


@admin_router.get("/articles/{article_id}")
async def admin_get_article(article_id: str, admin=Depends(get_current_admin)):
    doc = await articles_col.find_one({"id": article_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Articolo non trovato")
    return serialize_doc(doc)


@admin_router.post("/articles")
async def admin_create_article(body: ArticleIn, admin=Depends(get_current_admin)):
    data = body.model_dump()
    data["slug"] = slugify(data.get("slug") or data["titolo"])
    if await articles_col.find_one({"slug": data["slug"]}):
        data["slug"] = f"{data['slug']}-{uuid.uuid4().hex[:6]}"
    data["contenuto"] = sanitize_html(data.get("contenuto", ""))
    data["id"] = str(uuid.uuid4())
    data["created_at"] = now_iso()
    data["data_aggiornamento"] = now_iso()
    if data["stato"] == "pubblicato" and not data.get("data_pubblicazione"):
        data["data_pubblicazione"] = now_iso()
    data["fonte"] = "manuale"
    await articles_col.insert_one(data)
    await audit(admin["email"], "create", "article", data["id"])
    return serialize_doc({k: v for k, v in data.items() if k != "_id"})


@admin_router.put("/articles/{article_id}")
async def admin_update_article(article_id: str, body: ArticleIn, admin=Depends(get_current_admin)):
    existing = await articles_col.find_one({"id": article_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Articolo non trovato")
    data = body.model_dump()
    data["slug"] = slugify(data.get("slug") or data["titolo"])
    data["contenuto"] = sanitize_html(data.get("contenuto", ""))
    data["data_aggiornamento"] = now_iso()
    if data["stato"] == "pubblicato" and not existing.get("data_pubblicazione"):
        data["data_pubblicazione"] = now_iso()
    await articles_col.update_one({"id": article_id}, {"$set": data})
    await audit(admin["email"], "update", "article", article_id)
    doc = await articles_col.find_one({"id": article_id}, {"_id": 0})
    return serialize_doc(doc)


@admin_router.delete("/articles/{article_id}")
async def admin_delete_article(article_id: str, admin=Depends(get_current_admin)):
    res = await articles_col.delete_one({"id": article_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Articolo non trovato")
    await audit(admin["email"], "delete", "article", article_id)
    return {"ok": True}


# ---------------- SETTINGS ----------------
@admin_router.get("/settings")
async def admin_get_settings(admin=Depends(get_current_admin)):
    s = await settings_col.find_one({"id": "global"}, {"_id": 0})
    return s or {}


@admin_router.put("/settings")
async def admin_update_settings(body: SettingsIn, admin=Depends(get_current_admin)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    upd["updated_at"] = now_iso()
    await settings_col.update_one({"id": "global"}, {"$set": upd}, upsert=True)
    await audit(admin["email"], "update", "settings", "global")
    s = await settings_col.find_one({"id": "global"}, {"_id": 0})
    return s


@admin_router.get("/audit")
async def admin_audit(admin=Depends(get_current_admin), limit: int = 100):
    docs = await audit_col.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return {"items": docs}
