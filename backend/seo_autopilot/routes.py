"""Admin API: /api/admin/seo-autopilot/* (admin JWT). Read endpoints + 'run now' (background task) + the FULL guard demo.
Nothing here can change a public resource: even the 'execute' endpoint exists only to PROVE the guard (it always fails outside FULL)."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_admin

from . import engine, mode, store, render_audit, executor

router = APIRouter(prefix="/api/admin/seo-autopilot", tags=["SEO Autopilot (READ_ONLY)"])
_bg: dict = {"task": None, "kind": None}
_exec_bg: dict = {"task": None, "kind": None}


# ================================================================= Phase 15: EXECUTION LAYER (FULL / production)
@router.get("/production-status")
async def production_status(admin=Depends(get_current_admin)):
    st = await executor.production_status()
    st["executing"] = bool(_exec_bg["task"] and not _exec_bg["task"].done())
    st["executing_kind"] = _exec_bg["kind"] if st["executing"] else None
    return st


@router.post("/activate")
async def activate(body: Optional[dict] = None, admin=Depends(get_current_admin)):
    """Activate SEO Autopilot in FULL/production. DB-driven (no env change). Idempotent."""
    body = body or {}
    patch = {
        "seo_autopilot_enabled": True,
        "seo_autopilot_mode": "FULL",
        "seo_auto_publish": bool(body.get("seo_auto_publish", True)),
        "auto_publish_articles": bool(body.get("auto_publish_articles", True)),
        "seo_max_articles_per_day": int(body.get("seo_max_articles_per_day", 1)),
        "seo_target_country": body.get("seo_target_country", "IT"),
        "seo_language": body.get("seo_language", "it"),
    }
    s = await executor.set_settings(patch)
    await executor.enable_public_landings()
    return {"activated": True, "settings": s}


@router.post("/deactivate")
async def deactivate(admin=Depends(get_current_admin)):
    s = await executor.set_settings({"seo_autopilot_enabled": False, "seo_autopilot_mode": "READ_ONLY", "seo_auto_publish": False})
    return {"activated": False, "settings": s}


@router.post("/execute-now")
async def execute_now(force: bool = False, admin=Depends(get_current_admin)):
    if not force and not await executor.full_enabled():
        raise HTTPException(409, "SEO Autopilot non è in FULL: usa /activate prima o passa force=true")
    if _exec_bg["task"] and not _exec_bg["task"].done():
        return {"started": False, "status": "already_running", "kind": _exec_bg["kind"]}
    _exec_bg["task"] = asyncio.create_task(executor.run_execution("admin", force=force))
    _exec_bg["kind"] = "execution"
    return {"started": True, "kind": "execution"}


@router.post("/maintenance-now")
async def maintenance_now(admin=Depends(get_current_admin)):
    if _exec_bg["task"] and not _exec_bg["task"].done():
        return {"started": False, "status": "already_running", "kind": _exec_bg["kind"]}
    _exec_bg["task"] = asyncio.create_task(executor.run_maintenance("admin"))
    _exec_bg["kind"] = "maintenance"
    return {"started": True, "kind": "maintenance"}


@router.post("/publish-proposals")
async def publish_proposals(dry_run: bool = False, admin=Depends(get_current_admin)):
    return await executor.publish_proposals(dry_run=dry_run)


@router.post("/process-drafts")
async def process_drafts(admin=Depends(get_current_admin)):
    return await executor.process_article_drafts()


@router.post("/generate-article")
async def generate_article(force: bool = True, admin=Depends(get_current_admin)):
    return await executor.generate_article(force=force)


@router.get("/status")
async def status(admin=Depends(get_current_admin)):
    s = await engine.status()
    s["running"] = bool(_bg["task"] and not _bg["task"].done())
    s["running_kind"] = _bg["kind"] if s["running"] else None
    return s


@router.post("/run/{kind}")
async def run_now(kind: str, admin=Depends(get_current_admin), render: bool = True, llm: bool = True, base: Optional[str] = None, inspect_limit: int = Query(15, le=40)):
    """Starts a run in background (never blocks the request). kinds: tech_health | gsc_sync | daily_analysis | weekly_learning | full | foundation"""
    if kind == "foundation":
        return await foundation_run(base=base, inspect_limit=inspect_limit)
    fns = {"tech_health": lambda: engine.run_tech_health("admin", render=render), "gsc_sync": lambda: engine.run_gsc_sync("admin"), "daily_analysis": lambda: engine.run_daily("admin", use_llm=llm),
           "weekly_learning": lambda: engine.run_weekly("admin"), "full": lambda: engine.run_full("admin", use_llm=llm, render=render)}
    if kind not in fns:
        raise HTTPException(404, "Run inesistente")
    if mode.is_off():
        raise HTTPException(409, "SEO_AUTOPILOT_MODE=OFF")
    if _bg["task"] and not _bg["task"].done():
        return {"started": False, "status": "already_running", "kind": _bg["kind"]}
    _bg["task"] = asyncio.create_task(fns[kind]())
    _bg["kind"] = kind
    return {"started": True, "kind": kind, "mode": mode.current_mode()}


@router.get("/runs")
async def runs(limit: int = Query(20, le=100), admin=Depends(get_current_admin)):
    return {"items": [r async for r in store.runs_col.find({}, {"_id": 0}).sort("started_at", -1).limit(limit)]}


@router.get("/log")
async def log(limit: int = Query(50, le=300), kind: Optional[str] = None, run_id: Optional[str] = None, admin=Depends(get_current_admin)):
    q = {}
    if kind:
        q["kind"] = kind
    if run_id:
        q["run_id"] = run_id
    return {"items": [r async for r in store.log_col.find(q, {"_id": 0}).sort("timestamp", -1).limit(limit)]}


@router.get("/opportunities")
async def opportunities(status_: str = Query("OPEN", alias="status"), limit: int = Query(50, le=300), admin=Depends(get_current_admin)):
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "HOLD": 3}
    items = [o async for o in store.opportunities_col.find({"status": status_} if status_ != "ALL" else {}, {"_id": 0})]
    items.sort(key=lambda o: (order.get(o["score"], 9), -((o.get("metrics") or {}).get("impressions_28") or 0)))
    return {"items": items[:limit], "total": len(items)}


@router.get("/clusters")
async def clusters(limit: int = Query(100, le=500), intent: Optional[str] = None, admin=Depends(get_current_admin)):
    q = {"stale": {"$ne": True}}
    if intent:
        q["intent"] = intent
    items = [c async for c in store.clusters_col.find(q, {"_id": 0})]
    items.sort(key=lambda c: -((c.get("metrics") or {}).get("impressions_28") or 0))
    return {"items": items[:limit], "total": len(items)}


@router.get("/keywords")
async def keywords(limit: int = Query(200, le=2000), source: Optional[str] = None, admin=Depends(get_current_admin)):
    q = {"sources": source} if source else {}
    items = [k async for k in store.keywords_col.find(q, {"_id": 0}).limit(limit)]
    return {"items": items, "total": await store.keywords_col.count_documents(q)}


@router.get("/page-map")
async def page_map(admin=Depends(get_current_admin)):
    return {"items": [p async for p in store.page_map_col.find({}, {"_id": 0})]}


@router.get("/proposals")
async def proposals(status_: Optional[str] = Query(None, alias="status"), admin=Depends(get_current_admin)):
    q = {"status": status_} if status_ else {"status": {"$ne": "ARCHIVED"}}
    return {"items": [p async for p in store.proposals_col.find(q, {"_id": 0})], "note": "Proposte interne (SEO_DRAFT_PROPOSAL): nessuna è pubblica, nessuna è eseguibile in READ_ONLY"}


@router.get("/cannibalization")
async def cannibalization(admin=Depends(get_current_admin)):
    return {"items": [c async for c in store.cannibal_col.find({"status": "OPEN"}, {"_id": 0})]}


@router.get("/backlog")
async def backlog(limit: int = Query(100, le=500), admin=Depends(get_current_admin)):
    return {"items": [b async for b in store.backlog_col.find({"status": "OPEN"}, {"_id": 0}).sort("rank", 1).limit(limit)]}


@router.get("/tech")
async def tech(admin=Depends(get_current_admin)):
    audit = await store.audits_col.find_one({"kind": "tech"}, {"_id": 0}, sort=[("at", -1)]) or {}
    pages = [p async for p in store.tech_col.find({}, {"_id": 0, "initial_html": 0})]
    return {"audit": audit, "pages": pages}


@router.get("/render")
async def render(admin=Depends(get_current_admin)):
    docs = await render_audit.latest_docs()
    audit = await store.audits_col.find_one({"kind": "render"}, {"_id": 0}, sort=[("at", -1)]) or {}
    return {"audit": audit, "table": render_audit.initial_vs_rendered_table(docs)}


@router.get("/adult")
async def adult(admin=Depends(get_current_admin)):
    return await store.audits_col.find_one({"kind": "adult"}, {"_id": 0}, sort=[("at", -1)]) or {"findings": [], "note": "nessun audit ancora eseguito"}


@router.get("/matrix")
async def matrix(admin=Depends(get_current_admin)):
    return {"items": [m async for m in store.matrix_col.find({}, {"_id": 0})]}


@router.get("/gsc/compare")
async def gsc_compare(by: str = Query("query", pattern="^(query|page)$"), days: int = Query(7, ge=7, le=90), limit: int = Query(50, le=500), admin=Depends(get_current_admin)):
    from .gsc_sync import compare_windows
    cmp = await compare_windows(by, by, days)
    rows = []
    for k, cur in cmp["current"].items():
        prev = cmp["previous"].get(k) or {}
        rows.append({by: k, "current": cur, "previous": prev or None, "delta_impressions": cur["impressions"] - (prev.get("impressions") or 0)})
    rows.sort(key=lambda r: -r["current"]["impressions"])
    return {"days": days, "rows": rows[:limit], "note": "le impression sono quelle del sito su Google, NON il volume di ricerca globale"}


@router.get("/snapshot")
async def snapshot(admin=Depends(get_current_admin)):
    return await store.public_snapshot(store.crawl_base_url())


@router.post("/execute/{proposal_slug}")
async def execute_proposal(proposal_slug: str, admin=Depends(get_current_admin)):
    """Future FULL-mode executor. In this phase it can ONLY prove the guard: any call fails with 423 (WriteBlocked)."""
    try:
        mode.require_full(f"execute_proposal:{proposal_slug}")
    except mode.WriteBlocked as e:
        await store.log_decision(None, "WRITE_BLOCKED", proposal_slug, str(e), result="BLOCKED", kind="guard")
        raise HTTPException(423, str(e))
    raise HTTPException(501, "Esecuzione non implementata in questa fase")   # unreachable while FULL_LOCKED


# ------------------------------------------------------------------------------------------------ Phase 14B: technical SEO foundation
@router.get("/foundation")
async def foundation_latest(base: Optional[str] = None, admin=Depends(get_current_admin)):
    q = {"kind": "foundation"}
    if base:
        q["base"] = base.rstrip("/")
    doc = await store.audits_col.find_one(q, {"_id": 0}, sort=[("at", -1)])
    return doc or {"note": "nessun audit foundation eseguito"}


async def foundation_run(base: Optional[str] = None, inspect_limit: int = 15):
    """Read-only technical foundation audit. Allowed targets: the configured crawl base or the Search Console property host (explicitly authorised)."""
    from urllib.parse import urlsplit
    from google_search.config import cfg as gcfg
    target = (base or store.crawl_base_url()).rstrip("/")
    allowed = {urlsplit(store.crawl_base_url()).netloc.lower(), urlsplit(gcfg.property_url).netloc.lower()}
    if urlsplit(target).netloc.lower() not in allowed:
        raise HTTPException(400, "host non autorizzato per l'audit")
    if _bg["task"] and not _bg["task"].done():
        return {"started": False, "status": "already_running", "kind": _bg["kind"]}
    from . import foundation
    _bg["task"] = asyncio.create_task(foundation.run(target, inspect_limit=inspect_limit))
    _bg["kind"] = "foundation"
    return {"started": True, "kind": "foundation", "base": target, "mode": mode.current_mode()}
