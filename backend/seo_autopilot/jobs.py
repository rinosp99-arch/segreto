"""Scheduler registration (rule 19) — reuses the in-process scheduler of v1_jobs (background only, never on public request paths).
Importing this module registers the jobs; server.py imports it before ensure_job_docs()."""
from v1_jobs import job

from . import engine, mode


@job("seo_ap_tech_health", 6 * 3600, "SEO Autopilot: crawl tecnico + rendering sample + audit adult (READ_ONLY)")
async def j_tech():
    r = await engine.run_tech_health()
    return _compact(r)


@job("seo_ap_gsc_sync", 12 * 3600, "SEO Autopilot: import Search Console -> snapshot storici (READ_ONLY)")
async def j_gsc():
    r = await engine.run_gsc_sync()
    return _compact(r)


@job("seo_ap_daily_analysis", 24 * 3600, "SEO Autopilot: analisi SEO profonda giornaliera (keyword, cluster, opportunità, mappa, planner) (READ_ONLY)")
async def j_daily():
    r = await engine.run_daily()
    return _compact(r)


@job("seo_ap_weekly_learning", 7 * 24 * 3600, "SEO Autopilot: apprendimento settimanale (trend 7v7 / 28v28) (READ_ONLY)")
async def j_weekly():
    r = await engine.run_weekly()
    return _compact(r)


@job("seo_ap_execute", 24 * 3600, "SEO Autopilot FULL: pubblica bozze/proposte, genera 1 articolo/giorno, internal linking (solo FULL)")
async def j_execute():
    from . import executor
    r = await executor.run_execution("scheduler")
    return r if isinstance(r, dict) else {"result": str(r)[:200]}


@job("seo_ap_maintenance", 12 * 3600, "SEO Autopilot FULL: safe-fix + internal linking + sitemap (solo FULL)")
async def j_maintenance():
    from . import executor
    r = await executor.run_maintenance("scheduler")
    return r if isinstance(r, dict) else {"result": str(r)[:200]}


def _compact(r: dict) -> dict:
    if not isinstance(r, dict):
        return {"result": str(r)[:200]}
    return {"mode": mode.current_mode(), "run_id": r.get("id"), "status": r.get("status"), "PUBLIC_MUTATIONS": r.get("public_mutations"), "errors": len(r.get("errors") or []),
            "summary": {k: v for k, v in (r.get("summary") or {}).items() if k in ("gsc", "tech", "render", "keywords", "clusters", "opportunities", "page_map", "proposals", "backlog", "PUBLIC_MUTATIONS")}}
