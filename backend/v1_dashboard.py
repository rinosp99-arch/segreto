"""SUPER API v1 - ADMIN DASHBOARD aggregate (one call for the 'Motore API' page)."""
from datetime import datetime, timedelta, timezone
from typing import Dict
from fastapi import APIRouter, Depends

from database import (
    db, models_col, alerts_col, jobs_col, seo_issues_col, versions_col, ai_actions_col, health_col, api_keys_col, events_col, now_iso,
)
from v1_security import require
from v1_models import validate_model
from v1_tracking import build_match, funnel_for, model_kpis

dashboard_router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


@dashboard_router.get("/overview")
async def overview(range: str = "7g", principal=Depends(require("analytics:read"))):
    match = build_match(range)
    try:
        await db.command("ping")
        db_ok = True
    except Exception:
        db_ok = False
    health = await health_col.find_one({}, {"_id": 0, "overall": 1, "timestamp": 1, "checks": 1, "actions": 1}, sort=[("timestamp", -1)])
    f = await funnel_for(match)
    it = await funnel_for({**match, "geo.country": "IT"})
    seo_counts = {"SAFE_AUTO_FIX": 0, "REVIEW_REQUIRED": 0, "CRITICAL": 0}
    async for r in seo_issues_col.aggregate([{"$match": {"status": "open"}}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        seo_counts[r["_id"]] = r["n"]
    seo_score = max(0, 100 - seo_counts["SAFE_AUTO_FIX"] - seo_counts["REVIEW_REQUIRED"] * 3 - seo_counts["CRITICAL"] * 10)
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    autofixes = await versions_col.find({"source": {"$in": ["autofix", "ai"]}, "meta.code": {"$exists": True}, "timestamp": {"$gte": since}}, {"_id": 0, "before": 0, "after": 0}).sort("timestamp", -1).to_list(15)
    autofix_count = await versions_col.count_documents({"source": "autofix", "timestamp": {"$gte": since}})
    alerts = await alerts_col.find({"stato": {"$in": ["open", "acknowledged"]}}, {"_id": 0}).sort("created_at", -1).to_list(20)
    versions = await versions_col.find({}, {"_id": 0, "before": 0, "after": 0}).sort("timestamp", -1).to_list(15)
    ai_actions = await ai_actions_col.find({}, {"_id": 0}).sort("timestamp", -1).to_list(15)
    jobs = await jobs_col.find({}, {"_id": 0}).sort("name", 1).to_list(50)
    keys = await api_keys_col.count_documents({"active": True})
    top = []
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1, "nome_artistico": 1, "foto_card": 1}):
        k = await model_kpis(m["id"], match)
        top.append({**m, **k})
    top.sort(key=lambda r: (r["onlyfans_clicks"], r["visits"]), reverse=True)
    counts: Dict[str, int] = {}
    async for d in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}):
        st = validate_model(d)["status"]
        counts[st] = counts.get(st, 0) + 1
    events_24h = await events_col.count_documents({"timestamp": {"$gte": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}})
    return {
        "range": range, "generated_at": now_iso(),
        "api_status": {"api": "online", "database": db_ok, "health": (health or {}).get("overall", "n/d"), "health_at": (health or {}).get("timestamp"), "checks": (health or {}).get("checks", []), "active_api_keys": keys, "events_24h": events_24h},
        "seo_health": {"score": seo_score, "open": seo_counts},
        "traffic": f, "italian_traffic": {**it, "share": round(it["steps"][1]["value"] / (f["steps"][1]["value"] or 1) * 100, 1)},
        "onlyfans_clicks": f["steps"][4]["value"], "conversion_rate": f["conversion_rate"],
        "top_models": top[:8], "models_by_status": counts,
        "seo_issues": seo_counts, "auto_fixes": {"count_7d": autofix_count, "recent": autofixes},
        "alerts": alerts, "rollback": {"recent_versions": versions}, "ai_actions": ai_actions, "background_jobs": jobs,
    }
