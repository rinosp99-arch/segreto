"""Landing page planner (rule 12) + content quality gate (rule 13). Produces SEO_DRAFT_PROPOSAL documents that live ONLY in
seo_ap_landing_proposals (no public route, no sitemap, no slug reservation). Rejections are explicit: REJECTED_BY_QUALITY_GATE."""
import re
import unicodedata
from typing import List, Optional

from .store import proposals_col, page_map_col, log_decision, now_iso
from .textnorm import canon_tokens, jaccard, similarity

MIN_CREATORS = {"DISCOVERY": 3, "CATEGORY": 2, "INFORMATIONAL": 2}


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:70]


def _title(primary: str) -> str:
    core = primary.strip()
    core = core[0].upper() + core[1:]
    core = re.sub(r"\bonlyfans\b", "OnlyFans", core, flags=re.I)
    t = f"{core} | LATO SEGRETO"
    return t if len(t) <= 60 else core[:57] + "…"


async def plan(run_id: Optional[str], clusters: List[dict], matrix: dict, base_url: str) -> dict:
    creators = matrix["creators"]
    cats = {c["slug"]: c for c in matrix["categories"]}
    term_index = matrix.get("term_index", {})
    # pages that really cover an intent (GSC-observed pages or structural pages that are NOT the generic home fallback)
    existing_pages = [d async for d in page_map_col.find({"page": {"$ne": None}}, {"_id": 0, "primary_keyword": 1, "intent": 1, "page": 1, "page_source": 1, "inferred_page": 1})]
    existing_pages = [p for p in existing_pages if not (p.get("page_source") == "STRUCTURE" and (p.get("page") or "").rstrip("/") == base_url.rstrip("/"))]
    # candidates: clusters without a page, or DISCOVERY/INFORMATIONAL clusters that only fall back to the home (no dedicated page)
    create_rows = [d async for d in page_map_col.find({"$or": [{"action": {"$in": ["CREATE", "HOLD"]}, "page": None},
                                                                {"intent": {"$in": ["DISCOVERY", "INFORMATIONAL"]}, "page_source": "STRUCTURE", "inferred_page": base_url.rstrip("/") + "/"}]}, {"_id": 0})]
    by_cluster = {c["cluster_id"]: c for c in clusters}
    accepted: List[dict] = []
    counts = {"SEO_DRAFT_PROPOSAL": 0, "REJECTED_BY_QUALITY_GATE": 0}
    seen_slugs = []
    for row in create_rows:
        c = by_cluster.get(row["cluster_id"])
        if not c or c["intent"] not in MIN_CREATORS:
            continue
        ptoks = canon_tokens(c["primary_keyword"])
        if c["intent"] == "DISCOVERY":
            pertinent = [x for x in creators if x.get("indexable", True)]
        else:
            slugs = {s for t in ptoks for s in term_index.get(t, [])}
            pertinent = [x for x in creators if x["slug"] in slugs and x.get("indexable", True)]
        pert_cats = sorted({cs for x in pertinent for cs in x["categorie"]} & {k for k, v in cats.items() if v["stato"] == "pubblicata"})
        slug = slugify(c["primary_keyword"])
        gate: List[dict] = []

        def check(code, ok, detail):
            gate.append({"check": code, "ok": bool(ok), "detail": detail})
        # intento distinto vs pagine esistenti
        clash = [p for p in existing_pages if p["intent"] == c["intent"] and similarity(p["primary_keyword"], c["primary_keyword"]) >= 0.6]
        check("INTENTO_DISTINTO", not clash, "nessuna pagina esistente copre lo stesso intento" if not clash else f"sovrapposizione con {clash[0]['page']} ('{clash[0]['primary_keyword']}')")
        check("CREATOR_REALI", len(pertinent) >= MIN_CREATORS[c["intent"]], f"{len(pertinent)} creator pertinenti (min {MIN_CREATORS[c['intent']]})")
        check("CONTENUTO_SUFFICIENTE", len(pertinent) >= MIN_CREATORS[c["intent"]] and sum(1 for x in pertinent if x["bio_len"] >= 40) >= min(2, len(pertinent)), "bio reali disponibili per il contenuto editoriale")
        check("NO_KEYWORD_STUFFING", len(c.get("secondary_keywords", [])) <= 30 and max([0] + [c["primary_keyword"].lower().count(t) for t in ptoks]) <= 2, "keyword primaria non ripetuta, secondarie limitate")
        dup = [a for a in accepted if jaccard(canon_tokens(a["primary_keyword"]), ptoks) >= 0.6]
        check("NO_DOORWAY", not dup, "nessuna proposta quasi identica già accettata" if not dup else f"quasi identica a '{dup[0]['primary_keyword']}' (doorway)")
        check("NO_DATI_INVENTATI", True, "creator/categorie presi esclusivamente dal database; metriche solo GSC o UNKNOWN")
        risk = "HIGH" if clash else ("MEDIUM" if dup else "LOW")
        check("CANNIBALIZZAZIONE", risk != "HIGH", f"rischio {risk}")
        check("DATI_REALI", (c.get("metrics") or {}).get("source") == "GSC", "supportata da impression Search Console" if (c.get("metrics") or {}).get("source") == "GSC" else "nessun dato GSC: proposta in HOLD finché non arrivano dati reali")
        passed = all(g["ok"] for g in gate if g["check"] != "DATI_REALI")
        status = "SEO_DRAFT_PROPOSAL" if passed else "REJECTED_BY_QUALITY_GATE"
        m = c.get("metrics") or {}
        quality = round(sum(1 for g in gate if g["ok"]) / len(gate), 2)
        doc = {
            "proposed_slug": slug, "cluster_id": c["cluster_id"], "status": status, "hold": not (m.get("source") == "GSC"), "public": False, "executable": False,
            "search_intent": c["intent"], "primary_keyword": c["primary_keyword"], "secondary_keywords": c.get("secondary_keywords", [])[:12],
            "creator_pertinenti": [{"slug": x["slug"], "nome": x["nome"], "categorie": x["categorie"]} for x in pertinent[:24]], "categorie_pertinenti": pert_cats,
            "title_proposto": _title(c["primary_keyword"]), "h1_proposto": c["primary_keyword"][0].upper() + c["primary_keyword"][1:],
            "struttura_contenuto": ["Intro editoriale (cosa trova l'utente, in 2-3 frasi reali)", f"Griglia creator pertinenti ({len(pertinent)}) con card reali", "Come funziona il Lato Segreto (spiegazione breve)"]
                                    + (["FAQ con 3-5 domande reali dell'intento"] if c["intent"] == "INFORMATIONAL" else []) + ["Link interni a categorie e profili pertinenti"],
            "internal_links_suggeriti": [f"{base_url}/"] + [f"{base_url}/categorie/{cs}" for cs in pert_cats[:4]] + [f"{base_url}/modelle/{x['slug']}" for x in pertinent[:8]],
            "query_gsc_collegate": c.get("gsc_queries", [])[:15], "metriche": m,
            "motivo": (row.get("reason") if not row.get("page") else f"intento {c['intent']} coperto solo dalla Home (pagina generica): una landing dedicata potrebbe rispondere meglio; da confermare con dati Search Console reali"),
            "rischio_cannibalizzazione": risk, "quality_gate": gate, "quality_score": quality,
            "updated_at": now_iso(), "run_id": run_id,
        }
        await proposals_col.update_one({"proposed_slug": slug}, {"$set": doc, "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
        seen_slugs.append(slug)
        counts[status] += 1
        if passed:
            accepted.append(doc)
        await log_decision(run_id, "LANDING_PROPOSAL", slug, f"{status}: {'; '.join(g['detail'] for g in gate if not g['ok']) or 'tutti i controlli superati'}", metrics=m, confidence=quality, quality={"passed": passed, "checks": gate}, result=status, kind="planner")
    await proposals_col.update_many({"proposed_slug": {"$nin": seen_slugs}, "status": {"$ne": "ARCHIVED"}}, {"$set": {"status": "ARCHIVED", "archived_at": now_iso(), "archived_reason": "cluster non più in CREATE/HOLD"}})
    return counts
