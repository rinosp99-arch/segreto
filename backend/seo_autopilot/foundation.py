"""Phase 14B — TECHNICAL SEO FOUNDATION audit (read-only, target host explicit: production when authorised).

For a given base URL:
  1. HTTP layer (GET/HEAD): status, redirects, X-Robots-Tag, meta robots, canonical in initial HTML, robots.txt, sitemap.
  2. Rendered DOM (headless Chromium): title, H1, canonical, JSON-LD, text length, internal links -> REAL link graph
     (home, /articoli, every category, every article, legal pages, a sample of profiles) -> orphan status per sitemap URL.
  3. Google URL Inspection (existing google_search layer, property host only): verdict, indexingState, coverageState,
     robotsTxtState, pageFetchState, lastCrawlTime, userCanonical, googleCanonical, referringUrls.
  4. Soft-404 probe: a non-existent profile URL (HTTP status + rendered robots).
Nothing is written to the target: results go to seo_ap_audits (kind='foundation').
"""
import asyncio
import re
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import httpx

from .crawler import parse_html, UA
from .render_audit import render_pages
from .store import audits_col, log_decision, now_iso


async def _http(client: httpx.AsyncClient, url: str) -> dict:
    try:
        r = await client.get(url)
        p = parse_html(r.text, url) if "html" in r.headers.get("content-type", "") else {}
        return {"status": r.status_code, "final_url": str(r.url), "redirects": [{"status": h.status_code, "to": h.headers.get("location")} for h in r.history],
                "x_robots": r.headers.get("x-robots-tag"), "meta_robots": p.get("robots"), "initial_title": p.get("title"), "initial_canonical": p.get("canonical"),
                "initial_h1": p.get("h1") or [], "initial_jsonld": p.get("jsonld_types") or [], "initial_text_len": p.get("text_len")}
    except Exception as e:
        return {"status": 0, "error": type(e).__name__}


def _ptype(path: str) -> str:
    seg = path.strip("/").split("/")[0] if path.strip("/") else ""
    return {"": "home", "modelle": "model", "categorie": "category", "articoli": "article" if "/" in path.strip("/") else "articles_index", "l": "landing"}.get(seg, "legal" if seg in ("privacy", "cookie", "termini", "18-plus") else "other")


async def run(base: str, inspect_limit: int = 15, render_profiles: int = 6, run_id: Optional[str] = None) -> dict:
    base = base.rstrip("/")
    host = urlsplit(base).netloc.lower()
    out: Dict[str, object] = {"kind": "foundation", "base": base, "at": now_iso(), "run_id": run_id or "manual"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"}) as client:
        # ---- robots + sitemap
        rb = await client.get(f"{base}/robots.txt")
        robots_txt = rb.text if rb.status_code == 200 else ""
        sm = await client.get(f"{base}/api/sitemap.xml")
        sitemap_urls = re.findall(r"<loc>(.*?)</loc>", sm.text) if sm.status_code == 200 else []
        out["robots"] = {"status": rb.status_code, "x_robots": rb.headers.get("x-robots-tag"), "disallow_all": bool(re.search(r"(?im)^disallow:\s*/\s*$", robots_txt)),
                         "blocks_googlebot": bool(re.search(r"(?is)user-agent:\s*googlebot.*?disallow:\s*/\s*(\n|$)", robots_txt)), "sitemap_declared": re.findall(r"(?im)^sitemap:\s*(\S+)", robots_txt), "body": robots_txt[:600]}
        out["sitemap"] = {"status": sm.status_code, "urls": len(sitemap_urls), "same_host": all(urlsplit(u).netloc.lower() == host for u in sitemap_urls), "declared_in_robots": any(host in s for s in out["robots"]["sitemap_declared"])}
        # ---- URL set
        extra = [f"{base}{p}" for p in ("/articoli", "/privacy", "/cookie", "/termini", "/18-plus")]
        urls = list(dict.fromkeys(sitemap_urls + extra))
        sem = asyncio.Semaphore(4)
        http: Dict[str, dict] = {}

        async def one(u):
            async with sem:
                http[u] = await _http(client, u)
        await asyncio.gather(*(one(u) for u in urls))
        # ---- soft-404 probe (non-existent profile / category)
        probe = {}
        for u in (f"{base}/modelle/profilo-inesistente-seo-probe", f"{base}/categorie/categoria-inesistente-seo-probe", f"{base}/pagina-inesistente-seo-probe"):
            probe[u] = await _http(client, u)
    # ---- rendered DOM + real link graph
    to_render = [u for u in urls if _ptype(urlsplit(u).path) != "model"] + [u for u in urls if _ptype(urlsplit(u).path) == "model"][:render_profiles]
    to_render += list(probe)
    rendered = await render_pages(to_render)
    linked_from: Dict[str, List[str]] = {}
    for src, r in rendered.items():
        for l in (r.get("internal_links") or []):
            l = l.rstrip("/") or l
            linked_from.setdefault(l, []).append(src)
    # ---- Google URL Inspection (property host only)
    inspections: Dict[str, dict] = {}
    from google_search import service as gs
    from google_search.config import cfg as gcfg
    prop_host = urlsplit(gcfg.property_url).netloc.lower()
    out["google"] = {"configured": gs.configured(), "property": gcfg.property_url, "applicable": host == prop_host, "inspected": 0, "errors": 0}
    if gs.configured() and gcfg.inspection_enabled and host == prop_host:
        cats = [u for u in sitemap_urls if _ptype(urlsplit(u).path) == "category"]
        models = [u for u in sitemap_urls if _ptype(urlsplit(u).path) == "model"]
        arts = [u for u in sitemap_urls if _ptype(urlsplit(u).path) == "article"]
        targets = list(dict.fromkeys([f"{base}/"] + models[:6] + cats[:5] + arts[:2] + [f"{base}/articoli"]))[:inspect_limit]
        for u in targets:
            try:
                ins = await gs.inspect(u)
                g = ins.get("google") or {}
                inspections[u] = {"state": ins.get("state"), "source": ins.get("source"), "verdict": g.get("verdict"), "indexing_state": g.get("indexing_state"), "coverage_state": g.get("coverage_state"),
                                  "robots_txt_state": g.get("robots_txt_state"), "page_fetch_state": g.get("page_fetch_state"), "last_crawl_time": g.get("last_crawl_time"),
                                  "user_canonical": g.get("user_canonical"), "google_canonical": g.get("google_canonical"), "referring_urls": g.get("referring_urls") or [], "in_sitemaps": g.get("in_sitemaps") or [],
                                  "crawled_as": g.get("crawled_as"), "error": (ins.get("error") or {}).get("error_type") if ins.get("error") else None, "detail": ins.get("detail")}
                out["google"]["inspected"] += 1 if ins.get("source") in ("google", "cache") else 0
                out["google"]["errors"] += 1 if ins.get("source") == "error" else 0
            except Exception as e:
                inspections[u] = {"state": "UNKNOWN", "error": type(e).__name__}
                out["google"]["errors"] += 1
    # ---- per-URL table
    rows = []
    for u in urls:
        h = http.get(u, {})
        r = rendered.get(u) or {}
        g = inspections.get(u)
        key = u.rstrip("/") or u
        in_sm = u in sitemap_urls
        linked = linked_from.get(key) or linked_from.get(u) or []
        noindex_hdr = "noindex" in (h.get("x_robots") or "").lower()
        noindex_meta_i = "noindex" in (h.get("meta_robots") or "").lower()
        noindex_meta_r = "noindex" in (r.get("robots") or "").lower()
        blocked = h.get("status") != 200 or noindex_hdr or noindex_meta_i or noindex_meta_r
        rendered_canonical = r.get("canonical")
        canon_ok = (rendered_canonical or "").rstrip("/") == u.rstrip("/") if rendered_canonical else None
        # technical indexability (what WE can prove: status 200, no noindex header/meta, robots allowed) — independent of Google's index decision
        real_fetch_fail = bool(g and g.get("page_fetch_state") and g["page_fetch_state"] not in ("SUCCESSFUL", "PAGE_FETCH_STATE_UNSPECIFIED"))
        robots_blocked = bool(g and g.get("robots_txt_state") == "DISALLOWED")
        if blocked or real_fetch_fail or robots_blocked:
            indexable, src = "NOT_INDEXABLE", "GOOGLE" if (real_fetch_fail or robots_blocked) else "TECH"
        elif r or (g and g.get("state") == "INDEXED"):
            indexable, src = "INDEXABLE", "GOOGLE+TECH" if g else "TECH"
        else:
            indexable, src = "INDEXABLE_HTTP_ONLY", "TECH"
        cov = (g or {}).get("coverage_state") or ""
        google_status = ("INDEXED" if (g or {}).get("state") == "INDEXED" else "UNKNOWN_TO_GOOGLE" if "sconosciuto" in cov.lower() or "unknown" in cov.lower()
                         else "DISCOVERED_NOT_INDEXED" if "rilevata" in cov.lower() or "discovered" in cov.lower() else "CRAWLED_NOT_INDEXED" if "sottoposta a scansione" in cov.lower() or "crawled" in cov.lower()
                         else "BLOCKED" if (g or {}).get("state") == "BLOCKED_ERROR" else ("NOT_INDEXED" if g else "NOT_INSPECTED"))
        rows.append({"url": u, "type": _ptype(urlsplit(u).path), "status": h.get("status"), "redirects": len(h.get("redirects") or []), "x_robots": h.get("x_robots"), "meta_robots_initial": h.get("meta_robots"), "meta_robots_rendered": r.get("robots"),
                     "INDEXABLE": indexable, "indexable_source": src, "GOOGLE_INDEX_STATUS": google_status, "in_sitemap": in_sm, "sitemap_status": "IN_SITEMAP" if in_sm else ("SHOULD_BE_IN_SITEMAP" if _ptype(urlsplit(u).path) in ("articles_index",) else "NOT_IN_SITEMAP_OK"),
                     "orphan_status": ("LINKED" if linked else ("ORPHAN" if rendered else "UNKNOWN")), "linked_from": sorted(set(linked))[:6], "n_inlinks": len(set(linked)),
                     "initial": {"title": h.get("initial_title"), "h1": (h.get("initial_h1") or [None])[0], "canonical": h.get("initial_canonical"), "jsonld": h.get("initial_jsonld"), "text_len": h.get("initial_text_len")},
                     "rendered": {"title": r.get("title"), "h1": (r.get("h1") or [None])[0], "h1_count": len(r.get("h1") or []), "canonical": rendered_canonical, "canonical_matches_url": canon_ok, "jsonld": r.get("jsonld_types"), "text_len": r.get("text_len"), "links": len(r.get("internal_links") or []), "error": r.get("error")} if r else None,
                     "GOOGLE_CANONICAL": (g or {}).get("google_canonical"), "USER_CANONICAL": (g or {}).get("user_canonical"), "google": g})
    # ---- soft 404
    soft = []
    for u, h in probe.items():
        r = rendered.get(u) or {}
        if r.get("error") or not r:
            v = "UNKNOWN_RENDER_FAILED"
        elif h.get("status") == 200 and "noindex" in (r.get("robots") or "").lower():
            v = "OK_NOINDEX"
        elif h.get("status") == 200:
            v = "SOFT_404_RISK"
        else:
            v = "OK_404"
        soft.append({"url": u, "status": h.get("status"), "rendered_robots": r.get("robots"), "rendered_title": r.get("title"), "rendered_error": r.get("error"), "verdict": v})
    out["soft_404"] = soft
    # ---- findings + verdict
    findings = []
    hdr = [x["url"] for x in rows if "noindex" in (x["x_robots"] or "").lower()]
    meta = [x["url"] for x in rows if "noindex" in ((x["meta_robots_initial"] or "") + ((x["rendered"] or {}).get("robots") or "" if x["rendered"] else "")).lower() and x["in_sitemap"]]
    if hdr:
        prod = host == prop_host
        findings.append({"code": "X_ROBOTS_NOINDEX", "severity": "CRITICAL" if prod else "INFO", "detail": f"{len(hdr)} URL con header X-Robots-Tag noindex" + ("" if prod else " — ambiente preview (header di piattaforma, atteso; NON presente in produzione)"), "urls": hdr[:5]})
    if meta:
        findings.append({"code": "META_NOINDEX_ON_SITEMAP_URL", "severity": "CRITICAL", "detail": f"{len(meta)} URL in sitemap con meta noindex", "urls": meta[:5]})
    if out["robots"]["disallow_all"] or out["robots"]["blocks_googlebot"]:
        findings.append({"code": "ROBOTS_BLOCKS", "severity": "CRITICAL", "detail": "robots.txt blocca il crawling", "urls": [f"{base}/robots.txt"]})
    non200 = [x["url"] for x in rows if x["status"] != 200]
    if non200:
        findings.append({"code": "URL_NOT_200", "severity": "HIGH", "detail": f"{len(non200)} URL non 200", "urls": non200[:10]})
    orphans = [x["url"] for x in rows if x["orphan_status"] == "ORPHAN" and x["in_sitemap"]]
    if orphans:
        findings.append({"code": "ORPHAN_IN_SITEMAP", "severity": "MEDIUM", "detail": f"{len(orphans)} URL in sitemap senza alcun link interno nel DOM renderizzato di {len(rendered)} pagine", "urls": orphans})
    missing = [x["url"] for x in rows if x["sitemap_status"] == "SHOULD_BE_IN_SITEMAP"]
    if missing:
        findings.append({"code": "MISSING_FROM_SITEMAP", "severity": "MEDIUM", "detail": "pagina pubblica indicizzabile assente dalla sitemap", "urls": missing})
    canon_bad = [x["url"] for x in rows if x["rendered"] and x["rendered"]["canonical_matches_url"] is False]
    if canon_bad:
        findings.append({"code": "CANONICAL_MISMATCH_RENDERED", "severity": "HIGH", "detail": f"{len(canon_bad)} URL con canonical renderizzata diversa dall'URL", "urls": canon_bad[:10]})
    gcanon_bad = [x["url"] for x in rows if x["GOOGLE_CANONICAL"] and x["GOOGLE_CANONICAL"].rstrip("/") != x["url"].rstrip("/")]
    if gcanon_bad:
        findings.append({"code": "GOOGLE_CANONICAL_DIFFERS", "severity": "HIGH", "detail": f"{len(gcanon_bad)} URL dove Google ha scelto un canonical diverso", "urls": gcanon_bad[:10]})
    fetch_bad = [u for u, g in inspections.items() if g.get("page_fetch_state") and g["page_fetch_state"] not in ("SUCCESSFUL", "PAGE_FETCH_STATE_UNSPECIFIED")]
    robots_bad = [u for u, g in inspections.items() if g.get("robots_txt_state") == "DISALLOWED"]
    if robots_bad:
        findings.append({"code": "GOOGLE_ROBOTS_DISALLOWED", "severity": "CRITICAL", "detail": f"{len(robots_bad)} URL bloccate da robots.txt secondo Google", "urls": robots_bad[:10]})
    discovered = [u for u, g in inspections.items() if "rilevata" in (g.get("coverage_state") or "").lower() or "discovered" in (g.get("coverage_state") or "").lower()]
    if discovered:
        findings.append({"code": "GOOGLE_DISCOVERED_NOT_INDEXED", "severity": "INFO", "detail": f"{len(discovered)} URL 'Rilevata, ma attualmente non indicizzata': Google le conosce dalla sitemap ma non le ha ancora scansionate (pageFetchState non tentato). Non è un blocco tecnico: dipende da priorità di crawl/segnali (link interni, tempo).", "urls": discovered[:10]})
    unknown_g = [u for u, g in inspections.items() if "sconosciuto" in (g.get("coverage_state") or "").lower()]
    if unknown_g:
        findings.append({"code": "GOOGLE_URL_UNKNOWN", "severity": "LOW", "detail": f"{len(unknown_g)} URL sconosciute a Google (non ancora lette dalla sitemap o assenti da essa)", "urls": unknown_g[:10]})
    if fetch_bad:
        findings.append({"code": "GOOGLE_FETCH_PROBLEM", "severity": "CRITICAL", "detail": f"{len(fetch_bad)} URL con pageFetchState non SUCCESSFUL", "urls": fetch_bad[:10]})
    if any(s["verdict"] == "SOFT_404_RISK" for s in soft):
        findings.append({"code": "SOFT_404_RISK", "severity": "MEDIUM", "detail": "URL inesistenti rispondono 200 senza noindex nel DOM renderizzato (soft 404)", "urls": [s["url"] for s in soft if s["verdict"] == "SOFT_404_RISK"]})
    h1_brand = [x["url"] for x in rows if x["rendered"] and (x["rendered"]["h1"] or "").strip().lower() in ("lato segreto",)]
    if len(h1_brand) >= 3:
        findings.append({"code": "H1_BRAND_ONLY", "severity": "LOW", "detail": f"H1 = brand su {len(h1_brand)}/{sum(1 for x in rows if x['rendered'])} pagine renderizzate (non bloccante; nessuna modifica in questa fase)", "urls": h1_brand[:5]})
    blockers = [f for f in findings if f["severity"] == "CRITICAL"]
    not_indexed_google = [u for u, g in inspections.items() if g.get("state") == "NOT_INDEXED" and (g.get("coverage_state") or "")]
    out.update({"rows": rows, "inspections": inspections, "findings": findings, "rendered_pages": len(rendered),
                "verdict": {"BASE_SEO": "INDICIZZABILE" if not blockers else "NON_INDICIZZABILE", "blockers": blockers,
                            "google_indexed": sum(1 for g in inspections.values() if g.get("state") == "INDEXED"), "google_not_indexed": len(not_indexed_google),
                            "google_unknown": sum(1 for g in inspections.values() if g.get("state") not in ("INDEXED", "NOT_INDEXED")),
                            "google_discovered_not_indexed": len(discovered), "google_unknown_url": len(unknown_g),
                            "note": "Verdetto TECNICO (header/meta noindex, robots.txt, status HTTP, pageFetchState, robotsTxtState). 'Rilevata ma non indicizzata' = Google non ha ancora scansionato l'URL: non è un blocco tecnico ma indica bassa priorità di crawl (pochi link interni / sito nuovo)."}})
    await audits_col.update_one({"kind": "foundation", "base": base}, {"$set": out}, upsert=True)
    await log_decision(run_id, "FOUNDATION_AUDIT", base, f"BASE_SEO={out['verdict']['BASE_SEO']} · {len(rows)} URL · {len(findings)} rilevazioni · Google: {out['google']['inspected']} ispezioni, {out['verdict']['google_indexed']} indicizzate — solo lettura", metrics={"findings": [f["code"] for f in findings]}, kind="foundation")
    return out
