"""OF Autopilot media source = LATO SEGRETO database/storage. Both sides are read (the post shows PUBLIC -> SECRET of the SAME model).
Eligibility: PUBLISHED, active, not excluded (of_autopilot_excluded), >=1 PUBLIC media, >=1 SECRET media, valid onlyfans.com link of the model.
Real lightweight validation (HEAD, fallback GET Range 0-0) against OUR storage URLs only — never a provider write."""
import os
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from database import models_col

FIELDS = {"_id": 0, "id": 1, "slug": 1, "nome": 1, "nome_artistico": 1, "frase": 1, "bio": 1, "categorie": 1, "tag": 1, "tema": 1, "teaser_copy": 1, "onlyfans_url": 1,
          "foto_card": 1, "foto_copertina": 1, "foto_card_teaser": 1, "galleria_pubblica": 1, "galleria_segreta": 1, "foto_segreta_hero": 1, "media_pairs": 1,
          "stato": 1, "is_deleted": 1, "ordine": 1, "created_at": 1, "data_pubblicazione": 1, "of_autopilot_excluded": 1}
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")
VIDEO_EXT = (".mp4", ".mov", ".m4v")            # formats accepted by OnlyFans / provider upload
VALIDATION_TTL_S = 600
GLOBAL_OF_USERNAME = os.environ.get("OF_EXPECTED_USERNAME", "latosegreto").strip().lower()
VALIDATION_TIMEOUT_S = 20.0
_cache: Dict[str, Tuple[float, dict]] = {}


def media_base() -> str:
    return (os.environ.get("OF_MEDIA_BASE_URL") or os.environ.get("TELEGRAM_MEDIA_BASE_URL") or "").rstrip("/")


def absolute(url: str) -> str:
    if not url or url.startswith(("http://", "https://")):
        return url
    return f"{media_base()}{url if url.startswith('/') else '/' + url}"


def valid_of_link(url: Optional[str]) -> Optional[str]:
    """Only the model's real onlyfans.com profile link from the DB. Never site/social/global/generated links."""
    u = (url or "").strip()
    if not u:
        return None
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    try:
        sp = urlsplit(u)
    except Exception:
        return None
    if (sp.netloc or "").lower() in ("onlyfans.com", "www.onlyfans.com") and len(sp.path.strip("/")) >= 1:
        username = sp.path.strip("/").split("/")[0].lower()
        if username == GLOBAL_OF_USERNAME:
            return None                                 # global Lato Segreto account: never used as a model link
        return u
    return None


def _kind_from(url: str, tipo: Optional[str]) -> str:
    path = urlsplit(url or "").path.lower()
    if tipo == "video" or path.endswith(VIDEO_EXT):
        return "video"
    return "photo"


def _format_ok(url: str, kind: str) -> bool:
    path = urlsplit(url).path.lower()
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return True                                 # extension-less CDN URLs: decided by the real MIME check
    return path.endswith(VIDEO_EXT) if kind == "video" else path.endswith(PHOTO_EXT)


def get_of_media(m: dict) -> Dict[str, List[dict]]:
    """{"public": [...], "secret": [...], "rejected": [...]} — every item carries model_id (SAME_MODEL guard) and an absolute source_url."""
    out = {"PUBLIC": [], "SECRET": []}
    rejected, seen = [], set()
    mid_model = m.get("id")

    def add(side, url, mid, tipo=None, poster=""):
        url = (url or "").strip()
        if not url or (side, url) in seen:
            return
        seen.add((side, url))
        kind = _kind_from(url, tipo)
        if not _format_ok(url, kind):
            rejected.append({"id": mid, "side": side, "type": kind, "reason": "UNSUPPORTED_FORMAT"})
            return
        out[side].append({"id": mid, "type": kind, "url": absolute(url), "source_url": absolute(url), "poster": absolute(poster) if poster else None, "side": side, "model_id": mid_model})
    for i, p in enumerate(m.get("media_pairs") or []):
        pid = p.get("id") or i
        pub, sec = p.get("pubblico") or {}, p.get("segreto") or {}
        add("PUBLIC", pub.get("url"), f"pub:pair:{pid}", pub.get("tipo") or p.get("tipo"), pub.get("poster"))
        add("SECRET", sec.get("url"), f"sec:pair:{pid}", sec.get("tipo") or p.get("tipo"), sec.get("poster"))
    for i, g in enumerate(m.get("galleria_pubblica") or []):
        add("PUBLIC", g.get("url"), f"pub:gal:{i}", g.get("tipo"), g.get("poster"))
    for k in ("foto_card", "foto_copertina", "foto_card_teaser"):
        add("PUBLIC", m.get(k), f"pub:field:{k}", "image")
    for i, g in enumerate(m.get("galleria_segreta") or []):
        add("SECRET", g.get("url"), f"sec:gal:{i}", g.get("tipo"), g.get("poster"))
    add("SECRET", m.get("foto_segreta_hero"), "sec:field:foto_segreta_hero", "image")
    return {"public": out["PUBLIC"], "secret": out["SECRET"], "rejected": rejected}


def _order_key(m: dict):
    return (m.get("ordine") if isinstance(m.get("ordine"), (int, float)) else 10**6, m.get("data_pubblicazione") or m.get("created_at") or "", m.get("slug") or "")


async def published_models() -> List[dict]:
    items = [m async for m in models_col.find({"stato": "pubblicata", "is_deleted": {"$ne": True}}, FIELDS)]
    items.sort(key=_order_key)
    return items


def classify(m: dict) -> dict:
    xm = get_of_media(m)
    of = valid_of_link(m.get("onlyfans_url"))
    if m.get("of_autopilot_excluded") is True:
        status = "SKIPPED_EXCLUDED"
    elif not xm["public"]:
        status = "SKIPPED_NO_PUBLIC"
    elif not xm["secret"]:
        status = "SKIPPED_NO_SECRET"
    elif not of:
        status = "SKIPPED_NO_OF_LINK"
    else:
        status = "ELIGIBLE"
    return {"model_id": m.get("id"), "slug": m.get("slug"), "name": m.get("nome_artistico") or m.get("nome"), "public": xm["public"], "secret": xm["secret"], "rejected": xm["rejected"],
            "of_url": of, "n_public": len(xm["public"]), "n_secret": len(xm["secret"]), "status": status}


async def roster() -> dict:
    models = await published_models()
    rows = [classify(m) for m in models]
    return {"models": models, "rows": rows, "eligible": [r for r in rows if r["status"] == "ELIGIBLE"],
            "no_public": [r["slug"] for r in rows if r["status"] == "SKIPPED_NO_PUBLIC"], "no_secret": [r["slug"] for r in rows if r["status"] == "SKIPPED_NO_SECRET"],
            "no_of": [r["slug"] for r in rows if r["status"] == "SKIPPED_NO_OF_LINK"], "excluded": [r["slug"] for r in rows if r["status"] == "SKIPPED_EXCLUDED"],
            "rejected": {r["slug"]: r["rejected"] for r in rows if r["rejected"]}}


# ------------------------------------------------------------------------------------------------ real lightweight validation (our storage only)
def _mime_ok(ctype: str, kind: str, url: str) -> bool:
    ct = (ctype or "").split(";")[0].strip().lower()
    if kind == "video":
        return ct.startswith("video/") or (ct in ("application/octet-stream", "binary/octet-stream", "") and urlsplit(url).path.lower().endswith(VIDEO_EXT))
    return ct.startswith("image/") or (ct in ("application/octet-stream", "binary/octet-stream", "") and urlsplit(url).path.lower().endswith(PHOTO_EXT))


def _size_from(headers: httpx.Headers) -> Optional[int]:
    cr = headers.get("content-range")
    if cr and "/" in cr:
        try:
            return int(cr.split("/")[-1])
        except ValueError:
            pass
    cl = headers.get("content-length")
    try:
        return int(cl) if cl is not None else None
    except ValueError:
        return None


async def validate_media(item: dict, use_cache: bool = True) -> dict:
    """HEAD (follow redirects) -> fallback GET with Range bytes=0-0 (never downloads the file). Returns
    {ok, reason, status_code, mime, size, source_type, final_url}. Only OUR/DB URLs are touched."""
    url = item.get("source_url") or item.get("url") or ""
    kind = item.get("type", "photo")
    now = time.time()
    if use_cache and url in _cache and now - _cache[url][0] < VALIDATION_TTL_S:
        return _cache[url][1]
    res = {"ok": False, "reason": None, "status_code": None, "mime": None, "size": None, "source_type": None, "final_url": url}
    sp = urlsplit(url)
    if sp.scheme != "https" or not sp.netloc:
        res["reason"] = "NOT_HTTPS"
        return res
    try:
        async with httpx.AsyncClient(timeout=VALIDATION_TIMEOUT_S, follow_redirects=True) as c:
            r = await c.head(url)
            if r.status_code in (405, 501, 403, 400) or not r.headers.get("content-type"):
                async with c.stream("GET", url, headers={"Range": "bytes=0-0"}) as g:      # minimal GET, no body read
                    r = g
                    status, headers = g.status_code, g.headers
            else:
                status, headers = r.status_code, r.headers
    except httpx.HTTPError as e:
        res["reason"] = f"NETWORK_ERROR: {type(e).__name__}"
        return res
    res["status_code"], res["mime"], res["size"], res["final_url"] = status, (headers.get("content-type") or "").split(";")[0], _size_from(headers), str(r.url)
    if status not in (200, 206):
        res["reason"] = f"HTTP_{status}"
    elif not _mime_ok(res["mime"], kind, url):
        res["reason"] = "MIME_MISMATCH"
    elif res["size"] is not None and res["size"] <= 0:
        res["reason"] = "EMPTY_FILE"
    else:
        res["ok"] = True
        res["source_type"] = "source_url"            # https + reachable -> the provider can fetch it itself
    if use_cache:
        _cache[url] = (now, res)
    return res


async def fetch_bytes(url: str, max_bytes: int = 200 * 1024 * 1024) -> Tuple[bytes, str]:
    """FILE UPLOAD FALLBACK (server-side only): fetch the media from our storage when source_url cannot be used by the provider."""
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as c:
        async with c.stream("GET", url) as r:
            if r.status_code != 200:
                raise ValueError(f"HTTP_{r.status_code}")
            chunks, total = [], 0
            async for ch in r.aiter_bytes():
                total += len(ch)
                if total > max_bytes:
                    raise ValueError("FILE_TOO_LARGE")
                chunks.append(ch)
            data = b"".join(chunks)
            if not data:
                raise ValueError("EMPTY_FILE")
            return data, (r.headers.get("content-type") or "application/octet-stream").split(";")[0]
