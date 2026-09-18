"""READ-ONLY technical crawler (rule 15) + adult/OnlyFans SEO audit (rule 17).

Scope: the environment we run in (SEO_CRAWL_BASE_URL — decision 3a). URL set = sitemap entries (single source of truth,
v1_seo.sitemap_entries) + legal pages + /articoli, plus internal links found in rendered DOMs (render_audit).
For every URL: status, redirects, initial HTML (title/description/H1/canonical/robots/JSON-LD/img alt/links), sitemap presence.
HTTP only, small concurrency, custom UA. Findings are REPORTED (seo_ap_tech_pages / seo_ap_audits), never fixed.
"""
import asyncio
import json
import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

from database import models_col, config_col

from .store import tech_col, audits_col, render_col, log_decision, now_iso, crawl_base_url
from .textnorm import similarity

UA = "LatoSegreto-SEO-Autopilot/1.0 (+read-only technical audit)"
MAX_URLS = 250
CONCURRENCY = 4
EXTRA_PATHS = ["/articoli", "/privacy", "/cookie", "/termini", "/18-plus"]


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self._in_title = "", False
        self.h1: List[str] = []
        self._in_h1 = False
        self.metas: List[dict] = []
        self.links: List[dict] = []
        self.anchors: List[str] = []
        self.imgs: List[dict] = []
        self.jsonld: List[str] = []
        self._in_ld = False
        self.text_len = 0
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
            self.h1.append("")
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
        elif tag == "a" and a.get("href"):
            self.anchors.append(a["href"])
        elif tag == "img":
            self.imgs.append(a)
        elif tag == "script":
            if (a.get("type") or "").lower() == "application/ld+json":
                self._in_ld = True
                self.jsonld.append("")
            else:
                self._skip += 1
        elif tag == "style":
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "script":
            if self._in_ld:
                self._in_ld = False
            elif self._skip:
                self._skip -= 1
        elif tag == "style" and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_h1 and self.h1:
            self.h1[-1] += data
        if self._in_ld and self.jsonld:
            self.jsonld[-1] += data
        elif not self._skip and not self._in_title:
            self.text_len += len(data.strip())


def parse_html(html: str, url: str) -> dict:
    p = _P()
    try:
        p.feed(html or "")
    except Exception:
        pass
    meta = {}
    for m in p.metas:
        k = (m.get("name") or m.get("property") or "").lower()
        if k:
            meta.setdefault(k, m.get("content"))
    canonical = next((l.get("href") for l in p.links if (l.get("rel") or "").lower() == "canonical"), None)
    ld = []
    for s in p.jsonld:
        try:
            d = json.loads(s)
            ld.append(d.get("@type") if isinstance(d, dict) else "list")
        except Exception:
            ld.append("INVALID_JSON")
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
    internal, external = [], []
    for h in p.anchors:
        if h.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = urljoin(url, h)
        (internal if full.startswith(origin) else external).append(full.split("#")[0])
    return {"title": " ".join(p.title.split()), "meta_description": meta.get("description"), "robots": meta.get("robots"), "h1": [" ".join(h.split()) for h in p.h1 if h.strip()],
            "canonical": canonical, "og_title": meta.get("og:title"), "og_image": meta.get("og:image"), "viewport": bool(meta.get("viewport")), "jsonld_types": ld,
            "internal_links": sorted(set(internal)), "external_links": sorted(set(external)), "images": len(p.imgs), "images_without_alt": sum(1 for i in p.imgs if not (i.get("alt") or "").strip()),
            "text_len": p.text_len, "rating": meta.get("rating")}


def _ptype(path: str) -> str:
    if path in ("", "/"):
        return "home"
    seg = path.strip("/").split("/")[0]
    return {"modelle": "model", "categorie": "category", "articoli": "article", "l": "landing"}.get(seg, "legal" if seg in ("privacy", "cookie", "termini", "18-plus") else "other")


async def url_set(base: str) -> Tuple[List[dict], set]:
    """Sitemap entries (read-only, same function as the public sitemap) + extra public routes."""
    from v1_seo import sitemap_entries
    entries = await sitemap_entries(base)
    in_sitemap = {base + e["path"] for e in entries}
    urls = [{"url": base + e["path"], "page_type": e.get("type") or _ptype(e["path"]), "in_sitemap": True} for e in entries]
    for p in EXTRA_PATHS:
        if base + p not in in_sitemap:
            urls.append({"url": base + p, "page_type": _ptype(p), "in_sitemap": False})
    # links discovered in rendered DOMs of previous samples (internal only, same origin)
    known = {u["url"] for u in urls}
    async for r in render_col.find({}, {"_id": 0, "rendered": 1}).sort("checked_at", -1).limit(60):
        for l in ((r.get("rendered") or {}).get("internal_links") or []):
            l = l.rstrip("/") or l
            if l.startswith(base) and l not in known and "/admin" not in l and len(urls) < MAX_URLS and not urlsplit(l).query:
                urls.append({"url": l, "page_type": _ptype(urlsplit(l).path), "in_sitemap": l in in_sitemap, "discovered": True})
                known.add(l)
    return urls[:MAX_URLS], in_sitemap


async def fetch(client: httpx.AsyncClient, url: str) -> dict:
    chain = []
    try:
        r = await client.get(url)
        for h in r.history:
            chain.append({"status": h.status_code, "to": h.headers.get("location")})
        return {"status_code": r.status_code, "final_url": str(r.url), "redirects": chain, "content_type": r.headers.get("content-type", ""), "x_robots": r.headers.get("x-robots-tag"),
                "html": r.text if "html" in r.headers.get("content-type", "") else "", "bytes": len(r.content), "elapsed_ms": int(r.elapsed.total_seconds() * 1000) if r.elapsed else None}
    except Exception as e:
        return {"status_code": 0, "error": f"{type(e).__name__}", "redirects": chain, "html": ""}


async def head_ok(client: httpx.AsyncClient, url: str) -> Tuple[int, Optional[str]]:
    try:
        r = await client.head(url)
        if r.status_code in (405, 403):
            r = await client.get(url)
        return r.status_code, None
    except Exception as e:
        return 0, type(e).__name__


async def crawl(run_id: Optional[str], base: Optional[str] = None, check_links: bool = True) -> dict:
    base = (base or crawl_base_url()).rstrip("/")
    urls, in_sitemap = await url_set(base)
    findings: List[dict] = []
    results: List[dict] = []
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0), follow_redirects=True, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"}) as client:
        # robots + sitemap first
        robots = await fetch(client, f"{base}/robots.txt")
        robots_txt = robots.get("html") or ""
        try:
            robots_txt = (await client.get(f"{base}/robots.txt")).text if robots.get("status_code") == 200 else robots_txt
        except Exception:
            pass
        sm = await fetch(client, f"{base}/api/sitemap.xml")
        sm_ok = sm.get("status_code") == 200 and "<urlset" in (sm.get("html") or await _text(client, f"{base}/api/sitemap.xml"))

        async def one(u: dict):
            async with sem:
                f = await fetch(client, u["url"])
            parsed = parse_html(f.get("html", ""), u["url"]) if f.get("html") else {}
            doc = {**u, **{k: v for k, v in f.items() if k != "html"}, "initial_html": parsed, "checked_at": now_iso(), "run_id": run_id, "base": base,
                   "title": parsed.get("title"), "meta_description": parsed.get("meta_description"), "h1": parsed.get("h1"), "canonical": parsed.get("canonical"), "robots": parsed.get("robots"),
                   "indexable_initial": f.get("status_code") == 200 and "noindex" not in ((parsed.get("robots") or "") + (f.get("x_robots") or "")).lower()}
            results.append(doc)
        await asyncio.gather(*(one(u) for u in urls))
        # link check: internal links seen in rendered DOMs + OnlyFans/social outbound from the model DB (HEAD, low volume)
        broken = []
        if check_links:
            targets = set()
            async for r in render_col.find({}, {"_id": 0, "rendered": 1}).sort("checked_at", -1).limit(40):
                for l in ((r.get("rendered") or {}).get("internal_links") or []):
                    if l.startswith(base) and "/admin" not in l:
                        targets.add(l.split("?")[0])
            crawled = {r["url"].rstrip("/") for r in results}
            targets = [t for t in targets if t.rstrip("/") not in crawled][:60]

            async def chk(t):
                async with sem:
                    st, err = await head_ok(client, t)
                if st == 0 or st >= 400:
                    broken.append({"url": t, "status": st, "error": err, "kind": "internal"})
            await asyncio.gather(*(chk(t) for t in targets))
    # ---------------------------------------------------------------- findings
    def add(code, severity, detail, url=None):
        findings.append({"code": code, "severity": severity, "detail": detail, "url": url})
    if robots.get("status_code") != 200:
        add("ROBOTS_MISSING", "HIGH", f"robots.txt non raggiungibile (status {robots.get('status_code')})", f"{base}/robots.txt")
    else:
        if re.search(r"(?im)^disallow:\s*/\s*$", robots_txt):
            add("ROBOTS_BLOCKS_ALL", "CRITICAL", "robots.txt contiene 'Disallow: /' — Googlebot bloccato", f"{base}/robots.txt")
        if "googlebot" in robots_txt.lower() and re.search(r"(?is)user-agent:\s*googlebot.*?disallow:\s*/\s*(\n|$)", robots_txt):
            add("ROBOTS_BLOCKS_GOOGLEBOT", "CRITICAL", "regola specifica che blocca Googlebot", f"{base}/robots.txt")
        sm_decl = re.findall(r"(?im)^sitemap:\s*(\S+)", robots_txt)
        if not sm_decl:
            add("ROBOTS_NO_SITEMAP", "LOW", "robots.txt non dichiara la Sitemap", f"{base}/robots.txt")
        elif not any(s.startswith(base) for s in sm_decl):
            add("ROBOTS_SITEMAP_OTHER_HOST", "INFO", f"la Sitemap dichiarata punta a un altro host ({sm_decl[0]}): normale in preview, da verificare in produzione", f"{base}/robots.txt")
    if not sm_ok:
        add("SITEMAP_UNAVAILABLE", "HIGH", f"/api/sitemap.xml non valida o non raggiungibile (status {sm.get('status_code')})", f"{base}/api/sitemap.xml")
    titles: Dict[str, List[str]] = {}
    descs: Dict[str, List[str]] = {}
    ok_pages = [r for r in results if r.get("status_code") == 200]
    # site-wide patterns are reported ONCE (a SPA has the same initial HTML everywhere): per-page details stay on the page docs
    spa_codes = {"H1_MISSING_INITIAL": 0, "CANONICAL_MISSING_INITIAL": 0, "STRUCTURED_DATA_MISSING_INITIAL": 0, "THIN_INITIAL_HTML": 0}
    hdr_noindex = [r["url"] for r in ok_pages if "noindex" in (r.get("x_robots") or "").lower()]
    is_property_host = _same_host(base, _property_host())
    if hdr_noindex and len(hdr_noindex) >= max(1, int(0.8 * len(ok_pages))):
        add("X_ROBOTS_NOINDEX_SITEWIDE", "CRITICAL" if is_property_host else "INFO",
            f"header X-Robots-Tag noindex su {len(hdr_noindex)}/{len(ok_pages)} pagine — " + ("GOOGLEBOT BLOCCATO IN PRODUZIONE" if is_property_host else "atteso in ambiente preview (header di piattaforma); verificare che in produzione NON sia presente"), f"{base}/")
        hdr_noindex_set = set(hdr_noindex)
    else:
        hdr_noindex_set = set()
    for r in results:
        u = r["url"]
        if r.get("status_code") != 200:
            add("URL_NOT_200" if r.get("status_code") else "URL_UNREACHABLE", "CRITICAL" if r.get("in_sitemap") else "HIGH", f"status {r.get('status_code')} {r.get('error') or ''}".strip(), u)
            continue
        if r.get("redirects"):
            add("REDIRECT_CHAIN", "MEDIUM" if len(r["redirects"]) > 1 else "LOW", f"{len(r['redirects'])} redirect prima della risposta finale ({r.get('final_url')})", u)
        ih = r.get("initial_html") or {}
        if not r.get("indexable_initial") and u not in hdr_noindex_set:
            add("NOINDEX_INITIAL", "HIGH" if r.get("in_sitemap") else "INFO", f"noindex nell'HTML iniziale/header (robots={ih.get('robots')}, x-robots={r.get('x_robots')})", u)
        if not ih.get("title"):
            add("TITLE_MISSING_INITIAL", "MEDIUM", "nessun <title> nell'HTML iniziale", u)
        if not ih.get("h1"):
            spa_codes["H1_MISSING_INITIAL"] += 1
        if not ih.get("canonical"):
            spa_codes["CANONICAL_MISSING_INITIAL"] += 1
        if not ih.get("jsonld_types"):
            spa_codes["STRUCTURED_DATA_MISSING_INITIAL"] += 1
        if "INVALID_JSON" in (ih.get("jsonld_types") or []):
            add("STRUCTURED_DATA_INVALID", "MEDIUM", "JSON-LD non parsabile", u)
        if ih.get("images_without_alt"):
            add("IMG_WITHOUT_ALT", "LOW", f"{ih['images_without_alt']}/{ih.get('images')} immagini senza alt (HTML iniziale)", u)
        if not ih.get("viewport"):
            add("NO_VIEWPORT", "MEDIUM", "meta viewport assente (mobile)", u)
        if (ih.get("text_len") or 0) < 200:
            spa_codes["THIN_INITIAL_HTML"] += 1
        if ih.get("canonical") and ih["canonical"].rstrip("/") != u.rstrip("/"):
            add("CANONICAL_MISMATCH_INITIAL", "MEDIUM", f"canonical iniziale {ih['canonical']} ≠ URL", u)
        if not r.get("in_sitemap") and r.get("page_type") in ("model", "category", "article", "landing"):
            add("NOT_IN_SITEMAP", "MEDIUM", "pagina pubblica 200 non presente nella sitemap", u)
        titles.setdefault((ih.get("title") or "").strip().lower(), []).append(u)
        descs.setdefault((ih.get("meta_description") or "").strip().lower(), []).append(u)
    for t, us in titles.items():
        if t and len(us) > 1:
            add("DUPLICATE_TITLE_INITIAL", "INFO" if len(us) == len(results) else "LOW", f"{len(us)} URL con lo stesso title iniziale '{t[:60]}' (SPA: il title reale è nel DOM renderizzato)", None)
    if ok_pages and any(v for v in spa_codes.values()):
        n = len(ok_pages)
        add("CLIENT_SIDE_RENDERING", "MEDIUM", "HTML iniziale senza elementi SEO (resi da JavaScript): " + ", ".join(f"{k.replace('_INITIAL', '').replace('THIN_', '').lower()} {v}/{n}" for k, v in spa_codes.items() if v)
            + " — Google deve renderizzare ogni pagina (nessun SSR/prerender). Solo report: nessuna modifica in questa fase.", f"{base}/")
    for d, us in descs.items():
        if d and len(us) > 1:
            add("DUPLICATE_DESCRIPTION_INITIAL", "INFO" if len(us) == len(results) else "LOW", f"{len(us)} URL con la stessa description iniziale", None)
    for b in broken:
        add("BROKEN_INTERNAL_LINK", "HIGH", f"link interno rotto (status {b['status']} {b.get('error') or ''})".strip(), b["url"])
    # orphan: in sitemap but never linked in any rendered sample (only if we have samples)
    linked = set()
    async for r in render_col.find({}, {"_id": 0, "rendered": 1}).sort("checked_at", -1).limit(60):
        linked.update(l.rstrip("/") for l in ((r.get("rendered") or {}).get("internal_links") or []))
    if linked:
        for u in in_sitemap:
            if u.rstrip("/") not in linked and _ptype(urlsplit(u).path) != "home":
                add("POSSIBLY_ORPHAN", "LOW", "URL in sitemap ma non linkata da nessuna pagina del campione renderizzato", u)
    # persist per-URL results (upsert by url) + prune stale
    seen = []
    for r in results:
        await tech_col.update_one({"url": r["url"]}, {"$set": r, "$setOnInsert": {"first_seen": now_iso()}}, upsert=True)
        seen.append(r["url"])
    await tech_col.delete_many({"url": {"$nin": seen}, "base": base})
    by_sev: Dict[str, int] = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    summary = {"base": base, "urls": len(results), "ok_200": sum(1 for r in results if r.get("status_code") == 200), "in_sitemap": len(in_sitemap), "broken_links": len(broken), "findings": len(findings), "by_severity": by_sev}
    await audits_col.update_one({"kind": "tech", "run_id": run_id or "manual"}, {"$set": {"kind": "tech", "run_id": run_id or "manual", "at": now_iso(), "summary": summary, "findings": findings[:400]}}, upsert=True)
    await log_decision(run_id, "TECH_AUDIT", base, f"{len(results)} URL analizzati, {len(findings)} rilevazioni {by_sev}, {len(broken)} link rotti — solo report", metrics=summary, kind="tech")
    return {"summary": summary, "findings": findings, "results": results}


async def _text(client, url):
    try:
        return (await client.get(url)).text
    except Exception:
        return ""


def _property_host() -> str:
    try:
        from google_search.config import cfg as gcfg
        return urlsplit(gcfg.property_url).netloc.lower()
    except Exception:
        return ""


def _same_host(a: str, b: str) -> bool:
    ha = urlsplit(a if "://" in a else f"https://{a}").netloc.lower()
    hb = urlsplit(b if "://" in b else f"https://{b}").netloc.lower()
    return bool(ha) and ha == hb


# ------------------------------------------------------------------------------------------------ adult / OnlyFans audit (read-only)
EXPLICIT_WORDS = re.compile(r"\b(porn|porno|xxx|sesso|sex|nud[aoie]|nude|naked|hardcore|escort|hot\s*video|fetish|bdsm)\b", re.I)


async def adult_audit(run_id: Optional[str], tech_results: List[dict], render_docs: List[dict]) -> dict:
    base = crawl_base_url()
    findings: List[dict] = []

    def add(code, severity, detail, url=None):
        findings.append({"code": code, "severity": severity, "detail": detail, "url": url})
    # 1) Googlebot blocked? meta noindex vs header X-Robots-Tag (platform header is expected in preview, critical in production)
    meta_block = [r["url"] for r in tech_results if r.get("in_sitemap") and r.get("status_code") == 200 and "noindex" in (((r.get("initial_html") or {}).get("robots")) or "").lower()]
    hdr_block = [r["url"] for r in tech_results if r.get("in_sitemap") and r.get("status_code") == 200 and "noindex" in (r.get("x_robots") or "").lower()]
    prod = _same_host(base, _property_host())
    if meta_block:
        add("GOOGLEBOT_NOINDEX_META_ON_PUBLIC", "HIGH", f"{len(meta_block)} URL pubbliche in sitemap con meta robots noindex", meta_block[0])
    if hdr_block:
        add("GOOGLEBOT_NOINDEX_HEADER", "CRITICAL" if prod else "INFO", f"header X-Robots-Tag noindex su {len(hdr_block)} URL in sitemap — " + ("Googlebot bloccato in PRODUZIONE" if prod else "ambiente preview: header di piattaforma atteso, non riguarda la produzione"), hdr_block[0])
    if not meta_block and not hdr_block:
        add("GOOGLEBOT_NOT_BLOCKED", "INFO", "nessun noindex (meta o header) sulle URL pubbliche in sitemap")
    # 2) rating meta / explicit signals in public text (initial + rendered)
    rated = sum(1 for r in tech_results if ((r.get("initial_html") or {}).get("rating") or "").lower() in ("adult", "rta-5042-1996-1400-1577-rta"))
    add("ADULT_RATING_META", "INFO", f"meta rating=adult presente su {rated}/{len(tech_results)} pagine — {'coerente con SafeSearch' if rated else 'assente: Google può classificare autonomamente; valutare in futuro (nessuna modifica ora)'}")
    explicit_pages = []
    for d in render_docs:
        txt = " ".join([(d.get("rendered") or {}).get("title") or "", (d.get("rendered") or {}).get("meta_description") or "", " ".join((d.get("rendered") or {}).get("h1") or []), (d.get("rendered") or {}).get("text_sample") or ""])
        hits = sorted({m.lower() for m in EXPLICIT_WORDS.findall(txt)})
        if hits:
            explicit_pages.append({"url": d["url"], "terms": hits})
    if explicit_pages:
        add("EXPLICIT_TERMS_IN_PUBLIC_TEXT", "MEDIUM", f"{len(explicit_pages)} pagine del campione contengono termini che possono attivare SafeSearch: {explicit_pages[0]['terms']}", explicit_pages[0]["url"])
    else:
        add("NO_EXPLICIT_TERMS_IN_SAMPLE", "INFO", f"nessun termine esplicito nel testo pubblico di {len(render_docs)} pagine renderizzate")
    # 3) public vs secret: verify the secret content is behind an API route not linked in public DOM / not in sitemap
    secret_links = [l for d in render_docs for l in ((d.get("rendered") or {}).get("internal_links") or []) if "/segreto" in l]
    add("PUBLIC_SECRET_SEPARATION", "HIGH" if secret_links else "INFO", f"{len(secret_links)} link pubblici verso contenuti 'segreto' nel campione" if secret_links else "nessun link pubblico verso il Lato Segreto nel DOM renderizzato: separazione pubblico/segreto rispettata")
    # 4) media fetchability (public preview images of published models, HEAD only, max 20)
    media_checked, media_bad = 0, []
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True, headers={"User-Agent": UA}) as client:
        async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "media_pairs": 1}).limit(20):
            pairs = m.get("media_pairs") or []
            pub = ((pairs[0].get("pubblico") or {}) if pairs else {}).get("url")
            if not pub:
                continue
            u = pub if pub.startswith("http") else f"{base}{pub if pub.startswith('/') else '/' + pub}"
            st, err = await head_ok(client, u)
            media_checked += 1
            if st == 0 or st >= 400:
                media_bad.append({"model": m["slug"], "url": u, "status": st, "error": err})
    if media_bad:
        add("PUBLIC_MEDIA_NOT_FETCHABLE", "HIGH", f"{len(media_bad)}/{media_checked} media pubblici non raggiungibili (es. {media_bad[0]['model']}: status {media_bad[0]['status']})", media_bad[0]["url"])
    else:
        add("PUBLIC_MEDIA_FETCHABLE", "INFO", f"{media_checked}/{media_checked} media pubblici campionati raggiungibili")
    # 5) age gate: does the initial HTML/rendered DOM keep content crawlable? (informational)
    cfg = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    add("AGE_GATE_MODE", "INFO", "age gate lato client (overlay): il contenuto resta nel DOM e crawlabile; nessuna modifica prevista in questa fase" if not (cfg.get("flags") or {}).get("age_gate_blocking") else "age gate bloccante: verificare che Googlebot veda il contenuto")
    recs = ["Non pubblicare testo esplicito nelle pagine pubbliche (title/H1/description): il Lato Segreto resta dietro interazione.",
            "Valutare in una fase FULL la meta rating=adult solo se si accetta l'esclusione da SafeSearch (decisione editoriale, non automatica).",
            "Mantenere media pubblici raggiungibili senza autenticazione e con alt descrittivi non espliciti."]
    out = {"findings": findings, "recommendations": recs, "explicit_pages": explicit_pages[:20], "media": {"checked": media_checked, "unreachable": media_bad[:10]}, "at": now_iso()}
    await audits_col.update_one({"kind": "adult", "run_id": run_id or "manual"}, {"$set": {"kind": "adult", "run_id": run_id or "manual", **out}}, upsert=True)
    await log_decision(run_id, "ADULT_AUDIT", base, f"{len(findings)} rilevazioni; {len(explicit_pages)} pagine con termini sensibili; media non raggiungibili {len(media_bad)} — solo report", metrics={"explicit_pages": len(explicit_pages), "media_unreachable": len(media_bad)}, kind="adult")
    return out


def duplicates_in_rendered(render_docs: List[dict]) -> List[dict]:
    """Duplicate / too similar title, description, H1 across rendered pages (the real signal for a SPA)."""
    out = []
    docs = [d for d in render_docs if (d.get("rendered") or {}).get("title")]
    for i, a in enumerate(docs):
        for b in docs[i + 1:]:
            ra, rb = a["rendered"], b["rendered"]
            if ra.get("title", "").lower() == rb.get("title", "").lower():
                out.append({"code": "DUPLICATE_TITLE_RENDERED", "severity": "MEDIUM", "detail": f"title identico: '{ra['title'][:70]}'", "url": f"{a['url']} + {b['url']}"})
            elif similarity(ra.get("title", ""), rb.get("title", "")) >= 0.85:
                out.append({"code": "SIMILAR_TITLE_RENDERED", "severity": "LOW", "detail": f"title molto simili: '{ra['title'][:50]}' / '{rb['title'][:50]}'", "url": f"{a['url']} + {b['url']}"})
            if ra.get("meta_description") and ra.get("meta_description") == rb.get("meta_description"):
                out.append({"code": "DUPLICATE_DESCRIPTION_RENDERED", "severity": "MEDIUM", "detail": "meta description identica", "url": f"{a['url']} + {b['url']}"})
            ha, hb = (ra.get("h1") or [""])[0], (rb.get("h1") or [""])[0]
            if ha and ha.lower() == hb.lower():
                out.append({"code": "DUPLICATE_H1_RENDERED", "severity": "MEDIUM", "detail": f"H1 identico: '{ha[:60]}'", "url": f"{a['url']} + {b['url']}"})
    return out
