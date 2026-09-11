"""SUPER API v1 - BACKGROUND WORKERS + SCHEDULER (in-process asyncio, single worker).

Jobs: health_check, seo_scan, broken_link_scan, media_check, sitemap_verify, analytics_sync,
anomaly_detection, backup, alerts_digest. State persisted in `jobs` / `job_runs`.
"""
import os
import time
import uuid
import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Callable, Awaitable, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from database import jobs_col, job_runs_col, events_col, config_col, now_iso, serialize_doc
from v1_security import require, actor_of, request_id_of
from v1_versioning import audit_log

logger = logging.getLogger("lato-segreto.jobs")
jobs_router = APIRouter(prefix="/api/v1/jobs", tags=["Background Jobs"])

JOBS: Dict[str, Dict[str, Any]] = {}
_scheduler_task: Optional[asyncio.Task] = None
_running: Dict[str, bool] = {}


def job(name: str, interval_s: int, description: str):
    def deco(fn: Callable[[], Awaitable[dict]]):
        JOBS[name] = {"fn": fn, "interval_s": interval_s, "description": description}
        return fn
    return deco


# ---------------- JOB IMPLEMENTATIONS ----------------
@job("health_check", 600, "Health check completo + self-healing (fix sicuri)")
async def j_health():
    from v1_health import run_health_checks
    r = await run_health_checks()
    return {"overall": r["overall"], "actions": r["actions"]}


@job("seo_scan", 3600, "Audit SEO completo + Autopilot (solo fix SAFE)")
async def j_seo():
    from v1_seo import run_audit, apply_safe_fixes
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0}) or {}
    ap = cfg.get("seo_autopilot") or {}
    res = await run_audit()
    out = {"audit": res}
    if ap.get("enabled", True) and ap.get("auto_apply_safe", True) and res["counts"]["SAFE_AUTO_FIX"]:
        fx = await apply_safe_fixes("seo-autopilot", None, None, None, False, source="autofix")
        out["autofix"] = {"applied": fx["applied"], "skipped": fx["skipped"]}
    from v1_health import raise_alert, resolve_alerts
    if res["counts"]["CRITICAL"]:
        await raise_alert("seo_critical", "Issue SEO critiche", f"{res['counts']['CRITICAL']} issue CRITICAL aperte: intervento manuale", "critical", "seo", None, "seo_critical", {"counts": res["counts"], "source": "seo_scan"})
    else:
        await resolve_alerts("seo_critical")   # reconciliation: condition gone -> alert resolved (was never closed before)
    return out


@job("broken_link_scan", 6 * 3600, "Scansione link (OnlyFans, social, interni)")
async def j_links():
    from v1_health import check_onlyfans_links, check_links, raise_alert, resolve_alerts
    of = await check_onlyfans_links()
    so = await check_links()
    if of["status"] == "fail":
        await raise_alert("onlyfans_links", "Link OnlyFans non validi", of["detail"], "critical", "model", None, "onlyfans_links", {"items": of["items"]})
    else:
        await resolve_alerts("onlyfans_links")
    return {"onlyfans": of["detail"], "social": so["detail"]}


@job("media_check", 6 * 3600, "Verifica raggiungibilità media")
async def j_media():
    from v1_health import check_media, raise_alert, resolve_alerts
    r = await check_media(sample=40)
    if r["status"] == "fail":
        await raise_alert("media_missing", "Media non raggiungibili", r["detail"], "critical", "media", None, "media_missing", {"missing": r["missing"]})
    else:
        await resolve_alerts("media_missing")
    return {"detail": r["detail"], "missing": len(r["missing"])}


@job("sitemap_verify", 6 * 3600, "Verifica coerenza sitemap")
async def j_sitemap():
    from v1_seo import sitemap_entries
    entries = await sitemap_entries()
    dup = len(entries) - len({e["path"] for e in entries})
    if dup:
        from v1_health import raise_alert
        await raise_alert("sitemap_dup", "Sitemap con URL duplicati", f"{dup} duplicati", "warning", "seo", None, "sitemap_dup")
    return {"entries": len(entries), "duplicates": dup}


@job("google_sitemap_sync", 3600, "Search Console: re-invio sitemap solo se cambiata/dirty (debounce, quota-safe)")
async def j_google_sitemap_sync():
    from google_search.service import sitemap_sync, configured
    if not configured():
        return {"skipped": "Search Console non configurata"}
    r = await sitemap_sync(force=False)
    return {k: r.get(k) for k in ("submitted", "would_submit", "reason", "skipped_reason", "urls", "error")}


@job("analytics_sync", 3600, "Aggregazione giornaliera analytics (Italy Engine)")
async def j_analytics():
    from v1_tracking import aggregate_day
    today = datetime.now(timezone.utc).date()
    n = 0
    for d in (today, today - timedelta(days=1)):
        n += await aggregate_day(d.isoformat())
    return {"rows": n}


@job("anomaly_detection", 3600, "Anomalie traffico e conversioni (ultime 24h vs media 7 giorni)")
async def j_anomaly():
    from v1_health import raise_alert, resolve_alerts
    now = datetime.now(timezone.utc)
    last24 = (now - timedelta(hours=24)).isoformat()
    prev7 = (now - timedelta(days=8)).isoformat()
    async def cnt(ev, legacy, since, until=None):
        q = {"timestamp": {"$gte": since, **({"$lt": until} if until else {})}, "$or": [{"event": ev}, {"tipo": legacy}]}
        return await events_col.count_documents(q)
    v24 = await cnt("model_view", "page_view", last24)
    v7 = await cnt("model_view", "page_view", prev7, last24) / 7
    c24 = await cnt("onlyfans_click", "of_click", last24)
    c7 = await cnt("onlyfans_click", "of_click", prev7, last24) / 7
    out = {"views_24h": v24, "views_avg7": round(v7, 1), "clicks_24h": c24, "clicks_avg7": round(c7, 1), "anomalies": []}
    if v7 >= 50 and v24 < v7 * 0.4:
        out["anomalies"].append("traffic_drop")
        await raise_alert("traffic_anomaly", "Calo di traffico", f"Visite 24h {v24} vs media {round(v7)} (−{round((1 - v24 / v7) * 100)}%)", "warning", "analytics", None, "traffic_drop")
    else:
        await resolve_alerts("traffic_drop")
    if c7 >= 10 and c24 < c7 * 0.3:
        out["anomalies"].append("conversion_drop")
        await raise_alert("conversion_anomaly", "Calo conversioni OnlyFans", f"Click 24h {c24} vs media {round(c7)}", "warning", "analytics", None, "conversion_drop")
    else:
        await resolve_alerts("conversion_drop")
    if v7 >= 50 and v24 > v7 * 3:
        out["anomalies"].append("traffic_spike")
        await raise_alert("traffic_anomaly", "Picco di traffico", f"Visite 24h {v24} vs media {round(v7)}", "info", "analytics", None, "traffic_spike")
    return out


@job("backup", 24 * 3600, "Backup completo su object storage")
async def j_backup():
    from v1_config import create_backup, get_config
    cfg = await get_config()
    if not (cfg.get("backups") or {}).get("enabled", True):
        return {"skipped": True}
    r = await create_backup("scheduler", bool((cfg.get("backups") or {}).get("include_events")), "scheduled")
    return {"backup_id": r["id"], "size": r["size"]}


@job("alerts_digest", 24 * 3600, "Riepilogo giornaliero (usato da /ai/daily-summary)")
async def j_digest():
    from v1_ai import build_daily_summary
    s = await build_daily_summary()
    await config_col.update_one({"id": "daily_summary"}, {"$set": {"id": "daily_summary", "summary": s, "updated_at": now_iso()}}, upsert=True)
    return {"ok": True}


# ---------------- RUNNER ----------------
async def run_job(name: str, trigger: str = "scheduler", actor: str = "scheduler") -> dict:
    if name not in JOBS:
        raise HTTPException(status_code=404, detail=f"Job '{name}' inesistente")
    if _running.get(name):
        return {"job": name, "status": "already_running"}
    _running[name] = True
    started = time.time()
    run = {"id": str(uuid.uuid4()), "job": name, "trigger": trigger, "actor": actor, "started_at": now_iso(), "status": "running"}
    await job_runs_col.insert_one(dict(run))
    status, result, error = "ok", None, None
    try:
        result = await asyncio.wait_for(JOBS[name]["fn"](), timeout=280)
    except Exception as e:
        status, error = "error", f"{e}\n{traceback.format_exc()[-800:]}"
        logger.error(f"job {name} failed: {e}")
        try:
            from v1_health import raise_alert
            await raise_alert("job_failed", f"Job fallito: {name}", str(e), "critical", "job", name, f"job_failed:{name}")
            from v1_config import emit_event
            await emit_event("job.failed", {"job": name, "error": str(e)})
        except Exception:
            pass
    finally:
        _running[name] = False
    dur = round((time.time() - started) * 1000)
    await job_runs_col.update_one({"id": run["id"]}, {"$set": {"status": status, "result": result, "error": error, "duration_ms": dur, "ended_at": now_iso()}})
    await jobs_col.update_one({"name": name}, {"$set": {"last_run": now_iso(), "last_run_ts": time.time(), "last_status": status, "last_duration_ms": dur, "last_error": (error or "")[:300], "last_result": result}, "$inc": {"runs": 1, "errors": 1 if status == "error" else 0}}, upsert=True)
    if status == "ok":
        try:
            from v1_health import resolve_alerts
            await resolve_alerts(f"job_failed:{name}")
        except Exception:
            pass
    old = await job_runs_col.find({"job": name}, {"_id": 0, "id": 1}).sort("started_at", -1).skip(100).to_list(1000)
    if old:
        await job_runs_col.delete_many({"id": {"$in": [o["id"] for o in old]}})
    return {"job": name, "status": status, "duration_ms": dur, "result": result, "error": (error or "")[:300] or None}


async def ensure_job_docs():
    for name, spec in JOBS.items():
        await jobs_col.update_one({"name": name}, {"$setOnInsert": {"name": name, "enabled": True, "runs": 0, "errors": 0, "last_run": None, "last_run_ts": None, "last_status": None, "created_at": now_iso()},
                                                  "$set": {"interval_s": spec["interval_s"], "description": spec["description"]}}, upsert=True)


async def _scheduler_loop():
    await asyncio.sleep(45)  # let the app warm up
    logger.info("Scheduler avviato")
    while True:
        try:
            cfg = await config_col.find_one({"id": "global"}, {"_id": 0, "jobs": 1, "flags": 1}) or {}
            if (cfg.get("jobs") or {}).get("enabled", True):
                now = time.time()
                async for j in jobs_col.find({}, {"_id": 0}):
                    if not j.get("enabled", True) or j["name"] not in JOBS:
                        continue
                    last = j.get("last_run_ts") or 0
                    if now - last >= j.get("interval_s", JOBS[j["name"]]["interval_s"]):
                        await run_job(j["name"])
        except Exception as e:
            logger.error(f"scheduler tick error: {e}")
        await asyncio.sleep(30)


def start_scheduler():
    global _scheduler_task
    if os.environ.get("ENABLE_SCHEDULER", "true").lower() not in ("1", "true", "yes"):
        logger.info("Scheduler disabilitato via env")
        return
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop())


def stop_scheduler():
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()


# ---------------- ROUTES ----------------
@jobs_router.get("")
async def list_jobs(principal=Depends(require("jobs:read"))):
    items = await jobs_col.find({}, {"_id": 0}).sort("name", 1).to_list(100)
    for it in items:
        it["running"] = bool(_running.get(it["name"]))
        if it.get("last_run_ts"):
            it["next_run_in_s"] = max(0, int(it["interval_s"] - (time.time() - it["last_run_ts"])))
    return {"items": items, "scheduler_running": bool(_scheduler_task and not _scheduler_task.done())}


@jobs_router.post("/{name}/run")
async def run_now(name: str, request: Request, principal=Depends(require("jobs:run"))):
    res = await run_job(name, trigger="manual", actor=actor_of(principal))
    await audit_log(actor_of(principal), "job_run", "job", name, {"status": res.get("status")}, request_id_of(request), principal.get("source", "manual"))
    return res


class JobPatch(BaseModel):
    enabled: Optional[bool] = None
    interval_s: Optional[int] = None


@jobs_router.patch("/{name}")
async def patch_job(name: str, body: JobPatch, principal=Depends(require("jobs:run"))):
    if name not in JOBS:
        raise HTTPException(status_code=404, detail="Job inesistente")
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "interval_s" in upd:
        upd["interval_s"] = max(60, int(upd["interval_s"]))
    await jobs_col.update_one({"name": name}, {"$set": upd})
    return serialize_doc(await jobs_col.find_one({"name": name}, {"_id": 0}))


@jobs_router.get("/{name}/runs")
async def job_runs(name: str, limit: int = 20, principal=Depends(require("jobs:read"))):
    items = await job_runs_col.find({"job": name}, {"_id": 0}).sort("started_at", -1).to_list(limit)
    return {"items": items}
