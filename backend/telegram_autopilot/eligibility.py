"""Eligible creators + their PUBLIC promotional media. Only real DB data; never `segreto` material."""
import os
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from database import models_col

PUBLIC_FIELDS = {"_id": 0, "id": 1, "slug": 1, "nome": 1, "nome_artistico": 1, "frase": 1, "bio": 1, "categorie": 1, "tag": 1, "tema": 1, "onlyfans_url": 1, "cta_testo": 1, "teaser_copy": 1,
                 "foto_card": 1, "foto_copertina": 1, "foto_card_teaser": 1, "galleria_pubblica": 1, "media_pairs": 1, "stato": 1, "is_deleted": 1, "ordine": 1, "created_at": 1, "data_pubblicazione": 1}


def valid_of_link(url: Optional[str]) -> Optional[str]:
    """Only a real onlyfans.com profile link counts. Never social fallbacks."""
    u = (url or "").strip()
    if not u:
        return None
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    host = urlsplit(u).netloc.lower().split(":")[0]
    if host in ("onlyfans.com", "www.onlyfans.com") and len(urlsplit(u).path.strip("/")) >= 1:
        return u
    return None


def media_base() -> str:
    return (os.environ.get("TELEGRAM_MEDIA_BASE_URL") or os.environ.get("SEO_CRAWL_BASE_URL") or "").rstrip("/")


def absolute(url: str) -> str:
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    return f"{media_base()}{url if url.startswith('/') else '/' + url}"


def public_media(m: dict) -> List[dict]:
    """Ordered list of PUBLIC media: [{id, type: photo|video, url, poster}] — deduplicated, photos and videos interleaved when both exist.
    Sources (public only): media_pairs[].pubblico, galleria_pubblica, foto_card, foto_copertina, foto_card_teaser. Never *segret*."""
    photos, videos, seen = [], [], set()

    def add(kind, url, mid, poster=""):
        url = (url or "").strip()
        if not url or url in seen:
            return
        seen.add(url)
        (videos if kind == "video" else photos).append({"id": mid, "type": kind, "url": absolute(url), "poster": absolute(poster) if poster else None})
    for i, p in enumerate(m.get("media_pairs") or []):
        pub = p.get("pubblico") or {}
        add("video" if (pub.get("tipo") or p.get("tipo")) == "video" else "photo", pub.get("url"), f"pair:{p.get('id') or i}", pub.get("poster"))
    for i, g in enumerate(m.get("galleria_pubblica") or []):
        add("video" if g.get("tipo") == "video" else "photo", g.get("url"), f"gal:{i}", g.get("poster"))
    for k in ("foto_card", "foto_copertina", "foto_card_teaser"):
        add("photo", m.get(k), f"field:{k}")
    out, pi, vi = [], 0, 0
    while pi < len(photos) or vi < len(videos):       # alternate PHOTO -> VIDEO -> PHOTO ...
        if pi < len(photos):
            out.append(photos[pi]); pi += 1
        if vi < len(videos):
            out.append(videos[vi]); vi += 1
    return out


def _order_key(m: dict):
    return (m.get("ordine") if isinstance(m.get("ordine"), (int, float)) else 10**6, m.get("data_pubblicazione") or m.get("created_at") or "", m.get("slug") or "")


async def published_models() -> List[dict]:
    items = [m async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, PUBLIC_FIELDS)]
    items.sort(key=_order_key)
    return items


def classify(m: dict, use_photo: bool = True, use_video: bool = True) -> Dict[str, object]:
    of = valid_of_link(m.get("onlyfans_url"))
    media = [x for x in public_media(m) if (x["type"] == "photo" and use_photo) or (x["type"] == "video" and use_video)]
    status = "ELIGIBLE" if of and media else ("SKIPPED_NO_OF_LINK" if not of else "SKIPPED_NO_MEDIA")
    return {"model_id": m.get("id"), "slug": m.get("slug"), "name": m.get("nome_artistico") or m.get("nome"), "of_link": of, "media": media, "n_photos": sum(1 for x in media if x["type"] == "photo"), "n_videos": sum(1 for x in media if x["type"] == "video"), "status": status}


async def roster(use_photo: bool = True, use_video: bool = True) -> Dict[str, object]:
    """All published models classified, in rotation order."""
    models = await published_models()
    rows = [classify(m, use_photo, use_video) for m in models]
    return {"models": models, "rows": rows, "eligible": [r for r in rows if r["status"] == "ELIGIBLE"], "no_of": [r["slug"] for r in rows if r["status"] == "SKIPPED_NO_OF_LINK"], "no_media": [r["slug"] for r in rows if r["status"] == "SKIPPED_NO_MEDIA"]}
