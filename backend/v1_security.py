"""SUPER API security layer.

- Principals: admin users (JWT, roles) or API keys (X-API-Key, hashed, scoped).
- Roles -> scopes mapping (granular).
- `require(*scopes)` FastAPI dependency (JWT OR API key).
- Sliding-window rate limiting per principal / IP.
- Request-ID + idempotency middleware helpers.
- HMAC signing helpers for webhooks.
"""
import os
import hmac
import time
import uuid
import hashlib
import secrets
from typing import Optional, List
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader

from database import api_keys_col, admins_col, now_iso
from auth import decode_token

bearer_scheme = HTTPBearer(auto_error=False)
apikey_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

# ---------------- ROLES & SCOPES ----------------
ALL_SCOPES = [
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

ROLE_SCOPES = {
    "SUPER_ADMIN": ["*"],
    "ADMIN": [s for s in ALL_SCOPES if s not in ("keys:manage", "users:manage", "backup:manage")],
    "AI_OPERATOR": [
        "models:read", "models:write", "models:publish", "media:read", "media:write",
        "seo:read", "seo:write", "seo:autofix", "analytics:read", "landings:read",
        "landings:write", "landings:publish", "experiments:read", "health:read",
        "alerts:read", "versions:read", "versions:rollback", "jobs:read", "ai:execute", "config:read",
    ],
    "SEO_MANAGER": [
        "models:read", "media:read", "seo:read", "seo:write", "seo:autofix", "analytics:read",
        "landings:read", "landings:write", "versions:read", "versions:rollback", "health:read", "alerts:read", "jobs:read", "config:read",
    ],
    "CONTENT_MANAGER": [
        "models:read", "models:write", "models:publish", "media:read", "media:write",
        "landings:read", "landings:write", "versions:read", "analytics:read", "health:read", "alerts:read", "config:read",
    ],
    "ANALYST": ["models:read", "analytics:read", "experiments:read", "health:read", "alerts:read", "jobs:read", "seo:read", "landings:read", "config:read"],
    "READ_ONLY": ["models:read", "media:read", "seo:read", "analytics:read", "landings:read", "experiments:read", "health:read", "alerts:read", "jobs:read", "versions:read", "config:read"],
}
ROLES = list(ROLE_SCOPES.keys())
WRITE_BLOCKED_LEGACY_ROLES = {"ANALYST", "READ_ONLY"}


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


def has_scope(principal: dict, scope: str) -> bool:
    sc = principal.get("scopes") or []
    return "*" in sc or scope in sc


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


def rate_limit(bucket_id: str, limit_per_min: int):
    now = time.time()
    window = 60.0
    hits = _buckets.get(bucket_id)
    if hits is None:
        hits = []
    hits = [t for t in hits if now - t < window]
    if len(hits) >= limit_per_min:
        retry = int(window - (now - hits[0])) + 1
        raise HTTPException(status_code=429, detail="Limite richieste superato. Riprova tra poco.",
                            headers={"Retry-After": str(max(1, retry))})
    hits.append(now)
    _buckets[bucket_id] = hits
    # opportunistic cleanup
    if len(_buckets) > 5000:
        for k in list(_buckets.keys())[:1000]:
            if not _buckets[k] or now - _buckets[k][-1] > window:
                _buckets.pop(k, None)


# ---------------- PRINCIPAL RESOLUTION ----------------
async def resolve_principal(request: Request,
                            creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
                            api_key: Optional[str] = Depends(apikey_scheme)) -> dict:
    # 1) API key
    if api_key:
        rec = await api_keys_col.find_one({"key_hash": hash_key(api_key)}, {"_id": 0})
        if not rec or not rec.get("active", True):
            raise HTTPException(status_code=401, detail="API key non valida o disattivata")
        if rec.get("expires_at") and rec["expires_at"] < now_iso():
            raise HTTPException(status_code=401, detail="API key scaduta")
        allow = rec.get("ip_allowlist") or []
        ip = request.client.host if request.client else ""
        if allow and ip not in allow:
            raise HTTPException(status_code=403, detail="IP non autorizzato per questa API key")
        role = normalize_role(rec.get("role"))
        scopes = rec.get("scopes") or scopes_for_role(role)
        # scopes can only restrict the role
        role_sc = scopes_for_role(role)
        scopes = [s for s in scopes if s in role_sc] if "*" not in role_sc else scopes
        principal = {
            "type": "api_key", "id": rec["id"], "name": rec.get("name", "api-key"),
            "email": rec.get("name", "api-key"), "role": role, "scopes": scopes,
            "source": "ai" if role == "AI_OPERATOR" or rec.get("source") == "ai" else "api",
            "rate_limit": int(rec.get("rate_limit_per_min") or DEFAULT_LIMIT_KEY),
        }
        rate_limit(f"key:{rec['id']}", principal["rate_limit"])
        await api_keys_col.update_one({"id": rec["id"]}, {"$set": {"last_used_at": now_iso()}, "$inc": {"uses": 1}})
        request.state.principal = principal
        return principal
    # 2) JWT
    if creds and creds.credentials:
        payload = decode_token(creds.credentials)
        if not payload:
            raise HTTPException(status_code=401, detail="Sessione non valida o scaduta")
        role = normalize_role(payload.get("role") or payload.get("ruolo"))
        # refresh role from DB (role changes take effect immediately)
        user = await admins_col.find_one({"id": payload.get("sub")}, {"_id": 0, "ruolo": 1, "role": 1, "active": 1})
        if user is not None:
            if user.get("active") is False:
                raise HTTPException(status_code=401, detail="Utente disattivato")
            role = normalize_role(user.get("role") or user.get("ruolo"))
        principal = {
            "type": "user", "id": payload.get("sub"), "email": payload.get("email"),
            "name": payload.get("email"), "role": role, "scopes": scopes_for_role(role),
            "source": "manual", "rate_limit": DEFAULT_LIMIT_USER,
        }
        rate_limit(f"user:{principal['id']}", DEFAULT_LIMIT_USER)
        request.state.principal = principal
        return principal
    raise HTTPException(status_code=401, detail="Autenticazione richiesta (Bearer JWT o X-API-Key)")


def require(*scopes: str):
    """Dependency factory: principal must own ALL given scopes."""
    async def _dep(principal: dict = Depends(resolve_principal)):
        missing = [s for s in scopes if not has_scope(principal, s)]
        if missing:
            raise HTTPException(status_code=403, detail={
                "message": "Permessi insufficienti", "missing_scopes": missing, "role": principal.get("role"),
            })
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
