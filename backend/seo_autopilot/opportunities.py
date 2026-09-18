"""Opportunity engine (rules 8-9) + keyword->page map (10) + cannibalization (11) + weekly learning (20) + backlog (21).
All outputs are RECOMMENDATIONS: nothing is executed in READ_ONLY. Every finding has a readable reason and the metrics used."""
import hashlib
from typing import Dict, List, Optional


from .gsc_sync import window, compare_windows
from .store import (opportunities_col, page_map_col, cannibal_col, backlog_col, clusters_col, state_col, log_decision, now_iso)
from .textnorm import similarity, canon_tokens

MIN_IMP_A, MIN_IMP_B, MIN_IMP_C, MIN_IMP_F = 50, 100, 10, 50
EXPECTED_CTR = {1: 25.0, 2: 15.0, 3: 10.0, 4: 7.0, 5: 5.5, 6: 4.5, 7: 3.5, 8: 3.0, 9: 2.5, 10: 2.2}   # indicative curve, used only as a ratio


def expected_ctr(pos: Optional[float]) -> Optional[float]:
    if pos is None:
        return None
    p = int(round(pos))
    return EXPECTED_CTR.get(p, 1.5 if p <= 20 else 0.8)


def _fp(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


async def _upsert_opp(run_id, rule, target, kind, score, reason, metrics, action, extra=None):
    fp = _fp(rule, target)
    doc = {"fingerprint": fp, "rule": rule, "target": target, "target_kind": kind, "score": score, "reason": reason, "metrics": metrics, "suggested_action": action, "run_id": run_id,
           "updated_at": now_iso(), "status": "OPEN", "executable": False, **(extra or {})}
    await opportunities_col.update_one({"fingerprint": fp}, {"$set": doc, "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
    await log_decision(run_id, f"OPPORTUNITY_{rule}", target, f"[{score}] {reason}", metrics=metrics, confidence={"HIGH": 0.8, "MEDIUM": 0.6, "LOW": 0.4, "HOLD": 0.3}[score], kind="opportunity")
    return doc


async def run_opportunities(run_id: Optional[str], clusters: List[dict], matrix: dict) -> dict:
    counts = {"A_GROWTH": 0, "B_SNIPPET": 0, "C_NEW_QUERY": 0, "D_NO_PAGE": 0, "E_CANNIBALIZATION": 0, "F_DECLINE": 0, "by_score": {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "HOLD": 0}}
    seen = []

    async def emit(rule, target, kind, score, reason, metrics, action, extra=None):
        d = await _upsert_opp(run_id, rule, target, kind, score, reason, metrics, action, extra)
        counts[rule] += 1; counts["by_score"][score] += 1; seen.append(d["fingerprint"])

    creators_by_term = matrix.get("term_index", {})
    for c in clusters:
        m = c.get("metrics") or {}
        imps, pos, ctr = m.get("impressions_28"), m.get("position_28"), m.get("ctr_28")
        label = f"{c['primary_keyword']} ({c['cluster_id']})"
        pertinent_creators = sorted({s for t in canon_tokens(c["primary_keyword"]) for s in creators_by_term.get(t, [])})
        # A) impressions + position 5-20
        if imps is not None and imps >= MIN_IMP_A and pos is not None and 5 <= pos <= 20:
            score = "HIGH" if imps >= 200 and pos <= 12 else "MEDIUM"
            await emit("A_GROWTH", label, "cluster", score, f"{imps} impression in 28g con posizione media {pos}: portare la pagina in top 5 può moltiplicare i click", {"impressions_28": imps, "position_28": pos, "ctr_28": ctr, "page": c.get("current_page")}, "UPDATE", {"cluster_id": c["cluster_id"], "page": c.get("current_page")})
        # B) impressions + low CTR vs expected for that position
        exp = expected_ctr(pos)
        if imps is not None and imps >= MIN_IMP_B and ctr is not None and exp and ctr < exp * 0.5:
            await emit("B_SNIPPET", label, "cluster", "MEDIUM" if imps < 500 else "HIGH", f"CTR {ctr}% contro ~{exp}% atteso in posizione {pos}: title/description dello snippet da rivedere", {"impressions_28": imps, "ctr_28": ctr, "expected_ctr": exp, "position_28": pos, "page": c.get("current_page")}, "UPDATE", {"cluster_id": c["cluster_id"], "page": c.get("current_page")})
        # C) new query growing
        if (c.get("trend") or {}).get("status") == "NEW" and (m.get("impressions_7") or 0) >= MIN_IMP_C:
            await emit("C_NEW_QUERY", label, "cluster", "MEDIUM", f"query nuova: {m.get('impressions_7')} impression negli ultimi 7g, nessuna nei 7 precedenti", {"impressions_7": m.get("impressions_7"), "impressions_prev7": m.get("impressions_prev7")}, "REVIEW", {"cluster_id": c["cluster_id"]})
        # D) pertinent cluster with no adequate page (neither a GSC-observed page nor a natural structural page; the Home is a generic fallback, not a dedicated page)
        cats_pub = {x["slug"]: x for x in matrix["categories"] if x["stato"] == "pubblicata"}
        has_structural = (c["intent"] == "CATEGORY" and c.get("category_slug") in cats_pub and cats_pub[c["category_slug"]]["n"] >= 1) or (c["intent"] == "CREATOR" and c.get("creator_slug"))
        if not c.get("current_page") and not has_structural and c["intent"] in ("DISCOVERY", "CATEGORY", "INFORMATIONAL"):
            n_cr = len(pertinent_creators) if c["intent"] == "CATEGORY" else matrix["summary"]["pubblicate"]
            if imps is None:
                score, why = "HOLD", "nessun dato Search Console per questo cluster (metriche UNKNOWN): possibile futura landing, da confermare con dati reali"
            elif n_cr < 2:
                score, why = "HOLD", f"solo {n_cr} creator pertinenti nel database: una pagina sarebbe povera (rischio doorway)"
            else:
                score, why = ("HIGH" if imps >= 200 else "MEDIUM" if imps >= 50 else "LOW"), f"{imps} impression senza una pagina dedicata; {n_cr} creator pertinenti disponibili"
            await emit("D_NO_PAGE", label, "cluster", score, why, {"impressions_28": imps, "creator_pertinenti": n_cr, "intent": c["intent"]}, "CREATE" if score != "HOLD" else "HOLD", {"cluster_id": c["cluster_id"], "creators": pertinent_creators[:20]})
        # E) cannibalization inside the cluster
        can = c.get("cannibalization") or {}
        if can.get("risk") in ("MEDIUM", "HIGH"):
            await emit("E_CANNIBALIZATION", label, "cluster", "HIGH" if can["risk"] == "HIGH" else "MEDIUM", f"{len(can['pages'])} pagine competono sulle stesse query: {', '.join(can['pages'][:3])}", {"pages": can["pages"], "impressions_28": imps}, "MERGE" if can["risk"] == "HIGH" else "REVIEW", {"cluster_id": c["cluster_id"], "pages": can["pages"]})
    # F) pages losing impressions (28 vs previous 28)
    cmp = await compare_windows("page", "page", 28)
    for page, cur in cmp["current"].items():
        prev = cmp["previous"].get(page)
        if prev and prev["impressions"] >= MIN_IMP_F and cur["impressions"] < prev["impressions"] * 0.7:
            d = round(100.0 * (cur["impressions"] - prev["impressions"]) / prev["impressions"], 1)
            await emit("F_DECLINE", page, "page", "HIGH" if d <= -50 else "MEDIUM", f"impression {prev['impressions']} → {cur['impressions']} ({d}%) in 28g; posizione {prev['position']} → {cur['position']}", {"impressions_prev28": prev["impressions"], "impressions_28": cur["impressions"], "delta_pct": d, "position_prev": prev["position"], "position": cur["position"]}, "REVIEW", {"page": page})
    for page, prev in cmp["previous"].items():
        if page not in cmp["current"] and prev["impressions"] >= MIN_IMP_F:
            await emit("F_DECLINE", page, "page", "HIGH", f"pagina sparita da Search Console: {prev['impressions']} impression nei 28g precedenti, 0 negli ultimi 28g", {"impressions_prev28": prev["impressions"], "impressions_28": 0}, "REVIEW", {"page": page})
    closed = await opportunities_col.update_many({"fingerprint": {"$nin": seen}, "status": "OPEN"}, {"$set": {"status": "RESOLVED", "resolved_at": now_iso(), "resolved_reason": "condizione non più presente"}})
    counts["resolved"] = closed.modified_count
    return counts


# ------------------------------------------------------------------------------------------------ page map
async def build_page_map(run_id: Optional[str], clusters: List[dict], matrix: dict, base_url: str) -> dict:
    """CLUSTER -> current page -> future action (KEEP/UPDATE/EXPAND/CREATE/MERGE/REVIEW/HOLD). Recommendations only."""
    opps = {}
    async for o in opportunities_col.find({"status": "OPEN", "cluster_id": {"$exists": True}}, {"_id": 0}):
        opps.setdefault(o["cluster_id"], []).append(o)
    cats = {c["slug"]: c for c in matrix["categories"]}
    creators = {c["slug"]: c for c in matrix["creators"]}
    counts: Dict[str, int] = {}
    for c in clusters:
        page = c.get("current_page")
        inferred = None
        if not page:                                      # infer the natural page from the site structure (no GSC needed)
            if c["intent"] == "CREATOR" and c.get("creator_slug") in creators:
                inferred = f"{base_url}/modelle/{c['creator_slug']}"
            elif c["intent"] == "CATEGORY" and c.get("category_slug") in cats and cats[c["category_slug"]]["stato"] == "pubblicata":
                inferred = f"{base_url}/categorie/{c['category_slug']}"
            elif c["intent"] in ("BRANDED", "DISCOVERY"):
                inferred = f"{base_url}/"
        target_page = page or inferred
        rules = {o["rule"]: o for o in opps.get(c["cluster_id"], [])}
        m = c.get("metrics") or {}
        if "E_CANNIBALIZATION" in rules:
            action, why = ("MERGE" if rules["E_CANNIBALIZATION"]["score"] == "HIGH" else "REVIEW"), rules["E_CANNIBALIZATION"]["reason"]
        elif not target_page:
            d = rules.get("D_NO_PAGE")
            action, why = (("CREATE" if d["score"] != "HOLD" else "HOLD"), d["reason"]) if d else ("HOLD", "nessuna pagina naturale e nessun dato: in osservazione")
        elif c["intent"] == "CATEGORY" and c.get("category_slug") in cats and cats[c["category_slug"]]["n"] < 2:
            action, why = "HOLD", f"categoria '{c['category_slug']}' con {cats[c['category_slug']]['n']} creator: contenuto insufficiente"
        elif "A_GROWTH" in rules or "B_SNIPPET" in rules:
            action, why = "UPDATE", (rules.get("A_GROWTH") or rules.get("B_SNIPPET"))["reason"]
        elif c["n_keywords"] >= 5 and m.get("source") == "GSC":
            action, why = "EXPAND", f"{c['n_keywords']} varianti nel cluster: la pagina può coprire meglio le long-tail"
        elif (c.get("trend") or {}).get("status") == "DECLINING":
            action, why = "REVIEW", f"cluster in calo ({c['trend'].get('delta_pct')}% impression 7g vs 7g)"
        else:
            action, why = "KEEP", "pagina coerente con l'intento; nessun segnale che richieda intervento" if m.get("source") == "GSC" else "pagina naturale presente; metriche GSC non ancora disponibili (UNKNOWN)"
        doc = {"cluster_id": c["cluster_id"], "primary_keyword": c["primary_keyword"], "intent": c["intent"], "current_page": page, "inferred_page": inferred, "page": target_page, "page_source": "GSC" if page else ("STRUCTURE" if inferred else None),
               "action": action, "reason": why, "metrics": m, "executable": False, "updated_at": now_iso(), "run_id": run_id}
        await page_map_col.update_one({"cluster_id": c["cluster_id"]}, {"$set": doc}, upsert=True)
        counts[action] = counts.get(action, 0) + 1
    await page_map_col.delete_many({"cluster_id": {"$nin": [c["cluster_id"] for c in clusters]}})   # rows of stale clusters
    await log_decision(run_id, "PAGE_MAP", "page_map", f"mappa cluster→pagina→azione aggiornata: {counts}", metrics=counts, kind="page_map")
    return counts


# ------------------------------------------------------------------------------------------------ cannibalization
async def run_cannibalization(run_id: Optional[str], clusters: List[dict]) -> dict:
    found = []
    # 1) same query, several URLs (GSC query+page)
    per_q: Dict[str, Dict[str, int]] = {}
    for r in await window("query_page", 28, 0):
        per_q.setdefault(r["query"], {}).setdefault(r["page"], 0)
        per_q[r["query"]][r["page"]] += r["impressions"]
    for q, pages in per_q.items():
        tot = sum(pages.values())
        comp = {p: v for p, v in pages.items() if tot and v / tot >= 0.2}
        if len(comp) >= 2 and tot >= 20:
            risk = "HIGH" if sorted(comp.values())[-2] / tot >= 0.3 else "MEDIUM"
            found.append({"type": "SAME_QUERY", "risk": risk, "query": q, "urls": sorted(comp, key=lambda p: -comp[p]), "reason": f"la query '{q}' mostra {len(comp)} URL diversi ({tot} impression)", "metrics": comp})
    # 2) clusters with the same intent and overlapping tokens mapped to different pages
    mapped = [c for c in clusters if c.get("current_page")]
    for i, a in enumerate(mapped):
        for b in mapped[i + 1:]:
            if a["intent"] == b["intent"] and a["current_page"] != b["current_page"] and similarity(a["primary_keyword"], b["primary_keyword"]) >= 0.6:
                found.append({"type": "OVERLAPPING_CLUSTERS", "risk": "MEDIUM", "urls": [a["current_page"], b["current_page"]], "clusters": [a["cluster_id"], b["cluster_id"]],
                              "reason": f"cluster '{a['primary_keyword']}' e '{b['primary_keyword']}' (stesso intent {a['intent']}) rankano su pagine diverse", "metrics": {"similarity": round(similarity(a["primary_keyword"], b["primary_keyword"]), 2)}})
    # 3) very similar title / H1 across RENDERED pages (the initial HTML of a SPA is identical everywhere: not a signal)
    from .render_audit import latest_docs
    pages = [{"url": d["url"], "title": (d.get("rendered") or {}).get("title"), "h1": (d.get("rendered") or {}).get("h1") or [], "page_type": d.get("page_type")} for d in await latest_docs(80) if (d.get("rendered") or {}).get("title")]

    def strip_brand(t):
        return (t or "").split("|")[0].split("—")[0].strip()
    h1_first = [(p.get("h1") or [""])[0].strip().lower() for p in pages]
    same_h1_all = len(pages) >= 3 and len(set(h1_first)) == 1 and h1_first[0]
    # (an H1 identical on EVERY page is reported once by the render audit as H1_BRAND_ONLY_SITEWIDE, not here)
    for i, a in enumerate(pages):
        for b in pages[i + 1:]:
            ta, tb = strip_brand(a.get("title")), strip_brand(b.get("title"))
            if ta and tb and len(ta) > 8 and (a.get("title") or "").lower() != (b.get("title") or "").lower() and similarity(ta, tb) >= 0.8:
                found.append({"type": "SIMILAR_TITLE", "risk": "LOW" if a.get("page_type") != b.get("page_type") else "MEDIUM", "urls": [a["url"], b["url"]], "reason": f"title renderizzati quasi identici: '{ta}' vs '{tb}'", "metrics": {"similarity": round(similarity(ta, tb), 2)}})
            if not same_h1_all:
                ha, hb = (a.get("h1") or [""])[0], (b.get("h1") or [""])[0]
                if ha and hb and len(ha) > 8 and ha.lower() == hb.lower():
                    found.append({"type": "SAME_H1", "risk": "MEDIUM", "urls": [a["url"], b["url"]], "reason": f"H1 identico: '{ha}'", "metrics": {}})
    seen = []
    for f in found:
        fp = _fp(f["type"], *sorted(f["urls"]), f.get("query", ""))
        doc = {"fingerprint": fp, "CANNIBALIZATION_RISK": f["risk"], "status": "OPEN", "updated_at": now_iso(), "run_id": run_id, **f}
        await cannibal_col.update_one({"fingerprint": fp}, {"$set": doc, "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
        seen.append(fp)
        await log_decision(run_id, "CANNIBALIZATION", " + ".join(f["urls"][:2]), f"[{f['risk']}] {f['reason']}", metrics=f.get("metrics"), kind="cannibalization")
    await cannibal_col.update_many({"fingerprint": {"$nin": seen}, "status": "OPEN"}, {"$set": {"status": "RESOLVED", "resolved_at": now_iso()}})
    by = {}
    for f in found:
        by[f["risk"]] = by.get(f["risk"], 0) + 1
    return {"found": len(found), "by_risk": by}


# ------------------------------------------------------------------------------------------------ weekly learning
async def weekly_learning(run_id: Optional[str]) -> dict:
    out = {}
    for label, days in (("7v7", 7), ("28v28", 28)):
        for dims, by in (("query", "query"), ("page", "page")):
            cmp = await compare_windows(dims, by, days)
            status: Dict[str, List[str]] = {"GROWING": [], "STABLE": [], "DECLINING": [], "NEW": []}
            for k, cur in cmp["current"].items():
                prev = cmp["previous"].get(k)
                if not prev:
                    if cur["impressions"] >= 5:
                        status["NEW"].append(k)
                    continue
                d = (cur["impressions"] - prev["impressions"]) / prev["impressions"] if prev["impressions"] else 0
                status["GROWING" if d >= 0.2 else "DECLINING" if d <= -0.2 else "STABLE"].append(k)
            out[f"{by}_{label}"] = {k: len(v) for k, v in status.items()} | {"top_growing": status["GROWING"][:10], "top_declining": status["DECLINING"][:10], "new": status["NEW"][:10], "data": bool(cmp["current"] or cmp["previous"])}
    # clusters trend recount
    trend_counts: Dict[str, int] = {}
    async for c in clusters_col.find({"stale": {"$ne": True}}, {"_id": 0, "trend": 1}):
        s = (c.get("trend") or {}).get("status", "UNKNOWN")
        trend_counts[s] = trend_counts.get(s, 0) + 1
    out["clusters_trend"] = trend_counts
    focus = [f"{k}: {v['GROWING']} in crescita, {v['DECLINING']} in calo, {v['NEW']} nuove" for k, v in out.items() if isinstance(v, dict) and "GROWING" in v]
    await state_col.update_one({"id": "global"}, {"$set": {"weekly_learning": {"at": now_iso(), "result": out, "focus": focus}}}, upsert=True)
    await log_decision(run_id, "WEEKLY_LEARNING", "learning", "; ".join(focus) or "nessun dato storico sufficiente (servono almeno 14 giorni di snapshot)", metrics=trend_counts, kind="learning")
    return out


# ------------------------------------------------------------------------------------------------ backlog
PRIORITY = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "HOLD": 0}


async def rebuild_backlog(run_id: Optional[str], tech_findings: List[dict]) -> dict:
    items = []
    async for o in opportunities_col.find({"status": "OPEN"}, {"_id": 0}):
        if o["score"] == "HOLD":
            continue
        items.append({"fingerprint": "opp:" + o["fingerprint"], "action": o["suggested_action"], "target": o["target"], "reason": o["reason"], "metrics": o.get("metrics"), "score": o["score"], "priority": PRIORITY[o["score"]] * 10 + min(9, int((o.get("metrics") or {}).get("impressions_28") or 0) // 100), "source": "opportunity", "rule": o["rule"]})
    async for cnb in cannibal_col.find({"status": "OPEN", "CANNIBALIZATION_RISK": {"$in": ["MEDIUM", "HIGH"]}}, {"_id": 0}):
        items.append({"fingerprint": "can:" + cnb["fingerprint"], "action": "MERGE" if cnb["CANNIBALIZATION_RISK"] == "HIGH" else "REVIEW", "target": " + ".join(cnb["urls"][:2]), "reason": cnb["reason"], "metrics": cnb.get("metrics"), "score": cnb["CANNIBALIZATION_RISK"], "priority": PRIORITY[cnb["CANNIBALIZATION_RISK"]] * 10, "source": "cannibalization", "rule": cnb["type"]})
    for t in tech_findings:
        if t.get("severity") in ("CRITICAL", "HIGH", "MEDIUM"):
            sc = {"CRITICAL": "HIGH", "HIGH": "HIGH", "MEDIUM": "MEDIUM"}[t["severity"]]
            items.append({"fingerprint": "tech:" + _fp(t["code"], t.get("url")), "action": "TECH_REVIEW", "target": t.get("url") or "sito", "reason": f"{t['code']}: {t['detail']}", "metrics": {"severity": t["severity"]}, "score": sc, "priority": PRIORITY[sc] * 10 + (5 if t["severity"] == "CRITICAL" else 0), "source": "tech", "rule": t["code"]})
    items.sort(key=lambda x: -x["priority"])
    seen = []
    for rank, it in enumerate(items, 1):
        doc = {**it, "rank": rank, "status": "OPEN", "executable": False, "updated_at": now_iso(), "run_id": run_id}
        await backlog_col.update_one({"fingerprint": it["fingerprint"]}, {"$set": doc, "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
        seen.append(it["fingerprint"])
    await backlog_col.update_many({"fingerprint": {"$nin": seen}, "status": "OPEN"}, {"$set": {"status": "CLOSED", "closed_at": now_iso(), "closed_reason": "condizione non più presente"}})
    by_action: Dict[str, int] = {}
    for it in items:
        by_action[it["action"]] = by_action.get(it["action"], 0) + 1
    await log_decision(run_id, "BACKLOG", "backlog", f"{len(items)} voci aperte: {by_action}", metrics=by_action, kind="backlog")
    return {"open": len(items), "by_action": by_action}
