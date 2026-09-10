from fastapi import APIRouter, Request, Response
from xml.sax.saxutils import escape

from database import models_col, categories_col, articles_col

seo_router = APIRouter(prefix="/api")


def base_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    proto = request.headers.get("x-forwarded-proto", "https")
    return f"{proto}://{host}"


@seo_router.get("/sitemap.xml")
async def sitemap(request: Request):
    base = base_url(request)
    urls = [(f"{base}/", "1.0", "daily")]
    async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, {"_id": 0, "slug": 1, "updated_at": 1, "seo": 1}):
        seo = m.get("seo") or {}
        if seo.get("indexable", True) is False or "noindex" in (seo.get("robots") or "").lower():
            continue
        urls.append((f"{base}/modelle/{m['slug']}", "0.9", "weekly"))
    async for c in categories_col.find({"stato": "pubblicata", "indicizzabile": True}, {"_id": 0, "slug": 1}):
        urls.append((f"{base}/categorie/{c['slug']}", "0.7", "weekly"))
    async for a in articles_col.find({"stato": "pubblicato", "indicizzabile": True}, {"_id": 0, "slug": 1}):
        urls.append((f"{base}/articoli/{a['slug']}", "0.6", "monthly"))

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, prio, freq in urls:
        parts.append(f"<url><loc>{escape(loc)}</loc><changefreq>{freq}</changefreq><priority>{prio}</priority></url>")
    parts.append("</urlset>")
    return Response(content="\n".join(parts), media_type="application/xml")


@seo_router.get("/rss.xml")
async def rss(request: Request):
    base = base_url(request)
    items = []
    articles = await articles_col.find({"stato": "pubblicato", "indicizzabile": True}, {"_id": 0}).sort("data_pubblicazione", -1).to_list(50)
    for a in articles:
        link = f"{base}/articoli/{a['slug']}"
        items.append(
            f"<item><title>{escape(a.get('titolo',''))}</title>"
            f"<link>{escape(link)}</link>"
            f"<description>{escape(a.get('estratto',''))}</description>"
            f"<pubDate>{escape(a.get('data_pubblicazione') or '')}</pubDate></item>"
        )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<rss version="2.0"><channel>'
           '<title>LATO SEGRETO - Articoli</title>'
           f'<link>{base}/articoli</link>'
           '<description>Contenuti editoriali di LATO SEGRETO</description>'
           + "".join(items) + '</channel></rss>')
    return Response(content=xml, media_type="application/xml")


@seo_router.get("/robots.txt")
async def robots(request: Request):
    base = base_url(request)
    txt = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /api/admin\n"
        f"Sitemap: {base}/api/sitemap.xml\n"
    )
    return Response(content=txt, media_type="text/plain")
