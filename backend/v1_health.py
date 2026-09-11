"""SUPER API v1 - HEALTH MONITORING, SELF-HEALING, ALERTS.

Checks: api, database, frontend, media, links, OnlyFans links, SEO fields, sitemap,
tracking, analytics events, background jobs.
Policy: SAFE -> auto-fix (versioned, rollback on regression). IMPORTANT -> alert + review.
"""
import os
import uuid
import time
import asyncio
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Request
import requests as _requests

from database import (
    db, models_col, events_col, files_col, health_col, alerts_col, jobs_col, seo_issues_col, config_col, now_iso,
)
from v1_security import require, actor_of, request_id_of
from v1_versioning import audit_log

logger = logging.getLogger("lato-segreto.health")

health_router = APIRouter(prefix="/api/v1/health", tags=["Health & Self-healing"])
alerts_router = APIRouter(prefix="/api/v1/alerts", tags=["Health & Self-healing"])

from v1_models import onlyfans_url_status  # canonical OnlyFans URL rule (was a stale duplicate regex: root cause of false critical alerts)
FRONTEND_PUBLIC_DIR = "/app/frontend/public"


# ---------------- ALERTS ----------------
async def raise_alert(tipo: str, titolo: str, messaggio: str, severity: str = "warning", entity: Optional[str] = None,
                      entity_id: Optional[str] = None, dedupe_key: Optional[str] = None, meta: Optional[dict] = None) -> Optional[dict]:
    dedupe_key = dedupe_key or f"{tipo}:{entity}:{entity_id}"
    existing = await alerts_col.find_one({"dedupe_key": dedupe_key, "stato": {"$in": ["open", "acknowledged"]}}, {"_id": 0})
    if existing:
        # refresh the alert with the CURRENT evidence (message, meta, severity) so it never shows stale details
        await alerts_col.update_one({"id": existing["id"]}, {"$set": {"last_seen": now_iso(), "updated_at": now_iso(), "checked_at": now_iso(), "messaggio": messaggio,
                                                                     "severity": severity, "meta": meta or existing.get("meta") or {}, "current": True}, "$inc": {"occurrences": 1}})
        return None
    doc = {"id": str(uuid.uuid4()), "tipo": tipo, "titolo": titolo, "messaggio": messaggio, "severity": severity,
           "entity": entity, "entity_id": entity_id, "dedupe_key": dedupe_key, "stato": "open", "occurrences": 1, "current": True,
           "source": (meta or {}).get("source") or "health_check", "created_at": now_iso(), "updated_at": now_iso(), "checked_at": now_iso(), "last_seen": now_iso(), "meta": meta or {}}
    await alerts_col.insert_one(dict(doc))
    try:
        from v1_config import emit_event
        await emit_event("alert.created", doc)
    except Exception:
        pass
    return doc


async def resolve_alerts(dedupe_key: str, by: str = "system") -> int:
    """Reconciliation: the condition is no longer present -> close open alerts (history kept, resolved_at set)."""
    r = await alerts_col.update_many({"dedupe_key": dedupe_key, "stato": {"$in": ["open", "acknowledged"]}},
                                     {"$set": {"stato": "resolved", "current": False, "resolved_at": now_iso(), "updated_at": now_iso(), "checked_at": now_iso(), "resolved_by": by}})
    return r.modified_count


async def touch_alerts(dedupe_key: str):
    """Condition re-checked and still present: only refresh checked_at (used when a check passes through without re-raising)."""
    await alerts_col.update_many({"dedupe_key": dedupe_key, "stato": {"$in": ["open", "acknowledged"]}}, {"$set": {"checked_at": now_iso()}})


# ---------------- CHECKS ----------------
def _chk(name, status, detail="", **extra):
    return {"name": name, "status": status, "detail": detail, **extra}


async def check_db():
    t = time.time()
    try:
        await db.command("ping")
        n = await models_col.count_documents({})
        return _chk("database", "ok", f"MongoDB ping ok, {n} modelle", latency_ms=round((time.time() - t) * 1000, 1))
    except Exception as e:
        return _chk("database", "fail", str(e))


async def check_api():
    return _chk("api", "ok", "Backend attivo (self)", pid=os.getpid())


def _http_head(url: str, timeout=8):
    try:
        r = _requests.head(url, timeout=timeout, allow_redirects=True, headers={"User-Agent": "LatoSegreto-HealthCheck/1.0"})
        if r.status_code in (403, 405):
            r = _requests.get(url, timeout=timeout, stream=True, headers={"User-Agent": "LatoSegreto-HealthCheck/1.0"})
        return r.status_code
    except Exception:
        return None


def classify_reachability(code) -> str:
    """Remote reachability is NEVER a URL-validity verdict. 'missing' only for definitive 404/410; anti-bot/rate-limit/timeouts are warnings."""
    if code is None:
        return "REMOTE_REACHABILITY_WARNING"      # timeout / network error / challenge
    if code in (403, 429, 401, 405, 503):
        return "REMOTE_BLOCKED_WARNING"           # WAF / anti-bot / rate limit
    if code in (404, 410):
        return "REMOTE_MISSING"
    if code >= 500:
        return "REMOTE_ERROR_WARNING"
    return "OK"


async def check_frontend():
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0}) or {}
    base = (cfg.get("site") or {}).get("base_url") or os.environ.get("PUBLIC_BASE_URL") or ""
    if not base:
        return _chk("frontend", "unknown", "site.base_url non configurato: check esterno saltato (impostalo in Config Center)")
    code = await asyncio.get_event_loop().run_in_executor(None, _http_head, base)
    return _chk("frontend", "ok" if code and code < 400 else "fail", f"GET {base} -> {code}", status_code=code)


async def check_media(sample: int = 12):
    missing, checked = [], 0
    docs = await models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "foto_card": 1, "media_pairs": 1, "pellicola_home": 1}).to_list(200)
    urls = []
    for d in docs:
        if d.get("foto_card"):
            urls.append((d["slug"], "foto_card", d["foto_card"]))
        for i, p in enumerate(d.get("media_pairs") or []):
            for side in ("pubblico", "segreto"):
                u = (p.get(side) or {}).get("url")
                if u:
                    urls.append((d["slug"], f"pair{i}.{side}", u))
    local = [u for u in urls if u[2].startswith("/media/") or u[2].startswith("/api/uploads/")]
    external = [u for u in urls if u[2].startswith("http")]
    for slug, field, u in local:
        checked += 1
        if u.startswith("/media/"):
            if not os.path.exists(os.path.join(FRONTEND_PUBLIC_DIR, u.lstrip("/"))):
                missing.append({"slug": slug, "field": field, "url": u})
        else:
            path = u[len("/api/uploads/"):]
            if not await files_col.find_one({"storage_path": path, "is_deleted": {"$ne": True}}):
                missing.append({"slug": slug, "field": field, "url": u})
    loop = asyncio.get_event_loop()
    warnings = []
    for slug, field, u in external[:sample]:
        checked += 1
        code = await loop.run_in_executor(None, _http_head, u)
        kind = classify_reachability(code)
        if kind == "REMOTE_MISSING":
            missing.append({"slug": slug, "field": field, "url": u, "status": code, "code": kind})
        elif kind != "OK":
            warnings.append({"slug": slug, "field": field, "url": u, "status": code, "code": kind})
    status = "ok" if not missing and not warnings else ("warn" if len(missing) <= 3 else "fail")
    return _chk("media", status, f"{checked} media verificati, {len(missing)} mancanti, {len(warnings)} non verificabili da server", missing=missing[:20], warnings=warnings[:20], total_refs=len(urls), checked_at=now_iso())


async def check_onlyfans_links():
    """Structural check with the CANONICAL rule (same as validator / model-health / SEO). No HTTP request to OnlyFans:
    a server-side fetch would be blocked by anti-bot and must never be interpreted as an invalid URL."""
    bad, total = [], 0
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "onlyfans_url": 1}):
        total += 1
        st = onlyfans_url_status(m.get("onlyfans_url"))
        if st != "ok":
            bad.append({"slug": m["slug"], "onlyfans_url": (m.get("onlyfans_url") or "").strip(), "code": "URL_MISSING" if st == "missing" else "URL_STRUCTURE_INVALID", "problem": "mancante" if st == "missing" else "formato non valido"})
    return _chk("onlyfans_links", "ok" if not bad else "fail", (f"{len(bad)} link OnlyFans problematici su {total} modelle pubblicate" if bad else f"{total}/{total} link OnlyFans validi (controllo strutturale canonico)"),
                items=bad, valid=total - len(bad), total=total, check_kind="URL_STRUCTURE", reachability="not_tested (anti-bot)", checked_at=now_iso())


async def check_links():
    """Social + external links format check (no crawling of OnlyFans: bot-protected)."""
    bad = []
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "social": 1}):
        for k, v in (m.get("social") or {}).items():
            if k == "custom":
                continue
            if v and not str(v).startswith("https://"):
                bad.append({"slug": m["slug"], "social": k, "url": v})
    return _chk("links", "ok" if not bad else "warn", f"{len(bad)} link social non https", items=bad)


async def check_seo():
    counts = {"SAFE_AUTO_FIX": 0, "REVIEW_REQUIRED": 0, "CRITICAL": 0}
    async for r in seo_issues_col.aggregate([{"$match": {"status": "open"}}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        counts[r["_id"]] = r["n"]
    status = "fail" if counts["CRITICAL"] else ("warn" if counts["REVIEW_REQUIRED"] > 10 or counts["SAFE_AUTO_FIX"] > 0 else "ok")
    return _chk("seo_fields", status, f"Issue aperte: {counts}", counts=counts, checked_at=now_iso())


async def check_sitemap():
    from v1_seo import sitemap_entries
    entries = await sitemap_entries()
    published = await models_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}})
    in_map = len([e for e in entries if e["type"] == "model"])
    excluded = published - in_map
    return _chk("sitemap", "ok", f"{len(entries)} URL in sitemap ({in_map} modelle, {excluded} escluse per noindex)", total=len(entries), models_in_sitemap=in_map)


async def check_tracking():
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    n = await events_col.count_documents({"timestamp": {"$gte": since}})
    last = await events_col.find_one({}, {"_id": 0, "timestamp": 1, "event": 1, "tipo": 1}, sort=[("timestamp", -1)])
    geo = await events_col.count_documents({"timestamp": {"$gte": since}, "geo": {"$exists": True}})
    return _chk("tracking", "ok" if n > 0 else "warn", f"{n} eventi nelle ultime 24h ({geo} con geo)", last_event=last, events_24h=n)


async def check_jobs():
    from datetime import datetime, timezone
    items = await jobs_col.find({}, {"_id": 0}).to_list(100)
    late, failed = [], []
    now = datetime.now(timezone.utc).timestamp()
    for j in items:
        if j.get("last_status") == "error":
            failed.append(j["name"])
        if j.get("enabled", True) and j.get("last_run_ts") and now - j["last_run_ts"] > j.get("interval_s", 3600) * 2.5:
            late.append(j["name"])
    status = "fail" if failed else ("warn" if late else "ok")
    return _chk("background_jobs", status, f"{len(items)} job, {len(failed)} in errore, {len(late)} in ritardo", failed=failed, late=late)


async def run_health_checks(auto_fix: Optional[bool] = None) -> dict:
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0}) or {}
    sh = cfg.get("self_healing") or {}
    if auto_fix is None:
        auto_fix = bool(sh.get("enabled", True) and sh.get("auto_fix", True))
    checks = [await check_api(), await check_db(), await check_frontend(), await check_media(), await check_links(), await check_onlyfans_links(),
              await check_seo(), await check_sitemap(), await check_tracking(), await check_jobs()]
    actions: List[dict] = []
    # SELF-HEALING: safe SEO fixes
    seo_chk = next(c for c in checks if c["name"] == "seo_fields")
    if auto_fix and seo_chk["counts"]["SAFE_AUTO_FIX"] > 0:
        from v1_seo import apply_safe_fixes
        res = await apply_safe_fixes("self-healing", None, None, None, False, source="autofix")
        actions.append({"action": "seo_safe_fixes", "applied": res["applied"], "skipped": res["skipped"]})
        seo_chk = await check_seo()
        checks = [seo_chk if c["name"] == "seo_fields" else c for c in checks]
    # SELF-HEALING: published models that are no longer valid -> alert (never auto-unpublish silently; the legacy admin already auto-bozza on edit)
    from v1_models import validate_model
    broken = []
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0}):
        v = validate_model(m)
        if not v["ready"]:
            broken.append({"slug": m["slug"], "errors": [e["code"] for e in v["errors"]]})
    if broken:
        await raise_alert("published_not_ready", "Modelle pubblicate con requisiti mancanti", f"{len(broken)} modelle pubblicate non superano la validazione", "critical", "model", None, "published_not_ready", {"items": broken})
    else:
        await resolve_alerts("published_not_ready")
    # alerts from checks (reconciled on EVERY run: a condition that disappeared closes its alert, history is kept)
    resolved_now = []
    for c in checks:
        key = f"health:{c['name']}"
        if c["status"] == "fail":
            await raise_alert("health_check", f"Check fallito: {c['name']}", c["detail"], "critical", "health", c["name"], key, {k: v for k, v in c.items() if k not in ("name", "status", "detail")})
        elif c["status"] == "warn":
            await raise_alert("health_check", f"Attenzione: {c['name']}", c["detail"], "warning", "health", c["name"], key, {k: v for k, v in c.items() if k not in ("name", "status", "detail")})
        else:
            if await resolve_alerts(key):
                resolved_now.append(key)
    # job-level alerts that mirror the same conditions must be reconciled here too (they used to stay open forever)
    of_chk = next(c for c in checks if c["name"] == "onlyfans_links")
    if of_chk["status"] == "ok" and await resolve_alerts("onlyfans_links"):
        resolved_now.append("onlyfans_links")
    if seo_chk["counts"]["CRITICAL"] == 0 and await resolve_alerts("seo_critical"):
        resolved_now.append("seo_critical")
    elif seo_chk["counts"]["CRITICAL"] > 0:
        await touch_alerts("seo_critical")
    overall = "fail" if any(c["status"] == "fail" for c in checks) else ("warn" if any(c["status"] == "warn" for c in checks) else "ok")
    rec = {"id": str(uuid.uuid4()), "timestamp": now_iso(), "checked_at": now_iso(), "overall": overall, "checks": checks, "actions": actions, "auto_fix": auto_fix,
           "resolved_alerts": resolved_now, "source": "health_check"}
    await health_col.insert_one(dict(rec))
    old = await health_col.find({}, {"_id": 0, "id": 1}).sort("timestamp", -1).skip(300).to_list(1000)
    if old:
        await health_col.delete_many({"id": {"$in": [o["id"] for o in old]}})
    return {k: v for k, v in rec.items() if k != "_id"}


# ---------------- ROUTES ----------------
@health_router.get("")
async def latest(principal=Depends(require("health:read"))):
    rec = await health_col.find_one({}, {"_id": 0}, sort=[("timestamp", -1)])
    open_alerts = await alerts_col.count_documents({"stato": "open"})
    return {"latest": rec, "open_alerts": open_alerts, "note": "POST /api/v1/health/run per eseguire ora"}


@health_router.post("/run")
async def run_now(request: Request, auto_fix: Optional[bool] = None, principal=Depends(require("health:read"))):
    rec = await run_health_checks(auto_fix)
    await audit_log(actor_of(principal), "health_run", "health", rec["id"], {"overall": rec["overall"]}, request_id_of(request))
    return rec


@health_router.get("/history")
async def history(limit: int = 30, principal=Depends(require("health:read"))):
    items = await health_col.find({}, {"_id": 0, "checks": 0}).sort("timestamp", -1).to_list(limit)
    return {"items": items}


@alerts_router.get("")
async def list_alerts(stato: str = "open", severity: Optional[str] = None, limit: int = 100, principal=Depends(require("alerts:read"))):
    q: Dict[str, Any] = {}
    if stato != "all":
        q["stato"] = stato
    if severity:
        q["severity"] = severity
    items = await alerts_col.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    counts = {}
    async for r in alerts_col.aggregate([{"$match": {"stato": "open"}}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        counts[r["_id"]] = r["n"]
    return {"items": items, "open_counts": counts}


@alerts_router.post("/{alert_id}/ack")
async def ack(alert_id: str, principal=Depends(require("alerts:write"))):
    r = await alerts_col.update_one({"id": alert_id}, {"$set": {"stato": "acknowledged", "acknowledged_at": now_iso(), "acknowledged_by": actor_of(principal)}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Alert non trovato")
    return {"ok": True}


@alerts_router.post("/{alert_id}/resolve")
async def resolve(alert_id: str, principal=Depends(require("alerts:write"))):
    r = await alerts_col.update_one({"id": alert_id}, {"$set": {"stato": "resolved", "resolved_at": now_iso(), "resolved_by": actor_of(principal)}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Alert non trovato")
    return {"ok": True}
