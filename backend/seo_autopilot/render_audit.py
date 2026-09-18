"""React rendering audit (rule 16 — decision 4a): INITIAL_HTML vs RENDERED_DOM (headless Chromium, <= DAILY_BROWSER_BUDGET
pages/day, background only) vs GOOGLE_INSPECTION (URL Inspection API through the existing google_search layer, selective).
Read-only: it observes what a browser and what Google see; it changes nothing. No SSR/prerender is implemented here."""
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .store import render_col, tech_col, state_col, audits_col, log_decision, now_iso, crawl_base_url

DAILY_BROWSER_BUDGET = int(os.environ.get("SEO_AUTOPILOT_RENDER_DAILY", "30"))
PER_RUN = int(os.environ.get("SEO_AUTOPILOT_RENDER_PER_RUN", "10"))
INSPECT_PER_RUN = int(os.environ.get("SEO_AUTOPILOT_INSPECT_PER_RUN", "5"))
CHROME = os.environ.get("SEO_AUTOPILOT_CHROME", "/usr/bin/google-chrome")
PAGE_TIMEOUT_MS = 30000

JS_EXTRACT = """() => {
  const q = (s) => document.querySelector(s);
  const meta = (n) => (q(`meta[name="${n}"]`) || q(`meta[property="${n}"]`) || {}).content || null;
  const ld = [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => { try { const d = JSON.parse(s.textContent); return d['@type'] || 'list'; } catch (e) { return 'INVALID_JSON'; } });
  const links = [...document.querySelectorAll('a[href]')].map(a => a.href).filter(h => h.startsWith(location.origin)).map(h => h.split('#')[0]);
  const imgs = [...document.querySelectorAll('img')];
  const text = (document.body && document.body.innerText) || '';
  return { title: document.title || '', meta_description: meta('description'), robots: meta('robots'), canonical: (q('link[rel="canonical"]') || {}).href || null,
           h1: [...document.querySelectorAll('h1')].map(h => h.innerText.trim()).filter(Boolean), jsonld_types: ld, internal_links: [...new Set(links)].sort(),
           images: imgs.length, images_without_alt: imgs.filter(i => !(i.getAttribute('alt') || '').trim()).length, text_len: text.replace(/\\s+/g, ' ').trim().length,
           text_sample: text.replace(/\\s+/g, ' ').trim().slice(0, 1500), og_title: meta('og:title'), viewport: !!q('meta[name="viewport"]'),
           h2: [...document.querySelectorAll('h2')].map(h => h.innerText.trim()).filter(Boolean).slice(0, 12) };
}"""


async def _rendered_today() -> int:
    st = await state_col.find_one({"id": "global"}, {"_id": 0, "render_calls": 1}) or {}
    return int(((st.get("render_calls") or {}).get(now_iso()[:10])) or 0)


async def _count_render(n: int = 1):
    await state_col.update_one({"id": "global"}, {"$inc": {f"render_calls.{now_iso()[:10]}": n}}, upsert=True)


async def pick_urls(limit: int) -> List[dict]:
    """Priority: never rendered > tech problems > not rendered for 7+ days; home + one of each page type always represented."""
    pages = [p async for p in tech_col.find({"status_code": 200}, {"_id": 0, "url": 1, "page_type": 1, "in_sitemap": 1})]
    last: Dict[str, str] = {}
    async for r in render_col.find({}, {"_id": 0, "url": 1, "checked_at": 1}).sort("checked_at", -1):
        last.setdefault(r["url"], r["checked_at"])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    def prio(p):
        s = 0
        if p["url"] not in last:
            s += 100
        elif last[p["url"]] < cutoff:
            s += 40
        if p.get("page_type") == "home":
            s += 50
        if p.get("in_sitemap"):
            s += 10
        if p.get("page_type") in ("model", "category"):
            s += 5
        return -s
    pages.sort(key=prio)
    chosen, types = [], set()
    for p in pages:                                   # one per type first (representative sample)
        if p.get("page_type") not in types and len(chosen) < limit:
            chosen.append(p); types.add(p.get("page_type"))
    for p in pages:
        if len(chosen) >= limit:
            break
        if p not in chosen:
            chosen.append(p)
    return chosen[:limit]


async def render_pages(urls: List[str]) -> Dict[str, dict]:
    """Controlled headless Chromium session: one browser, sequential pages, no cookies persisted, no writes."""
    out: Dict[str, dict] = {}
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        return {u: {"error": f"playwright non disponibile: {type(e).__name__}"} for u in urls}
    try:
        async with async_playwright() as pw:
            launch = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]}
            if CHROME and os.path.exists(CHROME):
                launch["executable_path"] = CHROME
            browser = await pw.chromium.launch(**launch)
            ctx = await browser.new_context(user_agent="Mozilla/5.0 (compatible; LatoSegreto-SEO-Autopilot/1.0; render-audit)", viewport={"width": 1280, "height": 900}, locale="it-IT")
            await ctx.route("**/api/analytics/**", lambda route: route.abort())      # never generate analytics events (read-only observer)
            await ctx.route("**/api/v1/tracking/**", lambda route: route.abort())
            await ctx.route("**/api/track**", lambda route: route.abort())
            for u in urls:
                page = await ctx.new_page()
                try:
                    resp = await page.goto(u, wait_until="networkidle", timeout=PAGE_TIMEOUT_MS)
                    await page.wait_for_timeout(800)
                    data = await page.evaluate(JS_EXTRACT)
                    data["status"] = resp.status if resp else None
                    out[u] = data
                except Exception as e:
                    out[u] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
                finally:
                    await page.close()
            await ctx.close()
            await browser.close()
    except Exception as e:
        for u in urls:
            out.setdefault(u, {"error": f"browser: {type(e).__name__}: {str(e)[:120]}"})
    return out


def compare(initial: dict, rendered: dict, google: Optional[dict]) -> List[dict]:
    issues = []
    if rendered.get("error"):
        return [{"code": "RENDER_FAILED", "severity": "MEDIUM", "detail": rendered["error"]}]
    if not rendered.get("title"):
        issues.append({"code": "TITLE_MISSING_RENDERED", "severity": "HIGH", "detail": "nessun title nel DOM renderizzato"})
    elif (initial.get("title") or "") != rendered["title"]:
        issues.append({"code": "TITLE_JS_ONLY", "severity": "INFO", "detail": f"title reale solo via JavaScript: '{rendered['title'][:70]}' (iniziale: '{(initial.get('title') or '')[:40]}')"})
    if not rendered.get("h1"):
        issues.append({"code": "H1_MISSING_RENDERED", "severity": "HIGH", "detail": "nessun H1 nemmeno dopo il rendering"})
    elif len(rendered["h1"]) > 1:
        issues.append({"code": "MULTIPLE_H1", "severity": "LOW", "detail": f"{len(rendered['h1'])} H1 nel DOM"})
    if not rendered.get("canonical"):
        issues.append({"code": "CANONICAL_MISSING_RENDERED", "severity": "HIGH", "detail": "nessun canonical nemmeno dopo il rendering"})
    elif not initial.get("canonical"):
        issues.append({"code": "CANONICAL_JS_ONLY", "severity": "MEDIUM", "detail": "canonical presente solo dopo JavaScript: Google lo vede solo dopo il rendering (fase 2 di indicizzazione)"})
    if not rendered.get("meta_description"):
        issues.append({"code": "DESCRIPTION_MISSING_RENDERED", "severity": "MEDIUM", "detail": "nessuna meta description nel DOM"})
    if not rendered.get("jsonld_types"):
        issues.append({"code": "STRUCTURED_DATA_MISSING_RENDERED", "severity": "LOW", "detail": "nessun JSON-LD nel DOM"})
    elif not initial.get("jsonld_types"):
        issues.append({"code": "STRUCTURED_DATA_JS_ONLY", "severity": "INFO", "detail": f"JSON-LD {rendered['jsonld_types']} solo via JavaScript"})
    if (rendered.get("text_len") or 0) < 300:
        issues.append({"code": "THIN_RENDERED_TEXT", "severity": "MEDIUM", "detail": f"solo {rendered.get('text_len')} caratteri di testo visibile dopo il rendering"})
    if (initial.get("text_len") or 0) < 200 and (rendered.get("text_len") or 0) >= 300:
        issues.append({"code": "CONTENT_JS_ONLY", "severity": "MEDIUM", "detail": "il testo SEO esiste solo dopo il rendering JavaScript (nessun SSR/prerender): Google deve renderizzare la pagina"})
    if not rendered.get("internal_links"):
        issues.append({"code": "NO_INTERNAL_LINKS_RENDERED", "severity": "MEDIUM", "detail": "nessun link interno nel DOM"})
    if "noindex" in (rendered.get("robots") or "").lower():
        issues.append({"code": "NOINDEX_RENDERED", "severity": "HIGH", "detail": f"robots={rendered['robots']} nel DOM renderizzato"})
    if rendered.get("images_without_alt"):
        issues.append({"code": "IMG_WITHOUT_ALT_RENDERED", "severity": "LOW", "detail": f"{rendered['images_without_alt']}/{rendered.get('images')} immagini senza alt nel DOM"})
    if google and google.get("state") not in (None, "NOT_INSPECTED", "NOT_CONFIGURED", "UNKNOWN"):
        gc = google.get("google_canonical")
        if gc and rendered.get("canonical") and gc.rstrip("/") != rendered["canonical"].rstrip("/"):
            issues.append({"code": "GOOGLE_CANONICAL_DIFFERS", "severity": "HIGH", "detail": f"Google ha scelto un canonical diverso: {gc}"})
        if google.get("state") == "NOT_INDEXED":
            issues.append({"code": "GOOGLE_NOT_INDEXED", "severity": "HIGH", "detail": f"Google: {google.get('coverage_state')}"})
        if google.get("page_fetch_state") and google["page_fetch_state"] != "SUCCESSFUL":
            issues.append({"code": "GOOGLE_FETCH_PROBLEM", "severity": "HIGH", "detail": f"pageFetchState={google['page_fetch_state']}"})
    return issues


async def run(run_id: Optional[str], limit: Optional[int] = None, inspect: bool = True) -> dict:
    base = crawl_base_url()
    used = await _rendered_today()
    budget_left = max(0, DAILY_BROWSER_BUDGET - used)
    n = min(limit or PER_RUN, budget_left)
    out = {"base": base, "budget": {"daily": DAILY_BROWSER_BUDGET, "used_today": used, "this_run": n}, "pages": [], "inspected": 0, "issues": 0}
    if n <= 0:
        await log_decision(run_id, "RENDER_AUDIT_SKIPPED", base, f"budget browser giornaliero esaurito ({used}/{DAILY_BROWSER_BUDGET})", result="SKIPPED", kind="render")
        return out
    picks = await pick_urls(n)
    if not picks:
        await log_decision(run_id, "RENDER_AUDIT_SKIPPED", base, "nessuna pagina 200 nel crawl tecnico", result="SKIPPED", kind="render")
        return out
    rendered = await render_pages([p["url"] for p in picks])
    await _count_render(len(picks))
    # selective Google inspection: only pages with render/tech problems or never inspected, up to INSPECT_PER_RUN
    from google_search import service as gs
    from google_search.config import cfg as gcfg
    from urllib.parse import urlsplit
    same_host = urlsplit(base).netloc.lower() == urlsplit(gcfg.property_url).netloc.lower()
    can_inspect = inspect and gs.configured() and gcfg.inspection_enabled and same_host
    out["google_inspection"] = "ENABLED" if can_inspect else ("NOT_APPLICABLE_HOST" if (inspect and gs.configured() and not same_host) else "NOT_AVAILABLE")
    if inspect and gs.configured() and not same_host:
        await log_decision(run_id, "URL_INSPECTION_SKIPPED", base, f"host di crawl ({urlsplit(base).netloc}) diverso dalla proprietà Search Console ({urlsplit(gcfg.property_url).netloc}): URL Inspection non applicabile (nessuna quota consumata)", result="SKIPPED", kind="render")
    inspected = 0
    docs = []
    for p in picks:
        tech = await tech_col.find_one({"url": p["url"]}, {"_id": 0, "initial_html": 1}) or {}
        initial = tech.get("initial_html") or {}
        r = rendered.get(p["url"]) or {"error": "non renderizzata"}
        issues = compare(initial, r, None)
        google = None
        if can_inspect and inspected < INSPECT_PER_RUN:
            prev = await render_col.find_one({"url": p["url"], "google.state": {"$exists": True}}, {"_id": 0, "google": 1}, sort=[("checked_at", -1)])
            worth = any(i["severity"] in ("HIGH", "MEDIUM") for i in issues) or not prev or p.get("page_type") == "home"
            if worth:
                try:
                    ins = await gs.inspect(p["url"])              # cached by the existing layer; budgeted; read-only
                    google = {"state": ins.get("state"), "source": ins.get("source"), **{k: (ins.get("google") or {}).get(k) for k in ("coverage_state", "indexing_state", "page_fetch_state", "google_canonical", "user_canonical", "last_crawl_time", "robots_txt_state")}}
                    if ins.get("source") == "google":
                        inspected += 1
                    issues = compare(initial, r, google)
                except Exception as e:
                    google = {"state": "UNKNOWN", "error": type(e).__name__}
        doc = {"url": p["url"], "page_type": p.get("page_type"), "checked_at": now_iso(), "run_id": run_id, "base": base,
               "initial": {k: initial.get(k) for k in ("title", "meta_description", "h1", "canonical", "robots", "jsonld_types", "text_len")}, "rendered": r, "google": google,
               "issues": issues, "verdict": "OK" if not any(i["severity"] in ("HIGH", "CRITICAL") for i in issues) else "PROBLEM"}
        await render_col.insert_one(dict(doc))
        doc.pop("_id", None)
        docs.append(doc)
        out["pages"].append({"url": p["url"], "verdict": doc["verdict"], "issues": [i["code"] for i in issues], "google": (google or {}).get("state")})
        out["issues"] += len(issues)
    out["inspected"] = inspected
    # keep history bounded: last 5 audits per URL
    for p in picks:
        old = [d["_id"] async for d in render_col.find({"url": p["url"]}, {"_id": 1}).sort("checked_at", -1).skip(5)]
        if old:
            await render_col.delete_many({"_id": {"$in": old}})
    problems = sum(1 for d in docs if d["verdict"] == "PROBLEM")
    # site-level findings from the whole rendered sample (duplicates, brand-only H1) -> backlog
    from .crawler import duplicates_in_rendered
    all_docs = await latest_docs(80)
    site_findings = _collapse(duplicates_in_rendered(all_docs), all_docs)
    for d in docs:
        for i in d["issues"]:
            if i["severity"] in ("HIGH", "CRITICAL"):
                site_findings.append({"code": i["code"], "severity": i["severity"], "detail": i["detail"], "url": d["url"]})
    await audits_col.update_one({"kind": "render", "run_id": run_id or "manual"}, {"$set": {"kind": "render", "run_id": run_id or "manual", "at": now_iso(), "summary": {**out["budget"], "pages": len(docs), "problems": problems, "inspected": inspected, "google_inspection": out["google_inspection"]}, "pages": out["pages"], "findings": site_findings[:200]}}, upsert=True)
    out["findings"] = site_findings
    await log_decision(run_id, "RENDER_AUDIT", base, f"{len(docs)} pagine renderizzate ({problems} con problemi), {inspected} ispezioni Google; budget {used + len(picks)}/{DAILY_BROWSER_BUDGET}", metrics={"pages": len(docs), "problems": problems, "inspected": inspected}, kind="render")
    return out


def _collapse(dups: List[dict], docs: List[dict]) -> List[dict]:
    """N² pair findings -> a few readable site-level findings (same H1 everywhere, duplicate titles/descriptions)."""
    out: List[dict] = []
    n = len(docs)
    h1s = [((d.get("rendered") or {}).get("h1") or [""])[0].strip().lower() for d in docs if (d.get("rendered") or {}).get("title")]
    if n >= 3 and h1s and len(set(h1s)) == 1 and h1s[0]:
        out.append({"code": "H1_BRAND_ONLY_SITEWIDE", "severity": "MEDIUM", "detail": f"il primo H1 è '{h1s[0][:40]}' su {len(h1s)}/{len(h1s)} pagine renderizzate: l'H1 non descrive la pagina (nome creator / categoria). Solo report.", "url": None})
        dups = [x for x in dups if x["code"] != "DUPLICATE_H1_RENDERED"]
    by_code: Dict[str, List[dict]] = {}
    for x in dups:
        by_code.setdefault(x["code"], []).append(x)
    for code, items in by_code.items():
        if len(items) > 3:
            out.append({"code": code + "_MULTI", "severity": items[0]["severity"], "detail": f"{len(items)} coppie di pagine: es. {items[0]['detail']}", "url": items[0]["url"]})
        else:
            out.extend(items)
    return out


async def latest_docs(limit: int = 60) -> List[dict]:
    """Most recent render audit per URL."""
    seen, out = set(), []
    async for d in render_col.find({}, {"_id": 0}).sort("checked_at", -1):
        if d["url"] in seen:
            continue
        seen.add(d["url"]); out.append(d)
        if len(out) >= limit:
            break
    return out


def initial_vs_rendered_table(docs: List[dict]) -> List[dict]:
    rows = []
    for d in docs:
        i, r, g = d.get("initial") or {}, d.get("rendered") or {}, d.get("google") or {}
        rows.append({"url": d["url"], "INITIAL_HTML": {"title": i.get("title"), "h1": (i.get("h1") or [None])[0], "canonical": i.get("canonical"), "jsonld": i.get("jsonld_types"), "text_len": i.get("text_len")},
                     "RENDERED_DOM": {"title": r.get("title"), "h1": (r.get("h1") or [None])[0], "canonical": r.get("canonical"), "jsonld": r.get("jsonld_types"), "text_len": r.get("text_len"), "links": len(r.get("internal_links") or [])},
                     "GOOGLE_INSPECTION": {"state": g.get("state") or "NOT_INSPECTED", "canonical": g.get("google_canonical"), "coverage": g.get("coverage_state")} if g else {"state": "NOT_INSPECTED"},
                     "verdict": d.get("verdict"), "issues": [x["code"] for x in d.get("issues") or []], "checked_at": d.get("checked_at")})
    return rows
