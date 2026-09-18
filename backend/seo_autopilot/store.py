"""Dedicated collections (all prefixed seo_ap_) + decision log + public snapshot hashing (PUBLIC_MUTATIONS check)."""
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from database import db, models_col, categories_col, articles_col, landings_col, redirects_col, config_col, now_iso

snapshots_col = db["seo_ap_gsc_snapshots"]        # daily GSC rows, never overwritten (unique per day+dims+keys)
keywords_col = db["seo_ap_keywords"]             # keyword universe
clusters_col = db["seo_ap_clusters"]
opportunities_col = db["seo_ap_opportunities"]
page_map_col = db["seo_ap_page_map"]
proposals_col = db["seo_ap_landing_proposals"]   # SEO_DRAFT_PROPOSAL / REJECTED_BY_QUALITY_GATE — never public
cannibal_col = db["seo_ap_cannibalization"]
tech_col = db["seo_ap_tech_pages"]               # crawler results per URL
render_col = db["seo_ap_render_audits"]
audits_col = db["seo_ap_audits"]                 # adult / render / tech summaries per run
backlog_col = db["seo_ap_backlog"]
log_col = db["seo_ap_decision_log"]
runs_col = db["seo_ap_runs"]
state_col = db["seo_ap_state"]
matrix_col = db["seo_ap_creator_matrix"]
llm_cache_col = db["seo_ap_llm_cache"]


async def ensure_indexes():
    await snapshots_col.create_index([("date", 1), ("dims", 1), ("key", 1)], unique=True)
    await snapshots_col.create_index([("dims", 1), ("date", -1)])
    await snapshots_col.create_index([("query", 1), ("date", -1)], sparse=True)
    await snapshots_col.create_index([("page", 1), ("date", -1)], sparse=True)
    await keywords_col.create_index("norm", unique=True)
    await keywords_col.create_index("cluster_id")
    await clusters_col.create_index("cluster_id", unique=True)
    await opportunities_col.create_index([("run_id", 1), ("score", 1)])
    await opportunities_col.create_index("fingerprint")
    await page_map_col.create_index("cluster_id", unique=True)
    await proposals_col.create_index("proposed_slug", unique=True)
    await cannibal_col.create_index("fingerprint", unique=True)
    await tech_col.create_index("url", unique=True)
    await render_col.create_index([("url", 1), ("checked_at", -1)])
    await backlog_col.create_index("fingerprint", unique=True)
    await backlog_col.create_index([("status", 1), ("priority", -1)])
    await log_col.create_index([("timestamp", -1)])
    await log_col.create_index([("run_id", 1)])
    await runs_col.create_index([("started_at", -1)])
    await matrix_col.create_index("slug", unique=True)
    await llm_cache_col.create_index("key", unique=True)


# ------------------------------------------------------------------------------------------------ decision log
async def log_decision(run_id: Optional[str], action: str, target: str, reason: str, metrics: Optional[dict] = None, confidence: Optional[float] = None,
                       quality: Optional[dict] = None, result: str = "RECORDED", kind: str = "decision", source: str = "RULES") -> dict:
    """Every decision the engine takes is auditable: WHY (reason + metrics), HOW SURE (confidence), quality check, outcome."""
    doc = {"id": str(uuid.uuid4()), "run_id": run_id, "timestamp": now_iso(), "kind": kind, "action": action, "target": target, "reason": reason[:600],
           "metrics": metrics or {}, "confidence": confidence, "quality_check": quality, "result": result, "source": source, "mode": _mode()}
    try:
        await log_col.insert_one(dict(doc))
    except Exception:
        pass
    doc.pop("_id", None)
    return doc


def _mode() -> str:
    from .mode import current_mode
    return current_mode()


# ------------------------------------------------------------------------------------------------ runs
async def start_run(kind: str, trigger: str = "scheduler") -> dict:
    run = {"id": str(uuid.uuid4()), "kind": kind, "trigger": trigger, "mode": _mode(), "started_at": now_iso(), "status": "running", "steps": [], "errors": []}
    await runs_col.insert_one(dict(run))
    run.pop("_id", None)
    return run


async def step(run: dict, name: str, result: Any, ok: bool = True):
    entry = {"step": name, "ok": ok, "at": now_iso(), "result": _compact(result)}
    run["steps"].append(entry)
    await runs_col.update_one({"id": run["id"]}, {"$push": {"steps": entry}})


async def fail_step(run: dict, name: str, error: Exception):
    msg = f"{type(error).__name__}: {str(error)[:300]}"
    run["errors"].append({"step": name, "error": msg, "at": now_iso()})
    await runs_col.update_one({"id": run["id"]}, {"$push": {"errors": {"step": name, "error": msg, "at": now_iso()}, "steps": {"step": name, "ok": False, "at": now_iso(), "result": msg}}})
    await log_decision(run["id"], "STEP_ERROR", name, msg, result="ERROR", kind="error")


async def finish_run(run: dict, summary: dict, public_mutations: Optional[int] = None, snapshot_diff: Optional[dict] = None):
    status = "ok" if not run["errors"] else "partial"
    if public_mutations:
        status = "FAIL_PUBLIC_MUTATION"
    upd = {"status": status, "ended_at": now_iso(), "summary": _compact(summary, 12000), "public_mutations": public_mutations, "snapshot_diff": snapshot_diff,
           "PUBLIC_MUTATIONS_CHECK": ("PASS" if public_mutations == 0 else "FAIL") if public_mutations is not None else "N/A"}
    await runs_col.update_one({"id": run["id"]}, {"$set": upd})
    await state_col.update_one({"id": "global"}, {"$set": {f"last_run.{run['kind']}": {"id": run["id"], "at": now_iso(), "status": status, "public_mutations": public_mutations, "summary": _compact({k: v for k, v in summary.items() if k not in ("snapshot",)}, 6000)}}}, upsert=True)
    run.update(upd)
    return run


def _compact(x: Any, limit: int = 4000) -> Any:
    try:
        s = json.dumps(x, default=str)
        if len(s) <= limit:
            return json.loads(s)
        return {"_truncated": True, "preview": s[:limit]}
    except Exception:
        return str(x)[:limit]


# ------------------------------------------------------------------------------------------------ PUBLIC SNAPSHOT (zero-mutation proof)
PUBLIC_MODEL_FIELDS_EXCLUDED = {"analytics", "_id"}


def _h(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:24]


async def public_snapshot(base_url: Optional[str] = None, fetch_http: bool = True) -> dict:
    """Hashes of every public resource the engine must never change. Compared before/after each run -> PUBLIC_MUTATIONS."""
    parts: Dict[str, str] = {}
    models = [ {k: v for k, v in m.items() if k not in PUBLIC_MODEL_FIELDS_EXCLUDED} async for m in models_col.find({}, {"_id": 0, "analytics": 0}).sort("id", 1)]
    parts["models"] = _h(models)
    parts["models_public_fields"] = _h([{k: m.get(k) for k in ("slug", "stato", "seo", "nome_artistico", "bio", "bio_segreta", "categorie", "tag", "anteprima", "ordine", "media_pairs", "galleria_pubblica", "galleria_segreta", "onlyfans_url", "cta_testo", "social", "pellicola_home", "is_deleted")} for m in models])
    parts["categories"] = _h([c async for c in categories_col.find({}, {"_id": 0}).sort("id", 1)])
    parts["articles"] = _h([a async for a in articles_col.find({}, {"_id": 0}).sort("id", 1)])
    parts["landings"] = _h([l async for l in landings_col.find({}, {"_id": 0}).sort("id", 1)])
    parts["redirects"] = _h([r async for r in redirects_col.find({}, {"_id": 0, "hits": 0, "updated_at": 0}).sort("id", 1)])
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0, "site": 1, "flags": 1, "seo": 1, "public": 1}) or {}
    parts["config_public"] = _h(cfg)
    if fetch_http and base_url:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True, headers={"User-Agent": "LatoSegreto-SEO-Autopilot/1.0 (snapshot)"}) as c:
            for name, path in (("sitemap_xml", "/api/sitemap.xml"), ("robots_txt", "/robots.txt")):
                try:
                    r = await c.get(f"{base_url}{path}")
                    body = r.text
                    if name == "sitemap_xml":
                        import re
                        body = re.sub(r"<lastmod>.*?</lastmod>", "", body)   # lastmod moves legitimately (updated_at of models)
                    parts[name] = _h({"status": r.status_code, "body": body})
                except Exception as e:
                    parts[name] = f"UNAVAILABLE:{type(e).__name__}"
    return {"taken_at": now_iso(), "parts": parts, "hash": _h(parts)}


def diff_snapshots(before: dict, after: dict) -> dict:
    """PUBLIC_MUTATIONS = number of public resource groups whose hash changed between before and after."""
    changed = [k for k in before["parts"] if before["parts"].get(k) != after["parts"].get(k)]
    return {"public_mutations": len(changed), "changed": changed, "before": before["hash"], "after": after["hash"]}


def crawl_base_url() -> str:
    """Decision 3a: analyse the environment we run in. SEO_CRAWL_BASE_URL wins; fallback: frontend .env public URL."""
    v = (os.environ.get("SEO_CRAWL_BASE_URL") or "").strip().rstrip("/")
    if v:
        return v
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "frontend", ".env")) as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    return "http://localhost:3000"


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
