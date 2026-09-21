"""SEO Autopilot — EXECUTION LAYER ("the hands"), Phase 15.

The analysis brain (engine.py, READ_ONLY) proposes; this module EXECUTES in production, reusing the
existing content pipeline (landings v1, articles, SEO safe-fix, sitemap, internal linking). Every public
write is gated by a DB-driven FULL switch (settings.seo_autopilot_mode == FULL AND settings.seo_autopilot_enabled),
independent from the legacy mode.FULL_LOCKED (which stays locked for the analysis engine + its tests).

Guarantees:
- publish ONLY content that passes the EXISTING quality gate (validate_landing_full for landings, a
  deterministic article gate for articles); otherwise the content stays BOZZA with explicit reasons;
- SEO SAFE-FIX runs first and the gate is re-evaluated after fixes;
- duplicate protection before creating any landing/article (no doorway/near-duplicate);
- article generation is capped (default 1/day) and uses ONLY the existing LLM advisory layer (Emergent key);
- internal linking removes orphans; sitemap stays automatic (published + indexable only).
"""
import re
import uuid
from typing import Optional

from database import settings_col, articles_col, models_col, categories_col, config_col, now_iso
from sanitize import sanitize_html, slugify
from v1_security import actor_of

from . import store, llm
from .store import proposals_col, log_decision

BRAND = "LATO SEGRETO"
# internal principal for server-side writes (no HTTP request); SUPER_ADMIN so v1 services accept it
PRINCIPAL = {"type": "user", "id": "seo-autopilot", "email": "seo-autopilot", "name": "seo-autopilot",
             "role": "SUPER_ADMIN", "source": "seo-autopilot", "scopes": ["*"]}

DEFAULTS = {
    "seo_autopilot_enabled": False,
    "seo_autopilot_mode": "READ_ONLY",   # OFF | READ_ONLY | FULL
    "seo_auto_publish": False,
    "seo_max_articles_per_day": 1,
    "seo_target_country": "IT",
    "seo_language": "it",
    "auto_publish_articles": False,       # webhook (Soro) articles auto-publish
}


# --------------------------------------------------------------------------- settings / flags
async def get_settings() -> dict:
    s = await settings_col.find_one({"id": "global"}, {"_id": 0}) or {}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if s.get(k) is not None:
            out[k] = s[k]
    return out


async def set_settings(patch: dict) -> dict:
    clean = {k: v for k, v in (patch or {}).items() if k in DEFAULTS}
    if clean:
        await settings_col.update_one({"id": "global"}, {"$set": clean}, upsert=True)
    return await get_settings()


async def full_enabled() -> bool:
    s = await get_settings()
    return bool(s["seo_autopilot_enabled"]) and s["seo_autopilot_mode"] == "FULL"


async def _flags() -> dict:
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    return cfg.get("flags") or {}


async def enable_public_landings():
    await config_col.update_one({"id": "global"}, {"$set": {"flags.public_landing_routes": True}}, upsert=True)


async def _mark_sitemap_dirty(reason: str):
    try:
        from google_search.state import mark_sitemap_dirty
        await mark_sitemap_dirty(reason)
    except Exception:
        pass


def _text_len(html: str) -> int:
    return len(re.sub(r"<[^>]+>", "", html or "").strip())


async def _published_model_slugs() -> set:
    return {m["slug"] async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1})}


# --------------------------------------------------------------------------- LANDINGS (from proposals)
def _meta_desc(primary: str, n_models: int) -> str:
    core = primary.strip()
    core = core[0].upper() + core[1:] if core else BRAND
    md = f"{core}: scopri {n_models} creator italiane selezionate su {BRAND}. Profili reali, categorie e link OnlyFans ufficiali."
    if len(md) > 168:
        md = md[:167].rstrip() + "…"
    if len(md) < 60:
        md = (md + f" Esplora il lato segreto di {BRAND}.")[:168]
    return md


def _subtitle(primary: str, n_models: int) -> str:
    return f"Una selezione editoriale di {n_models} creator italiane pertinenti. Profili verificati, categorie tematiche e collegamenti ufficiali."


async def _landing_candidate_from_proposal(p: dict) -> Optional[dict]:
    published = await _published_model_slugs()
    slugs = [c["slug"] for c in (p.get("creator_pertinenti") or []) if c.get("slug") in published][:24]
    if len(slugs) < 2:
        return None
    primary = p.get("primary_keyword") or p.get("h1_proposto") or p.get("proposed_slug")
    title = p.get("title_proposto") or f"{primary} | {BRAND}"
    cats = [c for c in (p.get("categorie_pertinenti") or []) if c][:6]
    faq = []
    return {
        "titolo": (primary or "Landing")[:120],
        "slug": p.get("proposed_slug") or slugify(primary or "landing"),
        "headline": p.get("h1_proposto") or (primary[0].upper() + primary[1:] if primary else "Lato Segreto"),
        "subtitle": _subtitle(primary, len(slugs)),
        "model_slugs": slugs,
        "cta": {"testo": "SCOPRI IL LATO SEGRETO", "url": "/", "stile": "gold", "posizione": "hero"},
        "faq": faq,
        "seo": {"title": title[:65], "meta_description": _meta_desc(primary, len(slugs)),
                "canonical": "", "robots": "index,follow", "og_image": "",
                "structured_data_type": "CollectionPage",
                "keywords": (p.get("secondary_keywords") or [])[:10], "indexable": True},
        "tema": {"modalita": "pubblico"},
        "stato": "bozza",
        "_categorie": cats,
    }


async def publish_landing_from_proposal(p: dict, dry_run: bool = False) -> dict:
    from v1_landings import create_landing, set_landing_state, validate_landing_full, landings_col
    slug = p.get("proposed_slug")
    cand = await _landing_candidate_from_proposal(p)
    if not cand:
        return {"slug": slug, "published": False, "status": "BLOCKED", "reason": "CONTENUTO_INSUFFICIENTE: meno di 2 creator pubblicate pertinenti"}
    # duplicate protection: an already published landing with same slug/headline/title
    dup = await landings_col.find_one({"is_deleted": {"$ne": True}, "stato": "pubblicata",
                                       "$or": [{"slug": cand["slug"]}, {"headline": cand["headline"]}, {"seo.title": cand["seo"]["title"]}]}, {"_id": 0, "slug": 1})
    if dup:
        return {"slug": slug, "published": False, "status": "DUPLICATE_PROTECTED", "reason": f"Landing equivalente già pubblicata ({dup['slug']})"}
    gate = await validate_landing_full(cand)
    if not gate.get("publishable"):
        await proposals_col.update_one({"proposed_slug": slug}, {"$set": {"status": "REJECTED_BY_QUALITY_GATE", "exec_status": "REJECTED_BY_QUALITY_GATE", "exec_reasons": [e.get("code") for e in gate.get("errors", [])], "updated_at": now_iso()}})
        return {"slug": slug, "published": False, "status": "QUALITY_GATE_FAIL", "errors": gate.get("errors"), "score": gate.get("score")}
    if dry_run:
        return {"slug": slug, "published": False, "status": "WOULD_PUBLISH", "score": gate.get("score"), "models": len(cand["model_slugs"])}
    created = await create_landing({k: v for k, v in cand.items() if not k.startswith("_")}, PRINCIPAL, None)
    lid = created.get("id")
    raw = await landings_col.find_one({"id": lid}, {"_id": 0})
    out = await set_landing_state(raw, "pubblicata", PRINCIPAL, None)
    await enable_public_landings()
    await _mark_sitemap_dirty(f"landing published {out.get('slug')}")
    await proposals_col.update_one({"proposed_slug": slug}, {"$set": {"status": "PUBLISHED", "exec_status": "PUBLISHED", "landing_id": lid, "landing_slug": out.get("slug"), "updated_at": now_iso()}})
    await log_decision(None, "LANDING_PUBLISHED", out.get("slug"), f"Landing pubblicata da proposta '{slug}' ({len(cand['model_slugs'])} creator)", result="PUBLISHED", kind="executor")
    return {"slug": slug, "published": True, "status": "PUBLISHED", "landing_slug": out.get("slug"), "public_url": f"/l/{out.get('slug')}"}


async def publish_proposals(dry_run: bool = False) -> dict:
    proposals = [p async for p in proposals_col.find({"status": "SEO_DRAFT_PROPOSAL"}, {"_id": 0})]
    results = [await publish_landing_from_proposal(p, dry_run=dry_run) for p in proposals]
    return {"total": len(results), "published": sum(1 for r in results if r.get("published")),
            "blocked": sum(1 for r in results if not r.get("published")), "results": results}


# --------------------------------------------------------------------------- SAFE FIX / MODEL SEO
async def run_safe_fix(scope: str = "all") -> dict:
    from v1_seo import run_audit, apply_safe_fixes
    await run_audit(scope)
    return await apply_safe_fixes(actor_of(PRINCIPAL), None, scope, source="seo-autopilot")


async def prepare_model_seo() -> dict:
    from v1_seo import run_audit, apply_safe_fixes
    await run_audit("models")
    res = await apply_safe_fixes(actor_of(PRINCIPAL), None, "models", source="seo-autopilot")
    return {"models_seo_fixed": res.get("applied", 0), "skipped": res.get("skipped", 0)}


# --------------------------------------------------------------------------- INTERNAL LINKING
async def apply_internal_linking() -> dict:
    published = await _published_model_slugs()
    models = [m async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "categorie": 1, "tag": 1})]
    by_slug = {m["slug"]: m for m in models}
    linked = 0
    async for a in articles_col.find({"stato": "pubblicato"}, {"_id": 0, "id": 1, "categorie": 1, "modelle_correlate": 1}):
        current = [s for s in (a.get("modelle_correlate") or []) if s in published]
        if current:
            if current != (a.get("modelle_correlate") or []):
                await articles_col.update_one({"id": a["id"]}, {"$set": {"modelle_correlate": current, "data_aggiornamento": now_iso()}})
            continue
        acats = set(a.get("categorie") or [])
        rel = [m["slug"] for m in models if acats & set(m.get("categorie") or [])][:3] or [m["slug"] for m in models[:3]]
        if rel:
            await articles_col.update_one({"id": a["id"]}, {"$set": {"modelle_correlate": rel, "data_aggiornamento": now_iso()}})
            linked += 1
    # orphan snapshot (models with no inbound article and no shared-category peer)
    from v1_seo import internal_link_suggestions
    sug = await internal_link_suggestions()
    _ = by_slug  # kept for clarity
    return {"articles_linked": linked, "orphans": sug.get("orphans", [])}


# --------------------------------------------------------------------------- ARTICLES
def _article_gate(a: dict, model_slugs: set) -> dict:
    checks = []

    def c(code, ok):
        checks.append({"check": code, "ok": bool(ok)})
    title = a.get("seo_title") or a.get("titolo")
    c("TITLE", bool(a.get("titolo")))
    c("SEO_TITLE", bool(title))
    c("META_DESCRIPTION", bool(a.get("meta_description") or a.get("estratto")))
    c("SLUG_VALID", bool(re.match(r"^[a-z0-9-]+$", a.get("slug") or "")))
    c("CONTENT_SUFFICIENT", _text_len(a.get("contenuto")) >= 500)
    corr = [s for s in (a.get("modelle_correlate") or []) if s in model_slugs]
    c("INTERNAL_LINKS", len(corr) >= 1)
    c("NO_BROKEN_MODEL_LINK", all(s in model_slugs for s in (a.get("modelle_correlate") or [])))
    c("CATEGORIES", len(a.get("categorie") or []) >= 1)
    c("INDEXABLE", a.get("indicizzabile", True) is True)
    passed = all(x["ok"] for x in checks)
    return {"passed": passed, "checks": checks, "failed": [x["check"] for x in checks if not x["ok"]]}


async def _articles_generated_today() -> int:
    today = now_iso()[:10]
    return await articles_col.count_documents({"fonte": "seo-autopilot", "created_at": {"$regex": f"^{today}"}})


async def _pick_article_topic() -> Optional[dict]:
    """A published, indexable category with >=2 published models and NO published article yet. Dedup by intent."""
    published = [m async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "nome_artistico": 1, "categorie": 1})]
    covered = set()
    async for a in articles_col.find({"stato": "pubblicato"}, {"_id": 0, "categorie": 1}):
        covered |= set(a.get("categorie") or [])
    async for c in categories_col.find({"stato": "pubblicata", "indicizzabile": True, "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "nome": 1}):
        if c["slug"] in covered:
            continue
        models = [m for m in published if c["slug"] in (m.get("categorie") or [])]
        if len(models) >= 2:
            return {"categoria": c["slug"], "categoria_nome": c.get("nome") or c["slug"], "models": models[:12]}
    return None


async def generate_article(force: bool = False) -> dict:
    s = await get_settings()
    if not force and not (s["seo_autopilot_enabled"] and s["seo_autopilot_mode"] == "FULL" and s["seo_auto_publish"]):
        return {"generated": False, "reason": "FULL/auto-publish non attivo"}
    cap = int(s.get("seo_max_articles_per_day", 1) or 1)
    if await _articles_generated_today() >= cap:
        return {"generated": False, "reason": f"cap giornaliero raggiunto ({cap})"}
    if not llm.available():
        return {"generated": False, "reason": "LLM_UNAVAILABLE (EMERGENT_LLM_KEY assente o budget esaurito)"}
    topic = await _pick_article_topic()
    if not topic:
        return {"generated": False, "reason": "nessun tema distinto disponibile (evita duplicati)"}
    creators = [{"slug": m["slug"], "nome": m.get("nome_artistico") or m["slug"]} for m in topic["models"]]
    res = await llm.ask_json("genera_articolo", {
        "istruzioni": (
            "Scrivi un articolo editoriale ORIGINALE in italiano per il blog di un sito che presenta creator italiane con profilo OnlyFans (contenuti non espliciti). "
            "Target: Italia. Tono: informativo, elegante, non volgare. Collega naturalmente alle creator REALI fornite (usa solo i loro slug). "
            "NON inventare nomi. NON promettere nulla di esplicito. Almeno 500 parole totali, 3-5 sezioni. "
            "Formato JSON: {\"titolo\":\"…\",\"slug\":\"…\",\"meta_description\":\"…(60-165 char)\",\"estratto\":\"…\",\"h1\":\"…\","
            "\"sezioni\":[{\"titolo\":\"…\",\"paragrafi\":[\"…\",\"…\"]}],\"modelle_correlate\":[\"slug\"],\"categoria\":\"slug\"}"),
        "brand": BRAND, "categoria": topic["categoria"], "categoria_nome": topic["categoria_nome"],
        "creator_reali": creators, "lingua": "it", "paese": "IT"}, cache_ttl_days=1)
    if not res.get("available") or not res.get("data"):
        return {"generated": False, "reason": f"LLM non ha prodotto contenuto: {res.get('reason', 'n/d')}"}
    d = res["data"]
    valid_slugs = {c["slug"] for c in creators}
    corr = [x for x in (d.get("modelle_correlate") or []) if x in valid_slugs][:8] or [creators[0]["slug"]]
    titolo = (d.get("titolo") or topic["categoria_nome"]).strip()[:140]
    slug = slugify(d.get("slug") or titolo)
    if await articles_col.find_one({"slug": slug}) or await articles_col.find_one({"titolo": titolo}):
        return {"generated": False, "reason": "DUPLICATE_PROTECTED: slug/titolo già esistente"}
    # assemble sanitized HTML body with internal links
    parts = []
    for sec in (d.get("sezioni") or [])[:6]:
        h = sanitize_html(str(sec.get("titolo") or ""))
        if h:
            parts.append(f"<h2>{h}</h2>")
        for para in (sec.get("paragrafi") or [])[:6]:
            parts.append(f"<p>{sanitize_html(str(para))}</p>")
    links = " ".join(f'<a href="/modelle/{sl}">{sl}</a>' for sl in corr)
    parts.append(f'<p>Scopri le creator: {links}. Vedi anche la categoria <a href="/categorie/{topic["categoria"]}">{topic["categoria_nome"]}</a>.</p>')
    contenuto = sanitize_html("".join(parts))
    meta = (d.get("meta_description") or d.get("estratto") or titolo)[:168]
    doc = {
        "id": str(uuid.uuid4()), "slug": slug, "stato": "bozza",
        "titolo": titolo, "estratto": (d.get("estratto") or meta)[:300], "contenuto": contenuto,
        "immagine_principale": "", "autore": "SEO Autopilot", "categorie": [topic["categoria"]],
        "tag": [], "keyword_principale": topic["categoria_nome"], "keyword_secondarie": [],
        "seo_title": f"{titolo} | {BRAND}"[:65], "meta_description": meta, "external_id": None,
        "fonte": "seo-autopilot", "data_aggiornamento": now_iso(), "indicizzabile": True,
        "immagini_interne": [], "canonical": "", "alt_text": titolo, "og_image": "",
        "internal_links": [f"/modelle/{s}" for s in corr] + [f"/categorie/{topic['categoria']}"],
        "cta": {}, "modelle_correlate": corr, "data_pubblicazione": None, "created_at": now_iso(),
    }
    await articles_col.insert_one(doc)
    published_slugs = await _published_model_slugs()
    gate = _article_gate(doc, published_slugs)
    if not gate["passed"]:
        await log_decision(None, "ARTICLE_DRAFT", slug, f"Articolo generato ma non pubblicabile: {', '.join(gate['failed'])}", result="REJECTED_BY_QUALITY_GATE", kind="executor")
        return {"generated": True, "published": False, "slug": slug, "status": "QUALITY_GATE_FAIL", "failed": gate["failed"]}
    await articles_col.update_one({"id": doc["id"]}, {"$set": {"stato": "pubblicato", "data_pubblicazione": now_iso()}})
    await _mark_sitemap_dirty(f"article published {slug}")
    await log_decision(None, "ARTICLE_PUBLISHED", slug, f"Articolo IT generato e pubblicato (categoria {topic['categoria']})", result="PUBLISHED", kind="executor")
    return {"generated": True, "published": True, "slug": slug, "status": "PUBLISHED", "public_url": f"/articoli/{slug}"}


async def process_article_drafts() -> dict:
    from v1_seo import run_audit, apply_safe_fixes
    published_slugs = await _published_model_slugs()
    drafts = [a async for a in articles_col.find({"stato": "bozza"}, {"_id": 0})]
    published, blocked = 0, 0
    results = []
    for a in drafts:
        await run_audit("articles", a["id"])
        await apply_safe_fixes(actor_of(PRINCIPAL), None, "articles", a["id"], source="seo-autopilot")
        a = await articles_col.find_one({"id": a["id"]}, {"_id": 0})
        gate = _article_gate(a, published_slugs)
        if gate["passed"]:
            await articles_col.update_one({"id": a["id"]}, {"$set": {"stato": "pubblicato", "data_pubblicazione": a.get("data_pubblicazione") or now_iso(), "data_aggiornamento": now_iso()}})
            await _mark_sitemap_dirty(f"article published {a['slug']}")
            published += 1
            results.append({"slug": a["slug"], "published": True})
        else:
            blocked += 1
            results.append({"slug": a["slug"], "published": False, "failed": gate["failed"]})
    return {"total": len(drafts), "published": published, "blocked": blocked, "results": results}


# --------------------------------------------------------------------------- ORCHESTRATION
async def run_maintenance(trigger: str = "scheduler") -> dict:
    if not await full_enabled():
        return {"kind": "maintenance", "status": "SKIPPED", "reason": "FULL non attivo"}
    fix = await run_safe_fix("all")
    link = await apply_internal_linking()
    await _mark_sitemap_dirty("maintenance")
    out = {"kind": "maintenance", "status": "OK", "safe_fix_applied": fix.get("applied", 0), "internal_linking": link, "at": now_iso()}
    await store.state_col.update_one({"id": "global"}, {"$set": {"exec_last_maintenance": out}}, upsert=True)
    return out


async def run_execution(trigger: str = "scheduler", force: bool = False) -> dict:
    if not force and not await full_enabled():
        return {"kind": "execution", "status": "SKIPPED", "reason": "FULL non attivo"}
    before = await _draft_counts()
    steps = {}
    steps["safe_fix"] = await run_safe_fix("all")
    steps["model_seo"] = await prepare_model_seo()
    steps["article_drafts"] = await process_article_drafts()
    steps["landings"] = await publish_proposals()
    steps["internal_linking"] = await apply_internal_linking()
    steps["article_generated"] = await generate_article(force=force)
    await enable_public_landings()
    await _mark_sitemap_dirty("execution")
    after = await _draft_counts()
    out = {"kind": "execution", "status": "OK", "trigger": trigger, "at": now_iso(),
           "drafts_before": before["total"], "drafts_after": after["total"],
           "landings_published": steps["landings"]["published"], "article_drafts_published": steps["article_drafts"]["published"],
           "article_generated": steps["article_generated"].get("published", False), "steps": steps}
    await store.state_col.update_one({"id": "global"}, {"$set": {"exec_last_run": out}}, upsert=True)
    await log_decision(None, "EXECUTION_RUN", trigger, f"landings+{steps['landings']['published']} article_drafts+{steps['article_drafts']['published']} generated={out['article_generated']}", result="OK", kind="executor")
    return out


# --------------------------------------------------------------------------- STATUS / REPORT
async def _draft_counts() -> dict:
    art = await articles_col.count_documents({"stato": "bozza"})
    from v1_landings import landings_col
    lnd = await landings_col.count_documents({"stato": "bozza", "is_deleted": {"$ne": True}})
    prop = await proposals_col.count_documents({"status": "SEO_DRAFT_PROPOSAL"})
    return {"articles": art, "landings": lnd, "proposals": prop, "total": art + lnd + prop}


async def production_status() -> dict:
    from v1_landings import landings_col
    from v1_seo import sitemap_entries, internal_link_suggestions
    s = await get_settings()
    flags = await _flags()
    entries = await sitemap_entries()
    links = await internal_link_suggestions()
    pub_models = await models_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}})
    pub_articles = await articles_col.count_documents({"stato": "pubblicato"})
    pub_landings = await landings_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}})
    pub_categories = await categories_col.count_documents({"stato": "pubblicata", "indicizzabile": True, "is_deleted": {"$ne": True}})
    drafts = await _draft_counts()
    # Search Console
    try:
        from google_search.config import cfg as gcfg
        gsc_connected = bool(getattr(gcfg, "is_connected", False)) or bool(getattr(gcfg, "refresh_token", None))
    except Exception:
        gsc_connected = False
    try:
        from seo_autopilot.gsc_sync import gsc_status
        gsc_connected = (await gsc_status()).get("GSC_STATUS") == "CONNECTED"
    except Exception:
        pass
    active = bool(s["seo_autopilot_enabled"]) and s["seo_autopilot_mode"] == "FULL"
    last_run = (await store.state_col.find_one({"id": "global"}, {"_id": 0, "exec_last_run": 1, "exec_last_maintenance": 1}) or {})
    return {
        "SEO_AUTOPILOT_ACTIVE": active,
        "SEO_AUTOPILOT_PRODUCTION": active,
        "SEO_AUTOPILOT_MODE": s["seo_autopilot_mode"],
        "AUTO_PUBLISH_ENABLED": bool(s["seo_auto_publish"]),
        "ARTICLE_GENERATOR_ACTIVE": active and bool(s["seo_auto_publish"]),
        "LANDING_GENERATOR_ACTIVE": active,
        "MODEL_SEO_ACTIVE": active,
        "INTERNAL_LINKING_ACTIVE": active,
        "SITEMAP_AUTO_UPDATE": True,
        "SEO_SAFE_FIX_ACTIVE": active,
        "QUALITY_GATE_ACTIVE": True,
        "DUPLICATE_PROTECTION_ACTIVE": True,
        "TARGET_COUNTRY": s["seo_target_country"],
        "LANGUAGE": s["seo_language"],
        "MAX_ARTICLES_PER_DAY": int(s["seo_max_articles_per_day"]),
        "PUBLIC_LANDING_ROUTES": bool(flags.get("public_landing_routes")),
        "WEBHOOK_ARTICLES_AUTO_PUBLISH": bool(s.get("auto_publish_articles")),
        "DRAFTS_CURRENT": drafts,
        "TOTAL_PUBLISHED_PAGES": pub_models + pub_articles + pub_landings + pub_categories,
        "PUBLISHED_BREAKDOWN": {"models": pub_models, "articles": pub_articles, "landings": pub_landings, "categories": pub_categories},
        "INDEXABLE_PAGES": len(entries),
        "SITEMAP_URLS": len(entries),
        "ORPHAN_PAGES": len(links.get("orphans", [])),
        "ORPHANS": links.get("orphans", []),
        "SEARCH_CONSOLE_CONNECTED": bool(gsc_connected),
        "last_execution": last_run.get("exec_last_run"),
        "last_maintenance": last_run.get("exec_last_maintenance"),
    }
