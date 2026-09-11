"""PHASE 12A - TOTAL SITE CONTROL: Capability Registry + Secure Dispatcher.

ChatGPT (or any client) discovers capabilities via GET /api/v1/ai/capabilities and executes them via
POST /api/v1/ai/execute (or /preview = forced dry_run). No natural-language interpretation here: only structured actions.

Flow: action -> registry -> enabled? -> key allow/deny -> kill switch / READ_ONLY -> CRITICAL -> scopes (preview scopes for
dry_run) -> target resolver -> handler (existing service layer, never duplicated business logic) -> approval (REVIEW) ->
audit (ai_actions with session_id) -> standard envelope -> rollback reference.

Absolute limits: no shell, no raw Mongo, no filesystem, no secrets, no code, no auth bypass. Everything is an allowlisted
capability bound to existing services; CRITICAL surface (keys, users, config secrets, backup restore, hard delete) is
never reachable with an API key.
"""
import re
import uuid
import time
import json
import hashlib
import fnmatch
import asyncio
import inspect
import logging
import importlib
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Callable, Awaitable

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict

from database import (models_col, files_col, categories_col, settings_col, config_col, alerts_col, jobs_col, job_runs_col,
                      backups_col, versions_col, ai_actions_col, admins_col, landings_col, seo_issues_col, redirects_col, idempotency_col, api_keys_col, db as _db, now_iso)
from v1_security import resolve_principal, has_scope, actor_of, request_id_of, rate_limit_shared, err
from v1_ai_policy import (redact, ai_config, classify_model_changes, create_approval, list_pending_approvals, approvals_col,
                          missing_scopes_for, preview_scopes, bump, ERROR_CODES)
from v1_models import (resolve_model, create_model, patch_model, transition, validate_model, deep_merge, enrich, workflow_status,
                       ALLOWED_FIELDS, unique_slug)
from v1_versioning import record_version, audit_log, rollback_version, diff_fields

logger = logging.getLogger("capabilities")

caps_router = APIRouter(prefix="/api/v2/ai", tags=["AI v2 - Universal engine"])   # v2 namespace: Phase 10/11 routes under /api/v1/ai stay untouched

SAFE, REVIEW, CRITICAL = "SAFE", "REVIEW_REQUIRED", "CRITICAL"
BOUND, UNBOUND, CRITICAL_BLOCKED = "BOUND", "UNBOUND", "CRITICAL_BLOCKED"


# =====================================================================================================================
# REGISTRY
# =====================================================================================================================
@dataclass
class Capability:
    id: str
    category: str
    description: str
    scopes: List[str]
    risk: str = SAFE
    handler: Optional[Callable[..., Awaitable[dict]]] = None
    dry_run: bool = True
    rollback: bool = True
    batch: bool = False
    requires_approval: bool = False
    target: str = "none"        # model | landing | category | media | alert | job | backup | none
    params: Dict[str, Any] = field(default_factory=dict)
    examples: List[dict] = field(default_factory=list)
    natural: List[str] = field(default_factory=list)
    version: str = "1.0"        # stable capability version (declared, independent from the Python function name)
    read_only: bool = False     # pure read (never a mutation) -> allowed in READ_ONLY and never needs dry_run
    status: str = BOUND         # BOUND | UNBOUND (binding verification failed at startup -> never executable) | CRITICAL_BLOCKED
    unbound_reason: Optional[str] = None
    # scope -> (predicate(params) -> bool, human description): required ONLY when the optional parameter that needs it is present.
    # e.g. models.prepare_complete needs media:upload only if `media` is passed. Never used to widen a key: it only adds requirements.
    conditional_scopes: Dict[str, Any] = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        return self.status == BOUND and self.handler is not None and self.risk != CRITICAL

    def required_scopes(self, params: Optional[dict] = None) -> List[str]:
        """EXECUTE scopes for this call: base scopes + conditional ones whose predicate holds for `params`.
        With params=None (catalog/metadata) only the base scopes are returned."""
        out = list(self.scopes)
        if params is not None:
            for sc, (pred, _desc) in self.conditional_scopes.items():
                try:
                    needed = bool(pred(params or {}))
                except Exception:
                    needed = True   # a broken predicate must never relax a requirement
                if needed and sc not in out:
                    out.append(sc)
        return out

    def required_preview_scopes(self, params: Optional[dict] = None) -> List[str]:
        """PREVIEW (dry_run) scopes: deterministic read-level counterpart of the execute scopes (v1_ai_policy.preview_scopes).
        Read-only capabilities preview with their own scopes."""
        return preview_scopes(self.required_scopes(params))

    def required_parameters(self) -> List[str]:
        return [k for k, spec in (self.params or {}).items() if isinstance(spec, dict) and spec.get("required")]

    def example_parameters(self) -> dict:
        """Ready-to-copy parameters object: first registered example, otherwise a placeholder built from parameters_schema.
        Always contains every required parameter."""
        ex = {}
        for e in self.examples or []:
            if isinstance(e, dict) and isinstance(e.get("parameters"), dict):
                ex = dict(e["parameters"])
                break
        placeholders = {"string": "<string>", "integer": 1, "number": 1.0, "boolean": True, "array": [], "object": {}}
        for k in self.required_parameters():
            if k not in ex:
                spec = self.params.get(k) or {}
                ex[k] = spec.get("example", spec.get("default", placeholders.get(spec.get("type"), "<value>")))
        return ex

    def request_example(self, target: Optional[str] = None) -> dict:
        """The exact previewCapability body to send for this capability (GPT copies it and fills the values)."""
        ex_target = target
        if ex_target is None and self.target != "none":
            for e in self.examples or []:
                if isinstance(e, dict) and e.get("target"):
                    ex_target = e["target"]
                    break
            ex_target = ex_target or f"<{self.target} id/slug/name>"
        body = {"action": self.id, "parameters": self.example_parameters(), "dry_run": True, "reason": "<why>"}
        if ex_target is not None:
            body["target"] = ex_target
        return body

    def public(self) -> dict:
        return {"id": self.id, "capability": self.id, "category": self.category, "description": self.description, "required_scopes": self.scopes,
                "required_parameters": self.required_parameters(), "example_parameters": self.example_parameters(), "request_example": self.request_example(),
                "how_to_call": "POST /api/v2/ai/preview (or /execute) with body {action: id, target?, parameters: {<exactly the property names of parameters_schema>}, dry_run, reason}. "
                               "Required parameters MUST be inside `parameters` (fallback: `parameters_json` = same object as a JSON string).",
                "required_scopes_execute": self.required_scopes(), "required_scopes_preview": self.required_preview_scopes() if not self.read_only else list(self.scopes),
                "conditional_scopes": {sc: desc for sc, (_p, desc) in self.conditional_scopes.items()}, "risk": self.risk,
                "supports_dry_run": self.dry_run and not self.read_only, "supports_rollback": self.rollback and not self.read_only, "supports_batch": self.batch,
                "requires_approval": self.requires_approval or self.risk == REVIEW, "read_only": self.read_only, "target": self.target,
                "parameters_schema": {"type": "object", "properties": self.params}, "examples": self.examples, "natural_references": self.natural,
                "capability_version": self.version, "status": self.status}


def access_for(principal: dict, c: "Capability", params: Optional[dict] = None) -> dict:
    """Separate EXECUTE vs PREVIEW access for a principal (both computed from the same deterministic scope rules).
    execute_access: full | none. preview_access: preview_only | none | n/a (read-only capability or no dry_run support).
    access (legacy): full | preview_only | none."""
    if not c.executable:
        return {"execute_access": "none", "preview_access": "none", "access": "none"}
    exec_missing = missing_scopes_for(principal, ("ai:execute", *c.required_scopes(params)), False)
    execute_access = "full" if not exec_missing else "none"
    if c.read_only or not c.dry_run:
        preview_access = "n/a"
    else:
        prev_missing = missing_scopes_for(principal, ("ai:execute", *c.required_scopes(params)), True)
        preview_access = "preview_only" if not prev_missing else "none"
    legacy = "full" if execute_access == "full" else ("preview_only" if preview_access == "preview_only" else "none")
    return {"execute_access": execute_access, "preview_access": preview_access, "access": legacy,
            "missing_scopes_execute": exec_missing, "missing_scopes_preview": [] if preview_access != "none" else prev_missing}


REGISTRY: Dict[str, Capability] = {}


def cap(id: str, category: str, description: str, scopes: List[str], **kw):
    def deco(fn):
        if id in REGISTRY:
            raise RuntimeError(f"Capability id duplicata nel registry: {id}")   # stable ids: a duplicate is a programming error, caught at import
        REGISTRY[id] = Capability(id=id, category=category, description=description, scopes=scopes, handler=fn, **kw)
        return fn
    return deco


@dataclass
class Ctx:
    principal: dict
    request: Request
    params: dict
    dry: bool = False
    reason: str = ""
    session_id: Optional[str] = None
    approved: bool = False
    expected_updated_at: Optional[str] = None
    target_ref: Optional[str] = None
    target: Optional[dict] = None

    @property
    def actor(self) -> str:
        return actor_of(self.principal)

    @property
    def source(self) -> str:
        return "chatgpt" if self.principal.get("type") == "api_key" else "admin-ai"


def R(summary: str, data: Any = None, changes: Optional[List[dict]] = None, version_ids: Optional[List[str]] = None, before: Any = None, after: Any = None,
      warnings: Optional[List[str]] = None, next_steps: Optional[List[str]] = None, needs_approval: Optional[dict] = None, target: Optional[dict] = None,
      rollback_ref: Optional[str] = None, secondary: Optional[List[dict]] = None) -> dict:
    """`secondary`: non-versioned side effects the capability performed (e.g. file->model link), recorded in the audit so rollback.session can revert them."""
    return {"summary": summary, "data": data if data is not None else {}, "changes": changes or [], "version_ids": version_ids or [], "before": before, "after": after,
            "warnings": warnings or [], "next_steps": next_steps or [], "needs_approval": needs_approval, "target": target, "rollback_ref": rollback_ref, "secondary": secondary or []}


def _tgt(doc: dict, kind: str = "model") -> dict:
    if kind == "model":
        return {"type": "model", "id": doc.get("id"), "slug": doc.get("slug"), "nome": doc.get("nome_artistico") or doc.get("nome"), "etag": doc.get("updated_at")}
    return {"type": kind, "id": doc.get("id"), "slug": doc.get("slug"), "nome": doc.get("nome") or doc.get("titolo") or doc.get("name"), "etag": doc.get("updated_at")}


def _changes_from(before: dict, after: dict, fields: List[str]) -> List[dict]:
    return [{"field": f, "before": before.get(f), "after": after.get(f)} for f in fields]


# =====================================================================================================================
# SHARED HELPERS (all mutations go through existing services + versioning)
# =====================================================================================================================
async def model_change(ctx: Ctx, doc: dict, changes: dict, reason: str, force_review: bool = False) -> dict:
    """Central model mutation: classify SAFE/REVIEW, preview, approval, apply via patch_model (versioned)."""
    cfg = await ai_config()
    cls = classify_model_changes(changes, cfg["policy"])
    level = REVIEW if (force_review or cls["level"] == REVIEW) else SAFE
    preview = await patch_model(doc, changes, ctx.principal, ctx.request, reason, source=ctx.source, dry_run=True, expected_updated_at=ctx.expected_updated_at)
    ch = _changes_from(preview["before"], preview["proposed_after"], preview["changed_fields"])
    if ctx.dry:
        return R(f"Anteprima: {len(ch)} campi cambierebbero su {doc.get('nome_artistico') or doc['slug']} ({level})",
                 {"dry_run": True, "policy": {"level": level, "review_fields": cls["review_fields"]}, "workflow_status_before": preview["workflow_status_before"],
                  "workflow_status_after": preview["workflow_status_after"], "validation": preview["validation"], "approval_required": level == REVIEW, "etag": preview["etag"]},
                 changes=ch, before=preview["before"], after=preview["proposed_after"], target=_tgt(doc),
                 next_steps=["Esegui senza dry_run per applicare" + (" (richiederà approvazione)" if level == REVIEW else "")])
    if level == REVIEW and not ctx.approved:
        return R(f"Modifica di {', '.join(cls['review_fields'] or preview['changed_fields'])} richiede approvazione", {"policy": {"level": level, "review_fields": cls["review_fields"]}},
                 changes=ch, before=preview["before"], after=preview["proposed_after"], target=_tgt(doc),
                 needs_approval={"before": preview["before"], "after": preview["proposed_after"], "expected_updated_at": doc.get("updated_at"), "fields": cls["review_fields"] or preview["changed_fields"]})
    out = await patch_model(doc, changes, ctx.principal, ctx.request, reason, source=ctx.source, dry_run=False, expected_updated_at=ctx.expected_updated_at or (doc.get("updated_at") if ctx.approved else None))
    return R(f"{out.get('nome_artistico') or out['slug']} aggiornata ({', '.join(out.get('changed_fields', [])) or 'nessun campo'}); stato {out['workflow_status']}",
             {"id": out["id"], "slug": out["slug"], "workflow_status": out["workflow_status"], "validation": out.get("validation"), "etag": out["etag"], "version_id": out.get("version_id")},
             changes=ch, version_ids=[out["version_id"]] if out.get("version_id") else [], before=preview["before"], after={k: out.get(k) for k in preview["changed_fields"]},
             target=_tgt(out), rollback_ref=out.get("version_id"), next_steps=[f"Annulla: execute rollback.version {{version_id:'{out.get('version_id')}'}}"])


async def find_media(ref: str) -> dict:
    """Media by id, exact url, seo_name/filename/alt (case-insensitive), unambiguous."""
    ref = (ref or "").strip()
    if not ref:
        raise err(400, "VALIDATION_FAILED", "Riferimento media mancante")
    q_del = {"is_deleted": {"$ne": True}}
    doc = await files_col.find_one({"id": ref, **q_del}, {"_id": 0})
    if not doc:
        doc = await files_col.find_one({"$or": [{"url": ref}, {"variants.web.url": ref}, {"variants.original.url": ref}, {"storage_path": ref.replace("/api/uploads/", "")}], **q_del}, {"_id": 0})
    if not doc:
        rx = {"$regex": re.escape(ref), "$options": "i"}
        cands = await files_col.find({"$or": [{"seo_name": rx}, {"original_filename": rx}, {"alt": rx}, {"title": rx}], **q_del}, {"_id": 0}).to_list(10)
        if len(cands) == 1:
            doc = cands[0]
        elif len(cands) > 1:
            raise HTTPException(status_code=409, detail={"code": "AMBIGUOUS_REFERENCE", "message": "Più media corrispondono", "candidates": [{"id": c["id"], "name": c.get("seo_name") or c.get("original_filename"), "alt": c.get("alt"), "tipo": c.get("tipo")} for c in cands]})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Media '{ref}' non trovato"})
    return doc


def media_urls(f: dict) -> tuple:
    """(url, poster) for a media record using the REAL `variants` contract via v1_media.public_file
    (variants.{web|original|poster}.url are dicts, not strings). Videos use the original, images the web variant."""
    from v1_media import public_file
    pf = public_file(f)
    if f.get("tipo") == "video":
        return pf["url"], pf.get("poster_url") or ""
    return pf["web_url"], ""


def media_summary(f: dict) -> dict:
    url, poster = media_urls(f)
    return {"id": f.get("id"), "tipo": f.get("tipo"), "url": url, "poster_url": poster or None, "name": f.get("seo_name") or f.get("original_filename"),
            "alt": f.get("alt"), "width": f.get("width"), "height": f.get("height"), "duration": f.get("duration"), "size": f.get("size"), "model_id": f.get("model_id"),
            "slot": f.get("slot"), "created_at": f.get("created_at"), "is_deleted": f.get("is_deleted", False)}


# Semantic slots -> technical (slot, side, tipo, index)
SEMANTIC_SLOT_RX = re.compile(r"^(public|secret|pubblic[ao]|segret[ao])_(photo|foto|video)_(\d)$|^(foto|video)_(pubblic[ao]|segret[ao])_(\d)$")
SIMPLE_SLOTS = {"card": ("foto_card", "pubblico", "image"), "cover": ("foto_copertina", "pubblico", "image"), "teaser": ("foto_card_teaser", "pubblico", "image"),
                "secret_hero": ("foto_segreta_hero", "segreto", "image"), "og_image": ("og_image", "pubblico", "image"),
                "filmstrip_public": ("pellicola", "pubblico", "video"), "filmstrip_secret": ("pellicola", "segreto", "video"),
                "filmstrip_poster_public": ("pellicola", "pubblico", "image"), "filmstrip_poster_secret": ("pellicola", "segreto", "image"),
                "message_photo": ("messaggio_foto", "segreto", "image"), "message_video": ("messaggio_video", "segreto", "video"),
                "gallery_public": ("galleria_pubblica", "pubblico", "image"), "gallery_secret": ("galleria_segreta", "segreto", "image"),
                # Italian aliases
                "foto_card": ("foto_card", "pubblico", "image"), "copertina": ("foto_copertina", "pubblico", "image"), "hero_segreta": ("foto_segreta_hero", "segreto", "image"),
                "pellicola_pubblica": ("pellicola", "pubblico", "video"), "pellicola_segreta": ("pellicola", "segreto", "video")}


def parse_slot(slot: str):
    """Return (technical_slot, side, tipo, pair_index|None). Semantic: public_photo_2, secret_video_1, foto_segreta_1 ... Technical slots accepted too."""
    s = (slot or "").strip().lower()
    m = SEMANTIC_SLOT_RX.match(s)
    if m:
        side_tok = m.group(1) or m.group(5)
        tipo_tok = m.group(2) or m.group(4)
        n = int(m.group(3) or m.group(6))
        side = "pubblico" if side_tok.startswith("pub") else "segreto"
        tipo = "video" if tipo_tok == "video" else "image"
        return "pair", side, tipo, n
    if s in SIMPLE_SLOTS:
        tech, side, tipo = SIMPLE_SLOTS[s]
        return tech, side, tipo, None
    from v1_media import SLOTS
    if s in SLOTS and s != "pair":
        return s, "pubblico", "image", None
    raise err(400, "VALIDATION_FAILED", "Slot non valido", slots=sorted(list(SIMPLE_SLOTS) + ["public_photo_1..3", "public_video_1..3", "secret_photo_1..3", "secret_video_1..3"]))


def pair_index_for(doc: dict, tipo: str, n: int) -> Optional[int]:
    """n-th (1-based) pair of the given tipo. None -> a new pair will be created."""
    idxs = [i for i, p in enumerate(doc.get("media_pairs") or []) if p.get("tipo") == tipo]
    return idxs[n - 1] if n - 1 < len(idxs) else None


async def apply_media_to_slot(ctx: Ctx, doc: dict, url: str, slot: str, alt: str = "", poster: str = "", reason: str = "") -> dict:
    """Preview AND execute build the change with the SAME planner (v1_media.slot_changes) and validate/apply it with the
    SAME service (patch_model via model_change): the preview can never differ from what gets applied."""
    from v1_media import slot_changes
    tech, side, tipo, n = parse_slot(slot)
    pidx = pair_index_for(doc, tipo, n) if n else None
    changes = slot_changes(doc, url=url, slot=tech, side=side, tipo=tipo, alt=alt, poster=poster, pair_index=pidx)
    r = await model_change(ctx, doc, changes, reason or f"Media assegnato a {slot}")
    r["data"].update({"slot": slot, "technical_slot": tech, "side": side, "tipo": tipo, "url": url})
    if not ctx.dry and not r.get("needs_approval"):
        r["summary"] = f"Media assegnato a {slot} di {doc.get('nome_artistico') or doc['slug']}"
        r["changes"] = [{"field": f"slot:{slot}", "before": None, "after": url}]
    return r


async def settings_change(ctx: Ctx, changes: dict, reason: str, allowed: set) -> dict:
    cur = await settings_col.find_one({"id": "global"}, {"_id": 0}) or {"id": "global"}
    bad = [k for k in changes if k not in allowed]
    if bad:
        raise err(422, "VALIDATION_FAILED", "Impostazioni non modificabili via API", fields=bad, allowed=sorted(allowed))
    new = deep_merge(cur, changes)
    fields = diff_fields(cur, new)
    ch = _changes_from(cur, new, fields)
    if ctx.dry:
        return R(f"Anteprima impostazioni: {len(fields)} campi", {"dry_run": True}, changes=ch, before={k: cur.get(k) for k in fields}, after={k: new.get(k) for k in fields})
    if not fields:
        return R("Nessuna modifica alle impostazioni", {"unchanged": True})
    new["updated_at"] = now_iso()
    await settings_col.replace_one({"id": "global"}, new, upsert=True)
    ver = await record_version("settings", "global", cur, new, ctx.actor, source=ctx.source, reason=reason, request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
    await audit_log(ctx.actor, "settings.update", "settings", "global", {"fields": fields}, request_id_of(ctx.request), ctx.source)
    return R(f"Impostazioni aggiornate ({', '.join(fields)})", {"version_id": ver["id"], "fields": fields}, changes=ch, version_ids=[ver["id"]], rollback_ref=ver["id"])


# =====================================================================================================================
# CAPABILITIES - MODELS
# =====================================================================================================================
MODEL_FIELDS_DOC = ("nome, nome_artistico, slug(R), frase(R), bio(R), bio_segreta(R), teaser_copy, categorie[], tag[], badge, badge_tipo, onlyfans_url(R), cta_testo, "
                    "tema{preset, colore_primario, colore_secondario, grain, glow, sfondo_stile, frase_attivazione, testo_dopo_click, effetti_touch}, "
                    "messaggio_35s{attivo, ritardo_secondi, testo, foto, video, timer}, seo{title(R), meta_description(R), canonical(R), robots(R), indexable(R), keywords, topics, alt_default, og_image, schema_data}, "
                    "regia{fumo, luci, glow, movimento, audio{traccia, volume, attiva}}, cta_temporizzata{attiva, ritardo_secondi, testo}, social{instagram, tiktok, telegram, x, sito}, "
                    "pellicola_home{attiva, priorita, ordine, pubblico{video_url, poster_url}, segreto{video_url, poster_url}}, ordine, conferma_maggiorenne. (R)=richiede approvazione")


@cap("models.list", "models", "Elenca le modelle con stato workflow, opzionalmente filtrate per stato/categoria/tag.", ["models:read"], read_only=True,
     params={"status": {"type": "string", "enum": ["DRAFT", "INCOMPLETE", "READY", "PUBLISHED", "ARCHIVED", "ERROR"]}, "category": {"type": "string"}, "tag": {"type": "string"}, "limit": {"type": "integer", "default": 100}},
     natural=["quali modelle ci sono", "elenca le modelle in bozza"])
async def _models_list(ctx: Ctx):
    q: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if ctx.params.get("category"):
        q["categorie"] = ctx.params["category"]
    if ctx.params.get("tag"):
        q["tag"] = ctx.params["tag"]
    items = []
    async for m in models_col.find(q, {"_id": 0}).sort("ordine", 1):
        ws = workflow_status(m)
        if ctx.params.get("status") and ws != ctx.params["status"]:
            continue
        items.append({"id": m["id"], "slug": m["slug"], "nome": m.get("nome_artistico") or m.get("nome"), "workflow_status": ws, "stato": m.get("stato"), "categorie": m.get("categorie", []), "tag": m.get("tag", []),
                      "ordine": m.get("ordine"), "badge": m.get("badge"), "etag": m.get("updated_at")})
    items = items[: int(ctx.params.get("limit") or 100)]
    by = {}
    for i in items:
        by[i["workflow_status"]] = by.get(i["workflow_status"], 0) + 1
    return R(f"{len(items)} modelle ({', '.join(f'{v} {k}' for k, v in by.items())})", {"items": items, "by_status": by})


@cap("models.get", "models", "Scheda completa di una modella (tutti i campi del formulario, media, SEO, validazione).", ["models:read"], target="model", read_only=True,
     natural=["mostrami la scheda di Alessia", "dati completi di Aurora Caruso"])
async def _models_get(ctx: Ctx):
    d = enrich(ctx.target)
    d.pop("_id", None)
    return R(f"Scheda di {d.get('nome_artistico') or d['slug']} ({d['workflow_status']})", d, target=_tgt(ctx.target))


@cap("models.create", "models", "Crea una nuova modella in BOZZA con i campi indicati (non pubblica mai). " + MODEL_FIELDS_DOC, ["models:create"],
     params={"nome": {"type": "string", "required": True}, "fields": {"type": "object", "description": "qualsiasi campo del formulario"}},
     examples=[{"action": "models.create", "parameters": {"nome": "Giulia Rossi", "fields": {"categorie": ["more"], "tag": ["estate"], "cta_testo": "ENTRA"}}}],
     natural=["aggiungi una modella", "crea Giulia Rossi"])
async def _models_create(ctx: Ctx):
    nome = (ctx.params.get("nome") or (ctx.params.get("fields") or {}).get("nome") or "").strip()
    if not nome:
        raise err(422, "VALIDATION_FAILED", "Parametro 'nome' obbligatorio")
    data = {"nome": nome, **{k: v for k, v in (ctx.params.get("fields") or {}).items() if k in ALLOWED_FIELDS}}
    data.pop("stato", None)
    if ctx.dry:
        return R(f"Anteprima: verrebbe creata la bozza '{nome}'", {"dry_run": True, "proposed": data, "slug_preview": await unique_slug(nome)}, next_steps=["Esegui senza dry_run per creare la bozza"])
    out = await create_model(data, ctx.principal, ctx.request, ctx.reason or "Creazione modella via ChatGPT")
    ver = await versions_col.find_one({"entity": "model", "entity_id": out["id"]}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)])
    vid = ver["id"] if ver else None
    return R(f"Bozza '{out.get('nome_artistico') or nome}' creata (slug {out['slug']}); stato {out['workflow_status']}", {"id": out["id"], "slug": out["slug"], "workflow_status": out["workflow_status"], "validation": out.get("validation"), "etag": out.get("updated_at"), "version_id": vid},
             changes=[{"field": "model", "before": None, "after": out["slug"]}], version_ids=[vid] if vid else [], target=_tgt(out), rollback_ref=vid,
             next_steps=["models.update per compilare i campi", "media.assign per foto/video", "models.validate per la readiness"])


@cap("models.update", "models", "Modifica QUALSIASI campo del formulario di una modella (deep-merge). " + MODEL_FIELDS_DOC, ["models:update"], target="model", batch=True,
     params={"changes": {"type": "object", "required": True}}, examples=[{"action": "models.update", "target": "Alessia", "parameters": {"changes": {"tag": ["estate", "mare"], "tema": {"preset": "bordeaux"}}}}],
     natural=["cambia la bio di Alessia", "imposta il preset bordeaux ad Aurora", "cambia CTA"])
async def _models_update(ctx: Ctx):
    changes = ctx.params.get("changes") or {k: v for k, v in ctx.params.items() if k in ALLOWED_FIELDS}
    if not changes:
        raise err(422, "VALIDATION_FAILED", "Nessun campo modificabile in 'changes'", allowed=sorted(ALLOWED_FIELDS))
    return await model_change(ctx, ctx.target, changes, ctx.reason or "Aggiornamento via ChatGPT")


def _alias(cap_id, root, description, natural, scope="models:update"):
    @cap(cap_id, "models", description, [scope], target="model", params={"values": {"type": "object", "required": True}}, natural=natural)
    async def _h(ctx: Ctx):
        vals = ctx.params.get("values") or {k: v for k, v in ctx.params.items()}
        return await model_change(ctx, ctx.target, {root: vals} if root else vals, ctx.reason or f"{cap_id} via ChatGPT")
    return _h


_alias("models.set_public_side", None, "Lato Pubblico: frase(R), bio(R), teaser_copy, cta_testo, badge, categorie, tag, foto via media.assign.", ["imposta il lato pubblico"])
_alias("models.set_secret_side", "tema", "Lato Segreto / tema: preset, colore_primario, colore_secondario, grain, glow, sfondo_stile, frase_attivazione, testo_dopo_click, effetti_touch.", ["cambia atmosfera segreta", "glow più forte"])
_alias("models.set_regia", "regia", "Regista Lato Segreto: fumo, luci, glow, movimento, audio{traccia, volume, attiva}.", ["più fumo nel lato segreto", "abbassa il volume"])
_alias("models.set_cta", "cta_temporizzata", "CTA ritardata: attiva, ritardo_secondi, testo (per la CTA principale usa models.update {cta_testo}).", ["cambia la CTA", "CTA dopo 20 secondi"])
_alias("models.set_secret_message", "messaggio_35s", "Messaggio segreto: attivo, ritardo_secondi, testo, foto, video, timer.", ["cambia il messaggio segreto"])
_alias("models.set_social", "social", "Social: instagram, tiktok, telegram, x, sito.", ["aggiungi instagram ad Alessia"])
_alias("models.set_seo", "seo", "SEO della modella: title(R), meta_description(R), canonical(R), robots(R), indexable(R), keywords, topics, alt_default, og_image, schema_data.", ["cambia il title SEO"])


@cap("models.validate", "models", "Readiness alla pubblicazione: requisiti mancanti, warning, stato.", ["models:validate"], target="model", read_only=True, natural=["Alessia è pubblicabile?"])
async def _models_validate(ctx: Ctx):
    v = validate_model(ctx.target)
    ws = workflow_status(ctx.target)
    return R(("Pronta alla pubblicazione" if v["ready"] else f"Non pubblicabile: mancano {len(v['errors'])} requisiti") + f" (stato {ws})",
             {"ready": v["ready"], "workflow_status": ws, "errors": v["errors"], "warnings": v["warnings"], "missing": [e["field"] for e in v["errors"]]}, target=_tgt(ctx.target))


def _transition_cap(cap_id, action, scope, description, natural, risk=SAFE):
    @cap(cap_id, "models", description, [scope], target="model", risk=risk, natural=natural, params={})
    async def _h(ctx: Ctx):
        doc = ctx.target
        if ctx.dry:
            try:
                r = await transition(doc, action, ctx.principal, ctx.request, ctx.reason, dry_run=True)
            except HTTPException as e:
                if isinstance(e.detail, dict) and e.detail.get("code") == "PUBLICATION_BLOCKED":
                    return R("Non pubblicabile: " + ", ".join(e.detail.get("missing", [])), {"dry_run": True, "blocked": True, **e.detail}, target=_tgt(doc), warnings=[x["message"] if isinstance(x, dict) else str(x) for x in e.detail.get("errors", [])][:10])
                raise
            return R(f"Anteprima {action}: {r.get('workflow_status_before', workflow_status(doc))} → {r.get('workflow_status_after', r.get('stato_after', '?'))}", r, target=_tgt(doc))
        if risk == REVIEW and not ctx.approved:
            return R(f"{action} su {doc.get('nome_artistico') or doc['slug']} richiede approvazione", {}, target=_tgt(doc),
                     needs_approval={"before": {"stato": doc.get("stato")}, "after": {"action": action}, "expected_updated_at": doc.get("updated_at"), "fields": ["stato"]})
        out = await transition(doc, action, ctx.principal, ctx.request, ctx.reason or f"{action} via ChatGPT")
        return R(f"{out.get('nome_artistico') or out['slug']}: {action} eseguito → {out.get('workflow_status')}", {"workflow_status": out.get("workflow_status"), "stato": out.get("stato"), "version_id": out.get("version_id"), "etag": out.get("updated_at")},
                 changes=[{"field": "stato", "before": doc.get("stato"), "after": out.get("stato")}], version_ids=[out["version_id"]] if out.get("version_id") else [], target=_tgt(out), rollback_ref=out.get("version_id"))
    return _h


_transition_cap("models.publish", "publish", "models:publish", "Pubblica una modella: passa SEMPRE dal validator (PUBLICATION_BLOCKED se incompleta), nessuna forzatura.", ["pubblica Giulia"])
_transition_cap("models.unpublish", "unpublish", "models:unpublish", "Sospende una modella pubblicata (torna bozza/non visibile in Home).", ["togli Vanessa dalla homepage", "sospendi Alessia"], risk=REVIEW)
_transition_cap("models.archive", "archive", "models:archive", "Archivia una modella (non visibile, recuperabile).", ["archivia Zaira"], risk=REVIEW)
_transition_cap("models.restore", "restore", "models:archive", "Ripristina una modella archiviata in bozza.", ["ripristina Zaira"])


@cap("models.clone", "models", "Clona una modella in una nuova BOZZA (tutti i campi tranne stato/slug/analytics); opzionalmente con nuovo nome e senza media.", ["models:create"], target="model",
     params={"new_name": {"type": "string"}, "include_media": {"type": "boolean", "default": True}}, natural=["duplica Alessia", "clona la scheda di Aurora"])
async def _models_clone(ctx: Ctx):
    src = ctx.target
    new_name = (ctx.params.get("new_name") or f"{src.get('nome_artistico') or src.get('nome')} (copia)").strip()
    data = {k: v for k, v in src.items() if k in ALLOWED_FIELDS and k not in ("slug", "stato", "ordine", "analytics", "nome", "nome_artistico")}
    if ctx.params.get("include_media") is False:
        for k in ("foto_card", "foto_copertina", "foto_card_teaser", "foto_segreta_hero", "media_pairs", "galleria_pubblica", "galleria_segreta"):
            data.pop(k, None)
    data["nome"] = new_name
    data["nome_artistico"] = new_name
    if ctx.dry:
        return R(f"Anteprima: verrebbe creata la bozza '{new_name}' clonando {src['slug']}", {"dry_run": True, "fields": sorted(data.keys()), "slug_preview": await unique_slug(new_name)}, target=_tgt(src))
    out = await create_model(data, ctx.principal, ctx.request, ctx.reason or f"Clone di {src['slug']}")
    await audit_log(ctx.actor, "clone", "model", out["id"], {"from": src["id"]}, request_id_of(ctx.request), ctx.source)
    ver = await versions_col.find_one({"entity": "model", "entity_id": out["id"]}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)])
    return R(f"Clone creato: '{new_name}' (slug {out['slug']}, bozza)", {"id": out["id"], "slug": out["slug"], "from": src["slug"], "workflow_status": out["workflow_status"], "version_id": ver["id"] if ver else None},
             version_ids=[ver["id"]] if ver else [], target=_tgt(out), rollback_ref=ver["id"] if ver else None)


COPY_CONFIG_FIELDS = ["tema", "regia", "cta_temporizzata", "cta_testo", "messaggio_35s", "pellicola_home", "badge", "badge_tipo", "content_overrides"]


@cap("models.copy_config", "models", "Copia la configurazione (tema, regia, CTA, messaggio segreto, pellicola, badge) da una modella sorgente al target. Non copia media/testi/SEO.", ["models:update"], target="model",
     params={"from": {"type": "string", "required": True, "description": "modella sorgente (riferimento naturale)"}, "fields": {"type": "array", "items": {"type": "string"}, "description": f"sottoinsieme di {COPY_CONFIG_FIELDS}"}},
     natural=["clona le impostazioni di Alessia su Giulia", "copia il tema di Aurora su Zaira"])
async def _models_copy_config(ctx: Ctx):
    src = await resolve_model(ctx.params.get("from") or "")
    fields = [f for f in (ctx.params.get("fields") or COPY_CONFIG_FIELDS) if f in COPY_CONFIG_FIELDS]
    changes = {f: src.get(f) for f in fields if src.get(f) is not None}
    if "messaggio_35s" in changes:  # timing/flags only, not the secret media/text of the source
        changes["messaggio_35s"] = {k: v for k, v in (src.get("messaggio_35s") or {}).items() if k in ("attivo", "timer")}   # real schema Messaggio35s: attivo, timer (no secret text/media)
    if "pellicola_home" in changes:
        changes["pellicola_home"] = {k: v for k, v in (src.get("pellicola_home") or {}).items() if k in ("attiva", "priorita")}
    return await model_change(ctx, ctx.target, changes, ctx.reason or f"Configurazione copiata da {src['slug']}")


@cap("models.feature", "models", "Metti in evidenza: badge (es. 'In evidenza'), badge_tipo, ordine in Home (ordine=0 = prima) e/o pellicola attiva.", ["models:feature"], target="model",
     params={"badge": {"type": "string"}, "badge_tipo": {"type": "string"}, "ordine": {"type": "integer"}, "filmstrip": {"type": "boolean"}}, natural=["metti Aurora in evidenza", "porta Alessia in cima"])
async def _models_feature(ctx: Ctx):
    ch: Dict[str, Any] = {}
    if ctx.params.get("badge") is not None:
        ch["badge"] = ctx.params["badge"]
    if ctx.params.get("badge_tipo"):
        ch["badge_tipo"] = ctx.params["badge_tipo"]
    if ctx.params.get("ordine") is not None:
        ch["ordine"] = int(ctx.params["ordine"])
    if ctx.params.get("filmstrip") is not None:
        ch["pellicola_home"] = {"attiva": bool(ctx.params["filmstrip"])}
    if not ch:
        ch = {"badge": "In evidenza", "badge_tipo": "featured", "ordine": 0}
    return await model_change(ctx, ctx.target, ch, ctx.reason or "In evidenza via ChatGPT")


@cap("models.unfeature", "models", "Rimuove badge/evidenza dalla modella.", ["models:feature"], target="model", natural=["togli l'evidenza a Aurora"])
async def _models_unfeature(ctx: Ctx):
    return await model_change(ctx, ctx.target, {"badge": "", "badge_tipo": ""}, ctx.reason or "Evidenza rimossa")


@cap("models.soft_delete", "models", "Eliminazione LOGICA (recuperabile, richiede approvazione). L'eliminazione definitiva non esiste via API.", ["models:archive"], target="model", risk=REVIEW, natural=["elimina la modella di test"])
async def _models_soft_delete(ctx: Ctx):
    doc = ctx.target
    if ctx.dry:
        return R(f"Anteprima: {doc['slug']} verrebbe eliminata logicamente (recuperabile con models.undelete)", {"dry_run": True}, target=_tgt(doc))
    if not ctx.approved:
        return R(f"Eliminazione logica di {doc['slug']} richiede approvazione", {}, target=_tgt(doc), needs_approval={"before": {"is_deleted": False}, "after": {"is_deleted": True}, "expected_updated_at": doc.get("updated_at"), "fields": ["is_deleted"]})
    new = {**doc, "is_deleted": True, "deleted_at": now_iso(), "updated_at": now_iso()}
    await models_col.replace_one({"id": doc["id"]}, new)
    ver = await record_version("model", doc["id"], doc, new, ctx.actor, source=ctx.source, reason=ctx.reason or "Soft delete via ChatGPT", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
    await audit_log(ctx.actor, "soft_delete", "model", doc["id"], {}, request_id_of(ctx.request), ctx.source)
    return R(f"{doc['slug']} eliminata logicamente (recuperabile)", {"version_id": ver["id"]}, changes=[{"field": "is_deleted", "before": False, "after": True}], version_ids=[ver["id"]], target=_tgt(doc), rollback_ref=ver["id"])


@cap("models.undelete", "models", "Recupera una modella eliminata logicamente.", ["models:archive"], params={"model": {"type": "string", "required": True}}, natural=["recupera la modella eliminata"])
async def _models_undelete(ctx: Ctx):
    ref = ctx.params.get("model") or ctx.target_ref
    doc = await resolve_model(ref, include_deleted=True)
    if not doc.get("is_deleted"):
        return R(f"{doc['slug']} non è eliminata", {"unchanged": True}, target=_tgt(doc))
    if ctx.dry:
        return R(f"Anteprima: {doc['slug']} verrebbe recuperata in bozza", {"dry_run": True}, target=_tgt(doc))
    new = {**doc, "is_deleted": False, "stato": "bozza", "updated_at": now_iso()}
    new.pop("deleted_at", None)
    await models_col.replace_one({"id": doc["id"]}, new)
    ver = await record_version("model", doc["id"], doc, new, ctx.actor, source=ctx.source, reason="Undelete via ChatGPT", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
    return R(f"{doc['slug']} recuperata (bozza)", {"version_id": ver["id"]}, version_ids=[ver["id"]], target=_tgt(new), rollback_ref=ver["id"])


@cap("models.tags.add", "models", "Aggiunge tag a una modella (deduplicati, normalizzati in minuscolo).", ["models:update"], target="model", params={"tags": {"type": "array", "items": {"type": "string"}, "required": True}}, natural=["aggiungi il tag estate ad Alessia"])
async def _tags_add(ctx: Ctx):
    cur = [t for t in (ctx.target.get("tag") or [])]
    new = list(dict.fromkeys(cur + [str(t).strip().lower() for t in ctx.params.get("tags", []) if str(t).strip()]))
    return await model_change(ctx, ctx.target, {"tag": new}, ctx.reason or "Tag aggiunti")


@cap("models.tags.remove", "models", "Rimuove tag da una modella.", ["models:update"], target="model", params={"tags": {"type": "array", "items": {"type": "string"}, "required": True}}, natural=["togli il tag test"])
async def _tags_remove(ctx: Ctx):
    rm = {str(t).strip().lower() for t in ctx.params.get("tags", [])}
    return await model_change(ctx, ctx.target, {"tag": [t for t in (ctx.target.get("tag") or []) if str(t).lower() not in rm]}, ctx.reason or "Tag rimossi")


@cap("tags.list", "models", "Tutti i tag in uso con conteggio e possibili duplicati (maiuscole/spazi).", ["models:read"], read_only=True, natural=["quali tag esistono"])
async def _tags_list(ctx: Ctx):
    counts: Dict[str, int] = {}
    norm: Dict[str, set] = {}
    async for m in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0, "tag": 1}):
        for t in m.get("tag") or []:
            counts[t] = counts.get(t, 0) + 1
            norm.setdefault(str(t).strip().lower(), set()).add(t)
    dups = {k: sorted(v) for k, v in norm.items() if len(v) > 1}
    return R(f"{len(counts)} tag in uso, {len(dups)} con varianti duplicate", {"tags": sorted(counts.items(), key=lambda x: -x[1]), "duplicates": dups})


@cap("tags.normalize", "models", "Normalizza un tag su tutte le modelle (rinomina/unisce varianti): {from: 'Estate ', to: 'estate'}.", ["models:update"], batch=True,
     params={"from": {"type": "string", "required": True}, "to": {"type": "string", "required": True}}, natural=["unisci i tag duplicati", "rinomina il tag"])
async def _tags_normalize(ctx: Ctx):
    src, dst = str(ctx.params.get("from", "")).strip(), str(ctx.params.get("to", "")).strip().lower()
    if not src or not dst:
        raise err(422, "VALIDATION_FAILED", "Parametri from/to obbligatori")
    affected, vids = [], []
    async for m in models_col.find({"tag": {"$in": [src, src.lower(), src.strip()]}, "is_deleted": {"$ne": True}}, {"_id": 0}):
        new_tags = list(dict.fromkeys([dst if str(t).strip().lower() == src.strip().lower() else t for t in m.get("tag") or []]))
        if new_tags == m.get("tag"):
            continue
        affected.append(m["slug"])
        if not ctx.dry:
            out = await patch_model(m, {"tag": new_tags}, ctx.principal, ctx.request, f"Tag '{src}' → '{dst}'", source=ctx.source)
            if out.get("version_id"):
                vids.append(out["version_id"])
    return R(f"{'Anteprima: ' if ctx.dry else ''}tag '{src}' → '{dst}' su {len(affected)} modelle", {"affected": affected, "dry_run": ctx.dry}, version_ids=vids)


@cap("models.categories.set", "models", "Imposta le categorie di una modella (slug categorie esistenti).", ["models:update"], target="model", params={"categories": {"type": "array", "items": {"type": "string"}, "required": True}}, natural=["metti Alessia nella categoria more"])
async def _models_categories_set(ctx: Ctx):
    slugs = [str(c).strip() for c in ctx.params.get("categories", [])]
    known = {c["slug"] async for c in categories_col.find({"is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1})}
    unknown = [s for s in slugs if s not in known]
    if unknown:
        raise err(422, "VALIDATION_FAILED", "Categorie inesistenti", unknown=unknown, available=sorted(known))
    return await model_change(ctx, ctx.target, {"categorie": slugs}, ctx.reason or "Categorie impostate")


# =====================================================================================================================
# MEDIA
# =====================================================================================================================
@cap("media.list", "media", "Libreria media: filtra per modella, tipo (image/video), testo (nome/alt), inclusi eliminati se richiesto.", ["media:read"], read_only=True,
     params={"model": {"type": "string"}, "tipo": {"type": "string", "enum": ["image", "video"]}, "q": {"type": "string"}, "include_deleted": {"type": "boolean"}, "limit": {"type": "integer", "default": 50}},
     natural=["quali foto ho caricato", "media di Alessia"])
async def _media_list(ctx: Ctx):
    q: Dict[str, Any] = {}
    if not ctx.params.get("include_deleted"):
        q["is_deleted"] = {"$ne": True}
    if ctx.params.get("model"):
        m = await resolve_model(ctx.params["model"])
        q["model_id"] = m["id"]
    if ctx.params.get("tipo"):
        q["tipo"] = ctx.params["tipo"]
    if ctx.params.get("q"):
        rx = {"$regex": re.escape(ctx.params["q"]), "$options": "i"}
        q["$or"] = [{"seo_name": rx}, {"original_filename": rx}, {"alt": rx}, {"title": rx}]
    items = [media_summary(f) async for f in files_col.find(q, {"_id": 0}).sort("created_at", -1).limit(int(ctx.params.get("limit") or 50))]
    return R(f"{len(items)} media", {"items": items})


@cap("media.find", "media", "Trova un media per id, URL, nome file, ALT (non ambiguo; 409 se più risultati).", ["media:read"], read_only=True, params={"ref": {"type": "string", "required": True}}, natural=["trova la foto rossa di Alessia"])
async def _media_find(ctx: Ctx):
    f = await find_media(ctx.params.get("ref") or ctx.target_ref or "")
    return R(f"Media trovato: {f.get('seo_name') or f.get('original_filename')}", media_summary(f))


@cap("media.inspect", "media", "Dettagli tecnici di un media: dimensioni, durata, codec/varianti, dove è usato.", ["media:read"], read_only=True, params={"ref": {"type": "string", "required": True}})
async def _media_inspect(ctx: Ctx):
    from v1_media import _usages, public_file
    f = await find_media(ctx.params.get("ref") or ctx.target_ref or "")
    return R(f"{f.get('tipo')} {f.get('width')}x{f.get('height')}" + (f", {f.get('duration')}s" if f.get("duration") else ""), {**public_file(f), "usages": await _usages(f)})


@cap("media.upload_url", "media", "Carica un media da URL pubblico (o base64) nella libreria: anti-SSRF, magic bytes, MIME, limiti, varianti. Non assegna a una modella (usa media.assign).", ["media:upload"], rollback=True, dry_run=False,
     params={"url": {"type": "string"}, "base64_data": {"type": "string"}, "content_type": {"type": "string"}, "filename": {"type": "string"}, "alt": {"type": "string"}, "seo_name": {"type": "string"}, "model": {"type": "string"}, "slot": {"type": "string", "description": "se indicato assegna subito allo slot (semantico o tecnico)"}},
     natural=["carica questa foto", "aggiungi il video da questo link"])
async def _media_upload_url(ctx: Ctx):
    from v1_media import fetch_url_bytes, store_media, validate_bytes
    import base64
    if ctx.dry:
        return R("Anteprima upload: nessun file scaricato in dry_run", {"dry_run": True, "would_upload": ctx.params.get("url") or "<base64>", "then_assign": ctx.params.get("slot")})
    model = await resolve_model(ctx.params["model"]) if ctx.params.get("model") else None
    if ctx.params.get("url"):
        # real contract: fetch_url_bytes(url) -> (bytes, mime), SYNC (SSRF/size/magic-byte checks inside) -> run off the event loop
        data, mime = await asyncio.get_event_loop().run_in_executor(None, fetch_url_bytes, ctx.params["url"])
    elif ctx.params.get("base64_data"):
        raw = ctx.params["base64_data"]
        if raw.startswith("data:"):
            head, raw = raw.split(",", 1)
            mime = head.split(";")[0][5:]
        else:
            mime = ctx.params.get("content_type") or "application/octet-stream"
        data = base64.b64decode(raw)
        mime = validate_bytes(data, mime)
    else:
        raise err(422, "VALIDATION_FAILED", "Serve 'url' oppure 'base64_data'")
    # real contract: store_media(data, mime, *, original_filename, alt, seo_name, model_id, slot, actor, request_id) -> public_file(record); no `source` kwarg
    rec = await store_media(data, mime, original_filename=ctx.params.get("filename") or "", alt=ctx.params.get("alt") or "", seo_name=ctx.params.get("seo_name") or "",
                            model_id=model["id"] if model else None, slot=ctx.params.get("slot") or None, actor=ctx.actor, request_id=request_id_of(ctx.request))
    res = R(f"Media caricato: {rec.get('seo_name') or rec.get('original_filename')} ({rec.get('tipo')})", media_summary(rec), changes=[{"field": "file", "before": None, "after": rec["id"]}])
    fver = await versions_col.find_one({"entity": "file", "entity_id": rec["id"]}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)])
    if fver:   # store_media records a `file` creation version -> included so rollback.session soft-deletes the upload too
        res["version_ids"] = [fver["id"]]
        res["rollback_ref"] = fver["id"]
    if model and ctx.params.get("slot"):
        url, poster = media_urls(rec)
        a = await apply_media_to_slot(ctx, model, url, ctx.params["slot"], alt=ctx.params.get("alt") or "", poster=poster, reason=f"Upload + slot {ctx.params['slot']}")
        res["summary"] += f"; assegnato a {ctx.params['slot']} di {model.get('nome_artistico') or model['slug']}"
        res["version_ids"] = (res.get("version_ids") or []) + a["version_ids"]   # file version + model version
        res["rollback_ref"] = a["rollback_ref"] or res.get("rollback_ref")
        res["target"] = a["target"]
        res["data"]["assignment"] = a["data"]
    return res


@cap("media.assign", "media", "Assegna un media della libreria (id/nome/URL) a uno slot della modella. Slot semantici: public_photo_1..3, secret_photo_1..3, public_video_1..2, secret_video_1..2, card, cover, teaser, secret_hero, og_image, filmstrip_public, filmstrip_secret, message_photo, message_video, gallery_public, gallery_secret.",
     ["media:upload", "models:update"], target="model", params={"media": {"type": "string", "required": True}, "slot": {"type": "string", "required": True}, "alt": {"type": "string"}},
     examples=[{"action": "media.assign", "target": "Alessia", "parameters": {"media": "alessia-rossa.jpg", "slot": "secret_photo_2"}}], natural=["metti questa foto come seconda foto segreta di Alessia"])
async def _media_assign(ctx: Ctx):
    f = await find_media(ctx.params.get("media") or "")
    url, poster = media_urls(f)
    r = await apply_media_to_slot(ctx, ctx.target, url, ctx.params["slot"], alt=ctx.params.get("alt") or f.get("alt") or "", poster=poster, reason=ctx.reason or f"Media {f['id']} → {ctx.params['slot']}")
    if not ctx.dry and not r.get("needs_approval") and (f.get("model_id") != ctx.target["id"] or f.get("slot") != ctx.params["slot"]):
        before = {"model_id": f.get("model_id"), "slot": f.get("slot")}
        after = {"model_id": ctx.target["id"], "slot": ctx.params["slot"]}
        await files_col.update_one({"id": f["id"]}, {"$set": {**after, "updated_at": now_iso()}})
        r["secondary"] = [{"kind": "file_link", "file_id": f["id"], "before": before, "after": after}]   # reverted by rollback.session
    return r


@cap("media.replace_slot", "media", "Sostituisce il media presente in uno slot con un altro media della libreria (alias di media.assign sullo stesso slot; il precedente resta in libreria).", ["media:replace", "models:update"], target="model",
     params={"media": {"type": "string", "required": True}, "slot": {"type": "string", "required": True}}, natural=["sostituisci la seconda foto segreta"])
async def _media_replace_slot(ctx: Ctx):
    return await _media_assign(ctx)


@cap("media.remove_from_slot", "media", "Svuota uno slot della modella (il file resta in libreria).", ["models:update"], target="model", params={"slot": {"type": "string", "required": True}}, natural=["togli la terza foto pubblica"])
async def _media_remove(ctx: Ctx):
    doc = ctx.target
    tech, side, tipo, n = parse_slot(ctx.params["slot"])
    ch: Dict[str, Any] = {}
    if tech == "pair":
        idx = pair_index_for(doc, tipo, n or 1)
        if idx is None:
            return R("Slot già vuoto", {"unchanged": True}, target=_tgt(doc))
        pairs = [dict(p) for p in doc.get("media_pairs") or []]
        pairs[idx][side] = {"tipo": tipo, "url": "", "poster": "", "alt": ""}
        ch["media_pairs"] = pairs
    elif tech in ("foto_card", "foto_copertina", "foto_card_teaser", "foto_segreta_hero"):
        ch[tech] = ""
    elif tech == "og_image":
        ch["seo"] = {"og_image": ""}
    elif tech == "pellicola":
        ph = dict(ctx.target.get("pellicola_home") or {})
        ph[side] = {"video_url": "", "poster_url": ""}   # real schema: pellicola_home.{pubblico|segreto}.{video_url,poster_url}
        ch["pellicola_home"] = ph
    elif tech in ("messaggio_foto", "messaggio_video"):
        ch["messaggio_35s"] = {"foto" if tech == "messaggio_foto" else "video": ""}
    else:
        ch[tech] = []
    return await model_change(ctx, doc, ch, ctx.reason or f"Slot {ctx.params['slot']} svuotato")


@cap("media.reorder_pairs", "media", "Riordina le coppie media (griglia 2x3) passando la lista ordinata di pair_id o indici attuali.", ["models:update"], target="model",
     params={"order": {"type": "array", "items": {"type": "string"}, "required": True}}, natural=["riordina le foto di Alessia"])
async def _media_reorder_pairs(ctx: Ctx):
    pairs = [dict(p) for p in ctx.target.get("media_pairs") or []]
    order = ctx.params.get("order") or []
    new = []
    for o in order:
        p = next((x for x in pairs if x.get("id") == o), None)
        if p is None and str(o).isdigit() and int(o) < len(pairs):
            p = pairs[int(o)]
        if p is None or p in new:
            raise err(422, "VALIDATION_FAILED", f"Coppia '{o}' non valida o duplicata", pairs=[{"id": x.get("id"), "tipo": x.get("tipo")} for x in pairs])
        new.append(p)
    new += [p for p in pairs if p not in new]
    return await model_change(ctx, ctx.target, {"media_pairs": new}, ctx.reason or "Coppie media riordinate")


@cap("media.update", "media", "Aggiorna ALT, nome SEO, titolo, metadata di un media (versionato).", ["media:update"], params={"media": {"type": "string", "required": True}, "alt": {"type": "string"}, "seo_name": {"type": "string"}, "title": {"type": "string"}, "metadata": {"type": "object"}}, natural=["metti l'ALT alla foto"])
async def _media_update(ctx: Ctx):
    from v1_media import patch_media, MediaPatch
    f = await find_media(ctx.params.get("media") or ctx.target_ref or "")
    body = MediaPatch(**{k: v for k, v in ctx.params.items() if k in ("alt", "seo_name", "title", "metadata")})
    fields = [k for k in ("alt", "seo_name", "title", "metadata") if getattr(body, k) is not None]
    ch = [{"field": k, "before": f.get(k), "after": getattr(body, k)} for k in fields]
    if ctx.dry:
        return R(f"Anteprima metadata media: {', '.join(fields)}", {"dry_run": True}, changes=ch)
    out = await patch_media(f["id"], body, ctx.request, ctx.principal)
    ver = await versions_col.find_one({"entity": "file", "entity_id": f["id"]}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)])
    return R(f"Media aggiornato ({', '.join(fields)})", out, changes=ch, version_ids=[ver["id"]] if ver else [], rollback_ref=ver["id"] if ver else None)


@cap("media.optimize", "media", "Rigenera le varianti (web/mobile/thumb o poster/mobile) di un media dall'originale.", ["media:optimize"], rollback=False, params={"media": {"type": "string", "required": True}}, natural=["ottimizza questo video"])
async def _media_optimize(ctx: Ctx):
    from v1_media import optimize_media
    f = await find_media(ctx.params.get("media") or ctx.target_ref or "")
    if ctx.dry:
        return R(f"Anteprima: verrebbero rigenerate le varianti di {f.get('seo_name') or f['id']}", {"dry_run": True, "variants_now": list((f.get("variants") or {}).keys())})
    out = await optimize_media(f["id"], ctx.request, ctx.principal)
    return R("Varianti rigenerate", out)


@cap("media.optimize_all", "media", "Ottimizza tutti i media (o quelli di una modella / di un tipo). Batch con errori parziali; async consigliato.", ["media:optimize"], batch=True, rollback=False,
     params={"model": {"type": "string"}, "tipo": {"type": "string"}, "limit": {"type": "integer", "default": 50}}, natural=["ottimizza tutti i video"])
async def _media_optimize_all(ctx: Ctx):
    from v1_media import optimize_media
    q: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if ctx.params.get("model"):
        q["model_id"] = (await resolve_model(ctx.params["model"]))["id"]
    if ctx.params.get("tipo"):
        q["tipo"] = ctx.params["tipo"]
    cfg = await ai_config()
    lim = min(int(ctx.params.get("limit") or 50), int(cfg["policy"].get("max_batch", 50)))
    files = await files_col.find(q, {"_id": 0, "id": 1, "seo_name": 1, "tipo": 1}).limit(lim).to_list(lim)
    results = []
    for f in files:
        if ctx.dry:
            results.append({"id": f["id"], "would_optimize": True})
            continue
        try:
            await optimize_media(f["id"], ctx.request, ctx.principal)
            results.append({"id": f["id"], "ok": True})
        except Exception as e:
            results.append({"id": f["id"], "ok": False, "error": str(e)[:160]})
    okn = len([r for r in results if r.get("ok") or r.get("would_optimize")])
    return R(f"{'Anteprima: ' if ctx.dry else ''}{okn}/{len(results)} media ottimizzati", {"results": results, "failed": [r for r in results if r.get("ok") is False]})


@cap("media.soft_delete", "media", "Elimina logicamente un media (recuperabile). Blocca se usato da una modella pubblicata. Richiede approvazione.", ["media:delete"], risk=REVIEW, params={"media": {"type": "string", "required": True}}, natural=["elimina questa foto"])
async def _media_soft_delete(ctx: Ctx):
    from v1_media import delete_media, _usages
    f = await find_media(ctx.params.get("media") or ctx.target_ref or "")
    uses = await _usages(f)
    if ctx.dry:
        return R(f"Anteprima: {f.get('seo_name') or f['id']} verrebbe eliminato logicamente" + (f" — ATTENZIONE usato in {len(uses)} slot" if uses else ""), {"dry_run": True, "usages": uses}, warnings=[f"Usato da {u.get('slug')}" for u in uses])
    if not ctx.approved:
        return R("Eliminazione media richiede approvazione", {"usages": uses}, needs_approval={"before": {"is_deleted": False}, "after": {"is_deleted": True}, "fields": ["is_deleted"], "file_id": f["id"]})
    out = await delete_media(f["id"], ctx.request, False, ctx.principal)
    ver = await versions_col.find_one({"entity": "file", "entity_id": f["id"]}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)])
    return R("Media eliminato logicamente", out, changes=[{"field": "is_deleted", "before": False, "after": True}], version_ids=[ver["id"]] if ver else [], rollback_ref=ver["id"] if ver else None)


@cap("media.restore", "media", "Recupera un media eliminato logicamente.", ["media:delete"], params={"media": {"type": "string", "required": True}}, natural=["recupera la foto eliminata"])
async def _media_restore(ctx: Ctx):
    ref = ctx.params.get("media") or ctx.target_ref or ""
    f = await files_col.find_one({"id": ref, "is_deleted": True}, {"_id": 0}) or await files_col.find_one({"$or": [{"seo_name": ref}, {"original_filename": ref}], "is_deleted": True}, {"_id": 0})
    if not f:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Media eliminato non trovato"})
    if ctx.dry:
        return R("Anteprima: media verrebbe recuperato", {"dry_run": True, **media_summary(f)})
    new = {**f, "is_deleted": False}
    new.pop("deleted_at", None)
    await files_col.update_many({"$or": [{"id": f["id"]}, {"parent_id": f["id"]}]}, {"$set": {"is_deleted": False}, "$unset": {"deleted_at": ""}})
    ver = await record_version("file", f["id"], f, new, ctx.actor, source=ctx.source, reason="Restore media", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
    return R("Media recuperato", media_summary(new), version_ids=[ver["id"]], rollback_ref=ver["id"])


@cap("media.broken", "media", "Media mancanti o non raggiungibili secondo l'ultimo health check (con classificazione warning/missing).", ["media:read"], read_only=True, natural=["dimmi quali media sono rotti"])
async def _media_broken(ctx: Ctx):
    from v1_health import check_media
    c = await check_media()
    return R(c["detail"], {k: v for k, v in c.items() if k != "name"})


# =====================================================================================================================
# HOMEPAGE / FILMSTRIP / SETTINGS
# =====================================================================================================================
@cap("homepage.reorder_models", "homepage", "Imposta l'ordine delle modelle in Home (lista di riferimenti, dal primo all'ultimo; le altre seguono).", ["models:feature"], batch=True,
     params={"order": {"type": "array", "items": {"type": "string"}, "required": True}}, natural=["riordina la homepage", "metti Aurora prima di Alessia"])
async def _home_reorder(ctx: Ctx):
    docs = [await resolve_model(r) for r in ctx.params.get("order") or []]
    ids = [d["id"] for d in docs]
    rest = [m async for m in models_col.find({"is_deleted": {"$ne": True}, "id": {"$nin": ids}}, {"_id": 0}).sort("ordine", 1)]
    final = docs + rest
    ch = [{"field": f"ordine:{d['slug']}", "before": d.get("ordine"), "after": i} for i, d in enumerate(final) if d.get("ordine") != i]
    if ctx.dry:
        return R(f"Anteprima ordine Home: {[d['slug'] for d in final]}", {"dry_run": True, "order": [d["slug"] for d in final]}, changes=ch)
    vids = []
    for i, d in enumerate(final):
        if d.get("ordine") != i:
            out = await patch_model(d, {"ordine": i}, ctx.principal, ctx.request, "Riordino Home", source=ctx.source)
            if out.get("version_id"):
                vids.append(out["version_id"])
    return R(f"Ordine Home aggiornato ({len(vids)} modelle spostate)", {"order": [d["slug"] for d in final]}, changes=ch, version_ids=vids)


FILMSTRIP_KEYS = {"attiva", "titolo", "sottotitolo", "velocita", "max_video_attivi", "seconda_fila", "pausa_su_touch", "nomi_sempre_visibili", "inserisci_dopo_n"}
SETTINGS_KEYS = {"brand_name", "site_description", "footer_contatti", "global_switch_default", "home_pellicola"}


@cap("filmstrip.get_config", "homepage", "Configurazione FilmStrip (pellicola Home) e lista video attivi con ordine.", ["settings:read"], read_only=True, natural=["com'è configurata la pellicola"])
async def _filmstrip_get(ctx: Ctx):
    s = await settings_col.find_one({"id": "global"}, {"_id": 0, "home_pellicola": 1}) or {}
    items = []
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "nome_artistico": 1, "pellicola_home": 1, "ordine": 1}):
        ph = m.get("pellicola_home") or {}
        pub, sec = (ph.get("pubblico") or {}), (ph.get("segreto") or {})   # real schema: PellicolaHome.pubblico/segreto -> PellicolaSide{video_url, poster_url}
        items.append({"slug": m["slug"], "nome": m.get("nome_artistico"), "attiva": ph.get("attiva", True), "priorita": ph.get("priorita", 0), "ordine": ph.get("ordine", m.get("ordine")),
                      "video_pubblico": bool(pub.get("video_url")), "video_segreto": bool(sec.get("video_url")), "poster_pubblico": bool(pub.get("poster_url")), "poster_segreto": bool(sec.get("poster_url"))})
    items.sort(key=lambda x: (-(x["priorita"] or 0), x["ordine"] or 0))
    return R(f"FilmStrip: {len([i for i in items if i['attiva'] and (i['video_pubblico'] or i['video_segreto'])])} video attivi", {"config": s.get("home_pellicola") or {}, "models": items})


@cap("filmstrip.set_config", "homepage", f"Modifica la configurazione FilmStrip: {sorted(FILMSTRIP_KEYS)} (max_video_attivi 4-12).", ["settings:update"], params={"config": {"type": "object", "required": True}}, natural=["metti 6 video nella pellicola", "disattiva la seconda fila"])
async def _filmstrip_set(ctx: Ctx):
    cfg = {k: v for k, v in (ctx.params.get("config") or ctx.params).items() if k in FILMSTRIP_KEYS}
    if "max_video_attivi" in cfg:
        cfg["max_video_attivi"] = max(4, min(12, int(cfg["max_video_attivi"])))
    if not cfg:
        raise err(422, "VALIDATION_FAILED", "Nessuna chiave FilmStrip valida", allowed=sorted(FILMSTRIP_KEYS))
    return await settings_change(ctx, {"home_pellicola": cfg}, ctx.reason or "FilmStrip config", SETTINGS_KEYS)


@cap("filmstrip.set_model", "homepage", "FilmStrip per modella: attiva, priorita, ordine (video/poster via media.assign slot filmstrip_public/filmstrip_secret).", ["models:feature"], target="model",
     params={"attiva": {"type": "boolean"}, "priorita": {"type": "integer"}, "ordine": {"type": "integer"}}, natural=["togli Vanessa dalla pellicola", "metti il video di Aurora per primo"])
async def _filmstrip_model(ctx: Ctx):
    ph = {k: ctx.params[k] for k in ("attiva", "priorita", "ordine") if k in ctx.params}
    if not ph:
        raise err(422, "VALIDATION_FAILED", "Indica attiva/priorita/ordine")
    return await model_change(ctx, ctx.target, {"pellicola_home": ph}, ctx.reason or "FilmStrip modella")


@cap("filmstrip.reorder", "homepage", "Riordina i video della pellicola (lista di modelle dal primo all'ultimo).", ["models:feature"], batch=True, params={"order": {"type": "array", "items": {"type": "string"}, "required": True}}, natural=["riordina il FilmStrip"])
async def _filmstrip_reorder(ctx: Ctx):
    docs = [await resolve_model(r) for r in ctx.params.get("order") or []]
    ch, vids = [], []
    for i, d in enumerate(docs):
        cur = (d.get("pellicola_home") or {}).get("ordine")
        ch.append({"field": f"pellicola_home.ordine:{d['slug']}", "before": cur, "after": i})
        if not ctx.dry and cur != i:
            out = await patch_model(d, {"pellicola_home": {"ordine": i, "priorita": len(docs) - i}}, ctx.principal, ctx.request, "Riordino FilmStrip", source=ctx.source)
            if out.get("version_id"):
                vids.append(out["version_id"])
    return R(f"{'Anteprima ' if ctx.dry else ''}ordine FilmStrip: {[d['slug'] for d in docs]}", {"order": [d["slug"] for d in docs]}, changes=ch, version_ids=vids)


@cap("settings.get", "settings", "Impostazioni sito (brand, descrizione, footer, switch predefinito Lato Pubblico/Segreto, FilmStrip).", ["settings:read"], read_only=True, natural=["mostra le impostazioni"])
async def _settings_get(ctx: Ctx):
    s = await settings_col.find_one({"id": "global"}, {"_id": 0}) or {}
    return R("Impostazioni correnti", {k: s.get(k) for k in SETTINGS_KEYS | {"updated_at"}})


@cap("settings.update", "settings", f"Modifica impostazioni business: {sorted(SETTINGS_KEYS)}.", ["settings:update"], params={"changes": {"type": "object", "required": True}}, natural=["cambia la descrizione del sito", "switch predefinito su segreto"])
async def _settings_update(ctx: Ctx):
    return await settings_change(ctx, ctx.params.get("changes") or {k: v for k, v in ctx.params.items() if k in SETTINGS_KEYS}, ctx.reason or "Impostazioni via ChatGPT", SETTINGS_KEYS)


AI_MANAGEABLE_CONFIG = {"site.base_url", "seo.defaults", "analytics.thresholds", "media.limits", "ai.policy.approval_ttl_min", "ai.policy.max_batch"}
AI_MANAGEABLE_FLAGS = {"seo_autopilot", "self_healing", "landing_engine", "ab_testing", "italy_engine"}
NEVER_FLAGS = {"ai_api_enabled", "ai_write_enabled", "ai_batch_enabled", "ai_approval_flow_enabled", "public_landing_routes", "domain_it_migration", "ssr_prerender", "search_console_sync", "ga4_production", "super_api", "webhooks", "telegram"}


@cap("config.get", "settings", "Configurazione operativa (senza segreti): site, seo defaults, analytics thresholds, media limits, policy AI, flag.", ["config:read"], read_only=True)
async def _config_get(ctx: Ctx):
    c = await config_col.find_one({"id": "global"}, {"_id": 0}) or {}
    return R("Configurazione corrente (redatta)", redact({k: v for k, v in c.items() if k not in ("webhooks",)}))


def _get_path(d: dict, path: str):
    cur = d
    for p in path.split("."):
        cur = (cur or {}).get(p) if isinstance(cur, dict) else None
    return cur


def _set_path(d: dict, path: str, value):
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


@cap("config.update", "settings", f"Modifica SOLO chiavi di configurazione AI_MANAGEABLE: {sorted(AI_MANAGEABLE_CONFIG)} (dot-path → valore). site.base_url richiede approvazione.", ["config:update"], risk=SAFE,
     params={"changes": {"type": "object", "required": True, "description": "{'site.base_url': 'https://...'}"}}, natural=["imposta la base url", "alza il campione minimo analytics"])
async def _config_update(ctx: Ctx):
    changes = ctx.params.get("changes") or {}
    bad = [k for k in changes if not any(k == a or k.startswith(a + ".") for a in AI_MANAGEABLE_CONFIG)]
    if bad:
        raise err(403, "CRITICAL_ACTION_BLOCKED", "Chiavi di configurazione non gestibili via AI", keys=bad, allowed=sorted(AI_MANAGEABLE_CONFIG))
    cur = await config_col.find_one({"id": "global"}, {"_id": 0}) or {"id": "global"}
    import copy
    new = copy.deepcopy(cur)
    ch = []
    for k, v in changes.items():
        ch.append({"field": k, "before": _get_path(cur, k), "after": v})
        _set_path(new, k, v)
    review = any(k.startswith("site.base_url") for k in changes)
    if ctx.dry:
        return R(f"Anteprima config: {list(changes)}", {"dry_run": True, "approval_required": review}, changes=ch)
    if review and not ctx.approved:
        return R("site.base_url richiede approvazione", {}, changes=ch, needs_approval={"before": {c["field"]: c["before"] for c in ch}, "after": changes, "fields": list(changes)})
    new["updated_at"] = now_iso()
    await config_col.replace_one({"id": "global"}, new, upsert=True)
    ver = await record_version("config", "global", cur, new, ctx.actor, source=ctx.source, reason=ctx.reason or "Config via ChatGPT", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
    await audit_log(ctx.actor, "config.update", "config", "global", {"keys": list(changes)}, request_id_of(ctx.request), ctx.source)
    return R(f"Configurazione aggiornata ({', '.join(changes)})", {"version_id": ver["id"]}, changes=ch, version_ids=[ver["id"]], rollback_ref=ver["id"])


@cap("flags.list", "settings", "Tutti i feature flag con indicazione AI_MANAGEABLE / protetti.", ["config:read"], read_only=True, natural=["quali flag sono attivi"])
async def _flags_list(ctx: Ctx):
    c = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    flags = c.get("flags") or {}
    return R(f"{len(flags)} flag ({len(AI_MANAGEABLE_FLAGS & set(flags))} gestibili via AI)", {"flags": flags, "ai_manageable": sorted(AI_MANAGEABLE_FLAGS), "protected": sorted(NEVER_FLAGS)})


@cap("flags.set", "settings", f"Imposta un flag AI_MANAGEABLE ({sorted(AI_MANAGEABLE_FLAGS)}); richiede approvazione. I flag di sicurezza/kill switch/deploy sono sempre bloccati.", ["config:update"], risk=REVIEW,
     params={"flag": {"type": "string", "required": True}, "value": {"type": "boolean", "required": True}}, natural=["attiva il SEO autopilot"])
async def _flags_set(ctx: Ctx):
    name, value = ctx.params.get("flag"), bool(ctx.params.get("value"))
    if name in NEVER_FLAGS or name not in AI_MANAGEABLE_FLAGS:
        raise err(403, "CRITICAL_ACTION_BLOCKED", f"Il flag '{name}' non è gestibile via AI", ai_manageable=sorted(AI_MANAGEABLE_FLAGS))
    c = await config_col.find_one({"id": "global"}, {"_id": 0}) or {"id": "global", "flags": {}}
    before = (c.get("flags") or {}).get(name)
    ch = [{"field": f"flags.{name}", "before": before, "after": value}]
    if ctx.dry:
        return R(f"Anteprima flag {name}: {before} → {value}", {"dry_run": True, "approval_required": True}, changes=ch)
    if not ctx.approved:
        return R(f"Flag {name} richiede approvazione", {}, changes=ch, needs_approval={"before": {name: before}, "after": {name: value}, "fields": [name]})
    new = {**c, "flags": {**(c.get("flags") or {}), name: value}, "updated_at": now_iso()}
    await config_col.replace_one({"id": "global"}, new, upsert=True)
    ver = await record_version("config", "global", c, new, ctx.actor, source=ctx.source, reason=f"Flag {name}", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
    return R(f"Flag {name} = {value}", {"version_id": ver["id"]}, changes=ch, version_ids=[ver["id"]], rollback_ref=ver["id"])


# =====================================================================================================================
# CATEGORIES
# =====================================================================================================================
async def resolve_category(ref: str) -> dict:
    ref = (ref or "").strip()
    doc = await categories_col.find_one({"$or": [{"id": ref}, {"slug": ref.lower()}], "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        rx = {"$regex": f"^{re.escape(ref)}$", "$options": "i"}
        doc = await categories_col.find_one({"nome": rx, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Categoria '{ref}' non trovata"})
    return doc


# Real contract = schemas.CategoryIn (routes_admin.admin_create_category / admin_update_category). Public side lists only stato == "pubblicata".
CATEGORY_FIELDS = {"nome", "slug", "descrizione", "seo_title", "meta_description", "immagine", "ordine", "indicizzabile", "stato"}
CATEGORY_STATES = {"pubblicata", "bozza"}


async def category_change(ctx: Ctx, doc: dict, changes: dict, reason: str) -> dict:
    bad = [k for k in changes if k not in CATEGORY_FIELDS]
    if bad:
        raise err(422, "VALIDATION_FAILED", "Campi categoria non validi", fields=bad, allowed=sorted(CATEGORY_FIELDS))
    if "stato" in changes and changes["stato"] not in CATEGORY_STATES:
        raise err(422, "VALIDATION_FAILED", "stato categoria non valido", allowed=sorted(CATEGORY_STATES))
    if "slug" in changes:
        from sanitize import slugify
        changes = {**changes, "slug": slugify(changes["slug"] or doc.get("nome") or "")}
    new = deep_merge(doc, changes)
    fields = diff_fields(doc, new)
    ch = _changes_from(doc, new, fields)
    # hiding a published category (stato pubblicata -> bozza) changes the public site like slug/nome do -> REVIEW
    review = any(f in ("slug", "nome") for f in fields) or (doc.get("stato") == "pubblicata" and new.get("stato") != "pubblicata")
    if ctx.dry:
        return R(f"Anteprima categoria {doc['slug']}: {fields}", {"dry_run": True, "approval_required": review}, changes=ch, target=_tgt(doc, "category"))
    if not fields:
        return R("Nessuna modifica", {"unchanged": True}, target=_tgt(doc, "category"))
    if review and not ctx.approved:
        return R(f"Modifica {fields} della categoria richiede approvazione", {}, changes=ch, target=_tgt(doc, "category"), needs_approval={"before": {f: doc.get(f) for f in fields}, "after": {f: new.get(f) for f in fields}, "fields": fields, "expected_updated_at": doc.get("updated_at")})
    new["updated_at"] = now_iso()
    await categories_col.replace_one({"id": doc["id"]}, new)
    ver = await record_version("category", doc["id"], doc, new, ctx.actor, source=ctx.source, reason=reason, request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
    if "slug" in fields:
        from v1_seo import ensure_redirect
        await ensure_redirect(f"/categorie/{doc['slug']}", f"/categorie/{new['slug']}", ctx.actor, "slug_change")
    await audit_log(ctx.actor, "category.update", "category", doc["id"], {"fields": fields}, request_id_of(ctx.request), ctx.source)
    return R(f"Categoria {new['slug']} aggiornata ({', '.join(fields)})", {"id": doc["id"], "slug": new["slug"], "version_id": ver["id"]}, changes=ch, version_ids=[ver["id"]], target=_tgt(new, "category"), rollback_ref=ver["id"])


@cap("categories.list", "categories", "Elenco categorie con numero modelle assegnate.", ["categories:read"], read_only=True, natural=["quali categorie ci sono"])
async def _cat_list(ctx: Ctx):
    cats = [c async for c in categories_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}).sort("ordine", 1)]
    for c in cats:
        c["models_count"] = await models_col.count_documents({"categorie": c["slug"], "is_deleted": {"$ne": True}})
    return R(f"{len(cats)} categorie", {"items": cats})


@cap("categories.create", "categories", "Crea una categoria (nome, slug opzionale, descrizione, seo_title, meta_description, immagine, ordine, indicizzabile, stato pubblicata|bozza).", ["categories:write"],
     params={"nome": {"type": "string", "required": True}, "slug": {"type": "string"}, "descrizione": {"type": "string"}, "seo_title": {"type": "string"}, "meta_description": {"type": "string"}, "immagine": {"type": "string"},
             "ordine": {"type": "integer"}, "indicizzabile": {"type": "boolean"}, "stato": {"type": "string", "enum": ["pubblicata", "bozza"]}}, natural=["crea la categoria Estate"])
async def _cat_create(ctx: Ctx):
    from sanitize import slugify
    from schemas import CategoryIn
    nome = (ctx.params.get("nome") or "").strip()
    if not nome:
        raise err(422, "VALIDATION_FAILED", "nome obbligatorio")
    try:
        data = CategoryIn(**{k: v for k, v in ctx.params.items() if k in CATEGORY_FIELDS}).model_dump()   # same schema/validation as the admin form
    except Exception as e:
        raise err(422, "VALIDATION_FAILED", "Dati categoria non validi", errors=str(e)[:400])
    if data.get("stato") not in CATEGORY_STATES:
        raise err(422, "VALIDATION_FAILED", "stato categoria non valido", allowed=sorted(CATEGORY_STATES))
    slug = slugify(data.get("slug") or nome)   # same slugify as routes_admin.admin_create_category
    if await categories_col.find_one({"slug": slug, "is_deleted": {"$ne": True}}):
        raise err(409, "CONFLICT", f"Slug categoria '{slug}' già esistente")
    doc = {**data, "id": str(uuid.uuid4()), "slug": slug, "created_at": now_iso(), "updated_at": now_iso()}
    if ctx.dry:
        return R(f"Anteprima: categoria '{nome}' ({slug})", {"dry_run": True, "proposed": doc})
    await categories_col.insert_one(dict(doc))
    ver = await record_version("category", doc["id"], None, doc, ctx.actor, source=ctx.source, reason="Creazione categoria", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
    return R(f"Categoria '{nome}' creata ({slug})", {"id": doc["id"], "slug": slug, "version_id": ver["id"]}, version_ids=[ver["id"]], target=_tgt(doc, "category"), rollback_ref=ver["id"])


@cap("categories.update", "categories", f"Modifica una categoria: {sorted(CATEGORY_FIELDS)} (nome/slug richiedono approvazione).", ["categories:write"], target="category", params={"changes": {"type": "object", "required": True}}, natural=["cambia la descrizione della categoria more"])
async def _cat_update(ctx: Ctx):
    return await category_change(ctx, ctx.target, ctx.params.get("changes") or {}, ctx.reason or "Categoria aggiornata")


@cap("categories.reorder", "categories", "Riordina le categorie (lista slug).", ["categories:write"], batch=True, params={"order": {"type": "array", "items": {"type": "string"}, "required": True}})
async def _cat_reorder(ctx: Ctx):
    docs = [await resolve_category(r) for r in ctx.params.get("order") or []]
    vids, ch = [], []
    for i, d in enumerate(docs):
        ch.append({"field": f"ordine:{d['slug']}", "before": d.get("ordine"), "after": i})
        if not ctx.dry and d.get("ordine") != i:
            r = await category_change(ctx, d, {"ordine": i}, "Riordino categorie")
            vids += r["version_ids"]
    return R(f"{'Anteprima ' if ctx.dry else ''}ordine categorie: {[d['slug'] for d in docs]}", {}, changes=ch, version_ids=vids)


@cap("categories.archive", "categories", "Nasconde una categoria dal sito (stato=bozza; le modelle restano assegnate).", ["categories:write"], target="category", risk=REVIEW)
async def _cat_archive(ctx: Ctx):
    return await category_change(ctx, ctx.target, {"stato": "bozza"}, "Categoria nascosta (bozza)")


@cap("categories.restore", "categories", "Ripubblica una categoria (stato=pubblicata).", ["categories:write"], target="category")
async def _cat_restore(ctx: Ctx):
    return await category_change(ctx, ctx.target, {"stato": "pubblicata"}, "Categoria ripubblicata")


@cap("categories.assign_models", "categories", "Aggiunge (o rimuove con remove=true) la categoria a una lista di modelle.", ["models:update"], target="category", batch=True,
     params={"models": {"type": "array", "items": {"type": "string"}, "required": True}, "remove": {"type": "boolean", "default": False}}, natural=["metti Alessia e Aurora nella categoria more"])
async def _cat_assign(ctx: Ctx):
    slug = ctx.target["slug"]
    vids, done = [], []
    for ref in ctx.params.get("models") or []:
        m = await resolve_model(ref)
        cats = list(m.get("categorie") or [])
        new = [c for c in cats if c != slug] if ctx.params.get("remove") else (cats if slug in cats else cats + [slug])
        if new == cats:
            continue
        done.append(m["slug"])
        if not ctx.dry:
            out = await patch_model(m, {"categorie": new}, ctx.principal, ctx.request, f"Categoria {slug}", source=ctx.source)
            if out.get("version_id"):
                vids.append(out["version_id"])
    return R(f"{'Anteprima: ' if ctx.dry else ''}categoria {slug} {'rimossa da' if ctx.params.get('remove') else 'assegnata a'} {len(done)} modelle", {"models": done}, version_ids=vids, target=_tgt(ctx.target, "category"))


# =====================================================================================================================
# SEO
# =====================================================================================================================
@cap("seo.audit", "seo", "Audit SEO di una modella (target) o di tutto il sito: score, issue SAFE/REVIEW/CRITICAL.", ["seo:audit"], target="model", read_only=True, natural=["controlla tutta la SEO di Alessia", "audit SEO del sito"])
async def _seo_audit(ctx: Ctx):
    from v1_seo import run_audit
    if ctx.target:
        r = await run_audit(scope="models", entity_id=ctx.target["id"])
        return R(f"SEO {ctx.target.get('nome_artistico') or ctx.target['slug']}: score {r.get('health_score')} — {r['counts']}", r, target=_tgt(ctx.target))
    r = await run_audit(scope=ctx.params.get("scope") or "all")
    return R(f"Audit SEO sito: score {r.get('health_score')} — {r['counts']}", r)


def _safe_fix_view(r: dict) -> tuple:
    """Adapter on the REAL apply_safe_fixes return: dry -> {dry_run, would_fix:int, items[]}; apply -> {applied, skipped, results[{applied, version_id, code, ...}]}.
    Returns (n_fixes, version_ids, applied_results)."""
    if r.get("dry_run"):
        return int(r.get("would_fix") or 0), [], r.get("items", [])
    applied = [x for x in r.get("results", []) if x.get("applied")]
    return int(r.get("applied") or 0), [x["version_id"] for x in applied if x.get("version_id")], applied


@cap("seo.safe_fix", "seo", "Applica SOLO le correzioni SEO SAFE_AUTO_FIX a una modella (dry_run per anteprima). REVIEW/CRITICAL mai toccate.", ["seo:safe_fix"], target="model", natural=["sistema gli errori SEO sicuri di Alessia"])
async def _seo_safe_fix(ctx: Ctx):
    from v1_seo import apply_safe_fixes
    r = await apply_safe_fixes(scope="models", entity_id=ctx.target["id"], actor=ctx.actor, request_id=request_id_of(ctx.request), source=ctx.source, dry_run=ctx.dry)
    n, vids, applied = _safe_fix_view(r)
    return R(f"{'Anteprima: ' if ctx.dry else ''}{n} fix SAFE su {ctx.target.get('nome_artistico') or ctx.target['slug']}" + ("" if ctx.dry else f" ({r.get('skipped', 0)} saltati)"), r, version_ids=vids, target=_tgt(ctx.target),
             changes=[{"field": x.get("field") or x.get("code"), "before": x.get("before"), "after": x.get("after") or x.get("suggested_value")} for x in applied])


@cap("seo.safe_fix_all", "seo", "SEO autopilot: applica i fix SAFE a tutte le modelle (selezione all/published/draft/category/ids). Batch, errori parziali, mai CRITICAL.", ["seo:safe_fix"], batch=True,
     params={"selection": {"type": "string", "enum": ["all", "published", "draft", "category", "ids"], "default": "published"}, "category": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}, "max": {"type": "integer"}},
     natural=["controlla tutto il sito e correggi tutte le issue SAFE", "correggi la SEO di tutto il sito"])
async def _seo_safe_fix_all(ctx: Ctx):
    from v1_seo import apply_safe_fixes
    cfg = await ai_config()
    sel = ctx.params.get("selection") or "published"
    q: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if sel == "published":
        q["stato"] = "pubblicata"
    elif sel == "draft":
        q["stato"] = "bozza"
    elif sel == "category":
        q["categorie"] = ctx.params.get("category")
    elif sel == "ids":
        docs = [await resolve_model(r) for r in ctx.params.get("ids") or []]
        q["id"] = {"$in": [d["id"] for d in docs]}
    mx = min(int(ctx.params.get("max") or cfg["policy"].get("max_batch", 50)), int(cfg["policy"].get("max_batch", 50)))
    models = await models_col.find(q, {"_id": 0, "id": 1, "slug": 1}).limit(mx).to_list(mx)
    results, vids = [], []
    for m in models:
        try:
            r = await apply_safe_fixes(scope="models", entity_id=m["id"], actor=ctx.actor, request_id=request_id_of(ctx.request), source=ctx.source, dry_run=ctx.dry)
            n, v_ids, _ = _safe_fix_view(r)
            vids += v_ids
            results.append({"slug": m["slug"], "ok": True, "fixes": n, "skipped": r.get("skipped", 0)})
        except Exception as e:
            results.append({"slug": m["slug"], "ok": False, "error": str(e)[:160]})
    tot = sum(r.get("fixes", 0) for r in results)
    return R(f"{'Anteprima: ' if ctx.dry else ''}{tot} fix SAFE su {len(results)} modelle ({len([r for r in results if not r['ok']])} errori)", {"results": results, "failed": [r for r in results if not r["ok"]]}, version_ids=vids)


@cap("seo.issues", "seo", "Issue SEO aperte (filtri: modella, severity).", ["seo:read"], target="model", read_only=True, params={"severity": {"type": "string"}}, natural=["quali issue SEO ha Alessia"])
async def _seo_issues(ctx: Ctx):
    q: Dict[str, Any] = {"status": "open"}
    if ctx.target:
        q["entity_id"] = ctx.target["id"]
    if ctx.params.get("severity"):
        q["severity"] = ctx.params["severity"]
    items = await seo_issues_col.find(q, {"_id": 0}).sort("severity", 1).to_list(200)
    return R(f"{len(items)} issue SEO aperte", {"items": items}, target=_tgt(ctx.target) if ctx.target else None)


@cap("seo.fix_issue", "seo", "Applica il fix di UNA issue: SAFE subito, REVIEW con approvazione (anteprima prima/dopo), CRITICAL mai.", ["seo:review_prepare"], params={"issue_id": {"type": "string", "required": True}, "proposed_value": {"type": "string"}}, natural=["applica il fix di questa issue"])
async def _seo_fix_issue(ctx: Ctx):
    from v1_seo import apply_issue_fix, issue_impact
    issue = await seo_issues_col.find_one({"id": ctx.params.get("issue_id")}, {"_id": 0})
    if not issue:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Issue non trovata"})
    if issue["severity"] == "CRITICAL":
        raise err(403, "CRITICAL_ACTION_BLOCKED", "Issue CRITICAL: intervento umano", issue=issue)
    if ctx.params.get("proposed_value"):
        issue = {**issue, "suggested_value": ctx.params["proposed_value"]}
    if ctx.dry:
        return R(f"Anteprima fix issue {issue['code']} ({issue['severity']})", {"dry_run": True, "issue": issue, "impact": issue_impact(issue)})
    if issue["severity"] == "REVIEW_REQUIRED" and not ctx.approved:
        return R("Issue REVIEW: richiede approvazione", {"issue": issue}, needs_approval={"before": {issue.get("field"): issue.get("current_value")}, "after": {issue.get("field"): issue.get("suggested_value")}, "fields": [issue.get("field")], "issue_id": issue["id"]})
    r = await apply_issue_fix(issue, ctx.actor, request_id_of(ctx.request), source=ctx.source, apply_review=ctx.approved)
    return R(("Fix applicato" if r.get("applied") else f"Fix non applicato: {r.get('reason')}"), r, version_ids=[r["version_id"]] if r.get("version_id") else [], rollback_ref=r.get("version_id"))


@cap("seo.ignore_issue", "seo", "Ignora una issue SEO (richiede approvazione).", ["seo:update"], risk=REVIEW, params={"issue_id": {"type": "string", "required": True}})
async def _seo_ignore(ctx: Ctx):
    issue = await seo_issues_col.find_one({"id": ctx.params.get("issue_id")}, {"_id": 0})
    if not issue:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Issue non trovata"})
    if ctx.dry:
        return R(f"Anteprima: issue {issue['code']} verrebbe ignorata", {"dry_run": True, "issue": issue})
    if not ctx.approved:
        return R("Ignorare una issue richiede approvazione", {"issue": issue}, needs_approval={"before": {"status": issue.get("status")}, "after": {"status": "ignored"}, "fields": ["status"]})
    await seo_issues_col.update_one({"id": issue["id"]}, {"$set": {"status": "ignored", "ignored_at": now_iso(), "ignored_by": ctx.actor}})
    return R(f"Issue {issue['code']} ignorata", {"id": issue["id"]}, changes=[{"field": "status", "before": issue.get("status"), "after": "ignored"}])


@cap("seo.redirect.list", "seo", "Redirect attivi.", ["seo:read"], read_only=True)
async def _redir_list(ctx: Ctx):
    items = await redirects_col.find({"active": True}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return R(f"{len(items)} redirect", {"items": items})


@cap("seo.redirect.create", "seo", "Crea un redirect 301/302 (richiede approvazione).", ["seo:update"], risk=REVIEW, params={"from_path": {"type": "string", "required": True}, "to_path": {"type": "string", "required": True}, "status_code": {"type": "integer", "default": 301}})
async def _redir_create(ctx: Ctx):
    from v1_seo import ensure_redirect
    fp, tp = ctx.params.get("from_path"), ctx.params.get("to_path")
    if not (fp and tp and fp.startswith("/") and tp.startswith("/")):
        raise err(422, "VALIDATION_FAILED", "from_path/to_path devono essere percorsi che iniziano con /")
    if ctx.dry:
        return R(f"Anteprima redirect {fp} → {tp}", {"dry_run": True})
    if not ctx.approved:
        return R("Redirect richiede approvazione", {}, needs_approval={"before": {fp: None}, "after": {fp: tp}, "fields": ["redirect"]})
    r = await ensure_redirect(fp, tp, ctx.actor, ctx.reason or "ChatGPT", int(ctx.params.get("status_code") or 301))
    ver = await versions_col.find_one({"entity": "redirect", "entity_id": (r or {}).get("id")}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)]) if r else None
    return R(f"Redirect {fp} → {tp} creato", r or {}, changes=[{"field": "redirect", "before": None, "after": f"{fp} -> {tp}"}], version_ids=[ver["id"]] if ver else [], rollback_ref=ver["id"] if ver else None)


@cap("seo.redirect.delete", "seo", "Disattiva un redirect (richiede approvazione).", ["seo:update"], risk=REVIEW, params={"from_path": {"type": "string", "required": True}})
async def _redir_delete(ctx: Ctx):
    fp = ctx.params.get("from_path")
    r = await redirects_col.find_one({"from_path": fp, "active": True}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Redirect non trovato"})
    if ctx.dry:
        return R(f"Anteprima: redirect {fp} verrebbe disattivato", {"dry_run": True, "redirect": r})
    if not ctx.approved:
        return R("Disattivare un redirect richiede approvazione", {"redirect": r}, needs_approval={"before": {"active": True}, "after": {"active": False}, "fields": ["active"]})
    new = {**r, "active": False, "deactivated_at": now_iso(), "deactivated_by": ctx.actor}
    await redirects_col.replace_one({"id": r["id"]}, new)
    ver = await record_version("redirect", r["id"], r, new, ctx.actor, source=ctx.source, reason=ctx.reason or "Redirect disattivato via ChatGPT", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
    return R(f"Redirect {fp} disattivato", {"id": r["id"]}, changes=[{"field": "active", "before": True, "after": False}], version_ids=[ver["id"]], rollback_ref=ver["id"])


@cap("seo.sitemap_status", "seo", "Stato sitemap: URL inclusi per tipo, modelle escluse (noindex), URL XML.", ["seo:read"], read_only=True, natural=["com'è la sitemap"])
async def _sitemap(ctx: Ctx):
    from v1_seo import sitemap_status
    r = await sitemap_status(principal=ctx.principal)   # real route handler reused with explicit principal (dispatcher already enforced seo:read)
    return R(f"Sitemap: {r.get('total', 0)} URL ({r.get('excluded_noindex_models', 0)} modelle noindex escluse)",
             {"total": r.get("total"), "by_type": r.get("by_type"), "excluded_noindex_models": r.get("excluded_noindex_models"), "xml_url": r.get("xml_url"), "base_url": r.get("base_url"),
              "urls": [e.get("loc") for e in (r.get("entries") or [])][:200]})


@cap("seo.internal_links", "seo", "Grafo di link interni (modelle correlate/articoli) per il sito o filtrato su una modella.", ["seo:read"], target="model", read_only=True, params={"limit_per_model": {"type": "integer", "default": 4}})
async def _internal_links(ctx: Ctx):
    from v1_seo import internal_link_suggestions
    r = await internal_link_suggestions(limit_per_model=int(ctx.params.get("limit_per_model") or 4))   # real signature: (limit_per_model) -> {items, orphans, note}
    items = r.get("items", [])
    if ctx.target:
        items = [g for g in items if g.get("model") == ctx.target.get("slug")]
    return R(f"{len(items)} nodi del grafo link interni" + (f" per {ctx.target.get('nome_artistico') or ctx.target['slug']}" if ctx.target else f", {len(r.get('orphans', []))} orfane"),
             {"items": items, "orphans": r.get("orphans", []), "note": r.get("note")}, target=_tgt(ctx.target) if ctx.target else None)


@cap("seo.opportunities", "seo", "Opportunità SEO del sito (issue di contenuto aperte, link interni, bozze pronte).", ["seo:read"], read_only=True, natural=["opportunità SEO"])
async def _opps(ctx: Ctx):
    from v1_seo import opportunities
    r = await opportunities(principal=ctx.principal)   # real route handler reused with explicit principal
    n = len(r.get("items", r.get("issues", []))) if isinstance(r, dict) else 0
    return R(f"{n} opportunità SEO", r if isinstance(r, dict) else {"items": r})


# =====================================================================================================================
# LANDINGS (basic set; clone/variants in 12B)
# =====================================================================================================================
@cap("landing.list", "landing", "Elenco landing con stato e validazione.", ["landing:read"], read_only=True)
async def _landing_list(ctx: Ctx):
    items = await landings_col.find({"is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1, "titolo": 1, "h1": 1, "stato": 1, "updated_at": 1, "targeting": 1}).sort("updated_at", -1).to_list(200)
    return R(f"{len(items)} landing", {"items": items})


@cap("landing.get", "landing", "Dettaglio landing con validazione completa.", ["landing:read"], target="landing", read_only=True)
async def _landing_get(ctx: Ctx):
    from v1_landings import validate_landing_full
    v = await validate_landing_full(ctx.target)
    return R(f"Landing {ctx.target['slug']} ({ctx.target.get('stato')}), validazione {v.get('score')}", {**ctx.target, "validation": v}, target=_tgt(ctx.target, "landing"))


@cap("landing.create", "landing", "Crea una landing editoriale italiana in bozza (model/models, h1, title, titolo, hero_text, intro, cta_text, cta_url, meta_description, keywords, topics, faq, noindex). Mai geoblocking.", ["landing:create"], params={"fields": {"type": "object", "description": "campi landing (oppure passali direttamente in parameters)"}}, natural=["crea una landing italiana per Alessia"])
async def _landing_create(ctx: Ctx):
    """Preview and execute share the SAME builder (v1_ai.build_landing_data) and the SAME validator (LandingIn + validate_landing)."""
    from v1_landings import create_landing, validate_landing, LandingIn
    from v1_ai import AILandingCreate, build_landing_data
    f = dict(ctx.params.get("fields") or ctx.params)
    f.pop("dry_run", None)
    body = AILandingCreate(**f)
    refs = body.models or ([body.model] if body.model else [])
    slugs, names = [], []
    for r in refs:
        d = await resolve_model(r)
        slugs.append(d["slug"])
        names.append(d.get("nome_artistico") or d.get("nome"))
    data = build_landing_data(body, slugs, names)
    try:
        validated = LandingIn(**data).model_dump()   # same schema create_landing applies
    except Exception as e:
        raise err(422, "VALIDATION_FAILED", "Dati landing non validi", errors=str(e)[:400])
    if ctx.dry:
        return R(f"Anteprima landing '{data['titolo']}' (bozza, {len(slugs)} modelle)", {"dry_run": True, "proposed": {k: v for k, v in validated.items() if k != "reason"}, "validation": validate_landing(validated)})
    out = await create_landing(data, ctx.principal, ctx.request)
    ver = await versions_col.find_one({"entity": "landing", "entity_id": out["id"]}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)])
    return R(f"Landing '{out.get('titolo')}' creata in bozza ({out['slug']})", out, version_ids=[ver["id"]] if ver else [], target=_tgt(out, "landing"), rollback_ref=ver["id"] if ver else None)


@cap("landing.update", "landing", "Modifica campi di una landing.", ["landing:update"], target="landing", params={"changes": {"type": "object", "required": True}})
async def _landing_update(ctx: Ctx):
    from v1_landings import patch_landing
    changes = ctx.params.get("changes") or {}
    new = deep_merge(ctx.target, changes)
    fields = diff_fields(ctx.target, new)
    ch = _changes_from(ctx.target, new, fields)
    if ctx.dry:
        return R(f"Anteprima landing: {fields}", {"dry_run": True}, changes=ch, target=_tgt(ctx.target, "landing"))
    out = await patch_landing(ctx.target, changes, ctx.principal, ctx.request, ctx.reason or "Landing via ChatGPT")
    return R(f"Landing {out['slug']} aggiornata ({', '.join(fields)})", out, changes=ch, version_ids=[out["version_id"]] if out.get("version_id") else [], target=_tgt(out, "landing"), rollback_ref=out.get("version_id"))


@cap("landing.validate", "landing", "Validazione pre-pubblicazione completa della landing.", ["landing:validate"], target="landing", read_only=True)
async def _landing_validate(ctx: Ctx):
    from v1_landings import validate_landing_full
    v = await validate_landing_full(ctx.target)
    return R(("Pubblicabile" if v.get("publishable", v.get("ready")) else f"Non pubblicabile: {len(v.get('errors', []))} errori") + f" (score {v.get('score')})", v, target=_tgt(ctx.target, "landing"))


@cap("landing.publish", "landing", "Pubblica una landing (validator + scope landing:publish, altrimenti approvazione). Le rotte pubbliche restano OFF finché il flag non è attivo.", ["landing:update"], target="landing", risk=REVIEW)
async def _landing_publish(ctx: Ctx):
    from v1_landings import validate_landing_full, set_landing_state
    v = await validate_landing_full(ctx.target)   # real contract: {ready, publishable, score, errors, warnings, checks}
    if not v.get("publishable", v.get("ready")):
        return R(f"Landing non pubblicabile: {len(v.get('errors', []))} errori del validator", {"validation": v}, warnings=[e if isinstance(e, str) else (e.get("message") or e.get("code") or str(e)) for e in v.get("errors", [])], target=_tgt(ctx.target, "landing"))
    if ctx.dry:
        return R("Anteprima: la landing passerebbe a pubblicata", {"dry_run": True, "validation": v}, target=_tgt(ctx.target, "landing"))
    if not has_scope(ctx.principal, "landing:publish") and not ctx.approved:
        return R("Pubblicazione landing richiede approvazione (scope landing:publish assente)", {}, target=_tgt(ctx.target, "landing"), needs_approval={"before": {"stato": ctx.target.get("stato")}, "after": {"stato": "pubblicata"}, "fields": ["stato"], "expected_updated_at": ctx.target.get("updated_at")})
    out = await set_landing_state(ctx.target, "pubblicata", ctx.principal, ctx.request)
    return R(f"Landing {out['slug']} pubblicata", out, changes=[{"field": "stato", "before": ctx.target.get("stato"), "after": "pubblicata"}], version_ids=[out["version_id"]] if out.get("version_id") else [], target=_tgt(out, "landing"), rollback_ref=out.get("version_id"))


@cap("landing.unpublish", "landing", "Riporta una landing in bozza.", ["landing:update"], target="landing")
async def _landing_unpublish(ctx: Ctx):
    from v1_landings import set_landing_state
    if ctx.dry:
        return R("Anteprima: landing tornerebbe in bozza", {"dry_run": True}, target=_tgt(ctx.target, "landing"))
    out = await set_landing_state(ctx.target, "bozza", ctx.principal, ctx.request)
    return R(f"Landing {out['slug']} in bozza", out, changes=[{"field": "stato", "before": ctx.target.get("stato"), "after": "bozza"}], version_ids=[out["version_id"]] if out.get("version_id") else [], target=_tgt(out, "landing"), rollback_ref=out.get("version_id"))


# =====================================================================================================================
# ALERTS / JOBS / BACKUP / SYSTEM / ADMINS
# =====================================================================================================================
@cap("alerts.list", "alerts", "Alert correnti (open/acknowledged) e risolti di recente, con timestamp.", ["alerts:read"], read_only=True, params={"include_resolved_hours": {"type": "integer", "default": 24}}, natural=["controlla gli alert"])
async def _alerts_list(ctx: Ctx):
    from v1_ai import alerts_view
    v = await alerts_view(history_hours=int(ctx.params.get("include_resolved_hours") or 24))
    return R(f"{len(v['open'])} alert correnti ({v['open_critical']} critici), {len(v['resolved_recent'])} risolti nelle ultime {v['history_window_hours']}h", v)


async def resolve_alert(ref: str) -> dict:
    a = await alerts_col.find_one({"$or": [{"id": ref}, {"dedupe_key": ref}]}, {"_id": 0}, sort=[("created_at", -1)])
    if not a:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Alert '{ref}' non trovato"})
    return a


@cap("alerts.inspect", "alerts", "Dettaglio di un alert (id o dedupe_key) con evidenza corrente e storico.", ["alerts:read"], target="alert", read_only=True)
async def _alerts_inspect(ctx: Ctx):
    a = ctx.target
    hist = await alerts_col.find({"dedupe_key": a["dedupe_key"]}, {"_id": 0, "id": 1, "stato": 1, "created_at": 1, "resolved_at": 1, "occurrences": 1}).sort("created_at", -1).to_list(20)
    return R(f"Alert {a['dedupe_key']}: {a['stato']} ({a.get('severity')})", {**a, "history": hist})


@cap("alerts.ack", "alerts", "Prende in carico un alert (acknowledged), la storia resta.", ["alerts:write"], target="alert", rollback=False)
async def _alerts_ack(ctx: Ctx):
    a = ctx.target
    if ctx.dry:
        return R(f"Anteprima: alert {a['dedupe_key']} verrebbe preso in carico", {"dry_run": True})
    await alerts_col.update_one({"id": a["id"]}, {"$set": {"stato": "acknowledged", "acknowledged_at": now_iso(), "acknowledged_by": ctx.actor, "updated_at": now_iso()}})
    return R(f"Alert {a['dedupe_key']} preso in carico", {"id": a["id"]}, changes=[{"field": "stato", "before": a["stato"], "after": "acknowledged"}])


@cap("alerts.resolve", "alerts", "Risolve un alert SOLO se la condizione è realmente sparita: per gli alert health:* rilancia il check; altrimenti richiede approvazione.", ["alerts:write"], target="alert", rollback=False)
async def _alerts_resolve(ctx: Ctx):
    a = ctx.target
    key = a["dedupe_key"]
    if key.startswith("health:") or key in ("onlyfans_links", "seo_critical", "published_not_ready"):
        from v1_health import run_health_checks
        if ctx.dry:
            return R("Anteprima: verrebbe rieseguito l'health check; l'alert si chiude solo se la condizione è sparita", {"dry_run": True})
        rec = await run_health_checks(auto_fix=False)
        cur = await alerts_col.find_one({"id": a["id"]}, {"_id": 0, "stato": 1, "resolved_at": 1})
        if cur and cur["stato"] == "resolved":
            return R(f"Alert {key} risolto: condizione confermata assente dal check corrente", {"health_overall": rec["overall"], "resolved_at": cur["resolved_at"]}, changes=[{"field": "stato", "before": a["stato"], "after": "resolved"}])
        return R(f"Alert {key} NON risolto: la condizione è ancora presente", {"health_overall": rec["overall"], "check": next((c for c in rec["checks"] if key.endswith(c["name"])), None)}, warnings=["Condizione ancora presente"])
    if ctx.dry:
        return R("Anteprima: risoluzione manuale richiede approvazione", {"dry_run": True})
    if not ctx.approved:
        return R("Risoluzione manuale dell'alert richiede approvazione", {}, needs_approval={"before": {"stato": a["stato"]}, "after": {"stato": "resolved"}, "fields": ["stato"]})
    await alerts_col.update_one({"id": a["id"]}, {"$set": {"stato": "resolved", "current": False, "resolved_at": now_iso(), "resolved_by": ctx.actor, "updated_at": now_iso()}})
    return R(f"Alert {key} risolto manualmente (approvato)", {"id": a["id"]}, changes=[{"field": "stato", "before": a["stato"], "after": "resolved"}])


SAFE_JOBS = {"health_check", "seo_scan", "broken_link_scan", "media_check", "sitemap_verify", "analytics_sync", "anomaly_detection", "backup", "alerts_digest"}   # real names from v1_jobs.JOBS


@cap("jobs.list", "jobs", "Job schedulati con stato, ultima esecuzione, prossimo run.", ["jobs:read"], read_only=True, natural=["stato dei job"])
async def _jobs_list(ctx: Ctx):
    items = await jobs_col.find({}, {"_id": 0}).to_list(50)
    return R(f"{len(items)} job ({len([j for j in items if j.get('last_status') == 'error'])} in errore)", {"items": items})


@cap("jobs.runs", "jobs", "Ultime esecuzioni di un job.", ["jobs:read"], target="job", read_only=True, params={"limit": {"type": "integer", "default": 20}})
async def _jobs_runs(ctx: Ctx):
    runs = await job_runs_col.find({"job": ctx.target["name"]}, {"_id": 0}).sort("started_at", -1).to_list(int(ctx.params.get("limit") or 20))
    return R(f"{len(runs)} esecuzioni di {ctx.target['name']}", {"items": runs})


@cap("jobs.run", "jobs", f"Esegue subito un job sicuro: {sorted(SAFE_JOBS)}.", ["jobs:execute"], target="job", rollback=False, natural=["esegui health check", "fai backup", "lancia la scansione SEO"])
async def _jobs_run(ctx: Ctx):
    from v1_jobs import run_job
    name = ctx.target["name"]
    if name not in SAFE_JOBS:
        raise err(403, "CRITICAL_ACTION_BLOCKED", f"Job '{name}' non eseguibile via AI", allowed=sorted(SAFE_JOBS))
    if ctx.dry:
        return R(f"Anteprima: verrebbe eseguito il job {name}", {"dry_run": True, "job": ctx.target})
    r = await run_job(name, trigger="ai", actor=ctx.actor)
    return R(f"Job {name}: {r.get('status')} in {r.get('duration_ms')} ms", r)


@cap("jobs.pause", "jobs", "Mette in pausa un job schedulato (richiede approvazione).", ["jobs:execute"], target="job", risk=REVIEW, rollback=False)
async def _jobs_pause(ctx: Ctx):
    j = ctx.target
    if ctx.dry:
        return R(f"Anteprima: job {j['name']} verrebbe messo in pausa", {"dry_run": True})
    if not ctx.approved:
        return R(f"Pausa del job {j['name']} richiede approvazione", {}, needs_approval={"before": {"enabled": j.get("enabled", True)}, "after": {"enabled": False}, "fields": ["enabled"]})
    await jobs_col.update_one({"name": j["name"]}, {"$set": {"enabled": False, "updated_at": now_iso()}})
    return R(f"Job {j['name']} in pausa", {}, changes=[{"field": "enabled", "before": j.get("enabled", True), "after": False}])


@cap("jobs.resume", "jobs", "Riattiva un job in pausa.", ["jobs:execute"], target="job", rollback=False)
async def _jobs_resume(ctx: Ctx):
    j = ctx.target
    if ctx.dry:
        return R(f"Anteprima: job {j['name']} verrebbe riattivato", {"dry_run": True})
    await jobs_col.update_one({"name": j["name"]}, {"$set": {"enabled": True, "updated_at": now_iso()}})
    return R(f"Job {j['name']} riattivato", {}, changes=[{"field": "enabled", "before": j.get("enabled"), "after": True}])


@cap("backup.list", "backup", "Ultimi backup (id, data, collection, dimensione).", ["backup:read"], read_only=True, natural=["ultimo backup"])
async def _backup_list(ctx: Ctx):
    # real record: {id, created_at, actor, reason, counts{collection:n}, size, storage_path | inline(gzip)} -> never return the gzip blob
    items = await backups_col.find({}, {"_id": 0, "inline": 0}).sort("created_at", -1).to_list(20)
    return R(f"{len(items)} backup, ultimo {items[0]['created_at'][:16] if items else 'mai'}", {"items": items})


@cap("backup.create", "backup", "Crea un backup completo ora.", ["backup:create"], rollback=False, natural=["fai backup"])
async def _backup_create(ctx: Ctx):
    from v1_config import create_backup
    if ctx.dry:
        return R("Anteprima: verrebbe creato un backup completo", {"dry_run": True})
    b = await create_backup(actor=ctx.actor, include_events=False, reason=ctx.reason or "ChatGPT")   # real signature (actor, include_events, reason)
    return R(f"Backup creato ({b.get('id')})", {k: v for k, v in b.items() if k != "inline"})


@cap("backup.verify", "backup", "Verifica un backup: collection incluse e conteggi vs stato attuale.", ["backup:read"], read_only=True, params={"backup_id": {"type": "string"}})
async def _backup_verify(ctx: Ctx):
    from v1_config import _load_backup
    from database import db
    q = {"id": ctx.params["backup_id"]} if ctx.params.get("backup_id") else {}
    b = await backups_col.find_one(q, {"_id": 0, "inline": 0}, sort=[("created_at", -1)])
    if not b:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Backup non trovato"})
    snap = await _load_backup(b["id"])            # real contract: gzip(json) -> {"created_at", "app", "collections": {name: [docs]}}
    cols = snap.get("collections") or {}
    comp, mismatches = {}, []
    for c, docs in cols.items():
        n_backup = len(docs) if isinstance(docs, list) else None
        declared = (b.get("counts") or {}).get(c)
        try:
            now_n = await db[c].count_documents({})
        except Exception:
            now_n = None
        comp[c] = {"in_backup": n_backup, "declared": declared, "now": now_n}
        if declared is not None and n_backup is not None and declared != n_backup:
            mismatches.append(c)
    return R(f"Backup {b['id']} del {b['created_at'][:16]}: {len(comp)} collection, integrità {'OK' if not mismatches else 'ANOMALA'}",
             {"id": b["id"], "created_at": b["created_at"], "integrity_ok": not mismatches, "mismatches": mismatches, "collections": comp}, warnings=[f"Conteggio incoerente: {m}" for m in mismatches])


@cap("backup.restore_plan", "backup", "Piano di ripristino (dry-run): cosa cambierebbe. Il ripristino reale è CRITICAL (solo admin umano).", ["backup:read"], read_only=True, params={"backup_id": {"type": "string", "required": True}, "collections": {"type": "array", "items": {"type": "string"}}})
async def _backup_plan(ctx: Ctx):
    # reuse the REAL restore service in dry-run (restore_backup never writes when dry_run=True / confirm=False)
    from v1_config import restore_backup, RestoreBody
    if not await backups_col.find_one({"id": ctx.params.get("backup_id")}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Backup non trovato"})
    body = RestoreBody(collections=ctx.params.get("collections") or None, mode="replace", dry_run=True, confirm=False)
    r = await restore_backup(ctx.params["backup_id"], body, ctx.request, principal=ctx.principal)
    plan = [{"collection": c, "in_backup": v.get("in_backup"), "now": v.get("current"), "mode": r.get("mode")} for c, v in (r.get("plan") or {}).items()]
    return R("Piano di ripristino (nessuna modifica). Esecuzione reale: CRITICAL, solo amministratore umano dal pannello.", {"backup_id": ctx.params["backup_id"], "plan": plan, "critical": True, "dry_run": True})


@cap("system.health_run", "system", "Esegue ora l'health check completo (senza self-healing) e riconcilia gli alert.", ["health:run"], rollback=False, natural=["esegui health check"])
async def _health_run(ctx: Ctx):
    from v1_health import run_health_checks
    if ctx.dry:
        return R("Anteprima: verrebbe eseguito l'health check", {"dry_run": True})
    rec = await run_health_checks(auto_fix=False)
    return R(f"Health {rec['overall']}: {len([c for c in rec['checks'] if c['status'] != 'ok'])} check non ok, alert risolti {rec.get('resolved_alerts')}", rec)


@cap("admins.list", "system", "Amministratori (email, ruolo, creato). Mai password/hash. Creazione/eliminazione/ruoli = CRITICAL (umano).", ["users:read"], read_only=True)
async def _admins_list(ctx: Ctx):
    items = await admins_col.find({}, {"_id": 0, "id": 1, "email": 1, "ruolo": 1, "role": 1, "created_at": 1, "last_login": 1}).to_list(50)
    return R(f"{len(items)} amministratori", {"items": items, "critical_operations": ["create", "delete", "change_role", "reset_security"]})


# =====================================================================================================================
# ROLLBACK (version / session / window)
# =====================================================================================================================
@cap("rollback.version", "rollback", "Ripristina lo stato precedente a una versione (crea una NUOVA versione, storia intatta).", ["rollback:execute"], params={"version_id": {"type": "string", "required": True}}, natural=["annulla questa modifica"])
async def _rb_version(ctx: Ctx):
    v = await versions_col.find_one({"id": ctx.params.get("version_id")}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Versione non trovata"})
    if ctx.dry:
        return R(f"Anteprima rollback {v['id']}: ripristino di {v.get('changed_fields')} su {v['entity']} {v['entity_id']}", {"dry_run": True, "version": {k: v.get(k) for k in ("id", "entity", "entity_id", "actor", "timestamp", "reason", "changed_fields")}, "will_restore": v.get("before")})
    r = await rollback_version(v["id"], ctx.actor, request_id_of(ctx.request), ctx.reason or "Rollback via ChatGPT")
    return R(f"Rollback eseguito su {v['entity']} {v['entity_id']} (nuova versione {r.get('new_version_id') or r.get('version_id')})", r, version_ids=[r.get("new_version_id") or r.get("version_id")], rollback_ref=r.get("new_version_id") or r.get("version_id"))


async def _session_actions(session_id: str) -> List[dict]:
    return await ai_actions_col.find({"session_id": session_id, "ok": True}, {"_id": 0, "id": 1, "action": 1, "version_ids": 1, "timestamp": 1, "request_id": 1, "secondary": 1}).sort("timestamp", -1).to_list(500)


async def _versions_for_session(session_id: str, acts: Optional[List[dict]] = None) -> tuple:
    """Returns (versions_newest_first, reported_ids). `reported_ids` = version ids a capability EXPLICITLY returned
    (genuine create/update/delete). Versions swept only by request_id (e.g. optimize re-registering a file) are included
    for restore purposes but are NOT genuine creations: rollback must never soft-delete a `before=None` version that is
    not in reported_ids (that would delete a pre-existing asset a side effect merely re-touched)."""
    acts = acts if acts is not None else await _session_actions(session_id)
    ids, rids = [], []
    for a in acts:
        rids.append(a.get("request_id"))
        for v in a.get("version_ids") or []:
            if v and v not in ids:
                ids.append(v)
    q = {"$or": [{"id": {"$in": ids}}, {"meta.session_id": session_id}, {"request_id": {"$in": [r for r in rids if r]}, "source": {"$ne": "rollback"}}]}
    vers = await versions_col.find(q, {"_id": 0}).to_list(2000)
    seen, out = set(), []
    for v in vers:
        if v["id"] in seen or v.get("source") == "rollback":
            continue
        seen.add(v["id"])
        out.append(v)
    out.sort(key=lambda x: x.get("timestamp", ""), reverse=True)   # newest first -> undo in reverse order
    return out, set(ids)


def _slug_paths(entity: str, slug: str) -> List[str]:
    base = {"model": "/modelle", "category": "/categorie", "landing": "/landing", "article": "/articoli"}.get(entity)
    return [f"{base}/{slug}"] if base and slug else []


@cap("rollback.session", "rollback", "Annulla TUTTE le modifiche di una sessione (session_id) in ordine inverso, comprese le risorse secondarie (file/varianti, link media→slot, issue SEO, redirect da cambio slug). Ogni annullamento crea una nuova versione: storia e audit conservati.",
     ["rollback:execute"], params={"session_id": {"type": "string", "description": "default: sessione corrente"}}, natural=["annulla tutto quello che hai appena fatto"])
async def _rb_session(ctx: Ctx):
    sid = ctx.params.get("session_id") or ctx.session_id
    acts = await _session_actions(sid)
    vers, reported_ids = await _versions_for_session(sid, acts)
    secondary = [s for a in reversed(acts) for s in (a.get("secondary") or [])]   # chronological (acts are newest-first)
    if not vers and not secondary:
        return R(f"Nessuna modifica trovata per la sessione {sid}", {"session_id": sid, "versions": 0})
    plan = [{"version_id": v["id"], "entity": v["entity"], "entity_id": v["entity_id"], "changed_fields": v.get("changed_fields"), "operation": v.get("operation"),
             "already_rolled_back": bool(v.get("rolled_back")), "timestamp": v.get("timestamp")} for v in vers]
    plan_secondary = [{"kind": s.get("kind"), "id": s.get("file_id") or s.get("id"), "restore": s.get("before")} for s in secondary]
    if ctx.dry:
        return R(f"Anteprima: verrebbero annullate {len([p for p in plan if not p['already_rolled_back']])} modifiche + {len(secondary)} effetti secondari della sessione {sid}",
                 {"dry_run": True, "plan": plan, "secondary": plan_secondary})
    done, new_vids, errors, created_entities, side_effects = [], [], [], [], []
    rid = request_id_of(ctx.request)
    for v in vers:
        try:
            if v.get("rolled_back"):
                done.append({"version_id": v["id"], "action": "already_rolled_back"})
                continue
            # A `before=None` version is a genuine CREATION to undo (soft delete) ONLY if a capability explicitly reported it.
            # Side effects that merely re-register an existing asset (e.g. optimize_media -> store_media) also write a
            # `before=None` version but are NOT in reported_ids: undoing them must never delete the pre-existing asset.
            is_creation = v.get("before") is None
            if is_creation and v["id"] not in reported_ids:
                await versions_col.update_one({"id": v["id"]}, {"$set": {"rolled_back": True, "rollback_note": "effetto collaterale (ri-registrazione), non una creazione: nessuna eliminazione"}})
                done.append({"version_id": v["id"], "entity": v["entity"], "action": "skipped_side_effect"})
                continue
            r = await rollback_version(v["id"], ctx.actor, rid, f"Rollback sessione {sid}")   # creation -> soft delete, update -> restore `before`; never destructive
            new_vids.append(r.get("new_version_id") or r.get("version_id"))
            done.append({"version_id": v["id"], "entity": v["entity"], "action": "soft_deleted" if is_creation else "restored"})
            if is_creation:
                created_entities.append((v["entity"], v["entity_id"]))
                if v["entity"] == "redirect":   # soft-deleted redirect must not keep firing (lookups filter on `active`)
                    await redirects_col.update_one({"id": v["entity_id"]}, {"$set": {"active": False, "deactivated_by": "rollback", "updated_at": now_iso()}})
                if v["entity"] == "file":   # derived variants share the parent's lifecycle
                    n = (await files_col.update_many({"parent_id": v["entity_id"], "is_deleted": {"$ne": True}}, {"$set": {"is_deleted": True, "deleted_at": now_iso(), "updated_at": now_iso()}})).modified_count
                    if n:
                        side_effects.append({"kind": "file_variants_soft_deleted", "parent_id": v["entity_id"], "count": n})
            else:
                issue_id = (v.get("meta") or {}).get("issue_id")
                if issue_id:   # an SEO fix was undone -> the issue is open again (unless its entity is being removed, handled below)
                    await seo_issues_col.update_one({"id": issue_id}, {"$set": {"status": "open", "reopened_at": now_iso(), "reopened_by": "rollback"}, "$unset": {"fixed_at": "", "version_id": ""}})
                    side_effects.append({"kind": "seo_issue_reopened", "issue_id": issue_id})
                if "slug" in (v.get("changed_fields") or []) and (v.get("before") or {}).get("slug"):
                    # a slug change created a redirect old->new; the old slug is live again, so that redirect must not fire
                    paths = _slug_paths(v["entity"], v["before"]["slug"])
                    if paths:
                        n = (await redirects_col.update_many({"from_path": {"$in": paths}, "active": True}, {"$set": {"active": False, "updated_at": now_iso(), "deactivated_by": "rollback", "deactivated_reason": f"rollback sessione {sid}"}})).modified_count
                        if n:
                            side_effects.append({"kind": "redirect_deactivated", "paths": paths})
        except Exception as e:
            errors.append({"version_id": v["id"], "error": str(getattr(e, 'detail', e))[:160]})
    # entities created in the session are gone (soft) -> their open SEO issues are no longer real
    for ent, eid in created_entities:
        n = (await seo_issues_col.update_many({"entity_id": eid, "status": {"$in": ["open", "fixed"]}}, {"$set": {"status": "resolved", "resolved_at": now_iso(), "resolved_by": "rollback"}})).modified_count
        if n:
            side_effects.append({"kind": "seo_issues_resolved", "entity": ent, "entity_id": eid, "count": n})
        if ent == "model":   # files linked to a model that no longer exists lose the link (the files themselves keep their own version-based fate)
            n = (await files_col.update_many({"model_id": eid, "is_deleted": {"$ne": True}}, {"$set": {"model_id": None, "slot": None, "updated_at": now_iso()}})).modified_count
            if n:
                side_effects.append({"kind": "file_links_cleared", "model_id": eid, "count": n})
    # non-versioned side effects recorded by capabilities: apply in REVERSE (a file can be linked several times in one
    # session; `secondary` is appended oldest->newest, so reversing makes the ORIGINAL `before` the last state applied).
    for s in reversed(secondary):
        try:
            if s.get("kind") == "file_link" and s.get("file_id"):
                await files_col.update_one({"id": s["file_id"]}, {"$set": {**(s.get("before") or {"model_id": None, "slot": None}), "updated_at": now_iso()}})
                side_effects.append({"kind": "file_link_restored", "file_id": s["file_id"], "to": s.get("before")})
        except Exception as e:
            errors.append({"secondary": s.get("kind"), "error": str(e)[:160]})
    await audit_log(ctx.actor, "rollback.session", "session", sid, {"versions": len(done), "side_effects": len(side_effects), "errors": len(errors)}, rid, "rollback")
    return R(f"Sessione {sid}: {len([d for d in done if d['action'] != 'already_rolled_back'])} modifiche annullate, {len(side_effects)} effetti secondari ripristinati, {len(errors)} errori (storia e audit conservati)",
             {"session_id": sid, "done": done, "side_effects": side_effects, "errors": errors, "plan": plan}, version_ids=[x for x in new_vids if x], warnings=[e["error"] for e in errors])


@cap("rollback.window", "rollback", "Annulla le modifiche fatte a una modella negli ultimi N minuti (opz. solo da ChatGPT/attore), in ordine inverso.", ["rollback:execute"], target="model",
     params={"minutes": {"type": "integer", "default": 20}, "actor": {"type": "string"}, "only_ai": {"type": "boolean", "default": True}}, natural=["annulla tutte le modifiche fatte ad Alessia negli ultimi 20 minuti"])
async def _rb_window(ctx: Ctx):
    since = (datetime.now(timezone.utc) - timedelta(minutes=int(ctx.params.get("minutes") or 20))).isoformat()
    q: Dict[str, Any] = {"entity": "model", "entity_id": ctx.target["id"], "timestamp": {"$gte": since}, "source": {"$ne": "rollback"}}
    if ctx.params.get("actor"):
        q["actor"] = ctx.params["actor"]
    elif ctx.params.get("only_ai", True):
        q["source"] = {"$in": ["chatgpt", "ai", "admin-ai", "autofix"]}
    vers = await versions_col.find(q, {"_id": 0}).sort("timestamp", -1).to_list(200)
    plan = [{"version_id": v["id"], "changed_fields": v.get("changed_fields"), "actor": v.get("actor"), "timestamp": v.get("timestamp"), "reason": v.get("reason")} for v in vers]
    if ctx.dry:
        return R(f"Anteprima: {len(vers)} modifiche su {ctx.target['slug']} verrebbero annullate", {"dry_run": True, "plan": plan}, target=_tgt(ctx.target))
    new_vids, errors = [], []
    for v in vers:
        try:
            r = await rollback_version(v["id"], ctx.actor, request_id_of(ctx.request), f"Rollback finestra {ctx.params.get('minutes', 20)} min")
            new_vids.append(r.get("new_version_id") or r.get("version_id"))
        except Exception as e:
            errors.append({"version_id": v["id"], "error": str(getattr(e, 'detail', e))[:160]})
    return R(f"{len(new_vids)} modifiche annullate su {ctx.target['slug']} ({len(errors)} errori)", {"plan": plan, "errors": errors}, version_ids=new_vids, target=_tgt(ctx.target), warnings=[e["error"] for e in errors])


# =====================================================================================================================
# WORKFLOW: models.prepare_complete
# =====================================================================================================================
@cap("models.prepare_complete", "workflow", "Workflow deterministico: crea (o usa) la bozza → compila i campi → assegna media agli slot → fix SEO SAFE → ALT default → valida → readiness. NON pubblica mai. Tutto sotto lo stesso session_id (annullabile con rollback.session).",
     ["models:create", "models:update"], rollback=True,
     conditional_scopes={"media:upload": (lambda p: bool(p.get("media")), "solo se il parametro opzionale `media` è presente"),
                         "seo:safe_fix": (lambda p: p.get("seo_safe_fix", True) is not False, "solo se seo_safe_fix non è false (default true)")},
     params={"nome": {"type": "string", "required": True}, "fields": {"type": "object"}, "media": {"type": "array", "items": {"type": "object"}, "description": "[{media|url, slot, alt}]"}, "seo_safe_fix": {"type": "boolean", "default": True}},
     examples=[{"action": "models.prepare_complete", "parameters": {"nome": "TEST V2 GIULIA"}, "dry_run": True},
               {"action": "models.prepare_complete", "parameters": {"nome": "Giulia Rossi", "fields": {"frase": "Il lato che non mostro a tutti.", "categorie": ["more"], "onlyfans_url": "https://onlyfans.com/giulia_rossi"}, "media": [{"media": "giulia-1.jpg", "slot": "public_photo_1"}]}}],
     natural=["prepara Giulia completamente ma non pubblicarla", "crea una nuova modella con queste foto e preparala tutta"])
async def _prepare_complete(ctx: Ctx):
    steps = []
    nome = (ctx.params.get("nome") or "").strip()
    if not nome:
        raise err(422, "VALIDATION_FAILED", "nome obbligatorio")
    fields = {k: v for k, v in (ctx.params.get("fields") or {}).items() if k in ALLOWED_FIELDS}
    fields.pop("stato", None)   # the workflow never publishes
    media = ctx.params.get("media") or []
    cfg = await ai_config()
    cls = classify_model_changes(fields, cfg["policy"]) if fields else {"level": SAFE, "review_fields": []}
    review_roots = {f.split(".")[0] for f in cls.get("review_fields") or []}
    safe_fields = {k: v for k, v in fields.items() if k not in review_roots}
    review_fields = {k: v for k, v in fields.items() if k in review_roots}
    if ctx.dry:
        # READ-ONLY analysis: nothing is created, fetched or written. Media references are validated against the library
        # (URLs are only syntax-checked: no download in preview), slots are parsed with the real slot rules.
        from sanitize import slugify
        existing = await models_col.find_one({"is_deleted": {"$ne": True}, "$or": [{"id": nome}, {"slug": slugify(nome)},
                                                                                 {"nome": {"$regex": f"^{re.escape(nome)}$", "$options": "i"}}, {"nome_artistico": {"$regex": f"^{re.escape(nome)}$", "$options": "i"}}]}, {"_id": 0, "id": 1, "slug": 1, "stato": 1})
        media_plan, warnings = [], []
        for m in media:
            item = {"slot": m.get("slot"), "ref": m.get("media") or m.get("url")}
            try:
                tech, side, tipo, n = parse_slot(m.get("slot") or "")
                item.update({"technical_slot": tech, "side": side, "tipo": tipo})
            except HTTPException:
                item["error"] = "slot non valido"
                warnings.append(f"slot '{m.get('slot')}' non valido")
            if m.get("media"):
                try:
                    f = await find_media(m["media"])
                    item.update({"media_id": f["id"], "media_tipo": f.get("tipo"), "found": True})
                except HTTPException:
                    item["found"] = False
                    warnings.append(f"media '{m.get('media')}' non trovato in libreria")
            elif m.get("url"):
                item["found"] = None
                item["url_ok"] = bool(re.match(r"^https?://", str(m["url"])))
                if not item["url_ok"]:
                    warnings.append(f"url non valido: {m['url']}")
                item["note"] = "download e controlli anti-SSRF/magic-bytes avvengono solo all'esecuzione reale"
            media_plan.append(item)
        seo_fix = ctx.params.get("seo_safe_fix", True) is not False
        plan = [("models.create" + (f" (saltato: esiste già {existing['slug']})" if existing else f" → bozza '{nome}' (slug {await unique_slug(nome)})"))]
        if safe_fields:
            plan.append(f"models.update SAFE ({sorted(safe_fields)})")
        if review_fields:
            plan.append(f"models.update REVIEW → approvazione ({sorted(review_fields)})")
        plan += [f"media.assign {m.get('slot')}" for m in media] + (["seo.safe_fix"] if seo_fix else []) + ["models.validate"]
        return R(f"Anteprima workflow '{nome}': bozza + {len(safe_fields)} campi SAFE + {len(review_fields)} campi REVIEW (approvazione) + {len(media)} media + {'SEO safe + ' if seo_fix else ''}validate (nessuna pubblicazione, nessuna scrittura)",
                 {"dry_run": True, "would_create": not bool(existing), "existing": existing, "plan": plan, "fields_safe": sorted(safe_fields), "fields_review": sorted(review_fields),
                  "media_plan": media_plan, "seo_safe_fix": seo_fix, "publishes": False,
                  "required_scopes_execute": REGISTRY["models.prepare_complete"].required_scopes(ctx.params), "required_scopes_preview": REGISTRY["models.prepare_complete"].required_preview_scopes(ctx.params)},
                 warnings=warnings, next_steps=["Esegui senza dry_run (modalità FULL) per creare la bozza; i campi REVIEW richiederanno approvazione; annullabile con rollback.session"])
    vids: List[str] = []
    secondary: List[dict] = []
    # reuse ONLY an exact match (id / slug / exact name): never a fuzzy hit on a real model
    from sanitize import slugify
    existing = await models_col.find_one({"is_deleted": {"$ne": True}, "$or": [{"id": nome}, {"slug": slugify(nome)},
                                                                             {"nome": {"$regex": f"^{re.escape(nome)}$", "$options": "i"}}, {"nome_artistico": {"$regex": f"^{re.escape(nome)}$", "$options": "i"}}]}, {"_id": 0})
    if existing:
        doc = existing
        steps.append({"step": "models.create", "skipped": True, "reason": f"esiste già ({doc['slug']})"})
    else:
        out = await create_model({"nome": nome}, ctx.principal, ctx.request, f"Workflow prepare_complete ({nome})")
        doc = await models_col.find_one({"id": out["id"]}, {"_id": 0})
        ver = await versions_col.find_one({"entity": "model", "entity_id": doc["id"]}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)])
        if ver:
            vids.append(ver["id"])
        steps.append({"step": "models.create", "ok": True, "slug": doc["slug"], "version_id": ver["id"] if ver else None})
    if safe_fields:
        sub = Ctx(ctx.principal, ctx.request, {}, dry=False, reason="Workflow: campi", session_id=ctx.session_id, approved=False)   # SAFE only: no approval bypass
        r = await model_change(sub, doc, safe_fields, "Workflow prepare_complete: campi")
        vids += r["version_ids"]
        steps.append({"step": "models.update", "ok": True, "fields": sorted(safe_fields), "version_id": r.get("rollback_ref")})
        doc = await models_col.find_one({"id": doc["id"]}, {"_id": 0})
    approval = None
    if review_fields:
        # REVIEW fields are NOT applied: a real approval proposal (models.update) is created, exactly like a direct models.update would do
        preview = await patch_model(doc, review_fields, ctx.principal, ctx.request, "Workflow prepare_complete: campi REVIEW", source=ctx.source, dry_run=True)
        payload = {"action": "models.update", "target": doc["id"], "parameters": {"changes": review_fields}, "reason": "Workflow prepare_complete: campi REVIEW", "session_id": ctx.session_id, "expected_updated_at": None}   # workflow keeps editing the model: don't pin concurrency
        approval = await create_approval("CAPABILITY", ctx.actor, _tgt(doc), payload, preview["before"], preview["proposed_after"], f"models.update ({', '.join(sorted(review_fields))})", request_id_of(ctx.request))
        approval["id"] = approval.get("approval_id")
        approval["capability"] = "models.update"
        approval["confirm_with"] = f"POST /api/v2/ai/approvals/{approval['id']}/approve {{token}}"
        steps.append({"step": "models.update (REVIEW)", "ok": True, "pending_approval": True, "fields": sorted(review_fields), "approval_id": approval["id"]})
    for m in media:
        try:
            sub = Ctx(ctx.principal, ctx.request, {}, dry=False, reason="Workflow: media", session_id=ctx.session_id, approved=False)
            f = None
            if m.get("url") and not m.get("media"):
                from v1_media import fetch_url_bytes, store_media
                data, mime = await asyncio.get_event_loop().run_in_executor(None, fetch_url_bytes, m["url"])   # sync, 1 arg
                rec = await store_media(data, mime, original_filename=m.get("filename") or "", alt=m.get("alt") or "", seo_name=m.get("seo_name") or "", model_id=doc["id"], slot=m.get("slot"), actor=ctx.actor, request_id=request_id_of(ctx.request))
                fver = await versions_col.find_one({"entity": "file", "entity_id": rec["id"]}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)])
                if fver:
                    vids.append(fver["id"])   # the upload itself is undone (soft) by rollback.session
                url, poster = media_urls(rec)
            else:
                f = await find_media(m.get("media") or "")
                url, poster = media_urls(f)
            r = await apply_media_to_slot(sub, doc, url, m.get("slot") or "public_photo_1", alt=m.get("alt") or "", poster=poster, reason="Workflow: media")
            vids += r["version_ids"]
            if f is not None and (f.get("model_id") != doc["id"] or f.get("slot") != m.get("slot")):
                before, after = {"model_id": f.get("model_id"), "slot": f.get("slot")}, {"model_id": doc["id"], "slot": m.get("slot")}
                await files_col.update_one({"id": f["id"]}, {"$set": {**after, "updated_at": now_iso()}})
                secondary.append({"kind": "file_link", "file_id": f["id"], "before": before, "after": after})
            steps.append({"step": "media.assign", "ok": True, "slot": m.get("slot"), "version_id": r.get("rollback_ref")})
            doc = await models_col.find_one({"id": doc["id"]}, {"_id": 0})
        except Exception as e:
            steps.append({"step": "media.assign", "ok": False, "slot": m.get("slot"), "error": str(getattr(e, "detail", e))[:200]})
    if ctx.params.get("seo_safe_fix", True):
        from v1_seo import apply_safe_fixes
        r = await apply_safe_fixes(scope="models", entity_id=doc["id"], actor=ctx.actor, request_id=request_id_of(ctx.request), source=ctx.source, dry_run=False)
        n_fix, v_ids, _ = _safe_fix_view(r)
        vids += v_ids
        steps.append({"step": "seo.safe_fix", "ok": True, "fixes": n_fix, "skipped": r.get("skipped", 0)})
        doc = await models_col.find_one({"id": doc["id"]}, {"_id": 0})
    v = validate_model(doc)
    steps.append({"step": "models.validate", "ok": True, "ready": v["ready"], "missing": [e["field"] for e in v["errors"]]})
    res = R(f"'{doc.get('nome_artistico') or nome}' preparata (slug {doc['slug']}, stato {workflow_status(doc)}, NON pubblicata): {len([s for s in steps if s.get('ok')])} passi ok, {len(vids)} versioni"
            + (f", {len(review_fields)} campi REVIEW in attesa di approvazione" if review_fields else "") + ". " + ("Pronta alla pubblicazione." if v["ready"] else f"Mancano: {', '.join(e['field'] for e in v['errors'])}"),
            {"id": doc["id"], "slug": doc["slug"], "workflow_status": workflow_status(doc), "steps": steps, "readiness": v, "session_id": ctx.session_id, "published": False, "pending_review_fields": sorted(review_fields)},
            version_ids=[x for x in vids if x], target=_tgt(doc), secondary=secondary,
            next_steps=(["Conferma i campi REVIEW: approveApproval {token}"] if approval else []) + ["models.publish (separato, dopo la tua approvazione)", f"rollback.session {{session_id:'{ctx.session_id}'}} per annullare tutto"])
    if approval:
        res["approval"] = approval   # pre-built proposal (models.update on the REVIEW subset), surfaced by the dispatcher as approval_required
    return res




# =====================================================================================================================
# STARTUP BINDING VERIFICATION
# =====================================================================================================================
# Only these modules can be referenced by a binding (no dynamic import of arbitrary modules, no reflection on user input).
_BINDING_MODULES = ("v1_models", "v1_media", "v1_seo", "v1_landings", "v1_health", "v1_jobs", "v1_config", "v1_versioning", "v1_ai", "v1_ai_policy", "sanitize", "schemas")

# capability id (exact) or glob -> required service bindings. "module.func" or "module.func(param, param)" = params that MUST exist in the real signature.
BINDINGS: Dict[str, List[str]] = {
    "models.*": ["v1_models.resolve_model", "v1_models.patch_model(dry_run, expected_updated_at, source)", "v1_models.validate_model", "v1_versioning.record_version(meta, request_id)"],
    "models.create": ["v1_models.create_model"],
    "models.prepare_complete": ["v1_models.create_model", "v1_models.patch_model(dry_run)", "v1_media.slot_changes(url, slot, side, tipo, pair_index)", "v1_seo.apply_safe_fixes(entity_id, dry_run)"],
    "models.publish": ["v1_models.transition(dry_run)"], "models.unpublish": ["v1_models.transition(dry_run)"], "models.submit_review": ["v1_models.transition(dry_run)"],
    "models.approve": ["v1_models.transition(dry_run)"], "models.reject": ["v1_models.transition(dry_run)"], "models.back_to_draft": ["v1_models.transition(dry_run)"],
    "tags.*": ["v1_models.patch_model(dry_run)"],
    "media.*": ["v1_media.public_file", "v1_media.slot_changes(url, slot, side, tipo, pair_index)", "v1_models.patch_model(dry_run)"],
    "media.upload_url": ["v1_media.fetch_url_bytes(url)", "v1_media.store_media(original_filename, alt, seo_name, model_id, slot, actor, request_id)", "v1_media.validate_bytes"],
    "media.update": ["v1_media.patch_media", "v1_media.MediaPatch"], "media.optimize": ["v1_media.optimize_media"], "media.optimize_all": ["v1_media.optimize_media"],
    "media.soft_delete": ["v1_media.delete_media"], "media.broken": ["v1_health.check_media"],
    "home.*": ["v1_models.patch_model(dry_run)"], "filmstrip.*": ["v1_models.patch_model(dry_run)", "v1_versioning.record_version(meta)"],
    "settings.*": ["v1_versioning.record_version(meta)", "v1_versioning.diff_fields"], "config.*": ["v1_versioning.record_version(meta)"], "flags.*": ["v1_versioning.record_version(meta)"],
    "categories.*": ["sanitize.slugify", "schemas.CategoryIn", "v1_versioning.record_version(meta)"], "categories.assign_models": ["v1_models.patch_model(dry_run)"],
    "seo.audit": ["v1_seo.run_audit(scope, entity_id)"], "seo.safe_fix": ["v1_seo.apply_safe_fixes(actor, request_id, scope, entity_id, dry_run, source)"],
    "seo.safe_fix_all": ["v1_seo.apply_safe_fixes(entity_id, dry_run)"], "seo.fix_issue": ["v1_seo.apply_issue_fix"], "seo.redirect_create": ["v1_seo.ensure_redirect"],
    "seo.sitemap_status": ["v1_seo.sitemap_status(principal)"], "seo.internal_links": ["v1_seo.internal_link_suggestions(limit_per_model)"], "seo.opportunities": ["v1_seo.opportunities(principal)"],
    "landing.*": ["v1_landings.resolve_landing", "v1_landings.validate_landing_full"], "landing.create": ["v1_landings.create_landing", "v1_landings.LandingIn", "v1_landings.validate_landing", "v1_ai.build_landing_data", "v1_ai.AILandingCreate"],
    "landing.update": ["v1_landings.patch_landing"], "landing.publish": ["v1_landings.set_landing_state"], "landing.unpublish": ["v1_landings.set_landing_state"],
    "alerts.*": ["v1_ai.alerts_view(history_hours)"], "alerts.resolve": ["v1_health.run_health_checks(auto_fix)"],
    "jobs.run": ["v1_jobs.run_job(name, trigger, actor)"], "jobs.*": ["v1_jobs.JOBS"],
    "backup.create": ["v1_config.create_backup(actor, include_events, reason)"], "backup.verify": ["v1_config._load_backup"], "backup.restore_plan": ["v1_config.restore_backup(backup_id, body, principal)", "v1_config.RestoreBody"],
    "system.health_run": ["v1_health.run_health_checks(auto_fix)"],
    "rollback.*": ["v1_versioning.rollback_version(version_id, actor, request_id, reason)"],
}
_BIND_RX = re.compile(r"^(?P<mod>[a-z0-9_]+)\.(?P<attr>[A-Za-z_][A-Za-z0-9_]*)(?:\((?P<params>[^)]*)\))?$")


def _check_binding(spec: str) -> Optional[str]:
    """Return None if the binding resolves (module allowlisted, attribute exists, declared params present in the real signature), else the reason."""
    m = _BIND_RX.match(spec.strip())
    if not m:
        return f"binding malformato: {spec}"
    mod, attr, params = m.group("mod"), m.group("attr"), m.group("params")
    if mod not in _BINDING_MODULES:
        return f"modulo non consentito: {mod}"
    try:
        module = importlib.import_module(mod)
    except Exception as e:
        return f"modulo {mod} non importabile: {type(e).__name__}"
    obj = getattr(module, attr, None)
    if obj is None:
        return f"{mod}.{attr} inesistente"
    if params:
        wanted = [p.strip() for p in params.split(",") if p.strip()]
        try:
            real = inspect.signature(obj).parameters
        except (TypeError, ValueError):
            return f"{mod}.{attr}: firma non ispezionabile"
        missing = [p for p in wanted if p not in real]
        if missing:
            return f"{mod}.{attr}: parametri mancanti nella firma reale {missing}"
    return None


def bindings_for(cap_id: str) -> List[str]:
    out: List[str] = []
    for pat, specs in BINDINGS.items():
        if pat == cap_id or (pat.endswith("*") and fnmatch.fnmatch(cap_id, pat)):
            out += [s for s in specs if s not in out]
    return out


def verify_bindings() -> dict:
    """Validate every capability at startup. A failure marks the capability UNBOUND (never executable) but NEVER crashes the server."""
    report = {"bound": 0, "unbound": 0, "critical_blocked": 0, "problems": {}}
    for c in REGISTRY.values():
        problems: List[str] = []
        try:
            if c.risk == CRITICAL:
                c.status, c.unbound_reason = CRITICAL_BLOCKED, "CRITICAL: solo amministratore umano dal pannello, mai via dispatcher"
                report["critical_blocked"] += 1
                continue
            if c.handler is None or not inspect.iscoroutinefunction(c.handler):
                problems.append("handler mancante o non asincrono")
            elif len(inspect.signature(c.handler).parameters) != 1:
                problems.append("handler deve accettare esattamente (ctx)")
            for spec in bindings_for(c.id):
                why = _check_binding(spec)
                if why:
                    problems.append(why)
        except Exception as e:   # a broken capability must not take the whole engine down
            problems.append(f"verifica fallita: {type(e).__name__}: {str(e)[:120]}")
        if problems:
            c.status, c.unbound_reason = UNBOUND, "; ".join(problems)[:400]
            report["unbound"] += 1
            report["problems"][c.id] = problems
        else:
            c.status, c.unbound_reason = BOUND, None
            report["bound"] += 1
    report["total"] = len(REGISTRY)
    if report["unbound"]:
        logger.warning(f"[capabilities] {report['unbound']} capability UNBOUND: {sorted(report['problems'])}")
    logger.info(f"[capabilities] registry verified: {report['bound']} bound / {report['unbound']} unbound / {report['critical_blocked']} critical-blocked of {report['total']}")
    return report


def registry_status() -> dict:
    return {"total": len(REGISTRY), "bound": len([c for c in REGISTRY.values() if c.status == BOUND]), "unbound": [c.id for c in REGISTRY.values() if c.status == UNBOUND],
            "critical_blocked": [c.id for c in REGISTRY.values() if c.status == CRITICAL_BLOCKED],
            "by_risk": {r: len([c for c in REGISTRY.values() if c.risk == r]) for r in (SAFE, REVIEW, CRITICAL)}}


# =====================================================================================================================
# DISPATCHER
# =====================================================================================================================

# =====================================================================================================================
# PHASE 13 — GOOGLE SEO CORE: Search Console (status / sitemap sync / URL inspection / analytics), technical indexability
# and the orchestrated "prepara per Google" workflow. Every Google call goes through backend/google_search (never secrets).
# =====================================================================================================================
REAL_DATA_CODES = {"AGE_CONFIRMATION_MISSING": "conferma_maggiorenne", "ONLYFANS_URL_MISSING": "onlyfans_url", "ONLYFANS_URL_INVALID": "onlyfans_url"}
MEDIA_CODES = {"CARD_PHOTO_MISSING", "PUBLIC_PHOTOS_LT_3", "SECRET_PHOTOS_LT_3", "PUBLIC_VIDEO_MISSING", "SECRET_VIDEO_MISSING", "PELLICOLA_PUBLIC_VIDEO_MISSING", "PELLICOLA_SECRET_VIDEO_MISSING"}


async def _entity_from_params(ctx: Ctx, allow_all: bool = False) -> Optional[dict]:
    """Resolve the public URL to work on from target/model/landing/url/entity_type params (deterministic, no guessing)."""
    from google_search.service import resolve_entity_url, public_base
    p = ctx.params or {}
    if ctx.target:
        return await resolve_entity_url("model", ctx.target["slug"])
    if p.get("model"):
        doc = await resolve_model(str(p["model"]))
        return await resolve_entity_url("model", doc["slug"])
    if p.get("landing"):
        e = await resolve_entity_url("landing", str(p["landing"]))
        if not e:
            raise err(404, "NOT_FOUND", f"Landing '{p['landing']}' non trovata")
        return e
    if p.get("category"):
        e = await resolve_entity_url("category", str(p["category"]))
        if not e:
            raise err(404, "NOT_FOUND", f"Categoria '{p['category']}' non trovata")
        return e
    if p.get("url"):
        u = str(p["url"]).strip()
        base = public_base()
        if not u.startswith(base):
            raise err(422, "VALIDATION_FAILED", f"Solo URL del sito ({base}/...) possono essere ispezionati", received_url=u)
        path = u[len(base):]
        for prefix, et in (("/modelle/", "model"), ("/l/", "landing"), ("/categorie/", "category")):
            if path.startswith(prefix):
                e = await resolve_entity_url(et, path[len(prefix):].strip("/"))
                if e:
                    return e
        if path in ("", "/"):
            return await resolve_entity_url("home", "")
        return {"url": u, "entity_type": "url", "entity_id": u, "slug": None, "published": True, "indexable": True}
    if p.get("home"):
        return await resolve_entity_url("home", "")
    if allow_all:
        return None
    raise err(422, "VALIDATION_FAILED", "Indica la pagina: target (modella) oppure parameters.model / landing / category / url / home=true", missing=["target|model|landing|url"])


@cap("google.status", "google", "Stato Search Console: connessione (service account), proprietà, sitemap registrata/ultimo invio, budget ispezioni, conteggio URL per stato Google. Mai credenziali.",
     ["system:status"], read_only=True, natural=["Google è collegato?", "stato Search Console", "la sitemap è stata inviata a Google?"])
async def _google_status(ctx: Ctx):
    from google_search.service import status, public_entities
    st = await status()
    ents = await public_entities()
    st["public_urls"] = {"total": len(ents), "by_google_state": {k: sum(1 for e in ents if e["google_state"] == k) for k in ("INDEXED", "NOT_INDEXED", "BLOCKED_ERROR", "UNKNOWN", "NOT_INSPECTED")}}
    conn = st["connection"]["status"]
    summ = {"CONNECTED": "Search Console COLLEGATA", "NOT_CONFIGURED": "Search Console NON configurata (serve il service account sul server)", "PROPERTY_NOT_ACCESSIBLE": "Service account senza accesso alla proprietà",
            "ERROR": "Errore Google"}.get(conn, conn)
    warn = [] if conn == "CONNECTED" else [st["connection"].get("detail") or st["connection"].get("message") or conn]
    return R(f"{summ} · proprietà {st['property']} · sitemap {st['sitemap_url']} ({'dirty' if st['sitemap']['dirty'] else 'in sync'}, ultimo invio {st['sitemap']['last_submitted_at'] or 'mai'}) · URL pubblici {len(ents)}",
             st, warnings=[w for w in warn if w], next_steps=[] if conn == "CONNECTED" else ["Configura GOOGLE_SEARCH_ENABLED + GOOGLE_SEARCH_CREDENTIALS_JSON sul server e aggiungi il service account alla proprietà Search Console"])


@cap("google.sitemap.sync", "google", "Invia/re-invia la sitemap a Search Console solo se cambiata o marcata dirty (debounce 6h; force=true per forzare). Mostra la sitemap registrata (lastSubmitted, errori, URL indicizzati).",
     ["seo:update"], rollback=False, params={"force": {"type": "boolean", "default": False}}, examples=[{"action": "google.sitemap.sync", "parameters": {"force": False}, "dry_run": True}],
     natural=["invia la sitemap a Google", "sincronizza la sitemap con Search Console", "re-invia la sitemap"])
async def _google_sitemap_sync(ctx: Ctx):
    from google_search.service import sitemap_sync
    r = await sitemap_sync(force=bool(ctx.params.get("force")), dry_run=ctx.dry)
    if ctx.dry:
        s = f"Anteprima: {'INVIEREI' if r['would_submit'] else 'NON invierei'} la sitemap ({r['urls']} URL) — {r.get('reason') or r.get('skipped_reason')}"
    elif r.get("submitted"):
        s = f"Sitemap inviata a Search Console ({r['urls']} URL) — motivo: {r['reason']}"
    else:
        s = f"Sitemap NON inviata: {r.get('skipped_reason') or (r.get('error') or {}).get('message') or 'nessun motivo per re-inviare'}"
    return R(s, {**r, "dry_run": ctx.dry}, warnings=[r["error"]["message"]] if r.get("error") else [],
             next_steps=[] if r.get("configured") else ["Search Console non configurata: l'invio è simulato/saltato finché il service account non è impostato"])


@cap("google.url.inspect", "google", "Stato REALE su Google di una pagina (URL Inspection API, cache 24h, refresh=true per forzare): INDEXED / NOT_INDEXED / BLOCKED_ERROR / UNKNOWN + coverage, canonical Google, ultimo crawl. Target = modella, oppure parameters.landing/url/home. models=[..] per un gruppo (max 10).",
     ["seo:audit"], target="model", read_only=True,
     params={"model": {"type": "string"}, "landing": {"type": "string"}, "url": {"type": "string"}, "home": {"type": "boolean"}, "models": {"type": "array", "items": {"type": "string"}, "description": "gruppo di modelle (max 10)"}, "refresh": {"type": "boolean", "default": False}},
     examples=[{"action": "google.url.inspect", "target": "Federica Chiatti", "parameters": {"refresh": False}}, {"action": "google.url.inspect", "parameters": {"models": ["vanessa-bella", "alessia-golosa"]}}],
     natural=["Federica è indicizzata su Google?", "Google ha indicizzato Vanessa?", "quali modelle non sono indicizzate?"])
async def _google_url_inspect(ctx: Ctx):
    from google_search.service import inspect, resolve_entity_url, public_entities
    p = ctx.params or {}
    refresh = bool(p.get("refresh"))
    targets: List[dict] = []
    if p.get("models"):
        for ref in list(p["models"])[:10]:
            d = await resolve_model(str(ref))
            e = await resolve_entity_url("model", d["slug"])
            if e:
                targets.append(e)
    elif p.get("all_published"):
        targets = (await public_entities())[:20]
    else:
        targets = [await _entity_from_params(ctx)]
    results = []
    for e in targets:
        if not e.get("published") and e["entity_type"] != "url":
            results.append({"url": e["url"], "slug": e.get("slug"), "state": "NOT_PUBLIC", "detail": "pagina non pubblicata: Google non può indicizzarla (bozza/archiviata)", "entity_type": e["entity_type"]})
            continue
        r = await inspect(e["url"], entity=e, refresh=refresh)
        r["slug"], r["entity_type"], r["indexable_by_us"] = e.get("slug"), e["entity_type"], e.get("indexable")
        results.append(r)
    icons = {"INDEXED": "✅", "NOT_INDEXED": "🟡", "BLOCKED_ERROR": "🔴", "UNKNOWN": "⚪", "NOT_CONFIGURED": "⚪", "NOT_PUBLIC": "⛔"}
    lines = [f"{icons.get(r['state'], '⚪')} {r.get('slug') or r['url']}: {r['state']}" + (f" ({(r.get('google') or {}).get('coverage_state')})" if (r.get('google') or {}).get('coverage_state') else "") for r in results]
    counts = {k: sum(1 for r in results if r["state"] == k) for k in ("INDEXED", "NOT_INDEXED", "BLOCKED_ERROR", "UNKNOWN", "NOT_CONFIGURED", "NOT_PUBLIC")}
    warns = [r.get("detail") for r in results if r.get("detail") and r["state"] in ("NOT_CONFIGURED", "UNKNOWN")] [:2]
    return R(" · ".join(lines) if len(lines) <= 3 else f"{len(results)} URL: {counts}", {"results": results, "counts": counts, "source_note": "stato derivato SOLO da Google URL Inspection (cache 24h); la presenza in sitemap non significa indicizzata"},
             warnings=[w for w in warns if w], target=_tgt(ctx.target) if ctx.target else None)


@cap("google.analytics.summary", "google", "Search Analytics reali (Search Console): click, impressioni, CTR, posizione media per sito / modella / landing / URL. range 7g|28g|3m o start/end; compare=true = periodo precedente.",
     ["analytics:read"], target="model", read_only=True,
     params={"range": {"type": "string", "enum": ["7g", "28g", "3m"], "default": "28g"}, "start": {"type": "string"}, "end": {"type": "string"}, "model": {"type": "string"}, "landing": {"type": "string"}, "url": {"type": "string"}, "compare": {"type": "boolean", "default": True}},
     examples=[{"action": "google.analytics.summary", "target": "Federica Chiatti", "parameters": {"range": "28g"}}, {"action": "google.analytics.summary", "parameters": {"range": "7g"}}],
     natural=["quante impressioni riceve Federica?", "quanti click da Google negli ultimi 28 giorni?", "posizione media di Vanessa"])
async def _google_analytics_summary(ctx: Ctx):
    from google_search.service import analytics, summarize
    e = await _entity_from_params(ctx, allow_all=True)
    p = ctx.params or {}
    r = await analytics([], p.get("range"), p.get("start"), p.get("end"), page=e["url"] if e else None, compare=p.get("compare", True))
    if not r.get("available"):
        return R(f"Search Analytics non disponibile ({r.get('state')})", r, warnings=[r.get("detail") or (r.get("error") or {}).get("message") or "Search Console non configurata"])
    tot = summarize(r["rows"])
    prev = summarize(r["previous"]["rows"]) if r.get("previous") else None
    delta = {k: (tot[k] - prev[k]) if isinstance(tot.get(k), (int, float)) and isinstance(prev.get(k), (int, float)) else None for k in ("clicks", "impressions", "ctr", "position")} if prev else None
    label = e.get("slug") or e["entity_type"] if e else "sito"
    return R(f"Google {label} ({r['start']}→{r['end']}): {tot['clicks']} click, {tot['impressions']} impressioni, CTR {tot['ctr']}%, posizione {tot['position']}" + (f" · vs precedente: click {delta['clicks']:+}, impressioni {delta['impressions']:+}" if delta else ""),
             {"entity": e, "range": {"start": r["start"], "end": r["end"]}, "totals": tot, "previous": prev, "delta": delta, "cached": r.get("cached"), "note": "dati Search Console con ~3 giorni di ritardo; nessun valore inventato"},
             target=_tgt(ctx.target) if ctx.target else None)


@cap("google.analytics.queries", "google", "Query Google (o pagine/paesi/dispositivi/giorni) con click, impressioni, CTR e posizione: per il sito o per una modella/landing/URL. dimension=query|page|country|device|date, limit≤100.",
     ["analytics:read"], target="model", read_only=True,
     params={"range": {"type": "string", "enum": ["7g", "28g", "3m"], "default": "28g"}, "start": {"type": "string"}, "end": {"type": "string"}, "model": {"type": "string"}, "landing": {"type": "string"}, "url": {"type": "string"},
             "dimension": {"type": "string", "enum": ["query", "page", "country", "device", "date"], "default": "query"}, "limit": {"type": "integer", "default": 20}},
     examples=[{"action": "google.analytics.queries", "target": "Federica Chiatti", "parameters": {"dimension": "query", "limit": 10}}, {"action": "google.analytics.queries", "parameters": {"dimension": "page", "range": "28g"}}],
     natural=["quali query portano traffico?", "pagine che ricevono più impressioni", "query Google principali di Federica"])
async def _google_analytics_queries(ctx: Ctx):
    from google_search.service import analytics
    e = await _entity_from_params(ctx, allow_all=True)
    p = ctx.params or {}
    dim = p.get("dimension") or "query"
    r = await analytics([dim], p.get("range"), p.get("start"), p.get("end"), page=e["url"] if (e and dim != "page") else None, page_contains=None, limit=min(int(p.get("limit") or 20), 100))
    if not r.get("available"):
        return R(f"Search Analytics non disponibile ({r.get('state')})", r, warnings=[r.get("detail") or (r.get("error") or {}).get("message") or "Search Console non configurata"])
    rows = [{dim: x["keys"][0] if x["keys"] else None, "clicks": x["clicks"], "impressions": x["impressions"], "ctr": x["ctr"], "position": x["position"]} for x in r["rows"]]
    rows.sort(key=lambda x: (-x["clicks"], -x["impressions"]))
    top = ", ".join(f"{x[dim]} ({x['clicks']} click)" for x in rows[:3])
    return R(f"{len(rows)} {dim} per {e.get('slug') if e else 'sito'} ({r['start']}→{r['end']})" + (f": {top}" if top else ": nessun dato ancora"), {"entity": e, "dimension": dim, "range": {"start": r["start"], "end": r["end"]}, "rows": rows, "cached": r.get("cached")},
             target=_tgt(ctx.target) if ctx.target else None)


@cap("seo.indexability", "seo", "Checklist tecnica di indicizzabilità di una pagina (nessuna quota Google): pubblicata, HTTP 200, robots.txt, X-Robots-Tag, noindex, canonical, presenza in sitemap, title/meta/H1, structured data, og:image, internal links. all=true per tutte le pagine pubbliche (senza fetch HTTP).",
     ["seo:audit"], target="model", read_only=True,
     params={"model": {"type": "string"}, "landing": {"type": "string"}, "category": {"type": "string"}, "url": {"type": "string"}, "home": {"type": "boolean"}, "all": {"type": "boolean", "default": False}, "fetch": {"type": "boolean", "default": True}},
     examples=[{"action": "seo.indexability", "target": "Federica Chiatti", "parameters": {}}, {"action": "seo.indexability", "parameters": {"all": True}}],
     natural=["Federica è tecnicamente indicizzabile?", "controlla tutte le pagine pubblicate e mostrami quelle con problemi"])
async def _seo_indexability(ctx: Ctx):
    from google_search.service import indexability, public_entities
    p = ctx.params or {}
    if p.get("all"):
        ents = (await public_entities())[:60]
        out = [await indexability(e, fetch=False) for e in ents]
        bad = [o for o in out if not o["technically_indexable"]]
        return R(f"{len(out)} pagine pubbliche: {len(out) - len(bad)} tecnicamente indicizzabili, {len(bad)} con problemi" + (f" ({', '.join(o['slug'] or o['url'] for o in bad[:5])})" if bad else ""),
                 {"pages": out, "problems": [{"slug": o["slug"], "url": o["url"], "failing": o["failing"]} for o in bad]})
    e = await _entity_from_params(ctx)
    r = await indexability(e, fetch=p.get("fetch", True))
    return R(("Tecnicamente indicizzabile" if r["technically_indexable"] else f"NON indicizzabile: {', '.join(r['failing'])}") + f" — {e.get('slug') or e['url']}", r,
             warnings=[c["detail"] for c in r["checks"] if not c["ok"]][:6], target=_tgt(ctx.target) if ctx.target else None)


@cap("growth.prepare_model", "workflow", "Workflow 'completa e prepara per Google' (target = modella): readiness (dati reali mancanti → MISSING_REAL_DATA, media mancanti → li carichi tu), audit SEO + fix SAFE (title/meta/OG/canonical/alt/keywords/robots/schema), indexability tecnica, sitemap, landing collegate/internal links, Search Console sync (se pubblicata) e opzionale ispezione Google. NON pubblica: usa models.publish quando pronta.",
     ["models:update", "seo:safe_fix"], target="model", rollback=True,
     conditional_scopes={"seo:update": (lambda p: p.get("sync_sitemap", True) is not False, "solo se sync_sitemap non è false (invio sitemap a Search Console)")},
     params={"inspect": {"type": "boolean", "default": False, "description": "chiedi anche lo stato reale a Google (consuma 1 ispezione)"}, "sync_sitemap": {"type": "boolean", "default": True}},
     examples=[{"action": "growth.prepare_model", "target": "Federica Chiatti", "parameters": {"inspect": False}}],
     natural=["completa Federica Chiatti e preparala per Google", "prepara tutto per Google per Aurora Bianchini", "ho finito i media di Federica: fai tutto il resto"])
async def _growth_prepare_model(ctx: Ctx):
    from v1_seo import run_audit, apply_safe_fixes, internal_link_suggestions
    from google_search.service import indexability, resolve_entity_url, sitemap_sync, inspect, configured
    doc = ctx.target
    label = doc.get("nome_artistico") or doc["slug"]
    steps, warnings, next_steps, version_ids, changes = [], [], [], [], []
    # 1. readiness -> what only the human can provide
    v = validate_model(doc)
    missing_real = sorted({REAL_DATA_CODES[e["code"]] for e in v["errors"] if e["code"] in REAL_DATA_CODES})
    missing_media = [e["field"] for e in v["errors"] if e["code"] in MEDIA_CODES]
    missing_text = [e["field"] for e in v["errors"] if e["code"] not in REAL_DATA_CODES and e["code"] not in MEDIA_CODES]
    steps.append({"step": "readiness", "ready": v["ready"], "workflow_status": workflow_status(doc), "missing_real_data": missing_real, "missing_media": missing_media, "missing_text": missing_text})
    if missing_real:
        warnings.append(f"MISSING_REAL_DATA: {', '.join(missing_real)} — dati reali che devi fornire tu (non vengono mai inventati)")
        next_steps.append(f"Fornisci: {', '.join(missing_real)} (models.update sui campi reali)")
    if missing_media:
        next_steps.append(f"Carica manualmente i media mancanti: {', '.join(missing_media)}")
    if missing_text:
        next_steps.append(f"Completa i testi: {', '.join(missing_text)} (models.update — testi coerenti con il profilo, mai dati personali inventati)")
    # 2. SEO audit + SAFE fixes (real writes in the session; dry_run -> plan only)
    audit = await run_audit(scope="models", entity_id=doc["id"])
    fx = await apply_safe_fixes(scope="models", entity_id=doc["id"], actor=ctx.actor, request_id=request_id_of(ctx.request), source=ctx.source, dry_run=ctx.dry)
    n_fix, vids, applied = _safe_fix_view(fx)
    version_ids += vids
    changes += [{"field": x.get("field") or x.get("code"), "before": x.get("before"), "after": x.get("after") or x.get("suggested_value")} for x in applied]
    review_issues = [i for i in audit.get("issues", []) if i.get("severity") == "REVIEW_REQUIRED"]
    steps.append({"step": "seo", "score_before": audit.get("health_score"), "counts": audit.get("counts"), "safe_fixes": n_fix, "safe_fixes_applied": not ctx.dry and n_fix > 0,
                  "review_required": [{"code": i["code"], "field": i.get("field"), "message": i.get("message")} for i in review_issues][:10]})
    if review_issues:
        next_steps.append(f"{len(review_issues)} issue SEO REVIEW (es. {review_issues[0]['code']}): correggile con models.update/seo.fix_issue (approvazione)")
    # 3. structure / internal links / landings (report only: no automatic landing creation — quality > quantity)
    fresh = await models_col.find_one({"id": doc["id"]}, {"_id": 0}) or doc
    linked_landings = [l["slug"] async for l in landings_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}, "model_slugs": doc["slug"]}, {"_id": 0, "slug": 1})]
    cats = fresh.get("categorie") or []
    related = await models_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}, "id": {"$ne": doc["id"]}, "categorie": {"$in": cats}}) if cats else 0
    try:
        ils = await internal_link_suggestions(limit_per_model=4)
        my_links = next((x for x in (ils.get("items") or ils.get("suggestions") or []) if isinstance(x, dict) and x.get("model") == doc["slug"]), None)
    except Exception:
        my_links = None
    steps.append({"step": "links", "categories": cats, "related_models_same_category": related, "linked_landings": linked_landings, "internal_link_suggestions": my_links,
                  "landing_note": "nessuna landing creata automaticamente: crea una landing solo se aggiunge contenuto originale e un intento di ricerca distinto (landing.create, REVIEW alla pubblicazione)"})
    if not cats:
        next_steps.append("Assegna almeno una categoria (models.categories.set) per link interni e pagina categoria")
    # 4. technical indexability + sitemap
    e = await resolve_entity_url("model", doc["slug"])
    idx = await indexability(e, fetch=bool(e.get("published")))
    steps.append({"step": "indexability", "technically_indexable": idx["technically_indexable"], "failing": idx["failing"], "in_sitemap": "IN_SITEMAP" not in idx["failing"], "url": e["url"]})
    # 5. Search Console sync (only when public) + optional inspection
    if e.get("published") and ctx.params.get("sync_sitemap", True) is not False:
        sync = await sitemap_sync(force=False, dry_run=ctx.dry)
        steps.append({"step": "search_console", "configured": configured(), "would_submit": sync.get("would_submit"), "submitted": sync.get("submitted"), "reason": sync.get("reason") or sync.get("skipped_reason")})
        if not configured():
            warnings.append("Search Console non configurata: sitemap pronta ma non inviata a Google")
        if ctx.params.get("inspect") and not ctx.dry:
            ins = await inspect(e["url"], entity=e, refresh=False)
            steps.append({"step": "google_inspection", "state": ins["state"], "coverage_state": (ins.get("google") or {}).get("coverage_state"), "cached": ins.get("cached")})
    else:
        steps.append({"step": "search_console", "skipped": "modella non pubblicata: la sitemap la includerà automaticamente alla pubblicazione (models.publish) e il sync partirà da solo"})
        if v["ready"] or (not missing_real and not missing_media and not missing_text):
            next_steps.append("Pronta: pubblica con models.publish (validator + sitemap + Search Console automatici)")
    fresh_v = validate_model(fresh)
    status = "READY_TO_PUBLISH" if (fresh_v["ready"] and fresh.get("stato") != "pubblicata") else ("PUBLISHED" if fresh.get("stato") == "pubblicata" else "INCOMPLETE")
    summary = (f"{'Anteprima: ' if ctx.dry else ''}{label}: {status} — SEO fix SAFE {n_fix}{' (anteprima)' if ctx.dry else ''}, "
               f"{'indicizzabile' if idx['technically_indexable'] else 'non indicizzabile (' + ', '.join(idx['failing'][:3]) + ')'}"
               + (f", dati reali mancanti: {', '.join(missing_real)}" if missing_real else "") + (f", media mancanti: {len(missing_media)}" if missing_media else ""))
    return R(summary, {"dry_run": ctx.dry, "status": status, "steps": steps, "missing_real_data": missing_real, "missing_media": missing_media, "publishes": False, "public_url": e["url"]},
             changes=changes, version_ids=version_ids, warnings=warnings, next_steps=next_steps, target=_tgt(doc))


class ExecuteBody(BaseModel):
    """GPT-Action-tolerant request body. Canonical form: {action, target, parameters{...}, dry_run, reason, session_id}.
    Tolerated (deterministic, no policy bypass — everything still goes through the same validator/scopes):
      - `capability` as an alias of `action` (getCapability returns the id as `id`/`capability`);
      - `parameters_json`: the parameters object serialized as a JSON string (GPT Actions serialize free-form nested
        objects unreliably). Must decode to a JSON object; `parameters` wins on conflicting keys;
      - capability parameters leaked at the top level of the body (e.g. {"action": "...", "nome": "..."}): keys that are
        declared in the capability's parameters_schema are hoisted into `parameters` (never unknown keys)."""
    model_config = ConfigDict(extra="allow")
    action: Optional[str] = None
    capability: Optional[str] = None
    target: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    parameters_json: Optional[str] = None
    dry_run: bool = False
    reason: Optional[str] = ""
    session_id: Optional[str] = None
    expected_updated_at: Optional[str] = None
    run_async: bool = False

    def action_id(self) -> str:
        a = (self.action or self.capability or "").strip()
        if not a:
            raise err(422, "VALIDATION_FAILED", "Campo 'action' obbligatorio (id della capability, es. models.prepare_complete)", missing=["action"],
                      hint="POST {action: <capability id>, parameters: {...}} — see getCapability(...).request_example")
        return a


RESERVED_BODY_KEYS = {"action", "capability", "target", "parameters", "parameters_json", "dry_run", "reason", "session_id", "expected_updated_at", "run_async"}


def normalize_parameters(body: ExecuteBody, capability: "Capability") -> tuple:
    """Deterministic normalization of the received body into ONE parameters dict (+ notes for the response/audit).
    Precedence: parameters > parameters_json > top-level leaked keys declared in parameters_schema. No code, no eval:
    `parameters_json` is decoded with json.loads and accepted only if it is a JSON object."""
    notes: List[str] = []
    received = {"parameters": body.parameters if isinstance(body.parameters, dict) else None,
                "parameters_json_present": bool(body.parameters_json),
                "top_level_keys": sorted(k for k in (body.model_extra or {}).keys() if k not in RESERVED_BODY_KEYS)}
    params: Dict[str, Any] = dict(body.parameters) if isinstance(body.parameters, dict) else {}
    if body.parameters is not None and not isinstance(body.parameters, dict):
        raise err(422, "VALIDATION_FAILED", "'parameters' deve essere un oggetto JSON", received=received)
    if body.parameters_json:
        try:
            decoded = json.loads(body.parameters_json)
        except Exception as e:
            raise err(422, "VALIDATION_FAILED", "'parameters_json' non è JSON valido", parameters_json_error=str(e)[:120], received=received)
        if not isinstance(decoded, dict):
            raise err(422, "VALIDATION_FAILED", "'parameters_json' deve decodificare in un oggetto JSON", received=received)
        added = [k for k in decoded if k not in params]
        for k in added:
            params[k] = decoded[k]
        if added:
            notes.append(f"parameters_json: usati {sorted(added)}")
    declared = set((capability.params or {}).keys())
    leaked = {k: v for k, v in (body.model_extra or {}).items() if k in declared and k not in params}
    if leaked:
        params.update(leaked)
        notes.append(f"parametri ricevuti al top-level e spostati in 'parameters': {sorted(leaked)} — inviarli dentro 'parameters'")
    return params, notes, received


TARGET_RESOLVERS = {
    "model": lambda ref: resolve_model(ref),
    "category": lambda ref: resolve_category(ref),
    "alert": lambda ref: resolve_alert(ref),
    "media": lambda ref: find_media(ref),
}
# capabilities whose target is optional (site-wide when omitted)
OPTIONAL_TARGET = {"seo.audit", "seo.issues", "seo.internal_links", "models.undelete", "google.url.inspect", "google.analytics.summary", "google.analytics.queries", "seo.indexability"}
_PY_TYPES = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,), "array": (list,), "object": (dict,)}


async def _resolve_target(kind: str, ref: Optional[str], params: dict):
    if kind == "none":
        return None
    ref = ref or params.get(kind) or params.get("model" if kind == "model" else kind)
    if kind == "job":
        if not ref:
            raise err(422, "VALIDATION_FAILED", "Indica il job (target)", jobs=sorted(SAFE_JOBS))
        j = await jobs_col.find_one({"name": ref}, {"_id": 0})
        if not j:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Job '{ref}' non trovato", "jobs": [x["name"] async for x in jobs_col.find({}, {"_id": 0, "name": 1})]})
        return j
    if kind == "landing":
        if not ref:
            raise err(422, "VALIDATION_FAILED", "Indica la landing (target)")
        from v1_landings import resolve_landing
        return await resolve_landing(ref)
    if not ref:
        return None
    return await TARGET_RESOLVERS[kind](ref)


def key_allows(principal: dict, cap_id: str) -> Optional[str]:
    """Per-key capability policy. DENY always wins; ALLOW (when set) is a further restriction on top of the scopes, never a grant."""
    allow, deny = principal.get("capability_allow") or [], principal.get("capability_deny") or []
    if any(fnmatch.fnmatch(cap_id, d) for d in deny):
        return "denied"
    if allow and not any(fnmatch.fnmatch(cap_id, a) for a in allow):
        return "not_allowed"
    return None


async def disabled_capabilities() -> List[str]:
    c = await config_col.find_one({"id": "global"}, {"_id": 0, "ai": 1}) or {}
    return list(((c.get("ai") or {}).get("capabilities_disabled")) or [])


def _validate_params(capability: Capability, params: dict):
    missing = [k for k, spec in (capability.params or {}).items() if isinstance(spec, dict) and spec.get("required") and params.get(k) in (None, "", [], {})]
    if missing:
        raise err(422, "VALIDATION_FAILED", f"Parametri obbligatori mancanti per '{capability.id}'", missing=missing, parameters_schema=capability.params)
    wrong = []
    for k, spec in (capability.params or {}).items():
        if k in params and params[k] is not None and isinstance(spec, dict) and spec.get("type") in _PY_TYPES:
            ok_types = _PY_TYPES[spec["type"]]
            v = params[k]
            if not isinstance(v, ok_types) or (spec["type"] in ("integer", "number") and isinstance(v, bool)):
                wrong.append({"param": k, "expected": spec["type"], "got": type(v).__name__})
    if wrong:
        raise err(422, "VALIDATION_FAILED", "Tipi parametro non validi", wrong_types=wrong)


def _body_hash(body: ExecuteBody) -> str:
    raw = json.dumps({"action": body.action, "target": body.target, "parameters": body.parameters, "reason": body.reason, "expected_updated_at": body.expected_updated_at}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def unwrap_envelope(env: Any) -> dict:
    """Single normalizer for values returned by reused v1_ai route handlers (they return {ok, action, summary, data, warnings, next_steps, ...}).
    Always yields {ok, summary, data, warnings, next_steps, code} with `data` being the PAYLOAD (never a nested envelope)."""
    if isinstance(env, dict) and "ok" in env and "data" in env and "summary" in env:
        return {"ok": bool(env.get("ok", True)), "summary": env.get("summary") or "", "data": env.get("data") if isinstance(env.get("data"), dict) else {"value": env.get("data")},
                "warnings": list(env.get("warnings") or []), "next_steps": list(env.get("next_steps") or []), "code": env.get("code")}
    if isinstance(env, dict):
        return {"ok": True, "summary": "", "data": env, "warnings": [], "next_steps": [], "code": None}
    return {"ok": True, "summary": "", "data": {"value": env}, "warnings": [], "next_steps": [], "code": None}


async def _gate(principal: dict, request: Request, *scopes: str, write: bool = False):
    """Enforcement for v2 primitives that reuse v1_ai route handlers directly (their `Depends(ai_guard)` is NOT executed when called
    as plain functions): key status (kill switch) -> READ_ONLY -> rate limit -> scopes. Mirrors ai_guard semantics."""
    is_machine = principal.get("type") == "api_key"
    cfg = await ai_config()
    if is_machine:
        if not cfg["enabled"]:
            raise err(503, "AI_API_DISABLED", "ChatGPT API disattivata (kill switch)")
        if write and not cfg["write_enabled"]:
            raise err(403, "READ_ONLY_MODE", "Modalità READ_ONLY: nessuna modifica reale possibile (nemmeno tramite approvazione)")
        request.state.rate = await rate_limit_shared(f"ai:{principal['id']}", min(cfg["rate_limit_per_min"], principal.get("rate_limit", cfg["rate_limit_per_min"])))
    missing = missing_scopes_for(principal, scopes, False)
    if missing:
        raise err(403, "INSUFFICIENT_SCOPE", "Permessi insufficienti", missing_scopes=missing)
    return cfg


async def run_capability(principal: dict, request: Request, body: ExecuteBody, *, force_dry: bool = False, approved: bool = False) -> dict:
    """The whole enforcement chain, in this order:
    registry (unknown/unbound) -> key status (kill switch, disabled capability) -> scopes -> capability allow/deny -> READ_ONLY/FULL -> risk (CRITICAL/batch)
    -> rate limit -> target resolve -> params validation -> concurrency -> idempotency -> preview/approval -> service -> audit -> rollback metadata -> response."""
    from v1_ai import envelope, log_action
    t0 = time.time()
    # 0. body normalization (action alias, parameters / parameters_json / leaked top-level keys -> ONE parameters dict)
    body.action = body.action_id()
    # 1. registry
    capability = REGISTRY.get(body.action)
    if not capability:
        sugg = [k for k in REGISTRY if body.action.split(".")[0] in k][:10]
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_CAPABILITY", "message": f"Capability '{body.action}' inesistente", "suggestions": sugg, "hint": "GET /api/v2/ai/capabilities"})
    if capability.status == UNBOUND:
        raise err(503, "CAPABILITY_UNBOUND", f"Capability '{body.action}' non eseguibile: binding non valido", reason=capability.unbound_reason)
    norm_params, norm_notes, received = normalize_parameters(body, capability)
    body.parameters = norm_params
    request.state.received_body = received
    is_machine = principal.get("type") == "api_key"
    cfg = await ai_config()
    # 2. key status
    if is_machine and not cfg["enabled"]:
        raise err(503, "AI_API_DISABLED", "ChatGPT API disattivata (kill switch)")
    if body.action in await disabled_capabilities():
        raise err(403, "CAPABILITY_DISABLED", f"Capability '{body.action}' disattivata dall'amministratore")
    dry = bool(force_dry or body.dry_run) and not capability.read_only
    write = not capability.read_only
    # 3. scopes (allow-list can never replace them). EXECUTE scopes for a real run, deterministic PREVIEW (read) scopes for a
    #    dry_run; conditional scopes (e.g. media:upload) are required only when the optional parameter that needs them is present.
    req_scopes = capability.required_scopes(body.parameters or {})
    missing = missing_scopes_for(principal, ("ai:execute", *req_scopes), dry and write)
    if missing:
        raise err(403, "INSUFFICIENT_SCOPE", "Permessi insufficienti", missing_scopes=missing, capability=body.action, mode="preview" if (dry and write) else "execute",
                  required_scopes_execute=req_scopes, required_scopes_preview=capability.required_preview_scopes(body.parameters or {}),
                  hint="Con dry_run=true bastano gli scope di lettura (anteprima)" if not (dry and write) else "Mancano scope di lettura per l'anteprima")
    # 4. per-key capability policy (deny > allow > scopes)
    why = key_allows(principal, body.action)
    if why:
        raise err(403, "CAPABILITY_DENIED" if why == "denied" else "CAPABILITY_NOT_ALLOWED", f"Capability '{body.action}' non consentita per questa chiave ({why})")
    # 5. READ_ONLY / FULL (an approval never turns READ_ONLY into a mutation: `approved` is irrelevant here)
    if is_machine and write and not cfg["write_enabled"] and not dry:
        raise err(403, "READ_ONLY_MODE", "Modalità READ_ONLY: usa dry_run=true (anteprima) o chiedi all'amministratore di attivare FULL")
    # 6. risk
    if capability.risk == CRITICAL or capability.status == CRITICAL_BLOCKED:
        raise err(403, "CRITICAL_ACTION_BLOCKED", "Operazione critica: mai automatizzabile, solo amministratore umano dal pannello (anche in modalità FULL)")
    if capability.batch and not cfg["batch_enabled"] and not dry:
        raise err(403, "BATCH_DISABLED", "Operazioni batch disattivate")
    if dry and write and not capability.dry_run:
        raise err(422, "VALIDATION_FAILED", f"'{body.action}' non supporta dry_run")
    # 7. rate limit (machine keys)
    if is_machine:
        request.state.rate = await rate_limit_shared(f"ai:{principal['id']}", min(cfg["rate_limit_per_min"], principal.get("rate_limit", cfg["rate_limit_per_min"])))
    session_id = body.session_id or request.headers.get("X-Session-ID") or f"ses_{uuid.uuid4().hex[:12]}"
    request.state.session_id = session_id
    request.state.ai_write = write and not dry
    request.state.ai_dry_run = dry
    # 8. target
    params = dict(body.parameters or {})
    # tolerate `expected_updated_at` sent inside parameters (or parameters.changes): hoist it to the
    # root-level concurrency token so it is never treated as a business field and always enforced
    for holder in (params, params.get("changes") if isinstance(params.get("changes"), dict) else None):
        if holder is not None and "expected_updated_at" in holder:
            hoisted = holder.pop("expected_updated_at")
            if hoisted and not body.expected_updated_at:
                body.expected_updated_at = str(hoisted)
    target_doc = await _resolve_target(capability.target, body.target, params)
    if capability.target != "none" and target_doc is None and capability.id not in OPTIONAL_TARGET:
        raise err(422, "VALIDATION_FAILED", f"'{body.action}' richiede un target ({capability.target})")
    # 9. params validation (a failure here is audited WITH the received body, redacted, so real GPT requests can be inspected)
    try:
        _validate_params(capability, params)
    except HTTPException as e:
        det = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        det["received"] = {**received, "parameters_normalized": redact(params) if isinstance(params, dict) else params}
        det["request_example"] = capability.request_example(body.target)
        det["hint"] = "Put every required capability parameter inside `parameters` (or `parameters_json`) exactly as named in parameters_schema"
        await log_action(principal, request, body.action, {"target": body.target, "parameters": redact(params), "dry_run": dry, "received": det["received"]},
                         f"Errore: {det.get('code', 'VALIDATION_FAILED')} — {det.get('message', '')}", ok=False, target={"ref": body.target}, started=t0, reason=body.reason or "", session_id=session_id)
        raise HTTPException(status_code=e.status_code, detail=det)
    # 10. concurrency (optimistic): the caller states the version it looked at
    if body.expected_updated_at and target_doc and target_doc.get("updated_at") and target_doc["updated_at"] != body.expected_updated_at:
        raise err(409, "CONFLICT", "Il target è cambiato rispetto alla versione indicata (expected_updated_at)", current_updated_at=target_doc["updated_at"], expected_updated_at=body.expected_updated_at)
    # 11. idempotency (real mutations only)
    idem_key = request.headers.get("Idempotency-Key")
    idem_doc_key = None
    if idem_key and write and not dry:
        idem_doc_key = {"key": f"v2:{principal.get('id')}:{idem_key}"}
        h = _body_hash(body)
        cached = await idempotency_col.find_one(idem_doc_key, {"_id": 0})
        if cached:
            if cached.get("body_hash") != h:
                raise err(409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key già usata con un payload diverso", idempotency_key=idem_key)
            replay = json.loads(cached["body"])
            replay["request_id"] = request_id_of(request)
            replay.setdefault("data", {})["idempotent_replayed"] = True
            return replay
    ctx = Ctx(principal=principal, request=request, params=params, dry=dry, reason=body.reason or "", session_id=session_id, approved=approved,
              expected_updated_at=body.expected_updated_at, target_ref=body.target, target=target_doc)
    # 12. service (preview and execute go through the same handler -> same service/validator, `dry` decides)
    try:
        result = await capability.handler(ctx)
    except HTTPException as e:
        await log_action(principal, request, body.action, {"target": body.target, "parameters": params, "dry_run": dry}, f"Errore: {e.detail if isinstance(e.detail, str) else (e.detail or {}).get('code')}", ok=False,
                         target={"ref": body.target}, started=t0, reason=body.reason or "", session_id=session_id)
        raise
    # 13. approval (REVIEW): proposal only, nothing written; confirm re-enters run_capability with approved=True
    approval = result.get("approval") if not dry else None   # workflow may pre-build a proposal for its REVIEW subset
    if result.get("needs_approval") and not dry:
        na = result["needs_approval"]
        payload = {"action": body.action, "target": body.target, "parameters": params, "reason": body.reason, "session_id": session_id, "expected_updated_at": na.get("expected_updated_at")}
        approval = await create_approval("CAPABILITY", actor_of(principal), result.get("target") or {"ref": body.target}, payload, na.get("before"), na.get("after"), body.reason or f"{body.action} ({', '.join(na.get('fields') or [])})", request_id_of(request))
        approval["id"] = approval.get("approval_id")   # alias: approveApproval/rejectApproval use the id in the path
        approval["confirm_with"] = f"POST /api/v2/ai/approvals/{approval['id']}/approve {{token}}"
        approval["capability"] = body.action
        result["next_steps"] = ["Mostra all'utente prima/dopo e chiedi conferma esplicita", "Conferma: approveApproval {token}"] + result.get("next_steps", [])
    # 14. audit
    version_ids = [v for v in result.get("version_ids") or [] if v]
    await log_action(principal, request, body.action, {"target": body.target, "parameters": params, "dry_run": dry, "approved": approved},
                     result["summary"], ok=True, target=result.get("target") or ({"ref": body.target} if body.target else None), changes=result.get("changes"), version_ids=version_ids, started=t0,
                     rollback_ref=result.get("rollback_ref") or (version_ids[0] if version_ids else None), before=result.get("before"), after=result.get("after"), reason=body.reason or "",
                     session_id=session_id, extra={"secondary": result.get("secondary") or [], "capability_version": capability.version, "risk": capability.risk, "approval_id": approval.get("approval_id") if approval else None})
    if version_ids and not dry:
        bump("mutations")
    # 15. rollback metadata + response
    data = dict(result.get("data") or {})
    data.update({"capability": body.action, "capability_version": capability.version, "risk": capability.risk, "dry_run": dry, "session_id": session_id, "mode": cfg["mode"],
                 "rollback": {"available": bool(version_ids), "version_ids": version_ids, "undo": f"execute rollback.session {{session_id:'{session_id}'}}" if version_ids else None}})
    if result.get("before") is not None and "before" not in data:
        data["before"] = result["before"]
    if result.get("after") is not None and "after" not in data:
        data["after"] = result["after"]
    if result.get("target"):
        data["target"] = result["target"]
    out = envelope(body.action, request, result["summary"], data, list(result.get("warnings") or []) + list(norm_notes), result.get("next_steps"), ok=True, changes=result.get("changes"), approval=approval)
    if idem_doc_key:
        try:
            await idempotency_col.insert_one({**idem_doc_key, "body_hash": _body_hash(body), "status": 200, "body": json.dumps(redact(out), default=str), "request_id": request_id_of(request),
                                              "created_dt": datetime.now(timezone.utc), "created_at": now_iso()})
        except Exception:
            pass
    return out


# =====================================================================================================================
# v2 PRIMITIVES (compact GPT surface: 12 operations)
# =====================================================================================================================
async def _kill_switch(principal: dict):
    if principal.get("type") == "api_key" and not (await ai_config())["enabled"]:
        raise err(503, "AI_API_DISABLED", "ChatGPT API disattivata (kill switch)")


def catalog_for(principal: dict, disabled: List[str], mode: str, category: Optional[str] = None, q: Optional[str] = None, compact: bool = False) -> dict:
    items = []
    for c in REGISTRY.values():
        if not c.executable:
            continue   # UNBOUND / CRITICAL never advertised to machines
        if category and c.category != category:
            continue
        if q and q.lower() not in (c.id + " " + c.description + " " + " ".join(c.natural)).lower():
            continue
        acc = access_for(principal, c)   # base scopes only: conditional scopes depend on the call's parameters
        if acc["access"] == "none" or c.id in disabled or key_allows(principal, c.id):
            continue   # a dry_run-capable capability stays listed (preview_only) even if the key lacks its mutation scopes
        d = c.public() if not compact else {"id": c.id, "category": c.category, "description": c.description, "risk": c.risk, "target": c.target, "read_only": c.read_only,
                                             "parameters": sorted((c.params or {}).keys()), "capability_version": c.version}
        d["access"], d["execute_access"], d["preview_access"] = acc["access"], acc["execute_access"], acc["preview_access"]
        if mode == "READ_ONLY" and not c.read_only:
            d["read_only_note"] = "Modalità READ_ONLY: solo dry_run=true"
        items.append(d)
    cats: Dict[str, int] = {}
    for i in items:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
    return {"capabilities": items, "count": len(items), "by_category": cats, "mode": mode,
            "risk_levels": {SAFE: "eseguita subito (FULL) o anteprima (READ_ONLY)", REVIEW: "anteprima + approvazione esplicita", CRITICAL: "mai via API"},
            "how_to": {"preview": "POST /api/v2/ai/preview {action, target, parameters}", "execute": "POST /api/v2/ai/execute {action, target, parameters, reason, session_id}",
                       "undo": "POST /api/v2/ai/rollback {session_id}"}}


@caps_router.get("/capabilities", operation_id="getCapabilities", summary="Catalogo delle capability eseguibili da questa chiave (filtri: category, q, compact)")
async def v2_get_capabilities(request: Request, category: Optional[str] = None, q: Optional[str] = None, compact: bool = True, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope
    cfg = await _gate(principal, request, "ai:execute")
    cat = catalog_for(principal, await disabled_capabilities(), cfg["mode"], category, q, compact)
    return envelope("capabilities.list", request, f"{cat['count']} capability disponibili ({cfg['mode']})", cat,
                    next_steps=["Dettaglio: GET /api/v2/ai/capabilities/{id}", "Anteprima sempre prima di una modifica: POST /api/v2/ai/preview"])


@caps_router.get("/capabilities/{capability_id}", operation_id="getCapability", summary="Dettaglio di una capability (parametri, scope, rischio, esempi, accesso)")
async def v2_get_capability(capability_id: str, request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope
    cfg = await _gate(principal, request, "ai:execute")
    c = REGISTRY.get(capability_id)
    if not c:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_CAPABILITY", "message": f"Capability '{capability_id}' inesistente", "suggestions": [k for k in REGISTRY if capability_id.split('.')[0] in k][:10]})
    pub = c.public()
    pub.update(access_for(principal, c))   # execute_access / preview_access / access (legacy) + missing scopes per mode
    pub["disabled"] = capability_id in await disabled_capabilities()
    pub["key_restriction"] = key_allows(principal, capability_id)
    pub["mode"] = cfg["mode"]
    if c.status != BOUND and principal.get("type") != "api_key":
        pub["status_reason"] = c.unbound_reason
    return envelope("capabilities.get", request, f"{c.id}: {c.description[:120]}", pub)


@caps_router.post("/preview", operation_id="previewCapability", summary="Anteprima (dry_run forzato): before/after/diff/warnings, nessuna modifica scritta")
async def v2_preview(body: ExecuteBody, request: Request, principal: dict = Depends(resolve_principal)):
    return await run_capability(principal, request, body, force_dry=True)


@caps_router.post("/execute", operation_id="executeCapability", summary="Esegue una capability (dispatcher deterministico: scope, policy, READ_ONLY, approvazione, audit, rollback)")
async def v2_execute(body: ExecuteBody, request: Request, principal: dict = Depends(resolve_principal)):
    if body.run_async and REGISTRY.get(body.action) and REGISTRY[body.action].batch and not body.dry_run:
        return await _enqueue(principal, request, body)
    return await run_capability(principal, request, body)


# ---------------- async jobs (base) ----------------
ai_jobs_col = _db["ai_jobs"]
_bg_tasks: set = set()


async def _enqueue(principal: dict, request: Request, body: ExecuteBody) -> dict:
    from v1_ai import envelope
    # enforce the whole chain in dry mode first: a job is never queued for something the caller could not execute
    await run_capability(principal, request, ExecuteBody(**{**body.model_dump(), "dry_run": True, "run_async": False}), force_dry=True)
    job = {"id": f"aij_{uuid.uuid4().hex[:12]}", "status": "queued", "action": body.action, "target": body.target, "parameters": redact(body.parameters), "actor": actor_of(principal),
           "created_at": now_iso(), "started_at": None, "finished_at": None, "progress": 0, "result": None, "error": None, "request_id": request_id_of(request), "session_id": body.session_id}
    await ai_jobs_col.insert_one(dict(job))

    async def _run():
        await ai_jobs_col.update_one({"id": job["id"]}, {"$set": {"status": "running", "started_at": now_iso(), "progress": 10}})
        try:
            res = await run_capability(principal, request, ExecuteBody(**{**body.model_dump(), "run_async": False}))
            await ai_jobs_col.update_one({"id": job["id"]}, {"$set": {"status": "done", "finished_at": now_iso(), "progress": 100, "result": redact({k: v for k, v in res.items() if k != "request_id"})}})
        except Exception as e:
            await ai_jobs_col.update_one({"id": job["id"]}, {"$set": {"status": "failed", "finished_at": now_iso(), "error": str(getattr(e, "detail", e))[:500]}})
    t = asyncio.create_task(_run())
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return envelope(body.action, request, f"Operazione '{body.action}' accodata (job {job['id']})", {"job_id": job["id"], "status": "queued", "poll": f"GET /api/v2/ai/jobs/{job['id']}"}, next_steps=[f"Controlla GET /api/v2/ai/jobs/{job['id']}"])


@caps_router.get("/jobs/{job_id}", operation_id="getJob", summary="Stato di un job asincrono AI")
async def v2_get_job(job_id: str, request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope
    await _gate(principal, request, "ai:execute")
    j = await ai_jobs_col.find_one({"id": job_id}, {"_id": 0})
    if not j:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Job non trovato"})
    if principal.get("type") == "api_key" and j.get("actor") != actor_of(principal):
        raise err(403, "INSUFFICIENT_SCOPE", "Puoi consultare solo i tuoi job")
    return envelope("jobs.get", request, f"Job {job_id}: {j['status']} ({j.get('progress', 0)}%)", j)


# ---------------- approvals ----------------
class ApproveBody(BaseModel):
    token: Optional[str] = None
    reason: Optional[str] = ""


@caps_router.get("/approvals", operation_id="listApprovals", summary="Proposte in attesa di approvazione (le API key vedono solo le proprie)")
async def v2_list_approvals(request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope
    await _gate(principal, request, "ai:execute")
    items = await list_pending_approvals(actor_of(principal) if principal.get("type") == "api_key" else None)
    return envelope("approvals.list", request, f"{len(items)} proposte in attesa", {"items": items, "count": len(items)})


async def execute_approved_capability(doc: dict, principal: dict, request: Request) -> dict:
    """Re-enter the SAME chain with approved=True. Scopes, READ_ONLY, CRITICAL, allow/deny, concurrency are all re-checked: an approval never bypasses enforcement."""
    p = doc.get("payload") or {}
    body = ExecuteBody(action=p["action"], target=p.get("target"), parameters=p.get("parameters") or {}, dry_run=False, reason=p.get("reason") or "", session_id=p.get("session_id"), expected_updated_at=p.get("expected_updated_at"))
    return await run_capability(principal, request, body, approved=True)


@caps_router.post("/approvals/{approval_id}/approve", operation_id="approveApproval", summary="Approva ed esegue una proposta (token per API key; admin JWT senza token). Mai in READ_ONLY.")
async def v2_approve(approval_id: str, body: ApproveBody, request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import ai_confirm, AIConfirm
    doc = await approvals_col.find_one({"id": approval_id}, {"_id": 0, "token_hash": 0})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Approvazione non trovata"})
    # ai_confirm's Depends(ai_guard(...write=True)) does not run when called as a function -> enforce the same gate here, BEFORE the token is consumed
    await _gate(principal, request, "ai:execute", write=True)
    if principal.get("type") == "api_key":
        if not body.token:
            raise err(400, "APPROVAL_INVALID", "Le API key devono fornire il token di approvazione")
        if doc.get("actor") != actor_of(principal):
            raise err(403, "APPROVAL_INVALID", "Puoi confermare solo le tue proposte")
        return await ai_confirm(AIConfirm(token=body.token, reason=body.reason or ""), request, principal)
    # human admin (JWT): approve without token
    if doc.get("status") != "pending":
        raise err(409, "APPROVAL_INVALID", f"Approvazione in stato {doc.get('status')}")
    if doc.get("expires_at", "") < now_iso():
        await approvals_col.update_one({"id": doc["id"]}, {"$set": {"status": "expired"}})
        raise err(410, "APPROVAL_EXPIRED", "Approvazione scaduta")
    if doc.get("type") != "CAPABILITY":
        raise err(422, "VALIDATION_FAILED", f"Tipo approvazione {doc.get('type')}: usa /api/v1/ai/approvals/confirm con il token")
    res = await execute_approved_capability(doc, principal, request)   # runs the chain first: if it fails the approval stays pending
    await approvals_col.update_one({"id": doc["id"]}, {"$set": {"status": "used", "used_at": now_iso(), "approved_by": actor_of(principal)}})
    bump("approvals_confirmed")
    res["data"]["approval_id"] = approval_id
    return res


@caps_router.post("/approvals/{approval_id}/reject", operation_id="rejectApproval", summary="Rifiuta una proposta in attesa (nessuna modifica)")
async def v2_reject(approval_id: str, body: ApproveBody, request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope, log_action
    await _gate(principal, request, "ai:execute")
    doc = await approvals_col.find_one({"id": approval_id}, {"_id": 0, "token_hash": 0})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Approvazione non trovata"})
    if doc.get("status") != "pending":
        raise err(409, "APPROVAL_INVALID", f"Approvazione in stato {doc.get('status')}")
    if principal.get("type") == "api_key" and doc.get("actor") != actor_of(principal):
        raise err(403, "APPROVAL_INVALID", "Puoi rifiutare solo le tue proposte")
    await approvals_col.update_one({"id": approval_id}, {"$set": {"status": "rejected", "rejected_at": now_iso(), "rejected_by": actor_of(principal), "reject_reason": body.reason or ""}})
    await log_action(principal, request, "approvals.reject", {"approval_id": approval_id}, f"Proposta {doc.get('type')} rifiutata", target=doc.get("target"), reason=body.reason or "")
    return envelope("approvals.reject", request, f"Proposta rifiutata: nessuna modifica applicata ({doc.get('type')})", {"approval_id": approval_id, "status": "rejected"})


# ---------------- analytics / status / rollback / find (thin primitives over existing services) ----------------
@caps_router.post("/analytics/query", operation_id="queryAnalytics", summary="Interroga le analytics (metric/group_by/model/range) riusando il motore Phase 10")
async def v2_query_analytics(body: Dict[str, Any], request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import ai_query, AIQuery, envelope
    await _gate(principal, request, "analytics:read")
    u = unwrap_envelope(await ai_query(AIQuery(**(body or {})), request, principal))
    data = dict(u["data"]); data["capability"] = "analytics.query"
    return envelope("analytics.query", request, u["summary"], data, u["warnings"], u["next_steps"], ok=u["ok"], code=u["code"])


@caps_router.get("/status", operation_id="getSystemStatus", summary="Stato sistema: modalità (READ_ONLY/FULL), salute, alert correnti, registry capability")
async def v2_status(request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import ai_status, envelope
    await _gate(principal, request, "system:status")
    u = unwrap_envelope(await ai_status(request, principal))
    data = dict(u["data"])
    data["capabilities_registry"] = {k: (v if not isinstance(v, list) else len(v)) for k, v in registry_status().items()}
    data["mode"] = (await ai_config())["mode"]   # top-level for GPT convenience (also in data.ai.mode)
    data["capability"] = "system.status"
    return envelope("system.status", request, u["summary"], data, u["warnings"], u["next_steps"], ok=u["ok"], code=u["code"])


class RollbackBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version_id: Optional[str] = None
    session_id: Optional[str] = None
    model: Optional[str] = None
    minutes: Optional[int] = None
    dry_run: bool = False
    reason: Optional[str] = ""


@caps_router.post("/rollback", operation_id="rollback", summary="Annulla: una versione (version_id), una sessione intera (session_id) o le modifiche a una modella negli ultimi N minuti")
async def v2_rollback(body: RollbackBody, request: Request, principal: dict = Depends(resolve_principal)):
    if body.version_id:
        eb = ExecuteBody(action="rollback.version", parameters={"version_id": body.version_id}, dry_run=body.dry_run, reason=body.reason)
    elif body.session_id:
        eb = ExecuteBody(action="rollback.session", parameters={"session_id": body.session_id}, dry_run=body.dry_run, reason=body.reason)
    elif body.model:
        eb = ExecuteBody(action="rollback.window", target=body.model, parameters={"minutes": body.minutes or 20}, dry_run=body.dry_run, reason=body.reason)
    else:
        raise err(422, "VALIDATION_FAILED", "Indica version_id, session_id oppure model (+minutes)")
    return await run_capability(principal, request, eb)


class FindBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reference: str


@caps_router.post("/models/find", operation_id="findModel", summary="Risolve un riferimento (id, slug, nome, nome parziale) in una modella; 409 AMBIGUOUS_REFERENCE se più corrispondenze")
async def v2_find_model(body: FindBody, request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope
    from v1_models import summary as model_summary
    await _gate(principal, request, "models:read")
    doc = await resolve_model(body.reference)
    s = model_summary(doc)
    s["etag"] = doc.get("updated_at")
    return envelope("models.find", request, f"Trovata: {s.get('nome_artistico') or s.get('nome')} ({s['slug']}, {s['workflow_status']})", s,
                    next_steps=["Dettaglio: execute models.get", "Modifica: preview models.update {changes}"])


# ---------------- OpenAPI v2 (compact GPT Action schema, public document, separate from v1) ----------------
def build_openapi_v2(base_url: str, mode: str) -> dict:
    from v1_ai_openapi import _op, _p
    PARAMS_DESC = ("Parameters for the selected capability. After calling getCapability, copy ALL required and requested capability parameters into this "
                   "object using EXACTLY the property names returned by parameters_schema (see also example_parameters / request_example). "
                   "Example for models.prepare_complete: {\"nome\": \"TEST V2 GIULIA\"}. Example for models.update: {\"changes\": {\"badge\": \"Nuova\"}}. "
                   "Never send capability parameters at the top level of the body and never omit a required parameter.")
    EXEC = {"type": "object", "required": ["action", "parameters"], "properties": {
        "action": {"type": "string", "description": "Capability id exactly as returned by getCapabilities/getCapability (e.g. models.update, media.assign, seo.safe_fix, models.prepare_complete)",
                   "example": "models.prepare_complete"},
        "target": {"type": ["string", "null"], "description": "Target reference when the capability has a target (model id/slug/name, landing slug, category, alert id, job name); omit/null for capabilities without target (e.g. models.prepare_complete, models.create). Ambiguous -> 409 AMBIGUOUS_REFERENCE with data.matches"},
        "parameters": {"type": "object", "additionalProperties": True, "description": PARAMS_DESC,
                       "properties": {"nome": {"type": "string", "description": "e.g. models.prepare_complete / models.create: name of the model to create"},
                                      "changes": {"type": "object", "additionalProperties": True, "description": "e.g. models.update / settings.update: fields to change"},
                                      "fields": {"type": "object", "additionalProperties": True, "description": "e.g. models.prepare_complete: form fields to set on the draft"},
                                      "media": {"description": "e.g. media.assign: media reference (string) / models.prepare_complete: array of {media|url, slot, alt}"},
                                      "slot": {"type": "string", "description": "e.g. media.assign: card, cover, public_photo_1, secret_photo_1, filmstrip_public..."}},
                       "example": {"nome": "TEST V2 GIULIA"}},
        "parameters_json": {"type": "string", "description": "FALLBACK ONLY if you cannot send `parameters` as a nested object: the same parameters object serialized as a JSON string, e.g. \"{\\\"nome\\\": \\\"TEST V2 GIULIA\\\"}\". Must be a JSON object. If both are present, `parameters` wins."},
        "dry_run": {"type": "boolean", "default": False, "description": "true = preview only, nothing written (the only mode accepted in READ_ONLY). previewCapability forces it."},
        "reason": {"type": "string", "description": "Why (stored in audit/version history)"},
        "session_id": {"type": "string", "description": "Group related changes so they can be undone together with rollback {session_id}"},
        "expected_updated_at": {"type": "string", "description": "Optimistic concurrency: updated_at you last saw (409 CONFLICT if changed)"}},
        "example": {"action": "models.prepare_complete", "target": None, "parameters": {"nome": "TEST V2 GIULIA"}, "dry_run": True, "reason": "prepare the draft without publishing", "session_id": None}}
    paths: Dict[str, Any] = {
        "/api/v2/ai/capabilities": {"get": _op("getCapabilities", "List capabilities this key can run", "Compact catalog: id, category, description, risk, target, parameters, access. Filter with category/q. Call first.",
                                              [_p("category", "query", "models|media|homepage|categories|seo|landing|alerts|jobs|backup|system|rollback|workflow"), _p("q", "query", "Free text filter"), _p("compact", "query", "true (default) = short form", typ="boolean", default=True)], tag="Capabilities")},
        "/api/v2/ai/capabilities/{capability_id}": {"get": _op("getCapability", "Capability detail",
                                                               "parameters_schema, required_parameters, example_parameters and request_example (the exact previewCapability body to send), scopes, risk, execute_access/preview_access. Call it before preview/execute when the parameters are not already known.",
                                                               [_p("capability_id", "path", "Capability id", True)], tag="Capabilities")},
        "/api/v2/ai/preview": {"post": _op("previewCapability", "Preview one registered capability (no write)",
                                           "Preview one registered capability: same validation as execute, dry_run forced, nothing written. Put capability-specific inputs INSIDE `parameters` with the exact names of parameters_schema; if getCapability says a field is required it MUST be inside `parameters`. Always preview before executing.",
                                           body=EXEC, tag="Execute")},
        "/api/v2/ai/execute": {"post": _op("executeCapability", "Execute one registered capability",
                                           "Execute one registered capability. Same body as previewCapability: inputs INSIDE `parameters` with the exact names of parameters_schema, required fields never omitted. REVIEW_REQUIRED -> approval_required + token: show before/after, ask the user. READ_ONLY accepts only dry_run=true.",
                                           body=EXEC, tag="Execute")},
        "/api/v2/ai/approvals": {"get": _op("listApprovals", "Pending approvals", "Your pending proposals (before/after, expiry).", tag="Approvals")},
        "/api/v2/ai/approvals/{approval_id}/approve": {"post": _op("approveApproval", "Approve and apply a proposal", "Requires the token returned with approval_required. Blocked in READ_ONLY. Only after explicit user confirmation.",
                                                                   [_p("approval_id", "path", "Approval id", True)], {"type": "object", "required": ["token"], "properties": {"token": {"type": "string"}, "reason": {"type": "string"}}}, tag="Approvals")},
        "/api/v2/ai/approvals/{approval_id}/reject": {"post": _op("rejectApproval", "Reject a proposal", "Nothing is changed.", [_p("approval_id", "path", "Approval id", True)], {"type": "object", "properties": {"reason": {"type": "string"}}}, tag="Approvals")},
        "/api/v2/ai/jobs/{job_id}": {"get": _op("getJob", "Async job status", "Poll a job returned by execute with run_async.", [_p("job_id", "path", "Job id", True)], tag="System")},
        "/api/v2/ai/analytics/query": {"post": _op("queryAnalytics", "Query analytics", "metric (visits, model_views, secret_opens, cta_clicks, onlyfans_clicks, onlyfans_ctr, conversion_rate...), group_by (model, day, country, device), model, range (7g/30g/90g).",
                                                   body={"type": "object", "properties": {"metric": {"type": "string"}, "group_by": {"type": "string"}, "model": {"type": "string"}, "range": {"type": "string", "default": "30g"}, "question": {"type": "string"}}}, tag="Analytics")},
        "/api/v2/ai/status": {"get": _op("getSystemStatus", "System status", "Mode (READ_ONLY/FULL), health, current alerts, registry counts. Call when the user asks how the site is doing.", tag="System")},
        "/api/v2/ai/rollback": {"post": _op("rollback", "Undo changes", "version_id = one change; session_id = everything done in that session (incl. media, SEO, links); model+minutes = recent changes to a model. dry_run for a plan.",
                                            body={"type": "object", "properties": {"version_id": {"type": "string"}, "session_id": {"type": "string"}, "model": {"type": "string"}, "minutes": {"type": "integer"}, "dry_run": {"type": "boolean"}, "reason": {"type": "string"}}}, tag="Rollback")},
        "/api/v2/ai/models/find": {"post": _op("findModel", "Find a model", "Resolve id/slug/name/partial name. 409 AMBIGUOUS_REFERENCE lists matches: show them, never pick one yourself.",
                                               body={"type": "object", "required": ["reference"], "properties": {"reference": {"type": "string"}}}, tag="Models")},
    }
    n_ops = sum(len(v) for v in paths.values())
    assert n_ops == 12, n_ops
    return {
        "openapi": "3.1.0",
        "info": {"title": "LATO SEGRETO — Total Site Control API v2", "version": "2.0.0",
                 "description": (f"12 universal operations. Discover capabilities with getCapabilities, preview with previewCapability, apply with executeCapability. Server mode: {mode}. "
                                 "Auth: API key as Bearer token. Every response: {ok, summary, data, warnings, next_steps, request_id, changes, approval_required}. "
                                 "Never state a change happened unless ok:true and data.rollback.version_ids is non-empty. In READ_ONLY only dry_run previews are possible.")},
        "servers": [{"url": base_url, "description": "LATO SEGRETO API"}] if base_url else [],
        "paths": paths,
        "components": {
            "securitySchemes": {"ApiKeyBearer": {"type": "http", "scheme": "bearer", "description": "Dedicated AI API Key as Bearer token. Create it in /admin/motore → ChatGPT Control Layer."}},
            "schemas": {
                "AIResponse": {"type": "object", "properties": {"ok": {"type": "boolean"}, "action": {"type": "string"}, "summary": {"type": "string"}, "data": {"type": "object", "additionalProperties": True},
                                                               "warnings": {"type": "array", "items": {"type": "string"}}, "next_steps": {"type": "array", "items": {"type": "string"}}, "request_id": {"type": "string"},
                                                               "changes": {"type": "array", "items": {"type": "object", "additionalProperties": True}}, "approval_required": {"type": "boolean"},
                                                               "approval": {"type": "object", "additionalProperties": True}, "code": {"type": "string"}}},
                "AIError": {"type": "object", "properties": {"ok": {"type": "boolean"}, "code": {"type": "string", "enum": ERROR_CODES + ["UNKNOWN_CAPABILITY", "CAPABILITY_UNBOUND", "CAPABILITY_DISABLED", "CAPABILITY_DENIED", "CAPABILITY_NOT_ALLOWED"]},
                                                            "summary": {"type": "string"}, "data": {"type": "object", "additionalProperties": True}, "request_id": {"type": "string"}}},
            },
        },
        "security": [{"ApiKeyBearer": []}],
        "tags": [{"name": "Capabilities"}, {"name": "Execute"}, {"name": "Approvals"}, {"name": "Analytics"}, {"name": "System"}, {"name": "Rollback"}, {"name": "Models"}],
    }


@caps_router.get("/openapi-chatgpt.json", operation_id="getAiOpenApiV2", include_in_schema=False)
async def v2_openapi(request: Request):
    """Public GPT Action schema for the v2 engine (no secrets; separate from /api/v1/ai/openapi-chatgpt.json which stays as-is)."""
    from v1_ai import _public_base_url
    cfg = await ai_config()
    return build_openapi_v2(await _public_base_url(request), cfg["mode"])


# ---------------- admin: capability governance (JWT only, hidden from the GPT schema) ----------------
class CapToggle(BaseModel):
    capability_id: str
    disabled: bool


def _admin_only(principal: dict):
    if principal.get("type") == "api_key" or principal.get("role") not in ("SUPER_ADMIN", "ADMIN"):
        raise err(403, "CRITICAL_ACTION_BLOCKED", "Solo amministratori umani (JWT SUPER_ADMIN/ADMIN)")


@caps_router.get("/admin/capabilities", operation_id="adminCapabilities", include_in_schema=False)
async def v2_admin_capabilities(request: Request, principal: dict = Depends(resolve_principal)):
    _admin_only(principal)
    disabled = await disabled_capabilities()
    items = [{**c.public(), "disabled": c.id in disabled, "status_reason": c.unbound_reason, "bindings": bindings_for(c.id)} for c in REGISTRY.values()]
    use = {}
    async for a in ai_actions_col.aggregate([{"$match": {"action": {"$in": list(REGISTRY.keys())}}}, {"$group": {"_id": "$action", "n": {"$sum": 1}, "err": {"$sum": {"$cond": ["$ok", 0, 1]}}}}]):
        use[a["_id"]] = {"count": a["n"], "errors": a["err"]}
    for i in items:
        i["usage"] = use.get(i["id"], {"count": 0, "errors": 0})
    st = registry_status()
    recent = await ai_actions_col.find({"action": {"$in": list(REGISTRY.keys())}}, {"_id": 0, "id": 1, "action": 1, "ok": 1, "summary": 1, "actor": 1, "timestamp": 1, "duration_ms": 1, "session_id": 1, "target": 1, "input": 1, "rollback_ref": 1, "risk": 1}).sort("timestamp", -1).to_list(25)
    recent_errors = await ai_actions_col.find({"action": {"$in": list(REGISTRY.keys())}, "ok": False}, {"_id": 0, "id": 1, "action": 1, "summary": 1, "actor": 1, "timestamp": 1, "target": 1}).sort("timestamp", -1).to_list(15)
    for r in recent:   # dry-run flag from redacted input, never the raw payload
        r["dry_run"] = bool((r.pop("input", None) or {}).get("dry_run"))
    keys = await api_keys_col.find({"revoked_at": None}, {"_id": 0, "id": 1, "name": 1, "role": 1, "prefix": 1, "active": 1, "capability_allow": 1, "capability_deny": 1, "source": 1}).sort("created_at", -1).to_list(50)
    return {"items": items, "total": len(items), "disabled": len(disabled), "enabled": len([i for i in items if not i["disabled"] and i["status"] == BOUND]),
            "bound": st["bound"], "unbound": st["unbound"], "critical_blocked": st["critical_blocked"], "by_risk": st["by_risk"],
            "by_category": {c: len([i for i in items if i["category"] == c]) for c in sorted({i["category"] for i in items})}, "mode": (await ai_config())["mode"],
            "recent": recent, "recent_errors": recent_errors, "keys": keys}


@caps_router.post("/admin/capabilities/toggle", operation_id="adminToggleCapability", include_in_schema=False)
async def v2_admin_toggle(body: CapToggle, request: Request, principal: dict = Depends(resolve_principal)):
    _admin_only(principal)
    if body.capability_id not in REGISTRY:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_CAPABILITY", "message": "Capability inesistente"})
    disabled = set(await disabled_capabilities())
    (disabled.add if body.disabled else disabled.discard)(body.capability_id)
    await config_col.update_one({"id": "global"}, {"$set": {"ai.capabilities_disabled": sorted(disabled), "updated_at": now_iso()}}, upsert=True)
    await audit_log(actor_of(principal), "ai.capability_toggle", "config", "global", {"capability": body.capability_id, "disabled": body.disabled}, request_id_of(request), "admin")
    return {"capability_id": body.capability_id, "disabled": body.disabled, "disabled_list": sorted(disabled)}
