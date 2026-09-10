"""SUPER API v1 - CONFIGURATION CENTER, FEATURE FLAGS, WEBHOOKS, BACKUP/RESTORE, API KEYS, USERS.
"""
import os
import io
import json
import gzip
import uuid
import asyncio
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
import requests as _requests

from database import (
    config_col, webhooks_col, webhook_deliveries_col, backups_col, api_keys_col, admins_col,
    models_col, categories_col, articles_col, settings_col, landings_col, experiments_col, redirects_col, files_col,
    seo_issues_col, versions_col, events_col, now_iso, serialize_doc,
)
from auth import hash_password
from storage import put_object, get_object, APP_NAME
from v1_security import (
    require, actor_of, request_id_of, generate_api_key, hash_key, ROLES, ROLE_SCOPES, ALL_SCOPES, scopes_for_role,
    normalize_role, sign_payload, ROLE_OPTIONAL_SCOPES,
)
from v1_versioning import record_version, audit_log

logger = logging.getLogger("lato-segreto.config")

config_router = APIRouter(prefix="/api/v1/config", tags=["Config & Flags"])
webhooks_router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])
backup_router = APIRouter(prefix="/api/v1/backup", tags=["Backup & Restore"])
auth_router = APIRouter(prefix="/api/v1/auth", tags=["Auth, API Keys & Users"])

DEFAULT_CONFIG = {
    "id": "global",
    "site": {"base_url": "", "brand": "LATO SEGRETO", "default_locale": "it-IT", "target_country": "IT",
             "future_domain": "latosegreto.it", "domain_migration_ready": True, "domain_migration_active": False},
    "seo_autopilot": {"enabled": True, "auto_apply_safe": True, "scan_interval_min": 60, "max_fixes_per_run": 200, "notify_on_fix": True},
    "self_healing": {"enabled": True, "auto_fix": True, "rollback_on_regression": True, "check_interval_min": 10},
    "tracking": {"store_ip": False, "geo_headers": True, "language_fallback": True, "geo_provider": "headers", "canonical_events": True},
    "italy": {"priority": True, "geoblocking": False, "default_country": "IT"},
    "landings": {"public_routes": False},
    "experiments": {"enabled": True, "auto_winner": False},
    "alerts": {"email": "", "webhook_url": "", "min_severity": "warning"},
    "backups": {"enabled": True, "retention": 14, "interval_hours": 24, "include_events": False},
    "jobs": {"enabled": True},
    "ai": {"enabled": True, "default_source": "chatgpt", "require_reason": False, "max_batch": 50,
           "policy": {"review_fields": ["slug", "nome", "nome_artistico", "onlyfans_url", "bio", "bio_segreta", "frase", "seo.title", "seo.meta_description", "seo.canonical", "seo.robots", "seo.indexable"],
                      "approval_ttl_min": 30, "max_batch": 50, "rate_limit_per_min": 120}},
    "rendering": {"ssr": False, "prerender": False, "note": "Predisposto: da attivare nella fase dominio/SEO avanzata"},
    "analytics_production": {"ga4_measurement_id": "", "gsc_verified": False, "note": "Da configurare nella fase produzione"},
    "flags": {
        "super_api": True, "seo_autopilot": True, "self_healing": True, "italy_engine": True, "landing_engine": True,
        "ab_testing": True, "ai_api": True, "webhooks": True, "public_landing_routes": False, "domain_it_migration": False,
        "ai_api_enabled": True, "ai_write_enabled": False, "ai_batch_enabled": True, "ai_approval_flow_enabled": True,  # READ_ONLY by default: FULL is a human decision (Phase 11)
        "ssr_prerender": False, "search_console_sync": False, "ga4_production": False,
    },
    "created_at": None, "updated_at": None,
}


async def get_config() -> dict:
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0})
    if not cfg:
        cfg = {**DEFAULT_CONFIG, "created_at": now_iso(), "updated_at": now_iso()}
        await config_col.insert_one(dict(cfg))
        return serialize_doc(cfg)
    # backfill new keys non-destructively
    merged = _deep_default(cfg, DEFAULT_CONFIG)
    if merged != cfg:
        await config_col.replace_one({"id": "global"}, merged)
    return serialize_doc(merged)


def _deep_default(doc, defaults):
    if isinstance(defaults, dict):
        out = dict(doc) if isinstance(doc, dict) else {}
        for k, v in defaults.items():
            out[k] = _deep_default(out.get(k), v) if k in out else v
        return out
    return doc if doc is not None else defaults


async def flag(name: str) -> bool:
    cfg = await get_config()
    return bool((cfg.get("flags") or {}).get(name, False))


# ---------------- EVENTS -> WEBHOOKS ----------------
async def _deliver(hook: dict, event: str, payload: dict, attempt: int = 1):
    body = json.dumps({"event": event, "payload": payload, "timestamp": now_iso(), "delivery_id": str(uuid.uuid4())}, default=str).encode()
    ts = now_iso()
    headers = {"Content-Type": "application/json", "X-LS-Event": event, "X-LS-Timestamp": ts, "X-LS-Signature": sign_payload(hook["secret"], ts, body), "User-Agent": "LatoSegreto-Webhooks/1.0"}
    status, err = None, None
    try:
        r = await asyncio.get_event_loop().run_in_executor(None, lambda: _requests.post(hook["url"], data=body, headers=headers, timeout=15))
        status = r.status_code
        ok = 200 <= r.status_code < 300
    except Exception as e:
        ok, err = False, str(e)
    await webhook_deliveries_col.insert_one({"id": str(uuid.uuid4()), "webhook_id": hook["id"], "event": event, "status_code": status, "ok": ok, "error": err, "attempt": attempt, "created_at": now_iso()})
    if not ok and attempt < 3:
        await asyncio.sleep(2 ** attempt)
        await _deliver(hook, event, payload, attempt + 1)
    await webhooks_col.update_one({"id": hook["id"]}, {"$set": {"last_delivery_at": now_iso(), "last_status": status}, "$inc": {"deliveries": 1, "failures": 0 if ok else 1}})


async def emit_event(event: str, payload: dict):
    """Fan-out an internal event to active webhooks (fire-and-forget)."""
    try:
        if not await flag("webhooks"):
            return
        async for hook in webhooks_col.find({"active": True}, {"_id": 0}):
            evs = hook.get("events") or ["*"]
            if "*" in evs or event in evs or any(event.startswith(e.rstrip("*")) for e in evs if e.endswith("*")):
                asyncio.create_task(_deliver(hook, event, payload))
    except Exception as e:
        logger.warning(f"emit_event error: {e}")


# ---------------- CONFIG ROUTES ----------------
@config_router.get("")
async def read_config(principal=Depends(require("config:read"))):
    return await get_config()


@config_router.patch("")
async def patch_config(body: Dict[str, Any], request: Request, principal=Depends(require("config:write"))):
    from v1_models import deep_merge
    cfg = await get_config()
    body.pop("id", None)
    body.pop("created_at", None)
    new_cfg = deep_merge(cfg, body)
    new_cfg["updated_at"] = now_iso()
    await config_col.replace_one({"id": "global"}, new_cfg, upsert=True)
    ver = await record_version("config", "global", cfg, new_cfg, actor_of(principal), source=principal.get("source", "manual"), reason="Config update", request_id=request_id_of(request))
    await audit_log(actor_of(principal), "update", "config", "global", {"changed": ver.get("changed_fields")}, request_id_of(request))
    return {**serialize_doc(new_cfg), "version_id": ver.get("id")}


@config_router.get("/flags")
async def read_flags(principal=Depends(require("config:read"))):
    return {"flags": (await get_config()).get("flags", {})}


class FlagBody(BaseModel):
    value: bool
    reason: Optional[str] = ""


@config_router.put("/flags/{name}")
async def set_flag(name: str, body: FlagBody, request: Request, principal=Depends(require("config:write"))):
    cfg = await get_config()
    new_cfg = json.loads(json.dumps(cfg))
    new_cfg.setdefault("flags", {})[name] = body.value
    new_cfg["updated_at"] = now_iso()
    await config_col.replace_one({"id": "global"}, new_cfg, upsert=True)
    await record_version("config", "global", cfg, new_cfg, actor_of(principal), source=principal.get("source", "manual"), reason=body.reason or f"flag {name}={body.value}", request_id=request_id_of(request))
    return {"flag": name, "value": body.value}


# ---------------- WEBHOOKS ----------------
class WebhookIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    url: str
    events: List[str] = ["*"]
    description: str = ""
    active: bool = True


WEBHOOK_EVENTS = ["model.created", "model.updated", "model.published", "media.uploaded", "seo.autofix_applied", "alert.created", "job.failed", "version.rolled_back", "ai.action", "backup.created", "*"]


@webhooks_router.get("")
async def list_webhooks(principal=Depends(require("webhooks:manage"))):
    items = await webhooks_col.find({}, {"_id": 0, "secret": 0}).to_list(100)
    return {"items": items, "events": WEBHOOK_EVENTS, "signature": "X-LS-Signature = sha256=HMAC_SHA256(secret, X-LS-Timestamp + '.' + body)"}


@webhooks_router.post("", status_code=201)
async def create_webhook(body: WebhookIn, request: Request, principal=Depends(require("webhooks:manage"))):
    if not body.url.startswith("https://") and not body.url.startswith("http://localhost"):
        raise HTTPException(status_code=400, detail="URL webhook deve essere https")
    secret = "whsec_" + uuid.uuid4().hex + uuid.uuid4().hex[:16]
    doc = {"id": str(uuid.uuid4()), **body.model_dump(), "secret": secret, "created_by": actor_of(principal), "created_at": now_iso(), "deliveries": 0, "failures": 0}
    await webhooks_col.insert_one(doc)
    await audit_log(actor_of(principal), "create", "webhook", doc["id"], {"url": body.url}, request_id_of(request))
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["note"] = "Il secret viene mostrato SOLO ora: salvalo."
    return out


@webhooks_router.delete("/{hook_id}")
async def delete_webhook(hook_id: str, principal=Depends(require("webhooks:manage"))):
    r = await webhooks_col.delete_one({"id": hook_id})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Webhook non trovato")
    return {"ok": True}


@webhooks_router.post("/{hook_id}/test")
async def test_webhook(hook_id: str, principal=Depends(require("webhooks:manage"))):
    hook = await webhooks_col.find_one({"id": hook_id}, {"_id": 0})
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook non trovato")
    await _deliver(hook, "webhook.test", {"message": "Test LATO SEGRETO"})
    d = await webhook_deliveries_col.find_one({"webhook_id": hook_id}, {"_id": 0}, sort=[("created_at", -1)])
    return {"delivery": d}


@webhooks_router.get("/{hook_id}/deliveries")
async def deliveries(hook_id: str, limit: int = 50, principal=Depends(require("webhooks:manage"))):
    items = await webhook_deliveries_col.find({"webhook_id": hook_id}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"items": items}


# ---------------- BACKUP / RESTORE ----------------
BACKUP_COLLECTIONS = {
    "models": models_col, "categories": categories_col, "articles": articles_col, "settings": settings_col, "config": config_col,
    "landings": landings_col, "experiments": experiments_col, "redirects": redirects_col, "files": files_col, "seo_issues": seo_issues_col,
    "admin_users": admins_col, "api_keys": api_keys_col, "webhooks": webhooks_col,
}


async def create_backup(actor: str = "system", include_events: bool = False, reason: str = "") -> dict:
    snapshot: Dict[str, Any] = {"created_at": now_iso(), "app": APP_NAME, "collections": {}}
    counts = {}
    for name, col in BACKUP_COLLECTIONS.items():
        docs = await col.find({}, {"_id": 0}).to_list(50000)
        snapshot["collections"][name] = docs
        counts[name] = len(docs)
    if include_events:
        docs = await events_col.find({}, {"_id": 0}).to_list(500000)
        snapshot["collections"]["analytics_events"] = docs
        counts["analytics_events"] = len(docs)
    raw = json.dumps(snapshot, default=str).encode()
    gz = gzip.compress(raw)
    bid = str(uuid.uuid4())
    path = f"{APP_NAME}/backups/{now_iso()[:19].replace(':', '-')}-{bid[:8]}.json.gz"
    stored = None
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, put_object, path, gz, "application/gzip")
        stored = res.get("path", path)
    except Exception as e:
        logger.warning(f"backup storage failed, keeping inline copy: {e}")
    rec = {"id": bid, "storage_path": stored, "size": len(gz), "counts": counts, "created_by": actor, "created_at": now_iso(), "reason": reason, "inline": None if stored else gz}
    await backups_col.insert_one(dict(rec))
    rec.pop("inline", None)
    await emit_event("backup.created", {"id": bid, "size": len(gz), "counts": counts})
    # retention
    cfg = await get_config()
    keep = int((cfg.get("backups") or {}).get("retention", 14))
    old = await backups_col.find({}, {"_id": 0, "id": 1}).sort("created_at", -1).skip(keep).to_list(1000)
    if old:
        await backups_col.delete_many({"id": {"$in": [o["id"] for o in old]}})
    return rec


async def _load_backup(bid: str) -> dict:
    rec = await backups_col.find_one({"id": bid})
    if not rec:
        raise HTTPException(status_code=404, detail="Backup non trovato")
    if rec.get("inline"):
        gz = rec["inline"]
    else:
        data, _ = await asyncio.get_event_loop().run_in_executor(None, get_object, rec["storage_path"])
        gz = data
    return json.loads(gzip.decompress(gz).decode())


class BackupBody(BaseModel):
    include_events: bool = False
    reason: Optional[str] = ""


class RestoreBody(BaseModel):
    collections: Optional[List[str]] = None   # default: all in the snapshot
    mode: str = "replace"                      # replace | merge
    dry_run: bool = True
    confirm: bool = False


@backup_router.get("")
async def list_backups(principal=Depends(require("backup:manage"))):
    items = await backups_col.find({}, {"_id": 0, "inline": 0}).sort("created_at", -1).to_list(100)
    return {"items": items, "collections": list(BACKUP_COLLECTIONS.keys())}


@backup_router.post("", status_code=201)
async def backup_now(body: BackupBody = BackupBody(), request: Request = None, principal=Depends(require("backup:manage"))):
    rec = await create_backup(actor_of(principal), body.include_events, body.reason or "manual")
    await audit_log(actor_of(principal), "backup", "backup", rec["id"], {"counts": rec["counts"]}, request_id_of(request))
    return rec


@backup_router.get("/{backup_id}/download")
async def download_backup(backup_id: str, principal=Depends(require("backup:manage"))):
    snap = await _load_backup(backup_id)
    return Response(content=json.dumps(snap, default=str), media_type="application/json", headers={"Content-Disposition": f"attachment; filename=lato-segreto-backup-{backup_id[:8]}.json"})


@backup_router.post("/{backup_id}/restore")
async def restore_backup(backup_id: str, body: RestoreBody, request: Request, principal=Depends(require("backup:manage"))):
    snap = await _load_backup(backup_id)
    cols = body.collections or list(snap["collections"].keys())
    unknown = [c for c in cols if c not in BACKUP_COLLECTIONS and c != "analytics_events"]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Collection non ripristinabili: {unknown}")
    def _col(c):
        return BACKUP_COLLECTIONS[c] if c in BACKUP_COLLECTIONS else events_col
    plan = {c: {"in_backup": len(snap["collections"].get(c, [])), "current": await _col(c).count_documents({})} for c in cols}
    if body.dry_run or not body.confirm:
        return {"dry_run": True, "mode": body.mode, "plan": plan, "note": "Ripeti con dry_run=false e confirm=true per eseguire. Verrà creato un backup di sicurezza prima del ripristino."}
    safety = await create_backup(actor_of(principal), False, f"pre-restore {backup_id}")
    for c in cols:
        col = _col(c)
        docs = snap["collections"].get(c, [])
        if body.mode == "replace":
            await col.delete_many({})
            if docs:
                await col.insert_many(docs)
        else:
            for d in docs:
                if d.get("id"):
                    await col.replace_one({"id": d["id"]}, d, upsert=True)
    await audit_log(actor_of(principal), "restore", "backup", backup_id, {"collections": cols, "mode": body.mode, "safety_backup": safety["id"]}, request_id_of(request))
    return {"ok": True, "restored": plan, "safety_backup_id": safety["id"]}


# ---------------- AUTH: ME / API KEYS / USERS ----------------
@auth_router.get("/me")
async def me(principal=Depends(require())):
    return {k: principal.get(k) for k in ("type", "id", "email", "name", "role", "scopes", "source")}


@auth_router.get("/roles")
async def roles(principal=Depends(require())):
    return {"roles": {r: (ALL_SCOPES if "*" in s else s) for r, s in ROLE_SCOPES.items()}, "scopes": ALL_SCOPES}


class ApiKeyIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    name: str
    role: str = "AI_OPERATOR"
    scopes: Optional[List[str]] = None
    expires_at: Optional[str] = None
    rate_limit_per_min: int = 300
    ip_allowlist: List[str] = []
    source: str = "ai"   # ai | api
    capability_allow: Optional[List[str]] = None   # Phase 12A: if set, ONLY these capability ids (glob ok: "models.*")
    capability_deny: Optional[List[str]] = None    # Phase 12A: always blocked for this key


@auth_router.get("/keys")
async def list_keys(principal=Depends(require("keys:manage"))):
    items = await api_keys_col.find({}, {"_id": 0, "key_hash": 0}).sort("created_at", -1).to_list(200)
    return {"items": items}


@auth_router.post("/keys", status_code=201)
async def create_key(body: ApiKeyIn, request: Request, principal=Depends(require("keys:manage"))):
    role = normalize_role(body.role)
    if role not in ROLES:
        raise HTTPException(status_code=400, detail={"message": "Ruolo non valido", "roles": ROLES})
    if role == "SUPER_ADMIN" and principal.get("role") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Solo SUPER_ADMIN può creare chiavi SUPER_ADMIN")
    raw = generate_api_key()
    scopes = body.scopes or scopes_for_role(role)
    bad = [s for s in scopes if s not in ALL_SCOPES]
    if bad:
        raise HTTPException(status_code=400, detail={"message": "Scope non validi", "invalid": bad})
    allowed = set(scopes_for_role(role)) | set(ROLE_OPTIONAL_SCOPES.get(role, []))
    outside = [s for s in scopes if s not in allowed and "*" not in scopes_for_role(role)]
    if outside:
        raise HTTPException(status_code=400, detail={"message": f"Scope non consentiti per il ruolo {role}", "invalid": outside, "optional_allowed": ROLE_OPTIONAL_SCOPES.get(role, [])})
    doc = {"id": str(uuid.uuid4()), "name": body.name, "role": role, "scopes": scopes, "key_hash": hash_key(raw), "prefix": raw[:10],
           "expires_at": body.expires_at, "rate_limit_per_min": body.rate_limit_per_min, "ip_allowlist": body.ip_allowlist, "source": body.source,
           "capability_allow": body.capability_allow, "capability_deny": body.capability_deny or [],
           "active": True, "uses": 0, "request_count": 0, "error_count": 0, "last_ip": None, "revoked_at": None, "disabled_at": None,
           "created_by": actor_of(principal), "created_at": now_iso(), "last_used_at": None}
    await api_keys_col.insert_one(doc)
    await audit_log(actor_of(principal), "create", "api_key", doc["id"], {"name": body.name, "role": role}, request_id_of(request))
    return {"id": doc["id"], "name": body.name, "role": role, "scopes": scopes, "api_key": raw, "prefix": doc["prefix"],
            "note": "La chiave completa viene mostrata SOLO ora. Usala nell'header X-API-Key."}


@auth_router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, request: Request, principal=Depends(require("keys:manage"))):
    r = await api_keys_col.update_one({"id": key_id}, {"$set": {"active": False, "revoked_at": now_iso(), "revoked_by": actor_of(principal)}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="API key non trovata")
    await audit_log(actor_of(principal), "revoke", "api_key", key_id, {}, request_id_of(request))
    return {"ok": True, "revoked": True}


@auth_router.post("/keys/{key_id}/disable")
async def disable_key(key_id: str, request: Request, principal=Depends(require("keys:manage"))):
    r = await api_keys_col.update_one({"id": key_id, "revoked_at": None}, {"$set": {"active": False, "disabled_at": now_iso()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="API key non trovata o revocata")
    await audit_log(actor_of(principal), "disable", "api_key", key_id, {}, request_id_of(request))
    return {"ok": True, "active": False}


@auth_router.post("/keys/{key_id}/enable")
async def enable_key(key_id: str, request: Request, principal=Depends(require("keys:manage"))):
    r = await api_keys_col.update_one({"id": key_id, "revoked_at": None}, {"$set": {"active": True, "disabled_at": None}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="API key non trovata o revocata (non riattivabile)")
    await audit_log(actor_of(principal), "enable", "api_key", key_id, {}, request_id_of(request))
    return {"ok": True, "active": True}


@auth_router.post("/keys/{key_id}/rotate")
async def rotate_key(key_id: str, request: Request, principal=Depends(require("keys:manage"))):
    """Issue a new secret for the same key record (old secret stops working immediately)."""
    rec = await api_keys_col.find_one({"id": key_id, "revoked_at": None}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="API key non trovata o revocata")
    raw = generate_api_key()
    await api_keys_col.update_one({"id": key_id}, {"$set": {"key_hash": hash_key(raw), "prefix": raw[:10], "rotated_at": now_iso(), "rotated_by": actor_of(principal), "active": True, "disabled_at": None}})
    await audit_log(actor_of(principal), "rotate", "api_key", key_id, {}, request_id_of(request))
    return {"id": key_id, "name": rec["name"], "role": rec["role"], "scopes": rec.get("scopes"), "api_key": raw, "prefix": raw[:10], "note": "Nuova chiave mostrata SOLO ora. La precedente non funziona più."}


class KeyCapabilitiesIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    capability_allow: Optional[List[str]] = None   # None = no restriction (all capabilities the scopes permit)
    capability_deny: List[str] = []


@auth_router.patch("/keys/{key_id}/capabilities")
async def patch_key_capabilities(key_id: str, body: KeyCapabilitiesIn, request: Request, principal=Depends(require("keys:manage"))):
    """Phase 12A: per-key capability allow/deny (globs like 'models.*'). Deny always wins; allow can only restrict
    (the scope check is still enforced by the dispatcher), never broaden."""
    rec = await api_keys_col.find_one({"id": key_id, "revoked_at": None}, {"_id": 0, "id": 1})
    if not rec:
        raise HTTPException(status_code=404, detail="API key non trovata o revocata")
    import re as _re
    pat = _re.compile(r"^[a-z0-9_.*\-]+$")
    bad = [p for p in ((body.capability_allow or []) + (body.capability_deny or [])) if not pat.match(p)]
    if bad:
        raise HTTPException(status_code=400, detail={"message": "Pattern capability non validi", "invalid": bad})
    allow = [p.strip() for p in body.capability_allow] if body.capability_allow is not None else None
    deny = [p.strip() for p in body.capability_deny or []]
    await api_keys_col.update_one({"id": key_id}, {"$set": {"capability_allow": allow, "capability_deny": deny, "updated_at": now_iso()}})
    await audit_log(actor_of(principal), "capabilities", "api_key", key_id, {"allow": allow, "deny": deny}, request_id_of(request))
    return {"id": key_id, "capability_allow": allow, "capability_deny": deny}


@auth_router.get("/keys/{key_id}/usage")
async def key_usage(key_id: str, principal=Depends(require("keys:manage"))):
    rec = await api_keys_col.find_one({"id": key_id}, {"_id": 0, "key_hash": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="API key non trovata")
    from v1_security import bucket_usage
    from v1_ai_policy import ai_config
    cfg = await ai_config()
    since = (__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - __import__("datetime").timedelta(hours=24)).isoformat()
    from database import ai_actions_col
    acts = await ai_actions_col.count_documents({"key_id": key_id, "timestamp": {"$gte": since}})
    return {**rec, "requests_last_minute": bucket_usage(f"ai:{key_id}") or bucket_usage(f"key:{key_id}"), "requests_last_hour": bucket_usage(f"key:{key_id}", 3600), "ai_actions_24h": acts,
            "effective_rate_limit_per_min": min(cfg["rate_limit_per_min"], int(rec.get("rate_limit_per_min") or cfg["rate_limit_per_min"]))}


class UserIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    email: str
    password: str
    role: str = "READ_ONLY"


@auth_router.get("/users")
async def list_users(principal=Depends(require("users:manage"))):
    items = await admins_col.find({}, {"_id": 0, "password_hash": 0}).to_list(200)
    for u in items:
        u["role"] = normalize_role(u.get("role") or u.get("ruolo"))
    return {"items": items}


@auth_router.post("/users", status_code=201)
async def create_user(body: UserIn, request: Request, principal=Depends(require("users:manage"))):
    role = normalize_role(body.role)
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password di almeno 8 caratteri")
    if await admins_col.find_one({"email": body.email.lower().strip()}):
        raise HTTPException(status_code=409, detail="Email già registrata")
    doc = {"id": str(uuid.uuid4()), "email": body.email.lower().strip(), "password_hash": hash_password(body.password), "ruolo": role, "role": role, "active": True, "created_at": now_iso(), "created_by": actor_of(principal)}
    await admins_col.insert_one(doc)
    await audit_log(actor_of(principal), "create", "user", doc["id"], {"email": doc["email"], "role": role}, request_id_of(request))
    return {"id": doc["id"], "email": doc["email"], "role": role}


class UserPatch(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None


@auth_router.patch("/users/{user_id}")
async def patch_user(user_id: str, body: UserPatch, request: Request, principal=Depends(require("users:manage"))):
    u = await admins_col.find_one({"id": user_id}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    upd: Dict[str, Any] = {}
    if body.role:
        upd["role"] = upd["ruolo"] = normalize_role(body.role)
    if body.active is not None:
        if user_id == principal.get("id") and body.active is False:
            raise HTTPException(status_code=400, detail="Non puoi disattivare te stesso")
        upd["active"] = body.active
    if body.password:
        if len(body.password) < 8:
            raise HTTPException(status_code=400, detail="Password di almeno 8 caratteri")
        upd["password_hash"] = hash_password(body.password)
    await admins_col.update_one({"id": user_id}, {"$set": upd})
    await audit_log(actor_of(principal), "update", "user", user_id, {k: v for k, v in upd.items() if k != "password_hash"}, request_id_of(request))
    return {"ok": True}


@auth_router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request, principal=Depends(require("users:manage"))):
    """Soft delete: the user is deactivated (never hard-deleted, audit stays consistent)."""
    if user_id == principal.get("id"):
        raise HTTPException(status_code=400, detail="Non puoi eliminare te stesso")
    r = await admins_col.update_one({"id": user_id}, {"$set": {"active": False, "is_deleted": True, "deleted_at": now_iso()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    await audit_log(actor_of(principal), "soft_delete", "user", user_id, {}, request_id_of(request))
    return {"ok": True, "soft_deleted": True}


# ---------------- VERSIONS / AUDIT ROUTES ----------------
versions_router = APIRouter(prefix="/api/v1", tags=["Versions, Rollback & Audit"])


@versions_router.get("/versions")
async def versions(entity: Optional[str] = None, entity_id: Optional[str] = None, limit: int = 50, skip: int = 0, principal=Depends(require("versions:read"))):
    from v1_versioning import list_versions
    return await list_versions(entity, entity_id, limit, skip)


@versions_router.get("/versions/{version_id}")
async def version_detail(version_id: str, principal=Depends(require("versions:read"))):
    from v1_versioning import get_version
    return await get_version(version_id)


class RollbackBody(BaseModel):
    reason: Optional[str] = ""


@versions_router.post("/versions/{version_id}/rollback")
async def rollback(version_id: str, request: Request, body: RollbackBody = RollbackBody(), principal=Depends(require("versions:rollback"))):
    from v1_versioning import rollback_version
    res = await rollback_version(version_id, actor_of(principal), request_id_of(request), body.reason or "")
    await emit_event("version.rolled_back", {"version_id": version_id, "actor": actor_of(principal), **res})
    return res


@versions_router.get("/audit")
async def audit(entity: Optional[str] = None, entity_id: Optional[str] = None, actor: Optional[str] = None, request_id: Optional[str] = None, limit: int = 100, principal=Depends(require("versions:read"))):
    from database import audit_col
    q: Dict[str, Any] = {}
    if entity:
        q["entity"] = entity
    if entity_id:
        q["entity_id"] = entity_id
    if actor:
        q["actor"] = actor
    if request_id:
        q["request_id"] = request_id
    items = await audit_col.find(q, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return {"items": items}
