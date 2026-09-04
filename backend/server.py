import os
import logging
from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from database import ensure_indexes
from routes_public import public_router
from routes_admin import admin_router
from routes_analytics import analytics_router
from routes_seo import seo_router
from routes_integrations import integrations_router
from seed_data import seed_all

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("lato-segreto")

app = FastAPI(title="LATO SEGRETO API")


@app.get("/api/")
async def root():
    return {"message": "LATO SEGRETO API attiva"}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Routers
app.include_router(public_router)
app.include_router(admin_router)
app.include_router(analytics_router)
app.include_router(seo_router)
app.include_router(integrations_router)

# Security headers
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
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
)


@app.on_event("startup")
async def startup():
    try:
        await ensure_indexes()
        await seed_all()
        logger.info("Startup completo: indici + seed")
    except Exception as e:
        logger.error(f"Errore startup: {e}")


@app.on_event("shutdown")
async def shutdown():
    pass
