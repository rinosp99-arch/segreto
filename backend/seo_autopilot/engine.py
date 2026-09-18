"""Orchestrator: the runs the scheduler (and admin 'run now') execute. Every run:
  1. takes a PUBLIC SNAPSHOT (hashes of models/categories/articles/landings/redirects/public config/sitemap/robots),
  2. executes its steps (each step fails soft and is logged),
  3. takes the snapshot again -> PUBLIC_MUTATIONS = number of public groups changed (must be 0),
  4. persists the run + summary in seo_ap_runs / seo_ap_state.
Runs: tech_health (6h) · gsc_sync (12h) · daily_analysis (24h) · weekly_learning (7d) · full (manual, everything)."""
import asyncio

from . import mode, store, gsc_sync, models_matrix, keywords, clustering, opportunities, planner, crawler, render_audit

_lock = asyncio.Lock()


async def _guarded(run, name, coro):
    try:
        res = await coro
        await store.step(run, name, res)
        return res
    except Exception as e:
        await store.fail_step(run, name, e)
        return None


async def run_tech_health(trigger="scheduler", render=True) -> dict:
    return await _run("tech_health", trigger, steps=("crawl", "render", "adult"), render=render)


async def run_gsc_sync(trigger="scheduler") -> dict:
    return await _run("gsc_sync", trigger, steps=("gsc",))


async def run_daily(trigger="scheduler", use_llm=True) -> dict:
    return await _run("daily_analysis", trigger, steps=("gsc", "matrix", "keywords", "clusters", "opportunities", "page_map", "cannibalization", "planner", "backlog"), use_llm=use_llm)


async def run_weekly(trigger="scheduler") -> dict:
    return await _run("weekly_learning", trigger, steps=("learning",))


async def run_full(trigger="manual", use_llm=True, render=True) -> dict:
    return await _run("full", trigger, steps=("gsc", "crawl", "render", "adult", "matrix", "keywords", "clusters", "opportunities", "page_map", "cannibalization", "planner", "backlog", "learning"), use_llm=use_llm, render=render)


async def _run(kind: str, trigger: str, steps, use_llm: bool = True, render: bool = True) -> dict:
    if mode.is_off():
        return {"kind": kind, "status": "OFF", "detail": "SEO_AUTOPILOT_MODE=OFF: il motore non esegue nulla"}
    if _lock.locked():
        return {"kind": kind, "status": "already_running"}
    async with _lock:
        await store.ensure_indexes()
        base = store.crawl_base_url()
        run = await store.start_run(kind, trigger)
        before = await store.public_snapshot(base)
        await store.log_decision(run["id"], "RUN_START", kind, f"modalità {mode.current_mode()} · base {base} · snapshot pubblico {before['hash']}", metrics={"snapshot": before["parts"]}, kind="run")
        summary = {"base": base, "mode": mode.current_mode()}
        matrix = None
        clusters = None
        tech = None
        for s in steps:
            if s == "gsc":
                summary["gsc"] = await _guarded(run, "gsc_sync", gsc_sync.sync(run["id"]))
            elif s == "crawl":
                tech = await _guarded(run, "tech_crawl", crawler.crawl(run["id"], base))
                summary["tech"] = (tech or {}).get("summary")
            elif s == "render":
                if render:
                    summary["render"] = await _guarded(run, "render_audit", render_audit.run(run["id"]))
            elif s == "adult":
                docs = await render_audit.latest_docs()
                ad = await _guarded(run, "adult_audit", crawler.adult_audit(run["id"], (tech or {}).get("results") or [p async for p in store.tech_col.find({}, {"_id": 0})], docs))
                summary["adult"] = {"findings": len((ad or {}).get("findings", []))}
            elif s == "matrix":
                matrix = await _guarded(run, "models_matrix", models_matrix.analyse(run["id"]))
                summary["matrix"] = (matrix or {}).get("summary")
            elif s == "keywords":
                if matrix:
                    summary["keywords"] = await _guarded(run, "keyword_universe", keywords.build_universe(run["id"], matrix, use_llm=use_llm))
            elif s == "clusters":
                if matrix:
                    kws = await keywords.load_keywords()
                    pbq = await clustering.pages_by_query_map()
                    summary["clusters"] = await _guarded(run, "clustering", clustering.build_clusters(run["id"], kws, pbq, use_llm=use_llm))
                    clusters = await clustering.load_clusters()
            elif s == "opportunities":
                if clusters is not None and matrix:
                    summary["opportunities"] = await _guarded(run, "opportunities", opportunities.run_opportunities(run["id"], clusters, matrix))
            elif s == "page_map":
                if clusters is not None and matrix:
                    summary["page_map"] = await _guarded(run, "page_map", opportunities.build_page_map(run["id"], clusters, matrix, base))
            elif s == "cannibalization":
                if clusters is not None:
                    summary["cannibalization"] = await _guarded(run, "cannibalization", opportunities.run_cannibalization(run["id"], clusters))
            elif s == "planner":
                if clusters is not None and matrix:
                    summary["proposals"] = await _guarded(run, "landing_planner", planner.plan(run["id"], clusters, matrix, base))
            elif s == "backlog":
                tf = ((tech or {}).get("findings")) or ((await store.audits_col.find_one({"kind": "tech"}, {"_id": 0, "findings": 1}, sort=[("at", -1)])) or {}).get("findings", [])
                rf = ((await store.audits_col.find_one({"kind": "render"}, {"_id": 0, "findings": 1}, sort=[("at", -1)])) or {}).get("findings", [])
                summary["backlog"] = await _guarded(run, "backlog", opportunities.rebuild_backlog(run["id"], list(tf) + list(rf)))
            elif s == "learning":
                lr = await _guarded(run, "weekly_learning", opportunities.weekly_learning(run["id"]))
                summary["learning"] = (lr or {}).get("clusters_trend")
        after = await store.public_snapshot(base)
        diff = store.diff_snapshots(before, after)
        summary["PUBLIC_MUTATIONS"] = diff["public_mutations"]
        await store.log_decision(run["id"], "PUBLIC_MUTATION_CHECK", kind, f"PUBLIC_MUTATIONS={diff['public_mutations']} ({'PASS' if diff['public_mutations'] == 0 else 'FAIL: ' + ', '.join(diff['changed'])})",
                                 metrics=diff, result="PASS" if diff["public_mutations"] == 0 else "FAIL", kind="run")
        run = await store.finish_run(run, summary, diff["public_mutations"], diff)
        return run


async def status() -> dict:
    """Compact status for the admin card."""
    st = await store.state_col.find_one({"id": "global"}, {"_id": 0}) or {}
    gsc = await gsc_sync.gsc_status()
    data = await gsc_sync.data_summary()
    today = store.today()
    last_daily = ((st.get("last_run") or {}).get("daily_analysis") or {})
    last_any = max(((v.get("at") or "") for v in (st.get("last_run") or {}).values()), default=None)
    props = {s: await store.proposals_col.count_documents({"status": s}) for s in ("SEO_DRAFT_PROPOSAL", "REJECTED_BY_QUALITY_GATE")}
    pm = {}
    async for d in store.page_map_col.aggregate([{"$group": {"_id": "$action", "n": {"$sum": 1}}}]):
        pm[d["_id"]] = d["n"]
    tech_last = await store.audits_col.find_one({"kind": "tech"}, {"_id": 0, "summary": 1, "at": 1}, sort=[("at", -1)]) or {}
    render_last = await store.audits_col.find_one({"kind": "render"}, {"_id": 0, "summary": 1, "at": 1}, sort=[("at", -1)]) or {}
    errors = [e async for e in store.log_col.find({"kind": "error"}, {"_id": 0, "timestamp": 1, "target": 1, "reason": 1}).sort("timestamp", -1).limit(10)]
    from . import llm
    return {
        "mode": mode.mode_info(), "GSC_STATUS": gsc["GSC_STATUS"], "gsc": {k: v for k, v in gsc.items() if k not in ("connection",)}, "gsc_data": data,
        "crawl_base_url": store.crawl_base_url(), "llm": {"enabled": llm.available(), "model": llm.MODEL[1], "source_label": llm.SOURCE, "calls_today": int(((st.get("llm_calls") or {}).get(today)) or 0), "daily_budget": llm.DAILY_CALL_BUDGET},
        "render_budget": {"daily": render_audit.DAILY_BROWSER_BUDGET, "used_today": int(((st.get("render_calls") or {}).get(today)) or 0)},
        "last_analysis_at": last_daily.get("at"), "last_run_at": last_any, "last_runs": st.get("last_run") or {},
        "today": {
            "queries_analysed": await store.keywords_col.count_documents({"metrics.source": "GSC"}), "keywords_total": await store.keywords_col.count_documents({}),
            "clusters": await store.clusters_col.count_documents({"stale": {"$ne": True}}),
            "new_opportunities": await store.opportunities_col.count_documents({"status": "OPEN", "created_at": {"$gte": today}}), "open_opportunities": await store.opportunities_col.count_documents({"status": "OPEN"}),
            "tech_problems": ((tech_last.get("summary") or {}).get("by_severity") or {}), "tech_findings": (tech_last.get("summary") or {}).get("findings"),
            "render_problems": (render_last.get("summary") or {}).get("problems"),
            "proposals_CREATE": pm.get("CREATE", 0), "proposals_UPDATE": pm.get("UPDATE", 0), "proposals_MERGE": pm.get("MERGE", 0), "page_map": pm,
            "landing_drafts": props["SEO_DRAFT_PROPOSAL"], "blocked_by_quality_gate": props["REJECTED_BY_QUALITY_GATE"],
            "cannibalization_open": await store.cannibal_col.count_documents({"status": "OPEN"}),
        },
        "errors": errors, "PUBLIC_MUTATIONS_last": last_daily.get("public_mutations"),
    }
