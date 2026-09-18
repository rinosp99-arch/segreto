"""Model database analysis (rule 14): only REAL published data (name, slug, categories, tags, bio, declared editorial traits,
state, available contents). Builds the keyword/category <-> creator matrix used by the planner. Nothing is inferred."""
from typing import Dict, List

from database import models_col, categories_col

from .store import matrix_col, now_iso
from .textnorm import norm_key, tokens


async def analyse(run_id=None) -> dict:
    cats = {c["slug"]: c async for c in categories_col.find({"is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "nome": 1, "stato": 1, "descrizione": 1, "seo": 1, "indicizzabile": 1})}
    creators: List[dict] = []
    term_index: Dict[str, List[str]] = {}       # normalized term -> [slugs]
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "nome": 1, "nome_artistico": 1, "slug": 1, "categorie": 1, "tag": 1, "bio": 1, "bio_segreta": 1, "frase": 1, "badge": 1, "seo": 1, "anteprima": 1,
                                                                                                      "media_pairs": 1, "galleria_pubblica": 1, "galleria_segreta": 1, "pellicola_home": 1, "social": 1, "onlyfans_url": 1, "updated_at": 1}):
        pairs = m.get("media_pairs") or []
        n_video = sum(1 for p in pairs if (p.get("pubblico") or {}).get("tipo") == "video" or (p.get("segreto") or {}).get("tipo") == "video")
        seo = m.get("seo") or {}
        c = {
            "slug": m["slug"], "id": m["id"], "nome": m.get("nome_artistico") or m.get("nome"), "stato": "pubblicata", "indexable": seo.get("indexable", True) is not False and not m.get("anteprima"),
            "categorie": [c for c in (m.get("categorie") or []) if c in cats], "categorie_sconosciute": [c for c in (m.get("categorie") or []) if c not in cats],
            "tag": sorted(set(t.lower() for t in (m.get("tag") or []))), "badge": m.get("badge"),
            "bio_len": len(m.get("bio") or ""), "bio_segreta_len": len(m.get("bio_segreta") or ""), "frase": m.get("frase"),
            "title": seo.get("title"), "meta_description": seo.get("meta_description"),
            "contenuti": {"media_pairs": len(pairs), "video": n_video, "galleria_pubblica": len(m.get("galleria_pubblica") or []), "galleria_segreta": len(m.get("galleria_segreta") or []),
                          "pellicola_home": bool((m.get("pellicola_home") or {}).get("attiva")), "social": [k for k, v in (m.get("social") or {}).items() if v and k != "custom"], "onlyfans": bool(m.get("onlyfans_url"))},
            "termini": [], "updated_at": m.get("updated_at"), "analysed_at": now_iso(),
        }
        # real terms that describe this creator: name tokens, category names, tags (no invention)
        terms = set()
        for t in tokens(c["nome"] or ""):
            if len(t) > 2:
                terms.add(t)
        for cs in c["categorie"]:
            terms.add(norm_key(cats[cs].get("nome") or cs))
            terms.add(norm_key(cs))
        for t in c["tag"]:
            terms.add(norm_key(t))
        c["termini"] = sorted(x for x in terms if x)
        for t in c["termini"]:
            term_index.setdefault(t, []).append(c["slug"])
        creators.append(c)
        await matrix_col.update_one({"slug": c["slug"]}, {"$set": c}, upsert=True)
    slugs = {c["slug"] for c in creators}
    stale = [d["slug"] async for d in matrix_col.find({"slug": {"$nin": list(slugs)}}, {"_id": 0, "slug": 1})]
    if stale:
        await matrix_col.delete_many({"slug": {"$in": stale}})
    cat_rows = []
    for slug, cdoc in cats.items():
        members = [c["slug"] for c in creators if slug in c["categorie"]]
        cat_rows.append({"slug": slug, "nome": cdoc.get("nome"), "stato": cdoc.get("stato"), "indicizzabile": cdoc.get("indicizzabile", True), "creator": members, "n": len(members),
                         "has_description": bool(cdoc.get("descrizione")), "has_seo_title": bool((cdoc.get("seo") or {}).get("title"))})
    tag_rows = sorted(({"tag": t, "creator": s, "n": len(s)} for t, s in term_index.items()), key=lambda x: -x["n"])
    return {"creators": creators, "categories": cat_rows, "terms": tag_rows, "term_index": term_index,
            "summary": {"pubblicate": len(creators), "senza_tag": sum(1 for c in creators if not c["tag"]), "senza_categorie": sum(1 for c in creators if not c["categorie"]),
                        "senza_bio": sum(1 for c in creators if c["bio_len"] < 40), "senza_video": sum(1 for c in creators if c["contenuti"]["video"] == 0), "categorie_pubblicate": sum(1 for r in cat_rows if r["stato"] == "pubblicata"),
                        "categorie_vuote": [r["slug"] for r in cat_rows if r["stato"] == "pubblicata" and r["n"] == 0]}}


async def load_matrix() -> List[dict]:
    return [d async for d in matrix_col.find({}, {"_id": 0})]
