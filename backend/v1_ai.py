"""SUPER API v1 - AI / CHATGPT-FRIENDLY ENDPOINTS.

Flat request bodies, natural references (id | slug | nome), simple structured responses:
{ ok, action, request_id, summary (italiano), data, warnings, next_steps }
Every AI action is logged in `ai_actions` and versioned like any other change.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict

from database import (
    ai_actions_col, models_col, alerts_col, jobs_col, seo_issues_col, versions_col, events_col, health_col, config_col, now_iso, serialize_doc,
)
from v1_security import require, actor_of, request_id_of
from v1_models import resolve_model, create_model, patch_model, transition, validate_model, summary as model_summary, ALLOWED_FIELDS
from v1_tracking import build_match, funnel_for, model_kpis, counts_by, _ev_match

ai_router = APIRouter(prefix="/api/v1/ai", tags=["AI / ChatGPT"])


def _ai_principal(principal: dict) -> dict:
    return {**principal, "source": "ai"}


async def log_action(principal: dict, request: Request, action: str, inp: dict, result_summary: str, ok: bool = True, data: Optional[dict] = None):
    redacted = {k: ("<base64>" if k == "base64_data" else v) for k, v in (inp or {}).items()}
    await ai_actions_col.insert_one({"id": str(uuid.uuid4()), "request_id": request_id_of(request), "actor": actor_of(principal), "principal_type": principal.get("type"),
                                     "action": action, "input": redacted, "ok": ok, "summary": result_summary, "data_keys": list((data or {}).keys()), "timestamp": now_iso()})
    try:
        from v1_config import emit_event
        await emit_event("ai.action", {"action": action, "ok": ok, "summary": result_summary, "actor": actor_of(principal)})
    except Exception:
        pass


def envelope(action: str, request: Request, summary: str, data: Any = None, warnings: Optional[List[str]] = None, next_steps: Optional[List[str]] = None, ok: bool = True) -> dict:
    return {"ok": ok, "action": action, "request_id": request_id_of(request), "summary": summary, "data": data, "warnings": warnings or [], "next_steps": next_steps or []}


def _steps_for(v: dict, model: dict) -> List[str]:
    steps = []
    codes = {e["code"] for e in v["errors"]}
    ref = model.get("slug") or model.get("id")
    if {"PUBLIC_PHOTOS_LT_3", "SECRET_PHOTOS_LT_3", "PUBLIC_VIDEO_MISSING", "SECRET_VIDEO_MISSING", "CARD_PHOTO_MISSING"} & codes:
        steps.append(f"Carica media: POST /api/v1/ai/media/upload {{model:'{ref}', slot:'pair'|'foto_card', side:'pubblico'|'segreto', url:...}}")
    if {"CLAIM_MISSING", "PUBLIC_BIO_MISSING", "SECRET_BIO_MISSING"} & codes:
        steps.append(f"Completa i testi: POST /api/v1/ai/models/update {{model:'{ref}', changes:{{frase, bio, bio_segreta}}}}")
    if "ONLYFANS_URL_MISSING" in codes or "ONLYFANS_URL_INVALID" in codes:
        steps.append(f"Imposta il link: POST /api/v1/ai/models/update {{model:'{ref}', changes:{{onlyfans_url:'https://onlyfans.com/...'}}}}")
    if "AGE_CONFIRMATION_MISSING" in codes:
        steps.append(f"Conferma maggiore età: changes:{{conferma_maggiorenne:true}}")
    if v["ready"] and model.get("stato") != "pubblicata":
        steps.append(f"Pronta: POST /api/v1/ai/models/publish {{model:'{ref}'}}")
    if any(w["code"].startswith("SEO_") or w["code"] == "ALT_MISSING" for w in v["warnings"]):
        steps.append("SEO: POST /api/v1/ai/seo/apply-safe-fixes per completare title/meta/ALT automaticamente")
    return steps


def _errors_it(v: dict) -> str:
    if not v["errors"]:
        return "nessun requisito mancante"
    return "mancano: " + ", ".join(e["field"] for e in v["errors"])


# ---------------- BODIES ----------------
class AICreateModel(BaseModel):
    model_config = ConfigDict(extra='allow')
    nome: str
    reason: Optional[str] = ""


class AIRef(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str
    reason: Optional[str] = ""
    force: bool = False


class AIUpdateModel(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str
    changes: Dict[str, Any]
    reason: Optional[str] = ""


class AIFeature(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str
    position: int = 0
    badge: Optional[str] = None
    pellicola: Optional[bool] = None
    reason: Optional[str] = ""


class AIMediaUpload(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str
    slot: str = "pair"                 # foto_card | foto_copertina | foto_card_teaser | foto_segreta_hero | og_image | pair | pellicola | messaggio_foto | messaggio_video
    side: str = "pubblico"
    url: Optional[str] = None
    base64_data: Optional[str] = None
    content_type: Optional[str] = None
    filename: Optional[str] = ""
    alt: Optional[str] = ""
    seo_name: Optional[str] = ""
    poster_url: Optional[str] = None
    pair_index: Optional[int] = None
    reason: Optional[str] = ""


class AIMediaBatch(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str
    items: List[AIMediaUpload]


class AISeo(BaseModel):
    model_config = ConfigDict(extra='ignore')
    scope: Optional[str] = "all"
    model: Optional[str] = None
    dry_run: bool = False


class AILanding(BaseModel):
    model_config = ConfigDict(extra='allow')
    titolo: Optional[str] = None
    landing: Optional[str] = None
    changes: Optional[Dict[str, Any]] = None
    publish: bool = False


class AIQuery(BaseModel):
    model_config = ConfigDict(extra='ignore')
    question: str = "overview"        # overview | best_converting_model | italian_traffic | model_stats | traffic_sources | missing | top_models | onlyfans
    model: Optional[str] = None
    range: str = "30g"
    country: Optional[str] = None
    device: Optional[str] = None
    source: Optional[str] = None


class AIRollback(BaseModel):
    version_id: str
    reason: Optional[str] = ""


# ---------------- MODELS ----------------
@ai_router.post("/models/create")
async def ai_create(body: AICreateModel, request: Request, principal=Depends(require("ai:execute", "models:write"))):
    """'Crea Vanessa.' -> creates a DRAFT model with any provided fields, returns what's missing."""
    data = body.model_dump()
    reason = data.pop("reason", "") or "Creazione via AI"
    data["stato"] = "bozza"
    out = await create_model(data, _ai_principal(principal), request, reason)
    v = out["validation"]
    s = f"{out['nome_artistico']} creata in bozza (stato {out['workflow_status']}); {_errors_it(v)}."
    await log_action(principal, request, "models.create", body.model_dump(), s, True, {"id": out["id"]})
    return envelope("models.create", request, s, {"id": out["id"], "slug": out["slug"], "workflow_status": out["workflow_status"], "validation": v, "admin_url": f"/admin/modelle/{out['id']}"},
                    [w["message"] for w in v["warnings"]], _steps_for(v, out))


@ai_router.post("/models/find")
async def ai_find(body: AIRef, request: Request, principal=Depends(require("ai:execute", "models:read"))):
    try:
        doc = await resolve_model(body.model, include_deleted=True)
    except HTTPException as e:
        if e.status_code == 409:
            return envelope("models.find", request, "Più modelle corrispondono: specifica id o slug", e.detail, ok=False)
        raise
    s = model_summary(doc)
    return envelope("models.find", request, f"Trovata {s['nome_artistico']} ({s['workflow_status']})", s)


@ai_router.post("/models/update")
async def ai_update(body: AIUpdateModel, request: Request, principal=Depends(require("ai:execute", "models:write"))):
    """'Aggiorna la bio di Alessia.' -> partial deep-merge update with versioning."""
    doc = await resolve_model(body.model)
    unknown = [k for k in body.changes if k not in ALLOWED_FIELDS]
    out = await patch_model(doc, body.changes, _ai_principal(principal), request, body.reason or "Aggiornamento via AI")
    v = out["validation"]
    s = f"{out['nome_artistico']} aggiornata ({', '.join(out['changed_fields']) or 'nessuna differenza'}); stato {out['workflow_status']}; {_errors_it(v)}."
    warnings = [w["message"] for w in v["warnings"]]
    if unknown:
        warnings.insert(0, f"Campi ignorati (non esistono): {', '.join(unknown)}")
    if out.get("_auto"):
        warnings.insert(0, "La modella era pubblicata ma ora non supera i requisiti: riportata in bozza automaticamente")
    await log_action(principal, request, "models.update", body.model_dump(), s, True, {"version_id": out.get("version_id")})
    return envelope("models.update", request, s, {"id": out["id"], "slug": out["slug"], "workflow_status": out["workflow_status"], "changed_fields": out["changed_fields"], "version_id": out.get("version_id"), "validation": v},
                    warnings, _steps_for(v, out) + ([f"Annulla: POST /api/v1/ai/rollback {{version_id:'{out.get('version_id')}'}}"] if out.get("version_id") else []))


@ai_router.post("/models/validate")
async def ai_validate(body: AIRef, request: Request, principal=Depends(require("ai:execute", "models:read"))):
    """'Controlla se manca qualcosa.'"""
    doc = await resolve_model(body.model, include_deleted=True)
    v = validate_model(doc)
    s = f"{doc.get('nome_artistico')}: {'PRONTA' if v['ready'] else 'NON pronta'} ({v['status']}); {_errors_it(v)}; {len(v['warnings'])} avvisi."
    return envelope("models.validate", request, s, {"id": doc["id"], "slug": doc["slug"], **v}, [w["message"] for w in v["warnings"]], _steps_for(v, doc))


@ai_router.post("/models/publish")
async def ai_publish(body: AIRef, request: Request, principal=Depends(require("ai:execute", "models:publish"))):
    """'Mettila online.'"""
    doc = await resolve_model(body.model)
    try:
        out = await transition(doc, "publish", _ai_principal(principal), request, body.reason or "Pubblicazione via AI")
    except HTTPException as e:
        if e.status_code == 400:
            v = validate_model(doc)
            s = f"Impossibile pubblicare {doc.get('nome_artistico')}: {_errors_it(v)}."
            await log_action(principal, request, "models.publish", body.model_dump(), s, False)
            return envelope("models.publish", request, s, {"id": doc["id"], "slug": doc["slug"], "validation": v}, [w["message"] for w in v["warnings"]], _steps_for(v, doc), ok=False)
        raise
    s = f"{out['nome_artistico']} è ONLINE su /modelle/{out['slug']}."
    await log_action(principal, request, "models.publish", body.model_dump(), s, True, {"version_id": out.get("version_id")})
    return envelope("models.publish", request, s, {"id": out["id"], "slug": out["slug"], "public_url": f"/modelle/{out['slug']}", "workflow_status": out["workflow_status"], "version_id": out.get("version_id")},
                    [w["message"] for w in out["validation"]["warnings"]], ["Verifica la pagina pubblica", "SEO: POST /api/v1/ai/seo/audit"])


@ai_router.post("/models/unpublish")
async def ai_unpublish(body: AIRef, request: Request, principal=Depends(require("ai:execute", "models:publish"))):
    doc = await resolve_model(body.model)
    out = await transition(doc, "unpublish", _ai_principal(principal), request, body.reason or "Ritiro via AI")
    s = f"{out['nome_artistico']} non è più online (bozza)."
    await log_action(principal, request, "models.unpublish", body.model_dump(), s)
    return envelope("models.unpublish", request, s, {"id": out["id"], "workflow_status": out["workflow_status"], "version_id": out.get("version_id")})


@ai_router.post("/models/archive")
async def ai_archive(body: AIRef, request: Request, principal=Depends(require("ai:execute", "models:write"))):
    doc = await resolve_model(body.model)
    out = await transition(doc, "archive", _ai_principal(principal), request, body.reason or "Archiviazione via AI")
    s = f"{out['nome_artistico']} archiviata (ripristinabile)."
    await log_action(principal, request, "models.archive", body.model_dump(), s)
    return envelope("models.archive", request, s, {"id": out["id"], "workflow_status": out["workflow_status"], "version_id": out.get("version_id")}, next_steps=[f"Ripristina: POST /api/v1/models/{out['id']}/restore"])


@ai_router.post("/models/feature")
async def ai_feature(body: AIFeature, request: Request, principal=Depends(require("ai:execute", "models:write"))):
    """'Metti questa modella in homepage.'"""
    from v1_models import feature as feature_route, FeatureBody
    out = await feature_route(body.model, FeatureBody(position=body.position, badge=body.badge, pellicola=body.pellicola, reason=body.reason), request, _ai_principal(principal))
    s = f"{out['nome_artistico']} in posizione {out['home_position'] + 1} della Home" + (f" con badge {body.badge}" if body.badge else "") + ("." if out.get("published") else " (visibile dopo la pubblicazione).")
    await log_action(principal, request, "models.feature", body.model_dump(), s)
    return envelope("models.feature", request, s, {"id": out["id"], "home_position": out["home_position"], "badge": out.get("badge"), "published": out.get("published"), "version_id": out.get("version_id")}, [out["note"]] if out.get("note") else [])


@ai_router.get("/models/missing")
async def ai_missing(model: Optional[str] = None, request: Request = None, principal=Depends(require("ai:execute", "models:read"))):
    """'Controlla se manca qualcosa' (all models or one)."""
    if model:
        doc = await resolve_model(model, include_deleted=True)
        v = validate_model(doc)
        return envelope("models.missing", request, f"{doc.get('nome_artistico')}: {_errors_it(v)}", {"items": [{"slug": doc["slug"], "status": v["status"], "missing": [e["field"] for e in v["errors"]], "warnings": [w["message"] for w in v["warnings"]]}]}, next_steps=_steps_for(v, doc))
    items = []
    async for d in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}):
        v = validate_model(d)
        if v["errors"] or v["status"] in ("ERROR", "INCOMPLETE", "DRAFT"):
            items.append({"slug": d["slug"], "nome": d.get("nome_artistico"), "status": v["status"], "missing": [e["field"] for e in v["errors"]]})
    s = f"{len(items)} modelle con requisiti mancanti." if items else "Tutte le modelle sono complete."
    return envelope("models.missing", request, s, {"items": items})


@ai_router.get("/models")
async def ai_list(status: Optional[str] = None, request: Request = None, principal=Depends(require("ai:execute", "models:read"))):
    items = [model_summary(d) async for d in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}).sort("ordine", 1)]
    if status:
        items = [i for i in items if i["workflow_status"] == status.upper()]
    counts: Dict[str, int] = {}
    for i in items:
        counts[i["workflow_status"]] = counts.get(i["workflow_status"], 0) + 1
    return envelope("models.list", request, f"{len(items)} modelle: " + ", ".join(f"{k} {v}" for k, v in counts.items()), {"items": items, "counts": counts})


# ---------------- MEDIA ----------------
async def _ai_upload_one(item: AIMediaUpload, principal: dict, request: Request) -> dict:
    from v1_media import upload_from_url, FromUrlBody
    doc = await resolve_model(item.model)
    tipo_hint = "video" if (item.url or "").lower().split("?")[0].endswith((".mp4", ".webm", ".mov")) or (item.content_type or "").startswith("video") else "image"
    slot = item.slot
    if slot in ("video", "foto", "photo", "image"):
        slot = "pair"
    res = await upload_from_url(FromUrlBody(url=item.url, base64_data=item.base64_data, content_type=item.content_type, filename=item.filename, alt=item.alt or f"{doc.get('nome_artistico')} {'video' if tipo_hint == 'video' else 'foto'} {'lato segreto' if item.side == 'segreto' else 'lato pubblico'}",
                                            seo_name=item.seo_name or f"{doc.get('slug')}-{item.side}-{slot}", model_id=doc["id"], slot=slot, side=item.side, pair_index=item.pair_index, poster_url=item.poster_url), request, _ai_principal(principal))
    return {"file_id": res["file"]["id"], "tipo": res["file"]["tipo"], "url": res["file"]["url"], "web_url": res["file"].get("web_url"), "poster_url": res["file"].get("poster_url"), "slot": slot, "side": item.side, "model": res.get("model")}


@ai_router.post("/media/upload")
async def ai_media_upload(body: AIMediaUpload, request: Request, principal=Depends(require("ai:execute", "media:write", "models:write"))):
    """'Carica questa foto su Vanessa (lato pubblico).' URL or base64 -> stored, optimized, attached."""
    r = await _ai_upload_one(body, principal, request)
    m = r.get("model") or {}
    v = m.get("validation") or {}
    s = f"{r['tipo']} caricato e assegnato a slot {r['slot']} ({r['side']}); stato modella {m.get('workflow_status')}; {_errors_it(v) if v else ''}"
    await log_action(principal, request, "media.upload", body.model_dump(), s, True, r)
    return envelope("media.upload", request, s, r, [w["message"] for w in (v.get("warnings") or [])], _steps_for(v, {"slug": body.model}) if v else [])


@ai_router.post("/media/upload-batch")
async def ai_media_batch(body: AIMediaBatch, request: Request, principal=Depends(require("ai:execute", "media:write", "models:write"))):
    """'Carica queste foto.' -> multiple URLs in one call."""
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0}) or {}
    mx = int((cfg.get("ai") or {}).get("max_batch", 20))
    if len(body.items) > mx:
        raise HTTPException(status_code=400, detail=f"Massimo {mx} media per batch")
    results, errors = [], []
    for it in body.items:
        it.model = it.model or body.model
        try:
            results.append(await _ai_upload_one(it, principal, request))
        except HTTPException as e:
            errors.append({"url": it.url, "error": e.detail})
        except Exception as e:
            errors.append({"url": it.url, "error": str(e)})
    doc = await resolve_model(body.model)
    v = validate_model(doc)
    s = f"{len(results)} media caricati, {len(errors)} errori; {doc.get('nome_artistico')} ora {v['status']}; {_errors_it(v)}."
    await log_action(principal, request, "media.upload_batch", {"model": body.model, "count": len(body.items)}, s, not errors)
    return envelope("media.upload_batch", request, s, {"uploaded": results, "errors": errors, "validation": v}, [e["error"] if isinstance(e["error"], str) else str(e["error"]) for e in errors], _steps_for(v, doc), ok=not errors)


# ---------------- SEO ----------------
@ai_router.post("/seo/audit")
async def ai_seo_audit(body: AISeo = AISeo(), request: Request = None, principal=Depends(require("ai:execute", "seo:read"))):
    from v1_seo import run_audit
    entity = None
    if body.model:
        entity = (await resolve_model(body.model, include_deleted=True))["id"]
    res = await run_audit(body.scope if not body.model else "models", entity)
    c = res["counts"]
    issues = await seo_issues_col.find({"status": "open", **({"entity_id": entity} if entity else {})}, {"_id": 0, "code": 1, "severity": 1, "entity_label": 1, "message": 1, "id": 1}).sort("severity", 1).to_list(60)
    s = f"Audit SEO: {res['total']} issue (SAFE {c['SAFE_AUTO_FIX']} correggibili in automatico, REVIEW {c['REVIEW_REQUIRED']}, CRITICAL {c['CRITICAL']}). Health score {res['health_score']}/100."
    await log_action(principal, request, "seo.audit", body.model_dump(), s)
    steps = []
    if c["SAFE_AUTO_FIX"]:
        steps.append("POST /api/v1/ai/seo/apply-safe-fixes per correggere le SAFE")
    if c["CRITICAL"]:
        steps.append("Le CRITICAL richiedono intervento umano (link OnlyFans, pubblicazioni incomplete, slug)")
    return envelope("seo.audit", request, s, {**res, "issues_preview": issues}, next_steps=steps)


@ai_router.post("/seo/apply-safe-fixes")
async def ai_seo_fix(body: AISeo = AISeo(), request: Request = None, principal=Depends(require("ai:execute", "seo:autofix"))):
    """'Sistema gli errori SEO sicuri.' Only SAFE_AUTO_FIX; each fix versioned + rollback-able."""
    from v1_seo import run_audit, apply_safe_fixes
    entity = (await resolve_model(body.model, include_deleted=True))["id"] if body.model else None
    await run_audit(body.scope if not body.model else "models", entity)
    res = await apply_safe_fixes(actor_of(principal), request_id_of(request), body.scope if not body.model else "models", entity, body.dry_run, source="ai")
    if body.dry_run:
        s = f"Simulazione: {res['would_fix']} fix sicuri applicabili."
        return envelope("seo.apply_safe_fixes", request, s, res)
    applied = [r for r in res["results"] if r.get("applied")]
    s = f"Applicati {res['applied']} fix SEO sicuri ({res['skipped']} saltati). Tutto reversibile via version_id."
    await log_action(principal, request, "seo.apply_safe_fixes", body.model_dump(), s, True, {"applied": res["applied"]})
    return envelope("seo.apply_safe_fixes", request, s, {"applied": res["applied"], "skipped": res["skipped"], "fixes": applied[:50], "request_id": request_id_of(request)},
                    next_steps=[f"Annulla un fix: POST /api/v1/versions/{{version_id}}/rollback", "Rivedi le REVIEW_REQUIRED: GET /api/v1/seo/issues?severity=REVIEW_REQUIRED"])


# ---------------- LANDINGS ----------------
@ai_router.post("/landing/create")
async def ai_landing_create(body: AILanding, request: Request, principal=Depends(require("ai:execute", "landings:write"))):
    from v1_landings import create_landing, set_landing_state
    data = body.model_dump()
    publish = data.pop("publish", False)
    data.pop("landing", None)
    data.pop("changes", None)
    if not data.get("titolo"):
        raise HTTPException(status_code=400, detail="titolo obbligatorio")
    out = await create_landing(data, _ai_principal(principal), request)
    if publish and out["validation"]["ready"]:
        out = await set_landing_state(await __import__("v1_landings").resolve_landing(out["id"]), "pubblicata", _ai_principal(principal), request)
    s = f"Landing '{out['titolo']}' creata ({out['workflow_status']}) su {out['public_url']}."
    await log_action(principal, request, "landing.create", {"titolo": data.get("titolo")}, s)
    return envelope("landing.create", request, s, out, [w["message"] for w in out["validation"]["warnings"]],
                    ["Le landing sono servite da /api/landings/{slug}; la rotta pubblica /l/{slug} si attiva con il flag public_landing_routes (fase successiva)"])


@ai_router.post("/landing/update")
async def ai_landing_update(body: AILanding, request: Request, principal=Depends(require("ai:execute", "landings:write"))):
    from v1_landings import resolve_landing, patch_landing, set_landing_state
    if not body.landing:
        raise HTTPException(status_code=400, detail="'landing' (id|slug|titolo) obbligatorio")
    doc = await resolve_landing(body.landing)
    out = await patch_landing(doc, body.changes or {}, _ai_principal(principal), request, "Aggiornamento via AI") if body.changes else __import__("v1_landings")._enrich(doc)
    if body.publish:
        out = await set_landing_state(await resolve_landing(doc["id"]), "pubblicata", _ai_principal(principal), request)
    s = f"Landing '{out['titolo']}' aggiornata ({out['workflow_status']})."
    await log_action(principal, request, "landing.update", {"landing": body.landing}, s)
    return envelope("landing.update", request, s, out)


# ---------------- STATUS / SUMMARY / ANALYTICS ----------------
async def build_daily_summary() -> dict:
    now = datetime.now(timezone.utc)
    m24 = build_match("1g")
    m7 = build_match("7g")
    f24 = await funnel_for(m24)
    f7 = await funnel_for(m7)
    it24 = await funnel_for({**m24, "geo.country": "IT"})
    top = []
    async for r in events_col.aggregate([{"$match": _ev_match(m7, "onlyfans_click")}, {"$group": {"_id": "$model_id", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 5}]):
        m = await models_col.find_one({"id": r["_id"]}, {"_id": 0, "slug": 1, "nome_artistico": 1})
        if m:
            top.append({**m, "onlyfans_clicks_7d": r["n"]})
    since = (now - timedelta(hours=24)).isoformat()
    fixes = await versions_col.count_documents({"source": "autofix", "timestamp": {"$gte": since}})
    ai_actions = await ai_actions_col.count_documents({"timestamp": {"$gte": since}})
    alerts_open = await alerts_col.find({"stato": "open"}, {"_id": 0, "titolo": 1, "severity": 1, "created_at": 1}).sort("created_at", -1).to_list(10)
    seo_counts = {}
    async for r in seo_issues_col.aggregate([{"$match": {"status": "open"}}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        seo_counts[r["_id"]] = r["n"]
    jobs_err = await jobs_col.count_documents({"last_status": "error"})
    health = await health_col.find_one({}, {"_id": 0, "overall": 1, "timestamp": 1}, sort=[("timestamp", -1)])
    counts: Dict[str, int] = {}
    async for d in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}):
        st = validate_model(d)["status"]
        counts[st] = counts.get(st, 0) + 1
    v24 = f24["steps"][1]["value"]
    text = (f"Ultime 24h: {f24['steps'][0]['value']} sessioni, {v24} profili visti, {f24['steps'][2]['value']} Lati Segreti, {f24['steps'][4]['value']} click OnlyFans "
            f"(conversione {f24['conversion_rate']}%). Traffico italiano: {round(it24['steps'][1]['value'] / v24 * 100, 1) if v24 else 0}% dei profili visti. "
            f"Modelle: {counts}. SEO aperte: {seo_counts or 'nessuna'}. Fix automatici 24h: {fixes}. Azioni AI 24h: {ai_actions}. Alert aperti: {len(alerts_open)}. "
            f"Health: {(health or {}).get('overall', 'n/d')}.")
    return {"generated_at": now_iso(), "text": text, "traffic_24h": f24, "traffic_7d": f7, "italy_24h": it24, "top_models_7d": top, "models_by_status": counts,
            "seo_open": seo_counts, "autofixes_24h": fixes, "ai_actions_24h": ai_actions, "alerts_open": alerts_open, "jobs_in_error": jobs_err, "health": health}


@ai_router.get("/status")
async def ai_status(request: Request, principal=Depends(require("ai:execute"))):
    from database import db
    try:
        await db.command("ping")
        db_ok = True
    except Exception:
        db_ok = False
    health = await health_col.find_one({}, {"_id": 0, "overall": 1, "timestamp": 1, "actions": 1}, sort=[("timestamp", -1)])
    alerts = await alerts_col.count_documents({"stato": "open"})
    jobs = await jobs_col.find({}, {"_id": 0, "name": 1, "last_status": 1, "last_run": 1, "enabled": 1}).to_list(50)
    seo_counts = {}
    async for r in seo_issues_col.aggregate([{"$match": {"status": "open"}}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        seo_counts[r["_id"]] = r["n"]
    counts: Dict[str, int] = {}
    async for d in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}):
        st = validate_model(d)["status"]
        counts[st] = counts.get(st, 0) + 1
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    s = f"API online, DB {'ok' if db_ok else 'KO'}, health {(health or {}).get('overall', 'n/d')}, {alerts} alert aperti, modelle {counts}, SEO aperte {seo_counts or 0}."
    return envelope("status", request, s, {"api": "online", "database": db_ok, "health": health, "open_alerts": alerts, "jobs": jobs, "seo_open": seo_counts, "models_by_status": counts, "flags": cfg.get("flags", {}), "you": {"role": principal.get("role"), "scopes": principal.get("scopes")}})


@ai_router.get("/daily-summary")
async def ai_daily(request: Request, fresh: bool = True, principal=Depends(require("ai:execute", "analytics:read"))):
    if not fresh:
        cached = await config_col.find_one({"id": "daily_summary"}, {"_id": 0})
        if cached:
            return envelope("daily_summary", request, cached["summary"]["text"], cached["summary"])
    s = await build_daily_summary()
    return envelope("daily_summary", request, s["text"], s)


@ai_router.post("/analytics/query")
async def ai_query(body: AIQuery, request: Request, principal=Depends(require("ai:execute", "analytics:read"))):
    """Structured analytics questions: 'Quale modella converte meglio?', 'Mostrami solo il traffico italiano', ..."""
    q = body.question.lower().strip()
    match = build_match(body.range, body.country, None, None, body.device, body.source)
    if "ital" in q or q == "italian_traffic":
        from v1_tracking import italy
        d = await italy(match, principal)
        s = f"Traffico italiano ({body.range}): {d['model_views_italy']} profili visti su {d['model_views_total']} ({d['italian_share']}%), {d['funnel_italy']['steps'][4]['value']} click OnlyFans, conversione {d['funnel_italy']['conversion_rate']}%."
        return envelope("analytics.italian_traffic", request, s, d)
    if "convert" in q or q in ("best_converting_model", "top_models"):
        rows = []
        async for m in models_col.find({"is_deleted": {"$ne": True}, "stato": "pubblicata"}, {"_id": 0, "id": 1, "slug": 1, "nome_artistico": 1}):
            rows.append({**m, **(await model_kpis(m["id"], match))})
        rows.sort(key=lambda r: (r["conversion_rate"], r["onlyfans_clicks"]), reverse=True)
        best = next((r for r in rows if r["onlyfans_clicks"] > 0), None)
        s = (f"Converte meglio {best['nome_artistico']}: {best['conversion_rate']}% ({best['onlyfans_clicks']} click OnlyFans su {best['visits']} visite, {body.range})." if best else f"Nessun click OnlyFans nel periodo {body.range}.")
        return envelope("analytics.best_converting_model", request, s, {"best": best, "ranking": rows[:10]})
    if body.model or q in ("model_stats",):
        if not body.model:
            raise HTTPException(status_code=400, detail="Specifica 'model'")
        doc = await resolve_model(body.model, include_deleted=True)
        k = await model_kpis(doc["id"], match)
        s = f"{doc.get('nome_artistico')} ({body.range}): {k['visits']} visite, attivazione {k['activation_rate']}%, {k['onlyfans_clicks']} click OnlyFans, conversione {k['conversion_rate']}%, traffico IT {k['italian_share']}%."
        return envelope("analytics.model_stats", request, s, {"model": {"id": doc["id"], "slug": doc["slug"]}, **k})
    if "sorgent" in q or "source" in q or "traffic_sources" in q:
        src = await counts_by(_ev_match(match, "model_view"), "source")
        of = await counts_by(_ev_match(match, "onlyfans_click"), "source")
        s = "Sorgenti (profili visti): " + ", ".join(f"{k} {v}" for k, v in sorted(src.items(), key=lambda x: -x[1])[:6])
        return envelope("analytics.traffic_sources", request, s, {"model_views_by_source": src, "onlyfans_clicks_by_source": of})
    if "onlyfans" in q:
        from v1_tracking import onlyfans_funnel
        d = await onlyfans_funnel(match, principal)
        s = f"Click OnlyFans ({body.range}): {sum(x['clicks'] for x in d['by_model'])} totali; {len(d['broken_links'])} link problematici."
        return envelope("analytics.onlyfans", request, s, d)
    f = await funnel_for(match)
    it = await funnel_for({**match, "geo.country": "IT"})
    s = f"Overview {body.range}: {f['steps'][0]['value']} sessioni, {f['steps'][1]['value']} profili visti, {f['steps'][2]['value']} Lati Segreti, {f['steps'][4]['value']} click OnlyFans (conv. {f['conversion_rate']}%); Italia {it['steps'][1]['value']} profili visti."
    return envelope("analytics.overview", request, s, {"funnel": f, "italy": it, "filters": match})


@ai_router.post("/rollback")
async def ai_rollback(body: AIRollback, request: Request, principal=Depends(require("ai:execute", "versions:rollback"))):
    from v1_versioning import rollback_version
    res = await rollback_version(body.version_id, actor_of(principal), request_id_of(request), body.reason or "Rollback via AI")
    s = f"Rollback eseguito su {res['entity']} {res['entity_id']} ({res['operation']}). Nuova versione {res['new_version_id']}."
    await log_action(principal, request, "rollback", body.model_dump(), s)
    return envelope("rollback", request, s, res)


@ai_router.get("/actions")
async def ai_actions(limit: int = 50, request: Request = None, principal=Depends(require("ai:execute"))):
    items = await ai_actions_col.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return envelope("actions", request, f"{len(items)} azioni AI recenti", {"items": items})


@ai_router.get("/capabilities")
async def capabilities(request: Request, principal=Depends(require("ai:execute"))):
    """Machine-readable catalogue for GPT Actions / agents."""
    base = "/api/v1/ai"
    caps = [
        {"intent": "Crea <nome>", "method": "POST", "path": f"{base}/models/create", "body": {"nome": "Vanessa", "frase": "...", "bio": "...", "categorie": ["more"], "onlyfans_url": "https://onlyfans.com/..."}},
        {"intent": "Modifica <nome> / Aggiorna la bio", "method": "POST", "path": f"{base}/models/update", "body": {"model": "vanessa", "changes": {"bio": "...", "tema": {"preset": "tattoo"}}}},
        {"intent": "Carica queste foto", "method": "POST", "path": f"{base}/media/upload-batch", "body": {"model": "vanessa", "items": [{"model": "vanessa", "slot": "pair", "side": "pubblico", "url": "https://..."}]}},
        {"intent": "Carica una foto/video", "method": "POST", "path": f"{base}/media/upload", "body": {"model": "vanessa", "slot": "foto_card|pair|pellicola|og_image", "side": "pubblico|segreto", "url": "https://..."}},
        {"intent": "Controlla se manca qualcosa", "method": "POST", "path": f"{base}/models/validate", "body": {"model": "vanessa"}},
        {"intent": "Mettila online", "method": "POST", "path": f"{base}/models/publish", "body": {"model": "vanessa"}},
        {"intent": "Metti in homepage", "method": "POST", "path": f"{base}/models/feature", "body": {"model": "vanessa", "position": 0, "badge": "IN TENDENZA"}},
        {"intent": "Sistema gli errori SEO sicuri", "method": "POST", "path": f"{base}/seo/apply-safe-fixes", "body": {"scope": "all"}},
        {"intent": "Audit SEO", "method": "POST", "path": f"{base}/seo/audit", "body": {"scope": "all"}},
        {"intent": "Fammi vedere le statistiche", "method": "GET", "path": f"{base}/daily-summary"},
        {"intent": "Quale modella converte meglio?", "method": "POST", "path": f"{base}/analytics/query", "body": {"question": "best_converting_model", "range": "30g"}},
        {"intent": "Mostrami solo il traffico italiano", "method": "POST", "path": f"{base}/analytics/query", "body": {"question": "italian_traffic", "range": "30g"}},
        {"intent": "Crea una landing", "method": "POST", "path": f"{base}/landing/create", "body": {"titolo": "...", "headline": "...", "model_slugs": ["vanessa-neri"], "cta": {"testo": "..."}}},
        {"intent": "Annulla l'ultima modifica", "method": "POST", "path": f"{base}/rollback", "body": {"version_id": "..."}},
        {"intent": "Stato del sistema", "method": "GET", "path": f"{base}/status"},
    ]
    return envelope("capabilities", request, f"{len(caps)} azioni disponibili", {"auth": "header X-API-Key (ruolo AI_OPERATOR) oppure Bearer JWT", "openapi": "/api/openapi.json", "docs": "/api/docs",
                                                                              "idempotency": "header Idempotency-Key su POST/PATCH", "model_reference": "id | slug | nome (case-insensitive)", "actions": caps,
                                                                              "model_fields": sorted(ALLOWED_FIELDS), "slots": ["foto_card", "foto_copertina", "foto_card_teaser", "foto_segreta_hero", "og_image", "pair", "pellicola", "messaggio_foto", "messaggio_video"]})
