"""Deterministic keyword clustering (rule 6) + guarded LLM merge suggestions.

1. Exact groups by cluster_key (canonical tokens, people-nouns collapsed).
2. Merge groups with Jaccard(canonical tokens) >= 0.75 and identical intent.
3. LLM merge candidates (advisory) applied ONLY if: same intent, share >= 1 non-generic token, confidence >= 0.7. Logged.
Each cluster: cluster_id (stable hash of its representative key), intent, primary/secondary keywords, GSC queries + metrics,
trend (7 vs 7), associated page(s) from GSC query+page rows, cannibalization hint, opportunity_status (filled later)."""
import hashlib
from typing import Dict, List, Optional

from . import llm
from .gsc_sync import window, aggregate
from .store import clusters_col, keywords_col, log_decision, now_iso
from .textnorm import cluster_key, jaccard

GENERIC = {"onlyfans", "italiane", "<persone>", "ragazze", "modelle", "creator", "profili"}


def _cid(rep_key: str) -> str:
    return "c_" + hashlib.sha1(rep_key.encode()).hexdigest()[:10]


def _trend(cur: Optional[int], prev: Optional[int]) -> dict:
    if cur is None and prev is None:
        return {"status": "UNKNOWN", "reason": "nessun dato GSC"}
    cur, prev = cur or 0, prev or 0
    if prev == 0 and cur >= 5:
        return {"status": "NEW", "delta_pct": None}
    if prev == 0:
        return {"status": "UNKNOWN", "delta_pct": None}
    d = round(100.0 * (cur - prev) / prev, 1)
    return {"status": "GROWING" if d >= 20 else "DECLINING" if d <= -20 else "STABLE", "delta_pct": d}


async def build_clusters(run_id: Optional[str], keywords: List[dict], pages_by_query: Dict[str, Dict[str, dict]], use_llm: bool = True) -> dict:
    groups: Dict[str, List[dict]] = {}
    for k in keywords:
        if not k.get("pertinent", True):
            continue
        groups.setdefault(cluster_key(k["keyword"]), []).append(k)
    # step 2: deterministic near-merge
    keys = sorted(groups)
    merged: Dict[str, List[str]] = {k: [k] for k in keys}
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    tokset = {k: set(k.split()) for k in keys}
    intent_of = {k: _majority_intent(groups[k]) for k in keys}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if intent_of[a] == intent_of[b] and jaccard(tokset[a], tokset[b]) >= 0.75:
                union(a, b)
    # step 3: LLM merge suggestions (guarded)
    llm_merges = {"used": False, "applied": 0, "rejected": 0}
    prelim = _assemble(keys, find, groups, intent_of)
    if use_llm and llm.available() and len(prelim) >= 2:
        res = await llm.suggest_merges(list(prelim.values()))
        llm_merges["used"] = res.get("available", False)
        if res.get("available"):
            by_id = {c["cluster_id"]: c for c in prelim.values()}
            for m in (res["data"].get("merges") or [])[:40]:
                a, b = by_id.get(m.get("a")), by_id.get(m.get("b"))
                conf = float(m.get("confidence") or 0)
                if not a or not b or a is b:
                    continue
                shared = (set(a["rep_key"].split()) & set(b["rep_key"].split())) - GENERIC
                ok = a["intent"] == b["intent"] and conf >= 0.7 and bool(shared)
                await log_decision(run_id, "CLUSTER_MERGE", f"{a['cluster_id']}+{b['cluster_id']}", f"LLM propone merge ({m.get('motivo', '')[:120]}) → {'APPLICATO' if ok else 'RIFIUTATO'} dalle regole (stesso intent={a['intent'] == b['intent']}, token condivisi={sorted(shared)}, conf={conf})",
                                   confidence=conf, result="APPLIED" if ok else "REJECTED", kind="cluster", source="LLM_SUGGESTION")
                if ok:
                    union(a["rep_key"], b["rep_key"])
                    llm_merges["applied"] += 1
                else:
                    llm_merges["rejected"] += 1
    clusters = _assemble(keys, find, groups, intent_of)
    # metrics + pages + trend
    cur7 = aggregate(await window("query", 7, 0), "query")
    prev7 = aggregate(await window("query", 7, 7), "query")
    n = 0
    seen_ids = []
    for c in clusters.values():
        members = c.pop("_members")
        gsc_q = [k for k in members if (k.get("metrics") or {}).get("source") == "GSC"]
        imps = sum((k["metrics"]["impressions_28"] or 0) for k in gsc_q) if gsc_q else None
        clicks = sum((k["metrics"]["clicks_28"] or 0) for k in gsc_q) if gsc_q else None
        pos = round(sum((k["metrics"]["position_28"] or 0) * (k["metrics"]["impressions_28"] or 0) for k in gsc_q) / imps, 1) if imps else None
        c7 = sum(cur7.get(k["keyword"], {}).get("impressions", 0) for k in gsc_q) if gsc_q else None
        p7 = sum(prev7.get(k["keyword"], {}).get("impressions", 0) for k in gsc_q) if gsc_q else None
        pages: Dict[str, dict] = {}
        for k in gsc_q:
            for p, pm in (pages_by_query.get(k["keyword"]) or {}).items():
                a = pages.setdefault(p, {"impressions": 0, "clicks": 0})
                a["impressions"] += pm["impressions"]; a["clicks"] += pm["clicks"]
        page_rows = sorted(({"page": p, **v} for p, v in pages.items()), key=lambda x: -x["impressions"])
        tot_p = sum(p["impressions"] for p in page_rows) or 0
        competing = [p for p in page_rows if tot_p and p["impressions"] / tot_p >= 0.2]
        primary = (max(gsc_q, key=lambda k: k["metrics"]["impressions_28"] or 0) if gsc_q else
                   next((k for k in members if "SEED" in k.get("sources", [])), None) or min(members, key=lambda k: len(k["keyword"])))
        doc = {
            "cluster_id": c["cluster_id"], "rep_key": c["rep_key"], "intent": c["intent"], "primary_keyword": primary["keyword"],
            "keywords": [k["keyword"] for k in members], "secondary_keywords": [k["keyword"] for k in members if k is not primary][:30], "n_keywords": len(members),
            "sources": sorted({s for k in members for s in k.get("sources", [])}), "creator_slug": next((k.get("creator_slug") for k in members if k.get("creator_slug")), None),
            "category_slug": next((k.get("category_slug") for k in members if k.get("category_slug")), None),
            "gsc_queries": [{"query": k["keyword"], **{kk: k["metrics"].get(kk) for kk in ("impressions_28", "clicks_28", "ctr_28", "position_28")}} for k in gsc_q],
            "metrics": {"source": "GSC" if gsc_q else "UNKNOWN", "impressions_28": imps, "clicks_28": clicks, "ctr_28": (round(100.0 * clicks / imps, 2) if imps else None), "position_28": pos, "impressions_7": c7, "impressions_prev7": p7},
            "trend": _trend(c7, p7), "pages": page_rows[:5], "current_page": page_rows[0]["page"] if page_rows else None,
            "cannibalization": {"risk": "HIGH" if len(competing) >= 2 and all(p["impressions"] / tot_p >= 0.3 for p in competing[:2]) else "MEDIUM" if len(competing) >= 2 else "LOW", "pages": [p["page"] for p in competing]} if page_rows else {"risk": "UNKNOWN", "pages": []},
            "updated_at": now_iso(), "run_id": run_id,
        }
        await clusters_col.update_one({"cluster_id": doc["cluster_id"]}, {"$set": doc, "$setOnInsert": {"created_at": now_iso(), "opportunity_status": "NEW"}}, upsert=True)
        await keywords_col.update_many({"norm": {"$in": [k["norm"] for k in members]}}, {"$set": {"cluster_id": doc["cluster_id"]}})
        seen_ids.append(doc["cluster_id"])
        n += 1
    stale = await clusters_col.count_documents({"cluster_id": {"$nin": seen_ids}})
    if stale:
        await clusters_col.update_many({"cluster_id": {"$nin": seen_ids}}, {"$set": {"stale": True}})
    await log_decision(run_id, "CLUSTERING", "clusters", f"{n} cluster da {len(keywords)} keyword; merge LLM applicati {llm_merges['applied']}, rifiutati {llm_merges['rejected']}", metrics={"clusters": n, "llm": llm_merges, "stale": stale}, kind="cluster")
    return {"clusters": n, "llm": llm_merges, "stale": stale}


def _majority_intent(members: List[dict]) -> str:
    counts: Dict[str, float] = {}
    for m in members:
        counts[m.get("intent") or "OTHER"] = counts.get(m.get("intent") or "OTHER", 0) + (m.get("intent_confidence") or 0.5)
    return max(counts, key=counts.get)


def _assemble(keys, find, groups, intent_of) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for k in keys:
        root = find(k)
        c = out.setdefault(root, {"cluster_id": _cid(root), "rep_key": root, "intent": intent_of[root], "_members": [], "primary_keyword": "", "keywords": []})
        c["_members"].extend(groups[k])
        c["keywords"] = [m["keyword"] for m in c["_members"]]
        c["primary_keyword"] = c["keywords"][0]
    return out


async def pages_by_query_map() -> Dict[str, Dict[str, dict]]:
    """query -> {page: {impressions, clicks}} from the 28-day query+page snapshots."""
    out: Dict[str, Dict[str, dict]] = {}
    for r in await window("query_page", 28, 0):
        a = out.setdefault(r["query"], {}).setdefault(r["page"], {"impressions": 0, "clicks": 0})
        a["impressions"] += r["impressions"]; a["clicks"] += r["clicks"]
    return out


async def load_clusters(include_stale: bool = False) -> List[dict]:
    q = {} if include_stale else {"stale": {"$ne": True}}
    return [d async for d in clusters_col.find(q, {"_id": 0})]
