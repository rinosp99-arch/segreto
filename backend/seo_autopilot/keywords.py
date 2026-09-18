"""Keyword discovery engine (rules 4-5): seeds + GSC queries + real model database + LLM suggestions (advisory).
Every keyword carries its sources and ONLY GSC-backed metrics; otherwise metrics.source = UNKNOWN and
search_volume = DATA_SOURCE_UNAVAILABLE. Mechanical combinations are limited to REAL categories with published creators."""
from typing import Dict, List, Optional

from database import config_col

from . import llm
from .gsc_sync import window, aggregate
from .intent import classify
from .store import keywords_col, log_decision, now_iso
from .textnorm import norm_key, canon_tokens

SEEDS = [
    "ragazze OnlyFans italiane", "ragazze OF", "ragazze OF italiane", "ragazze italiane OnlyFans", "modelle OnlyFans italiane", "modelle OF italiane",
    "profili OnlyFans italiani", "profili OF italiani", "creator OnlyFans italiane", "creator OF italiane", "OnlyFans italiane", "ragazze su OnlyFans", "modelle italiane su OnlyFans",
]
SECTOR_TOKENS = {"onlyfans", "creator", "modelle", "ragazze", "profili", "lato", "segreto"}
UNKNOWN_METRICS = {"source": "UNKNOWN", "impressions_28": None, "clicks_28": None, "ctr_28": None, "position_28": None}


async def brand_name() -> str:
    c = await config_col.find_one({"id": "global"}, {"_id": 0, "site": 1}) or {}
    return ((c.get("site") or {}).get("brand") or "LATO SEGRETO").lower()


def _pertinent(kw: str, creator_terms: set) -> bool:
    """A candidate must carry a sector token or a real creator/category/tag term — otherwise it is off-topic noise."""
    toks = canon_tokens(kw)
    return bool(toks & SECTOR_TOKENS) or bool(toks & creator_terms)


async def build_universe(run_id: Optional[str], matrix: dict, use_llm: bool = True) -> dict:
    brand = await brand_name()
    creators = matrix["creators"]
    cats = [c for c in matrix["categories"] if c["stato"] == "pubblicata"]
    creator_names = [c["nome"] for c in creators if c.get("nome")]
    creator_terms = set(matrix.get("term_index", {}).keys())
    cand: Dict[str, dict] = {}

    def add(kw: str, source: str, extra: Optional[dict] = None):
        kw = " ".join((kw or "").split())
        if len(kw) < 3 or len(kw) > 90:
            return
        k = norm_key(kw)
        if not k:
            return
        d = cand.setdefault(k, {"keyword": kw, "norm": k, "sources": set(), "llm": None})
        d["sources"].add(source)
        if extra:
            d.update(extra)

    for s in SEEDS:
        add(s, "SEED")
    add(brand, "BRAND"); add(f"{brand} onlyfans", "BRAND"); add(f"{brand} modelle", "BRAND")
    for c in creators:                                            # real creator names only
        if c.get("nome") and c.get("indexable", True):
            add(c["nome"], "DB_CREATOR", {"creator_slug": c["slug"]})
            add(f"{c['nome']} onlyfans", "DB_CREATOR", {"creator_slug": c["slug"]})
    for cat in cats:                                              # real categories WITH published creators only (no empty doorway intents)
        if cat["n"] >= 1:
            nome = (cat["nome"] or cat["slug"]).lower()
            add(f"modelle {nome} onlyfans", "DB_CATEGORY", {"category_slug": cat["slug"]})
            add(f"ragazze {nome} onlyfans italiane", "DB_CATEGORY", {"category_slug": cat["slug"]})
    # GSC: real queries Google already associates with the site (28 available days)
    gsc = aggregate(await window("query", 28, 0), "query")
    for q in gsc:
        add(q, "GSC")
    # LLM variants (advisory, filtered for pertinence, tagged)
    llm_info = {"used": False}
    if use_llm and llm.available():
        res = await llm.suggest_variants(SEEDS + list(gsc)[:20], creator_names, [c["nome"] for c in cats], sorted({t for c in creators for t in c["tag"]}))
        llm_info = {"used": res.get("available", False), "cached": res.get("cached"), "reason": res.get("reason"), "model": res.get("model")}
        if res.get("available"):
            n_ok, n_drop = 0, 0
            for v in (res["data"].get("variants") or [])[:120]:
                kw = str(v.get("keyword") or "").strip()
                if kw and _pertinent(kw, creator_terms):
                    add(kw, "LLM_SUGGESTION", {"llm": {"intent": v.get("intent"), "motivo": v.get("motivo"), "seed": v.get("seed")}})
                    n_ok += 1
                else:
                    n_drop += 1
            llm_info.update({"accepted": n_ok, "dropped_not_pertinent": n_drop})
    # persist (upsert by norm: keeps first_seen; metrics only from GSC)
    n_new, n_upd, by_source = 0, 0, {}
    for k, d in cand.items():
        m = gsc.get(d["keyword"]) or next((v for q, v in gsc.items() if norm_key(q) == k), None)
        metrics = {"source": "GSC", "impressions_28": m["impressions"], "clicks_28": m["clicks"], "ctr_28": m["ctr"], "position_28": m["position"], "days_28": m["days"]} if m else dict(UNKNOWN_METRICS)
        intent, conf, why = classify(d["keyword"], creator_names, [c["nome"] for c in cats] + [c["slug"] for c in cats], sorted({t for c in creators for t in c["tag"]}), brand)
        doc = {"keyword": d["keyword"], "norm": k, "sources": sorted(d["sources"]), "metrics": metrics, "search_volume": "DATA_SOURCE_UNAVAILABLE",
               "intent": intent, "intent_confidence": conf, "intent_reason": why, "intent_source": "RULES", "llm": d.get("llm"), "creator_slug": d.get("creator_slug"), "category_slug": d.get("category_slug"),
               "pertinent": _pertinent(d["keyword"], creator_terms), "last_seen": now_iso(), "run_id": run_id}
        r = await keywords_col.update_one({"norm": k}, {"$set": doc, "$setOnInsert": {"first_seen": now_iso()}}, upsert=True)
        if r.upserted_id is not None:
            n_new += 1
        else:
            n_upd += 1
        for s in d["sources"]:
            by_source[s] = by_source.get(s, 0) + 1
    total = await keywords_col.count_documents({})
    await log_decision(run_id, "KEYWORD_UNIVERSE", "universe", f"{total} keyword totali ({n_new} nuove, {n_upd} aggiornate); GSC {by_source.get('GSC', 0)}, LLM {by_source.get('LLM_SUGGESTION', 0)}", metrics={"by_source": by_source, "llm": llm_info}, kind="discovery")
    return {"total": total, "new": n_new, "updated": n_upd, "by_source": by_source, "gsc_queries": len(gsc), "llm": llm_info}


async def load_keywords() -> List[dict]:
    return [d async for d in keywords_col.find({}, {"_id": 0})]
