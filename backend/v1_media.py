"""SUPER API v1 - MEDIA MANAGEMENT.

Upload (multipart / from URL / base64), validation by magic bytes, variants
(web/mobile/thumb WebP via Pillow, poster/mobile via ffmpeg for video), metadata,
ALT text, SEO filename, association to model slots, replace, optimize, soft delete.
Storage: Emergent Object Storage (durable) -> served by /api/uploads/{path}.
"""
import io
import os
import re
import uuid
import base64
import hashlib
import asyncio
import ipaddress
import subprocess
import tempfile
import socket
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File, Form
from pydantic import BaseModel, ConfigDict
import requests as _requests

from database import files_col, models_col, now_iso, serialize_doc
from storage import put_object, APP_NAME
from sanitize import slugify
from v1_security import require, actor_of, request_id_of
from v1_versioning import record_version, audit_log

media_router = APIRouter(prefix="/api/v1/media", tags=["Media"])

ALLOWED_IMG = {"image/jpeg", "image/png", "image/webp", "image/avif", "image/gif"}
ALLOWED_VID = {"video/mp4", "video/webm", "video/quicktime"}
MAX_IMG_BYTES = 25 * 1024 * 1024
MAX_VID_BYTES = 200 * 1024 * 1024
EXT_MAP = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/avif": "avif", "image/gif": "gif",
           "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}
SLOTS = {"foto_card", "foto_copertina", "foto_card_teaser", "foto_segreta_hero", "og_image",
         "pair", "pellicola", "messaggio_foto", "messaggio_video", "galleria_pubblica", "galleria_segreta"}


# ---------------- validation ----------------
def sniff_mime(data: bytes) -> Optional[str]:
    h = data[:16]
    if h.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "image/webp"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if h[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"qt  ",):
            return "video/quicktime"
        return "video/mp4"
    if h[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    return None


def validate_bytes(data: bytes, declared: str) -> str:
    real = sniff_mime(data)
    if not real:
        raise HTTPException(status_code=400, detail="Contenuto non riconosciuto come immagine/video valido")
    if declared and declared != real and not (declared == "video/quicktime" and real == "video/mp4"):
        # trust bytes, not headers
        pass
    if real in ALLOWED_IMG and len(data) > MAX_IMG_BYTES:
        raise HTTPException(status_code=400, detail="Immagine troppo grande (max 25MB)")
    if real in ALLOWED_VID and len(data) > MAX_VID_BYTES:
        raise HTTPException(status_code=400, detail="Video troppo grande (max 200MB)")
    if real not in ALLOWED_IMG and real not in ALLOWED_VID:
        raise HTTPException(status_code=400, detail=f"Tipo non consentito: {real}")
    return real


def seo_filename(base: str, ext: str, suffix: str = "") -> str:
    s = slugify(base)[:80] or "media"
    return f"{s}{('-' + suffix) if suffix else ''}.{ext}"


# ---------------- processing ----------------
def _process_image(data: bytes, mime: str) -> Dict[str, Any]:
    from PIL import Image, ImageOps
    out: Dict[str, Any] = {"variants": {}}
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise HTTPException(status_code=400, detail="Immagine corrotta o non leggibile")
    im = ImageOps.exif_transpose(im)  # fix rotation, drop EXIF orientation
    out["width"], out["height"] = im.size
    animated = getattr(im, "is_animated", False)
    if animated:  # keep GIFs as-is
        return out
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    for name, max_w, q in (("web", 1600, 82), ("mobile", 900, 78), ("thumb", 400, 72)):
        v = im.copy()
        if v.size[0] > max_w:
            ratio = max_w / v.size[0]
            v = v.resize((max_w, max(1, int(v.size[1] * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        v.save(buf, format="WEBP", quality=q, method=4)
        out["variants"][name] = {"bytes": buf.getvalue(), "width": v.size[0], "height": v.size[1], "content_type": "image/webp"}
    return out


def _ffprobe(path: str) -> Dict[str, Any]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,duration:format=duration", "-of", "json", path],
                           capture_output=True, text=True, timeout=30)
        import json
        j = json.loads(r.stdout or "{}")
        st = (j.get("streams") or [{}])[0]
        dur = st.get("duration") or (j.get("format") or {}).get("duration")
        return {"width": st.get("width"), "height": st.get("height"), "duration": round(float(dur), 2) if dur else None}
    except Exception:
        return {}


def _process_video(data: bytes, mime: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"variants": {}}
    ext = EXT_MAP.get(mime, "mp4")
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, f"in.{ext}")
        with open(src, "wb") as f:
            f.write(data)
        meta = _ffprobe(src)
        out.update({k: v for k, v in meta.items() if v is not None})
        # poster at 1s (or 0s for very short clips)
        poster = os.path.join(td, "poster.jpg")
        ts = "1" if (meta.get("duration") or 0) > 1.5 else "0"
        try:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", ts, "-i", src, "-frames:v", "1", "-q:v", "3", poster],
                           capture_output=True, timeout=60)
            if os.path.exists(poster):
                with open(poster, "rb") as f:
                    out["variants"]["poster"] = {"bytes": f.read(), "content_type": "image/jpeg"}
        except Exception:
            pass
        # mobile version (<=720p, faststart) only for reasonably sized inputs (sync, bounded)
        if len(data) <= 60 * 1024 * 1024 and (meta.get("height") or 0) > 720:
            mob = os.path.join(td, "mobile.mp4")
            try:
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", "scale=-2:720", "-c:v", "libx264",
                                "-preset", "veryfast", "-crf", "26", "-movflags", "+faststart", "-an", mob],
                               capture_output=True, timeout=110)
                if os.path.exists(mob):
                    with open(mob, "rb") as f:
                        out["variants"]["mobile"] = {"bytes": f.read(), "content_type": "video/mp4"}
            except Exception:
                pass
    return out


async def store_media(data: bytes, mime: str, *, original_filename: str = "", alt: str = "", seo_name: str = "",
                      model_id: Optional[str] = None, slot: Optional[str] = None, actor: str = "system",
                      request_id: Optional[str] = None, file_id: Optional[str] = None) -> dict:
    """Validate, process variants, upload everything to object storage, persist record."""
    mime = validate_bytes(data, mime)
    tipo = "video" if mime in ALLOWED_VID else "image"
    ext = EXT_MAP[mime]
    sha = hashlib.sha256(data).hexdigest()
    base_name = seo_name or os.path.splitext(original_filename or "")[0] or f"{tipo}-{sha[:8]}"
    fid = file_id or str(uuid.uuid4())
    folder = f"{APP_NAME}/uploads/{fid[:8]}"
    fname = seo_filename(base_name, ext)

    loop = asyncio.get_event_loop()
    processed = await loop.run_in_executor(None, _process_image if tipo == "image" else _process_video, data, mime)

    try:
        res = await loop.run_in_executor(None, put_object, f"{folder}/{fname}", data, mime)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Errore di archiviazione: {e}")
    original_path = res.get("path", f"{folder}/{fname}")
    variants: Dict[str, Any] = {"original": {"url": f"/api/uploads/{original_path}", "path": original_path, "size": len(data),
                                             "width": processed.get("width"), "height": processed.get("height"), "content_type": mime}}
    for vname, v in (processed.get("variants") or {}).items():
        vext = "webp" if v["content_type"] == "image/webp" else ("jpg" if v["content_type"] == "image/jpeg" else "mp4")
        vpath = f"{folder}/{seo_filename(base_name, vext, vname)}"
        try:
            vres = await loop.run_in_executor(None, put_object, vpath, v["bytes"], v["content_type"])
            variants[vname] = {"url": f"/api/uploads/{vres.get('path', vpath)}", "path": vres.get("path", vpath), "size": len(v["bytes"]),
                               "width": v.get("width"), "height": v.get("height"), "content_type": v["content_type"]}
        except Exception:
            continue

    record = {
        "id": fid, "storage_path": original_path, "original_filename": original_filename, "seo_filename": fname,
        "content_type": mime, "size": len(data), "tipo": tipo, "sha256": sha,
        "width": processed.get("width"), "height": processed.get("height"), "duration": processed.get("duration"),
        "alt": alt or "", "variants": variants, "model_id": model_id, "slot": slot,
        "is_deleted": False, "created_by": actor, "created_at": now_iso(), "updated_at": now_iso(),
        "metadata": {"has_web": "web" in variants, "has_mobile": "mobile" in variants, "has_poster": "poster" in variants},
    }
    # register every variant path so /api/uploads serves them
    for vname, v in variants.items():
        if vname == "original":
            continue
        await files_col.insert_one({"id": f"{fid}:{vname}", "parent_id": fid, "variant": vname, "storage_path": v["path"],
                                    "content_type": v["content_type"], "size": v["size"], "tipo": tipo, "is_deleted": False, "created_at": now_iso()})
    await files_col.replace_one({"id": fid}, record, upsert=True)
    await record_version("file", fid, None, record, actor, source="api", reason="Upload media", request_id=request_id)
    return public_file(record)


def public_file(rec: dict) -> dict:
    r = serialize_doc(rec)
    r["url"] = (r.get("variants") or {}).get("original", {}).get("url") or f"/api/uploads/{r.get('storage_path')}"
    r["web_url"] = (r.get("variants") or {}).get("web", {}).get("url") or r["url"]
    r["mobile_url"] = (r.get("variants") or {}).get("mobile", {}).get("url") or r["web_url"]
    r["thumb_url"] = (r.get("variants") or {}).get("thumb", {}).get("url") or r["web_url"]
    r["poster_url"] = (r.get("variants") or {}).get("poster", {}).get("url") or ""
    return r


# ---------------- SSRF-safe URL fetch ----------------
def _is_private_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def fetch_url_bytes(url: str) -> (bytes, str):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(status_code=400, detail="URL non valido (solo http/https)")
    if _is_private_host(p.hostname):
        raise HTTPException(status_code=400, detail="Host non consentito")
    try:
        r = _requests.get(url, timeout=60, stream=True, headers={"User-Agent": "LatoSegreto-MediaIngest/1.0"})
        r.raise_for_status()
        buf = io.BytesIO()
        for chunk in r.iter_content(1024 * 256):
            buf.write(chunk)
            if buf.tell() > MAX_VID_BYTES:
                raise HTTPException(status_code=400, detail="File remoto troppo grande")
        return buf.getvalue(), (r.headers.get("Content-Type") or "").split(";")[0].strip()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Impossibile scaricare il file: {e}")


# ---------------- association ----------------
async def attach_to_model(doc: dict, *, url: str, slot: str, side: str = "pubblico", tipo: str = "image",
                          alt: str = "", poster: str = "", pair_index: Optional[int] = None, pair_id: Optional[str] = None,
                          principal: dict, request: Optional[Request], reason: str = "") -> dict:
    """Place a media URL in a model slot. Returns patched model (enriched)."""
    from v1_models import patch_model
    if slot not in SLOTS:
        raise HTTPException(status_code=400, detail={"message": "Slot non valido", "slots": sorted(SLOTS)})
    if side not in ("pubblico", "segreto"):
        raise HTTPException(status_code=400, detail="side deve essere 'pubblico' o 'segreto'")
    changes: Dict[str, Any] = {}
    if slot in ("foto_card", "foto_copertina", "foto_card_teaser", "foto_segreta_hero"):
        changes[slot] = url
    elif slot == "og_image":
        changes["seo"] = {**(doc.get("seo") or {}), "og_image": url}
    elif slot == "pellicola":
        ph = dict(doc.get("pellicola_home") or {})
        s = dict(ph.get(side) or {})
        if tipo == "video":
            s["video_url"] = url
            if poster:
                s["poster_url"] = poster
        else:
            s["poster_url"] = url
        ph[side] = s
        changes["pellicola_home"] = ph
    elif slot in ("messaggio_foto", "messaggio_video"):
        msg = dict(doc.get("messaggio_35s") or {})
        msg["foto" if slot == "messaggio_foto" else "video"] = url
        changes["messaggio_35s"] = msg
    elif slot in ("galleria_pubblica", "galleria_segreta"):
        gal = list(doc.get(slot) or [])
        gal.append({"tipo": "image", "url": url, "poster": "", "alt": alt})
        changes[slot] = gal
    elif slot == "pair":
        pairs = [dict(p) for p in (doc.get("media_pairs") or [])]
        idx = None
        if pair_id:
            idx = next((i for i, p in enumerate(pairs) if p.get("id") == pair_id), None)
            if idx is None:
                raise HTTPException(status_code=404, detail="Coppia media non trovata")
        elif pair_index is not None and 0 <= pair_index < len(pairs):
            idx = pair_index
        if idx is None:
            # first pair of the right type with an empty side, else append (max 3 images + 3 videos in the 2x3 grid)
            for i, p in enumerate(pairs):
                if p.get("tipo") == tipo and not ((p.get(side) or {}).get("url")):
                    idx = i
                    break
        if idx is None:
            pairs.append({"id": str(uuid.uuid4()), "tipo": tipo, "pubblico": {"tipo": tipo, "url": "", "poster": "", "alt": ""},
                          "segreto": {"tipo": tipo, "url": "", "poster": "", "alt": ""}})
            idx = len(pairs) - 1
        item = dict(pairs[idx].get(side) or {})
        item.update({"tipo": tipo, "url": url, "alt": alt or item.get("alt", "")})
        if poster:
            item["poster"] = poster
        pairs[idx][side] = item
        pairs[idx]["tipo"] = tipo
        changes["media_pairs"] = pairs
    return await patch_model(doc, changes, principal, request, reason or f"Media assegnato allo slot {slot} ({side})")


# ---------------- bodies ----------------
class FromUrlBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    url: Optional[str] = None
    base64_data: Optional[str] = None       # data URI or raw base64
    content_type: Optional[str] = None
    filename: Optional[str] = ""
    alt: Optional[str] = ""
    seo_name: Optional[str] = ""
    model_id: Optional[str] = None
    slot: Optional[str] = None
    side: Optional[str] = "pubblico"
    pair_index: Optional[int] = None
    pair_id: Optional[str] = None
    poster_url: Optional[str] = None


class MediaPatch(BaseModel):
    model_config = ConfigDict(extra='ignore')
    alt: Optional[str] = None
    seo_name: Optional[str] = None
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    model_id: Optional[str] = None
    slot: Optional[str] = None


class AttachBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    file_id: Optional[str] = None
    url: Optional[str] = None
    slot: str
    side: str = "pubblico"
    tipo: Optional[str] = None
    alt: Optional[str] = ""
    poster: Optional[str] = ""
    pair_index: Optional[int] = None
    pair_id: Optional[str] = None
    prefer: str = "web"   # original | web | mobile
    reason: Optional[str] = ""


async def _maybe_attach(rec: dict, body_model_id, slot, side, tipo, alt, poster, pair_index, pair_id, principal, request, prefer="web"):
    if not body_model_id or not slot:
        return None
    from v1_models import resolve_model
    doc = await resolve_model(body_model_id)
    url = rec.get(f"{prefer}_url") or rec["url"]
    if tipo == "video":
        url = rec["url"]
        poster = poster or rec.get("poster_url", "")
    out = await attach_to_model(doc, url=url, slot=slot, side=side or "pubblico", tipo=tipo, alt=alt or rec.get("alt", ""),
                                poster=poster or "", pair_index=pair_index, pair_id=pair_id, principal=principal, request=request)
    await files_col.update_one({"id": rec["id"]}, {"$set": {"model_id": doc["id"], "slot": slot, "side": side}})
    return out


# ---------------- ROUTES ----------------
@media_router.get("")
async def list_media(model_id: Optional[str] = None, tipo: Optional[str] = None, limit: int = 100, skip: int = 0,
                     include_deleted: bool = False, principal=Depends(require("media:read"))):
    q: Dict[str, Any] = {"parent_id": {"$exists": False}}
    if not include_deleted:
        q["is_deleted"] = {"$ne": True}
    if model_id:
        q["model_id"] = model_id
    if tipo:
        q["tipo"] = tipo
    docs = await files_col.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await files_col.count_documents(q)
    return {"items": [public_file(d) for d in docs], "total": total}


@media_router.post("/upload", status_code=201)
async def upload(request: Request, file: UploadFile = File(...), alt: str = Form(""), seo_name: str = Form(""),
                 model_id: Optional[str] = Form(None), slot: Optional[str] = Form(None), side: str = Form("pubblico"),
                 pair_index: Optional[int] = Form(None), pair_id: Optional[str] = Form(None), poster_url: str = Form(""),
                 principal=Depends(require("media:write"))):
    data = await file.read()
    rec = await store_media(data, file.content_type or "", original_filename=file.filename or "", alt=alt, seo_name=seo_name,
                            model_id=model_id, slot=slot, actor=actor_of(principal), request_id=request_id_of(request))
    model_out = await _maybe_attach(rec, model_id, slot, side, rec["tipo"], alt, poster_url, pair_index, pair_id, principal, request)
    await audit_log(actor_of(principal), "upload", "file", rec["id"], {"tipo": rec["tipo"], "size": rec["size"], "model_id": model_id, "slot": slot}, request_id_of(request), principal.get("source", "manual"))
    return {"file": rec, "model": {"id": model_out["id"], "workflow_status": model_out["workflow_status"], "validation": model_out["validation"]} if model_out else None}


@media_router.post("/from-url", status_code=201)
async def upload_from_url(body: FromUrlBody, request: Request, principal=Depends(require("media:write"))):
    """Ingest a media file from a public URL or base64 payload (AI-friendly)."""
    if body.url:
        data, ctype = await asyncio.get_event_loop().run_in_executor(None, fetch_url_bytes, body.url)
        fname = body.filename or os.path.basename(urlparse(body.url).path)
    elif body.base64_data:
        raw = body.base64_data
        ctype = body.content_type or ""
        if raw.startswith("data:"):
            head, raw = raw.split(",", 1)
            ctype = head[5:].split(";")[0] or ctype
        try:
            data = base64.b64decode(raw)
        except Exception:
            raise HTTPException(status_code=400, detail="Base64 non valido")
        fname = body.filename or "upload"
    else:
        raise HTTPException(status_code=400, detail="Fornisci 'url' oppure 'base64_data'")
    rec = await store_media(data, ctype, original_filename=fname, alt=body.alt or "", seo_name=body.seo_name or "",
                            model_id=body.model_id, slot=body.slot, actor=actor_of(principal), request_id=request_id_of(request))
    model_out = await _maybe_attach(rec, body.model_id, body.slot, body.side, rec["tipo"], body.alt, body.poster_url, body.pair_index, body.pair_id, principal, request)
    await audit_log(actor_of(principal), "upload_from_url", "file", rec["id"], {"tipo": rec["tipo"], "model_id": body.model_id, "slot": body.slot}, request_id_of(request), principal.get("source", "manual"))
    return {"file": rec, "model": {"id": model_out["id"], "workflow_status": model_out["workflow_status"], "validation": model_out["validation"]} if model_out else None}


@media_router.get("/{file_id}")
async def get_media(file_id: str, principal=Depends(require("media:read"))):
    rec = await files_col.find_one({"id": file_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Media non trovato")
    return public_file(rec)


@media_router.patch("/{file_id}")
async def patch_media(file_id: str, body: MediaPatch, request: Request, principal=Depends(require("media:write"))):
    rec = await files_col.find_one({"id": file_id, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Media non trovato")
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "seo_name" in upd:
        upd["seo_filename"] = seo_filename(upd["seo_name"], EXT_MAP.get(rec["content_type"], "bin"))
    upd["updated_at"] = now_iso()
    new_rec = {**rec, **upd}
    await files_col.update_one({"id": file_id}, {"$set": upd})
    # propagate ALT to model references
    if "alt" in upd:
        url = public_file(rec)["url"]
        async for m in models_col.find({"media_pairs": {"$elemMatch": {"$or": [{"pubblico.url": {"$regex": re.escape(rec["storage_path"])}}, {"segreto.url": {"$regex": re.escape(rec["storage_path"])}}]}}}, {"_id": 0}):
            pairs = m.get("media_pairs") or []
            changed = False
            for p in pairs:
                for side in ("pubblico", "segreto"):
                    if rec["storage_path"] in ((p.get(side) or {}).get("url") or ""):
                        p[side]["alt"] = upd["alt"]
                        changed = True
            if changed:
                await models_col.update_one({"id": m["id"]}, {"$set": {"media_pairs": pairs, "updated_at": now_iso()}})
        _ = url
    await record_version("file", file_id, rec, new_rec, actor_of(principal), source=principal.get("source", "manual"), reason="Modifica metadata media", request_id=request_id_of(request))
    return public_file(new_rec)


async def _usages(rec: dict) -> List[dict]:
    path = rec.get("storage_path") or ""
    if not path:
        return []
    rx = re.escape(path.split("/")[-2] if "/" in path else path)  # folder id -> catches all variants
    used = []
    async for m in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1, "nome_artistico": 1, "foto_card": 1, "foto_copertina": 1, "foto_card_teaser": 1, "foto_segreta_hero": 1, "media_pairs": 1, "pellicola_home": 1, "seo": 1, "messaggio_35s": 1}):
        import json
        if re.search(rx, json.dumps(m)):
            used.append({"model_id": m["id"], "slug": m["slug"], "nome": m.get("nome_artistico")})
    return used


@media_router.delete("/{file_id}")
async def delete_media(file_id: str, request: Request, force: bool = False, principal=Depends(require("media:write"))):
    rec = await files_col.find_one({"id": file_id, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Media non trovato")
    usages = await _usages(rec)
    if usages and not force:
        raise HTTPException(status_code=409, detail={"message": "Media in uso: usa force=true per rimuoverlo comunque (le pagine mostreranno slot vuoti)", "usages": usages})
    await files_col.update_many({"$or": [{"id": file_id}, {"parent_id": file_id}]}, {"$set": {"is_deleted": True, "deleted_at": now_iso()}})
    new_rec = {**rec, "is_deleted": True, "deleted_at": now_iso()}
    await record_version("file", file_id, rec, new_rec, actor_of(principal), source=principal.get("source", "manual"), reason="Soft delete media", request_id=request_id_of(request))
    await audit_log(actor_of(principal), "soft_delete", "file", file_id, {"usages": usages}, request_id_of(request))
    return {"ok": True, "soft_deleted": True, "usages": usages}


@media_router.post("/{file_id}/replace")
async def replace_media(file_id: str, request: Request, file: UploadFile = File(...), principal=Depends(require("media:write"))):
    """Upload a new file under the same media id and rewrite every model reference to the old URLs."""
    rec = await files_col.find_one({"id": file_id, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Media non trovato")
    data = await file.read()
    old = public_file(rec)
    await files_col.delete_many({"parent_id": file_id})
    new = await store_media(data, file.content_type or "", original_filename=file.filename or rec.get("original_filename", ""), alt=rec.get("alt", ""),
                            seo_name=os.path.splitext(rec.get("seo_filename") or "")[0], model_id=rec.get("model_id"), slot=rec.get("slot"),
                            actor=actor_of(principal), request_id=request_id_of(request), file_id=file_id)
    # rewrite references
    mapping = {old["url"]: new["url"], old["web_url"]: new["web_url"], old["mobile_url"]: new["mobile_url"], old["thumb_url"]: new["thumb_url"]}
    if old.get("poster_url") and new.get("poster_url"):
        mapping[old["poster_url"]] = new["poster_url"]
    import json
    rewritten = []
    async for m in models_col.find({"is_deleted": {"$ne": True}}, {"_id": 0}):
        s = json.dumps(m)
        s2 = s
        for a, b in mapping.items():
            if a and b and a != b:
                s2 = s2.replace(a, b)
        if s2 != s:
            nd = json.loads(s2)
            nd["updated_at"] = now_iso()
            await models_col.replace_one({"id": m["id"]}, nd)
            await record_version("model", m["id"], m, nd, actor_of(principal), source=principal.get("source", "manual"), reason=f"Sostituzione media {file_id}", request_id=request_id_of(request))
            rewritten.append(m["slug"])
    await audit_log(actor_of(principal), "replace", "file", file_id, {"rewritten_models": rewritten}, request_id_of(request))
    return {"file": new, "rewritten_models": rewritten}


@media_router.post("/{file_id}/optimize")
async def optimize_media(file_id: str, request: Request, principal=Depends(require("media:write"))):
    """Regenerate variants (web/mobile/thumb or poster/mobile) from the stored original."""
    rec = await files_col.find_one({"id": file_id, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Media non trovato")
    from storage import get_object
    try:
        data, ctype = await asyncio.get_event_loop().run_in_executor(None, get_object, rec["storage_path"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Originale non recuperabile: {e}")
    await files_col.delete_many({"parent_id": file_id})
    new = await store_media(data, rec.get("content_type") or ctype, original_filename=rec.get("original_filename", ""), alt=rec.get("alt", ""),
                            seo_name=os.path.splitext(rec.get("seo_filename") or "")[0], model_id=rec.get("model_id"), slot=rec.get("slot"),
                            actor=actor_of(principal), request_id=request_id_of(request), file_id=file_id)
    return {"file": new, "optimized": True}


# ---- model association route lives under /api/v1/models/{id}/media ----
model_media_router = APIRouter(prefix="/api/v1/models", tags=["Media"])


@model_media_router.post("/{model_id}/media")
async def attach_media(model_id: str, body: AttachBody, request: Request, principal=Depends(require("media:write", "models:write"))):
    from v1_models import resolve_model
    doc = await resolve_model(model_id)
    url, tipo, poster = body.url, body.tipo, body.poster or ""
    if body.file_id:
        rec = await files_col.find_one({"id": body.file_id, "is_deleted": {"$ne": True}}, {"_id": 0})
        if not rec:
            raise HTTPException(status_code=404, detail="Media non trovato")
        pf = public_file(rec)
        tipo = tipo or rec["tipo"]
        url = pf["url"] if tipo == "video" else (pf.get(f"{body.prefer}_url") or pf["url"])
        poster = poster or (pf.get("poster_url") if tipo == "video" else "")
        await files_col.update_one({"id": rec["id"]}, {"$set": {"model_id": doc["id"], "slot": body.slot, "side": body.side}})
    if not url:
        raise HTTPException(status_code=400, detail="Fornisci file_id oppure url")
    tipo = tipo or ("video" if re.search(r"\.(mp4|webm|mov)(\?|$)", url, re.I) else "image")
    return await attach_to_model(doc, url=url, slot=body.slot, side=body.side, tipo=tipo, alt=body.alt or "", poster=poster,
                                 pair_index=body.pair_index, pair_id=body.pair_id, principal=principal, request=request, reason=body.reason or "")


@model_media_router.get("/{model_id}/media")
async def list_model_media(model_id: str, principal=Depends(require("media:read"))):
    from v1_models import resolve_model
    doc = await resolve_model(model_id, include_deleted=True)
    slots = {
        "foto_card": doc.get("foto_card"), "foto_copertina": doc.get("foto_copertina"),
        "foto_card_teaser": doc.get("foto_card_teaser"), "foto_segreta_hero": doc.get("foto_segreta_hero"),
        "og_image": (doc.get("seo") or {}).get("og_image"),
        "pellicola": doc.get("pellicola_home"), "messaggio_35s": {"foto": (doc.get("messaggio_35s") or {}).get("foto"), "video": (doc.get("messaggio_35s") or {}).get("video")},
        "media_pairs": doc.get("media_pairs") or [],
    }
    files = await files_col.find({"model_id": doc["id"], "parent_id": {"$exists": False}, "is_deleted": {"$ne": True}}, {"_id": 0}).to_list(200)
    return {"model_id": doc["id"], "slots": slots, "files": [public_file(f) for f in files], "available_slots": sorted(SLOTS)}
