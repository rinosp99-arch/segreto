"""PHASE 10 - CHATGPT CONTROL LAYER: policy, guards, approvals, metrics, error contract.

- Feature flags: ai_api_enabled (kill switch), ai_write_enabled (FULL/READ_ONLY), ai_batch_enabled, ai_approval_flow_enabled.
- Safe execution policy: SAFE | REVIEW_REQUIRED | CRITICAL (central classification, configurable review fields).
- Approval tokens: single-use, TTL, bound to actor + target + action + payload hash.
- AI metrics: in-memory ring (latency p50/p95, counts, 429s, top capabilities) + daily persisted counters.
- Standard error contract for /api/v1/ai/*.
"""
import time
import uuid
import json
import hashlib
import secrets
import statistics
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from fastapi import Depends, Request, HTTPException

from database import db, config_col, now_iso
from v1_security import rate_limit_shared, resolve_principal, has_scope, err, READ_SCOPES, CRITICAL_SCOPES, DEFAULT_LIMIT_AI, MIN_AI_LIMIT, rate_limit, bucket_usage

approvals_col = db["ai_approvals"]
ai_metrics_col = db["ai_metrics"]

SAFE, REVIEW, CRITICAL = "SAFE", "REVIEW_REQUIRED", "CRITICAL"

ERROR_CODES = [
    "AUTH_REQUIRED", "INVALID_API_KEY", "API_KEY_REVOKED", "API_KEY_DISABLED", "API_KEY_EXPIRED", "INSUFFICIENT_SCOPE", "AI_API_DISABLED",
    "READ_ONLY_MODE", "BATCH_DISABLED", "RATE_LIMITED", "NOT_FOUND", "AMBIGUOUS_REFERENCE", "VALIDATION_FAILED", "PUBLICATION_BLOCKED",
    "SEO_REVIEW_REQUIRED", "CRITICAL_ACTION_BLOCKED", "APPROVAL_REQUIRED", "APPROVAL_EXPIRED", "APPROVAL_INVALID", "APPROVAL_DISABLED",
    "IDEMPOTENCY_CONFLICT", "MEDIA_VALIDATION_FAILED", "CONFLICT", "INTERNAL_ERROR", "BAD_REQUEST", "IP_NOT_ALLOWED",
]

DEFAULT_AI_POLICY = {
    "review_fields": ["slug", "nome", "nome_artistico", "onlyfans_url", "bio", "bio_segreta", "frase",
                      "seo.title", "seo.meta_description", "seo.canonical", "seo.robots", "seo.indexable"],
    "approval_ttl_min": 30,
    "max_batch": 50,
    "rate_limit_per_min": DEFAULT_LIMIT_AI,
}


# ---------------- CONFIG HELPERS ----------------
async def ai_config() -> dict:
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1, "ai": 1}) or {}
    flags = cfg.get("flags") or {}
    ai = cfg.get("ai") or {}
    policy = {**DEFAULT_AI_POLICY, **(ai.get("policy") or {})}
    return {
        "enabled": flags.get("ai_api_enabled", True) and flags.get("ai_api", True),
        "write_enabled": flags.get("ai_write_enabled", False),
        "batch_enabled": flags.get("ai_batch_enabled", True),
        "approval_enabled": flags.get("ai_approval_flow_enabled", True),
        "mode": "FULL" if flags.get("ai_write_enabled", False) else "READ_ONLY",
        "policy": policy,
        "rate_limit_per_min": max(MIN_AI_LIMIT, int(policy.get("rate_limit_per_min") or DEFAULT_LIMIT_AI)),
    }


# ---------------- GUARD ----------------
# dry_run is a READ-level operation: a write scope can be satisfied by its preview (read) scope when dry_run=true
PREVIEW_SCOPE = {
    "models:create": "models:read", "models:update": "models:read", "models:publish": "models:validate", "models:unpublish": "models:read",
    "models:archive": "models:read", "models:feature": "models:read", "seo:safe_fix": "seo:audit",
    "landing:create": "landing:read", "landing:update": "landing:read", "landing:publish": "landing:read", "rollback:execute": "rollback:read",
}


async def request_is_dry_run(request: Request) -> bool:
    if str(request.query_params.get("dry_run", "")).lower() in ("1", "true"):
        return True
    if request.method in ("POST", "PATCH", "PUT"):
        try:
            payload = await request.json()
            return isinstance(payload, dict) and payload.get("dry_run") is True
        except Exception:
            return False
    return False


def missing_scopes_for(principal: dict, scopes, dry: bool) -> List[str]:
    """Scopes still missing; when dry=True a write scope may be replaced by its preview scope."""
    out = []
    for s in scopes:
        if has_scope(principal, s):
            continue
        if dry and s in PREVIEW_SCOPE and has_scope(principal, PREVIEW_SCOPE[s]):
            continue
        out.append(s)
    return out


def ai_guard(*scopes: str, write: bool = False, batch: bool = False, dry_capable: bool = True):
    """Dependency for /api/v1/ai routes: kill switch, mode, flags, scopes, dedicated AI rate limit.
    dry_capable=False marks write endpoints that cannot preview (upload, confirm): always blocked in READ_ONLY."""
    async def _dep(request: Request, principal: dict = Depends(resolve_principal)):
        cfg = await ai_config()
        is_machine = principal.get("type") == "api_key"
        if is_machine and not cfg["enabled"]:
            raise err(503, "AI_API_DISABLED", "ChatGPT API disattivata dall'amministratore (kill switch)")
        dry = bool(write and dry_capable and await request_is_dry_run(request))
        if is_machine and write and not cfg["write_enabled"]:
            # READ_ONLY still allows previews: dry_run=true (JSON body or query string) never mutates
            if not dry:
                raise err(403, "READ_ONLY_MODE", "ChatGPT API in modalità READ_ONLY: sono consentite solo letture, audit e anteprime (dry_run=true)")
            request.state.forced_dry_run = True
        if batch and not cfg["batch_enabled"]:
            raise err(403, "BATCH_DISABLED", "Operazioni batch disattivate (flag ai_batch_enabled)")
        if is_machine:
            crit = [s for s in scopes if s in CRITICAL_SCOPES]
            if crit:
                raise err(403, "CRITICAL_ACTION_BLOCKED", "Operazione critica non consentita alle API key", scopes=crit)
            rl = await rate_limit_shared(f"ai:{principal['id']}", min(cfg["rate_limit_per_min"], principal.get("rate_limit", cfg["rate_limit_per_min"])))
            request.state.rate = rl
        # every AI endpoint requires ai:execute in addition to the action scopes (preview scopes accepted for dry_run)
        missing = missing_scopes_for(principal, ("ai:execute", *scopes), dry)
        if missing:
            extra = {"missing_scopes": missing, "role": principal.get("role")}
            if write and dry_capable and not dry:
                extra["hint"] = "Con dry_run=true bastano gli scope di lettura corrispondenti (anteprima, nessuna modifica)"
            raise err(403, "INSUFFICIENT_SCOPE", "Permessi insufficienti", **extra)
        request.state.ai_write = write and not dry
        request.state.ai_dry_run = dry
        return principal
    return _dep


# ---------------- POLICY ----------------
def _flatten(d: Any, prefix: str = "") -> List[str]:
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out += _flatten(v, p)
            else:
                out.append(p)
    return out


def classify_model_changes(changes: dict, policy: dict) -> dict:
    """Return {level, review_fields, safe_fields}."""
    paths = _flatten(changes)
    review = set(policy.get("review_fields") or [])
    hit = [p for p in paths if p in review or p.split(".")[0] in review]
    if "stato" in paths:
        hit.append("stato")
    return {"level": REVIEW if hit else SAFE, "review_fields": sorted(set(hit)), "safe_fields": sorted(set(paths) - set(hit))}


# ---------------- APPROVAL TOKENS ----------------
def payload_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def create_approval(kind: str, actor: str, target: dict, payload: dict, before: Any, after: Any, reason: str,
                          request_id: str, ttl_min: Optional[int] = None) -> dict:
    cfg = await ai_config()
    ttl = int(ttl_min or cfg["policy"].get("approval_ttl_min", 30))
    token = "apr_" + secrets.token_urlsafe(24)
    doc = {
        "id": str(uuid.uuid4()), "token_hash": hashlib.sha256(token.encode()).hexdigest(), "type": kind, "actor": actor,
        "target": target, "payload": payload, "payload_hash": payload_hash(payload), "before": before, "after": after,
        "reason": reason, "request_id": request_id, "created_at": now_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=ttl)).isoformat(), "used_at": None, "status": "pending",
    }
    await approvals_col.insert_one(dict(doc))
    return {"type": kind, "token": token, "expires_at": doc["expires_at"], "target": target, "before": before, "after": after, "reason": reason,
            "confirm_with": "POST /api/v1/ai/approvals/confirm {token}", "approval_id": doc["id"]}


async def consume_approval(token: str, actor: str, payload_override: Optional[dict] = None) -> dict:
    if not token or not token.startswith("apr_"):
        raise err(400, "APPROVAL_INVALID", "Token di approvazione non valido")
    doc = await approvals_col.find_one({"token_hash": hashlib.sha256(token.encode()).hexdigest()}, {"_id": 0})
    if not doc:
        raise err(404, "APPROVAL_INVALID", "Token di approvazione sconosciuto")
    if doc.get("used_at") or doc.get("status") != "pending":
        raise err(409, "APPROVAL_INVALID", "Token già utilizzato")
    if doc["expires_at"] < now_iso():
        await approvals_col.update_one({"id": doc["id"]}, {"$set": {"status": "expired"}})
        raise err(410, "APPROVAL_EXPIRED", "Token di approvazione scaduto: prepara di nuovo la modifica")
    if doc.get("actor") != actor:
        raise err(403, "APPROVAL_INVALID", "Il token è legato a un altro attore")
    if payload_override is not None and payload_hash(payload_override) != doc["payload_hash"]:
        raise err(409, "APPROVAL_INVALID", "Il payload è cambiato rispetto all'anteprima approvata")
    await approvals_col.update_one({"id": doc["id"]}, {"$set": {"used_at": now_iso(), "status": "used"}})
    return doc


async def list_pending_approvals(actor: Optional[str] = None, limit: int = 50) -> List[dict]:
    q: Dict[str, Any] = {"status": "pending", "expires_at": {"$gte": now_iso()}}
    if actor:
        q["actor"] = actor
    return await approvals_col.find(q, {"_id": 0, "token_hash": 0}).sort("created_at", -1).to_list(limit)


# ---------------- METRICS ----------------
_lat = deque(maxlen=2000)          # (ts, latency_ms, status, path, key_id)
_counters = {"requests": 0, "success": 0, "errors": 0, "rate_limited": 0, "mutations": 0, "rollbacks": 0, "approvals_requested": 0, "approvals_confirmed": 0, "critical_blocked": 0}
_caps: Dict[str, int] = {}
_started = time.time()


def _cap_of(path: str) -> str:
    p = path.replace("/api/v1/ai/", "").split("?")[0]
    parts = p.split("/")
    parts = [x if len(x) < 30 else "{ref}" for x in parts]
    return "/".join(parts)


async def record_metric(path: str, method: str, status: int, latency_ms: float, key_id: Optional[str], is_write: bool):
    _lat.append((time.time(), latency_ms, status, path, key_id))
    _counters["requests"] += 1
    if 200 <= status < 400:
        _counters["success"] += 1
        if is_write and method in ("POST", "PATCH", "PUT", "DELETE"):
            _counters["mutations"] += 1
    else:
        _counters["errors"] += 1
    if status == 429:
        _counters["rate_limited"] += 1
    if status == 403 and "CRITICAL" in path:
        pass
    cap = _cap_of(path)
    _caps[cap] = _caps.get(cap, 0) + 1
    day = now_iso()[:10]
    inc = {"requests": 1, "success": 1 if 200 <= status < 400 else 0, "errors": 0 if 200 <= status < 400 else 1, "rate_limited": 1 if status == 429 else 0,
           "mutations": 1 if (200 <= status < 400 and is_write and method in ("POST", "PATCH", "PUT", "DELETE")) else 0,
           "latency_sum_ms": round(latency_ms),
           f"caps.{cap.replace('.', '_').replace('/', '__')}": 1}
    try:
        await ai_metrics_col.update_one({"day": day}, {"$inc": inc, "$set": {"updated_at": now_iso()}, "$max": {"latency_max_ms": round(latency_ms)}, "$setOnInsert": {"day": day}}, upsert=True)
    except Exception:
        pass


def bump(counter: str, n: int = 1):
    _counters[counter] = _counters.get(counter, 0) + n


async def metrics_snapshot_shared() -> dict:
    """Cluster-wide view: counters come from Mongo (all pods, all days); latency/p50/p95 from this pod's window.
    Production runs several replicas, so in-memory counters alone would show only one pod (Phase 11 finding)."""
    snap = metrics_snapshot()
    try:
        docs = await ai_metrics_col.find({}, {"_id": 0}).to_list(400)
    except Exception:
        docs = []
    if docs:
        tot = {"requests": 0, "success": 0, "errors": 0, "rate_limited": 0, "mutations": 0}
        caps: Dict[str, int] = {}
        for d in docs:
            for k in tot:
                tot[k] += int(d.get(k, 0) or 0)
            for ck, cv in (d.get("caps") or {}).items():
                name = ck.replace("__", "/")
                caps[name] = caps.get(name, 0) + int(cv or 0)
        # keep pod-only counters that Mongo does not track (approvals, rollbacks, critical blocked)
        merged = dict(snap["counters"])
        merged.update(tot)
        snap["counters"] = merged
        snap["counters_scope"] = "cluster (Mongo, tutti i pod)"
        snap["top_capabilities"] = sorted(caps.items(), key=lambda x: -x[1])[:10] or snap["top_capabilities"]
        today = next((d for d in docs if d.get("day") == now_iso()[:10]), None)
        if today:
            snap["today"] = {"requests": today.get("requests", 0), "errors": today.get("errors", 0), "rate_limited": today.get("rate_limited", 0), "mutations": today.get("mutations", 0),
                             "avg_ms": round(today.get("latency_sum_ms", 0) / max(1, today.get("requests", 1)), 1), "max_ms": today.get("latency_max_ms", 0)}
    snap["latency_scope"] = "questo pod (ultima ora)"
    return snap


def metrics_snapshot() -> dict:
    now = time.time()
    last_h = [x for x in _lat if now - x[0] < 3600]
    last_m = [x for x in _lat if now - x[0] < 60]
    lats = sorted(x[1] for x in last_h) or [0]
    def pct(p):
        if not lats:
            return 0
        k = max(0, min(len(lats) - 1, int(round(p * (len(lats) - 1)))))
        return round(lats[k], 1)
    errs = [x for x in last_h if x[2] >= 400]
    return {
        "since": datetime.fromtimestamp(_started, tz=timezone.utc).isoformat(), "counters": dict(_counters),
        "last_hour": {"requests": len(last_h), "errors": len(errs), "success_rate": round((1 - len(errs) / len(last_h)) * 100, 1) if last_h else None,
                      "p50_ms": pct(0.5), "p95_ms": pct(0.95), "rate_limited": len([x for x in last_h if x[2] == 429])},
        "last_minute": {"requests": len(last_m)},
        "top_capabilities": sorted(_caps.items(), key=lambda x: -x[1])[:10],
        "last_request_at": datetime.fromtimestamp(_lat[-1][0], tz=timezone.utc).isoformat() if _lat else None,
        "last_error": next(({"at": datetime.fromtimestamp(x[0], tz=timezone.utc).isoformat(), "status": x[2], "path": x[3]} for x in reversed(_lat) if x[2] >= 400), None),
    }


# ---------------- ERROR CONTRACT ----------------
STATUS_CODE_MAP = {401: "AUTH_REQUIRED", 403: "INSUFFICIENT_SCOPE", 404: "NOT_FOUND", 409: "CONFLICT", 422: "VALIDATION_FAILED", 429: "RATE_LIMITED", 400: "BAD_REQUEST", 410: "APPROVAL_EXPIRED", 503: "AI_API_DISABLED", 500: "INTERNAL_ERROR", 502: "INTERNAL_ERROR"}


def error_body(exc: HTTPException, request_id: str) -> dict:
    detail = exc.detail
    code = STATUS_CODE_MAP.get(exc.status_code, "INTERNAL_ERROR")
    summary = str(detail)
    data: Dict[str, Any] = {}
    next_steps: List[str] = []
    if isinstance(detail, dict):
        code = detail.get("code") or code
        summary = detail.get("message") or summary
        data = {k: v for k, v in detail.items() if k not in ("code", "message")}
        if "candidates" in data or "matches" in data:
            code = "AMBIGUOUS_REFERENCE"
            data["matches"] = [{"id": c.get("id"), "nome": c.get("nome_artistico") or c.get("nome"), "slug": c.get("slug"), "status": c.get("workflow_status")} for c in (data.pop("candidates", None) or data.get("matches") or [])]
            next_steps = ["Ripeti la richiesta usando lo slug o l'id di una delle corrispondenze"]
        if summary.startswith("NON PUOI ANCORA PUBBLICARE") or "errors" in data and exc.status_code == 400:
            code = "PUBLICATION_BLOCKED"
            data["missing"] = [e.get("field") for e in data.get("errors", [])]
    elif isinstance(detail, str) and "non trovat" in detail.lower():
        code = "NOT_FOUND"
    if code == "INSUFFICIENT_SCOPE" and "missing_scopes" in data:
        next_steps = [f"Chiedi all'amministratore di aggiungere gli scope: {', '.join(data['missing_scopes'])}"]
    if code == "RATE_LIMITED":
        next_steps = ["Attendi Retry-After secondi e riprova"]
    if code == "READ_ONLY_MODE":
        next_steps = ["Puoi eseguire letture, audit e anteprime (dry_run=true). Chiedi di attivare la modalità FULL nel pannello Motore."]
    return {"ok": False, "summary": summary, "code": code, "data": data, "warnings": [], "next_steps": next_steps, "request_id": request_id, "approval_required": code == "APPROVAL_REQUIRED"}


# ---------------- SAFE SERIALIZATION ----------------
SECRET_KEYS = {"password_hash", "key_hash", "secret", "token_hash", "api_key", "jwt_secret", "mongo_url", "storage_key", "emergent_key"}


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if k.lower() in SECRET_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj
