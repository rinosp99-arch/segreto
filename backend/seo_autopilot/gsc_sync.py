"""Google Search Console import -> daily, NON-overwriting snapshots (reuses backend/google_search — decision 2a).

Dimensions imported (when connected): query · page · date · device · country, each row keyed by its dimension values.
GSC data lags ~2-3 days: every sync imports the last N available days and is idempotent (unique index date+dims+key).
GSC impressions are OUR site's impressions, never global search volume (rule 25).
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from google_search import service as gs
from google_search.config import cfg as gcfg

from .store import snapshots_col, state_col, log_decision, now_iso

DIM_SETS = {
    "query": ["date", "query"],
    "page": ["date", "page"],
    "query_page": ["date", "query", "page"],
    "device": ["date", "device"],
    "country": ["date", "country"],
    "query_device": ["date", "query", "device"],
}
ROW_LIMIT = 5000


async def gsc_status() -> dict:
    """GSC_STATUS: CONNECTED | NOT_CONNECTED | ERROR (+ what is needed when not connected). Never returns credentials."""
    if not gs.configured():
        return {"GSC_STATUS": "NOT_CONNECTED", "property": gcfg.property_url,
                "required": ["GOOGLE_SEARCH_ENABLED=true", "GOOGLE_SEARCH_CREDENTIALS_JSON=<service account JSON> (solo backend/env)",
                             "GOOGLE_SEARCH_PROPERTY=<proprietà Search Console>", "service account aggiunto come utente della proprietà (scope read-only: webmasters.readonly)"],
                "features": {"search_analytics": False, "url_inspection": False}}
    try:
        st = await gs.status()
        conn = (st.get("connection") or {}).get("status")
        return {"GSC_STATUS": "CONNECTED" if conn == "CONNECTED" else ("ERROR" if conn in ("ERROR",) else "NOT_CONNECTED"), "connection": st.get("connection"),
                "property": gcfg.property_url, "mock": gcfg.mock, "features": {"search_analytics": gcfg.analytics_enabled, "url_inspection": gcfg.inspection_enabled},
                "inspection_budget": st.get("inspection_budget"), "last_error": st.get("last_error")}
    except Exception as e:
        return {"GSC_STATUS": "ERROR", "error": f"{type(e).__name__}", "property": gcfg.property_url}


def _available_end() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=3)


async def _fetch(dims: List[str], start: str, end: str) -> dict:
    """Read-only Search Analytics query through the EXISTING google_search client (same auth, same request log).
    Uses the raw adapter (not the 250-row cached helper) so a whole day of queries fits; paginates with startRow.
    Returns {"available": bool, "rows": [...], "error": ...}. Tests monkeypatch this function."""
    if not gs.configured() or not gcfg.analytics_enabled:
        return {"available": False, "state": "NOT_CONFIGURED", "rows": []}
    rows, start_row = [], 0
    try:
        for _ in range(5):                                   # max 5 pages x ROW_LIMIT
            body = {"startDate": start, "endDate": end, "dimensions": dims, "rowLimit": ROW_LIMIT, "startRow": start_row, "dataState": "all"}
            raw = await gs._adapter().search_analytics(gcfg.property_url, body)
            page = raw.get("rows") or []
            rows.extend(page)
            if len(page) < ROW_LIMIT:
                break
            start_row += ROW_LIMIT
        return {"available": True, "rows": rows}
    except Exception as e:
        return {"available": False, "state": "ERROR", "error": f"{type(e).__name__}: {str(e)[:160]}", "rows": []}


async def sync(run_id: Optional[str] = None, days: int = 7, dim_sets: Optional[List[str]] = None) -> dict:
    """Import the last `days` available days for each dimension set. Idempotent; returns per-set counts."""
    status = await gsc_status()
    out: Dict[str, object] = {"GSC_STATUS": status["GSC_STATUS"], "imported": {}, "skipped": {}, "errors": {}}
    if status["GSC_STATUS"] != "CONNECTED":
        await log_decision(run_id, "GSC_SYNC_SKIPPED", "search_console", f"GSC_STATUS={status['GSC_STATUS']}: nessun import (nessun dato inventato)", result="SKIPPED", kind="sync")
        return out
    end = _available_end().date()
    start = end - timedelta(days=days - 1)
    for name in (dim_sets or list(DIM_SETS)):
        dims = DIM_SETS[name]
        try:
            data = await _fetch(dims, start.isoformat(), end.isoformat())
            if not data.get("available"):
                out["errors"][name] = data.get("error") or data.get("state")
                continue
            n_new, n_dup = 0, 0
            for r in data.get("rows", []):
                keys = r.get("keys") or []
                if len(keys) != len(dims):
                    continue
                row = dict(zip(dims, keys))
                doc = {"date": row.get("date"), "dims": name, "key": "|".join(keys[1:]) or "_", **{d: row[d] for d in dims if d != "date"},
                       "clicks": int(r.get("clicks") or 0), "impressions": int(r.get("impressions") or 0), "ctr": round(float(r.get("ctr") or 0.0) * 100, 2), "position": round(float(r.get("position") or 0.0), 1),
                       "imported_at": now_iso(), "source": "GSC"}
                try:
                    await snapshots_col.insert_one(doc)
                    n_new += 1
                except Exception:
                    n_dup += 1              # already imported: never overwritten
            out["imported"][name] = n_new
            out["skipped"][name] = n_dup
        except Exception as e:
            out["errors"][name] = f"{type(e).__name__}: {str(e)[:120]}"
    await state_col.update_one({"id": "global"}, {"$set": {"gsc_last_sync_at": now_iso(), "gsc_last_sync": out}}, upsert=True)
    await log_decision(run_id, "GSC_SYNC", "search_console", f"import {start}→{end}: {sum(out['imported'].values())} righe nuove, {sum(out['skipped'].values())} già presenti", metrics={"imported": out["imported"], "errors": out["errors"]}, result="OK" if not out["errors"] else "PARTIAL", kind="sync")
    return out


# ------------------------------------------------------------------------------------------------ read helpers (historical comparisons)
async def window(dims: str, days: int, offset_days: int = 0) -> List[dict]:
    """Rows for the window [end-offset-days+1, end-offset] where end = last available day (never overwritten history)."""
    end = _available_end().date() - timedelta(days=offset_days)
    start = end - timedelta(days=days - 1)
    return [r async for r in snapshots_col.find({"dims": dims, "date": {"$gte": start.isoformat(), "$lte": end.isoformat()}}, {"_id": 0})]


def aggregate(rows: List[dict], by: str) -> Dict[str, dict]:
    """Sum clicks/impressions, impression-weighted position, CTR — per key (query or page)."""
    out: Dict[str, dict] = {}
    for r in rows:
        k = r.get(by)
        if not k:
            continue
        a = out.setdefault(k, {"clicks": 0, "impressions": 0, "_pos_w": 0.0, "days": set()})
        a["clicks"] += r["clicks"]
        a["impressions"] += r["impressions"]
        a["_pos_w"] += r["position"] * r["impressions"]
        a["days"].add(r["date"])
    for k, a in out.items():
        a["position"] = round(a["_pos_w"] / a["impressions"], 1) if a["impressions"] else None
        a["ctr"] = round(100.0 * a["clicks"] / a["impressions"], 2) if a["impressions"] else None
        a["days"] = len(a["days"])
        a.pop("_pos_w", None)
    return out


async def compare_windows(dims: str, by: str, days: int) -> dict:
    """today-window vs previous window of the same length (7 vs 7, 28 vs 28, 90 vs 90)."""
    cur = aggregate(await window(dims, days, 0), by)
    prev = aggregate(await window(dims, days, days), by)
    return {"current": cur, "previous": prev, "days": days}


async def data_summary() -> dict:
    """What history exists (for the admin status and for honest UNKNOWN labelling)."""
    n = await snapshots_col.count_documents({})
    first = await snapshots_col.find_one({}, {"_id": 0, "date": 1}, sort=[("date", 1)])
    last = await snapshots_col.find_one({}, {"_id": 0, "date": 1}, sort=[("date", -1)])
    days = len(await snapshots_col.distinct("date"))
    return {"rows": n, "first_date": (first or {}).get("date"), "last_date": (last or {}).get("date"), "days": days,
            "comparisons_available": {"7g": days >= 14, "28g": days >= 56, "90g": days >= 180}}
