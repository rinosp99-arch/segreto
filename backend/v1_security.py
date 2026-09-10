"""SUPER API security layer.

- Principals: admin users (JWT, roles) or API keys (X-API-Key, hashed, scoped).
- Roles -> scopes mapping (granular, with fine-grained ChatGPT scopes + legacy aliases).
- `require(*scopes)` FastAPI dependency (JWT OR API key).
- Sliding-window rate limiting per principal / IP.
- Request-ID + idempotency middleware helpers.
- HMAC signing helpers for webhooks.
- Machine-readable error codes (detail = {"code", "message", ...}).
"""
import os
import hmac
import time
import uuid
import hashlib
import secrets
from typing import Optional, List, Dict
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader

from database import api_keys_col, admins_col, now_iso

bearer_scheme = HTTPBearer(auto_error=False)
apikey_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def err(status: int, code: str, message: str, **extra) -> HTTPException:
    """Standard machine-readable error."""
    headers = extra.pop("headers", None)
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra}, headers=headers)


# ---------------- ROLES & SCOPES ----------------
# Coarse (Phase 9) scopes
COARSE_SCOPES = [
    "models:read", "models:write", "models:publish", "models:delete",
    "media:read", "media:write",
    "seo:read", "seo:write", "seo:autofix",
    "analytics:read",
    "landings:read", "landings:write", "landings:publish",
    "experiments:read", "experiments:write",
    "config:read", "config:write",
    "keys:manage", "users:manage",
    "jobs:read", "jobs:run",
    "health:read", "alerts:read", "alerts:write",
    "versions:read", "versions:rollback",
    "backup:manage", "webhooks:manage",
    "ai:execute",
]
# Fine-grained (Phase 10 / ChatGPT) scopes
FINE_SCOPES = [
    "models:create", "models:update", "models:validate", "models:unpublish", "models:archive", "models:feature",
    "media:upload", "media:optimize", "media:replace",
    "seo:audit", "seo:safe_fix", "seo:review_prepare",
    "landing:read", "landing:create", "landing:update", "landing:validate", "landing:publish",
    "system:status", "system:daily_summary",
    "rollback:read", "rollback:execute",
]
ALL_SCOPES = COARSE_SCOPES + FINE_SCOPES

# A coarse scope IMPLIES these fine scopes (backward compatible)
IMPLIED: Dict[str, List[str]] = {
    "models:write": ["models:create", "models:update", "models:validate", "models:archive", "models:feature"],
    "models:read": ["models:validate"],
    "models:publish": ["models:unpublish"],
    "media:write": ["media:upload", "media:optimize", "media:replace"],
    "seo:read": ["seo:audit"],
    "seo:write": ["seo:review_prepare", "seo:audit"],
    "seo:autofix": ["seo:safe_fix"],
    "landings:read": ["landing:read"],
    "landings:write": ["landing:create", "landing:update", "landing:validate"],
    "landings:publish": ["landing:publish"],
    "health:read": ["system:status"],
    "analytics:read": ["system:daily_summary"],
    "versions:read": ["rollback:read"],
    "versions:rollback": ["rollback:execute"],
    # fine -> coarse (so fine-only keys can call the underlying v1 services)
    "models:create": ["models:write"], "models:update": ["models:write"], "models:archive": ["models:write"], "models:feature": ["models:write"],
    "models:unpublish": ["models:publish"],
    "media:upload": ["media:write"], "media:optimize": ["media:write"], "media:replace": ["media:write"],
    "seo:audit": ["seo:read"], "seo:safe_fix": ["seo:autofix"], "seo:review_prepare": ["seo:write"],
    "landing:read": ["landings:read"], "landing:create": ["landings:write"], "landing:update": ["landings:write"], "landing:validate": ["landings:read"],
    "landing:publish": ["landings:publish"],
    "system:status": ["health:read"], "rollback:read": ["versions:read"], "rollback:execute": ["versions:rollback"],
}

# Scopes an API key (machine principal) may NEVER exercise: CRITICAL surface
CRITICAL_SCOPES = {"keys:manage", "users:manage", "config:write", "backup:manage", "webhooks:manage", "models:delete"}

AI_OPERATOR_SCOPES = [
    "models:read", "models:create", "models:update", "models:validate", "models:publish", "models:unpublish", "models:archive", "models:feature",
    "media:read", "media:upload", "media:optimize", "media:replace",
    "seo:read", "seo:audit", "seo:safe_fix", "seo:review_prepare",
    "landing:read", "landing:create", "landing:update", "landing:validate",
    "analytics:read", "system:status", "system:daily_summary",
    "rollback:read", "rollback:execute",
    "experiments:read", "health:read", "alerts:read", "jobs:read", "config:read", "ai:execute",
]
# Optional scopes that a human can explicitly grant to a key of that role
ROLE_OPTIONAL_SCOPES = {"AI_OPERATOR": ["landing:publish"]}
# Minimum-privilege preset for the first real ChatGPT connection (READ_ONLY session):
# reads, audits, validation, review preparation and dry-run previews only (dry_run accepts these read scopes).
AI_READ_ONLY_SCOPES = [
    "models:read", "models:validate", "media:read", "seo:read", "seo:audit", "seo:review_prepare",
    "analytics:read", "landing:read", "landing:validate", "rollback:read", "system:status", "system:daily_summary",
    "health:read", "alerts:read", "jobs:read", "experiments:read", "config:read", "ai:execute",
]

ROLE_SCOPES = {
    "SUPER_ADMIN": ["*"],
    "ADMIN": [s for s in ALL_SCOPES if s not in ("keys:manage", "users:manage", "backup:manage")],
    "AI_OPERATOR": AI_OPERATOR_SCOPES,
    "SEO_MANAGER": [
        "models:read", "media:read", "seo:read", "seo:write", "seo:autofix", "analytics:read",
        "landings:read", "landings:write", "versions:read", "versions:rollback", "health:read", "alerts:read", "jobs:read", "config:read", "ai:execute",
    ],
    "CONTENT_MANAGER": [
        "models:read", "models:write", "models:publish", "media:read", "media:write",
        "landings:read", "landings:write", "versions:read", "analytics:read", "health:read", "alerts:read", "config:read", "ai:execute",
    ],
    "ANALYST": ["models:read", "analytics:read", "experiments:read", "health:read", "alerts:read", "jobs:read", "seo:read", "landings:read", "config:read", "ai:execute"],
    "READ_ONLY": ["models:read", "media:read", "seo:read", "analytics:read", "landings:read", "experiments:read", "health:read", "alerts:read", "jobs:read", "versions:read", "config:read"],
}
ROLES = list(ROLE_SCOPES.keys())
WRITE_BLOCKED_LEGACY_ROLES = {"ANALYST", "READ_ONLY"}
READ_SCOPES = {s for s in ALL_SCOPES if s.endswith(":read") or s in ("models:validate", "seo:audit", "seo:review_prepare", "landing:validate", "system:status", "system:daily_summary", "rollback:read", "ai:execute")}


def normalize_role(ruolo: Optional[str]) -> str:
    """Legacy 'amministratore' -> SUPER_ADMIN."""
    if not ruolo:
        return "SUPER_ADMIN"
    r = str(ruolo).upper()
    if r in ROLE_SCOPES:
        return r
    if r in ("AMMINISTRATORE", "ADMINISTRATOR"):
        return "SUPER_ADMIN"
    return "READ_ONLY"


def scopes_for_role(role: str) -> List[str]:
    sc = ROLE_SCOPES.get(role, [])
    return ALL_SCOPES[:] if "*" in sc else sc[:]


def expand_scopes(scopes: List[str]) -> set:
    out = set(scopes)
    if "*" in out:
        return set(ALL_SCOPES) | {"*"}
    changed = True
    while changed:
        changed = False
        for s in list(out):
            for i in IMPLIED.get(s, []):
                if i not in out:
                    out.add(i)
                    changed = True
    return out


def has_scope(principal: dict, scope: str) -> bool:
    sc = principal.get("scopes") or []
    if "*" in sc:
        return True
    exp = principal.get("_expanded")
    if exp is None:
        exp = expand_scopes(sc)
        principal["_expanded"] = exp
    return scope in exp


# ---------------- API KEYS ----------------
def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return "ls_" + secrets.token_urlsafe(32)


# ---------------- RATE LIMIT (sliding window, in-memory) ----------------
_buckets: dict = {}
DEFAULT_LIMIT_USER = int(os.environ.get("RATE_LIMIT_USER_PER_MIN", "600"))
DEFAULT_LIMIT_KEY = int(os.environ.get("RATE_LIMIT_KEY_PER_MIN", "300"))
DEFAULT_LIMIT_PUBLIC = int(os.environ.get("RATE_LIMIT_PUBLIC_PER_MIN", "240"))
DEFAULT_LIMIT_AI = int(os.environ.get("RATE_LIMIT_AI_PER_MIN", "120"))
MIN_AI_LIMIT = 10  # anti-abuse protections can never be fully disabled


def rate_limit(bucket_id: str, limit_per_min: int, window: float = 60.0) -> dict:
    now = time.time()
    hits = [t for t in _buckets.get(bucket_id, []) if now - t < window]
    if len(hits) >= limit_per_min:
        retry = int(window - (now - hits[0])) + 1
        _buckets[bucket_id] = hits
        raise err(429, "RATE_LIMITED", "Limite richieste superato. Riprova tra poco.", retry_after=max(1, retry),
                  headers={"Retry-After": str(max(1, retry)), "X-RateLimit-Limit": str(limit_per_min), "X-RateLimit-Remaining": "0"})
    hits.append(now)
    _buckets[bucket_id] = hits
    if len(_buckets) > 5000:
        for k in list(_buckets.keys())[:1000]:
            if not _buckets[k] or now - _buckets[k][-1] > window:
                _buckets.pop(k, None)
    return {"limit": limit_per_min, "remaining": max(0, limit_per_min - len(hits))}


def bucket_usage(bucket_id: str, window: float = 60.0) -> int:
    now = time.time()
    return len([t for t in _buckets.get(bucket_id, []) if now - t < window])


# ---------------- PRINCIPAL RESOLUTION ----------------
async def resolve_principal(request: Request,
                            creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
                            api_key: Optional[str] = Depends(apikey_scheme)) -> dict:
    ip = request.client.host if request.client else ""
    # Accept "Authorization: Bearer ls_..." (API key via bearer) for GPT Actions convenience
    if not api_key and creds and creds.credentials and creds.credentials.startswith("ls_"):
        api_key, creds = creds.credentials, None
    # 1) API key
    if api_key:
        rec = await api_keys_col.find_one({"key_hash": hash_key(api_key)}, {"_id": 0})
        if not rec:
            raise err(401, "INVALID_API_KEY", "API key non valida")
        async def _fail(code, msg):
            await api_keys_col.update_one({"id": rec["id"]}, {"$inc": {"error_count": 1}, "$set": {"last_error_at": now_iso(), "last_error_status": 401, "last_error_code": code, "last_ip": ip}})
            raise err(401, code, msg)
        if rec.get("revoked_at") or not rec.get("active", True):
            await _fail("API_KEY_REVOKED" if rec.get("revoked_at") else "API_KEY_DISABLED", "API key revocata o disattivata")
        if rec.get("expires_at") and rec["expires_at"] < now_iso():
            await _fail("API_KEY_EXPIRED", "API key scaduta")
        allow = rec.get("ip_allowlist") or []
        if allow and ip not in allow:
            raise err(403, "IP_NOT_ALLOWED", "IP non autorizzato per questa API key")
        role = normalize_role(rec.get("role"))
        allowed = set(scopes_for_role(role)) | set(ROLE_OPTIONAL_SCOPES.get(role, []))
        scopes = rec.get("scopes") or scopes_for_role(role)
        scopes = [s for s in scopes if s in allowed] if "*" not in scopes_for_role(role) else scopes
        principal = {
            "type": "api_key", "id": rec["id"], "key_id": rec["id"], "name": rec.get("name", "api-key"),
            "email": rec.get("name", "api-key"), "role": role, "scopes": scopes,
            "source": "chatgpt" if rec.get("source") in ("ai", "chatgpt") or role == "AI_OPERATOR" else "api",
            "rate_limit": int(rec.get("rate_limit_per_min") or DEFAULT_LIMIT_KEY), "ip": ip,
        }
        rl = rate_limit(f"key:{rec['id']}", principal["rate_limit"])
        request.state.rate = rl
        request.state.principal = principal
        await api_keys_col.update_one({"id": rec["id"]}, {"$set": {"last_used_at": now_iso(), "last_ip": ip}, "$inc": {"uses": 1, "request_count": 1}})
        return principal
    # 2) JWT
    if creds and creds.credentials:
        from auth import decode_token
        payload = decode_token(creds.credentials)
        if not payload:
            raise err(401, "AUTH_REQUIRED", "Sessione non valida o scaduta")
        role = normalize_role(payload.get("role") or payload.get("ruolo"))
        user = await admins_col.find_one({"id": payload.get("sub")}, {"_id": 0, "ruolo": 1, "role": 1, "active": 1})
        if user is not None:
            if user.get("active") is False:
                raise err(401, "AUTH_REQUIRED", "Utente disattivato")
            role = normalize_role(user.get("role") or user.get("ruolo"))
        principal = {
            "type": "user", "id": payload.get("sub"), "email": payload.get("email"),
            "name": payload.get("email"), "role": role, "scopes": scopes_for_role(role),
            "source": "manual", "rate_limit": DEFAULT_LIMIT_USER, "ip": ip,
        }
        request.state.rate = rate_limit(f"user:{principal['id']}", DEFAULT_LIMIT_USER)
        request.state.principal = principal
        return principal
    raise err(401, "AUTH_REQUIRED", "Autenticazione richiesta (Bearer JWT o X-API-Key)")


def require(*scopes: str):
    """Dependency factory: principal must own ALL given scopes. API keys can never exercise CRITICAL scopes."""
    async def _dep(principal: dict = Depends(resolve_principal)):
        if principal.get("type") == "api_key":
            crit = [s for s in scopes if s in CRITICAL_SCOPES]
            if crit:
                raise err(403, "CRITICAL_ACTION_BLOCKED", "Operazione critica non consentita alle API key (solo amministratore umano)", scopes=crit)
        missing = [s for s in scopes if not has_scope(principal, s)]
        if missing:
            raise err(403, "INSUFFICIENT_SCOPE", "Permessi insufficienti", missing_scopes=missing, role=principal.get("role"))
        return principal
    return _dep


def actor_of(principal: dict) -> str:
    return principal.get("email") or principal.get("name") or principal.get("id") or "system"


def request_id_of(request: Optional[Request]) -> str:
    if request is None:
        return str(uuid.uuid4())
    rid = getattr(request.state, "request_id", None)
    if not rid:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = rid
    return rid


# ---------------- WEBHOOK SIGNING ----------------
def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    msg = timestamp.encode("utf-8") + b"." + body
    return "sha256=" + hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_payload(secret, timestamp, body), signature or "")
