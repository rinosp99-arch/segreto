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
import fnmatch
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Callable, Awaitable

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict

from database import (models_col, files_col, categories_col, settings_col, config_col, alerts_col, jobs_col, job_runs_col,
                      backups_col, versions_col, ai_actions_col, admins_col, landings_col, seo_issues_col, redirects_col, articles_col, now_iso)
from v1_security import resolve_principal, has_scope, actor_of, request_id_of, CRITICAL_SCOPES, rate_limit_shared, err
from v1_ai_policy import (redact, ai_config, classify_model_changes, create_approval, consume_approval, list_pending_approvals, approvals_col,
                          missing_scopes_for, PREVIEW_SCOPE, bump)
from v1_models import (resolve_model, create_model, patch_model, transition, validate_model, deep_merge, enrich, workflow_status,
                       ALLOWED_FIELDS, unique_slug, onlyfans_url_status)
from v1_versioning import record_version, audit_log, rollback_version, diff_fields

caps_router = APIRouter(prefix="/api/v1/ai", tags=["AI - Universal engine"])

SAFE, REVIEW, CRITICAL = "SAFE", "REVIEW_REQUIRED", "CRITICAL"


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
    version: str = "1.0"
    read_only: bool = False     # pure read (never a mutation) -> allowed in READ_ONLY and never needs dry_run

    def public(self) -> dict:
        return {"id": self.id, "category": self.category, "description": self.description, "required_scopes": self.scopes, "risk": self.risk,
                "supports_dry_run": self.dry_run and not self.read_only, "supports_rollback": self.rollback and not self.read_only, "supports_batch": self.batch,
                "requires_approval": self.requires_approval or self.risk == REVIEW, "read_only": self.read_only, "target": self.target,
                "parameters_schema": {"type": "object", "properties": self.params}, "examples": self.examples, "natural_references": self.natural,
                "capability_version": self.version}


REGISTRY: Dict[str, Capability] = {}


def cap(id: str, category: str, description: str, scopes: List[str], **kw):
    def deco(fn):
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
      rollback_ref: Optional[str] = None) -> dict:
    return {"summary": summary, "data": data if data is not None else {}, "changes": changes or [], "version_ids": version_ids or [], "before": before, "after": after,
            "warnings": warnings or [], "next_steps": next_steps or [], "needs_approval": needs_approval, "target": target, "rollback_ref": rollback_ref}


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
        doc = await files_col.find_one({"$or": [{"url": ref}, {"variants.web": ref}, {"variants.original": ref}], **q_del}, {"_id": 0})
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


def media_summary(f: dict) -> dict:
    return {"id": f.get("id"), "tipo": f.get("tipo"), "url": (f.get("variants") or {}).get("web") or f.get("url"), "name": f.get("seo_name") or f.get("original_filename"),
            "alt": f.get("alt"), "width": f.get("width"), "height": f.get("height"), "duration": f.get("duration"), "size": f.get("size"), "model_id": f.get("model_id"),
            "slot": f.get("slot"), "created_at": f.get("created_at"), "is_deleted": f.get("is_deleted", False)}


# Semantic slots -> technical (slot, side, tipo, index)
SEMANTIC_SLOT_RX = re.compile(r"^(public|secret)_(photo|video)_(\d)$")
SIMPLE_SLOTS = {"card": ("foto_card", "pubblico", "image"), "cover": ("foto_copertina", "pubblico", "image"), "teaser": ("foto_card_teaser", "pubblico", "image"),
                "secret_hero": ("foto_segreta_hero", "segreto", "image"), "og_image": ("og_image", "pubblico", "image"),
                "filmstrip_public": ("pellicola", "pubblico", "video"), "filmstrip_secret": ("pellicola", "segreto", "video"),
                "message_photo": ("messaggio_foto", "segreto", "image"), "message_video": ("messaggio_video", "segreto", "video"),
                "gallery_public": ("galleria_pubblica", "pubblico", "image"), "gallery_secret": ("galleria_segreta", "segreto", "image")}


def parse_slot(slot: str):
    """Return (technical_slot, side, tipo, pair_index|None). Semantic: public_photo_2, secret_video_1 ... Technical slots accepted too."""
    s = (slot or "").strip().lower()
    m = SEMANTIC_SLOT_RX.match(s)
    if m:
        side = "pubblico" if m.group(1) == "public" else "segreto"
        tipo = "image" if m.group(2) == "photo" else "video"
        return "pair", side, tipo, int(m.group(3))
    if s in SIMPLE_SLOTS:
        return SIMPLE_SLOTS[s]
    from v1_media import SLOTS
    if s in SLOTS:
        return s, "pubblico", "image", None
    raise err(400, "VALIDATION_FAILED", "Slot non valido", slots=sorted(list(SIMPLE_SLOTS) + ["public_photo_1..3", "public_video_1..2", "secret_photo_1..3", "secret_video_1..2"]))


def pair_index_for(doc: dict, tipo: str, n: int) -> Optional[int]:
    """n-th (1-based) pair of the given tipo. None -> a new pair will be created."""
    idxs = [i for i, p in enumerate(doc.get("media_pairs") or []) if p.get("tipo") == tipo]
    return idxs[n - 1] if n - 1 < len(idxs) else None


async def apply_media_to_slot(ctx: Ctx, doc: dict, url: str, slot: str, alt: str = "", poster: str = "", reason: str = "") -> dict:
    from v1_media import attach_to_model
    tech, side, tipo, n = parse_slot(slot)
    pidx = pair_index_for(doc, tipo, n) if n else None
    if ctx.dry:
        # build the same change attach_to_model would build and preview it through patch_model
        preview_doc = dict(doc)
        # simulate with a dry attach: attach_to_model always writes -> emulate by computing changes on a copy
        import copy
        sim = copy.deepcopy(doc)
        sim_changes = {}
        if tech == "pair":
            pairs = [dict(p) for p in (sim.get("media_pairs") or [])]
            if pidx is None:
                pairs.append({"id": str(uuid.uuid4()), "tipo": tipo, "pubblico": {"tipo": tipo, "url": "", "poster": "", "alt": ""}, "segreto": {"tipo": tipo, "url": "", "poster": "", "alt": ""}})
                pidx = len(pairs) - 1
            item = dict(pairs[pidx].get(side) or {})
            item.update({"tipo": tipo, "url": url, "alt": alt or item.get("alt", "")})
            if poster:
                item["poster"] = poster
            pairs[pidx][side] = item
            sim_changes["media_pairs"] = pairs
        elif tech in ("foto_card", "foto_copertina", "foto_card_teaser", "foto_segreta_hero"):
            sim_changes[tech] = url
        elif tech == "og_image":
            sim_changes["seo"] = {"og_image": url}
        elif tech == "pellicola":
            ph = dict(sim.get("pellicola_home") or {})
            ph[f"video_{side}"] = url
            if poster:
                ph[f"poster_{side}"] = poster
            sim_changes["pellicola_home"] = ph
        elif tech in ("messaggio_foto", "messaggio_video"):
            msg = dict(sim.get("messaggio_35s") or {})
            msg["foto" if tech == "messaggio_foto" else "video"] = url
            sim_changes["messaggio_35s"] = msg
        else:
            gal = list(sim.get(tech) or [])
            gal.append({"tipo": "image", "url": url, "poster": "", "alt": alt})
            sim_changes[tech] = gal
        return await model_change(ctx, doc, sim_changes, reason or f"Media → {slot}")
    out = await attach_to_model(doc, url=url, slot=tech, side=side, tipo=tipo, alt=alt, poster=poster, pair_index=pidx, principal=ctx.principal, request=ctx.request, reason=reason or f"Media assegnato a {slot}")
    return R(f"Media assegnato a {slot} di {out.get('nome_artistico') or out['slug']}", {"slot": slot, "technical_slot": tech, "side": side, "tipo": tipo, "url": url, "version_id": out.get("version_id"), "etag": out.get("etag")},
             changes=[{"field": f"slot:{slot}", "before": None, "after": url}], version_ids=[out["version_id"]] if out.get("version_id") else [], target=_tgt(out), rollback_ref=out.get("version_id"))


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
                    "pellicola_home{attiva, priorita, ordine, video_pubblico, poster_pubblico, video_segreto, poster_segreto}, ordine, conferma_maggiorenne. (R)=richiede approvazione")


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
        changes["messaggio_35s"] = {k: v for k, v in (src.get("messaggio_35s") or {}).items() if k in ("attivo", "ritardo_secondi", "timer")}
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


@cap("media.upload_url", "media", "Carica un media da URL pubblico (o base64) nella libreria: anti-SSRF, magic bytes, MIME, limiti, varianti. Non assegna a una modella (usa media.assign).", ["media:upload"], rollback=False,
     params={"url": {"type": "string"}, "base64_data": {"type": "string"}, "content_type": {"type": "string"}, "filename": {"type": "string"}, "alt": {"type": "string"}, "seo_name": {"type": "string"}, "model": {"type": "string"}, "slot": {"type": "string", "description": "se indicato assegna subito allo slot (semantico o tecnico)"}},
     natural=["carica questa foto", "aggiungi il video da questo link"])
async def _media_upload_url(ctx: Ctx):
    from v1_media import fetch_url_bytes, store_media, validate_bytes
    import base64
    if ctx.dry:
        return R("Anteprima upload: nessun file scaricato in dry_run", {"dry_run": True, "would_upload": ctx.params.get("url") or "<base64>", "then_assign": ctx.params.get("slot")})
    model = await resolve_model(ctx.params["model"]) if ctx.params.get("model") else None
    if ctx.params.get("url"):
        data, mime = await fetch_url_bytes(ctx.params["url"], ctx.params.get("content_type"))
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
    rec = await store_media(data, mime, original_filename=ctx.params.get("filename") or "", alt=ctx.params.get("alt") or "", seo_name=ctx.params.get("seo_name") or "",
                            model_id=model["id"] if model else None, slot=ctx.params.get("slot") or None, actor=ctx.actor, request_id=request_id_of(ctx.request), source=ctx.source)
    res = R(f"Media caricato: {rec.get('seo_name') or rec.get('original_filename')} ({rec.get('tipo')})", media_summary(rec), changes=[{"field": "file", "before": None, "after": rec["id"]}])
    if model and ctx.params.get("slot"):
        url = (rec.get("variants") or {}).get("web") or rec["url"]
        poster = (rec.get("variants") or {}).get("poster") or ""
        a = await apply_media_to_slot(ctx, model, url, ctx.params["slot"], alt=ctx.params.get("alt") or "", poster=poster, reason=f"Upload + slot {ctx.params['slot']}")
        res["summary"] += f"; assegnato a {ctx.params['slot']} di {model.get('nome_artistico') or model['slug']}"
        res["version_ids"] = a["version_ids"]
        res["rollback_ref"] = a["rollback_ref"]
        res["target"] = a["target"]
        res["data"]["assignment"] = a["data"]
    return res


@cap("media.assign", "media", "Assegna un media della libreria (id/nome/URL) a uno slot della modella. Slot semantici: public_photo_1..3, secret_photo_1..3, public_video_1..2, secret_video_1..2, card, cover, teaser, secret_hero, og_image, filmstrip_public, filmstrip_secret, message_photo, message_video, gallery_public, gallery_secret.",
     ["media:upload", "models:update"], target="model", params={"media": {"type": "string", "required": True}, "slot": {"type": "string", "required": True}, "alt": {"type": "string"}},
     examples=[{"action": "media.assign", "target": "Alessia", "parameters": {"media": "alessia-rossa.jpg", "slot": "secret_photo_2"}}], natural=["metti questa foto come seconda foto segreta di Alessia"])
async def _media_assign(ctx: Ctx):
    f = await find_media(ctx.params.get("media") or "")
    url = (f.get("variants") or {}).get("web") or f["url"]
    poster = (f.get("variants") or {}).get("poster") or ""
    r = await apply_media_to_slot(ctx, ctx.target, url, ctx.params["slot"], alt=ctx.params.get("alt") or f.get("alt") or "", poster=poster, reason=ctx.reason or f"Media {f['id']} → {ctx.params['slot']}")
    if not ctx.dry and f.get("model_id") != ctx.target["id"]:
        await files_col.update_one({"id": f["id"]}, {"$set": {"model_id": ctx.target["id"], "slot": ctx.params["slot"], "updated_at": now_iso()}})
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
        ch["pellicola_home"] = {f"video_{side}": "", f"poster_{side}": ""}
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
    from v1_media import patch_media, MediaPatch, public_file
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
        items.append({"slug": m["slug"], "nome": m.get("nome_artistico"), "attiva": ph.get("attiva", True), "priorita": ph.get("priorita", 0), "ordine": ph.get("ordine", m.get("ordine")), "video_pubblico": bool(ph.get("video_pubblico")), "video_segreto": bool(ph.get("video_segreto"))})
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
    ver = await record_version("config", "global", redact(cur), redact(new), ctx.actor, source=ctx.source, reason=ctx.reason or "Config via ChatGPT", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
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
    ver = await record_version("config", "global", redact(c), redact(new), ctx.actor, source=ctx.source, reason=f"Flag {name}", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id})
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


CATEGORY_FIELDS = {"nome", "slug", "descrizione", "ordine", "attiva", "seo", "hero_text", "icona", "colore"}


async def category_change(ctx: Ctx, doc: dict, changes: dict, reason: str) -> dict:
    changes = {k: v for k, v in changes.items() if k in CATEGORY_FIELDS}
    new = deep_merge(doc, changes)
    fields = diff_fields(doc, new)
    ch = _changes_from(doc, new, fields)
    review = any(f in ("slug", "nome") for f in fields)
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


@cap("categories.create", "categories", "Crea una categoria (nome, slug opzionale, descrizione, ordine, seo).", ["categories:write"], params={"nome": {"type": "string", "required": True}, "slug": {"type": "string"}, "descrizione": {"type": "string"}, "ordine": {"type": "integer"}}, natural=["crea la categoria Estate"])
async def _cat_create(ctx: Ctx):
    nome = (ctx.params.get("nome") or "").strip()
    if not nome:
        raise err(422, "VALIDATION_FAILED", "nome obbligatorio")
    slug = re.sub(r"[^a-z0-9]+", "-", (ctx.params.get("slug") or nome).lower()).strip("-")
    if await categories_col.find_one({"slug": slug, "is_deleted": {"$ne": True}}):
        raise err(409, "CONFLICT", f"Slug categoria '{slug}' già esistente")
    doc = {"id": str(uuid.uuid4()), "nome": nome, "slug": slug, "descrizione": ctx.params.get("descrizione") or "", "ordine": int(ctx.params.get("ordine") or 99), "attiva": True, "seo": {},
           "created_at": now_iso(), "updated_at": now_iso()}
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


@cap("categories.archive", "categories", "Disattiva una categoria (attiva=false; le modelle restano).", ["categories:write"], target="category", risk=REVIEW)
async def _cat_archive(ctx: Ctx):
    return await category_change(ctx, ctx.target, {"attiva": False}, "Categoria disattivata")


@cap("categories.restore", "categories", "Riattiva una categoria.", ["categories:write"], target="category")
async def _cat_restore(ctx: Ctx):
    return await category_change(ctx, ctx.target, {"attiva": True}, "Categoria riattivata")


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
        r = await run_audit(scope="models", model_id=ctx.target["id"])
        return R(f"SEO {ctx.target.get('nome_artistico') or ctx.target['slug']}: score {r.get('health_score')} — {r['counts']}", r, target=_tgt(ctx.target))
    r = await run_audit(scope=ctx.params.get("scope") or "all")
    return R(f"Audit SEO sito: score {r.get('health_score')} — {r['counts']}", r)


@cap("seo.safe_fix", "seo", "Applica SOLO le correzioni SEO SAFE_AUTO_FIX a una modella (dry_run per anteprima). REVIEW/CRITICAL mai toccate.", ["seo:safe_fix"], target="model", natural=["sistema gli errori SEO sicuri di Alessia"])
async def _seo_safe_fix(ctx: Ctx):
    from v1_seo import apply_safe_fixes
    r = await apply_safe_fixes(model_id=ctx.target["id"], actor=ctx.actor, request_id=request_id_of(ctx.request), source=ctx.source, dry_run=ctx.dry)
    vids = [f.get("version_id") for f in r.get("fixes", []) if f.get("version_id")]
    n = len(r.get("would_fix", r.get("fixes", [])))
    return R(f"{'Anteprima: ' if ctx.dry else ''}{n} fix SAFE su {ctx.target.get('nome_artistico') or ctx.target['slug']}" + ("" if ctx.dry else f" (score {r.get('seo_score_before')} → {r.get('seo_score_after')})"), r, version_ids=vids, target=_tgt(ctx.target))


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
            r = await apply_safe_fixes(model_id=m["id"], actor=ctx.actor, request_id=request_id_of(ctx.request), source=ctx.source, dry_run=ctx.dry)
            n = len(r.get("would_fix", r.get("fixes", [])))
            vids += [f.get("version_id") for f in r.get("fixes", []) if f.get("version_id")]
            results.append({"slug": m["slug"], "ok": True, "fixes": n, "score_before": r.get("seo_score_before"), "score_after": r.get("seo_score_after")})
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
    return R(f"Redirect {fp} → {tp} creato", r or {}, changes=[{"field": "redirect", "before": None, "after": f"{fp} -> {tp}"}])


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
    await redirects_col.update_one({"id": r["id"]}, {"$set": {"active": False, "deactivated_at": now_iso(), "deactivated_by": ctx.actor}})
    return R(f"Redirect {fp} disattivato", {"id": r["id"]}, changes=[{"field": "active", "before": True, "after": False}])


@cap("seo.sitemap_status", "seo", "Stato sitemap: URL inclusi, esclusi (noindex), errori.", ["seo:read"], read_only=True, natural=["com'è la sitemap"])
async def _sitemap(ctx: Ctx):
    from v1_seo import sitemap_entries
    entries = await sitemap_entries()
    return R(f"Sitemap: {len(entries)} URL", {"count": len(entries), "urls": [e.get("loc") if isinstance(e, dict) else e for e in entries][:200]})


@cap("seo.internal_links", "seo", "Suggerimenti di link interni per una modella.", ["seo:read"], target="model", read_only=True)
async def _internal_links(ctx: Ctx):
    from v1_seo import internal_link_suggestions
    r = await internal_link_suggestions(ctx.target["id"]) if ctx.target else []
    return R(f"{len(r)} suggerimenti di link interni", {"items": r}, target=_tgt(ctx.target) if ctx.target else None)


@cap("seo.opportunities", "seo", "Opportunità SEO del sito (contenuti mancanti, pagine deboli).", ["seo:read"], read_only=True, natural=["opportunità SEO"])
async def _opps(ctx: Ctx):
    from v1_seo import opportunities
    r = await opportunities()
    return R(f"{len(r) if isinstance(r, list) else 'n/d'} opportunità", {"items": r})


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


@cap("landing.create", "landing", "Crea una landing editoriale italiana in bozza (model/models, h1, title, intro, cta_text, meta_description, keywords, faq). Mai geoblocking.", ["landing:create"], params={"fields": {"type": "object", "required": True}}, natural=["crea una landing italiana per Alessia"])
async def _landing_create(ctx: Ctx):
    from v1_landings import create_landing
    f = dict(ctx.params.get("fields") or ctx.params)
    refs = f.pop("models", None) or ([f.pop("model")] if f.get("model") else [])
    models = [await resolve_model(r) for r in refs]
    data = {"titolo": f.get("title") or f.get("titolo") or f.get("h1") or "", "h1": f.get("h1") or f.get("title") or "", "sottotitolo": f.get("subtitle") or f.get("sottotitolo") or "", "hero_text": f.get("hero_text") or "",
            "intro": f.get("intro") or "", "cta_text": f.get("cta_text") or "ENTRA NEL LATO SEGRETO", "cta_url": f.get("cta_url") or "", "meta_description": f.get("meta_description") or "", "keywords": f.get("keywords") or [],
            "slug": f.get("slug") or "", "model_ids": [m["id"] for m in models], "faq": f.get("faq") or [], "noindex": bool(f.get("noindex", False)), "targeting": {"country": "IT", "language": "it", "geoblocking": False, "editorial_only": True}}
    if ctx.dry:
        from v1_landings import validate_landing
        return R(f"Anteprima landing '{data['h1']}'", {"dry_run": True, "proposed": data, "validation": validate_landing(data)})
    out = await create_landing(data, ctx.principal, ctx.request)
    ver = await versions_col.find_one({"entity": "landing", "entity_id": out["id"]}, {"_id": 0, "id": 1}, sort=[("timestamp", -1)])
    return R(f"Landing '{out.get('h1')}' creata in bozza ({out['slug']})", out, version_ids=[ver["id"]] if ver else [], target=_tgt(out, "landing"), rollback_ref=ver["id"] if ver else None)


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
    return R(("Pubblicabile" if v.get("ok") else f"Non pubblicabile: {len(v.get('errors', []))} errori") + f" (score {v.get('score')})", v, target=_tgt(ctx.target, "landing"))


@cap("landing.publish", "landing", "Pubblica una landing (validator + scope landing:publish, altrimenti approvazione). Le rotte pubbliche restano OFF finché il flag non è attivo.", ["landing:update"], target="landing", risk=REVIEW)
async def _landing_publish(ctx: Ctx):
    from v1_landings import validate_landing_full, set_landing_state
    v = await validate_landing_full(ctx.target)
    if not v.get("ok"):
        return R("Landing non pubblicabile", {"validation": v}, warnings=[e if isinstance(e, str) else e.get("message", "") for e in v.get("errors", [])], target=_tgt(ctx.target, "landing"))
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


SAFE_JOBS = {"health_check", "seo_scan", "broken_link_scan", "media_verify", "sitemap_verify", "analytics_sync", "anomaly_detection", "backup", "daily_digest"}


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
    items = await backups_col.find({}, {"_id": 0, "data": 0, "snapshot": 0}).sort("created_at", -1).to_list(20)
    return R(f"{len(items)} backup, ultimo {items[0]['created_at'][:16] if items else 'mai'}", {"items": items})


@cap("backup.create", "backup", "Crea un backup completo ora.", ["backup:create"], rollback=False, natural=["fai backup"])
async def _backup_create(ctx: Ctx):
    from v1_config import create_backup
    if ctx.dry:
        return R("Anteprima: verrebbe creato un backup completo", {"dry_run": True})
    b = await create_backup(actor=ctx.actor, reason=ctx.reason or "ChatGPT")
    return R(f"Backup creato ({b.get('id')})", {k: v for k, v in b.items() if k not in ("data", "snapshot")})


@cap("backup.verify", "backup", "Verifica un backup: collection incluse e conteggi vs stato attuale.", ["backup:read"], read_only=True, params={"backup_id": {"type": "string"}})
async def _backup_verify(ctx: Ctx):
    q = {"id": ctx.params["backup_id"]} if ctx.params.get("backup_id") else {}
    b = await backups_col.find_one(q, {"_id": 0}, sort=[("created_at", -1)])
    if not b:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Backup non trovato"})
    snap = b.get("snapshot") or b.get("data") or {}
    from database import db
    comp = {}
    for c, docs in snap.items():
        try:
            comp[c] = {"in_backup": len(docs) if isinstance(docs, list) else None, "now": await db[c].count_documents({})}
        except Exception:
            comp[c] = {"in_backup": None, "now": None}
    return R(f"Backup {b['id']} del {b['created_at'][:16]}: {len(comp)} collection", {"id": b["id"], "created_at": b["created_at"], "collections": comp})


@cap("backup.restore_plan", "backup", "Piano di ripristino (dry-run): cosa cambierebbe. Il ripristino reale è CRITICAL (solo admin umano).", ["backup:read"], read_only=True, params={"backup_id": {"type": "string", "required": True}, "collections": {"type": "array", "items": {"type": "string"}}})
async def _backup_plan(ctx: Ctx):
    b = await backups_col.find_one({"id": ctx.params.get("backup_id")}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Backup non trovato"})
    snap = b.get("snapshot") or b.get("data") or {}
    from database import db
    cols = ctx.params.get("collections") or list(snap.keys())
    plan = []
    for c in cols:
        docs = snap.get(c) or []
        plan.append({"collection": c, "in_backup": len(docs), "now": await db[c].count_documents({}), "mode": "replace"})
    return R("Piano di ripristino (nessuna modifica). Esecuzione reale: CRITICAL, solo amministratore umano.", {"backup_id": b["id"], "plan": plan, "critical": True})


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


async def _versions_for_session(session_id: str) -> List[dict]:
    acts = await ai_actions_col.find({"session_id": session_id, "ok": True}, {"_id": 0, "version_ids": 1, "timestamp": 1}).sort("timestamp", -1).to_list(500)
    vids = []
    for a in acts:
        for v in a.get("version_ids") or []:
            if v and v not in vids:
                vids.append(v)
    vers = []
    for vid in vids:
        v = await versions_col.find_one({"id": vid}, {"_id": 0})
        if v:
            vers.append(v)
    vers.sort(key=lambda x: x.get("timestamp", ""), reverse=True)   # newest first -> undo in reverse order
    return vers


@cap("rollback.session", "rollback", "Annulla TUTTE le modifiche di una sessione (session_id) in ordine inverso; ogni annullamento crea una nuova versione. Creazioni → eliminazione logica.", ["rollback:execute"],
     params={"session_id": {"type": "string", "required": True}}, natural=["annulla tutto quello che hai appena fatto"])
async def _rb_session(ctx: Ctx):
    sid = ctx.params.get("session_id") or ctx.session_id
    vers = await _versions_for_session(sid)
    if not vers:
        return R(f"Nessuna modifica trovata per la sessione {sid}", {"session_id": sid, "versions": 0})
    plan = [{"version_id": v["id"], "entity": v["entity"], "entity_id": v["entity_id"], "changed_fields": v.get("changed_fields"), "created": v.get("before") is None, "timestamp": v.get("timestamp")} for v in vers]
    if ctx.dry:
        return R(f"Anteprima: verrebbero annullate {len(vers)} modifiche della sessione {sid}", {"dry_run": True, "plan": plan})
    done, new_vids, errors = [], [], []
    for v in vers:
        try:
            if v.get("before") is None:  # creation -> soft delete (never destructive)
                from v1_versioning import ENTITY_COLLECTIONS
                col = ENTITY_COLLECTIONS.get(v["entity"])
                cur = await col.find_one({"id": v["entity_id"]}, {"_id": 0}) if col is not None else None
                if cur and not cur.get("is_deleted"):
                    new = {**cur, "is_deleted": True, "deleted_at": now_iso(), "updated_at": now_iso()}
                    await col.replace_one({"id": cur["id"]}, new)
                    nv = await record_version(v["entity"], cur["id"], cur, new, ctx.actor, source="rollback", reason=f"Rollback sessione {sid}: creazione annullata", request_id=request_id_of(ctx.request), meta={"session_id": ctx.session_id, "rollback_of": v["id"]})
                    new_vids.append(nv["id"])
                done.append({"version_id": v["id"], "action": "soft_deleted"})
            else:
                r = await rollback_version(v["id"], ctx.actor, request_id_of(ctx.request), f"Rollback sessione {sid}")
                new_vids.append(r.get("new_version_id") or r.get("version_id"))
                done.append({"version_id": v["id"], "action": "restored"})
        except Exception as e:
            errors.append({"version_id": v["id"], "error": str(getattr(e, 'detail', e))[:160]})
    return R(f"Sessione {sid}: {len(done)} modifiche annullate, {len(errors)} errori (storia conservata)", {"session_id": sid, "done": done, "errors": errors, "plan": plan}, version_ids=[x for x in new_vids if x], warnings=[e["error"] for e in errors])


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
     ["models:create", "models:update", "media:upload", "seo:safe_fix"], rollback=True,
     params={"nome": {"type": "string", "required": True}, "fields": {"type": "object"}, "media": {"type": "array", "items": {"type": "object"}, "description": "[{media|url, slot, alt}]"}, "seo_safe_fix": {"type": "boolean", "default": True}},
     examples=[{"action": "models.prepare_complete", "parameters": {"nome": "Giulia Rossi", "fields": {"frase": "Il lato che non mostro a tutti.", "categorie": ["more"], "onlyfans_url": "https://onlyfans.com/giulia_rossi"}, "media": [{"media": "giulia-1.jpg", "slot": "public_photo_1"}]}}],
     natural=["prepara Giulia completamente ma non pubblicarla", "crea una nuova modella con queste foto e preparala tutta"])
async def _prepare_complete(ctx: Ctx):
    steps = []
    nome = (ctx.params.get("nome") or "").strip()
    if not nome:
        raise err(422, "VALIDATION_FAILED", "nome obbligatorio")
    fields = {k: v for k, v in (ctx.params.get("fields") or {}).items() if k in ALLOWED_FIELDS}
    media = ctx.params.get("media") or []
    if ctx.dry:
        return R(f"Anteprima workflow '{nome}': bozza + {len(fields)} campi + {len(media)} media + SEO safe + validate (nessuna pubblicazione)",
                 {"dry_run": True, "plan": ["models.create", f"models.update ({len(fields)} campi)"] + [f"media.assign {m.get('slot')}" for m in media] + ["seo.safe_fix", "models.validate"]})
    vids: List[str] = []
    existing = None
    try:
        existing = await resolve_model(nome)
    except HTTPException:
        existing = None
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
    if fields:
        sub = Ctx(ctx.principal, ctx.request, {}, dry=False, reason="Workflow: campi", session_id=ctx.session_id, approved=True)
        r = await model_change(sub, doc, fields, "Workflow prepare_complete: campi")
        vids += r["version_ids"]
        steps.append({"step": "models.update", "ok": True, "fields": list(fields), "version_id": r.get("rollback_ref")})
        doc = await models_col.find_one({"id": doc["id"]}, {"_id": 0})
    for m in media:
        try:
            sub = Ctx(ctx.principal, ctx.request, {}, dry=False, reason="Workflow: media", session_id=ctx.session_id, approved=True)
            if m.get("url") and not m.get("media"):
                from v1_media import fetch_url_bytes, store_media
                data, mime = await fetch_url_bytes(m["url"], None)
                rec = await store_media(data, mime, original_filename=m.get("filename") or "", alt=m.get("alt") or "", seo_name=m.get("seo_name") or "", model_id=doc["id"], slot=m.get("slot"), actor=ctx.actor, request_id=request_id_of(ctx.request), source=ctx.source)
                url = (rec.get("variants") or {}).get("web") or rec["url"]
                poster = (rec.get("variants") or {}).get("poster") or ""
            else:
                f = await find_media(m.get("media") or "")
                url = (f.get("variants") or {}).get("web") or f["url"]
                poster = (f.get("variants") or {}).get("poster") or ""
            r = await apply_media_to_slot(sub, doc, url, m.get("slot") or "public_photo_1", alt=m.get("alt") or "", poster=poster, reason="Workflow: media")
            vids += r["version_ids"]
            steps.append({"step": "media.assign", "ok": True, "slot": m.get("slot"), "version_id": r.get("rollback_ref")})
            doc = await models_col.find_one({"id": doc["id"]}, {"_id": 0})
        except Exception as e:
            steps.append({"step": "media.assign", "ok": False, "slot": m.get("slot"), "error": str(getattr(e, "detail", e))[:200]})
    if ctx.params.get("seo_safe_fix", True):
        from v1_seo import apply_safe_fixes
        r = await apply_safe_fixes(model_id=doc["id"], actor=ctx.actor, request_id=request_id_of(ctx.request), source=ctx.source, dry_run=False)
        vids += [f.get("version_id") for f in r.get("fixes", []) if f.get("version_id")]
        steps.append({"step": "seo.safe_fix", "ok": True, "fixes": len(r.get("fixes", [])), "score_before": r.get("seo_score_before"), "score_after": r.get("seo_score_after")})
        doc = await models_col.find_one({"id": doc["id"]}, {"_id": 0})
    v = validate_model(doc)
    steps.append({"step": "models.validate", "ok": True, "ready": v["ready"], "missing": [e["field"] for e in v["errors"]]})
    return R(f"'{doc.get('nome_artistico') or nome}' preparata (slug {doc['slug']}, stato {workflow_status(doc)}, NON pubblicata): {len([s for s in steps if s.get('ok')])} passi ok, {len(vids)} versioni. " + ("Pronta alla pubblicazione." if v["ready"] else f"Mancano: {', '.join(e['field'] for e in v['errors'])}"),
             {"id": doc["id"], "slug": doc["slug"], "workflow_status": workflow_status(doc), "steps": steps, "readiness": v, "session_id": ctx.session_id, "published": False},
             version_ids=[x for x in vids if x], target=_tgt(doc), next_steps=["models.publish (separato, dopo la tua approvazione)", f"rollback.session {{session_id:'{ctx.session_id}'}} per annullare tutto"])


# =====================================================================================================================
# DISPATCHER
# =====================================================================================================================
class ExecuteBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str
    target: Optional[str] = None
    parameters: Dict[str, Any] = {}
    dry_run: bool = False
    reason: Optional[str] = ""
    session_id: Optional[str] = None
    expected_updated_at: Optional[str] = None
    run_async: bool = False


TARGET_RESOLVERS = {
    "model": lambda ref: resolve_model(ref),
    "category": lambda ref: resolve_category(ref),
    "alert": lambda ref: resolve_alert(ref),
    "media": lambda ref: find_media(ref),
}


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
    allow, deny = principal.get("capability_allow") or [], principal.get("capability_deny") or []
    if any(fnmatch.fnmatch(cap_id, d) for d in deny):
        return "denied"
    if allow and not any(fnmatch.fnmatch(cap_id, a) for a in allow):
        return "not_allowed"
    return None


async def disabled_capabilities() -> List[str]:
    c = await config_col.find_one({"id": "global"}, {"_id": 0, "ai": 1}) or {}
    return list(((c.get("ai") or {}).get("capabilities_disabled")) or [])


def _needs_approval(capability: Capability, result: dict) -> bool:
    return bool(result.get("needs_approval"))


async def run_capability(principal: dict, request: Request, body: ExecuteBody, *, force_dry: bool = False, approved: bool = False) -> dict:
    """The whole chain. Returns the AI envelope. Raises HTTPException with machine-readable codes."""
    from v1_ai import envelope, log_action
    t0 = time.time()
    capability = REGISTRY.get(body.action)
    if not capability:
        sugg = [k for k in REGISTRY if body.action.split(".")[0] in k][:10]
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_CAPABILITY", "message": f"Capability '{body.action}' inesistente", "suggestions": sugg, "hint": "GET /api/v1/ai/capabilities"})
    is_machine = principal.get("type") == "api_key"
    cfg = await ai_config()
    if is_machine and not cfg["enabled"]:
        raise err(503, "AI_API_DISABLED", "ChatGPT API disattivata (kill switch)")
    if body.action in await disabled_capabilities():
        raise err(403, "CAPABILITY_DISABLED", f"Capability '{body.action}' disattivata dall'amministratore")
    why = key_allows(principal, body.action)
    if why:
        raise err(403, "CAPABILITY_NOT_ALLOWED", f"Capability '{body.action}' non consentita per questa chiave ({why})")
    dry = bool(force_dry or body.dry_run) and not capability.read_only
    write = not capability.read_only
    if is_machine and capability.risk == CRITICAL:
        raise err(403, "CRITICAL_ACTION_BLOCKED", "Operazione critica: solo amministratore umano")
    if is_machine and write and not cfg["write_enabled"] and not dry:
        raise err(403, "READ_ONLY_MODE", "Modalità READ_ONLY: usa dry_run=true (anteprima) o chiedi all'amministratore di attivare FULL")
    if capability.batch and not cfg["batch_enabled"] and not dry:
        raise err(403, "BATCH_DISABLED", "Operazioni batch disattivate")
    if is_machine:
        rl = await rate_limit_shared(f"ai:{principal['id']}", min(cfg["rate_limit_per_min"], principal.get("rate_limit", cfg["rate_limit_per_min"])))
        request.state.rate = rl
    missing = missing_scopes_for(principal, ("ai:execute", *capability.scopes), dry and write)
    if missing:
        raise err(403, "INSUFFICIENT_SCOPE", "Permessi insufficienti", missing_scopes=missing, capability=body.action, hint="Con dry_run=true bastano gli scope di lettura")
    if dry and write and not capability.dry_run:
        raise err(422, "VALIDATION_FAILED", f"'{body.action}' non supporta dry_run")
    session_id = body.session_id or request.headers.get("X-Session-ID") or f"ses_{uuid.uuid4().hex[:12]}"
    request.state.session_id = session_id
    request.state.ai_write = write and not dry
    request.state.ai_dry_run = dry
    target_doc = await _resolve_target(capability.target, body.target, body.parameters or {})
    if capability.target != "none" and target_doc is None and capability.id not in ("seo.audit", "seo.issues", "seo.internal_links", "models.undelete"):
        raise err(422, "VALIDATION_FAILED", f"'{body.action}' richiede un target ({capability.target})")
    ctx = Ctx(principal=principal, request=request, params=body.parameters or {}, dry=dry, reason=body.reason or "", session_id=session_id, approved=approved,
              expected_updated_at=body.expected_updated_at, target_ref=body.target, target=target_doc)
    try:
        result = await capability.handler(ctx)
    except HTTPException as e:
        await log_action(principal, request, body.action, {"target": body.target, "parameters": body.parameters, "dry_run": dry, "session_id": session_id}, f"Errore: {e.detail if isinstance(e.detail, str) else (e.detail or {}).get('code')}", ok=False,
                         target={"ref": body.target}, started=t0, reason=body.reason or "")
        raise
    approval = None
    if _needs_approval(capability, result) and not dry:
        na = result["needs_approval"]
        payload = {"action": body.action, "target": body.target, "parameters": body.parameters, "reason": body.reason, "session_id": session_id, "expected_updated_at": na.get("expected_updated_at")}
        approval = await create_approval("CAPABILITY", actor_of(principal), result.get("target") or {"ref": body.target}, payload, na.get("before"), na.get("after"), body.reason or f"{body.action} ({', '.join(na.get('fields') or [])})", request_id_of(request))
        approval["confirm_with"] = "POST /api/v1/ai/approvals/confirm {token} oppure POST /api/v1/ai/approvals/{id}/approve"
        approval["capability"] = body.action
        result["next_steps"] = ["Mostra all'utente prima/dopo e chiedi conferma", "Conferma: approvals.confirm {token}"] + result.get("next_steps", [])
    version_ids = [v for v in result.get("version_ids") or [] if v]
    await log_action(principal, request, body.action, {"target": body.target, "parameters": body.parameters, "dry_run": dry, "session_id": session_id, "approved": approved},
                     result["summary"], ok=True, target=result.get("target") or ({"ref": body.target} if body.target else None), changes=result.get("changes"), version_ids=version_ids, started=t0,
                     rollback_ref=result.get("rollback_ref") or (version_ids[0] if version_ids else None), before=result.get("before"), after=result.get("after"), reason=body.reason or "")
    if version_ids and not dry:
        bump("mutations")
    data = dict(result.get("data") or {})
    data.update({"capability": body.action, "capability_version": capability.version, "risk": capability.risk, "dry_run": dry, "session_id": session_id,
                 "rollback": {"available": bool(version_ids), "version_ids": version_ids, "undo": f"execute rollback.session {{session_id:'{session_id}'}}" if version_ids else None}})
    if result.get("before") is not None and "before" not in data:
        data["before"] = result["before"]
    if result.get("after") is not None and "after" not in data:
        data["after"] = result["after"]
    if result.get("target"):
        data["target"] = result["target"]
    return envelope(body.action, request, result["summary"], data, result.get("warnings"), result.get("next_steps"), ok=True, changes=result.get("changes"), approval=approval)


@caps_router.post("/execute", operation_id="executeCapability", summary="Esegue una capability strutturata (dispatcher deterministico)")
async def execute(body: ExecuteBody, request: Request, principal: dict = Depends(resolve_principal)):
    if body.run_async and REGISTRY.get(body.action) and REGISTRY[body.action].batch and not body.dry_run:
        return await _enqueue(principal, request, body)
    return await run_capability(principal, request, body)


@caps_router.post("/preview", operation_id="previewCapability", summary="Anteprima (dry_run forzato): before/after/diff/warnings, nessuna modifica")
async def preview(body: ExecuteBody, request: Request, principal: dict = Depends(resolve_principal)):
    return await run_capability(principal, request, body, force_dry=True)


# ---------------- async jobs (base) ----------------
from database import db as _db
ai_jobs_col = _db["ai_jobs"]


async def _enqueue(principal: dict, request: Request, body: ExecuteBody) -> dict:
    from v1_ai import envelope
    job = {"id": f"aij_{uuid.uuid4().hex[:12]}", "status": "queued", "action": body.action, "target": body.target, "parameters": redact(body.parameters), "actor": actor_of(principal),
           "created_at": now_iso(), "started_at": None, "finished_at": None, "progress": 0, "result": None, "error": None, "request_id": request_id_of(request), "session_id": body.session_id}
    await ai_jobs_col.insert_one(dict(job))

    async def _run():
        await ai_jobs_col.update_one({"id": job["id"]}, {"$set": {"status": "running", "started_at": now_iso(), "progress": 10}})
        try:
            res = await run_capability(principal, request, body)
            await ai_jobs_col.update_one({"id": job["id"]}, {"$set": {"status": "done", "finished_at": now_iso(), "progress": 100, "result": redact({k: v for k, v in res.items() if k != "request_id"})}})
        except Exception as e:
            await ai_jobs_col.update_one({"id": job["id"]}, {"$set": {"status": "failed", "finished_at": now_iso(), "error": str(getattr(e, "detail", e))[:500]}})
    asyncio.create_task(_run())
    return envelope(body.action, request, f"Operazione '{body.action}' accodata (job {job['id']})", {"job_id": job["id"], "status": "queued", "poll": f"GET /api/v1/ai/jobs/{job['id']}"}, next_steps=[f"Controlla GET /api/v1/ai/jobs/{job['id']}"])


@caps_router.get("/jobs/{job_id}", operation_id="getJob", summary="Stato di un job asincrono AI")
async def get_job(job_id: str, request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope
    j = await ai_jobs_col.find_one({"id": job_id}, {"_id": 0})
    if not j:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Job non trovato"})
    return envelope("jobs.get", request, f"Job {job_id}: {j['status']} ({j.get('progress', 0)}%)", j)


# ---------------- capability catalog ----------------
@caps_router.get("/capabilities/{capability_id}", operation_id="getCapability", summary="Dettaglio di una capability (parametri, scope, rischio, esempi)")
async def get_capability(capability_id: str, request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope
    c = REGISTRY.get(capability_id)
    if not c:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_CAPABILITY", "message": f"Capability '{capability_id}' inesistente", "suggestions": [k for k in REGISTRY if capability_id.split('.')[0] in k][:10]})
    cfg = await ai_config()
    pub = c.public()
    missing = missing_scopes_for(principal, ("ai:execute", *c.scopes), False)
    pub["access"] = "full" if not missing else ("preview_only" if not missing_scopes_for(principal, ("ai:execute", *c.scopes), True) else "none")
    pub["disabled"] = capability_id in await disabled_capabilities()
    pub["key_restriction"] = key_allows(principal, capability_id)
    pub["mode"] = cfg["mode"]
    return envelope("capabilities.get", request, f"{c.id}: {c.description[:120]}", pub)


def catalog_for(principal: dict, disabled: List[str], mode: str) -> dict:
    items = []
    for c in REGISTRY.values():
        missing = missing_scopes_for(principal, ("ai:execute", *c.scopes), False)
        access = "full" if not missing else ("preview_only" if (not c.read_only and c.dry_run and not missing_scopes_for(principal, ("ai:execute", *c.scopes), True)) else "none")
        if access == "none":
            continue
        if c.id in disabled or key_allows(principal, c.id):
            continue
        d = c.public()
        d["access"] = access
        if mode == "READ_ONLY" and not c.read_only:
            d["read_only_note"] = "Modalità READ_ONLY: solo dry_run=true"
        items.append(d)
    cats: Dict[str, int] = {}
    for i in items:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
    return {"capabilities": items, "count": len(items), "by_category": cats, "risk_levels": {SAFE: "eseguita subito", REVIEW: "anteprima + token di approvazione", CRITICAL: "mai via API key"}}


# ---------------- approvals: approve / reject by id ----------------
class ApproveBody(BaseModel):
    token: Optional[str] = None
    reason: Optional[str] = ""


async def execute_approved_capability(doc: dict, principal: dict, request: Request) -> dict:
    p = doc.get("payload") or {}
    body = ExecuteBody(action=p["action"], target=p.get("target"), parameters=p.get("parameters") or {}, dry_run=False, reason=p.get("reason") or "", session_id=p.get("session_id"), expected_updated_at=p.get("expected_updated_at"))
    return await run_capability(principal, request, body, approved=True)


@caps_router.post("/approvals/{approval_id}/approve", operation_id="approveApproval", summary="Approva ed esegue una proposta in attesa (token per API key; admin JWT senza token)")
async def approve_by_id(approval_id: str, body: ApproveBody, request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope, ai_confirm, AIConfirm
    doc = await approvals_col.find_one({"id": approval_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Approvazione non trovata"})
    if principal.get("type") == "api_key":
        if not body.token:
            raise err(400, "APPROVAL_INVALID", "Le API key devono fornire il token di approvazione")
        return await ai_confirm(AIConfirm(token=body.token, reason=body.reason or ""), request, principal)
    # human admin (JWT): approve without token
    if doc.get("status") != "pending":
        raise err(409, "APPROVAL_INVALID", f"Approvazione in stato {doc.get('status')}")
    if doc.get("expires_at", "") < now_iso():
        await approvals_col.update_one({"id": doc["id"]}, {"$set": {"status": "expired"}})
        raise err(410, "APPROVAL_EXPIRED", "Approvazione scaduta")
    await approvals_col.update_one({"id": doc["id"]}, {"$set": {"status": "used", "used_at": now_iso(), "approved_by": actor_of(principal)}})
    bump("approvals_confirmed")
    if doc.get("type") == "CAPABILITY":
        res = await execute_approved_capability(doc, principal, request)
        res["data"]["approval_id"] = approval_id
        return res
    raise err(422, "VALIDATION_FAILED", f"Tipo approvazione {doc.get('type')}: usa /approvals/confirm con il token")


@caps_router.post("/approvals/{approval_id}/reject", operation_id="rejectApproval", summary="Rifiuta una proposta in attesa (nessuna modifica)")
async def reject_by_id(approval_id: str, body: ApproveBody, request: Request, principal: dict = Depends(resolve_principal)):
    from v1_ai import envelope, log_action
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


# ---------------- admin: capability governance (JWT) ----------------
class CapToggle(BaseModel):
    capability_id: str
    disabled: bool


@caps_router.get("/capabilities-admin", operation_id="adminCapabilities", include_in_schema=False)
async def admin_capabilities(request: Request, principal: dict = Depends(resolve_principal)):
    if principal.get("type") == "api_key":
        raise err(403, "CRITICAL_ACTION_BLOCKED", "Solo amministratori")
    disabled = await disabled_capabilities()
    items = [{**c.public(), "disabled": c.id in disabled} for c in REGISTRY.values()]
    use = {}
    async for a in ai_actions_col.aggregate([{"$match": {"action": {"$in": list(REGISTRY.keys())}}}, {"$group": {"_id": "$action", "n": {"$sum": 1}, "err": {"$sum": {"$cond": ["$ok", 0, 1]}}}}]):
        use[a["_id"]] = {"count": a["n"], "errors": a["err"]}
    for i in items:
        i["usage"] = use.get(i["id"], {"count": 0, "errors": 0})
    return {"items": items, "total": len(items), "disabled": len(disabled), "enabled": len(items) - len(disabled),
            "by_risk": {r: len([i for i in items if i["risk"] == r]) for r in (SAFE, REVIEW, CRITICAL)}, "by_category": {c: len([i for i in items if i["category"] == c]) for c in sorted({i["category"] for i in items})}}


@caps_router.post("/capabilities-admin/toggle", operation_id="adminToggleCapability", include_in_schema=False)
async def admin_toggle(body: CapToggle, request: Request, principal: dict = Depends(resolve_principal)):
    if principal.get("type") == "api_key":
        raise err(403, "CRITICAL_ACTION_BLOCKED", "Solo amministratori")
    if body.capability_id not in REGISTRY:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_CAPABILITY", "message": "Capability inesistente"})
    disabled = set(await disabled_capabilities())
    (disabled.add if body.disabled else disabled.discard)(body.capability_id)
    await config_col.update_one({"id": "global"}, {"$set": {"ai.capabilities_disabled": sorted(disabled), "updated_at": now_iso()}}, upsert=True)
    await audit_log(actor_of(principal), "ai.capability_toggle", "config", "global", {"capability": body.capability_id, "disabled": body.disabled}, request_id_of(request), "admin")
    return {"capability_id": body.capability_id, "disabled": body.disabled, "disabled_list": sorted(disabled)}
