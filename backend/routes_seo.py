from fastapi import APIRouter, Request, Response
from xml.sax.saxutils import escape

from database import articles_col

seo_router = APIRouter(prefix="/api")


def base_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    proto = request.headers.get("x-forwarded-proto", "https")
    return f"{proto}://{host}"


@seo_router.get("/sitemap.xml")
async def sitemap(request: Request):
    """Public sitemap: single source of truth = v1_seo.sitemap_entries (lastmod, landings behind flag, no draft/noindex).
    Base = request host (works for preview and production); production also matches the Search Console property."""
    from v1_seo import sitemap_entries, sitemap_xml
    entries = await sitemap_entries(base_url(request))
    return Response(content=sitemap_xml(entries), media_type="application/xml", headers={"Cache-Control": "public, max-age=300"})


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
