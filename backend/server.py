import os
import json
import uuid
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.cors import CORSMiddleware

from database import ensure_indexes, idempotency_col, now_dt, now_iso
from routes_public import public_router
from routes_admin import admin_router
from routes_analytics import analytics_router
from routes_seo import seo_router
from routes_integrations import integrations_router
from seed_data import seed_all
from auth import decode_token

# SUPER API v1
from v1_security import normalize_role, WRITE_BLOCKED_LEGACY_ROLES
from v1_models import models_router
from v1_media import media_router, model_media_router
from v1_seo import seo_router as seo_v1_router
from v1_tracking import tracking_router
from v1_landings import landings_router, public_landings_router
from v1_experiments import experiments_router, public_experiments_router
from v1_health import health_router, alerts_router
from v1_jobs import jobs_router, ensure_job_docs, start_scheduler, stop_scheduler
from v1_config import config_router, webhooks_router, backup_router, auth_router, versions_router, get_config
from v1_ai import ai_router
from v1_dashboard import dashboard_router

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("lato-segreto")

OPENAPI_TAGS = [
    {"name": "AI / ChatGPT", "description": "Endpoint AI-friendly: body piatti, riferimenti naturali (id|slug|nome), risposte {ok, summary, data, next_steps}."},
    {"name": "Models", "description": "Gestione modelle: CRUD, validate, publish/unpublish, archive/restore, duplicate, feature in Home."},
    {"name": "Media", "description": "Upload (multipart/URL/base64), varianti web/mobile/thumb/poster, ALT, SEO filename, associazione slot."},
    {"name": "SEO", "description": "SEO Engine + Autopilot: issues (SAFE_AUTO_FIX / REVIEW_REQUIRED / CRITICAL), audit, fix, fix-all, sitemap manager, redirect, internal linking."},
    {"name": "Tracking & Analytics", "description": "Eventi canonici, Italy Engine (country/region/city/device/source), funnel VISIT→MODEL VIEW→SECRET→CTA→ONLYFANS."},
    {"name": "Landings", "description": "Landing page engine (dati; rotta pubblica dietro feature flag)."},
    {"name": "A/B Testing", "description": "Esperimenti con assegnazione deterministica e z-test: nessun vincitore automatico."},
    {"name": "Health & Self-healing", "description": "Controlli periodici, auto-fix sicuri, alert, rollback su regressione."},
    {"name": "Background Jobs", "description": "Scheduler in-process: SEO scan, link scan, media check, health, sitemap, analytics sync, anomalie, backup."},
    {"name": "Versions, Rollback & Audit", "description": "Storico before/after di ogni modifica importante, rollback, audit log con request_id."},
    {"name": "Config & Flags", "description": "Configuration center + feature flags (dominio .it, SSR, GA4, GSC predisposti ma OFF)."},
    {"name": "Webhooks", "description": "Webhook firmati HMAC-SHA256 per eventi interni."},
    {"name": "Backup & Restore", "description": "Snapshot su object storage, restore con dry-run e backup di sicurezza."},
    {"name": "Auth, API Keys & Users", "description": "API key con ruoli/scopes (SUPER_ADMIN, ADMIN, AI_OPERATOR, SEO_MANAGER, CONTENT_MANAGER, ANALYST, READ_ONLY)."},
    {"name": "Dashboard", "description": "Aggregato per il pannello admin 'Motore API'."},
]

app = FastAPI(
    title="LATO SEGRETO SUPER API",
    version="1.0.0",
    description="Motore API-first dietro LATO SEGRETO. Autenticazione: Bearer JWT (admin) oppure header X-API-Key. Idempotenza: header Idempotency-Key. Ogni risposta include X-Request-ID.",
    docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json", openapi_tags=OPENAPI_TAGS,
)


@app.get("/api/")
async def root():
    return {"message": "LATO SEGRETO API attiva", "v1": "/api/v1", "docs": "/api/docs"}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1")
async def v1_root():
    return {"name": "LATO SEGRETO SUPER API", "version": "1.0.0", "docs": "/api/docs", "openapi": "/api/openapi.json", "ai": "/api/v1/ai/capabilities"}


# Routers (legacy: untouched)
app.include_router(public_router)
app.include_router(admin_router)
app.include_router(analytics_router)
app.include_router(seo_router)
app.include_router(integrations_router)
# SUPER API v1
for r in (ai_router, models_router, media_router, model_media_router, seo_v1_router, tracking_router, landings_router, public_landings_router,
          experiments_router, public_experiments_router, health_router, alerts_router, jobs_router, config_router, webhooks_router,
          backup_router, auth_router, versions_router, dashboard_router):
    app.include_router(r)


# ---------------- MIDDLEWARE ----------------
@app.middleware("http")
async def request_context(request: Request, call_next):
    """Request-ID, security headers, legacy-admin role guard, idempotency for /api/v1 writes."""
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = rid
    path = request.url.path
    method = request.method.upper()

    # Legacy admin panel: read-only roles cannot write
    if path.startswith("/api/admin") and method in ("POST", "PUT", "PATCH", "DELETE") and not path.endswith("/login"):
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            payload = decode_token(auth.split(" ", 1)[1].strip())
            if payload and normalize_role(payload.get("role") or payload.get("ruolo")) in WRITE_BLOCKED_LEGACY_ROLES:
                return JSONResponse(status_code=403, content={"detail": "Il tuo ruolo è in sola lettura"}, headers={"X-Request-ID": rid})

    # Idempotency (v1 writes)
    idem_key = request.headers.get("Idempotency-Key")
    idem_doc_key = None
    if idem_key and path.startswith("/api/v1") and method in ("POST", "PATCH", "PUT"):
        principal_hint = request.headers.get("X-API-Key") or request.headers.get("authorization") or (request.client.host if request.client else "")
        import hashlib
        idem_doc_key = {"key": idem_key, "principal": hashlib.sha256(principal_hint.encode()).hexdigest()[:24], "path": path}
        cached = await idempotency_col.find_one(idem_doc_key, {"_id": 0})
        if cached:
            return Response(content=cached["body"], status_code=cached["status"], media_type="application/json",
                            headers={"X-Request-ID": cached.get("request_id", rid), "Idempotent-Replayed": "true"})

    response = await call_next(request)

    if idem_doc_key and 200 <= response.status_code < 500:
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            await idempotency_col.insert_one({**idem_doc_key, "status": response.status_code, "body": body.decode("utf-8", "ignore"), "request_id": rid, "created_dt": now_dt(), "created_at": now_iso()})
        except Exception:
            pass
        headers = dict(response.headers)
        headers.pop("content-length", None)
        response = Response(content=body, status_code=response.status_code, headers=headers, media_type=response.media_type)

    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Idempotent-Replayed", "Retry-After"],
)


# OpenAPI security schemes
_orig_openapi = app.openapi


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = _orig_openapi()
    comps = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    comps["ApiKeyAuth"] = {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    comps["BearerAuth"] = {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    schema["security"] = [{"ApiKeyAuth": []}, {"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


@app.on_event("startup")
async def startup():
    try:
        await ensure_indexes()
        await seed_all()
        await get_config()
        await ensure_job_docs()
        start_scheduler()
        logger.info("Startup completo: indici + seed + config + scheduler")
    except Exception as e:
        logger.error(f"Errore startup: {e}")


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()
