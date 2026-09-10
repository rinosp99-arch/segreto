"""SUPER API v1 - AI / CHATGPT CONTROL LAYER (Phase 10).

Contract (every response):
  ok, summary, data, warnings, next_steps, request_id, changes, approval_required [, approval] [, code on error]
Natural references (id | slug | nome | nome parziale non ambiguo). Dry-run everywhere it matters.
Policy: SAFE executes · REVIEW_REQUIRED returns an approval token · CRITICAL is never exposed.
No LLM server-side: deterministic dispatch only; DB text is always data, never instructions.
"""
import os
import time
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
import requests as _requests

from database import (
    ai_actions_col, models_col, alerts_col, jobs_col, seo_issues_col, versions_col, events_col, health_col, config_col, backups_col,
    landings_col, files_col, webhook_deliveries_col, redirects_col, now_iso, serialize_doc,
)
from v1_security import require, actor_of, request_id_of, has_scope, ALL_SCOPES, AI_OPERATOR_SCOPES, AI_READ_ONLY_SCOPES, ROLE_OPTIONAL_SCOPES, generate_api_key, hash_key
from v1_ai_policy import (
    ai_guard, ai_config, classify_model_changes, create_approval, consume_approval, list_pending_approvals, metrics_snapshot, metrics_snapshot_shared, bump,
    SAFE, REVIEW, CRITICAL, ERROR_CODES, redact,
)
from v1_models import resolve_model, create_model, patch_model, transition, validate_model, summary as model_summary, ALLOWED_FIELDS, workflow_status, check_precondition
from v1_tracking import build_match, funnel_for, model_kpis, counts_by, _ev_match, CANONICAL_TO_LEGACY

ai_router = APIRouter(prefix="/api/v1/ai", tags=["AI / ChatGPT"])


# =====================================================================
# helpers
# =====================================================================
def _p(principal: dict) -> dict:
    return {**principal, "source": "chatgpt" if principal.get("type") == "api_key" else "ai"}


def envelope(action: str, request: Request, summary: str, data: Any = None, warnings: Optional[List[str]] = None, next_steps: Optional[List[str]] = None,
             ok: bool = True, changes: Optional[List[dict]] = None, approval: Optional[dict] = None, code: Optional[str] = None) -> dict:
    out = {"ok": ok, "action": action, "summary": summary, "data": data if data is not None else {}, "warnings": warnings or [], "next_steps": next_steps or [],
           "request_id": request_id_of(request), "changes": changes or [], "approval_required": approval is not None}
    if approval:
        out["approval"] = approval
        bump("approvals_requested")
    if code:
        out["code"] = code
    return out


async def log_action(principal: dict, request: Request, action: str, inp: Any, result_summary: str, ok: bool = True, target: Optional[dict] = None,
                     changes: Optional[List[dict]] = None, version_ids: Optional[List[str]] = None, started: Optional[float] = None, rollback_ref: Optional[str] = None,
                     before: Any = None, after: Any = None, reason: str = "", session_id: Optional[str] = None, extra: Optional[dict] = None):
    inp_red = redact(inp if isinstance(inp, dict) else {"input": inp})
    if isinstance(inp_red, dict) and "base64_data" in inp_red:
        inp_red["base64_data"] = "<base64>"
    doc = {"id": str(uuid.uuid4()), "request_id": request_id_of(request), "actor": actor_of(principal), "key_id": principal.get("key_id"), "principal_type": "machine" if principal.get("type") == "api_key" else "user",
           "source": "chatgpt" if principal.get("type") == "api_key" else "admin-ai", "action": action, "target": target, "input": inp_red, "ok": ok, "status": "ok" if ok else "error",
           "summary": result_summary, "changes": changes or [], "version_ids": version_ids or [], "rollback_ref": rollback_ref or ((version_ids or [None])[-1]),
           "before": redact(before) if before is not None else None, "after": redact(after) if after is not None else None, "reason": reason or "",
           "session_id": session_id or (inp.get("session_id") if isinstance(inp, dict) else None),  # Phase 12A: session grouping for rollback.session
           "duration_ms": round((time.time() - started) * 1000) if started else None, "timestamp": now_iso(), **(extra or {})}
    await ai_actions_col.insert_one(dict(doc))
    try:
        from v1_config import emit_event
        await emit_event("ai.action", {"action": action, "ok": ok, "summary": result_summary, "actor": actor_of(principal), "request_id": doc["request_id"]})
    except Exception:
        pass


def _steps_for(v: dict, model: dict) -> List[str]:
    steps = []
    codes = {e["code"] for e in v.get("errors", [])}
    ref = model.get("slug") or model.get("id")
    if {"PUBLIC_PHOTOS_LT_3", "SECRET_PHOTOS_LT_3", "PUBLIC_VIDEO_MISSING", "SECRET_VIDEO_MISSING", "CARD_PHOTO_MISSING", "PELLICOLA_PUBLIC_VIDEO_MISSING", "PELLICOLA_SECRET_VIDEO_MISSING"} & codes:
        steps.append(f"Carica media: POST /api/v1/ai/media/upload {{model:'{ref}', slot:'pair'|'foto_card'|'pellicola', side:'pubblico'|'segreto', url:...}}")
    if {"CLAIM_MISSING", "PUBLIC_BIO_MISSING", "SECRET_BIO_MISSING"} & codes:
        steps.append(f"Completa i testi: POST /api/v1/ai/models/update {{model:'{ref}', changes:{{frase, bio, bio_segreta}}}} (richiede approvazione)")
    if "ONLYFANS_URL_MISSING" in codes or "ONLYFANS_URL_INVALID" in codes:
        steps.append(f"Imposta il link: changes:{{onlyfans_url:'https://onlyfans.com/...'}} (richiede approvazione)")
    if "AGE_CONFIRMATION_MISSING" in codes:
        steps.append("Conferma maggiore età: changes:{conferma_maggiorenne:true}")
    if v.get("ready") and model.get("stato") != "pubblicata":
        steps.append(f"Pronta: POST /api/v1/ai/models/publish {{model:'{ref}'}}")
    if any(w["code"].startswith("SEO_") or w["code"] == "ALT_MISSING" for w in v.get("warnings", [])):
        steps.append(f"SEO: POST /api/v1/ai/models/{ref}/seo/apply-safe-fixes")
    return steps


def _errors_it(v: dict) -> str:
    return "nessun requisito mancante" if not v.get("errors") else "mancano: " + ", ".join(e["field"] for e in v["errors"])


def _target(doc: dict) -> dict:
    return {"type": "model", "id": doc.get("id"), "slug": doc.get("slug"), "nome": doc.get("nome_artistico") or doc.get("nome")}


def _changes_from(before: dict, after: dict, fields: List[str]) -> List[dict]:
    return [{"field": f, "before": before.get(f), "after": after.get(f)} for f in fields if f not in ("updated_at",)]


async def _seo_score(entity_id: Optional[str] = None) -> Optional[int]:
    q: Dict[str, Any] = {"status": "open"}
    if entity_id:
        q["entity_id"] = entity_id
    counts = {SAFE_: 0 for SAFE_ in ("SAFE_AUTO_FIX", "REVIEW_REQUIRED", "CRITICAL")}
    async for r in seo_issues_col.aggregate([{"$match": q}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        counts[r["_id"]] = r["n"]
    return max(0, 100 - counts["SAFE_AUTO_FIX"] * (3 if entity_id else 1) - counts["REVIEW_REQUIRED"] * (6 if entity_id else 3) - counts["CRITICAL"] * (20 if entity_id else 10))


# =====================================================================
# bodies
# =====================================================================
class AICreateModel(BaseModel):
    model_config = ConfigDict(extra='allow')
    nome: str
    reason: Optional[str] = ""
    dry_run: bool = False


class AIRef(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str
    reason: Optional[str] = ""
    dry_run: bool = False
    expected_updated_at: Optional[str] = None


class AIUpdateModel(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str
    changes: Dict[str, Any]
    reason: Optional[str] = ""
    dry_run: bool = False
    expected_updated_at: Optional[str] = None


class AIFeature(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str
    position: int = 0
    badge: Optional[str] = None
    pellicola: Optional[bool] = None
    reason: Optional[str] = ""
    dry_run: bool = False


class AIMediaUpload(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str
    slot: str = "pair"
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
    dry_run: bool = False


class AILandingCreate(BaseModel):
    model_config = ConfigDict(extra='allow')
    model: Optional[str] = None                 # model reference
    models: Optional[List[str]] = None
    slug: Optional[str] = ""
    title: Optional[str] = None                 # SEO title
    titolo: Optional[str] = None
    h1: Optional[str] = None
    hero_text: Optional[str] = None
    intro: Optional[str] = None
    cta_text: Optional[str] = None
    cta_url: Optional[str] = None
    meta_description: Optional[str] = None
    keywords: Optional[List[str]] = None
    topics: Optional[List[str]] = None
    canonical: Optional[str] = None
    noindex: bool = False
    location_targeting: Optional[str] = "Italia"   # editorial only, NO geoblocking
    faq: Optional[List[Dict[str, str]]] = None
    reason: Optional[str] = ""
    dry_run: bool = False


class AIQuery(BaseModel):
    model_config = ConfigDict(extra='ignore')
    question: Optional[str] = None
    metric: Optional[str] = None
    group_by: Optional[str] = None
    model: Optional[str] = None
    period: Optional[str] = None
    range: str = "30g"
    country: Optional[str] = None
    region: Optional[str] = None
    device: Optional[str] = None
    source: Optional[str] = None
    sort: str = "desc"
    limit: int = 10


class AIRollback(BaseModel):
    model_config = ConfigDict(extra='ignore')
    version_id: Optional[str] = None
    model: Optional[str] = None
    target: Optional[str] = None
    actor: Optional[str] = None
    request_id: Optional[str] = None
    latest_ai: bool = True
    reason: Optional[str] = ""
    dry_run: bool = False


class AIConfirm(BaseModel):
    token: str
    reason: Optional[str] = ""


class AICommand(BaseModel):
    model_config = ConfigDict(extra='ignore')
    action: str
    target: Optional[str] = None
    parameters: Dict[str, Any] = {}
    reason: Optional[str] = ""
    dry_run: bool = False


class AIBatch(BaseModel):
    model_config = ConfigDict(extra='ignore')
    selection: str = "all"           # all | published | draft | category | ids
    category: Optional[str] = None
    ids: Optional[List[str]] = None
    dry_run: bool = False
    max_items: Optional[int] = None


# =====================================================================
# MODELS
# =====================================================================
@ai_router.post("/models/create", operation_id="createModel", summary="Crea una modella (bozza)")
async def ai_create(body: AICreateModel, request: Request, principal=Depends(ai_guard("models:create", write=True))):
    t0 = time.time()
    data = body.model_dump()
    reason = data.pop("reason", "") or "Creazione via ChatGPT"
    dry = data.pop("dry_run", False)
    data["stato"] = "bozza"
    if dry:
        from schemas import ModelIn
        try:
            norm = ModelIn(**{k: v for k, v in data.items() if k in ALLOWED_FIELDS}).model_dump()
        except Exception as e:
            raise HTTPException(status_code=422, detail={"code": "VALIDATION_FAILED", "message": str(e)})
        v = validate_model(norm)
        return envelope("models.create", request, f"[dry-run] Verrebbe creata '{data['nome']}' in bozza ({v['status']}); {_errors_it(v)}.",
                        {"dry_run": True, "proposed_after": {k: norm.get(k) for k in data if k in norm}, "validation": v, "approval_required": False})
    out = await create_model(data, _p(principal), request, reason)
    v = out["validation"]
    s = f"{out['nome_artistico']} creata in bozza (stato {out['workflow_status']}); {_errors_it(v)}."
    await log_action(principal, request, "models.create", body.model_dump(), s, True, _target(out), [{"field": "create", "before": None, "after": out["slug"]}], started=t0, reason=reason)
    return envelope("models.create", request, s, {"id": out["id"], "slug": out["slug"], "workflow_status": out["workflow_status"], "validation": v, "etag": out.get("updated_at"), "admin_url": f"/admin/modelle/{out['id']}"},
                    [w["message"] for w in v["warnings"]], _steps_for(v, out), changes=[{"field": "model", "before": None, "after": out["slug"]}])


@ai_router.post("/models/find", operation_id="findModel", summary="Trova una modella (id | slug | nome)")
async def ai_find(body: AIRef, request: Request, principal=Depends(ai_guard("models:read"))):
    doc = await resolve_model(body.model, include_deleted=True)
    s = model_summary(doc)
    s["etag"] = doc.get("updated_at")
    return envelope("models.find", request, f"Trovata {s['nome_artistico']} ({s['workflow_status']})", s)


@ai_router.get("/models", operation_id="listModels", summary="Elenco modelle con stato workflow")
async def ai_list(status: Optional[str] = None, request: Request = None, principal=Depends(ai_guard("models:read"))):
    items = [model_summary(d) async for d in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}).sort("ordine", 1)]
    if status:
        items = [i for i in items if i["workflow_status"] == status.upper()]
    counts: Dict[str, int] = {}
    for i in items:
        counts[i["workflow_status"]] = counts.get(i["workflow_status"], 0) + 1
    return envelope("models.list", request, f"{len(items)} modelle: " + ", ".join(f"{k} {v}" for k, v in counts.items()), {"items": items, "counts": counts})


async def _apply_model_update(doc: dict, changes: dict, principal: dict, request: Request, reason: str, dry_run: bool, expected: Optional[str], t0: float, action="models.update"):
    cfg = await ai_config()
    unknown = [k for k in changes if k not in ALLOWED_FIELDS]
    cls = classify_model_changes({k: v for k, v in changes.items() if k in ALLOWED_FIELDS}, cfg["policy"])
    # always compute the preview first (no DB writes)
    preview = await patch_model(doc, changes, _p(principal), request, reason, dry_run=True, expected_updated_at=expected)
    changes_list = _changes_from(preview["before"], preview["proposed_after"], preview["changed_fields"])
    warnings = [w["message"] for w in preview["validation"]["warnings"]]
    if unknown:
        warnings.insert(0, f"Campi ignorati (non esistono): {', '.join(unknown)}")
    if preview.get("auto"):
        warnings.insert(0, "La modella è pubblicata e con questa modifica non supererebbe più i requisiti: verrebbe riportata in bozza")
    if not preview["changed_fields"]:
        return envelope(action, request, f"Nessuna differenza: {doc.get('nome_artistico')} è già così.", {"id": doc["id"], "slug": doc["slug"], "changed_fields": [], "etag": doc.get("updated_at")})
    if dry_run:
        return envelope(action, request, f"[dry-run] {doc.get('nome_artistico')}: {len(preview['changed_fields'])} campi cambierebbero ({', '.join(preview['changed_fields'])}); livello {cls['level']}; stato {preview['workflow_status_before']} → {preview['workflow_status_after']}.",
                        {**preview, "policy": cls, "approval_required": cls["level"] == REVIEW}, warnings, changes=changes_list)
    if cls["level"] == REVIEW:
        if not cfg["approval_enabled"]:
            raise HTTPException(status_code=403, detail={"code": "APPROVAL_DISABLED", "message": "Modifica che richiede revisione umana, ma il flusso di approvazione è disattivato", "review_fields": cls["review_fields"]})
        appr = await create_approval("MODEL_UPDATE", actor_of(principal), _target(doc), {"model_id": doc["id"], "changes": changes, "expected_updated_at": doc.get("updated_at")},
                                     preview["before"], preview["proposed_after"], reason or "Modifica campi editoriali/strategici", request_id_of(request))
        s = f"Modifica preparata per {doc.get('nome_artistico')} (campi {', '.join(cls['review_fields'])} richiedono approvazione). Nessuna modifica applicata."
        await log_action(principal, request, action, {"model": doc["slug"], "changes": changes}, s, True, _target(doc), changes_list, started=t0, reason=reason, before=preview["before"], after=preview["proposed_after"])
        return envelope(action, request, s, {**preview, "policy": cls}, warnings, ["Conferma con POST /api/v1/ai/approvals/confirm {token} dopo approvazione dell'utente"], changes=changes_list, approval=appr)
    out = await patch_model(doc, changes, _p(principal), request, reason or "Aggiornamento via ChatGPT", expected_updated_at=expected)
    v = out["validation"]
    s = f"{out['nome_artistico']} aggiornata ({', '.join(out['changed_fields'])}); stato {out['workflow_status']}; {_errors_it(v)}."
    await log_action(principal, request, action, {"model": doc["slug"], "changes": changes}, s, True, _target(doc), changes_list, [out.get("version_id")], t0, reason=reason, before=preview["before"], after=preview["proposed_after"])
    return envelope(action, request, s, {"id": out["id"], "slug": out["slug"], "workflow_status": out["workflow_status"], "changed_fields": out["changed_fields"], "version_id": out.get("version_id"), "validation": v, "etag": out.get("etag"), "policy": cls},
                    warnings, _steps_for(v, out) + [f"Annulla: POST /api/v1/ai/rollback {{version_id:'{out.get('version_id')}'}}"], changes=changes_list)


@ai_router.post("/models/update", operation_id="updateModel", summary="Aggiorna una modella (deep-merge, dry_run, approvazione per campi sensibili)")
async def ai_update(body: AIUpdateModel, request: Request, principal=Depends(ai_guard("models:update", write=True))):
    t0 = time.time()
    doc = await resolve_model(body.model)
    return await _apply_model_update(doc, body.changes, principal, request, body.reason or "", body.dry_run, body.expected_updated_at, t0)


@ai_router.post("/models/validate", operation_id="validateModel", summary="Controlla cosa manca per pubblicare")
async def ai_validate(body: AIRef, request: Request, principal=Depends(ai_guard("models:validate"))):
    doc = await resolve_model(body.model, include_deleted=True)
    v = validate_model(doc)
    s = f"{doc.get('nome_artistico')}: {'PRONTA' if v['ready'] else 'NON pronta'} ({v['status']}); {_errors_it(v)}; {len(v['warnings'])} avvisi."
    return envelope("models.validate", request, s, {"id": doc["id"], "slug": doc["slug"], "etag": doc.get("updated_at"), **v}, [w["message"] for w in v["warnings"]], _steps_for(v, doc))


@ai_router.post("/models/publish", operation_id="publishModel", summary="Pubblica (sempre tramite validator; force non bypassa)")
async def ai_publish(body: AIRef, request: Request, principal=Depends(ai_guard("models:publish", write=True))):
    t0 = time.time()
    doc = await resolve_model(body.model)
    check_precondition(doc, body.expected_updated_at)
    v = validate_model(doc)
    if not v["ready"]:
        s = f"Impossibile pubblicare {doc.get('nome_artistico')}: {_errors_it(v)}."
        await log_action(principal, request, "models.publish", body.model_dump(), s, False, _target(doc), started=t0)
        return envelope("models.publish", request, s, {"id": doc["id"], "slug": doc["slug"], "validation": v, "missing": [e["field"] for e in v["errors"]]}, [w["message"] for w in v["warnings"]], _steps_for(v, doc), ok=False, code="PUBLICATION_BLOCKED")
    if doc.get("stato") == "pubblicata":
        return envelope("models.publish", request, f"{doc.get('nome_artistico')} è già online.", {"id": doc["id"], "slug": doc["slug"], "public_url": f"/modelle/{doc['slug']}", "workflow_status": "PUBLISHED"})
    out = await transition(doc, "publish", _p(principal), request, body.reason or "Pubblicazione via ChatGPT", dry_run=body.dry_run)
    if body.dry_run:
        return envelope("models.publish", request, f"[dry-run] {doc.get('nome_artistico')} è pubblicabile: passerebbe a PUBLISHED su /modelle/{doc['slug']}.", out, changes=[{"field": "stato", "before": doc.get("stato"), "after": "pubblicata"}])
    s = f"{out['nome_artistico']} è ONLINE su /modelle/{out['slug']}."
    await log_action(principal, request, "models.publish", body.model_dump(), s, True, _target(doc), [{"field": "stato", "before": doc.get("stato"), "after": "pubblicata"}], [out.get("version_id")], t0)
    return envelope("models.publish", request, s, {"id": out["id"], "slug": out["slug"], "public_url": f"/modelle/{out['slug']}", "workflow_status": out["workflow_status"], "version_id": out.get("version_id"), "etag": out.get("updated_at")},
                    [w["message"] for w in out["validation"]["warnings"]], ["Verifica la pagina pubblica", f"SEO: POST /api/v1/ai/models/{out['slug']}/seo/apply-safe-fixes"], changes=[{"field": "stato", "before": doc.get("stato"), "after": "pubblicata"}])


async def _simple_transition(action: str, label: str, body: AIRef, request: Request, principal: dict, scope_action: str):
    t0 = time.time()
    doc = await resolve_model(body.model, include_deleted=(action == "restore"))
    check_precondition(doc, body.expected_updated_at)
    out = await transition(doc, action, _p(principal), request, body.reason or f"{label} via ChatGPT", dry_run=body.dry_run)
    ch = [{"field": "stato", "before": doc.get("stato"), "after": out.get("stato") or (out.get("proposed_after") or {}).get("stato")}]
    if body.dry_run:
        return envelope(scope_action, request, f"[dry-run] {doc.get('nome_artistico')}: {doc.get('stato')} → {ch[0]['after']} ({out['workflow_status']}).", out, changes=ch)
    s = f"{out['nome_artistico']}: {label} eseguita ({out['workflow_status']})."
    await log_action(principal, request, scope_action, body.model_dump(), s, True, _target(doc), ch, [out.get("version_id")], t0)
    return envelope(scope_action, request, s, {"id": out["id"], "slug": out["slug"], "workflow_status": out["workflow_status"], "version_id": out.get("version_id"), "etag": out.get("updated_at")}, changes=ch,
                    next_steps=[f"Annulla: POST /api/v1/ai/rollback {{version_id:'{out.get('version_id')}'}}"] if out.get("version_id") else [])


@ai_router.post("/models/unpublish", operation_id="unpublishModel", summary="Ritira dalla pubblicazione (torna bozza)")
async def ai_unpublish(body: AIRef, request: Request, principal=Depends(ai_guard("models:unpublish", write=True))):
    return await _simple_transition("unpublish", "Ritiro", body, request, principal, "models.unpublish")


@ai_router.post("/models/archive", operation_id="archiveModel", summary="Archivia (ripristinabile)")
async def ai_archive(body: AIRef, request: Request, principal=Depends(ai_guard("models:archive", write=True))):
    return await _simple_transition("archive", "Archiviazione", body, request, principal, "models.archive")


@ai_router.post("/models/restore", operation_id="restoreModel", summary="Ripristina una modella archiviata")
async def ai_restore(body: AIRef, request: Request, principal=Depends(ai_guard("models:archive", write=True))):
    return await _simple_transition("restore", "Ripristino", body, request, principal, "models.restore")


@ai_router.post("/models/feature", operation_id="featureModel", summary="Metti in evidenza in Home (posizione, badge, pellicola)")
async def ai_feature(body: AIFeature, request: Request, principal=Depends(ai_guard("models:feature", write=True))):
    t0 = time.time()
    doc = await resolve_model(body.model)
    if body.dry_run:
        return envelope("models.feature", request, f"[dry-run] {doc.get('nome_artistico')} andrebbe in posizione {body.position + 1} della Home" + (f" con badge {body.badge}" if body.badge else "") + ".",
                        {"dry_run": True, "before": {"ordine": doc.get("ordine"), "badge": doc.get("badge")}, "proposed_after": {"ordine": body.position, "badge": body.badge if body.badge is not None else doc.get("badge")}, "published": doc.get("stato") == "pubblicata"},
                        changes=[{"field": "ordine", "before": doc.get("ordine"), "after": body.position}])
    from v1_models import feature as feature_route, FeatureBody
    out = await feature_route(doc["id"], FeatureBody(position=body.position, badge=body.badge, pellicola=body.pellicola, reason=body.reason), request, _p(principal))
    ch = [{"field": "ordine", "before": doc.get("ordine"), "after": out["home_position"]}] + ([{"field": "badge", "before": doc.get("badge"), "after": body.badge}] if body.badge is not None else [])
    s = f"{out['nome_artistico']} in posizione {out['home_position'] + 1} della Home" + (f" con badge {body.badge}" if body.badge else "") + ("." if out.get("published") else " (visibile dopo la pubblicazione).")
    await log_action(principal, request, "models.feature", body.model_dump(), s, True, _target(doc), ch, [out.get("version_id")], t0)
    return envelope("models.feature", request, s, {"id": out["id"], "home_position": out["home_position"], "badge": out.get("badge"), "published": out.get("published"), "version_id": out.get("version_id")}, [out["note"]] if out.get("note") else [], changes=ch)


@ai_router.get("/models/missing", operation_id="listMissingRequirements", summary="Cosa manca (tutte o una)")
async def ai_missing(model: Optional[str] = None, request: Request = None, principal=Depends(ai_guard("models:read"))):
    if model:
        doc = await resolve_model(model, include_deleted=True)
        v = validate_model(doc)
        return envelope("models.missing", request, f"{doc.get('nome_artistico')}: {_errors_it(v)}", {"items": [{"slug": doc["slug"], "status": v["status"], "missing": [e["field"] for e in v["errors"]], "warnings": [w["message"] for w in v["warnings"]]}]}, next_steps=_steps_for(v, doc))
    items = []
    async for d in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}):
        v = validate_model(d)
        if v["errors"] or v["status"] in ("ERROR", "INCOMPLETE", "DRAFT"):
            items.append({"slug": d["slug"], "nome": d.get("nome_artistico"), "status": v["status"], "missing": [e["field"] for e in v["errors"]]})
    return envelope("models.missing", request, f"{len(items)} modelle con requisiti mancanti." if items else "Tutte le modelle sono complete.", {"items": items})


async def model_health(doc: dict, range_key: str = "7g") -> dict:
    v = validate_model(doc)
    pairs = doc.get("media_pairs") or []
    pub = [p.get("pubblico") for p in pairs if (p.get("pubblico") or {}).get("url")]
    sec = [p.get("segreto") for p in pairs if (p.get("segreto") or {}).get("url")]
    with_alt = len([m for m in pub + sec if (m or {}).get("alt")])
    total_media = len(pub) + len(sec)
    # broken media (local refs)
    broken = []
    for i, p in enumerate(pairs):
        for side in ("pubblico", "segreto"):
            u = (p.get(side) or {}).get("url") or ""
            if u.startswith("/media/") and not os.path.exists(os.path.join("/app/frontend/public", u.lstrip("/"))):
                broken.append(u)
            elif u.startswith("/api/uploads/") and not await files_col.find_one({"storage_path": u[len("/api/uploads/"):], "is_deleted": {"$ne": True}}):
                broken.append(u)
    optimized = await files_col.count_documents({"model_id": doc["id"], "parent_id": {"$exists": False}, "is_deleted": {"$ne": True}, "metadata.has_web": True})
    files_total = await files_col.count_documents({"model_id": doc["id"], "parent_id": {"$exists": False}, "is_deleted": {"$ne": True}})
    issues = await seo_issues_col.find({"entity_id": doc["id"], "status": "open"}, {"_id": 0, "code": 1, "severity": 1, "message": 1, "id": 1}).to_list(100)
    from v1_models import OF_RX
    of = (doc.get("onlyfans_url") or "").strip()
    seo = doc.get("seo") or {}
    in_sitemap = doc.get("stato") == "pubblicata" and seo.get("indexable", True) and "noindex" not in (seo.get("robots") or "").lower()
    redirects = await redirects_col.find({"to_path": f"/modelle/{doc['slug']}", "active": True}, {"_id": 0, "from_path": 1}).to_list(20)
    kp = await model_kpis(doc["id"], build_match(range_key))
    last_audit = await seo_issues_col.find_one({"entity_id": doc["id"]}, {"_id": 0, "last_seen": 1}, sort=[("last_seen", -1)])
    recent_errors = await ai_actions_col.find({"target.id": doc["id"], "ok": False}, {"_id": 0, "action": 1, "summary": 1, "timestamp": 1}).sort("timestamp", -1).to_list(5)
    last_ver = await versions_col.find_one({"entity": "model", "entity_id": doc["id"]}, {"_id": 0, "timestamp": 1, "actor": 1, "source": 1, "reason": 1}, sort=[("timestamp", -1)])
    return {
        "model": _target(doc), "etag": doc.get("updated_at"),
        "publication": {"stato": doc.get("stato"), "workflow_status": v["status"], "published_at": doc.get("data_pubblicazione"), "public_url": f"/modelle/{doc['slug']}" if doc.get("stato") == "pubblicata" else None},
        "readiness": {"ready": v["ready"], "missing_fields": [e["field"] for e in v["errors"]], "warnings": [w["message"] for w in v["warnings"]]},
        "seo": {"score": await _seo_score(doc["id"]), "open_issues": issues, "title": seo.get("title"), "meta_description": seo.get("meta_description"), "indexable": in_sitemap, "noindex": not in_sitemap, "sitemap_presence": in_sitemap, "last_audit": (last_audit or {}).get("last_seen")},
        "media": {"public_count": len(pub), "secret_count": len(sec), "alt_coverage": round(with_alt / total_media * 100) if total_media else None, "broken": broken, "uploaded_files": files_total, "optimized_files": optimized, "foto_card": bool(doc.get("foto_card"))},
        "cta": {"testo": (doc.get("cta") or {}).get("testo") or doc.get("cta_testo"), "status": "ok" if of and OF_RX.match(of) else ("missing" if not of else "invalid")},
        "onlyfans_link": {"url": of or None, "valid": bool(of and OF_RX.match(of))},
        "social": {k: v_ for k, v_ in (doc.get("social") or {}).items() if v_ and k != "custom"},
        "redirects_to_here": [r["from_path"] for r in redirects],
        "analytics": {"period": range_key, **kp, "data_available": kp["visits"] > 0},
        "recent_errors": recent_errors, "last_modification": last_ver,
    }


@ai_router.get("/models/{reference}/health", operation_id="getModelHealth", summary="Health completo di una modella")
async def ai_model_health(reference: str, request: Request, range: str = "7g", principal=Depends(ai_guard("models:read"))):
    doc = await resolve_model(reference, include_deleted=True)
    h = await model_health(doc, range)
    s = (f"{doc.get('nome_artistico')}: {h['publication']['workflow_status']}, SEO score {h['seo']['score']}, {len(h['seo']['open_issues'])} issue SEO, "
         f"media {h['media']['public_count']}+{h['media']['secret_count']} (ALT {h['media']['alt_coverage']}%), link OnlyFans {h['onlyfans_link']['valid'] and 'ok' or h['cta']['status']}, "
         f"{h['analytics']['visits']} visite {range}" + ("" if h["analytics"]["data_available"] else " (dati analytics non disponibili)") + ".")
    steps = _steps_for({"ready": h["readiness"]["ready"], "errors": [{"field": f, "code": ""} for f in h["readiness"]["missing_fields"]], "warnings": []}, doc)
    if any(i["severity"] == "SAFE_AUTO_FIX" for i in h["seo"]["open_issues"]):
        steps.append(f"POST /api/v1/ai/models/{doc['slug']}/seo/apply-safe-fixes")
    return envelope("models.health", request, s, h, h["readiness"]["warnings"][:5], steps)


# =====================================================================
# MEDIA
# =====================================================================
async def _ai_upload_one(item: AIMediaUpload, principal: dict, request: Request) -> dict:
    from v1_media import upload_from_url, FromUrlBody
    doc = await resolve_model(item.model)
    tipo_hint = "video" if (item.url or "").lower().split("?")[0].endswith((".mp4", ".webm", ".mov")) or (item.content_type or "").startswith("video") else "image"
    slot = item.slot
    if slot in ("video", "foto", "photo", "image"):
        slot = "pair"
    try:
        res = await upload_from_url(FromUrlBody(url=item.url, base64_data=item.base64_data, content_type=item.content_type, filename=item.filename,
                                                alt=item.alt or f"{doc.get('nome_artistico')} {'video' if tipo_hint == 'video' else 'foto'} {'lato segreto' if item.side == 'segreto' else 'lato pubblico'}",
                                                seo_name=item.seo_name or f"{doc.get('slug')}-{item.side}-{slot}", model_id=doc["id"], slot=slot, side=item.side, pair_index=item.pair_index, poster_url=item.poster_url), request, _p(principal))
    except HTTPException as e:
        d = e.detail if isinstance(e.detail, dict) else {"message": e.detail}
        raise HTTPException(status_code=e.status_code, detail={"code": d.get("code") or "MEDIA_VALIDATION_FAILED", **d})
    return {"file_id": res["file"]["id"], "tipo": res["file"]["tipo"], "url": res["file"]["url"], "web_url": res["file"].get("web_url"), "poster_url": res["file"].get("poster_url"), "slot": slot, "side": item.side, "model": res.get("model")}


@ai_router.post("/media/upload", operation_id="uploadMedia", summary="Carica un media (URL pubblico o base64) e assegnalo a uno slot")
async def ai_media_upload(body: AIMediaUpload, request: Request, principal=Depends(ai_guard("media:upload", "models:update", write=True, dry_capable=False))):
    t0 = time.time()
    doc = await resolve_model(body.model)
    r = await _ai_upload_one(body, principal, request)
    m = r.get("model") or {}
    v = m.get("validation") or {}
    s = f"{r['tipo']} caricato e assegnato a slot {r['slot']} ({r['side']}); stato modella {m.get('workflow_status')}; {_errors_it(v) if v else ''}"
    await log_action(principal, request, "media.upload", body.model_dump(), s, True, _target(doc), [{"field": f"{r['slot']}.{r['side']}", "before": None, "after": r["url"]}], started=t0)
    return envelope("media.upload", request, s, r, [w["message"] for w in (v.get("warnings") or [])], _steps_for(v, doc) if v else [], changes=[{"field": f"{r['slot']}.{r['side']}", "before": None, "after": r["url"]}])


@ai_router.post("/media/upload-batch", operation_id="uploadMediaBatch", summary="Carica più media in una chiamata")
async def ai_media_batch(body: AIMediaBatch, request: Request, principal=Depends(ai_guard("media:upload", "models:update", write=True, batch=True, dry_capable=False))):
    t0 = time.time()
    cfg = await ai_config()
    mx = int(cfg["policy"].get("max_batch", 50))
    if len(body.items) > mx:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED", "message": f"Massimo {mx} media per batch"})
    doc = await resolve_model(body.model)
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
    await log_action(principal, request, "media.upload_batch", {"model": body.model, "count": len(body.items)}, s, not errors, _target(doc), [{"field": r["slot"], "before": None, "after": r["url"]} for r in results], started=t0)
    return envelope("media.upload_batch", request, s, {"uploaded": results, "errors": errors, "validation": v, "progress": {"total": len(body.items), "done": len(results), "failed": len(errors)}},
                    [str(e["error"]) for e in errors], _steps_for(v, doc), ok=not errors)


# =====================================================================
# SEO
# =====================================================================
async def _audit(scope: Optional[str], model_ref: Optional[str]):
    from v1_seo import run_audit
    entity = None
    doc = None
    if model_ref:
        doc = await resolve_model(model_ref, include_deleted=True)
        entity = doc["id"]
    res = await run_audit("models" if model_ref else scope, entity)
    return res, entity, doc


@ai_router.post("/seo/audit", operation_id="runSeoAudit", summary="Audit SEO (tutto o una modella)")
async def ai_seo_audit(body: AISeo = AISeo(), request: Request = None, principal=Depends(ai_guard("seo:audit"))):
    t0 = time.time()
    res, entity, doc = await _audit(body.scope, body.model)
    c = res["counts"]
    issues = await seo_issues_col.find({"status": "open", **({"entity_id": entity} if entity else {})}, {"_id": 0, "code": 1, "severity": 1, "entity_label": 1, "message": 1, "id": 1, "field": 1, "suggested_value": 1}).sort("severity", 1).to_list(80)
    score = await _seo_score(entity)
    s = (f"Audit SEO{(' di ' + doc.get('nome_artistico')) if doc else ''}: {res['total']} issue (SAFE {c['SAFE_AUTO_FIX']} correggibili in automatico, REVIEW {c['REVIEW_REQUIRED']} da approvare, CRITICAL {c['CRITICAL']} manuali). SEO score {score}/100.")
    await log_action(principal, request, "seo.audit", body.model_dump(), s, True, _target(doc) if doc else None, started=t0)
    steps = []
    if c["SAFE_AUTO_FIX"]:
        steps.append((f"POST /api/v1/ai/models/{doc['slug']}/seo/apply-safe-fixes" if doc else "POST /api/v1/ai/seo/apply-safe-fixes") + " per correggere le SAFE")
    if c["REVIEW_REQUIRED"]:
        steps.append((f"GET /api/v1/ai/models/{doc['slug']}/seo/review" if doc else "GET /api/v1/seo/issues?severity=REVIEW_REQUIRED") + " per preparare le REVIEW")
    if c["CRITICAL"]:
        steps.append("Le CRITICAL richiedono intervento umano (link OnlyFans, pubblicazioni incomplete, slug)")
    return envelope("seo.audit", request, s, {**res, "seo_score": score, "issues": issues, "review_required": [i for i in issues if i["severity"] == "REVIEW_REQUIRED"], "critical": [i for i in issues if i["severity"] == "CRITICAL"]}, next_steps=steps)


async def _safe_fix(request: Request, principal: dict, scope: Optional[str], model_ref: Optional[str], dry_run: bool, t0: float):
    from v1_seo import apply_safe_fixes
    res, entity, doc = await _audit(scope, model_ref)
    before = await _seo_score(entity)
    counts_before = res["counts"]
    fx = await apply_safe_fixes(actor_of(principal), request_id_of(request), "models" if model_ref else scope, entity, dry_run, source="chatgpt" if principal.get("type") == "api_key" else "ai")
    if dry_run:
        s = f"[dry-run] {fx['would_fix']} fix SEO sicuri applicabili{(' a ' + doc.get('nome_artistico')) if doc else ''}; {counts_before['REVIEW_REQUIRED']} REVIEW e {counts_before['CRITICAL']} CRITICAL resterebbero intatte. Score attuale {before}."
        return envelope("seo.apply_safe_fixes", request, s, {**fx, "seo_score_before": before, "counts": counts_before, "approval_required": False})
    res2, _, _ = await _audit(scope, model_ref)
    after = await _seo_score(entity)
    applied = [r for r in fx["results"] if r.get("applied")]
    s = (f"SEO{(' ' + doc.get('nome_artistico')) if doc else ''}: {res['total']} problemi trovati, {len(applied)} risolti automaticamente, {res2['counts']['REVIEW_REQUIRED']} richiedono approvazione, {res2['counts']['CRITICAL']} critici (manuali). SEO score {before} → {after}.")
    changes = [{"field": a.get("field"), "entity": a.get("entity"), "code": a.get("code"), "version_id": a.get("version_id")} for a in applied]
    await log_action(principal, request, "seo.apply_safe_fixes", {"scope": scope, "model": model_ref}, s, True, _target(doc) if doc else None, changes, [a.get("version_id") for a in applied], t0)
    return envelope("seo.apply_safe_fixes", request, s, {"found": res["total"], "fixed": len(applied), "skipped": fx["skipped"], "review_required": res2["counts"]["REVIEW_REQUIRED"], "critical": res2["counts"]["CRITICAL"],
                                                          "seo_score_before": before, "seo_score_after": after, "fixes": applied[:100]},
                    [r["reason"] for r in fx["results"] if not r.get("applied") and "rollback" in str(r.get("reason", "")).lower()],
                    ["Annulla un fix: POST /api/v1/ai/rollback {version_id}", (f"Prepara le REVIEW: GET /api/v1/ai/models/{doc['slug']}/seo/review" if doc else "Rivedi le REVIEW: GET /api/v1/seo/issues?severity=REVIEW_REQUIRED")], changes=changes)


@ai_router.post("/seo/apply-safe-fixes", operation_id="applySafeSeoFixes", summary="Applica SOLO i fix SEO SAFE_AUTO_FIX (versionati, reversibili)")
async def ai_seo_fix(body: AISeo = AISeo(), request: Request = None, principal=Depends(ai_guard("seo:safe_fix", write=True))):
    return await _safe_fix(request, principal, body.scope, body.model, body.dry_run, time.time())


@ai_router.post("/models/{reference}/seo/apply-safe-fixes", operation_id="applySafeSeoFixesForModel", summary="Fix SEO sicuri di una modella")
async def ai_seo_fix_model(reference: str, request: Request, dry_run: bool = False, principal=Depends(ai_guard("seo:safe_fix", write=True))):
    return await _safe_fix(request, principal, "models", reference, dry_run, time.time())


@ai_router.get("/models/{reference}/seo/review", operation_id="listSeoReviewIssues", summary="Issue SEO che richiedono approvazione")
async def ai_seo_review_list(reference: str, request: Request, principal=Depends(ai_guard("seo:review_prepare"))):
    doc = await resolve_model(reference, include_deleted=True)
    await _audit("models", reference)
    items = await seo_issues_col.find({"entity_id": doc["id"], "status": "open", "severity": {"$in": ["REVIEW_REQUIRED", "CRITICAL"]}}, {"_id": 0}).to_list(100)
    from v1_seo import issue_impact
    for i in items:
        i.update(issue_impact(i))
    s = f"{doc.get('nome_artistico')}: {len([i for i in items if i['severity'] == 'REVIEW_REQUIRED'])} issue da approvare, {len([i for i in items if i['severity'] == 'CRITICAL'])} critiche (solo manuali)."
    return envelope("seo.review_list", request, s, {"items": items}, next_steps=[f"POST /api/v1/ai/models/{doc['slug']}/seo/review/{{issue_id}}/preview per preparare una singola issue"])


class ReviewBody(BaseModel):
    proposed_value: Optional[Any] = None
    reason: Optional[str] = ""


@ai_router.post("/models/{reference}/seo/review/{issue_id}/preview", operation_id="prepareSeoReview", summary="Prepara una issue REVIEW: anteprima + token di approvazione")
async def ai_seo_review_preview(reference: str, issue_id: str, request: Request, body: ReviewBody = ReviewBody(), principal=Depends(ai_guard("seo:review_prepare"))):
    t0 = time.time()
    doc = await resolve_model(reference, include_deleted=True)
    issue = await seo_issues_col.find_one({"id": issue_id, "entity_id": doc["id"]}, {"_id": 0})
    if not issue:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Issue non trovata per questa modella"})
    if issue["status"] != "open":
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": f"Issue già {issue['status']}"})
    from v1_seo import issue_impact
    impact = issue_impact(issue)
    if issue["severity"] == "CRITICAL":
        bump("critical_blocked")
        return envelope("seo.review_preview", request, f"Issue CRITICAL ({issue['code']}): non può essere applicata tramite ChatGPT, serve intervento manuale.", {"issue": issue, **impact}, ok=False, code="CRITICAL_ACTION_BLOCKED")
    field = issue.get("field") or ""
    cur = doc
    for part in field.split("."):
        cur = (cur or {}).get(part) if isinstance(cur, dict) else None
    proposed = body.proposed_value if body.proposed_value is not None else issue.get("suggested_value")
    if issue["severity"] == "SAFE_AUTO_FIX":
        return envelope("seo.review_preview", request, f"Issue SAFE ({issue['code']}): non serve approvazione, usa apply-safe-fixes.", {"issue": issue, "current_value": cur, "proposed_value": proposed, **impact}, next_steps=[f"POST /api/v1/ai/models/{doc['slug']}/seo/apply-safe-fixes"])
    if proposed is None or "[" in field:
        return envelope("seo.review_preview", request, f"Issue {issue['code']}: nessun valore proposto automaticamente; fornisci proposed_value per preparare l'approvazione.", {"issue": issue, "current_value": cur, "proposed_value": None, **impact}, ok=True)
    cfg = await ai_config()
    if not cfg["approval_enabled"]:
        raise HTTPException(status_code=403, detail={"code": "APPROVAL_DISABLED", "message": "Flusso di approvazione disattivato"})
    appr = await create_approval("SEO_REVIEW", actor_of(principal), _target(doc), {"issue_id": issue_id, "model_id": doc["id"], "field": field, "value": proposed}, cur, proposed,
                                 body.reason or issue.get("message", ""), request_id_of(request))
    s = f"Anteprima {issue['code']} per {doc.get('nome_artistico')}: {field} '{str(cur)[:60]}' → '{str(proposed)[:60]}'. In attesa di approvazione."
    await log_action(principal, request, "seo.review_preview", {"model": reference, "issue_id": issue_id}, s, True, _target(doc), [{"field": field, "before": cur, "after": proposed}], started=t0, before=cur, after=proposed)
    return envelope("seo.review_preview", request, s, {"issue": issue, "current_value": cur, "proposed_value": proposed, **impact}, changes=[{"field": field, "before": cur, "after": proposed}], approval=appr,
                    next_steps=["Se l'utente approva: POST /api/v1/ai/approvals/confirm {token}"])


# =====================================================================
# APPROVALS
# =====================================================================
@ai_router.get("/approvals", operation_id="listPendingApprovals", summary="Approvazioni in attesa")
async def ai_approvals(request: Request, principal=Depends(ai_guard("ai:execute"))):
    items = await list_pending_approvals(actor_of(principal) if principal.get("type") == "api_key" else None)
    return envelope("approvals.list", request, f"{len(items)} approvazioni in attesa", {"items": items})


@ai_router.post("/approvals/confirm", operation_id="confirmApproval", summary="Conferma un'approvazione (token single-use) ed esegue la modifica")
async def ai_confirm(body: AIConfirm, request: Request, principal=Depends(ai_guard("ai:execute", write=True, dry_capable=False))):
    t0 = time.time()
    appr = await consume_approval(body.token, actor_of(principal))
    kind, payload = appr["type"], appr["payload"]
    bump("approvals_confirmed")
    if kind == "CAPABILITY":
        # Phase 12A: proposal prepared by the universal dispatcher -> re-run the SAME capability with approved=True
        # (scopes, READ_ONLY, CRITICAL, target etag and idempotency are re-checked by run_capability itself)
        from v1_capabilities import execute_approved_capability
        res = await execute_approved_capability(appr, principal, request)
        res["data"]["approval_id"] = appr["id"]
        return res
    if kind == "MODEL_UPDATE":
        doc = await models_col.find_one({"id": payload["model_id"]}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Modella non trovata"})
        if not has_scope(principal, "models:update"):
            raise HTTPException(status_code=403, detail={"code": "INSUFFICIENT_SCOPE", "message": "Serve models:update", "missing_scopes": ["models:update"]})
        out = await patch_model(doc, payload["changes"], _p(principal), request, body.reason or appr.get("reason") or "Modifica approvata", expected_updated_at=payload.get("expected_updated_at"))
        ch = _changes_from(appr.get("before") or {}, appr.get("after") or {}, out["changed_fields"])
        s = f"Approvazione confermata: {out['nome_artistico']} aggiornata ({', '.join(out['changed_fields'])})."
        await log_action(principal, request, "approvals.confirm", {"type": kind, "approval_id": appr["id"]}, s, True, appr["target"], ch, [out.get("version_id")], t0)
        return envelope("approvals.confirm", request, s, {"id": out["id"], "slug": out["slug"], "version_id": out.get("version_id"), "workflow_status": out["workflow_status"], "etag": out.get("etag")}, changes=ch, next_steps=[f"Annulla: POST /api/v1/ai/rollback {{version_id:'{out.get('version_id')}'}}"])
    if kind == "SEO_REVIEW":
        from v1_seo import apply_issue_fix
        issue = await seo_issues_col.find_one({"id": payload["issue_id"]}, {"_id": 0})
        if not issue or issue["status"] != "open":
            raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "Issue non più aperta"})
        if not has_scope(principal, "seo:review_prepare"):
            raise HTTPException(status_code=403, detail={"code": "INSUFFICIENT_SCOPE", "message": "Serve seo:review_prepare", "missing_scopes": ["seo:review_prepare"]})
        issue["fix"] = {"set": {payload["field"]: payload["value"]}}
        r = await apply_issue_fix(issue, actor_of(principal), request_id_of(request), source="chatgpt" if principal.get("type") == "api_key" else "ai", apply_review=True)
        ch = [{"field": payload["field"], "before": appr.get("before"), "after": payload["value"]}]
        s = f"Approvazione confermata: fix {issue['code']} applicato." if r.get("applied") else f"Fix non applicato: {r.get('reason')}"
        await log_action(principal, request, "approvals.confirm", {"type": kind, "approval_id": appr["id"]}, s, bool(r.get("applied")), appr["target"], ch, [r.get("version_id")] if r.get("version_id") else [], t0)
        return envelope("approvals.confirm", request, s, r, changes=ch if r.get("applied") else [], ok=bool(r.get("applied")))
    if kind == "LANDING_PUBLISH":
        from v1_landings import resolve_landing, set_landing_state
        if not has_scope(principal, "landing:publish"):
            raise HTTPException(status_code=403, detail={"code": "INSUFFICIENT_SCOPE", "message": "Serve landing:publish (concesso solo dall'amministratore)", "missing_scopes": ["landing:publish"]})
        out = await set_landing_state(await resolve_landing(payload["landing_id"]), "pubblicata", _p(principal), request)
        s = f"Landing '{out['titolo']}' pubblicata (dati; rotta pubblica dietro flag)."
        await log_action(principal, request, "approvals.confirm", {"type": kind}, s, True, {"type": "landing", "id": out["id"], "slug": out["slug"]}, [{"field": "stato", "before": "bozza", "after": "pubblicata"}], [out.get("version_id")], t0)
        return envelope("approvals.confirm", request, s, out, changes=[{"field": "stato", "before": "bozza", "after": "pubblicata"}])
    raise HTTPException(status_code=400, detail={"code": "APPROVAL_INVALID", "message": f"Tipo approvazione sconosciuto: {kind}"})


# =====================================================================
# LANDINGS
# =====================================================================
async def _landing_out(doc: dict) -> dict:
    from v1_landings import _enrich, validate_landing_full
    out = _enrich(doc)
    out["full_validation"] = await validate_landing_full(doc)
    return out


def build_landing_data(body: "AILandingCreate", slugs: List[str], names: List[str]) -> dict:
    """Single source of truth for the landing payload built from an AI request (shared with the Phase 12A dispatcher)."""
    titolo = body.titolo or body.h1 or body.title or (f"Il Lato Segreto di {names[0]}" if names else "Landing")
    headline = body.h1 or body.hero_text or titolo
    return {
        "titolo": titolo, "slug": body.slug or "", "headline": headline, "subtitle": (body.hero_text if body.h1 else body.intro) or "",
        "intro": body.intro or "", "model_slugs": slugs,
        "cta": {"testo": body.cta_text or "SCOPRI IL LATO SEGRETO", "url": body.cta_url or (f"/modelle/{slugs[0]}" if slugs else "/"), "stile": "gold", "posizione": "hero"},
        "faq": body.faq or [],
        "seo": {"title": body.title or f"{titolo} | LATO SEGRETO", "meta_description": body.meta_description or "", "canonical": body.canonical or "", "robots": "noindex,nofollow" if body.noindex else "index,follow",
                "og_image": "", "structured_data_type": "WebPage", "keywords": body.keywords or [], "topics": body.topics or [], "indexable": not body.noindex, "locale": "it-IT"},
        "analytics": {"campaign": f"landing-{(body.slug or titolo)}", "utm_source": "", "goal_event": "onlyfans_click"},
        "targeting": {"editorial_location": body.location_targeting or "Italia", "geoblocking": False, "note": "Solo personalizzazione editoriale/SEO: nessun blocco geografico"},
        "stato": "bozza", "reason": body.reason or "Landing creata via ChatGPT",
    }


@ai_router.post("/landings", operation_id="createLanding", summary="Crea una landing (bozza) per una o più modelle")
async def ai_landings_create(body: AILandingCreate, request: Request, principal=Depends(ai_guard("landing:create", write=True))):
    t0 = time.time()
    from v1_landings import create_landing, validate_landing_full
    refs = body.models or ([body.model] if body.model else [])
    slugs, names = [], []
    for r in refs:
        d = await resolve_model(r)
        slugs.append(d["slug"])
        names.append(d.get("nome_artistico") or d.get("nome"))
    data = build_landing_data(body, slugs, names)
    titolo = data["titolo"]
    if body.dry_run:
        fv = await validate_landing_full({**data, "id": None})
        return envelope("landing.create", request, f"[dry-run] Landing '{titolo}' per {', '.join(names) or 'nessuna modella'}: score {fv['score']}, {len(fv['errors'])} errori, {len(fv['warnings'])} avvisi.", {"dry_run": True, "proposed_after": data, "full_validation": fv})
    out = await create_landing(data, _p(principal), request)
    out = await _landing_out(await landings_col.find_one({"id": out["id"]}, {"_id": 0}))
    fv = out["full_validation"]
    s = f"Landing '{out['titolo']}' creata in bozza (/l/{out['slug']}) per {', '.join(names) or 'nessuna modella'}; validazione {fv['score']}/100, {len(fv['errors'])} errori."
    await log_action(principal, request, "landing.create", body.model_dump(), s, True, {"type": "landing", "id": out["id"], "slug": out["slug"]}, [{"field": "landing", "before": None, "after": out["slug"]}], started=t0)
    return envelope("landing.create", request, s, out, [w["message"] for w in fv["warnings"]],
                    [f"Valida: POST /api/v1/ai/landings/{out['slug']}/validate", "La rotta pubblica /l/{slug} resta OFF (flag public_landing_routes) fino alla fase successiva"], changes=[{"field": "landing", "before": None, "after": out["slug"]}])


@ai_router.get("/landings/{reference}", operation_id="getLanding", summary="Dettaglio landing")
async def ai_landing_get(reference: str, request: Request, principal=Depends(ai_guard("landing:read"))):
    from v1_landings import resolve_landing
    out = await _landing_out(await resolve_landing(reference))
    return envelope("landing.get", request, f"Landing '{out['titolo']}' ({out['workflow_status']})", out)


@ai_router.post("/landings/{reference}/validate", operation_id="validateLanding", summary="Validazione pre-pubblicazione landing")
async def ai_landing_validate(reference: str, request: Request, principal=Depends(ai_guard("landing:validate"))):
    from v1_landings import resolve_landing, validate_landing_full
    doc = await resolve_landing(reference)
    fv = await validate_landing_full(doc)
    s = f"Landing '{doc['titolo']}': {'pubblicabile' if fv['publishable'] else 'NON pubblicabile'} (score {fv['score']}/100, {len(fv['errors'])} errori, {len(fv['warnings'])} avvisi)."
    return envelope("landing.validate", request, s, {"id": doc["id"], "slug": doc["slug"], **fv}, [w["message"] for w in fv["warnings"]],
                    ([f"Pubblica: POST /api/v1/ai/landings/{doc['slug']}/publish (richiede scope landing:publish)"] if fv["publishable"] else []))


@ai_router.post("/landings/{reference}/publish", operation_id="publishLanding", summary="Pubblica landing (scope landing:publish, altrimenti approvazione)")
async def ai_landing_publish(reference: str, request: Request, dry_run: bool = False, principal=Depends(ai_guard("landing:read", write=True))):
    t0 = time.time()
    from v1_landings import resolve_landing, validate_landing_full, set_landing_state
    doc = await resolve_landing(reference)
    fv = await validate_landing_full(doc)
    if not fv["publishable"]:
        return envelope("landing.publish", request, f"Landing '{doc['titolo']}' non pubblicabile: " + "; ".join(e["message"] for e in fv["errors"]), {"validation": fv}, ok=False, code="PUBLICATION_BLOCKED")
    if dry_run:
        return envelope("landing.publish", request, f"[dry-run] Landing '{doc['titolo']}' pubblicabile.", {"dry_run": True, "validation": fv}, changes=[{"field": "stato", "before": doc.get("stato"), "after": "pubblicata"}])
    if not has_scope(principal, "landing:publish"):
        cfg = await ai_config()
        if not cfg["approval_enabled"]:
            raise HTTPException(status_code=403, detail={"code": "INSUFFICIENT_SCOPE", "message": "Serve landing:publish", "missing_scopes": ["landing:publish"]})
        appr = await create_approval("LANDING_PUBLISH", actor_of(principal), {"type": "landing", "id": doc["id"], "slug": doc["slug"]}, {"landing_id": doc["id"]}, {"stato": doc.get("stato")}, {"stato": "pubblicata"}, "Pubblicazione landing senza scope landing:publish", request_id_of(request))
        return envelope("landing.publish", request, f"Pubblicazione di '{doc['titolo']}' preparata: richiede approvazione (scope landing:publish non concesso).", {"validation": fv}, approval=appr, changes=[{"field": "stato", "before": doc.get("stato"), "after": "pubblicata"}])
    out = await set_landing_state(doc, "pubblicata", _p(principal), request)
    s = f"Landing '{out['titolo']}' pubblicata (dati). La rotta pubblica resta dietro flag."
    await log_action(principal, request, "landing.publish", {"landing": reference}, s, True, {"type": "landing", "id": out["id"], "slug": out["slug"]}, [{"field": "stato", "before": doc.get("stato"), "after": "pubblicata"}], [out.get("version_id")], t0)
    return envelope("landing.publish", request, s, out, changes=[{"field": "stato", "before": doc.get("stato"), "after": "pubblicata"}])


@ai_router.post("/landing/create", operation_id="createLandingLegacy", summary="(compat Phase 9) Crea landing con body LandingIn")
async def ai_landing_create(body: AILanding, request: Request, principal=Depends(ai_guard("landing:create", write=True))):
    from v1_landings import create_landing
    data = body.model_dump()
    publish = data.pop("publish", False)
    data.pop("landing", None); data.pop("changes", None); dry = data.pop("dry_run", False)
    if not data.get("titolo"):
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED", "message": "titolo obbligatorio"})
    if dry:
        return envelope("landing.create", request, f"[dry-run] Landing '{data['titolo']}' verrebbe creata in bozza.", {"dry_run": True, "proposed_after": data})
    out = await create_landing(data, _p(principal), request)
    s = f"Landing '{out['titolo']}' creata ({out['workflow_status']}) su {out['public_url']}."
    await log_action(principal, request, "landing.create", {"titolo": data.get("titolo")}, s, True, {"type": "landing", "id": out["id"], "slug": out["slug"]})
    warnings = [w["message"] for w in out["validation"]["warnings"]]
    if publish:
        warnings.append("publish ignorato: usa POST /api/v1/ai/landings/{slug}/publish (scope landing:publish o approvazione)")
    return envelope("landing.create", request, s, out, warnings, changes=[{"field": "landing", "before": None, "after": out["slug"]}])


@ai_router.post("/landing/update", operation_id="updateLanding", summary="Aggiorna landing (deep-merge, dry_run)")
async def ai_landing_update(body: AILanding, request: Request, principal=Depends(ai_guard("landing:update", write=True))):
    t0 = time.time()
    from v1_landings import resolve_landing, patch_landing, _enrich
    if not body.landing:
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED", "message": "'landing' (id|slug|titolo) obbligatorio"})
    doc = await resolve_landing(body.landing)
    if not body.changes:
        return envelope("landing.update", request, "Nessuna modifica richiesta.", await _landing_out(doc))
    if body.dry_run:
        from v1_models import deep_merge
        from v1_versioning import diff_fields
        merged = deep_merge(doc, {k: v for k, v in body.changes.items() if k != "stato"})
        ch = diff_fields(serialize_doc(doc), serialize_doc(merged))
        return envelope("landing.update", request, f"[dry-run] Landing '{doc['titolo']}': {len(ch)} campi cambierebbero.", {"dry_run": True, "changed_fields": ch, "before": {k: doc.get(k) for k in ch}, "proposed_after": {k: merged.get(k) for k in ch}}, changes=_changes_from(doc, merged, ch))
    changes = {k: v for k, v in body.changes.items() if k != "stato"}
    out = await patch_landing(doc, changes, _p(principal), request, "Aggiornamento via ChatGPT")
    ch = _changes_from(doc, out, out.get("changed_fields", []))
    s = f"Landing '{out['titolo']}' aggiornata ({', '.join(out.get('changed_fields', []))})."
    await log_action(principal, request, "landing.update", {"landing": body.landing, "changes": changes}, s, True, {"type": "landing", "id": out["id"], "slug": out["slug"]}, ch, [out.get("version_id")], t0)
    return envelope("landing.update", request, s, out, changes=ch, warnings=(["publish ignorato: usa POST /api/v1/ai/landings/{slug}/publish"] if body.publish else []))


# =====================================================================
# ANALYTICS (natural + structured)
# =====================================================================
PERIODS = {"24h": "1g", "today": "oggi", "oggi": "oggi", "7d": "7g", "7g": "7g", "30d": "30g", "30g": "30g", "1d": "1g", "1g": "1g", "yesterday": "ieri", "ieri": "ieri"}
METRICS = {
    "visits": ("model_view", None), "model_views": ("model_view", None), "sessions": ("visit", None), "secret_opens": ("secret_side_open", None),
    "cta_views": ("cta_view", None), "cta_clicks": ("cta_click", None), "onlyfans_clicks": ("onlyfans_click", None),
    "onlyfans_ctr": ("onlyfans_click", "model_view"), "conversion_rate": ("onlyfans_click", "model_view"), "ctr": ("cta_click", "model_view"),
    "activation_rate": ("secret_side_open", "model_view"), "secret_activation_rate": ("secret_side_open", "model_view"), "cta_view_rate": ("cta_view", "model_view"),
}
GROUPS = {"model": "model_id", "country": "geo.country", "region": "geo.region", "city": "geo.city", "device": "device", "source": "source", "day": None, "none": None, None: None}
MIN_SAMPLE = 20


def _period(body: AIQuery) -> str:
    return PERIODS.get((body.period or body.range or "30g").lower(), body.range or "30g")


async def _structured(body: AIQuery, match: dict) -> dict:
    metric = (body.metric or "onlyfans_ctr").lower()
    if metric not in METRICS:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_FAILED", "message": f"Metrica sconosciuta '{metric}'", "allowed": list(METRICS.keys())})
    num_ev, den_ev = METRICS[metric]
    group = (body.group_by or "none").lower()
    if group not in GROUPS:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_FAILED", "message": f"group_by sconosciuto '{group}'", "allowed": [g for g in GROUPS if g]})
    field = GROUPS[group]
    if body.model:
        match = {**match, "model_id": (await resolve_model(body.model, include_deleted=True))["id"]}
    async def agg(ev):
        m = _ev_match(match, ev) if ev != "visit" else match
        if group == "day":
            pipeline = [{"$match": m}, {"$group": {"_id": {"$substr": ["$timestamp", 0, 10]}, "n": {"$sum": 1}, "s": {"$addToSet": "$session_id"}}}]
        elif field:
            pipeline = [{"$match": m}, {"$group": {"_id": f"${field}", "n": {"$sum": 1}, "s": {"$addToSet": "$session_id"}}}]
        else:
            pipeline = [{"$match": m}, {"$group": {"_id": None, "n": {"$sum": 1}, "s": {"$addToSet": "$session_id"}}}]
        out = {}
        async for r in events_col.aggregate(pipeline + [{"$project": {"n": 1, "s": {"$size": "$s"}}}]):
            out[r["_id"] if r["_id"] is not None else "all"] = (r["s"] if ev == "visit" else r["n"], r["s"])
        return out
    num = await agg(num_ev)
    den = await agg(den_ev) if den_ev else None
    keys = set(num) | (set(den) if den else set())
    rows = []
    names = {}
    if group == "model":
        names = {m["id"]: m.get("nome_artistico") for m in await models_col.find({}, {"_id": 0, "id": 1, "nome_artistico": 1}).to_list(2000)}
    for k in keys:
        n, s = num.get(k, (0, 0))
        d = den.get(k, (0, 0))[0] if den else None
        val = round(n / d * 100, 2) if den and d else (n if not den else None)
        rows.append({"key": k if k != "all" else "all", "label": names.get(k, k) if group == "model" else (k or "unknown"), "value": val, "numerator": n, "denominator": d, "sessions": s,
                     "sample_size": d if den else n, "reliable": (d if den else n) >= MIN_SAMPLE, "data_available": val is not None})
    rows = [r for r in rows if r["key"] not in (None, "")]
    rows.sort(key=lambda r: ((r["value"] if r["value"] is not None else -1), r["sample_size"]), reverse=(body.sort != "asc"))
    total_sample = sum(r["sample_size"] for r in rows)
    limitations = []
    if total_sample < MIN_SAMPLE:
        limitations.append(f"Campione totale {total_sample} < {MIN_SAMPLE}: percentuali non affidabili")
    if any(not r["reliable"] for r in rows):
        limitations.append("Alcune righe hanno campione ridotto (reliable=false)")
    unknown_geo = await events_col.count_documents({**match, "geo.country": "UNKNOWN"})
    if unknown_geo and (body.country or group in ("country", "region", "city")):
        limitations.append(f"{unknown_geo} eventi senza geolocalizzazione (header geo assenti)")
    return {"metric": metric, "definition": f"{num_ev}" + (f" / {den_ev} × 100" if den_ev else " (conteggio)"), "group_by": group, "period": _period(body), "filters": {k: v for k, v in match.items() if k != "timestamp"},
            "items": rows[:body.limit], "sample_size": total_sample, "data_available": total_sample > 0, "limitations": limitations}


@ai_router.post("/analytics/query", operation_id="queryAnalytics", summary="Analytics: domanda testuale o query strutturata (metric/group_by/period/country)")
async def ai_query(body: AIQuery, request: Request, principal=Depends(ai_guard("analytics:read"))):
    rng = _period(body)
    match = build_match(rng, body.country, body.region, None, body.device, body.source)
    base = {"period": rng, "filters": {k: v for k, v in match.items() if k != "timestamp"}}
    if body.metric:
        d = await _structured(body, match)
        top = d["items"][0] if d["items"] else None
        s = (f"{d['metric']} per {d['group_by']} ({rng}): " + (f"in testa {top['label']} con {top['value']}{'%' if d['definition'].endswith('100') else ''} (campione {top['sample_size']})" if top and top["value"] is not None else "dati insufficienti") + ("; " + "; ".join(d["limitations"]) if d["limitations"] else "") + ".")
        return envelope("analytics.structured", request, s, d)
    q = (body.question or "overview").lower().strip()
    def pick(metric, group=None, sort="desc"):
        return AIQuery(metric=metric, group_by=group, model=body.model, period=body.period, range=body.range, country=body.country, region=body.region, device=body.device, source=body.source, sort=sort, limit=body.limit)
    if ("ital" in q and "region" in q) or "regione" in q or "regioni" in q:
        d = await _structured(pick("visits", "region"), {**match, "geo.country": "IT"})
        return envelope("analytics.italian_regions", request, f"Traffico italiano per regione ({rng}): " + (", ".join(f"{r['label']} {r['numerator']}" for r in d["items"][:5]) or "nessun dato regionale (header geo assenti)") + ".", d)
    if "ital" in q or q == "italian_traffic":
        from v1_tracking import italy
        d = await italy(match, principal)
        d["period"] = rng
        d["data_available"] = d["model_views_total"] > 0
        d["limitations"] = ([f"{d['unknown_geo']} profili visti senza geo"] if d["unknown_geo"] else []) + (["Campione ridotto"] if d["model_views_total"] < MIN_SAMPLE else [])
        s = f"Traffico italiano ({rng}): {d['model_views_italy']} profili visti su {d['model_views_total']} ({d['italian_share']}%), {d['funnel_italy']['steps'][4]['value']} click OnlyFans, conversione {d['funnel_italy']['conversion_rate']}%." if d["data_available"] else f"Nessun dato di traffico nel periodo {rng}."
        return envelope("analytics.italian_traffic", request, s, d)
    if "ctr" in q and "cta" in q or "ctr più alto" in q or "ctr piu alto" in q or q == "highest_ctr":
        d = await _structured(pick("ctr", "model"), match)
        top = next((r for r in d["items"] if r["reliable"]), d["items"][0] if d["items"] else None)
        return envelope("analytics.highest_ctr", request, (f"CTR più alto ({rng}): {top['label']} {top['value']}% (campione {top['sample_size']})" if top and top["value"] is not None else "Dati insufficienti per determinare il CTR") + ".", d)
    if "convert" in q or q in ("best_converting_model", "top_models", "converte meglio"):
        d = await _structured(pick("onlyfans_ctr", "model"), match)
        reliable = [r for r in d["items"] if r["reliable"] and r["numerator"] > 0]
        best = reliable[0] if reliable else None
        if best:
            s = f"Converte meglio {best['label']}: {best['value']}% ({best['numerator']} click OnlyFans su {best['denominator']} profili visti, {rng}{', Italia' if body.country == 'IT' else ''})."
        else:
            s = "Dati insufficienti per determinare un vincitore affidabile" + (f" (miglior candidato {d['items'][0]['label']} con campione {d['items'][0]['sample_size']})" if d["items"] and d["items"][0]["numerator"] > 0 else "") + "."
        return envelope("analytics.best_converting_model", request, s, {**d, "best": best, "data_available": best is not None})
    if "più visite" in q or "piu visite" in q or "most_visits" in q or "visite" in q and "modella" in q:
        d = await _structured(pick("visits", "model"), match)
        top = d["items"][0] if d["items"] else None
        return envelope("analytics.most_visited", request, (f"Più visite ({rng}): {top['label']} con {top['numerator']}" if top else "Nessuna visita nel periodo") + ".", d)
    if "mobile" in q or "desktop" in q or "device" in q or "dispositiv" in q:
        d = await _structured(pick("visits", "device"), match)
        return envelope("analytics.devices", request, f"Dispositivi ({rng}): " + (", ".join(f"{r['label']} {r['numerator']}" for r in d["items"]) or "nessun dato") + ".", d)
    if "sorgent" in q or "source" in q or "traffic_sources" in q:
        d = await _structured(pick("visits", "source"), match)
        of = await _structured(pick("onlyfans_clicks", "source"), match)
        return envelope("analytics.traffic_sources", request, f"Sorgenti ({rng}): " + (", ".join(f"{r['label']} {r['numerator']}" for r in d["items"][:6]) or "nessun dato") + ".", {"visits_by_source": d, "onlyfans_clicks_by_source": of})
    if "activation" in q or "attivazion" in q or "secret" in q or "segreto" in q:
        d = await _structured(pick("activation_rate", "model" if not body.model else "none"), match)
        return envelope("analytics.secret_activation", request, f"Secret activation rate ({rng}): " + (", ".join(f"{r['label']} {r['value']}%" for r in d["items"][:5] if r["value"] is not None) or "dati insufficienti") + ".", d)
    if "cta view" in q or "cta_view" in q:
        d = await _structured(pick("cta_view_rate", "model" if not body.model else "none"), match)
        return envelope("analytics.cta_view_rate", request, f"CTA view rate ({rng}): " + (", ".join(f"{r['label']} {r['value']}%" for r in d["items"][:5] if r["value"] is not None) or "dati insufficienti") + ".", d)
    if "funnel" in q or "drop" in q or "conversioni" in q or "conversion" in q:
        m = {**match, **({"model_id": (await resolve_model(body.model, include_deleted=True))["id"]} if body.model else {})}
        f = await funnel_for(m)
        drops = [{"from": f["steps"][i - 1]["step"], "to": s_["step"], "drop_off_percent": round(100 - s_["step_conversion"], 1)} for i, s_ in enumerate(f["steps"]) if i]
        worst = max(drops, key=lambda d_: d_["drop_off_percent"]) if drops and f["steps"][0]["value"] else None
        return envelope("analytics.funnel", request, (f"Funnel ({rng}): {f['steps'][0]['value']} sessioni → {f['steps'][4]['value']} click OnlyFans (conv. {f['conversion_rate']}%). Drop-off maggiore: {worst['from']}→{worst['to']} ({worst['drop_off_percent']}%)." if worst else f"Nessun dato nel periodo {rng}."),
                        {**base, **f, "drop_offs": drops, "sample_size": f["steps"][0]["value"], "data_available": f["steps"][0]["value"] > 0, "limitations": ["Campione ridotto"] if f["steps"][0]["value"] < MIN_SAMPLE else []})
    if body.model or q == "model_stats":
        if not body.model:
            raise HTTPException(status_code=422, detail={"code": "VALIDATION_FAILED", "message": "Specifica 'model'"})
        doc = await resolve_model(body.model, include_deleted=True)
        k = await model_kpis(doc["id"], match)
        s = f"{doc.get('nome_artistico')} ({rng}): {k['visits']} visite, attivazione {k['activation_rate']}%, {k['onlyfans_clicks']} click OnlyFans, conversione {k['conversion_rate']}%, traffico IT {k['italian_share']}%." if k["visits"] else f"{doc.get('nome_artistico')}: nessuna visita nel periodo {rng}."
        return envelope("analytics.model_stats", request, s, {**base, "model": _target(doc), **k, "sample_size": k["visits"], "data_available": k["visits"] > 0, "limitations": ["Campione ridotto"] if k["visits"] < MIN_SAMPLE else []})
    if "onlyfans" in q:
        from v1_tracking import onlyfans_funnel
        d = await onlyfans_funnel(match, principal)
        tot = sum(x["clicks"] for x in d["by_model"])
        return envelope("analytics.onlyfans", request, f"Click OnlyFans ({rng}): {tot} totali; {len(d['broken_links'])} link problematici.", {**base, **d, "sample_size": tot, "data_available": tot > 0})
    f = await funnel_for(match)
    it = await funnel_for({**match, "geo.country": "IT"})
    s = (f"Overview {rng}: {f['steps'][0]['value']} sessioni, {f['steps'][1]['value']} profili visti, {f['steps'][2]['value']} Lati Segreti, {f['steps'][4]['value']} click OnlyFans (conv. {f['conversion_rate']}%); Italia {it['steps'][1]['value']} profili visti." if f["steps"][0]["value"] else f"Nessun dato nel periodo {rng}.")
    return envelope("analytics.overview", request, s, {**base, "funnel": f, "italy": it, "sample_size": f["steps"][0]["value"], "data_available": f["steps"][0]["value"] > 0, "limitations": ["Campione ridotto"] if f["steps"][0]["value"] < MIN_SAMPLE else []})


# =====================================================================
# ROLLBACK
# =====================================================================
async def _locate_version(body: AIRollback) -> dict:
    if body.version_id:
        v = await versions_col.find_one({"id": body.version_id}, {"_id": 0})
        if not v:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Versione non trovata"})
        return v
    q: Dict[str, Any] = {"rolled_back": {"$ne": True}, "source": {"$ne": "rollback"}}
    ref = body.model or body.target
    if ref:
        doc = await resolve_model(ref, include_deleted=True)
        q.update({"entity": "model", "entity_id": doc["id"]})
    if body.request_id:
        q["request_id"] = body.request_id
    if body.actor:
        q["actor"] = body.actor
    elif body.latest_ai:
        q["source"] = {"$in": ["chatgpt", "ai", "autofix"]}
    v = await versions_col.find_one(q, {"_id": 0}, sort=[("timestamp", -1)])
    if not v:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Nessuna modifica trovata con questi criteri (già annullata o inesistente)"})
    return v


def _rollback_preview(v: dict) -> dict:
    from v1_versioning import diff_fields
    fields = v.get("changed_fields") or diff_fields(v.get("before"), v.get("after"))
    op = "soft_delete" if v.get("before") is None else ("restore" if v.get("after") is None else "restore_fields")
    return {"version_id": v["id"], "entity": v["entity"], "entity_id": v["entity_id"], "made_by": v.get("actor"), "source": v.get("source"), "reason": v.get("reason"), "at": v.get("timestamp"), "operation": op,
            "will_restore": {k: (v.get("before") or {}).get(k) for k in fields} if v.get("before") is not None else None, "current": {k: (v.get("after") or {}).get(k) for k in fields} if v.get("after") is not None else None,
            "changed_fields": fields, "already_rolled_back": bool(v.get("rolled_back"))}


@ai_router.post("/rollback/preview", operation_id="previewRollback", summary="Cosa verrebbe ripristinato (per version_id, o ultima modifica AI su una modella)")
async def ai_rollback_preview(body: AIRollback, request: Request, principal=Depends(ai_guard("rollback:read"))):
    v = await _locate_version(body)
    p = _rollback_preview(v)
    s = f"Rollback di {p['entity']} {p['entity_id'][:8]}… ({p['made_by']}, {p['source']}, {p['at'][:16]}): ripristinerebbe {', '.join(p['changed_fields'][:6]) or p['operation']}."
    return envelope("rollback.preview", request, s, p, ["Versione già annullata"] if p["already_rolled_back"] else [], [f"Esegui: POST /api/v1/ai/rollback {{version_id:'{v['id']}'}}"])


@ai_router.post("/rollback", operation_id="rollbackChange", summary="Esegue un rollback (nuovo evento audit, history intatta)")
async def ai_rollback(body: AIRollback, request: Request, principal=Depends(ai_guard("rollback:execute", write=True))):
    t0 = time.time()
    v = await _locate_version(body)
    p = _rollback_preview(v)
    if p["already_rolled_back"]:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "Versione già annullata"})
    if body.dry_run:
        return envelope("rollback", request, f"[dry-run] {p['operation']} su {p['entity']}: {', '.join(p['changed_fields'][:6])}.", {"dry_run": True, **p}, changes=[{"field": f, "before": (p["current"] or {}).get(f), "after": (p["will_restore"] or {}).get(f)} for f in p["changed_fields"]])
    from v1_versioning import rollback_version
    res = await rollback_version(v["id"], actor_of(principal), request_id_of(request), body.reason or "Rollback via ChatGPT")
    bump("rollbacks")
    ch = [{"field": f, "before": (p["current"] or {}).get(f), "after": (p["will_restore"] or {}).get(f)} for f in p["changed_fields"]]
    s = f"Rollback eseguito su {res['entity']} ({res['operation']}): ripristinati {', '.join(p['changed_fields'][:6]) or p['operation']}. Nuova versione {res['new_version_id']}."
    await log_action(principal, request, "rollback", body.model_dump(), s, True, {"type": res["entity"], "id": res["entity_id"]}, ch, [res["new_version_id"]], t0, rollback_ref=v["id"])
    try:
        from v1_config import emit_event
        await emit_event("version.rolled_back", {"version_id": v["id"], "actor": actor_of(principal), "request_id": request_id_of(request), **res})
    except Exception:
        pass
    return envelope("rollback", request, s, {**res, "preview": p}, changes=ch)


# =====================================================================
# STATUS / SITE HEALTH / SUMMARY / RECOMMENDATIONS
# =====================================================================
async def _models_by_status() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    async for d in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}):
        st = validate_model(d)["status"]
        counts[st] = counts.get(st, 0) + 1
    return counts



# ---------------- HEALTH: fresh + reconciled (Phase 11 fix) ----------------
HEALTH_FRESH_S = 600  # a stored health record older than this is re-run before being reported to ChatGPT


async def reconciled_health(max_age_s: int = HEALTH_FRESH_S) -> dict:
    """Return the latest health record; if stale (or missing) run the checks now WITHOUT self-healing writes.
    Running the checks also reconciles alerts (conditions that disappeared are resolved, history kept), so
    health_overall / alerts / recommendations always describe the CURRENT state, never a stale snapshot."""
    rec = await health_col.find_one({}, {"_id": 0}, sort=[("timestamp", -1)])
    fresh = False
    if rec:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(rec["timestamp"])).total_seconds()
        except Exception:
            age = max_age_s + 1
        fresh = age <= max_age_s
    if not fresh:
        from v1_health import run_health_checks
        rec = await run_health_checks(auto_fix=False)
        rec["refreshed_now"] = True
    rec = rec or {}
    rec["checked_at"] = rec.get("checked_at") or rec.get("timestamp")
    return rec


async def alerts_view(limit_open: int = 50, history_hours: int = 24) -> dict:
    """Current (open/acknowledged) alerts vs recently resolved ones, with timestamps so a client can tell them apart."""
    fields = {"_id": 0, "id": 1, "tipo": 1, "titolo": 1, "messaggio": 1, "severity": 1, "stato": 1, "current": 1, "source": 1, "occurrences": 1,
              "created_at": 1, "updated_at": 1, "checked_at": 1, "last_seen": 1, "resolved_at": 1, "resolved_by": 1, "dedupe_key": 1}
    open_ = await alerts_col.find({"stato": {"$in": ["open", "acknowledged"]}}, fields).sort("created_at", -1).to_list(limit_open)
    since = (datetime.now(timezone.utc) - timedelta(hours=history_hours)).isoformat()
    resolved = await alerts_col.find({"stato": "resolved", "resolved_at": {"$gte": since}}, fields).sort("resolved_at", -1).to_list(limit_open)
    for a in open_:
        a["current"] = True
    for a in resolved:
        a["current"] = False
    return {"open": open_, "open_critical": len([a for a in open_ if a.get("severity") == "critical"]), "resolved_recent": resolved, "history_window_hours": history_hours}


@ai_router.get("/status", operation_id="getSystemStatus", summary="Stato sistema (API, DB, health, alert, job, SEO, flag, permessi)")
async def ai_status(request: Request, principal=Depends(ai_guard("system:status"))):
    from database import db
    try:
        await db.command("ping")
        db_ok = True
    except Exception:
        db_ok = False
    hrec = await reconciled_health()
    health = {k: hrec.get(k) for k in ("overall", "timestamp", "checked_at", "actions", "refreshed_now")}
    alerts = await alerts_col.count_documents({"stato": {"$in": ["open", "acknowledged"]}})
    jobs = await jobs_col.find({}, {"_id": 0, "name": 1, "last_status": 1, "last_run": 1, "enabled": 1}).to_list(50)
    seo_counts = {}
    async for r in seo_issues_col.aggregate([{"$match": {"status": "open"}}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        seo_counts[r["_id"]] = r["n"]
    counts = await _models_by_status()
    cfg = await ai_config()
    s = f"API online, DB {'ok' if db_ok else 'KO'}, health {(health or {}).get('overall', 'n/d')}, {alerts} alert aperti, modelle {counts}, SEO aperte {seo_counts or 0}. ChatGPT API: {'ON' if cfg['enabled'] else 'OFF'} modalità {cfg['mode']}."
    return envelope("status", request, s, {"api": "online", "database": db_ok, "health": health, "open_alerts": alerts, "jobs": jobs, "seo_open": seo_counts, "models_by_status": counts,
                                             "ai": {"enabled": cfg["enabled"], "mode": cfg["mode"], "batch_enabled": cfg["batch_enabled"], "approval_flow": cfg["approval_enabled"]},
                                             "you": {"role": principal.get("role"), "scopes": principal.get("scopes"), "type": principal.get("type")}})


@ai_router.get("/site-health", operation_id="getSiteHealth", summary="Salute complessiva del sito")
async def ai_site_health(request: Request, principal=Depends(ai_guard("system:status"))):
    counts = await _models_by_status()
    health = await reconciled_health()
    checks = {c["name"]: c for c in health.get("checks", [])}
    av = await alerts_view()
    seo_counts = {"SAFE_AUTO_FIX": 0, "REVIEW_REQUIRED": 0, "CRITICAL": 0}
    async for r in seo_issues_col.aggregate([{"$match": {"status": "open"}}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        seo_counts[r["_id"]] = r["n"]
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    job_fail = await jobs_col.find({"last_status": "error"}, {"_id": 0, "name": 1, "last_error": 1}).to_list(20)
    wh_fail = await webhook_deliveries_col.count_documents({"ok": False, "created_at": {"$gte": since}})
    last_backup = await backups_col.find_one({}, {"_id": 0, "id": 1, "created_at": 1, "size": 1}, sort=[("created_at", -1)])
    alerts = av["open"]
    m = await metrics_snapshot_shared()
    total = sum(counts.values())
    data = {"models": {"total": total, "published": counts.get("PUBLISHED", 0), "draft": counts.get("DRAFT", 0), "incomplete": counts.get("INCOMPLETE", 0), "ready": counts.get("READY", 0), "error": counts.get("ERROR", 0), "archived": counts.get("ARCHIVED", 0)},
            "broken_media": (checks.get("media") or {}).get("missing", []), "seo_issues": sum(seo_counts.values()), "critical_issues": seo_counts["CRITICAL"], "safe_issues": seo_counts["SAFE_AUTO_FIX"], "review_issues": seo_counts["REVIEW_REQUIRED"],
            "sitemap_status": (checks.get("sitemap") or {}).get("detail"), "job_failures": job_fail, "webhook_failures_24h": wh_fail, "api_errors_last_hour": m["last_hour"]["errors"],
            "performance_alerts": [a for a in alerts if a.get("tipo") in ("traffic_anomaly", "conversion_anomaly")],
            "alerts": alerts, "alerts_open_critical": av["open_critical"], "alerts_resolved_recent": av["resolved_recent"],
            "onlyfans_links": {k: v for k, v in (checks.get("onlyfans_links") or {}).items() if k != "name"},
            "checks": [{"name": c["name"], "status": c["status"], "detail": c["detail"], "checked_at": c.get("checked_at") or health.get("checked_at")} for c in health.get("checks", [])],
            "backup_status": "ok" if last_backup and last_backup["created_at"] >= since else ("stale" if last_backup else "none"), "last_successful_backup": last_backup,
            "health_overall": health.get("overall"), "health_at": health.get("timestamp"), "health_checked_at": health.get("checked_at"), "health_refreshed_now": bool(health.get("refreshed_now")),
            "health_source": "checks correnti (alert risolti non influenzano lo stato)", "data_available": bool(health)}
    s = f"Sito: {total} modelle ({data['models']['published']} online, {data['models']['incomplete'] + data['models']['draft']} in lavorazione, {data['models']['error']} in errore); SEO {data['seo_issues']} issue ({seo_counts['CRITICAL']} critiche); health {health.get('overall', 'n/d')} (verificato {str(health.get('checked_at', ''))[11:16]} UTC); alert critici aperti {av['open_critical']}; {len(job_fail)} job in errore; backup {data['backup_status']}."
    return envelope("site_health", request, s, data)


async def build_daily_summary() -> dict:
    now = datetime.now(timezone.utc)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async def fun(start: datetime, end: Optional[datetime] = None, extra=None):
        m = {"timestamp": {"$gte": start.isoformat(), **({"$lt": end.isoformat()} if end else {})}, **(extra or {})}
        return await funnel_for(m)
    def cmp(a, b):
        if b is None or b == 0:
            return None
        return round((a - b) / b * 100, 1)
    def safe_cmp(a, b, min_n=MIN_SAMPLE):
        return cmp(a, b) if (a >= min_n or b >= min_n) else None
    today, yesterday = await fun(today0), await fun(today0 - timedelta(days=1), today0)
    it_today = await fun(today0, None, {"geo.country": "IT"})
    last7, prev7 = await fun(now - timedelta(days=7)), await fun(now - timedelta(days=14), now - timedelta(days=7))
    it7 = await fun(now - timedelta(days=7), None, {"geo.country": "IT"})
    v7, v_prev = last7["steps"][1]["value"], prev7["steps"][1]["value"]
    # per-model trend
    top, declining = [], []
    m7, mprev = build_match("7g"), {"timestamp": {"$gte": (now - timedelta(days=14)).isoformat(), "$lt": (now - timedelta(days=7)).isoformat()}}
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1, "nome_artistico": 1}):
        k = await model_kpis(m["id"], m7)
        kp = await model_kpis(m["id"], mprev)
        row = {**m, **{x: k[x] for x in ("visits", "onlyfans_clicks", "conversion_rate", "italian_share")}, "visits_prev7": kp["visits"], "trend_visits_percent": safe_cmp(k["visits"], kp["visits"])}
        top.append(row)
        if row["trend_visits_percent"] is not None and row["trend_visits_percent"] <= -30:
            declining.append(row)
    top.sort(key=lambda r: (r["onlyfans_clicks"], r["visits"]), reverse=True)
    since24 = (now - timedelta(hours=24)).isoformat()
    fixes = await versions_col.count_documents({"source": "autofix", "timestamp": {"$gte": since24}})
    chatgpt_changes = await versions_col.count_documents({"source": {"$in": ["chatgpt", "ai"]}, "timestamp": {"$gte": since24}})
    manual_changes = await versions_col.count_documents({"source": "manual", "timestamp": {"$gte": since24}})
    ai_actions = await ai_actions_col.count_documents({"timestamp": {"$gte": since24}})
    ai_errors = await ai_actions_col.count_documents({"timestamp": {"$gte": since24}, "ok": False})
    alerts_open = (await alerts_view(limit_open=10))["open"]
    seo_counts = {}
    async for r in seo_issues_col.aggregate([{"$match": {"status": "open"}}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        seo_counts[r["_id"]] = r["n"]
    health = await reconciled_health()
    media_issues = (next((c for c in health.get("checks", []) if c["name"] == "media"), {}) or {}).get("missing", [])
    jobs_err = await jobs_col.find({"last_status": "error"}, {"_id": 0, "name": 1}).to_list(20)
    new_landings = await landings_col.count_documents({"created_at": {"$gte": since24}})
    last_backup = await backups_col.find_one({}, {"_id": 0, "created_at": 1, "id": 1}, sort=[("created_at", -1)])
    counts = await _models_by_status()
    m = await metrics_snapshot_shared()
    tv, yv = today["steps"][1]["value"], yesterday["steps"][1]["value"]
    text = (f"Oggi: {today['steps'][0]['value']} sessioni, {tv} profili visti" + (f" ({'+' if cmp(tv, yv) >= 0 else ''}{cmp(tv, yv)}% vs ieri)" if safe_cmp(tv, yv) is not None else " (confronto con ieri non significativo)") +
            f", {today['steps'][4]['value']} click OnlyFans (CTR OF {today['conversion_rate']}%), Italia {round(it_today['steps'][1]['value'] / tv * 100, 1) if tv else 0}%. "
            f"Ultimi 7 giorni: {v7} profili visti" + (f" ({'+' if cmp(v7, v_prev) >= 0 else ''}{cmp(v7, v_prev)}% vs 7 precedenti)" if safe_cmp(v7, v_prev) is not None else "") + f", {last7['steps'][4]['value']} click OnlyFans, conv. {last7['conversion_rate']}%. "
            f"Top: {', '.join(t['nome_artistico'] for t in top[:3]) or 'n/d'}. In calo: {', '.join(d['nome_artistico'] for d in declining) or 'nessuna'}. "
            f"Modelle {counts}. SEO aperte {seo_counts or 'nessuna'}; media problematici {len(media_issues)}; alert {len(alerts_open)}; job in errore {len(jobs_err)}; errori API AI 1h {m['last_hour']['errors']}. "
            f"Nuove landing 24h: {new_landings}. Modifiche 24h: ChatGPT {chatgpt_changes}, manuali {manual_changes}, autofix {fixes}. Backup: {'ok ' + last_backup['created_at'][:16] if last_backup else 'nessuno'}.")
    return {"generated_at": now_iso(), "text": text,
            "today": {"funnel": today, "vs_yesterday_percent": {"model_views": safe_cmp(tv, yv), "onlyfans_clicks": safe_cmp(today["steps"][4]["value"], yesterday["steps"][4]["value"])}, "italy": it_today, "sample_size": today["steps"][0]["value"]},
            "last_7d": {"funnel": last7, "vs_previous_7d_percent": {"model_views": safe_cmp(v7, v_prev), "onlyfans_clicks": safe_cmp(last7["steps"][4]["value"], prev7["steps"][4]["value"])}, "italy": it7, "sample_size": last7["steps"][0]["value"]},
            "onlyfans_ctr": {"today": today["conversion_rate"], "last_7d": last7["conversion_rate"]}, "top_models_7d": top[:5], "declining_models": declining, "models_by_status": counts,
            "seo_issues": seo_counts, "media_issues": media_issues, "alerts": alerts_open, "job_errors": jobs_err, "api_errors_last_hour": m["last_hour"]["errors"], "new_landings_24h": new_landings,
            "changes_24h": {"chatgpt": chatgpt_changes, "manual": manual_changes, "autofix": fixes, "ai_actions": ai_actions, "ai_errors": ai_errors}, "backup": last_backup, "health": {"overall": health.get("overall"), "at": health.get("timestamp")},
            "limitations": ["Confronti percentuali omessi quando il campione è < 20"] + (["Nessun traffico registrato oggi"] if not today["steps"][0]["value"] else [])}


@ai_router.get("/daily-summary", operation_id="getDailySummary", summary="Riepilogo giornaliero con confronti")
async def ai_daily(request: Request, fresh: bool = True, principal=Depends(ai_guard("system:daily_summary"))):
    if not fresh:
        cached = await config_col.find_one({"id": "daily_summary"}, {"_id": 0})
        if cached:
            return envelope("daily_summary", request, cached["summary"]["text"], cached["summary"])
    s = await build_daily_summary()
    return envelope("daily_summary", request, s["text"], s)


@ai_router.get("/recommendations", operation_id="getRecommendations", summary="Cosa dovrei sistemare? (regole deterministiche)")
async def ai_recommendations(request: Request, limit: int = 30, principal=Depends(ai_guard("system:status"))):
    recs: List[dict] = []
    from v1_seo import run_audit
    await run_audit()
    match7 = build_match("7g")
    async for d in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}):
        v = validate_model(d)
        name = d.get("nome_artistico") or d.get("nome")
        if v["status"] == "ERROR":
            recs.append({"priority": "HIGH", "type": "content_readiness", "target": name, "target_slug": d["slug"], "problem": "Pubblicata ma con requisiti mancanti: " + ", ".join(e["field"] for e in v["errors"][:3]), "recommended_action": "Completa i campi mancanti o ritira la pubblicazione", "automatic": False, "capability_id": "validateModel"})
        elif v["status"] == "READY":
            recs.append({"priority": "MEDIUM", "type": "content_readiness", "target": name, "target_slug": d["slug"], "problem": "Pronta ma non pubblicata", "recommended_action": "Pubblica", "automatic": True, "capability_id": "publishModel"})
        elif v["status"] in ("INCOMPLETE", "DRAFT") and d.get("stato") != "archiviata":
            recs.append({"priority": "LOW", "type": "content_readiness", "target": name, "target_slug": d["slug"], "problem": f"{len(v['errors'])} requisiti mancanti", "recommended_action": "Carica media / completa testi", "automatic": False, "capability_id": "uploadMedia"})
        safe_n = await seo_issues_col.count_documents({"entity_id": d["id"], "status": "open", "severity": "SAFE_AUTO_FIX"})
        rev_n = await seo_issues_col.count_documents({"entity_id": d["id"], "status": "open", "severity": "REVIEW_REQUIRED"})
        crit = await seo_issues_col.find({"entity_id": d["id"], "status": "open", "severity": "CRITICAL"}, {"_id": 0, "code": 1}).to_list(5)
        if crit:
            recs.append({"priority": "HIGH", "type": "SEO", "target": name, "target_slug": d["slug"], "problem": "Issue SEO critiche: " + ", ".join(c["code"] for c in crit), "recommended_action": "Intervento manuale (link OnlyFans / slug / pubblicazione)", "automatic": False, "capability_id": "runSeoAudit"})
        if safe_n:
            recs.append({"priority": "MEDIUM", "type": "SEO", "target": name, "target_slug": d["slug"], "problem": f"{safe_n} issue SEO correggibili automaticamente", "recommended_action": "Applica fix sicuri", "automatic": True, "capability_id": "applySafeSeoFixesForModel"})
        if rev_n:
            recs.append({"priority": "LOW", "type": "SEO", "target": name, "target_slug": d["slug"], "problem": f"{rev_n} issue SEO da approvare", "recommended_action": "Prepara anteprime e chiedi approvazione", "automatic": False, "capability_id": "prepareSeoReview"})
        pairs = d.get("media_pairs") or []
        no_alt = sum(1 for p in pairs for side in ("pubblico", "segreto") if (p.get(side) or {}).get("url") and not (p.get(side) or {}).get("alt"))
        if no_alt:
            recs.append({"priority": "LOW", "type": "media", "target": name, "target_slug": d["slug"], "problem": f"{no_alt} media senza ALT", "recommended_action": "Genera ALT (fix SEO sicuro)", "automatic": True, "capability_id": "applySafeSeoFixesForModel"})
        if d.get("stato") == "pubblicata":
            k = await model_kpis(d["id"], match7)
            if k["visits"] >= 50 and k["conversion_rate"] < 1.0:
                recs.append({"priority": "MEDIUM", "type": "conversion", "target": name, "target_slug": d["slug"], "problem": f"Conversione bassa: {k['conversion_rate']}% su {k['visits']} visite (7g)", "recommended_action": "Rivedi CTA/teaser o avvia un A/B test sulla CTA", "automatic": False, "capability_id": "queryAnalytics"})
            if k["visits"] >= 50 and k["activation_rate"] < 20:
                recs.append({"priority": "LOW", "type": "conversion", "target": name, "target_slug": d["slug"], "problem": f"Attivazione Lato Segreto bassa: {k['activation_rate']}%", "recommended_action": "Rafforza frase di attivazione / teaser", "automatic": False, "capability_id": "updateModel"})
    health = await reconciled_health()   # current, reconciled state only: stale alerts never produce recommendations
    for c in health.get("checks", []):
        if c["status"] == "fail":
            recs.append({"priority": "HIGH", "type": "technical", "target": "sito", "problem": f"Check {c['name']} fallito: {c['detail']}", "recommended_action": "Verifica e risolvi", "automatic": False, "capability_id": "getSiteHealth"})
    if not await landings_col.count_documents({"is_deleted": {"$ne": True}}):
        recs.append({"priority": "LOW", "type": "landing", "target": "sito", "problem": "Nessuna landing SEO creata", "recommended_action": "Crea una landing italiana per la modella top", "automatic": True, "capability_id": "createLanding"})
    unknown_geo = await events_col.count_documents({**match7, "geo.country": "UNKNOWN"})
    total7 = await events_col.count_documents(match7)
    if total7 and unknown_geo / total7 > 0.5:
        recs.append({"priority": "LOW", "type": "analytics", "target": "tracking", "problem": f"{round(unknown_geo / total7 * 100)}% eventi senza geo (header CDN assenti)", "recommended_action": "Nella fase dominio: abilita header geo del CDN/proxy", "automatic": False, "capability_id": "getSiteHealth"})
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    recs.sort(key=lambda r: (order[r["priority"]], r["type"]))
    s = f"{len(recs)} raccomandazioni: {len([r for r in recs if r['priority'] == 'HIGH'])} HIGH, {len([r for r in recs if r['priority'] == 'MEDIUM'])} MEDIUM, {len([r for r in recs if r['automatic']])} eseguibili automaticamente."
    return envelope("recommendations", request, s, {"items": recs[:limit], "total": len(recs), "data_available": True})


# =====================================================================
# BATCH
# =====================================================================
async def _select_models(sel: AIBatch) -> List[dict]:
    q: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if sel.selection == "published":
        q["stato"] = "pubblicata"
    elif sel.selection == "draft":
        q["stato"] = {"$ne": "pubblicata"}
    elif sel.selection == "category":
        q["categorie"] = sel.category
    elif sel.selection == "ids":
        docs = []
        for r in sel.ids or []:
            docs.append(await resolve_model(r, include_deleted=True))
        return docs
    return await models_col.find(q, {"_id": 0}).sort("ordine", 1).to_list(1000)


@ai_router.post("/batch/seo-safe-fix", operation_id="batchSafeSeoFix", summary="Fix SEO sicuri su più modelle (dry_run, risultati individuali)")
async def ai_batch_seo(body: AIBatch, request: Request, principal=Depends(ai_guard("seo:safe_fix", write=True, batch=True))):
    t0 = time.time()
    cfg = await ai_config()
    mx = min(int(body.max_items or cfg["policy"].get("max_batch", 50)), int(cfg["policy"].get("max_batch", 50)))
    docs = await _select_models(body)
    blocked = docs[mx:]
    docs = docs[:mx]
    from v1_seo import run_audit, apply_safe_fixes
    results = []
    tot_found = tot_fixed = tot_review = tot_crit = 0
    for d in docs:
        try:
            res = await run_audit("models", d["id"])
            before = await _seo_score(d["id"])
            fx = await apply_safe_fixes(actor_of(principal), request_id_of(request), "models", d["id"], body.dry_run, source="chatgpt" if principal.get("type") == "api_key" else "ai")
            after = before if body.dry_run else await _seo_score(d["id"])
            fixed = fx.get("would_fix", 0) if body.dry_run else fx.get("applied", 0)
            results.append({"slug": d["slug"], "nome": d.get("nome_artistico"), "ok": True, "found": res["total"], "fixed": fixed, "review": res["counts"]["REVIEW_REQUIRED"], "critical": res["counts"]["CRITICAL"], "score_before": before, "score_after": after,
                            "version_ids": [r.get("version_id") for r in fx.get("results", []) if r.get("applied")] if not body.dry_run else []})
            tot_found += res["total"]; tot_fixed += fixed; tot_review += res["counts"]["REVIEW_REQUIRED"]; tot_crit += res["counts"]["CRITICAL"]
        except Exception as e:
            results.append({"slug": d["slug"], "ok": False, "error": str(e)[:200]})
    s = (f"{'[dry-run] ' if body.dry_run else ''}Batch SEO su {len(docs)} modelle: {tot_found} issue, {tot_fixed} fix sicuri {'applicabili' if body.dry_run else 'applicati'}, {tot_review} da approvare, {tot_crit} critiche; {len([r for r in results if not r['ok']])} errori." + (f" {len(blocked)} modelle oltre il limite batch ({mx})." if blocked else ""))
    if not body.dry_run:
        await log_action(principal, request, "batch.seo_safe_fix", body.model_dump(), s, all(r["ok"] for r in results), {"type": "batch", "count": len(docs)}, [{"field": "seo", "entity": r["slug"], "fixed": r.get("fixed")} for r in results if r.get("fixed")], [v for r in results for v in r.get("version_ids", [])], t0)
    return envelope("batch.seo_safe_fix", request, s, {"dry_run": body.dry_run, "targets_affected": len(docs), "progress": {"total": len(docs), "done": len(results), "failed": len([r for r in results if not r["ok"]])}, "results": results,
                                                         "predicted_changes" if body.dry_run else "applied": tot_fixed, "review_items": tot_review, "blocked_items": [d["slug"] for d in blocked], "critical_items": tot_crit}, ok=all(r["ok"] for r in results))


@ai_router.post("/batch/validate", operation_id="batchValidate", summary="Valida più modelle")
async def ai_batch_validate(body: AIBatch, request: Request, principal=Depends(ai_guard("models:validate", batch=True))):
    docs = await _select_models(body)
    items = [{"slug": d["slug"], "nome": d.get("nome_artistico"), **{k: v for k, v in validate_model(d).items() if k in ("ready", "status", "missing_count")}, "missing": [e["field"] for e in validate_model(d)["errors"]]} for d in docs]
    return envelope("batch.validate", request, f"{len(items)} modelle: {len([i for i in items if i['ready']])} pronte, {len([i for i in items if not i['ready']])} incomplete.", {"items": items})


# =====================================================================
# COMMAND DISPATCHER (structured, no LLM)
# =====================================================================
COMMANDS = {
    # action: (handler name, write?, scopes, batch?)
    "models.find": ("find", False, ["models:read"]), "models.create": ("create", True, ["models:create"]), "models.update": ("update", True, ["models:update"]),
    "models.validate": ("validate", False, ["models:validate"]), "models.publish": ("publish", True, ["models:publish"]), "models.unpublish": ("unpublish", True, ["models:unpublish"]),
    "models.archive": ("archive", True, ["models:archive"]), "models.restore": ("restore", True, ["models:archive"]), "models.feature": ("feature", True, ["models:feature"]), "models.health": ("health", False, ["models:read"]),
    "media.upload": ("media_upload", True, ["media:upload", "models:update"]),
    "seo.audit": ("seo_audit", False, ["seo:audit"]), "seo.safe_fix": ("seo_safe_fix", True, ["seo:safe_fix"]), "seo.review_list": ("seo_review_list", False, ["seo:review_prepare"]), "seo.review_preview": ("seo_review_preview", False, ["seo:review_prepare"]),
    "landing.create": ("landing_create", True, ["landing:create"]), "landing.validate": ("landing_validate", False, ["landing:validate"]), "landing.publish": ("landing_publish", True, ["landing:read"]),
    "analytics.query": ("analytics", False, ["analytics:read"]), "rollback.preview": ("rollback_preview", False, ["rollback:read"]), "rollback.execute": ("rollback", True, ["rollback:execute"]),
    "system.status": ("status", False, ["system:status"]), "system.site_health": ("site_health", False, ["system:status"]), "system.daily_summary": ("daily", False, ["system:daily_summary"]), "system.recommendations": ("recommendations", False, ["system:status"]),
    "batch.seo_safe_fix": ("batch_seo", True, ["seo:safe_fix"]), "approvals.confirm": ("confirm", True, ["ai:execute"]),
}


@ai_router.post("/command", operation_id="runCommand", summary="Dispatcher strutturato: {action, target, parameters, reason, dry_run}")
async def ai_command(body: AICommand, request: Request, principal=Depends(ai_guard("ai:execute"))):
    spec = COMMANDS.get(body.action)
    if not spec:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_FAILED", "message": f"Azione sconosciuta '{body.action}'", "allowed": sorted(COMMANDS.keys())})
    handler, write, scopes = spec
    cfg = await ai_config()
    if write and principal.get("type") == "api_key" and not cfg["write_enabled"] and (not body.dry_run or handler in ("confirm", "media_upload")):
        raise HTTPException(status_code=403, detail={"code": "READ_ONLY_MODE", "message": "Modalità READ_ONLY: usa dry_run=true (upload e conferme non hanno anteprima)"})
    if handler in ("batch_seo",) and not cfg["batch_enabled"]:
        raise HTTPException(status_code=403, detail={"code": "BATCH_DISABLED", "message": "Batch disattivato"})
    from v1_ai_policy import missing_scopes_for
    missing = missing_scopes_for(principal, scopes, bool(write and body.dry_run and handler not in ("confirm", "media_upload")))
    if missing:
        raise HTTPException(status_code=403, detail={"code": "INSUFFICIENT_SCOPE", "message": "Permessi insufficienti", "missing_scopes": missing})
    p, t, r, dry = body.parameters or {}, body.target, body.reason or "", body.dry_run
    if handler == "find": return await ai_find(AIRef(model=t), request, principal)
    if handler == "create": return await ai_create(AICreateModel(nome=p.get("nome") or t, reason=r, dry_run=dry, **{k: v for k, v in p.items() if k != "nome"}), request, principal)
    if handler == "update": return await ai_update(AIUpdateModel(model=t, changes=p.get("changes") or p, reason=r, dry_run=dry, expected_updated_at=p.get("expected_updated_at")), request, principal)
    if handler == "validate": return await ai_validate(AIRef(model=t), request, principal)
    if handler == "publish": return await ai_publish(AIRef(model=t, reason=r, dry_run=dry, expected_updated_at=p.get("expected_updated_at")), request, principal)
    if handler == "unpublish": return await ai_unpublish(AIRef(model=t, reason=r, dry_run=dry), request, principal)
    if handler == "archive": return await ai_archive(AIRef(model=t, reason=r, dry_run=dry), request, principal)
    if handler == "restore": return await ai_restore(AIRef(model=t, reason=r, dry_run=dry), request, principal)
    if handler == "feature": return await ai_feature(AIFeature(model=t, reason=r, dry_run=dry, **{k: v for k, v in p.items() if k in ("position", "badge", "pellicola")}), request, principal)
    if handler == "health": return await ai_model_health(t, request, p.get("range", "7g"), principal)
    if handler == "media_upload": return await ai_media_upload(AIMediaUpload(model=t, **{k: v for k, v in p.items() if k in AIMediaUpload.model_fields}), request, principal)
    if handler == "seo_audit": return await ai_seo_audit(AISeo(model=t, scope=p.get("scope", "all")), request, principal)
    if handler == "seo_safe_fix": return await _safe_fix(request, principal, p.get("scope", "all"), t, dry, time.time())
    if handler == "seo_review_list": return await ai_seo_review_list(t, request, principal)
    if handler == "seo_review_preview": return await ai_seo_review_preview(t, p.get("issue_id"), request, ReviewBody(proposed_value=p.get("proposed_value"), reason=r), principal)
    if handler == "landing_create": return await ai_landings_create(AILandingCreate(model=t, reason=r, dry_run=dry, **{k: v for k, v in p.items() if k in AILandingCreate.model_fields and k not in ("model", "reason", "dry_run")}), request, principal)
    if handler == "landing_validate": return await ai_landing_validate(t, request, principal)
    if handler == "landing_publish": return await ai_landing_publish(t, request, dry, principal)
    if handler == "analytics": return await ai_query(AIQuery(model=t if t else p.get("model"), **{k: v for k, v in p.items() if k in AIQuery.model_fields and k != "model"}), request, principal)
    if handler == "rollback_preview": return await ai_rollback_preview(AIRollback(model=t, **{k: v for k, v in p.items() if k in AIRollback.model_fields and k != "model"}), request, principal)
    if handler == "rollback": return await ai_rollback(AIRollback(model=t, reason=r, dry_run=dry, **{k: v for k, v in p.items() if k in AIRollback.model_fields and k not in ("model", "reason", "dry_run")}), request, principal)
    if handler == "status": return await ai_status(request, principal)
    if handler == "site_health": return await ai_site_health(request, principal)
    if handler == "daily": return await ai_daily(request, True, principal)
    if handler == "recommendations": return await ai_recommendations(request, int(p.get("limit", 30)), principal)
    if handler == "batch_seo": return await ai_batch_seo(AIBatch(dry_run=dry, **{k: v for k, v in p.items() if k in AIBatch.model_fields and k != "dry_run"}), request, principal)
    if handler == "confirm": return await ai_confirm(AIConfirm(token=p.get("token", ""), reason=r), request, principal)
    raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Handler non implementato"})


# =====================================================================
# ACTIVITY / CAPABILITIES / OPENAPI
# =====================================================================
@ai_router.get("/actions", operation_id="listAiActions", summary="Attività ChatGPT recente")
async def ai_actions(limit: int = 50, request: Request = None, principal=Depends(ai_guard("ai:execute"))):
    items = await ai_actions_col.find({}, {"_id": 0, "before": 0, "after": 0}).sort("timestamp", -1).to_list(limit)
    return envelope("actions", request, f"{len(items)} azioni AI recenti", {"items": items})


CAPABILITIES = [
    {"id": "findModel", "name": "Trova modella", "description": "Risolve un riferimento naturale (id, slug, nome, nome parziale) e restituisce stato e workflow.", "method": "POST", "endpoint": "/api/v1/ai/models/find", "required_scopes": ["models:read"], "safety_level": "SAFE",
     "parameters": {"model": "string (id|slug|nome)"}, "required": ["model"], "optional": [], "example_request": {"model": "Alessia"}, "example_response": {"ok": True, "summary": "Trovata Alessia (PUBLISHED)"}, "errors": ["NOT_FOUND", "AMBIGUOUS_REFERENCE"]},
    {"id": "listModels", "name": "Elenco modelle", "description": "Tutte le modelle con workflow status.", "method": "GET", "endpoint": "/api/v1/ai/models", "required_scopes": ["models:read"], "safety_level": "SAFE", "parameters": {"status": "DRAFT|INCOMPLETE|READY|PUBLISHED|ARCHIVED|ERROR"}, "required": [], "optional": ["status"], "errors": []},
    {"id": "createModel", "name": "Crea modella", "description": "Crea una bozza con i campi forniti; mai pubblica direttamente.", "method": "POST", "endpoint": "/api/v1/ai/models/create", "required_scopes": ["models:create"], "safety_level": "SAFE", "idempotent": True,
     "parameters": {"nome": "string", "...": "qualsiasi campo modella", "dry_run": "bool"}, "required": ["nome"], "optional": ["frase", "bio", "bio_segreta", "categorie", "tag", "onlyfans_url", "tema", "regia", "dry_run"], "example_request": {"nome": "Vanessa", "categorie": ["more"]}, "errors": ["VALIDATION_FAILED", "READ_ONLY_MODE"]},
    {"id": "updateModel", "name": "Aggiorna modella", "description": "Deep-merge dei campi. Campi editoriali/strategici (slug, nome, bio, frase, onlyfans_url, seo.title/meta/canonical/robots) → REVIEW_REQUIRED con token di approvazione.", "method": "POST", "endpoint": "/api/v1/ai/models/update", "required_scopes": ["models:update"], "safety_level": "SAFE|REVIEW_REQUIRED", "idempotent": True,
     "parameters": {"model": "ref", "changes": "object", "reason": "string", "dry_run": "bool", "expected_updated_at": "etag per concorrenza"}, "required": ["model", "changes"], "optional": ["reason", "dry_run", "expected_updated_at"], "example_request": {"model": "alessia", "changes": {"tema": {"preset": "tattoo"}}}, "errors": ["NOT_FOUND", "AMBIGUOUS_REFERENCE", "VALIDATION_FAILED", "CONFLICT", "APPROVAL_REQUIRED", "READ_ONLY_MODE"]},
    {"id": "validateModel", "name": "Valida modella", "description": "Requisiti mancanti, avvisi, stato workflow.", "method": "POST", "endpoint": "/api/v1/ai/models/validate", "required_scopes": ["models:validate"], "safety_level": "SAFE", "parameters": {"model": "ref"}, "required": ["model"], "optional": [], "errors": ["NOT_FOUND", "AMBIGUOUS_REFERENCE"]},
    {"id": "publishModel", "name": "Pubblica modella", "description": "Passa sempre dal validator: se non pronta → PUBLICATION_BLOCKED con missing. force non esiste.", "method": "POST", "endpoint": "/api/v1/ai/models/publish", "required_scopes": ["models:publish"], "safety_level": "SAFE", "idempotent": True, "parameters": {"model": "ref", "dry_run": "bool", "expected_updated_at": "etag"}, "required": ["model"], "optional": ["dry_run", "expected_updated_at"], "errors": ["PUBLICATION_BLOCKED", "CONFLICT", "READ_ONLY_MODE"]},
    {"id": "unpublishModel", "name": "Ritira modella", "description": "Torna in bozza.", "method": "POST", "endpoint": "/api/v1/ai/models/unpublish", "required_scopes": ["models:unpublish"], "safety_level": "SAFE", "idempotent": True, "parameters": {"model": "ref", "dry_run": "bool"}, "required": ["model"], "optional": ["dry_run"], "errors": ["NOT_FOUND"]},
    {"id": "archiveModel", "name": "Archivia modella", "description": "Archivia (ripristinabile con restoreModel).", "method": "POST", "endpoint": "/api/v1/ai/models/archive", "required_scopes": ["models:archive"], "safety_level": "SAFE", "idempotent": True, "parameters": {"model": "ref", "dry_run": "bool"}, "required": ["model"], "optional": ["dry_run"], "errors": ["NOT_FOUND"]},
    {"id": "featureModel", "name": "Metti in Home", "description": "Posizione nella griglia Home, badge, pellicola.", "method": "POST", "endpoint": "/api/v1/ai/models/feature", "required_scopes": ["models:feature"], "safety_level": "SAFE", "idempotent": True, "parameters": {"model": "ref", "position": "int", "badge": "string", "pellicola": "bool", "dry_run": "bool"}, "required": ["model"], "optional": ["position", "badge", "pellicola", "dry_run"], "errors": ["NOT_FOUND"]},
    {"id": "getModelHealth", "name": "Health modella", "description": "Pubblicazione, readiness, SEO score, media, ALT, CTA, OnlyFans, sitemap, redirect, analytics, errori recenti.", "method": "GET", "endpoint": "/api/v1/ai/models/{reference}/health", "required_scopes": ["models:read"], "safety_level": "SAFE", "parameters": {"reference": "path", "range": "7g|30g"}, "required": ["reference"], "optional": ["range"], "errors": ["NOT_FOUND", "AMBIGUOUS_REFERENCE"]},
    {"id": "uploadMedia", "name": "Carica media", "description": "URL pubblico o base64 → storage, varianti, ALT, slot (foto_card|pair|pellicola|og_image|...). Anti-SSRF, magic bytes.", "method": "POST", "endpoint": "/api/v1/ai/media/upload", "required_scopes": ["media:upload", "models:update"], "safety_level": "SAFE", "idempotent": True,
     "parameters": {"model": "ref", "slot": "string", "side": "pubblico|segreto", "url": "https://...", "base64_data": "string", "alt": "string"}, "required": ["model", "slot"], "optional": ["side", "url", "base64_data", "alt", "seo_name", "poster_url", "pair_index"], "errors": ["MEDIA_VALIDATION_FAILED", "NOT_FOUND"]},
    {"id": "uploadMediaBatch", "name": "Carica più media", "description": "Batch di upload con risultati individuali.", "method": "POST", "endpoint": "/api/v1/ai/media/upload-batch", "required_scopes": ["media:upload", "models:update"], "safety_level": "SAFE", "idempotent": True, "parameters": {"model": "ref", "items": "[uploadMedia]"}, "required": ["model", "items"], "optional": [], "errors": ["MEDIA_VALIDATION_FAILED", "BATCH_DISABLED"]},
    {"id": "runSeoAudit", "name": "Audit SEO", "description": "Classifica le issue SAFE_AUTO_FIX / REVIEW_REQUIRED / CRITICAL e calcola il SEO score.", "method": "POST", "endpoint": "/api/v1/ai/seo/audit", "required_scopes": ["seo:audit"], "safety_level": "SAFE", "parameters": {"model": "ref (opz.)", "scope": "all|models|articles|categories|landings"}, "required": [], "optional": ["model", "scope"], "errors": []},
    {"id": "applySafeSeoFixes", "name": "Fix SEO sicuri", "description": "Applica SOLO SAFE_AUTO_FIX; ogni fix è versionato e reversibile; ritorna score prima/dopo.", "method": "POST", "endpoint": "/api/v1/ai/seo/apply-safe-fixes", "required_scopes": ["seo:safe_fix"], "safety_level": "SAFE_AUTO_FIX", "idempotent": True, "parameters": {"model": "ref (opz.)", "scope": "string", "dry_run": "bool"}, "required": [], "optional": ["model", "scope", "dry_run"], "errors": ["READ_ONLY_MODE"]},
    {"id": "applySafeSeoFixesForModel", "name": "Fix SEO sicuri (modella)", "description": "Come applySafeSeoFixes ma su una sola modella.", "method": "POST", "endpoint": "/api/v1/ai/models/{reference}/seo/apply-safe-fixes", "required_scopes": ["seo:safe_fix"], "safety_level": "SAFE_AUTO_FIX", "idempotent": True, "parameters": {"reference": "path", "dry_run": "query bool"}, "required": ["reference"], "optional": ["dry_run"], "errors": ["NOT_FOUND"]},
    {"id": "listSeoReviewIssues", "name": "Issue SEO da approvare", "description": "REVIEW_REQUIRED e CRITICAL di una modella con impatto SEO/UX e rischio.", "method": "GET", "endpoint": "/api/v1/ai/models/{reference}/seo/review", "required_scopes": ["seo:review_prepare"], "safety_level": "SAFE", "parameters": {"reference": "path"}, "required": ["reference"], "optional": [], "errors": ["NOT_FOUND"]},
    {"id": "prepareSeoReview", "name": "Prepara review SEO", "description": "Anteprima current→proposed + token di approvazione (single-use, TTL). Nulla viene applicato.", "method": "POST", "endpoint": "/api/v1/ai/models/{reference}/seo/review/{issue_id}/preview", "required_scopes": ["seo:review_prepare"], "safety_level": "REVIEW_REQUIRED", "parameters": {"reference": "path", "issue_id": "path", "proposed_value": "any (opz.)"}, "required": ["reference", "issue_id"], "optional": ["proposed_value", "reason"], "errors": ["NOT_FOUND", "CRITICAL_ACTION_BLOCKED", "APPROVAL_DISABLED"]},
    {"id": "listPendingApprovals", "name": "Approvazioni in attesa", "description": "Token pendenti creati da questo attore.", "method": "GET", "endpoint": "/api/v1/ai/approvals", "required_scopes": ["ai:execute"], "safety_level": "SAFE", "parameters": {}, "required": [], "optional": [], "errors": []},
    {"id": "confirmApproval", "name": "Conferma approvazione", "description": "Esegue la modifica approvata dall'utente. Token single-use legato ad attore/target/payload.", "method": "POST", "endpoint": "/api/v1/ai/approvals/confirm", "required_scopes": ["ai:execute"], "safety_level": "REVIEW_REQUIRED", "idempotent": True, "parameters": {"token": "apr_..."}, "required": ["token"], "optional": ["reason"], "errors": ["APPROVAL_INVALID", "APPROVAL_EXPIRED", "INSUFFICIENT_SCOPE", "CONFLICT"]},
    {"id": "createLanding", "name": "Crea landing", "description": "Landing in bozza per una o più modelle (SEO, CTA, FAQ, targeting editoriale Italia, nessun geoblocking). La rotta pubblica resta dietro flag.", "method": "POST", "endpoint": "/api/v1/ai/landings", "required_scopes": ["landing:create"], "safety_level": "SAFE", "idempotent": True,
     "parameters": {"model": "ref", "models": "[ref]", "slug": "string", "title": "SEO title", "h1": "string", "hero_text": "string", "intro": "string", "cta_text": "string", "meta_description": "string", "keywords": "[string]", "noindex": "bool", "location_targeting": "Italia", "dry_run": "bool"}, "required": [], "optional": ["model", "models", "slug", "title", "h1", "hero_text", "intro", "cta_text", "cta_url", "meta_description", "keywords", "topics", "canonical", "noindex", "faq", "dry_run"], "errors": ["NOT_FOUND", "VALIDATION_FAILED"]},
    {"id": "getLanding", "name": "Dettaglio landing", "description": "Landing con validazione completa.", "method": "GET", "endpoint": "/api/v1/ai/landings/{reference}", "required_scopes": ["landing:read"], "safety_level": "SAFE", "parameters": {"reference": "id|slug|titolo"}, "required": ["reference"], "optional": [], "errors": ["NOT_FOUND"]},
    {"id": "validateLanding", "name": "Valida landing", "description": "SEO, duplicati, slug, canonical, CTA, modelle target, media, accessibilità, index, link interni.", "method": "POST", "endpoint": "/api/v1/ai/landings/{reference}/validate", "required_scopes": ["landing:validate"], "safety_level": "SAFE", "parameters": {"reference": "path"}, "required": ["reference"], "optional": [], "errors": ["NOT_FOUND"]},
    {"id": "publishLanding", "name": "Pubblica landing", "description": "Richiede scope landing:publish; senza scope prepara un'approvazione.", "method": "POST", "endpoint": "/api/v1/ai/landings/{reference}/publish", "required_scopes": ["landing:read", "landing:publish (o approvazione)"], "safety_level": "REVIEW_REQUIRED", "parameters": {"reference": "path", "dry_run": "query bool"}, "required": ["reference"], "optional": ["dry_run"], "errors": ["PUBLICATION_BLOCKED", "APPROVAL_REQUIRED"]},
    {"id": "updateLanding", "name": "Aggiorna landing", "description": "Deep-merge campi landing.", "method": "POST", "endpoint": "/api/v1/ai/landing/update", "required_scopes": ["landing:update"], "safety_level": "SAFE", "idempotent": True, "parameters": {"landing": "ref", "changes": "object", "dry_run": "bool"}, "required": ["landing", "changes"], "optional": ["dry_run"], "errors": ["NOT_FOUND"]},
    {"id": "queryAnalytics", "name": "Analytics", "description": "Testuale ('quale modella converte meglio?', 'traffico italiano', 'funnel', 'mobile vs desktop') o strutturata {metric, group_by, period, country, sort, limit}. Sempre: periodo, filtri, sample_size, data_available, limitations.", "method": "POST", "endpoint": "/api/v1/ai/analytics/query", "required_scopes": ["analytics:read"], "safety_level": "SAFE",
     "parameters": {"question": "string", "metric": "|".join(METRICS.keys()), "group_by": "model|country|region|city|device|source|day|none", "period": "24h|7d|30d|today|yesterday", "country": "IT", "device": "mobile|desktop|tablet", "source": "string", "model": "ref", "sort": "asc|desc", "limit": "int"}, "required": [], "optional": ["question", "metric", "group_by", "period", "country", "region", "device", "source", "model", "sort", "limit"],
     "example_request": {"metric": "onlyfans_ctr", "group_by": "model", "country": "IT", "period": "7d", "sort": "desc", "limit": 10}, "errors": ["VALIDATION_FAILED"]},
    {"id": "previewRollback", "name": "Anteprima rollback", "description": "Mostra cosa verrebbe ripristinato: per version_id oppure ultima modifica AI su una modella (target/actor/request_id).", "method": "POST", "endpoint": "/api/v1/ai/rollback/preview", "required_scopes": ["rollback:read"], "safety_level": "SAFE", "parameters": {"version_id": "string", "model": "ref", "actor": "string", "request_id": "string", "latest_ai": "bool"}, "required": [], "optional": ["version_id", "model", "actor", "request_id", "latest_ai"], "errors": ["NOT_FOUND"]},
    {"id": "rollbackChange", "name": "Rollback", "description": "Ripristina lo stato precedente creando una nuova versione (history intatta).", "method": "POST", "endpoint": "/api/v1/ai/rollback", "required_scopes": ["rollback:execute"], "safety_level": "SAFE", "idempotent": True, "parameters": {"version_id": "string", "model": "ref", "dry_run": "bool", "reason": "string"}, "required": [], "optional": ["version_id", "model", "actor", "request_id", "dry_run", "reason"], "errors": ["NOT_FOUND", "CONFLICT", "READ_ONLY_MODE"]},
    {"id": "getSystemStatus", "name": "Stato sistema", "description": "API, DB, health, alert, job, SEO, flag AI, permessi correnti.", "method": "GET", "endpoint": "/api/v1/ai/status", "required_scopes": ["system:status"], "safety_level": "SAFE", "parameters": {}, "required": [], "optional": [], "errors": []},
    {"id": "getSiteHealth", "name": "Salute sito", "description": "Modelle per stato, media rotti, SEO, sitemap, job, webhook, errori API, backup.", "method": "GET", "endpoint": "/api/v1/ai/site-health", "required_scopes": ["system:status"], "safety_level": "SAFE", "parameters": {}, "required": [], "optional": [], "errors": []},
    {"id": "getDailySummary", "name": "Riepilogo giornaliero", "description": "Visite, Italia, funnel, CTR OF, top/in calo, SEO, media, alert, job, API, landing, modifiche ChatGPT/manuali, backup; confronti oggi/ieri e 7/7 solo con campione sufficiente.", "method": "GET", "endpoint": "/api/v1/ai/daily-summary", "required_scopes": ["system:daily_summary"], "safety_level": "SAFE", "parameters": {}, "required": [], "optional": [], "errors": []},
    {"id": "getRecommendations", "name": "Cosa sistemare", "description": "Lista deterministica (SEO, media, readiness, conversion, technical, landing, analytics) con capability_id per agire.", "method": "GET", "endpoint": "/api/v1/ai/recommendations", "required_scopes": ["system:status"], "safety_level": "SAFE", "parameters": {"limit": "int"}, "required": [], "optional": ["limit"], "errors": []},
    {"id": "batchSafeSeoFix", "name": "Fix SEO sicuri in batch", "description": "Su tutte / pubblicate / bozze / categoria / ids; dry_run; risultati individuali; nessun rollback totale per errori singoli.", "method": "POST", "endpoint": "/api/v1/ai/batch/seo-safe-fix", "required_scopes": ["seo:safe_fix"], "safety_level": "SAFE_AUTO_FIX", "idempotent": True, "parameters": {"selection": "all|published|draft|category|ids", "category": "slug", "ids": "[ref]", "dry_run": "bool", "max_items": "int"}, "required": [], "optional": ["selection", "category", "ids", "dry_run", "max_items"], "errors": ["BATCH_DISABLED", "READ_ONLY_MODE"]},
    {"id": "batchValidate", "name": "Valida in batch", "description": "Readiness di più modelle.", "method": "POST", "endpoint": "/api/v1/ai/batch/validate", "required_scopes": ["models:validate"], "safety_level": "SAFE", "parameters": {"selection": "all|published|draft|category|ids"}, "required": [], "optional": ["selection", "category", "ids"], "errors": []},
    {"id": "runCommand", "name": "Comando strutturato", "description": "Dispatcher: {action, target, parameters, reason, dry_run}. Nessun LLM server-side.", "method": "POST", "endpoint": "/api/v1/ai/command", "required_scopes": ["ai:execute", "+ scope dell'azione"], "safety_level": "dipende dall'azione", "parameters": {"action": "|".join(sorted(COMMANDS.keys())), "target": "ref", "parameters": "object", "reason": "string", "dry_run": "bool"}, "required": ["action"], "optional": ["target", "parameters", "reason", "dry_run"], "errors": ["VALIDATION_FAILED", "INSUFFICIENT_SCOPE"]},
    {"id": "listAiActions", "name": "Attività AI", "description": "Log delle azioni ChatGPT.", "method": "GET", "endpoint": "/api/v1/ai/actions", "required_scopes": ["ai:execute"], "safety_level": "SAFE", "parameters": {"limit": "int"}, "required": [], "optional": ["limit"], "errors": []},
]
for _c in CAPABILITIES:
    _c.setdefault("idempotent", _c["method"] == "GET")
    _c.setdefault("natural_references", ["id", "slug", "nome", "nome parziale non ambiguo"] if "model" in str(_c.get("parameters")) or "reference" in _c["endpoint"] else [])
    _c.setdefault("example_request", {})
    _c.setdefault("example_response", {"ok": True, "summary": "...", "data": {}, "warnings": [], "next_steps": [], "request_id": "...", "changes": [], "approval_required": False})
    _c["errors"] = sorted(set(_c.get("errors", []) + ["AUTH_REQUIRED", "INVALID_API_KEY", "INSUFFICIENT_SCOPE", "AI_API_DISABLED", "RATE_LIMITED"]))


@ai_router.get("/capabilities", operation_id="getCapabilities", summary="Catalogo machine-readable delle capacità ChatGPT")
async def capabilities(request: Request, principal=Depends(ai_guard("ai:execute"))):
    cfg = await ai_config()
    from v1_ai_policy import PREVIEW_SCOPE
    def _req(c):
        return [s.split(" ")[0] for s in c["required_scopes"] if ":" in s and "(" not in s and "+" not in s]
    mine = []
    for c in CAPABILITIES:
        req = _req(c)
        if all(has_scope(principal, s) for s in req):
            mine.append({**c, "access": "full"})
        elif all(has_scope(principal, s) or (s in PREVIEW_SCOPE and has_scope(principal, PREVIEW_SCOPE[s])) for s in req) and "dry_run" in str(c.get("parameters")):
            mine.append({**c, "access": "preview_only", "note": "Con i tuoi scope puoi solo usare dry_run=true (anteprima, nessuna modifica)"})
    if not cfg["write_enabled"]:
        for c in mine:
            if c["method"] == "POST" and "dry_run" in str(c.get("parameters")):
                c["read_only_note"] = "Modalità READ_ONLY: consentito solo con dry_run=true"
    return envelope("capabilities", request, f"{len(mine)} capacità disponibili per questa chiave ({len(CAPABILITIES)} totali). Modalità {cfg['mode']}.",
                    {"version": "1.0", "auth": {"header": "X-API-Key: <chiave>", "alternative": "Authorization: Bearer <chiave ls_...>", "roles": "AI_OPERATOR consigliato"},
                     "openapi": "/api/v1/ai/openapi.json", "docs": "/api/docs", "idempotency": "header Idempotency-Key su POST", "request_correlation": "header X-Request-ID (accettato e restituito)",
                     "response_contract": {"ok": "bool", "summary": "string (italiano)", "data": "object", "warnings": "[string]", "next_steps": "[string]", "request_id": "string", "changes": "[{field,before,after}]", "approval_required": "bool", "approval": "{type,token,expires_at,before,after,reason} quando approval_required", "code": "solo in errore"},
                     "safety_levels": {"SAFE": "eseguibile con lo scope", "REVIEW_REQUIRED": "prepara anteprima + token, applica solo dopo confirmApproval", "CRITICAL": "mai via ChatGPT"},
                     "error_codes": ERROR_CODES, "mode": cfg["mode"], "enabled": cfg["enabled"], "your_scopes": principal.get("scopes"), "model_fields": sorted(ALLOWED_FIELDS),
                     "slots": ["foto_card", "foto_copertina", "foto_card_teaser", "foto_segreta_hero", "og_image", "pair", "pellicola", "messaggio_foto", "messaggio_video"],
                     "capabilities": mine, "all_capabilities_count": len(CAPABILITIES)})


@ai_router.get("/openapi.json", operation_id="getAiOpenApi", include_in_schema=False)
async def ai_openapi(request: Request):
    """Clean OpenAPI containing only the ChatGPT endpoints (public document; no auth needed to read the spec)."""
    from server import app
    full = app.openapi()
    paths = {p: v for p, v in full.get("paths", {}).items() if p.startswith("/api/v1/ai/") and p != "/api/v1/ai/openapi.json" and p != "/api/v1/ai/test-connection"}
    # collect referenced schemas
    import json as _json
    used = set()
    def walk(o):
        if isinstance(o, dict):
            if "$ref" in o:
                used.add(o["$ref"].split("/")[-1])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(paths)
    schemas = full.get("components", {}).get("schemas", {})
    changed = True
    while changed:
        n = len(used)
        for k in list(used):
            walk(schemas.get(k, {}))
        changed = len(used) != n
    base = await _public_base_url(request)
    spec = {"openapi": full.get("openapi", "3.1.0"),
            "info": {"title": "LATO SEGRETO — ChatGPT Control API", "version": "1.0.0", "description": "Azioni sicure per amministrare LATO SEGRETO via ChatGPT. Auth: header X-API-Key (o Bearer con chiave ls_...). Risposte: {ok, summary, data, warnings, next_steps, request_id, changes, approval_required}. Errori: {ok:false, code, summary}."},
            "servers": [{"url": base}] if base else [], "paths": paths,
            "components": {"schemas": {k: schemas[k] for k in used if k in schemas}, "securitySchemes": {"ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}, "BearerAuth": {"type": "http", "scheme": "bearer"}}},
            "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}]}
    for p, ops in spec["paths"].items():
        for m, op in ops.items():
            op.setdefault("responses", {}).setdefault("4XX", {"description": "Errore machine-readable {ok:false, code, summary, data, request_id}", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AIError"}}}})
            op["security"] = [{"ApiKeyAuth": []}, {"BearerAuth": []}]
    spec["components"]["schemas"]["AIError"] = {"type": "object", "properties": {"ok": {"type": "boolean", "enum": [False]}, "code": {"type": "string", "enum": ERROR_CODES}, "summary": {"type": "string"}, "data": {"type": "object"}, "warnings": {"type": "array", "items": {"type": "string"}}, "next_steps": {"type": "array", "items": {"type": "string"}}, "request_id": {"type": "string"}}}
    spec["components"]["schemas"]["AIResponse"] = {"type": "object", "properties": {"ok": {"type": "boolean"}, "action": {"type": "string"}, "summary": {"type": "string"}, "data": {"type": "object"}, "warnings": {"type": "array", "items": {"type": "string"}}, "next_steps": {"type": "array", "items": {"type": "string"}}, "request_id": {"type": "string"}, "changes": {"type": "array", "items": {"type": "object"}}, "approval_required": {"type": "boolean"}, "approval": {"type": "object"}}}
    return spec


@ai_router.get("/openapi-chatgpt.json", operation_id="getAiOpenApiChatGpt", include_in_schema=False)
async def ai_openapi_chatgpt(request: Request):
    """GPT Action-ready schema: sanitized READ_ONLY-first subset (<=30 operations), single Bearer security scheme.
    Public document (no secrets, no auth needed to read it) so ChatGPT can import it from URL."""
    from v1_ai_openapi import build_chatgpt_openapi
    cfg = await ai_config()
    return build_chatgpt_openapi(await _public_base_url(request), ERROR_CODES, cfg["mode"])


async def _public_base_url(request: Request) -> str:
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0, "site": 1}) or {}
    base = (cfg.get("site") or {}).get("base_url") or os.environ.get("PUBLIC_BASE_URL") or ""
    if not base:
        proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        if host and "localhost" not in host and not host.startswith("10.") and not host.startswith("127."):
            base = f"{proto}://{host}"
    return base.rstrip("/")


# =====================================================================
# ADMIN CONTROL (panel): metrics, kill switch, mode
# =====================================================================
@ai_router.get("/control", operation_id="getAiControl", include_in_schema=False)
async def ai_control(request: Request, principal=Depends(require("config:read"))):
    cfg = await ai_config()
    m = await metrics_snapshot_shared()
    from database import api_keys_col
    keys = await api_keys_col.find({"revoked_at": None, "internal_test": {"$ne": True}}, {"_id": 0, "key_hash": 0}).sort("created_at", -1).to_list(50)
    last = await ai_actions_col.find_one({"source": "chatgpt"}, {"_id": 0, "timestamp": 1, "action": 1, "ok": 1, "summary": 1}, sort=[("timestamp", -1)])
    last_err = await ai_actions_col.find_one({"ok": False}, {"_id": 0, "timestamp": 1, "action": 1, "summary": 1}, sort=[("timestamp", -1)])
    activity = await ai_actions_col.find({}, {"_id": 0, "before": 0, "after": 0, "input": 0}).sort("timestamp", -1).to_list(30)
    from database import ai_requests_col
    requests_log = await ai_requests_col.find({}, {"_id": 0, "created_dt": 0}).sort("timestamp", -1).to_list(40)
    last_req = await ai_requests_col.find_one({}, {"_id": 0, "created_dt": 0}, sort=[("timestamp", -1)])
    pending = await list_pending_approvals()
    base = await _public_base_url(request)
    ai_keys = [k for k in keys if k.get("role") == "AI_OPERATOR"]
    status = "disabled" if not cfg["enabled"] else ("connected" if (last or last_req) else ("never_used" if ai_keys else "no_key"))
    return {"flags": {"ai_api_enabled": cfg["enabled"], "ai_write_enabled": cfg["write_enabled"], "ai_batch_enabled": cfg["batch_enabled"], "ai_approval_flow_enabled": cfg["approval_enabled"]}, "mode": cfg["mode"],
            "policy": cfg["policy"], "rate_limit_per_min": cfg["rate_limit_per_min"], "metrics": m, "keys": keys, "status": status, "last_request": last, "last_error": last_err,
            "activity": activity, "requests": requests_log, "last_request_any": last_req, "pending_approvals": pending,
            "setup": {"base_url": base, "openapi_url": f"{base}/api/v1/ai/openapi-chatgpt.json", "openapi_full_url": f"{base}/api/v1/ai/openapi.json",
                      "capabilities_url": f"{base}/api/v1/ai/capabilities", "docs_url": f"{base}/api/docs",
                      "gpt_auth": {"type": "API Key", "auth_type": "Bearer", "header": "Authorization: Bearer <API_KEY>"},
                      "auth_header": "Authorization: Bearer <API_KEY>", "auth_alternative": "X-API-Key: <API_KEY>", "recommended_role": "AI_OPERATOR",
                      "read_only_scopes": AI_READ_ONLY_SCOPES, "recommended_scopes": AI_OPERATOR_SCOPES, "optional_scopes": ROLE_OPTIONAL_SCOPES.get("AI_OPERATOR", []), "error_codes": ERROR_CODES}}


class ControlPatch(BaseModel):
    ai_api_enabled: Optional[bool] = None
    ai_write_enabled: Optional[bool] = None
    ai_batch_enabled: Optional[bool] = None
    ai_approval_flow_enabled: Optional[bool] = None
    rate_limit_per_min: Optional[int] = None


@ai_router.patch("/control", operation_id="patchAiControl", include_in_schema=False)
async def ai_control_patch(body: ControlPatch, request: Request, principal=Depends(require("config:write"))):
    from v1_config import get_config
    from v1_versioning import record_version, audit_log
    cfg = await get_config()
    new_cfg = __import__("json").loads(__import__("json").dumps(cfg))
    flags = new_cfg.setdefault("flags", {})
    for k in ("ai_api_enabled", "ai_write_enabled", "ai_batch_enabled", "ai_approval_flow_enabled"):
        v = getattr(body, k)
        if v is not None:
            flags[k] = bool(v)
    if body.rate_limit_per_min is not None:
        new_cfg.setdefault("ai", {}).setdefault("policy", {})["rate_limit_per_min"] = max(10, int(body.rate_limit_per_min))
    new_cfg["updated_at"] = now_iso()
    await config_col.replace_one({"id": "global"}, new_cfg, upsert=True)
    await record_version("config", "global", cfg, new_cfg, actor_of(principal), source="manual", reason="AI control", request_id=request_id_of(request))
    await audit_log(actor_of(principal), "ai_control", "config", "global", body.model_dump(exclude_none=True), request_id_of(request))
    return await ai_control(request, principal)


# =====================================================================
# TEST CONNECTION (admin only, JWT) - creates a temporary key, exercises the flow, deletes it
# =====================================================================
@ai_router.post("/test-connection", operation_id="testChatgptConnection", include_in_schema=False)
async def ai_test_connection(request: Request, principal=Depends(require("keys:manage"))):
    from database import api_keys_col
    raw = generate_api_key()
    kid = str(uuid.uuid4())
    await api_keys_col.insert_one({"id": kid, "name": "__test_connection__", "role": "AI_OPERATOR", "scopes": AI_OPERATOR_SCOPES, "key_hash": hash_key(raw), "prefix": raw[:10],
                                   "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(), "rate_limit_per_min": 60, "active": True, "uses": 0, "created_by": "test", "created_at": now_iso(), "source": "chatgpt", "internal_test": True})
    base = "http://127.0.0.1:8001"
    H = {"X-API-Key": raw, "Content-Type": "application/json"}
    results = []
    def add(name, ok, detail, level="ok"):
        results.append({"check": name, "ok": bool(ok), "detail": detail, "level": "ok" if ok else level})
    loop = asyncio.get_event_loop()
    def get(path, headers=None): return _requests.get(base + path, headers=headers or H, timeout=20)
    def post(path, body, headers=None): return _requests.post(base + path, json=body, headers=headers or H, timeout=30)
    try:
        r = await loop.run_in_executor(None, get, "/api/v1/ai/status")
        add("authentication", r.status_code == 200 and r.json().get("ok"), f"GET /ai/status → {r.status_code}", "error")
        r2 = await loop.run_in_executor(None, get, "/api/v1/ai/status", {"X-API-Key": "ls_wrong"})
        add("invalid_key_rejected", r2.status_code == 401 and r2.json().get("code") == "INVALID_API_KEY", f"chiave errata → {r2.status_code} {r2.json().get('code')}", "error")
        r = await loop.run_in_executor(None, get, "/api/v1/ai/capabilities")
        j = r.json() if r.status_code == 200 else {}
        add("capabilities", r.status_code == 200 and len((j.get("data") or {}).get("capabilities", [])) > 10, f"{len((j.get('data') or {}).get('capabilities', []))} capacità", "error")
        r = await loop.run_in_executor(None, get, "/api/v1/auth/me")
        sc = r.json().get("scopes", []) if r.status_code == 200 else []
        need = ["models:read", "seo:safe_fix", "analytics:read", "rollback:execute"]
        add("scopes", all(s in sc for s in need), f"{len(sc)} scope; richiesti presenti: {all(s in sc for s in need)}", "error")
        r = await loop.run_in_executor(None, get, "/api/v1/auth/keys")
        add("critical_blocked", r.status_code == 403 and r.json().get("detail", {}).get("code") == "CRITICAL_ACTION_BLOCKED", f"GET /auth/keys con API key → {r.status_code}", "warning")
        r = await loop.run_in_executor(None, get, "/api/v1/ai/models")
        items = (r.json().get("data") or {}).get("items", []) if r.status_code == 200 else []
        add("read_models", r.status_code == 200 and len(items) > 0, f"{len(items)} modelle lette", "error")
        r = await loop.run_in_executor(None, post, "/api/v1/ai/analytics/query", {"question": "overview", "period": "7d"})
        add("analytics_read", r.status_code == 200 and r.json().get("ok"), (r.json().get("summary") or "")[:90], "error")
        if items:
            slug = items[0]["slug"]
            r = await loop.run_in_executor(None, post, "/api/v1/ai/models/update", {"model": slug, "changes": {"tag": items[0].get("tag") or ["test"]}, "dry_run": True})
            add("dry_run", r.status_code == 200 and (r.json().get("data") or {}).get("dry_run") is True or (r.json().get("data") or {}).get("changed_fields") == [], f"dry-run update {slug} → {r.status_code}", "error")
            ik = str(uuid.uuid4())
            body = {"model": slug, "dry_run": True}
            r1 = await loop.run_in_executor(None, lambda: _requests.post(base + "/api/v1/ai/models/publish", json=body, headers={**H, "Idempotency-Key": ik}, timeout=30))
            r2 = await loop.run_in_executor(None, lambda: _requests.post(base + "/api/v1/ai/models/publish", json=body, headers={**H, "Idempotency-Key": ik}, timeout=30))
            add("idempotency", r2.headers.get("Idempotent-Replayed") == "true" and r1.text == r2.text, f"replay header: {r2.headers.get('Idempotent-Replayed')}", "warning")
            add("request_id", bool(r1.headers.get("X-Request-ID")), f"X-Request-ID: {r1.headers.get('X-Request-ID', '')[:8]}…", "warning")
            add("rate_limit_headers", bool(r1.headers.get("X-RateLimit-Limit")), f"X-RateLimit-Limit={r1.headers.get('X-RateLimit-Limit')} Remaining={r1.headers.get('X-RateLimit-Remaining')}", "warning")
        r = await loop.run_in_executor(None, get, "/api/v1/ai/openapi.json")
        add("openapi", r.status_code == 200 and len(r.json().get("paths", {})) > 10, f"{len(r.json().get('paths', {})) if r.status_code == 200 else 0} path nella spec AI", "warning")
        cfg = await ai_config()
        add("kill_switch", cfg["enabled"], f"ChatGPT API {'ON' if cfg['enabled'] else 'OFF'} · modalità {cfg['mode']}", "warning")
    except Exception as e:
        add("exception", False, str(e)[:200], "error")
    finally:
        await api_keys_col.delete_one({"id": kid})
    errors = [r for r in results if not r["ok"] and r["level"] == "error"]
    warns = [r for r in results if not r["ok"] and r["level"] == "warning"]
    status = "red" if errors else ("yellow" if warns else "green")
    return {"status": status, "summary": f"{len([r for r in results if r['ok']])}/{len(results)} controlli superati" + (f", {len(errors)} errori" if errors else "") + (f", {len(warns)} avvisi" if warns else ""), "results": results, "tested_at": now_iso()}
