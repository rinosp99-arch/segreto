"""SUPER API v1 - SEO ENGINE + SEO AUTOPILOT.

Rules classify issues as SAFE_AUTO_FIX / REVIEW_REQUIRED / CRITICAL.
Only SAFE_AUTO_FIX issues can be applied automatically; every fix is versioned and
re-validated (rollback if the entity gets worse). REVIEW_REQUIRED can be applied only
one-by-one with an explicit human confirmation (apply_review=true). CRITICAL is never auto-applied.
"""
import re
import uuid
import copy
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict

from database import (
    models_col, categories_col, articles_col, landings_col, seo_issues_col, redirects_col, config_col,
    now_iso,
)
from sanitize import slugify
from v1_security import require, actor_of, request_id_of
from v1_versioning import record_version, audit_log, rollback_version

seo_router = APIRouter(prefix="/api/v1/seo", tags=["SEO"])

SAFE, REVIEW, CRITICAL = "SAFE_AUTO_FIX", "REVIEW_REQUIRED", "CRITICAL"
from v1_models import OF_RX  # canonical rule (no duplicated regex)
SLUG_RX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BRAND = "LATO SEGRETO"


def _nz(v) -> bool:
    return bool(v and str(v).strip())


def _trunc(text: str, n: int) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…"


async def site_base_url() -> str:
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0}) or {}
    return ((cfg.get("site") or {}).get("base_url") or "").rstrip("/")


def _issue(entity_type, entity, code, severity, message, field="", suggested=None, fix=None):
    return {
        "entity_type": entity_type, "entity_id": entity.get("id"), "entity_label": entity.get("nome_artistico") or entity.get("nome") or entity.get("titolo") or entity.get("slug"),
        "entity_slug": entity.get("slug"), "code": code, "severity": severity, "message": message, "field": field,
        "suggested_value": suggested, "fix": fix,  # fix = {"set": {dotted.path: value}} applied on the entity
    }


# ---------------- RULES ----------------
async def audit_model(m: dict, all_models: List[dict], base: str) -> List[dict]:
    out = []
    seo = m.get("seo") or {}
    name = m.get("nome_artistico") or m.get("nome") or "Creator"
    published = m.get("stato") == "pubblicata"
    if not _nz(seo.get("title")):
        val = f"{name} | {BRAND}"
        out.append(_issue("model", m, "MISSING_SEO_TITLE", SAFE, "SEO title mancante", "seo.title", val, {"set": {"seo.title": val}}))
    elif len(seo["title"]) > 65:
        out.append(_issue("model", m, "SEO_TITLE_TOO_LONG", REVIEW, f"SEO title troppo lungo ({len(seo['title'])} caratteri, max 60-65)", "seo.title", _trunc(seo["title"], 60)))
    if not _nz(seo.get("meta_description")):
        src = m.get("bio") or m.get("frase") or f"Scopri {name} su {BRAND}."
        val = _trunc(f"Scopri {name}: {src}", 155)
        out.append(_issue("model", m, "MISSING_META_DESCRIPTION", SAFE, "Meta description mancante", "seo.meta_description", val, {"set": {"seo.meta_description": val}}))
    else:
        ln = len(seo["meta_description"])
        if ln > 170:
            val = _trunc(seo["meta_description"], 155)
            out.append(_issue("model", m, "META_DESCRIPTION_TOO_LONG", SAFE, f"Meta description troppo lunga ({ln})", "seo.meta_description", val, {"set": {"seo.meta_description": val}}))
        elif ln < 60:
            out.append(_issue("model", m, "META_DESCRIPTION_TOO_SHORT", REVIEW, f"Meta description corta ({ln} caratteri)", "seo.meta_description"))
    if not _nz(seo.get("og_image")) and _nz(m.get("foto_card")):
        out.append(_issue("model", m, "MISSING_OG_IMAGE", SAFE, "Immagine OpenGraph mancante", "seo.og_image", m["foto_card"], {"set": {"seo.og_image": m["foto_card"]}}))
    if not _nz(seo.get("og_title")) and _nz(seo.get("title")):
        out.append(_issue("model", m, "MISSING_OG_TITLE", SAFE, "OG title mancante", "seo.og_title", seo["title"], {"set": {"seo.og_title": seo["title"]}}))
    if not _nz(seo.get("og_description")) and _nz(seo.get("meta_description")):
        out.append(_issue("model", m, "MISSING_OG_DESCRIPTION", SAFE, "OG description mancante", "seo.og_description", seo["meta_description"], {"set": {"seo.og_description": seo["meta_description"]}}))
    if not _nz(seo.get("robots")):
        out.append(_issue("model", m, "MISSING_ROBOTS", SAFE, "Direttiva robots mancante", "seo.robots", "index,follow", {"set": {"seo.robots": "index,follow"}}))
    if not _nz(seo.get("structured_data_type")):
        out.append(_issue("model", m, "MISSING_STRUCTURED_DATA_TYPE", SAFE, "Tipo structured data mancante", "seo.structured_data_type", "ProfilePage", {"set": {"seo.structured_data_type": "ProfilePage"}}))
    if base and m.get("slug"):
        canon = f"{base}/modelle/{m['slug']}"
        if not _nz(seo.get("canonical")):
            out.append(_issue("model", m, "MISSING_CANONICAL", SAFE, "Canonical mancante", "seo.canonical", canon, {"set": {"seo.canonical": canon}}))
        elif seo["canonical"] != canon and base in seo["canonical"]:
            out.append(_issue("model", m, "CANONICAL_MISMATCH", REVIEW, "Canonical non coincide con l'URL della pagina", "seo.canonical", canon))
    if not _nz(seo.get("alt_default")):
        val = f"{name} - creator {BRAND}"
        out.append(_issue("model", m, "MISSING_ALT_DEFAULT", SAFE, "ALT predefinito mancante", "seo.alt_default", val, {"set": {"seo.alt_default": val}}))
    # ALT on media pairs
    pairs = m.get("media_pairs") or []
    alt_fix: Dict[str, Any] = {}
    missing_alt = 0
    for i, pr in enumerate(pairs):
        for side in ("pubblico", "segreto"):
            item = pr.get(side) or {}
            if _nz(item.get("url")) and not _nz(item.get("alt")):
                missing_alt += 1
                kind = "video" if pr.get("tipo") == "video" else "foto"
                alt_fix[f"media_pairs.{i}.{side}.alt"] = f"{name} {kind} {'lato segreto' if side == 'segreto' else 'lato pubblico'} {i + 1}"
    if missing_alt:
        out.append(_issue("model", m, "MISSING_ALT_MEDIA", SAFE, f"{missing_alt} media senza testo ALT", "media_pairs[].alt", None, {"set": alt_fix}))
    # slug validity (changing a slug is destructive: never automatic)
    if m.get("slug") and not SLUG_RX.match(m["slug"]):
        out.append(_issue("model", m, "SLUG_INVALID", CRITICAL if published else REVIEW, "Slug non conforme (solo minuscole, numeri e trattini)", "slug", slugify(m["slug"])))
    # keywords / topics opportunities
    if not (seo.get("keywords") or []):
        kws = list(dict.fromkeys([*(m.get("tag") or []), *(m.get("categorie") or []), name.lower()]))[:8]
        out.append(_issue("model", m, "MISSING_KEYWORDS", SAFE, "Keyword/topic SEO non impostati", "seo.keywords", kws, {"set": {"seo.keywords": kws, "seo.topics": list(m.get("categorie") or [])}}))
    if published and len(m.get("bio") or "") < 120:
        out.append(_issue("model", m, "THIN_CONTENT", REVIEW, "Bio pubblica corta (<120 caratteri): pagina povera per i motori di ricerca", "bio"))
    # links
    of = (m.get("onlyfans_url") or "").strip()
    if published and not of:
        out.append(_issue("model", m, "ONLYFANS_URL_MISSING", CRITICAL, "Modella pubblicata senza link OnlyFans", "onlyfans_url"))
    elif of and not OF_RX.match(of):
        out.append(_issue("model", m, "ONLYFANS_URL_INVALID", CRITICAL, "Link OnlyFans non valido", "onlyfans_url"))
    # duplicates
    if _nz(seo.get("title")):
        dups = [o["slug"] for o in all_models if o["id"] != m["id"] and (o.get("seo") or {}).get("title") == seo["title"] and o.get("stato") == "pubblicata"]
        if dups and published:
            out.append(_issue("model", m, "DUPLICATE_SEO_TITLE", REVIEW, f"SEO title duplicato con: {', '.join(dups[:3])}", "seo.title"))
    if _nz(seo.get("meta_description")):
        dups = [o["slug"] for o in all_models if o["id"] != m["id"] and (o.get("seo") or {}).get("meta_description") == seo["meta_description"] and o.get("stato") == "pubblicata"]
        if dups and published:
            out.append(_issue("model", m, "DUPLICATE_META_DESCRIPTION", REVIEW, f"Meta description duplicata con: {', '.join(dups[:3])}", "seo.meta_description"))
    # published but not ready
    from v1_models import validate_model
    if published:
        v = validate_model(m)
        if not v["ready"]:
            out.append(_issue("model", m, "PUBLISHED_NOT_READY", CRITICAL, "Pubblicata ma con requisiti mancanti: " + ", ".join(e["field"] for e in v["errors"][:4]), "stato"))
    # sitemap consistency: noindex but indexable flag true (or vice versa)
    robots = (seo.get("robots") or "index,follow").lower()
    if "noindex" in robots and seo.get("indexable", True):
        out.append(_issue("model", m, "SITEMAP_INCONSISTENCY", SAFE, "robots=noindex ma pagina marcata indicizzabile (finirebbe in sitemap)", "seo.indexable", False, {"set": {"seo.indexable": False}}))
    return out


async def audit_article(a: dict, model_slugs: set, base: str) -> List[dict]:
    out = []
    if not _nz(a.get("seo_title")):
        val = f"{a.get('titolo', '')} | {BRAND}"
        out.append(_issue("article", a, "MISSING_SEO_TITLE", SAFE, "SEO title mancante", "seo_title", val, {"set": {"seo_title": val}}))
    if not _nz(a.get("meta_description")):
        val = _trunc(a.get("estratto") or a.get("contenuto") or a.get("titolo", ""), 155)
        out.append(_issue("article", a, "MISSING_META_DESCRIPTION", SAFE, "Meta description mancante", "meta_description", val, {"set": {"meta_description": val}}))
    if not _nz(a.get("alt_text")) and _nz(a.get("immagine_principale")):
        out.append(_issue("article", a, "MISSING_ALT", SAFE, "ALT immagine principale mancante", "alt_text", a.get("titolo"), {"set": {"alt_text": a.get("titolo")}}))
    if not _nz(a.get("og_image")) and _nz(a.get("immagine_principale")):
        out.append(_issue("article", a, "MISSING_OG_IMAGE", SAFE, "OG image mancante", "og_image", a["immagine_principale"], {"set": {"og_image": a["immagine_principale"]}}))
    if base and a.get("slug") and not _nz(a.get("canonical")):
        canon = f"{base}/articoli/{a['slug']}"
        out.append(_issue("article", a, "MISSING_CANONICAL", SAFE, "Canonical mancante", "canonical", canon, {"set": {"canonical": canon}}))
    dead = [s for s in (a.get("modelle_correlate") or []) if s not in model_slugs]
    if dead:
        keep = [s for s in (a.get("modelle_correlate") or []) if s in model_slugs]
        out.append(_issue("article", a, "BROKEN_INTERNAL_LINK", SAFE, f"Link interni a modelle inesistenti: {', '.join(dead)}", "modelle_correlate", keep, {"set": {"modelle_correlate": keep}}))
    for m in re.finditer(r'href="/modelle/([a-z0-9\-]+)"', a.get("contenuto") or ""):
        if m.group(1) not in model_slugs:
            out.append(_issue("article", a, "BROKEN_INTERNAL_LINK_BODY", REVIEW, f"Link nel testo a /modelle/{m.group(1)} inesistente", "contenuto"))
    if a.get("stato") == "pubblicato" and not (a.get("modelle_correlate") or []):
        out.append(_issue("article", a, "NO_INTERNAL_LINKS", REVIEW, "Articolo pubblicato senza collegamenti a modelle (internal linking)", "modelle_correlate"))
    return out


async def audit_category(c: dict, base: str) -> List[dict]:
    out = []
    if not _nz(c.get("seo_title")):
        val = f"Modelle {c.get('nome', '')} | {BRAND}"
        out.append(_issue("category", c, "MISSING_SEO_TITLE", SAFE, "SEO title mancante", "seo_title", val, {"set": {"seo_title": val}}))
    if not _nz(c.get("meta_description")):
        val = _trunc(c.get("descrizione") or f"Le creator {c.get('nome', '')} di {BRAND}.", 155)
        out.append(_issue("category", c, "MISSING_META_DESCRIPTION", SAFE, "Meta description mancante", "meta_description", val, {"set": {"meta_description": val}}))
    return out


async def audit_landing(l: dict, base: str) -> List[dict]:
    out = []
    seo = l.get("seo") or {}
    if not _nz(seo.get("title")):
        val = f"{l.get('headline') or l.get('titolo') or 'Landing'} | {BRAND}"
        out.append(_issue("landing", l, "MISSING_SEO_TITLE", SAFE, "SEO title mancante", "seo.title", val, {"set": {"seo.title": val}}))
    if not _nz(seo.get("meta_description")):
        val = _trunc(l.get("subtitle") or l.get("headline") or "", 155) or f"{l.get('titolo', '')} - {BRAND}"
        out.append(_issue("landing", l, "MISSING_META_DESCRIPTION", SAFE, "Meta description mancante", "seo.meta_description", val, {"set": {"seo.meta_description": val}}))
    return out


async def run_audit(scope: Optional[str] = None, entity_id: Optional[str] = None) -> dict:
    base = await site_base_url()
    models = await models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}).to_list(2000)
    model_slugs = {m["slug"] for m in models if m.get("stato") == "pubblicata"}
    found: List[dict] = []
    if scope in (None, "all", "model", "models"):
        for m in models:
            if entity_id and m["id"] != entity_id and m["slug"] != entity_id:
                continue
            found += await audit_model(m, models, base)
    if scope in (None, "all", "article", "articles"):
        async for a in articles_col.find({}, {"_id": 0}):
            found += await audit_article(a, model_slugs, base)
    if scope in (None, "all", "category", "categories"):
        async for c in categories_col.find({}, {"_id": 0}):
            found += await audit_category(c, base)
    if scope in (None, "all", "landing", "landings"):
        async for l in landings_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}):
            found += await audit_landing(l, base)
    if not base:
        found.append({"entity_type": "site", "entity_id": "global", "entity_label": "Sito", "entity_slug": None, "code": "SITE_BASE_URL_MISSING",
                      "severity": REVIEW, "message": "site.base_url non configurato in Config Center: canonical/sitemap assoluti non verificabili (impostare quando si passa al dominio definitivo)", "field": "config.site.base_url", "suggested_value": None, "fix": None})

    # persist: upsert open issues, auto-resolve those no longer detected (within scope)
    keys = set()
    for it in found:
        k = (it["entity_type"], it["entity_id"], it["code"], it.get("field") or "")
        keys.add(k)
        await seo_issues_col.update_one(
            {"entity_type": k[0], "entity_id": k[1], "code": k[2], "field": k[3]},
            {"$set": {**it, "status": "open", "last_seen": now_iso()},
             "$setOnInsert": {"id": str(uuid.uuid4()), "detected_at": now_iso()}}, upsert=True)
    q: Dict[str, Any] = {"status": "open"}
    if scope not in (None, "all"):
        q["entity_type"] = scope.rstrip("s")
    if entity_id:
        q["$or"] = [{"entity_id": entity_id}, {"entity_slug": entity_id}]
    async for old in seo_issues_col.find(q, {"_id": 0}):
        k = (old["entity_type"], old["entity_id"], old["code"], old.get("field") or "")
        if k not in keys:
            await seo_issues_col.update_one({"id": old["id"]}, {"$set": {"status": "resolved", "resolved_at": now_iso(), "resolved_by": "audit"}})
    counts = {SAFE: 0, REVIEW: 0, CRITICAL: 0}
    for it in found:
        counts[it["severity"]] += 1
    score = max(0, 100 - counts[SAFE] * 1 - counts[REVIEW] * 3 - counts[CRITICAL] * 10)
    return {"ok": True, "total": len(found), "counts": counts, "health_score": score, "audited_at": now_iso(), "scope": scope or "all"}


def issue_impact(issue: dict) -> dict:
    """Deterministic impact/risk description for a review preview (no LLM)."""
    code = issue.get("code", "")
    seo_impact = {"SEO_TITLE_TOO_LONG": "Alto: il title viene troncato nei risultati", "META_DESCRIPTION_TOO_SHORT": "Medio: snippet povero, CTR ridotto",
                  "DUPLICATE_SEO_TITLE": "Alto: pagine in competizione tra loro", "DUPLICATE_META_DESCRIPTION": "Medio: snippet identici",
                  "THIN_CONTENT": "Alto: pagina povera, difficile da posizionare", "CANONICAL_MISMATCH": "Alto: segnali di indicizzazione confusi",
                  "SLUG_INVALID": "Alto: URL non pulito", "NO_INTERNAL_LINKS": "Medio: pagina isolata", "BROKEN_INTERNAL_LINK_BODY": "Medio: link rotto nel testo",
                  "SITE_BASE_URL_MISSING": "Bloccante per canonical/sitemap assoluti"}.get(code, "Basso/Medio")
    ux_impact = "Nessuno (solo metadati)" if issue.get("field", "").startswith("seo") or issue.get("field") in ("seo_title", "meta_description") else "Visibile agli utenti: verificare il testo"
    risk = "CRITICAL" if issue.get("severity") == "CRITICAL" else ("medio: modifica editoriale" if issue.get("severity") == "REVIEW_REQUIRED" else "basso: reversibile con rollback")
    return {"seo_impact": seo_impact, "ux_impact": ux_impact, "risk": risk}


# ---------------- FIX APPLICATION ----------------
ENTITY_COL = {"model": models_col, "article": articles_col, "category": categories_col, "landing": landings_col}


def _set_path(doc: dict, path: str, value):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        if p.isdigit() and isinstance(cur, list):
            cur = cur[int(p)]
        else:
            if p not in cur or not isinstance(cur[p], (dict, list)):
                cur[p] = {}
            cur = cur[p]
    last = parts[-1]
    if last.isdigit() and isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


async def apply_issue_fix(issue: dict, actor: str, request_id: Optional[str], source: str = "autofix", apply_review: bool = False) -> dict:
    if issue["severity"] == CRITICAL:
        return {"id": issue["id"], "applied": False, "reason": "CRITICAL: richiede intervento manuale"}
    if issue["severity"] == REVIEW and not apply_review:
        return {"id": issue["id"], "applied": False, "reason": "REVIEW_REQUIRED: conferma manuale necessaria (apply_review=true su singola issue)"}
    fix = issue.get("fix")
    if not fix or not fix.get("set"):
        # review issues without a machine fix but with a suggested value on a simple field
        if apply_review and issue.get("suggested_value") is not None and issue.get("field") and "[" not in issue["field"]:
            fix = {"set": {issue["field"]: issue["suggested_value"]}}
        else:
            return {"id": issue["id"], "applied": False, "reason": "Nessun fix automatico disponibile"}
    col = ENTITY_COL.get(issue["entity_type"])
    if col is None:
        return {"id": issue["id"], "applied": False, "reason": "Entità non modificabile automaticamente"}
    doc = await col.find_one({"id": issue["entity_id"]}, {"_id": 0})
    if not doc:
        await seo_issues_col.update_one({"id": issue["id"]}, {"$set": {"status": "resolved", "resolved_at": now_iso(), "resolved_by": "entity_missing"}})
        return {"id": issue["id"], "applied": False, "reason": "Entità non trovata"}
    new_doc = copy.deepcopy(doc)
    try:
        for path, value in fix["set"].items():
            _set_path(new_doc, path, value)
    except Exception as e:
        return {"id": issue["id"], "applied": False, "reason": f"Fix non applicabile: {e}"}
    new_doc["updated_at"] = now_iso()
    await col.replace_one({"id": doc["id"]}, new_doc)
    ver = await record_version(issue["entity_type"], doc["id"], doc, new_doc, actor, source=source,
                               reason=f"SEO fix {issue['code']}", request_id=request_id, meta={"issue_id": issue["id"], "code": issue["code"]})
    # SELF-CHECK: a published model must stay ready, otherwise rollback
    if issue["entity_type"] == "model" and new_doc.get("stato") == "pubblicata":
        from v1_models import validate_model
        if not validate_model(new_doc)["ready"] and ver.get("id"):
            await rollback_version(ver["id"], actor, request_id, reason="Auto-rollback: il fix SEO rendeva la modella non pubblicabile")
            return {"id": issue["id"], "applied": False, "reason": "Fix annullato con rollback (validazione fallita)", "rolled_back_version": ver["id"]}
    await seo_issues_col.update_one({"id": issue["id"]}, {"$set": {"status": "fixed", "fixed_at": now_iso(), "fixed_by": actor, "version_id": ver.get("id"), "fix_source": source}})
    return {"id": issue["id"], "applied": True, "code": issue["code"], "entity": issue["entity_label"], "field": issue.get("field"), "version_id": ver.get("id")}


async def apply_safe_fixes(actor: str, request_id: Optional[str], scope: Optional[str] = None, entity_id: Optional[str] = None, dry_run: bool = False, source: str = "autofix") -> dict:
    q: Dict[str, Any] = {"status": "open", "severity": SAFE}
    if scope and scope not in ("all",):
        q["entity_type"] = scope.rstrip("s")
    if entity_id:
        q["$or"] = [{"entity_id": entity_id}, {"entity_slug": entity_id}]
    issues = await seo_issues_col.find(q, {"_id": 0}).to_list(2000)
    if dry_run:
        return {"dry_run": True, "would_fix": len(issues), "items": [{"id": i["id"], "code": i["code"], "entity": i["entity_label"], "field": i.get("field"), "suggested_value": i.get("suggested_value")} for i in issues]}
    results = [await apply_issue_fix(i, actor, request_id, source) for i in issues]
    applied = [r for r in results if r.get("applied")]
    if applied:
        from v1_config import emit_event
        await emit_event("seo.autofix_applied", {"count": len(applied), "actor": actor, "codes": list({a["code"] for a in applied})})
    return {"applied": len(applied), "skipped": len(results) - len(applied), "results": results}


# ---------------- REDIRECTS ----------------
async def ensure_redirect(from_path: str, to_path: str, actor: str = "system", reason: str = "", status_code: int = 301):
    if not from_path or not to_path or from_path == to_path:
        return None
    existing = await redirects_col.find_one({"from_path": from_path}, {"_id": 0})
    doc = {"id": existing["id"] if existing else str(uuid.uuid4()), "from_path": from_path, "to_path": to_path, "status_code": status_code,
           "reason": reason, "active": True, "created_by": actor, "created_at": existing["created_at"] if existing else now_iso(), "updated_at": now_iso(), "hits": existing.get("hits", 0) if existing else 0}
    await redirects_col.replace_one({"from_path": from_path}, doc, upsert=True)
    # avoid chains: anything pointing to from_path now points to to_path
    await redirects_col.update_many({"to_path": from_path}, {"$set": {"to_path": to_path, "updated_at": now_iso()}})
    await record_version("redirect", doc["id"], existing, doc, actor, source="system", reason=reason or "redirect")
    return doc


# ---------------- INTERNAL LINKING ----------------
async def internal_link_suggestions(limit_per_model: int = 4) -> dict:
    models = await models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1, "nome_artistico": 1, "categorie": 1, "tag": 1}).to_list(1000)
    arts = await articles_col.find({"stato": "pubblicato"}, {"_id": 0, "id": 1, "slug": 1, "titolo": 1, "categorie": 1, "modelle_correlate": 1}).to_list(500)
    graph = []
    for m in models:
        cats = set(m.get("categorie") or [])
        tags = set(m.get("tag") or [])
        scored = []
        for o in models:
            if o["id"] == m["id"]:
                continue
            s = len(cats & set(o.get("categorie") or [])) * 2 + len(tags & set(o.get("tag") or []))
            if s > 0:
                scored.append((s, o))
        scored.sort(key=lambda x: -x[0])
        related_articles = [a for a in arts if m["slug"] in (a.get("modelle_correlate") or []) or cats & set(a.get("categorie") or [])]
        graph.append({"model": m["slug"], "nome": m.get("nome_artistico"), "related_models": [{"slug": o["slug"], "score": s} for s, o in scored[:limit_per_model]],
                      "related_articles": [a["slug"] for a in related_articles[:3]], "inbound_articles": len([a for a in arts if m["slug"] in (a.get("modelle_correlate") or [])])})
    orphans = [g["model"] for g in graph if g["inbound_articles"] == 0 and not g["related_models"]]
    return {"items": graph, "orphans": orphans, "note": "Le correlate pubbliche usano già categoria condivisa (/api/models/{slug}/correlate); questo grafo alimenta articoli/landing."}


# ---------------- SITEMAP MANAGER ----------------
async def sitemap_entries(base: Optional[str] = None) -> List[dict]:
    """Single source of truth for the sitemap (public /api/sitemap.xml, SEO status, Google layer).
    Only public + indexable URLs: published models (no anteprima/noindex), indexable published categories/articles and
    published landings ONLY while flags.public_landing_routes is on. Real lastmod, deduplicated."""
    if base is None:
        base = await site_base_url()
        if not base:
            from google_search.config import cfg as gcfg
            base = gcfg.public_base
    base = (base or "").rstrip("/")
    entries = [{"path": "/", "priority": "1.0", "changefreq": "daily", "type": "home"}]
    latest = ""
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "seo": 1, "updated_at": 1, "anteprima": 1, "data_pubblicazione": 1}):
        seo = m.get("seo") or {}
        if seo.get("indexable", True) is False or "noindex" in (seo.get("robots") or "").lower() or m.get("anteprima"):
            continue
        lm = (m.get("updated_at") or m.get("data_pubblicazione") or "")[:10]
        latest = max(latest, lm)
        entries.append({"path": f"/modelle/{m['slug']}", "priority": "0.9", "changefreq": "weekly", "type": "model", "lastmod": lm or None})
    async for c in categories_col.find({"stato": "pubblicata", "indicizzabile": True, "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "updated_at": 1}):
        entries.append({"path": f"/categorie/{c['slug']}", "priority": "0.7", "changefreq": "weekly", "type": "category", "lastmod": (c.get("updated_at") or "")[:10] or None})
    n_articles = 0
    async for a in articles_col.find({"stato": "pubblicato", "indicizzabile": True}, {"_id": 0, "slug": 1, "data_aggiornamento": 1, "data_pubblicazione": 1}):
        entries.append({"path": f"/articoli/{a['slug']}", "priority": "0.6", "changefreq": "monthly", "type": "article", "lastmod": (a.get("data_aggiornamento") or a.get("data_pubblicazione") or "")[:10] or None})
        n_articles += 1
    if n_articles:
        # Phase 14B: the public, indexable, internally-linked "Rivista" index (/articoli) was missing from the sitemap (Google: "URL sconosciuto")
        entries.append({"path": "/articoli", "priority": "0.5", "changefreq": "weekly", "type": "articles_index", "lastmod": max((e.get("lastmod") or "") for e in entries if e.get("type") == "article") or None})
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    if (cfg.get("flags") or {}).get("public_landing_routes"):
        async for l in landings_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "seo": 1, "updated_at": 1}):
            lseo = l.get("seo") or {}
            if lseo.get("indexable", True) is False or "noindex" in (lseo.get("robots") or "").lower():
                continue
            entries.append({"path": f"/l/{l['slug']}", "priority": "0.8", "changefreq": "weekly", "type": "landing", "lastmod": (l.get("updated_at") or "")[:10] or None})
    if latest:
        entries[0]["lastmod"] = latest
    seen, out = set(), []
    for e in entries:
        e["loc"] = f"{base}{e['path']}" if base else e["path"]
        if e["loc"] in seen:
            continue
        seen.add(e["loc"])
        out.append(e)
    return out


def sitemap_xml(entries: List[dict]) -> str:
    from xml.sax.saxutils import escape
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for e in entries:
        lm = f"<lastmod>{escape(e['lastmod'])}</lastmod>" if e.get("lastmod") else ""
        parts.append(f"<url><loc>{escape(e['loc'])}</loc>{lm}<changefreq>{e['changefreq']}</changefreq><priority>{e['priority']}</priority></url>")
    parts.append("</urlset>")
    return "\n".join(parts)


# ---------------- BODIES ----------------
class AuditBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    scope: Optional[str] = "all"      # all | models | articles | categories | landings
    entity_id: Optional[str] = None


class FixBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    issue_id: Optional[str] = None
    issue_ids: Optional[List[str]] = None
    apply_review: bool = False         # explicit human confirmation for REVIEW_REQUIRED
    reason: Optional[str] = ""


class FixAllBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    scope: Optional[str] = "all"
    entity_id: Optional[str] = None
    dry_run: bool = False


class RedirectBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    from_path: str
    to_path: str
    status_code: int = 301
    reason: Optional[str] = ""


# ---------------- ROUTES ----------------
@seo_router.get("/issues")
async def list_issues(severity: Optional[str] = None, status: str = "open", entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                      limit: int = 200, principal=Depends(require("seo:read"))):
    q: Dict[str, Any] = {}
    if status and status != "all":
        q["status"] = status
    if severity:
        q["severity"] = severity
    if entity_type:
        q["entity_type"] = entity_type
    if entity_id:
        q["$or"] = [{"entity_id": entity_id}, {"entity_slug": entity_id}]
    items = await seo_issues_col.find(q, {"_id": 0}).sort([("severity", 1), ("detected_at", -1)]).to_list(limit)
    counts = {SAFE: 0, REVIEW: 0, CRITICAL: 0}
    async for r in seo_issues_col.aggregate([{"$match": {"status": "open"}}, {"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
        counts[r["_id"]] = r["n"]
    return {"items": items, "total": len(items), "open_counts": counts, "severity_levels": {SAFE: "correggibile in automatico", REVIEW: "richiede conferma umana", CRITICAL: "mai automatico"}}


@seo_router.get("/opportunities")
async def opportunities(principal=Depends(require("seo:read"))):
    items = await seo_issues_col.find({"status": "open", "code": {"$in": ["MISSING_KEYWORDS", "THIN_CONTENT", "NO_INTERNAL_LINKS", "META_DESCRIPTION_TOO_SHORT", "DUPLICATE_SEO_TITLE", "DUPLICATE_META_DESCRIPTION"]}}, {"_id": 0}).to_list(500)
    links = await internal_link_suggestions()
    unpublished_ready = []
    from v1_models import validate_model
    async for m in models_col.find({"stato": {"$ne": "pubblicata"}, "is_deleted": {"$ne": True}}, {"_id": 0}):
        if validate_model(m)["ready"]:
            unpublished_ready.append({"slug": m["slug"], "nome": m.get("nome_artistico"), "opportunity": "Pronta ma non pubblicata: pagina indicizzabile persa"})
    cats_without = []
    async for c in categories_col.find({"stato": "pubblicata"}, {"_id": 0, "slug": 1, "nome": 1}):
        n = await models_col.count_documents({"stato": "pubblicata", "categorie": c["slug"]})
        if n < 2:
            cats_without.append({"slug": c["slug"], "nome": c["nome"], "models": n, "opportunity": "Categoria con meno di 2 modelle: pagina debole"})
    return {"content": items, "internal_linking": {"orphans": links["orphans"], "suggestions": links["items"][:20]}, "ready_to_publish": unpublished_ready, "weak_categories": cats_without,
            "italy_focus": {"locale": "it-IT", "note": "Tutti i suggerimenti testuali sono in italiano; keyword target da impostare in seo.keywords per pubblico italiano."}}


@seo_router.post("/audit")
async def audit(body: AuditBody = AuditBody(), principal=Depends(require("seo:read"))):
    return await run_audit(body.scope, body.entity_id)


@seo_router.post("/fix")
async def fix(body: FixBody, request: Request, principal=Depends(require("seo:write"))):
    ids = body.issue_ids or ([body.issue_id] if body.issue_id else [])
    if not ids:
        raise HTTPException(status_code=400, detail="Specifica issue_id o issue_ids")
    if body.apply_review and len(ids) > 1:
        raise HTTPException(status_code=400, detail="Le issue REVIEW_REQUIRED si applicano una alla volta")
    results = []
    for iid in ids:
        issue = await seo_issues_col.find_one({"id": iid}, {"_id": 0})
        if not issue:
            results.append({"id": iid, "applied": False, "reason": "Issue non trovata"})
            continue
        if issue.get("status") != "open":
            results.append({"id": iid, "applied": False, "reason": f"Issue già {issue.get('status')}"})
            continue
        results.append(await apply_issue_fix(issue, actor_of(principal), request_id_of(request), source=principal.get("source", "manual"), apply_review=body.apply_review))
    await audit_log(actor_of(principal), "seo_fix", "seo", "-", {"results": results}, request_id_of(request), principal.get("source", "manual"))
    return {"results": results, "applied": len([r for r in results if r.get("applied")])}


@seo_router.post("/fix-all")
async def fix_all(body: FixAllBody, request: Request, principal=Depends(require("seo:autofix"))):
    """Apply ALL open SAFE_AUTO_FIX issues (never REVIEW/CRITICAL). Runs a fresh audit first."""
    await run_audit(body.scope, body.entity_id)
    res = await apply_safe_fixes(actor_of(principal), request_id_of(request), body.scope, body.entity_id, body.dry_run, source=principal.get("source", "manual") if principal.get("source") == "ai" else "autofix")
    if not body.dry_run:
        await audit_log(actor_of(principal), "seo_fix_all", "seo", "-", {"applied": res["applied"], "skipped": res["skipped"]}, request_id_of(request), principal.get("source", "manual"))
    return res


@seo_router.post("/issues/{issue_id}/ignore")
async def ignore_issue(issue_id: str, request: Request, principal=Depends(require("seo:write"))):
    r = await seo_issues_col.update_one({"id": issue_id}, {"$set": {"status": "ignored", "ignored_at": now_iso(), "ignored_by": actor_of(principal)}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Issue non trovata")
    return {"ok": True}


@seo_router.get("/sitemap")
async def sitemap_status(principal=Depends(require("seo:read"))):
    entries = await sitemap_entries()
    by_type: Dict[str, int] = {}
    for e in entries:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    excluded = await models_col.count_documents({"stato": "pubblicata", "is_deleted": {"$ne": True}, "$or": [{"seo.indexable": False}, {"seo.robots": {"$regex": "noindex", "$options": "i"}}]})
    return {"total": len(entries), "by_type": by_type, "excluded_noindex_models": excluded, "entries": entries, "xml_url": "/api/sitemap.xml", "base_url": await site_base_url() or None}


@seo_router.get("/internal-links")
async def internal_links(principal=Depends(require("seo:read"))):
    return await internal_link_suggestions()


@seo_router.get("/redirects")
async def list_redirects(principal=Depends(require("seo:read"))):
    items = await redirects_col.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return {"items": items}


@seo_router.post("/redirects", status_code=201)
async def create_redirect(body: RedirectBody, request: Request, principal=Depends(require("seo:write"))):
    if not body.from_path.startswith("/") or not body.to_path.startswith("/"):
        raise HTTPException(status_code=400, detail="I percorsi devono iniziare con /")
    doc = await ensure_redirect(body.from_path, body.to_path, actor_of(principal), body.reason or "manual", body.status_code)
    return doc


@seo_router.delete("/redirects/{redirect_id}")
async def delete_redirect(redirect_id: str, principal=Depends(require("seo:write"))):
    r = await redirects_col.update_one({"id": redirect_id}, {"$set": {"active": False, "updated_at": now_iso()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Redirect non trovato")
    return {"ok": True}


@seo_router.get("/pages/{entity_type}/{entity_id}")
async def page_seo(entity_type: str, entity_id: str, principal=Depends(require("seo:read"))):
    """Full SEO view of a page: fields + open issues + indexability."""
    col = ENTITY_COL.get(entity_type)
    if col is None:
        raise HTTPException(status_code=400, detail="entity_type non valido")
    doc = await col.find_one({"$or": [{"id": entity_id}, {"slug": entity_id}]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Pagina non trovata")
    base = await site_base_url()
    issues = await seo_issues_col.find({"entity_type": entity_type, "entity_id": doc["id"], "status": "open"}, {"_id": 0}).to_list(100)
    if entity_type == "model":
        seo = doc.get("seo") or {}
        path = f"/modelle/{doc['slug']}"
        fields = {"title": seo.get("title"), "meta_description": seo.get("meta_description"), "slug": doc.get("slug"), "canonical": seo.get("canonical") or (f"{base}{path}" if base else path),
                  "robots": seo.get("robots", "index,follow"), "og": {"title": seo.get("og_title") or seo.get("title"), "description": seo.get("og_description") or seo.get("meta_description"), "image": seo.get("og_image")},
                  "structured_data_type": seo.get("structured_data_type", "ProfilePage"), "keywords": seo.get("keywords", []), "topics": seo.get("topics", []),
                  "alt_default": seo.get("alt_default"), "indexable": seo.get("indexable", True) and doc.get("stato") == "pubblicata"}
    else:
        path = {"article": "/articoli/", "category": "/categorie/", "landing": "/l/"}[entity_type] + doc["slug"]
        seo = doc.get("seo") or {}
        fields = {"title": doc.get("seo_title") or seo.get("title"), "meta_description": doc.get("meta_description") or seo.get("meta_description"), "slug": doc.get("slug"),
                  "canonical": doc.get("canonical") or seo.get("canonical") or (f"{base}{path}" if base else path), "indexable": doc.get("indicizzabile", seo.get("indexable", True))}
    return {"entity_type": entity_type, "entity_id": doc["id"], "path": path, "fields": fields, "open_issues": issues,
            "indexability_status": "indexable" if fields.get("indexable") else "noindex"}
