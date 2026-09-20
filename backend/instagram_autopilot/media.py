"""Eligibility + PUBLIC-ONLY media for Instagram. `get_instagram_public_media()` is the single gate: it reads exclusively
public fields and refuses any URL/field that smells 'segreto/secret/private'. Instagram-safe filter on top."""
import os
import re
from typing import Dict, List, Tuple
from urllib.parse import urlsplit

from database import models_col

PUBLIC_FIELDS = {"_id": 0, "id": 1, "slug": 1, "nome": 1, "nome_artistico": 1, "frase": 1, "bio": 1, "categorie": 1, "tag": 1, "tema": 1, "teaser_copy": 1,
                 "foto_card": 1, "foto_copertina": 1, "foto_card_teaser": 1, "galleria_pubblica": 1, "media_pairs": 1, "stato": 1, "is_deleted": 1, "ordine": 1, "created_at": 1, "data_pubblicazione": 1}
# never read: bio_segreta, foto_segreta_hero, galleria_segreta, media_pairs[].segreto, cta_segreto ...
FORBIDDEN_MARKERS = re.compile(r"(segret|secret|privat|nsfw|explicit|esplicit|hidden)", re.I)
ALLOWED_PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic")
ALLOWED_VIDEO_EXT = (".mp4", ".mov", ".m4v")
EXPLICIT_TAGS = re.compile(r"\b(esplicit[oa]|explicit|hardcore|nud[aoie]|nude|xxx|porn|topless|18\+only)\b", re.I)


def media_base() -> str:
    return (os.environ.get("INSTAGRAM_MEDIA_BASE_URL") or os.environ.get("TELEGRAM_MEDIA_BASE_URL") or "").rstrip("/")


def absolute(url: str) -> str:
    if not url or url.startswith(("http://", "https://")):
        return url
    return f"{media_base()}{url if url.startswith('/') else '/' + url}"


def _media_path(url: str) -> str:
    """Path+query of the media (the host is NOT inspected: the site domain itself may contain 'secret')."""
    sp = urlsplit(url or "")
    return f"{sp.path}?{sp.query}" if sp.query else sp.path


def _safe(url: str, kind: str, meta: dict) -> Tuple[bool, str]:
    """Instagram-safe check: public, technically valid, not flagged explicit."""
    if not url:
        return False, "EMPTY_URL"
    if FORBIDDEN_MARKERS.search(_media_path(url)):
        return False, "SECRET_MARKER_IN_URL"
    path = urlsplit(url).path.lower()
    ext_ok = path.endswith(ALLOWED_VIDEO_EXT) if kind == "video" else path.endswith(ALLOWED_PHOTO_EXT)
    if "." in path.rsplit("/", 1)[-1] and not ext_ok:
        return False, "UNSUPPORTED_FORMAT"
    flags = " ".join(str(meta.get(k) or "") for k in ("tag", "tags", "label", "rating", "visibilita", "visibility", "alt"))
    if EXPLICIT_TAGS.search(flags) or meta.get("esplicito") is True or meta.get("explicit") is True:
        return False, "EXPLICIT_FLAG"
    return True, ""


def get_instagram_public_media(m: dict) -> Dict[str, List[dict]]:
    """Returns {"media": [...PUBLIC + safe, photo/video interleaved...], "rejected": [...]}.
    Sources (public side only): media_pairs[].pubblico, galleria_pubblica, foto_card, foto_copertina, foto_card_teaser.
    Structural guarantee: the 'segreto' branch of media_pairs, galleria_segreta and foto_segreta_hero are never read."""
    photos, videos, rejected, seen = [], [], [], set()

    def add(kind, url, mid, meta, poster=""):
        url = (url or "").strip()
        if not url or url in seen:
            return
        seen.add(url)
        ok, why = _safe(url, kind, meta or {})
        if not ok:
            rejected.append({"id": mid, "type": kind, "reason": why})
            return
        (videos if kind == "video" else photos).append({"id": mid, "type": kind, "url": absolute(url), "poster": absolute(poster) if poster else None, "side": "PUBLIC"})
    for i, p in enumerate(m.get("media_pairs") or []):
        pub = p.get("pubblico") or {}                     # the ONLY branch read
        add("video" if (pub.get("tipo") or p.get("tipo")) == "video" else "photo", pub.get("url"), f"pair:{p.get('id') or i}", pub, pub.get("poster"))
    for i, g in enumerate(m.get("galleria_pubblica") or []):
        add("video" if g.get("tipo") == "video" else "photo", g.get("url"), f"gal:{i}", g, g.get("poster"))
    for k in ("foto_card", "foto_copertina", "foto_card_teaser"):
        add("photo", m.get(k), f"field:{k}", {})
    out, pi, vi = [], 0, 0
    while pi < len(photos) or vi < len(videos):       # FOTO -> VIDEO -> FOTO ...
        if pi < len(photos):
            out.append(photos[pi]); pi += 1
        if vi < len(videos):
            out.append(videos[vi]); vi += 1
    assert all(x["side"] == "PUBLIC" and not FORBIDDEN_MARKERS.search(_media_path(x["url"])) for x in out)
    return {"media": out, "rejected": rejected}


def _order_key(m: dict):
    return (m.get("ordine") if isinstance(m.get("ordine"), (int, float)) else 10**6, m.get("data_pubblicazione") or m.get("created_at") or "", m.get("slug") or "")


async def published_models() -> List[dict]:
    items = [m async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, PUBLIC_FIELDS)]
    items.sort(key=_order_key)
    return items


def classify(m: dict, use_photo: bool = True, use_video: bool = True) -> dict:
    pm = get_instagram_public_media(m)
    media = [x for x in pm["media"] if (x["type"] == "photo" and use_photo) or (x["type"] == "video" and use_video)]
    return {"model_id": m.get("id"), "slug": m.get("slug"), "name": m.get("nome_artistico") or m.get("nome"), "media": media, "rejected": pm["rejected"],
            "n_photos": sum(1 for x in media if x["type"] == "photo"), "n_videos": sum(1 for x in media if x["type"] == "video"), "status": "ELIGIBLE" if media else "SKIPPED_NO_PUBLIC_MEDIA"}


async def roster(use_photo: bool = True, use_video: bool = True) -> dict:
    models = await published_models()
    rows = [classify(m, use_photo, use_video) for m in models]
    return {"models": models, "rows": rows, "eligible": [r for r in rows if r["status"] == "ELIGIBLE"], "no_media": [r["slug"] for r in rows if r["status"] == "SKIPPED_NO_PUBLIC_MEDIA"],
            "not_safe": {r["slug"]: r["rejected"] for r in rows if r["rejected"]}}
