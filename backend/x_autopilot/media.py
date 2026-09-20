"""Eligibility + media for X: BOTH sides are read on purpose (the post shows PUBLIC -> SECRET), plus the model's real OnlyFans link.
Eligible = PUBLISHED, active, >=1 X-safe PUBLIC media, >=1 X-safe SECRET media, valid onlyfans.com link.
X-safe (light): explicit flag/x_safe=false/disabled -> no; nsfw/explicit markers in metadata or file name -> no; unsupported format -> no."""
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from database import models_col

FIELDS = {"_id": 0, "id": 1, "slug": 1, "nome": 1, "nome_artistico": 1, "frase": 1, "bio": 1, "categorie": 1, "tag": 1, "tema": 1, "teaser_copy": 1, "onlyfans_url": 1,
          "foto_card": 1, "foto_copertina": 1, "foto_card_teaser": 1, "galleria_pubblica": 1, "galleria_segreta": 1, "foto_segreta_hero": 1, "media_pairs": 1,
          "stato": 1, "is_deleted": 1, "ordine": 1, "created_at": 1, "data_pubblicazione": 1}
EXPLICIT_MARKERS = re.compile(r"(nsfw|explicit|esplicit|xxx|porn|hardcore)", re.I)
EXPLICIT_TAGS = re.compile(r"\b(esplicit[oa]|explicit|hardcore|nud[aoie]|nude|xxx|porn|18\+only)\b", re.I)
ALLOWED_PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp")
ALLOWED_VIDEO_EXT = (".mp4", ".mov")


def media_base() -> str:
    return (os.environ.get("X_MEDIA_BASE_URL") or os.environ.get("TELEGRAM_MEDIA_BASE_URL") or "").rstrip("/")


def absolute(url: str) -> str:
    if not url or url.startswith(("http://", "https://")):
        return url
    return f"{media_base()}{url if url.startswith('/') else '/' + url}"


def valid_of_link(url: Optional[str]) -> Optional[str]:
    """Only a real onlyfans.com profile link of THIS model counts. Never social/site/global fallbacks."""
    u = (url or "").strip()
    if not u:
        return None
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    try:
        sp = urlsplit(u)
    except Exception:
        return None
    host = (sp.netloc or "").lower()
    if host in ("onlyfans.com", "www.onlyfans.com") and len(sp.path.strip("/")) >= 1:
        return u
    return None


def x_safe(url: str, kind: str, meta: dict) -> Tuple[bool, str]:
    if not url:
        return False, "EMPTY_URL"
    if meta.get("x_safe") is False or meta.get("esplicito") is True or meta.get("explicit") is True:
        return False, "EXPLICIT_FLAG"
    if meta.get("disabled") is True or meta.get("pubblicabile") is False or meta.get("attivo") is False:
        return False, "MEDIA_DISABLED"
    sp = urlsplit(url)
    path = f"{sp.path}?{sp.query}".lower() if sp.query else sp.path.lower()
    if EXPLICIT_MARKERS.search(path):
        return False, "EXPLICIT_MARKER"
    ext_ok = sp.path.lower().endswith(ALLOWED_VIDEO_EXT) if kind == "video" else sp.path.lower().endswith(ALLOWED_PHOTO_EXT)
    if "." in sp.path.rsplit("/", 1)[-1] and not ext_ok:
        return False, "UNSUPPORTED_FORMAT"
    flags = " ".join(str(meta.get(k) or "") for k in ("tag", "tags", "label", "rating", "alt", "nome", "name"))
    if EXPLICIT_TAGS.search(flags):
        return False, "EXPLICIT_FLAG"
    return True, ""


def get_x_media(m: dict) -> Dict[str, List[dict]]:
    """{"public": [...], "secret": [...], "rejected": [...]} — each side ordered PHOTOS FIRST, then videos (photo+photo pairs are preferred)."""
    sides = {"PUBLIC": {"photo": [], "video": []}, "SECRET": {"photo": [], "video": []}}
    rejected, seen = [], set()

    def add(side, kind, url, mid, meta, poster=""):
        url = (url or "").strip()
        if not url or (side, url) in seen:
            return
        seen.add((side, url))
        ok, why = x_safe(url, kind, meta or {})
        if not ok:
            rejected.append({"id": mid, "side": side, "type": kind, "reason": why})
            return
        sides[side][kind].append({"id": mid, "type": kind, "url": absolute(url), "poster": absolute(poster) if poster else None, "side": side})
    for i, p in enumerate(m.get("media_pairs") or []):
        pid = p.get("id") or i
        pub, sec = p.get("pubblico") or {}, p.get("segreto") or {}
        add("PUBLIC", "video" if (pub.get("tipo") or p.get("tipo")) == "video" else "photo", pub.get("url"), f"pub:pair:{pid}", pub, pub.get("poster"))
        add("SECRET", "video" if (sec.get("tipo") or p.get("tipo")) == "video" else "photo", sec.get("url"), f"sec:pair:{pid}", sec, sec.get("poster"))
    for i, g in enumerate(m.get("galleria_pubblica") or []):
        add("PUBLIC", "video" if g.get("tipo") == "video" else "photo", g.get("url"), f"pub:gal:{i}", g, g.get("poster"))
    for k in ("foto_card", "foto_copertina", "foto_card_teaser"):
        add("PUBLIC", "photo", m.get(k), f"pub:field:{k}", {})
    for i, g in enumerate(m.get("galleria_segreta") or []):
        add("SECRET", "video" if g.get("tipo") == "video" else "photo", g.get("url"), f"sec:gal:{i}", g, g.get("poster"))
    add("SECRET", "photo", m.get("foto_segreta_hero"), "sec:field:foto_segreta_hero", {})
    out = {side: sides[side]["photo"] + sides[side]["video"] for side in sides}
    assert all(x["side"] == "PUBLIC" for x in out["PUBLIC"]) and all(x["side"] == "SECRET" for x in out["SECRET"])
    return {"public": out["PUBLIC"], "secret": out["SECRET"], "rejected": rejected}


def _order_key(m: dict):
    return (m.get("ordine") if isinstance(m.get("ordine"), (int, float)) else 10**6, m.get("data_pubblicazione") or m.get("created_at") or "", m.get("slug") or "")


async def published_models() -> List[dict]:
    items = [m async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, FIELDS)]
    items.sort(key=_order_key)
    return items


def classify(m: dict) -> dict:
    xm = get_x_media(m)
    of = valid_of_link(m.get("onlyfans_url"))
    status = "ELIGIBLE"
    if not xm["public"]:
        status = "SKIPPED_NO_PUBLIC_MEDIA"
    elif not xm["secret"]:
        status = "SKIPPED_NO_SECRET_MEDIA"
    elif not of:
        status = "SKIPPED_NO_OF_LINK"
    return {"model_id": m.get("id"), "slug": m.get("slug"), "name": m.get("nome_artistico") or m.get("nome"), "public": xm["public"], "secret": xm["secret"], "rejected": xm["rejected"], "of_url": of,
            "n_public": len(xm["public"]), "n_secret": len(xm["secret"]), "status": status}


async def roster() -> dict:
    models = await published_models()
    rows = [classify(m) for m in models]
    return {"models": models, "rows": rows, "eligible": [r for r in rows if r["status"] == "ELIGIBLE"],
            "no_public": [r["slug"] for r in rows if r["status"] == "SKIPPED_NO_PUBLIC_MEDIA"], "no_secret": [r["slug"] for r in rows if r["status"] == "SKIPPED_NO_SECRET_MEDIA"],
            "no_of": [r["slug"] for r in rows if r["status"] == "SKIPPED_NO_OF_LINK"], "not_safe": {r["slug"]: r["rejected"] for r in rows if r["rejected"]}}
