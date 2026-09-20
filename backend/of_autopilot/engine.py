"""OF Autopilot engine — INDEPENDENT queue/state/cursors (collections of_*). Talks ONLY to `OFProviderAdapter`.

Pipeline (PUBLISH_NOW = immediate post, SCHEDULE = isScheduled+scheduledDate at the slot time):
  lock -> slot claim -> next eligible model -> next PUBLIC + next SECRET (two cursors, SAME_MODEL guard) -> real lightweight validation
  (HEAD/Range on OUR storage) -> caption IT + model's real OF link -> upload PUBLIC, upload SECRET (complete media objects, of_media_uploads)
  -> create/schedule -> VERIFY (GET post / GET schedules) -> ONLY on confirmation: cursors + queue advance. Any failure: no advance, bounded retries.
MOCK (OF_AUTOPILOT_MOCK=true): MockOFProvider for every write; the real adapter is used only for connection/health reads.

Collections: of_autopilot_state · of_model_media_state · of_media_uploads · of_autopilot_logs · of_autopilot_slots · of_autopilot_locks.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from database import db

from . import connection
from .caption import build_caption, build_dm_caption
from .media import fetch_bytes, roster, validate_media
from .providers.base import OFMassMessageRequest, OFMedia, OFPostRequest, OFProviderAdapter, OFProviderError, real_test_max_posts_limit
from .providers.mock import MOCK_OF_USER_ID, MockOFProvider
from .providers import the_only_api as toa

state_col = db["of_autopilot_state"]
media_state_col = db["of_model_media_state"]
uploads_col = db["of_media_uploads"]
log_col = db["of_autopilot_logs"]
slots_col = db["of_autopilot_slots"]
locks_col = db["of_autopilot_locks"]
runs_col = db["of_model_runs"]       # FEED + MASS DM state per (model_id, cycle_number): feed_status / mass_dm_status kept separate

DEFAULTS = {"enabled": False, "posts_per_day": 3, "schedule_times": ["11:30", "17:30", "22:00"], "timezone": "Europe/Rome", "use_ai_copy": True,
            "cycle_number": 1, "cycle_done": [], "last_position": -1, "current_position": 0, "current_model_id": None, "last_published": None, "last_processed": None,
            "last_run": None, "last_success": None, "last_error": None, "next_run": None, "last_slot": None}
MAX_MEDIA_ATTEMPTS = 3          # media tried per side (validation + upload), bounded
LOCK_TTL_S = 240
SLOT_LEAD_MIN = 30              # a scheduled slot is prepared up to 30' before its time (scheduledDate = slot time)
SLOT_GRACE_MIN = 90

_mock_provider: Optional[MockOFProvider] = None
_forced: Optional[OFProviderAdapter] = None


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def mock_enabled() -> bool:
    return os.environ.get("OF_AUTOPILOT_MOCK", "true").lower() in ("1", "true", "yes")


def auto_scheduler_enabled() -> bool:
    return connection.auto_scheduler_enabled()


def real_test_max_posts() -> Optional[int]:
    """None = test limit DISABLED (variable missing, empty, 0 or negative). Integer > 0 = controlled real test with that maximum."""
    return real_test_max_posts_limit()


def real_test_mode() -> bool:
    """Controlled real test: single candidate, STOP on any pre-check failure, hard post limit, write gate opened only for the write."""
    return (not mock_enabled()) and real_test_max_posts() is not None


async def real_posts_created() -> int:
    """Real (non-mock) create calls that returned a provider_post_id, any confirmation state (DB-level hard-limit source)."""
    return await log_col.count_documents({"mock": {"$ne": True}, "provider_post_id": {"$nin": [None, ""]}, "action_type": {"$in": ["PUBLISH_NOW", "SCHEDULE"]}})


def get_provider() -> OFProviderAdapter:
    """Writes go through here. MOCK -> MockOFProvider (process-wide, zero network). REAL -> OFProviderAdapter from connection (write-gated)."""
    global _mock_provider
    if _forced is not None:
        return _forced
    if mock_enabled():
        if _mock_provider is None:
            _mock_provider = MockOFProvider()
        return _mock_provider
    return connection.get_adapter()


def force_provider(p: Optional[OFProviderAdapter]):
    global _forced
    _forced = p


async def ensure_indexes():
    await slots_col.create_index("slot_id", unique=True)
    await locks_col.create_index("id", unique=True)
    await media_state_col.create_index("model_id", unique=True)
    await log_col.create_index([("timestamp", -1)])
    await uploads_col.create_index([("model_id", 1), ("created_at", -1)])
    await runs_col.create_index([("model_id", 1), ("cycle_number", 1)], unique=True)
    await state_col.update_one({"id": "global"}, {"$setOnInsert": {"id": "global", **DEFAULTS, "updated_at": now_iso()}}, upsert=True)


async def get_state() -> dict:
    st = await state_col.find_one({"id": "global"}, {"_id": 0})
    if not st:
        await ensure_indexes()
        st = await state_col.find_one({"id": "global"}, {"_id": 0})
    return {**DEFAULTS, **st}


async def set_state(**fields):
    fields["updated_at"] = now_iso()
    await state_col.update_one({"id": "global"}, {"$set": fields}, upsert=True)


# ----------------------------------------------------------------------------------------------- lock
async def acquire_lock(owner: str) -> bool:
    now = datetime.now(timezone.utc)
    try:
        await locks_col.insert_one({"id": "publish", "owner": None, "locked_until": now - timedelta(seconds=1)})
    except DuplicateKeyError:
        pass
    r = await locks_col.update_one({"id": "publish", "locked_until": {"$lt": now}}, {"$set": {"owner": owner, "locked_until": now + timedelta(seconds=LOCK_TTL_S)}})
    return r.modified_count == 1


async def release_lock(owner: str):
    await locks_col.update_one({"id": "publish", "owner": owner}, {"$set": {"owner": None, "locked_until": datetime.now(timezone.utc) - timedelta(seconds=1)}})


# ----------------------------------------------------------------------------------------------- queue
def _next_from(eligible: List[dict], done: set, last_position: int) -> Optional[dict]:
    n = len(eligible)
    if n == 0:
        return None
    start = (last_position + 1) % n
    for k in range(n):
        cand = eligible[(start + k) % n]
        if cand["model_id"] not in done:
            return cand
    return None


async def queue_view(st: Optional[dict] = None) -> dict:
    st = st or await get_state()
    ros = await roster()
    eligible = ros["eligible"]
    done = set(st.get("cycle_done") or [])
    ids = [r["model_id"] for r in eligible]
    nxt = _next_from(eligible, done, st.get("last_position", -1))
    n_done = len([i for i in ids if i in done])
    return {"roster": ros, "eligible": eligible, "n_eligible": len(eligible), "n_done_in_cycle": n_done, "next": nxt, "position": (n_done + 1) if nxt else len(ids)}


async def _advance(st: dict, eligible: List[dict], model_id: str, published: bool, published_info: Optional[dict], processed_status: str):
    done = list(st.get("cycle_done") or [])
    if model_id not in done:
        done.append(model_id)
    ids = [r["model_id"] for r in eligible]
    pos = ids.index(model_id) if model_id in ids else st.get("last_position", -1)
    cycle = st["cycle_number"]
    if all(i in done for i in ids):
        cycle, done, pos = cycle + 1, [], -1
    nxt = _next_from(eligible, set(done), pos)
    upd = {"cycle_done": done, "last_position": pos, "cycle_number": cycle, "current_position": len([i for i in ids if i in done]) + (1 if nxt else 0),
           "current_model_id": nxt["model_id"] if nxt else None, "last_processed": {"model_id": model_id, "status": processed_status, "at": now_iso()}}
    if published:
        upd["last_published"], upd["last_success"], upd["last_error"] = published_info, now_iso(), None
    await set_state(**upd)


# ----------------------------------------------------------------------------------------------- media cursors (two, independent)
def _seq_from_cursor(media: List[dict], last_id: Optional[str], last_index: int) -> List[dict]:
    if not media:
        return []
    ids = [x["id"] for x in media]
    idx = (ids.index(last_id) + 1) if last_id in ids else (int(last_index) + 1)
    idx %= len(media)
    return [media[(idx + k) % len(media)] for k in range(len(media))]


async def pick_sequences(model_id: str, public: List[dict], secret: List[dict]) -> dict:
    ms = await media_state_col.find_one({"model_id": model_id}, {"_id": 0}) or {}
    return {"public": _seq_from_cursor(public, ms.get("last_public_media_id"), ms.get("public_media_index", -1)),
            "secret": _seq_from_cursor(secret, ms.get("last_secret_media_id"), ms.get("secret_media_index", -1))}


async def mark_media_used(model_id: str, public: List[dict], secret: List[dict], pub: dict, sec: dict, cycle: int):
    """Called ONLY after a confirmed publication/schedule."""
    await media_state_col.update_one({"model_id": model_id}, {"$set": {
        "model_id": model_id, "last_public_media_id": pub["id"], "public_media_index": [x["id"] for x in public].index(pub["id"]),
        "last_secret_media_id": sec["id"], "secret_media_index": [x["id"] for x in secret].index(sec["id"]),
        "cycle_last_used": cycle, "last_published_at": now_iso(), "updated_at": now_iso()}}, upsert=True)


async def _log(**fields):
    doc = {"id": str(uuid.uuid4()), "timestamp": now_iso(), "created_at": now_iso(), **fields}
    await log_col.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _finish_slot(slot_id: Optional[str], status: str):
    if slot_id:
        await slots_col.update_one({"slot_id": slot_id}, {"$set": {"status": status, "finished_at": now_iso()}})


# ----------------------------------------------------------------------------------------------- media selection (validation) + upload
async def select_valid(seq: List[dict], model_id: str) -> dict:
    """First media of the cursor sequence that passes the real lightweight validation; bounded attempts; SAME_MODEL guard."""
    errors, chosen, val = [], None, None
    for item in seq[:MAX_MEDIA_ATTEMPTS]:
        if item.get("model_id") != model_id:
            errors.append({"media_id": item["id"], "stage": "VALIDATION", "reason": "FOREIGN_MODEL_MEDIA"})
            continue
        v = await validate_media(item)
        if v["ok"]:
            chosen, val = item, v
            break
        errors.append({"media_id": item["id"], "type": item["type"], "stage": "VALIDATION", "reason": v["reason"], "status_code": v["status_code"], "mime": v["mime"]})
    return {"item": chosen, "validation": val, "errors": errors}


async def _record_upload(model: dict, item: dict, val: dict, status: str, provider: str, media: Optional[OFMedia] = None, error: Optional[str] = None) -> str:
    doc = {"id": str(uuid.uuid4()), "model_id": model.get("id"), "model_name": model.get("nome_artistico") or model.get("nome"), "source_media_id": item["id"], "media_side": item["side"],
           "media_type": item["type"], "source_url": item["source_url"], "source_type": (val or {}).get("source_type"), "mime_type": (val or {}).get("mime"), "file_size": (val or {}).get("size"),
           "provider": provider, "provider_media_reference": media.provider_ref if media else None, "provider_media_object": dict(media.raw) if media else None,
           "uploaded_at": now_iso() if media else None, "status": status, "error": error, "created_at": now_iso(), "updated_at": now_iso()}
    await uploads_col.insert_one(dict(doc))
    return doc["id"]


async def _set_upload(upload_id: str, **fields):
    await uploads_col.update_one({"id": upload_id}, {"$set": {**fields, "updated_at": now_iso()}})


async def upload_side(provider: OFProviderAdapter, of_user_id: str, model: dict, seq: List[dict], is_mock: bool) -> dict:
    """Validate -> upload (source_url preferred, file fallback) -> COMPLETE media object. Tries up to MAX_MEDIA_ATTEMPTS media of the side.
    Returns {"item", "media", "upload_id", "validation", "errors"} or media=None when everything failed (caller: NO advance)."""
    errors, tried = [], 0
    for item in seq:
        if tried >= MAX_MEDIA_ATTEMPTS:
            break
        if item.get("model_id") != model.get("id"):
            errors.append({"media_id": item["id"], "reason": "FOREIGN_MODEL_MEDIA"})
            continue
        v = await validate_media(item)
        if not v["ok"]:
            errors.append({"media_id": item["id"], "type": item["type"], "stage": "VALIDATION", "reason": v["reason"], "status_code": v["status_code"], "mime": v["mime"]})
            continue
        tried += 1
        uid = await _record_upload(model, item, v, "MOCK_PREPARED" if is_mock else "UPLOAD_PENDING", provider.name)
        name = item["source_url"].split("?")[0].rsplit("/", 1)[-1] or f"{item['id']}.{'mp4' if item['type'] == 'video' else 'jpg'}"
        try:
            try:
                media = await provider.upload_media_from_url(of_user_id, source_url=item["source_url"], file_name=name, kind=item["type"])
                used_source = "source_url"
            except OFProviderError as e:
                if e.code != "NOT_SUPPORTED":
                    raise
                data, ctype = await fetch_bytes(item["source_url"])                              # FILE UPLOAD FALLBACK (server-side)
                media = await provider.upload_media(of_user_id, file_name=name, content=data, content_type=ctype or v["mime"] or "application/octet-stream")
                used_source = "file"
        except (OFProviderError, ValueError) as e:
            code = getattr(e, "code", "FETCH_ERROR")
            await _set_upload(uid, status="UPLOAD_FAILED", error=code)
            errors.append({"media_id": item["id"], "type": item["type"], "stage": "UPLOAD", "reason": code})
            if code in ("WRITES_DISABLED", "NOT_CONNECTED", "UNAUTHORIZED", "NOT_CONFIGURED"):
                break                                                                             # infrastructure gate: stop immediately
            continue
        # NO FALSE SUCCESS: a usable media object (processId + complete fields) is mandatory
        if not media or not media.raw or not media.raw.get("processId"):
            await _set_upload(uid, status="UPLOAD_FAILED", error="NO_MEDIA_OBJECT")
            errors.append({"media_id": item["id"], "stage": "UPLOAD", "reason": "NO_MEDIA_OBJECT"})
            continue
        await _set_upload(uid, status="UPLOAD_SUCCESS", provider_media_reference=media.provider_ref, provider_media_object=dict(media.raw), uploaded_at=now_iso(), source_type=used_source)
        return {"item": item, "media": media, "upload_id": uid, "validation": v, "errors": errors, "source_type": used_source}
    return {"item": None, "media": None, "upload_id": None, "validation": None, "errors": errors}


# ----------------------------------------------------------------------------------------------- readiness
async def readiness(live: bool = False) -> dict:
    """MOCK: always operational (no network). REAL: CONNECTED + HEALTHY (+ live re-check when live=True) + OF_REAL_POSTING_ENABLED
    + hard limit not reached (real test mode)."""
    if mock_enabled():
        return {"operational": True, "reason": None, "connection": connection.public_view(await connection.saved())}
    if not connection.real_posting_enabled():
        return {"operational": False, "reason": "OF_REAL_POSTING_DISABLED", "connection": connection.public_view(await connection.saved())}
    conn = await connection.discover(check_schedules=False) if live else connection.public_view(await connection.saved())
    if conn.get("CONNECTION_STATUS") != "CONNECTED" or conn.get("ACCOUNT_STATUS") != "HEALTHY" or (conn.get("ACCOUNT_USERNAME") or "").lower() != connection.EXPECTED_USERNAME:
        return {"operational": False, "reason": f"ACCOUNT_{conn.get('ACCOUNT_STATUS')}" if conn.get("CONNECTION_STATUS") == "CONNECTED" else conn.get("CONNECTION_STATUS"), "connection": conn}
    mx = real_test_max_posts()
    if mx is not None and await real_posts_created() >= mx:
        return {"operational": False, "reason": "REAL_TEST_LIMIT", "connection": conn}
    return {"operational": True, "reason": None, "connection": conn}


async def _of_user_id(is_mock: bool) -> Optional[str]:
    return MOCK_OF_USER_ID if is_mock else await connection.of_user_id()


# ----------------------------------------------------------------------------------------------- preview (zero write)
async def preview() -> dict:
    st = await get_state()
    q = await queue_view(st)
    cand = q["next"]
    conn = connection.public_view(await connection.saved())
    if not cand:
        return {"status": "NO_ELIGIBLE_MODELS", "connection": conn}
    model = next(x for x in q["roster"]["models"] if x["id"] == cand["model_id"])
    seqs = await pick_sequences(cand["model_id"], cand["public"], cand["secret"])
    pub = await select_valid(seqs["public"], cand["model_id"])
    sec = await select_valid(seqs["secret"], cand["model_id"])
    cap = await build_caption(model, cand["of_url"], st["cycle_number"], use_ai=st["use_ai_copy"])
    sch = await schedule_view(st)
    same_model = bool(pub["item"] and sec["item"] and pub["item"]["model_id"] == sec["item"]["model_id"] == cand["model_id"])
    return {"status": "PREVIEW", "model": cand["name"], "model_slug": cand["slug"], "position": q["position"], "total": q["n_eligible"], "cycle_number": st["cycle_number"],
            "public": pub["item"], "public_validation": pub["validation"], "public_errors": pub["errors"], "secret": sec["item"], "secret_validation": sec["validation"], "secret_errors": sec["errors"],
            "media_order": ["PUBLIC", "SECRET"], "SAME_MODEL_MEDIA": same_model, "caption": cap["text"], "caption_source": cap["source"], "of_url": cand["of_url"],
            "slot": sch["next_slot"], "provider": "MOCK" if mock_enabled() else conn.get("PROVIDER"), "account": conn.get("ACCOUNT_USERNAME"), "account_status": conn.get("ACCOUNT_STATUS"),
            "mock": mock_enabled(), "writes": 0}


# ----------------------------------------------------------------------------------------------- pipeline
async def run(action: str = "PUBLISH_NOW", trigger: str = "admin", slot_id: Optional[str] = None, scheduled_at: Optional[str] = None) -> dict:
    """action PUBLISH_NOW -> immediate post + verify (GET post). action SCHEDULE -> isScheduled+scheduledDate + verify (GET schedules).
    Queue/cursors advance ONLY after *_CONFIRMED."""
    assert action in ("PUBLISH_NOW", "SCHEDULE")
    owner = str(uuid.uuid4())
    if not await acquire_lock(owner):
        return {"status": "LOCKED", "detail": "pubblicazione già in corso"}
    try:
        st = await get_state()
        if slot_id:
            try:
                await slots_col.insert_one({"slot_id": slot_id, "claimed_at": now_iso(), "trigger": trigger, "status": "RUNNING"})
            except DuplicateKeyError:
                await _log(status="SKIP_DUPLICATE_SLOT", action_type=action, slot_id=slot_id, trigger=trigger, cycle_number=st["cycle_number"])
                return {"status": "SKIP_DUPLICATE_SLOT", "slot_id": slot_id}
        await set_state(last_run=now_iso(), last_slot=slot_id or st.get("last_slot"))
        ready = await readiness(live=not mock_enabled())                      # REAL: live health check right before any write
        if not ready["operational"]:
            await set_state(last_error=ready["reason"])
            res = await _log(status="FAILED", action_type=action, error_code=ready["reason"], slot_id=slot_id, trigger=trigger, cycle_number=st["cycle_number"])
            await _finish_slot(slot_id, "FAILED")
            return {"status": "FAILED", "error_code": ready["reason"], "log": res, "ACCOUNT_STATUS": (ready.get("connection") or {}).get("ACCOUNT_STATUS")}
        if action == "SCHEDULE" and real_test_mode():
            await _finish_slot(slot_id, "FAILED")
            return {"status": "FAILED", "error_code": "REAL_TEST_MODE_IMMEDIATE_ONLY"}
        q = await queue_view(st)
        eligible = q["eligible"]
        if not eligible:
            res = await _log(status="FAILED", action_type=action, error_code="NO_ELIGIBLE_MODELS", slot_id=slot_id, trigger=trigger, cycle_number=st["cycle_number"])
            await _finish_slot(slot_id, "FAILED")
            return {"status": "FAILED", "error_code": "NO_ELIGIBLE_MODELS", "log": res}
        provider = get_provider()
        is_mock = isinstance(provider, MockOFProvider)
        of_uid = await _of_user_id(is_mock)
        if not of_uid:
            await _finish_slot(slot_id, "FAILED")
            return {"status": "FAILED", "error_code": "OF_USER_ID_MISSING"}
        result = None
        single = real_test_mode()                                             # controlled real test: ONE candidate, never the next model
        gate_opened = False
        for _ in range(1 if single else len(eligible)):                       # bounded pass over the queue
            st = await get_state()
            cand = _next_from(eligible, set(st.get("cycle_done") or []), st.get("last_position", -1))
            if not cand:
                break
            model = next(x for x in q["roster"]["models"] if x["id"] == cand["model_id"])
            base = {"model_id": cand["model_id"], "model_slug": cand["slug"], "model_name": cand["name"], "cycle_number": st["cycle_number"], "slot_id": slot_id, "action_type": action, "trigger": trigger, "of_link": cand["of_url"], "mock": is_mock}
            prev = await get_run(cand["model_id"], st["cycle_number"])
            if prev and prev.get("feed_status") == "OK":                                             # FEED already confirmed this cycle -> NEVER a second feed: only the mass DM
                result = await _retry_dm_only(provider, of_uid, model, cand, prev, st, eligible, is_mock, trigger, slot_id)
                break
            seqs = await pick_sequences(cand["model_id"], cand["public"], cand["secret"])
            # ---- 1) validate BOTH sides first (real HEAD on our storage) -> skip the model before any upload if a side has no valid media
            pub_sel = await select_valid(seqs["public"], cand["model_id"])
            if not pub_sel["item"]:
                if single:
                    result = await _fail(base, "STOPPED_PRECHECK", pub_sel["errors"], slot_id, error_code="NO_VALID_PUBLIC_MEDIA"); break
                await _advance(st, eligible, cand["model_id"], False, None, "SKIPPED_NO_PUBLIC")
                await _log(status="SKIPPED_NO_PUBLIC", **base, error_code="NO_VALID_PUBLIC_MEDIA", media_errors=pub_sel["errors"])
                continue
            sec_sel = await select_valid(seqs["secret"], cand["model_id"])
            if not sec_sel["item"]:
                if single:
                    result = await _fail(base, "STOPPED_PRECHECK", sec_sel["errors"], slot_id, error_code="NO_VALID_SECRET_MEDIA"); break
                await _advance(st, eligible, cand["model_id"], False, None, "SKIPPED_NO_SECRET")
                await _log(status="SKIPPED_NO_SECRET", **base, error_code="NO_VALID_SECRET_MEDIA", media_errors=sec_sel["errors"])
                continue
            if pub_sel["item"]["model_id"] != cand["model_id"] or sec_sel["item"]["model_id"] != cand["model_id"]:
                result = await _fail(base, "STOPPED_PRECHECK", [], slot_id, error_code="SAME_MODEL_MEDIA_FAILED"); break
            mx = real_test_max_posts()
            if not is_mock and mx is not None and await real_posts_created() >= mx:                   # HARD LIMIT before any upload
                result = await _fail(base, "BLOCKED", [], slot_id, error_code="REAL_TEST_LIMIT"); break
            if not is_mock and hasattr(provider, "set_write_gate"):                                    # open the panel write gate ONLY now
                try:
                    await provider.set_write_gate(of_uid, True)
                    gate_opened = True
                except OFProviderError as e:
                    result = await _fail(base, "FAILED", [{"stage": "WRITE_GATE", "reason": e.code}], slot_id, error_code=f"WRITE_GATE_{e.code}"); break
            # ---- 2) upload PUBLIC then SECRET (complete media objects); any upload failure -> NO advance
            pub = await upload_side(provider, of_uid, model, seqs["public"], is_mock)
            if not pub["media"]:
                result = await _fail(base, "UPLOAD_FAILED", pub_sel["errors"] + pub["errors"], slot_id)
                break
            sec = await upload_side(provider, of_uid, model, seqs["secret"], is_mock)
            if not sec["media"]:
                result = await _fail(base, "UPLOAD_FAILED", sec_sel["errors"] + sec["errors"], slot_id, public_media_id=pub["item"]["id"])
                break
            pub["errors"], sec["errors"] = pub_sel["errors"] + pub["errors"], sec_sel["errors"] + sec["errors"]
            assert pub["item"]["model_id"] == sec["item"]["model_id"] == cand["model_id"], "SAME_MODEL_MEDIA violated"
            cap = await build_caption(model, cand["of_url"], st["cycle_number"], use_ai=st["use_ai_copy"])
            req = OFPostRequest(text=cap["text"], media=[pub["media"], sec["media"]], scheduled_at=scheduled_at if action == "SCHEDULE" else None)   # PUBLIC first
            info = {**base, "public_media_id": pub["item"]["id"], "secret_media_id": sec["item"]["id"], "public_source_url": pub["item"]["source_url"], "secret_source_url": sec["item"]["source_url"],
                    "public_media_type": pub["item"]["type"], "secret_media_type": sec["item"]["type"], "caption_source": cap["source"], "scheduled_at": req.scheduled_at}
            # ---- create / schedule + verify (hard limit re-checked right before the create write)
            if not is_mock and mx is not None and await real_posts_created() >= mx:
                result = await _fail(info, "BLOCKED", [], slot_id, error_code="REAL_TEST_LIMIT"); break
            try:
                if action == "SCHEDULE":
                    pr = await provider.schedule_post(of_uid, req)
                    confirmed = pr.schedule_state == "SCHEDULE_CONFIRMED"
                    real_status = "SCHEDULE_CONFIRMED" if confirmed else "SCHEDULE_NOT_CONFIRMED"
                else:
                    pr = await provider.create_post(of_uid, req)
                    verify = await verify_real_post(provider, of_uid, pr, cap["text"], cand["of_url"], [pub["media"], sec["media"]])
                    confirmed = verify["ok"]
                    real_status = "POST_CONFIRMED" if confirmed else "POST_NOT_CONFIRMED"
            except OFProviderError as e:
                for u in (pub["upload_id"], sec["upload_id"]):
                    await _set_upload(u, status="UPLOAD_SUCCESS", error=f"post: {e.code}")
                result = await _fail(info, "FAILED", [{"stage": "CREATE", "reason": e.code}], slot_id, error_code=e.code)
                break
            info["provider_post_id"] = pr.post_id
            if action == "PUBLISH_NOW":
                info["verification"] = verify
            if not confirmed:                                                                           # 200 but not verifiable -> NO advance
                await set_state(last_error=real_status)
                res = await _log(status=real_status, **info, error_code=real_status)
                await _finish_slot(slot_id, real_status)
                result = {"status": real_status, **info, "caption": cap["text"], "log": res}
                break
            # ---- confirmed FEED: uploads USED_IN_POST, cursors; queue advances only when the MASS DM step is complete (or not applicable)
            for u in (pub["upload_id"], sec["upload_id"]):
                await _set_upload(u, status="USED_IN_POST", provider_post_id=pr.post_id)
            await mark_media_used(cand["model_id"], cand["public"], cand["secret"], pub["item"], sec["item"], st["cycle_number"])
            status_ = "MOCK_CONFIRMED" if is_mock else real_status
            pub_info = {"model_id": cand["model_id"], "model_slug": cand["slug"], "model_name": cand["name"], "public_media_id": pub["item"]["id"], "secret_media_id": sec["item"]["id"],
                        "provider_post_id": pr.post_id, "action_type": action, "status": status_, "at": now_iso(), "cycle_number": st["cycle_number"], "slot_id": slot_id}
            run_doc = await upsert_run(cand["model_id"], st["cycle_number"], model_slug=cand["slug"], model_name=cand["name"], mock=is_mock, action_type=action, slot_id=slot_id,
                                       feed_status="OK", feed_post_id=pr.post_id, feed_media_ids=(verify.get("media_ids") if action == "PUBLISH_NOW" else []) or [],
                                       feed_caption=cap["text"], feed_confirmed_at=now_iso(), of_link=cand["of_url"], public_media_id=pub["item"]["id"], secret_media_id=sec["item"]["id"],
                                       public_source_url=pub["item"]["source_url"], secret_source_url=sec["item"]["source_url"], public_media_type=pub["item"]["type"], secret_media_type=sec["item"]["type"],
                                       dm_due_at=(_dm_due(scheduled_at) if action == "SCHEDULE" else None))
            res = await _log(status=status_, real_status=real_status, **info, media_errors=(pub["errors"] + sec["errors"]) or None)
            result = {"status": status_, "real_status": real_status, **info, "caption": cap["text"], "media_order": ["PUBLIC", "SECRET"], "SAME_MODEL_MEDIA": True,
                      "public_media_object": dict(pub["media"].raw), "secret_media_object": dict(sec["media"].raw), "log": res, "FEED_STATUS": "OK"}
            dm = await _mass_dm_step(provider, of_uid, model, run_doc, is_mock, trigger, deferred_ok=(action == "SCHEDULE"))
            result["mass_dm"] = dm
            result["MASS_DM_STATUS"] = dm["MASS_DM_STATUS"]
            if dm["advance"]:
                await _advance(st, eligible, cand["model_id"], True, pub_info, status_)
                await _finish_slot(slot_id, status_)
            else:                                                                                       # feed done, DM pending/failed -> NO advance (retry only the DM)
                await set_state(last_error=f"MASS_DM:{dm.get('error_code') or dm['MASS_DM_STATUS']}" if dm["MASS_DM_STATUS"] != "PENDING" else None)
                await _finish_slot(slot_id, f"{status_}_DM_{dm['MASS_DM_STATUS']}")
                result["status"] = f"{status_}_DM_{dm['MASS_DM_STATUS']}"
            break
        if result is None:
            result = {"status": "FAILED", "error_code": "NO_PUBLISHABLE_MODEL"}
            await _finish_slot(slot_id, "FAILED")
        if gate_opened:                                                                                # ALWAYS restore the gate (PASS or FAIL) and verify by READ
            result["write_gate"] = await _restore_gate(provider, of_uid)
        return result
    finally:
        await release_lock(owner)


# ----------------------------------------------------------------------------------------------- FEED + MASS DM run state (collection of_model_runs)
def mass_dm_enabled() -> bool:
    return os.environ.get("OF_MASS_DM_ENABLED", "false").lower() in ("1", "true", "yes")


def mass_dm_mock() -> bool:
    return os.environ.get("OF_MASS_DM_MOCK", "true").lower() in ("1", "true", "yes")


def _dm_due(scheduled_at: Optional[str]) -> Optional[str]:
    """Scheduled feed -> the DM is due 2' after the post goes live (media must be consumed by the post before it can be attached)."""
    if not scheduled_at:
        return None
    try:
        return (datetime.fromisoformat(scheduled_at) + timedelta(minutes=2)).isoformat()
    except ValueError:
        return None


async def get_run(model_id: str, cycle: int) -> Optional[dict]:
    return await runs_col.find_one({"model_id": model_id, "cycle_number": cycle}, {"_id": 0})


async def upsert_run(model_id: str, cycle: int, **fields) -> dict:
    fields = {k: v for k, v in fields.items() if v is not None or k in ("dm_due_at", "mass_dm_error")}
    on_insert = {"id": str(uuid.uuid4()), "model_id": model_id, "cycle_number": cycle, "created_at": now_iso(), "mass_dm_status": "PENDING", "mass_dm_attempts": 0}
    on_insert = {k: v for k, v in on_insert.items() if k not in fields}                   # a key may live in $set OR $setOnInsert, never both
    await runs_col.update_one({"model_id": model_id, "cycle_number": cycle}, {"$set": {**fields, "updated_at": now_iso()}, "$setOnInsert": on_insert}, upsert=True)
    return await get_run(model_id, cycle)


def _media_ids_from_post(data: dict) -> list:
    media = (data or {}).get("media") or (data or {}).get("mediaFiles") or []
    return [m.get("id") for m in media if isinstance(m, dict) and m.get("id") is not None]


def _dm_provider(feed_provider: OFProviderAdapter, is_mock: bool):
    """Which provider sends the DM, or (None, reason). MOCK DM only after a MOCK feed (same MockOFProvider); REAL DM only after a REAL feed."""
    if not mass_dm_enabled():
        return None, "DISABLED"
    if mass_dm_mock():
        return (feed_provider, None) if is_mock else (None, "MOCK_ONLY")
    return (None, "SKIPPED") if is_mock else (feed_provider, None)


async def _mass_dm_step(provider: OFProviderAdapter, of_uid: str, model: dict, run: dict, is_mock: bool, trigger: str, deferred_ok: bool = False) -> dict:
    """ONE mass message to ALL fans for the run's model (same PUBLIC+SECRET pair as the feed, different copy). Never twice: an existing
    mass_dm_id/OK status is final. Returns {"MASS_DM_STATUS", "advance", ...}. advance=True when the queue may move on."""
    mid, cyc = run["model_id"], run["cycle_number"]
    out = {"MASS_DM_STATUS": run.get("mass_dm_status") or "PENDING", "advance": False, "mass_dm_id": run.get("mass_dm_id"), "duplicate_prevented": False, "error_code": None}
    if run.get("mass_dm_status") in ("OK", "UNVERIFIED") or run.get("mass_dm_id"):
        out.update(MASS_DM_STATUS=run.get("mass_dm_status") or "UNVERIFIED", advance=run.get("mass_dm_status") == "OK", duplicate_prevented=True)
        return out
    dmp, reason = _dm_provider(provider, is_mock)
    if dmp is None:
        await upsert_run(mid, cyc, mass_dm_status=reason)
        out.update(MASS_DM_STATUS=reason, advance=True)                                                  # not applicable -> feed-only behaviour (unchanged)
        return out
    if run.get("feed_status") != "OK":
        out.update(MASS_DM_STATUS="PENDING", error_code="FEED_NOT_CONFIRMED")
        return out
    if run.get("dm_due_at") and run["dm_due_at"] > now_iso():
        if deferred_ok:
            out.update(MASS_DM_STATUS="PENDING", error_code="DEFERRED_UNTIL_POST_LIVE")                 # scheduled feed: DM handled by tick() when due
        return out
    if run.get("mass_dm_status") == "SENDING":
        out.update(MASS_DM_STATUS="SENDING", duplicate_prevented=True)
        return out
    # vault ids of the confirmed feed (appear ~10-15s after the post consumed the media): short controlled wait, never a new feed
    media_ids = list(run.get("feed_media_ids") or [])
    for attempt in range(VAULT_ID_TRIES if not is_mock else 1):
        if len(media_ids) >= 2 or not run.get("feed_post_id"):
            break
        if attempt:
            await asyncio.sleep(VAULT_ID_WAIT_S)
        try:
            media_ids = _media_ids_from_post(await provider.get_post(of_uid, run["feed_post_id"]))
        except OFProviderError:
            media_ids = media_ids or []
    if not media_ids:
        await upsert_run(mid, cyc, mass_dm_status="FAILED", mass_dm_error="NO_VAULT_MEDIA_IDS", mass_dm_attempts=int(run.get("mass_dm_attempts") or 0) + 1)
        await _log(status="MASS_DM_FAILED", action_type="MASS_DM", model_id=mid, model_slug=run.get("model_slug"), model_name=run.get("model_name"), cycle_number=cyc, trigger=trigger, mock=is_mock, error_code="NO_VAULT_MEDIA_IDS")
        out.update(MASS_DM_STATUS="FAILED", error_code="NO_VAULT_MEDIA_IDS")
        return out
    if media_ids != list(run.get("feed_media_ids") or []):
        await upsert_run(mid, cyc, feed_media_ids=media_ids)
    text = run.get("mass_dm_text")
    if not text:
        st = await get_state()
        cap = await build_dm_caption(model, run["of_link"], cyc, run.get("feed_caption") or "", use_ai=st.get("use_ai_copy", True))
        text = cap["text"]
        await upsert_run(mid, cyc, mass_dm_text=text, mass_dm_copy_source=cap["source"], mass_dm_different_from_feed=bool(cap["different_from_feed"]))
    run_filter = {"model_id": mid, "cycle_number": cyc}
    log_base = dict(action_type="MASS_DM", model_id=mid, model_slug=run.get("model_slug"), model_name=run.get("model_name"), cycle_number=cyc, trigger=trigger, mock=is_mock, of_link=run["of_link"],
                    feed_post_id=run.get("feed_post_id"), public_media_id=run.get("public_media_id"), secret_media_id=run.get("secret_media_id"), media_ids=media_ids)
    res = await _execute_mass_dm(dmp, provider, of_uid, run_filter, text, media_ids, run["of_link"], is_mock, log_base, attempts_before=int(run.get("mass_dm_attempts") or 0))
    out.update(MASS_DM_STATUS=res["MASS_DM_STATUS"], advance=res["MASS_DM_STATUS"] == "OK", mass_dm_id=res.get("MASS_DM_MARKER"), error_code=res.get("error_code"), target="FAN",
               fans_list_id=res.get("FANS_LIST_ID"), fans_users_count=res.get("OF_FANS_USERS_COUNT"), audience_size=res.get("OF_FANS_USERS_COUNT"), text=text, refresh=res.get("refresh"),
               sent_count=res.get("REAL_MASS_DM_SENT_COUNT"), queue_verify=res.get("QUEUE_VERIFY"), readback=res.get("READBACK_VERIFY"))
    return out


# ----------------------------------------------------------------------------------------------- shared CRM mass DM flow (refresh -> dry_run -> SENDING -> send -> read-back)
REFRESH_POLL_S = float(os.environ.get("OF_REFRESH_POLL_SECONDS", "10"))
VAULT_ID_TRIES, VAULT_ID_WAIT_S = 4, 8.0


def refresh_max_wait_minutes() -> float:
    try:
        return float(os.environ.get("OF_REFRESH_MAX_WAIT_MINUTES", "10"))
    except ValueError:
        return 10.0


async def _refresh_subscribers(dmp: OFProviderAdapter, of_uid: str, run_filter: dict, is_mock: bool, subscribers_hint: Optional[int]) -> dict:
    """POST subscribers/refresh -> poll GET subscribers/refresh/status (READ) until COMPLETED / FAILED / timeout. Sends nothing, never touches queue/media/feed.
    Returns {"ok", "status": OK|FAILED|TIMEOUT|EMPTY_CACHE|START_FAILED|NOT_SUPPORTED, "cache": {...}}."""
    started = now_iso()
    rec = {"subscriber_refresh_status": "RUNNING", "subscriber_refresh_started_at": started, "subscriber_refresh_completed_at": None}
    await runs_col.update_one(run_filter, {"$set": {**rec, "updated_at": now_iso()}})
    try:
        before = await dmp.subscribers_refresh_status(of_uid)
    except OFProviderError:
        before = {"state": "UNKNOWN", "cache": {}}
    try:
        await dmp.subscribers_refresh_start(of_uid)
    except OFProviderError as e:
        st = "NOT_SUPPORTED" if e.code == "NOT_SUPPORTED" else "START_FAILED"
        await runs_col.update_one(run_filter, {"$set": {"subscriber_refresh_status": st, "subscriber_refresh_error": e.code, "updated_at": now_iso()}})
        return {"ok": False, "status": st, "error_code": e.code, "cache": before.get("cache") or {}}
    deadline = datetime.now(timezone.utc) + timedelta(minutes=refresh_max_wait_minutes())
    status, cache, polls = "TIMEOUT", before.get("cache") or {}, 0
    while datetime.now(timezone.utc) < deadline:
        try:
            cur = await dmp.subscribers_refresh_status(of_uid)
        except OFProviderError as e:
            cur = {"state": "UNKNOWN", "cache": cache, "error": e.code}
        polls += 1
        cache = cur.get("cache") or cache
        state = cur.get("state")
        fresh = bool(cache.get("last_refreshed_at")) and cache.get("last_refreshed_at") != (before.get("cache") or {}).get("last_refreshed_at") and str(cache.get("last_refreshed_at")) >= started[:19]
        if state == "COMPLETED" or (state in ("IDLE", "UNKNOWN") and fresh):
            status = "OK"
            break
        if state == "FAILED":
            status = "FAILED"
            break
        await asyncio.sleep(0 if is_mock else REFRESH_POLL_S)
    total = cache.get("total")
    if status == "OK" and (not isinstance(total, int) or total <= 0) and (subscribers_hint or 0) > 0:
        status = "EMPTY_CACHE"                                                                     # completed but the cache is still empty while OnlyFans reports fans -> do NOT send
    upd = {"subscriber_refresh_status": status, "subscriber_refresh_completed_at": now_iso() if status in ("OK", "FAILED", "EMPTY_CACHE") else None, "subscriber_refresh_polls": polls,
           "cached_total": cache.get("total"), "cached_active": cache.get("active"), "cached_expired": cache.get("expired"), "last_refreshed_at": cache.get("last_refreshed_at")}
    await runs_col.update_one(run_filter, {"$set": {**upd, "updated_at": now_iso()}})
    return {"ok": status == "OK", "status": status, "cache": cache, "polls": polls}


async def _execute_mass_dm(dmp: OFProviderAdapter, provider: OFProviderAdapter, of_uid: str, run_filter: dict, text: str, media_ids: list, of_url: str, is_mock: bool, log_base: dict, attempts_before: int = 0) -> dict:
    """ONE mass DM = OnlyFans UI "Messaggio di massa -> Fan": subscriber cache refresh (CRM data only) -> GET lists -> system list type=fans (usersCount>0)
    -> gate on -> state SENDING -> POST messages/mass {userLists:[fans_id], excludedLists:[]} -> verify (GET messages/queue by id, else read-back recent chats)
    -> OK | UNVERIFIED | FAILED -> gate off (finally, verified by READ). No audience.type, no fan_ids, no cache-built audience, no tranches, never a second send."""
    rep = {"MASS_DM_STATUS": "PENDING", "TARGET": "FAN", "WRITE_GATE_ENABLED": False, "REAL_MASS_DM_CREATE": None, "FANS_LIST_FOUND": None, "FANS_LIST_ID": None, "OF_FANS_USERS_COUNT": None,
           "FANS_DRY_RUN_SUPPORTED": bool(getattr(dmp, "FANS_DRY_RUN_SUPPORTED", False)), "REAL_MASS_DM_SENT_COUNT": None, "MASS_DM_ID": None, "QUEUE_VERIFY": None, "READBACK_VERIFY": None,
           "MASS_DM_MARKER": None, "error_code": None, "refresh": None}
    gate_opened = False

    async def fail(status: str, err: str, log_status: str = "MASS_DM_FAILED", **extra):
        await runs_col.update_one(run_filter, {"$set": {"mass_dm_status": status, "mass_dm_error": err, "updated_at": now_iso(), **extra}, "$inc": {"mass_dm_attempts": 1}})
        await _log(status=log_status, **log_base, error_code=err, fans_users_count=rep.get("OF_FANS_USERS_COUNT"))
        rep.update(MASS_DM_STATUS=status, error_code=err)
        return rep

    try:
        try:
            hint = await dmp.subscribers_count(of_uid)
        except OFProviderError:
            hint = None
        rep["SUBSCRIBERS_COUNT"] = hint
        # 1) subscriber cache refresh (keeps CRM data fresh; NOT the audience source). If the panel gate blocks it, open the gate and retry once.
        ref = await _refresh_subscribers(dmp, of_uid, run_filter, is_mock, hint)
        if ref["status"] == "START_FAILED" and ref.get("error_code") in ("FORBIDDEN", "WRITES_DISABLED") and hasattr(dmp, "set_write_gate"):
            await dmp.set_write_gate(of_uid, True)
            gate_opened, rep["WRITE_GATE_ENABLED"] = True, True
            ref = await _refresh_subscribers(dmp, of_uid, run_filter, is_mock, hint)
        rep["refresh"] = {k: ref.get(k) for k in ("status", "polls")} | {"cache": ref.get("cache")}
        if not ref["ok"]:
            return await fail("PENDING" if ref["status"] in ("TIMEOUT", "START_FAILED") else "FAILED", f"REFRESH_{ref['status']}", "MASS_DM_REFRESH_FAILED")
        # 2) resolve the native OnlyFans "Fans" list dynamically (READ) — the ONLY target
        try:
            fans = await dmp.get_fans_list(of_uid)
        except OFProviderError as e:
            fans = None
            rep["FANS_LIST_ERROR"] = e.code
        rep["FANS_LIST_FOUND"] = bool(fans)
        if not fans:
            return await fail("FAILED", "FANS_LIST_NOT_FOUND", target="FAN")
        rep["FANS_LIST_ID"], rep["OF_FANS_USERS_COUNT"] = fans["id"], fans.get("usersCount")
        await runs_col.update_one(run_filter, {"$set": {"target": "FAN", "of_fans_list_id": fans["id"], "of_fans_users_count": fans.get("usersCount"), "updated_at": now_iso()}})
        if not isinstance(fans.get("usersCount"), int) or fans["usersCount"] <= 0:
            return await fail("FAILED", "FANS_LIST_EMPTY")
        req = OFMassMessageRequest(text=text, media_ids=media_ids, price=None, user_lists=[fans["id"]], excluded_lists=[])
        # 3) gate on (writes)
        if not gate_opened and hasattr(dmp, "set_write_gate"):
            await dmp.set_write_gate(of_uid, True)
            gate_opened, rep["WRITE_GATE_ENABLED"] = True, True
        # 4) SENDING state BEFORE the send (idempotency key = run_filter: model_id + cycle/post key)
        await runs_col.update_one(run_filter, {"$set": {"mass_dm_status": "SENDING", "mass_dm_recipients": fans["usersCount"], "mass_dm_user_lists": [fans["id"]], "mass_dm_send_started_at": now_iso(), "updated_at": now_iso()}, "$inc": {"mass_dm_attempts": 1}})
        send_error, definitive_fail, res = None, False, None
        try:
            res = await dmp.mass_message_fans(of_uid, req)
        except OFProviderError as e:
            send_error = e.code
            definitive_fail = e.code in ("WRITES_DISABLED", "FORBIDDEN", "MASS_DM_DISABLED", "NOT_SUPPORTED", "NOT_CONFIGURED", "UNAUTHORIZED", "NOT_FOUND") or (e.code == "API_ERROR" and e.status is not None and e.status < 500)
        mid = res.get("id") if isinstance(res, dict) else None
        sent = res.get("sent") if isinstance(res, dict) else None
        accepted = isinstance(res, dict) and bool(res.get("success"))
        rep.update(REAL_MASS_DM_CREATE="PASS" if accepted else ("FAIL" if (res is not None or definitive_fail) else f"UNKNOWN_{send_error}"), REAL_MASS_DM_SENT_COUNT=sent, MASS_DM_ID=mid)
        # 5) verify: documented queue READ by id first; otherwise read-back on recent conversations (never a reason to resend)
        q_ok = False
        if mid:
            try:
                q_ok = await dmp.verify_mass_message(of_uid, str(mid))
            except OFProviderError:
                q_ok = False
        rep["QUEUE_VERIFY"] = ("PASS" if q_ok else "FAIL") if mid else "NO_ID"
        verified, checked = q_ok, 0
        if not verified:
            needle = of_url.lower().replace("https://", "")
            try:
                chats = await dmp.get_recent_chats(of_uid, limit=20)
            except OFProviderError:
                chats = []
            for ch in chats[:20]:
                checked += 1
                blob = json.dumps(ch.get("lastMessage") or ch, ensure_ascii=False).lower()
                if needle in blob and "hai già scoperto" in blob:
                    verified = True
                    break
        rep["READBACK_VERIFY"] = "PASS" if (verified and not q_ok) else ("SKIPPED" if q_ok else ("FAIL" if checked else "UNAVAILABLE"))
        confirmed = accepted and verified
        status = "OK" if confirmed else ("UNVERIFIED" if (accepted or verified or (res is None and not definitive_fail)) else "FAILED")
        marker = (str(mid) if mid else f"crm:{uuid.uuid4().hex[:12]}") if status in ("OK", "UNVERIFIED") else None
        err = None if confirmed else (send_error or ("NOT_VERIFIED" if accepted else "SEND_FAILED"))
        await runs_col.update_one(run_filter, {"$set": {"mass_dm_status": status, "mass_dm_id": marker, "mass_dm_queue_id": mid, "mass_dm_sent_count": sent, "mass_dm_error": err,
                                  "mass_dm_confirmed_at": now_iso() if confirmed else None, "mass_dm_queue_verify": rep["QUEUE_VERIFY"], "mass_dm_readback": rep["READBACK_VERIFY"], "updated_at": now_iso()}})
        await _log(status=("MOCK_DM_CONFIRMED" if is_mock else "MASS_DM_CONFIRMED") if confirmed else ("MASS_DM_NOT_CONFIRMED" if status == "UNVERIFIED" else "MASS_DM_FAILED"), **log_base,
                   mass_dm_id=marker, mass_dm_text=text, target="FAN", user_lists=[fans["id"]], fans_users_count=fans["usersCount"], sent=sent, error_code=err)
        rep.update(MASS_DM_STATUS=status, MASS_DM_MARKER=marker, error_code=err)
        return rep
    finally:
        if gate_opened:
            g = await _restore_gate(dmp, of_uid)
            rep["write_gate"] = g
            rep["WRITE_GATE_RESTORED_TO_FALSE"] = bool(g.get("restored") and g.get("verified_false"))


async def _retry_dm_only(provider: OFProviderAdapter, of_uid: str, model: dict, cand: dict, run: dict, st: dict, eligible: list, is_mock: bool, trigger: str, slot_id: Optional[str]) -> dict:
    """Feed already confirmed for this model+cycle: NO new feed, only the mass DM. Advances the queue on OK."""
    dm = await _mass_dm_step(provider, of_uid, model, run, is_mock, trigger)
    status_ = ("MOCK_CONFIRMED" if is_mock else "POST_CONFIRMED") if dm["advance"] else f"FEED_OK_DM_{dm['MASS_DM_STATUS']}"
    if dm["advance"]:
        pub_info = {"model_id": cand["model_id"], "model_slug": cand["slug"], "model_name": cand["name"], "public_media_id": run.get("public_media_id"), "secret_media_id": run.get("secret_media_id"),
                    "provider_post_id": run.get("feed_post_id"), "action_type": run.get("action_type") or "PUBLISH_NOW", "status": status_, "at": now_iso(), "cycle_number": st["cycle_number"], "slot_id": slot_id}
        await _advance(st, eligible, cand["model_id"], True, pub_info, status_)
    else:
        await set_state(last_error=f"MASS_DM:{dm.get('error_code') or dm['MASS_DM_STATUS']}")
    await _finish_slot(slot_id, status_)
    return {"status": status_, "FEED_STATUS": "OK", "feed_skipped_duplicate": True, "provider_post_id": run.get("feed_post_id"), "model_slug": cand["slug"], "model_name": cand["name"],
            "MASS_DM_STATUS": dm["MASS_DM_STATUS"], "mass_dm": dm, "of_link": run.get("of_link"), "caption": run.get("feed_caption"), "mass_dm_text": run.get("mass_dm_text") or dm.get("text")}


async def process_due_mass_dm(trigger: str = "scheduler") -> Optional[dict]:
    """Scheduler helper: complete the pending (due) mass DM of the current model before any new slot is claimed."""
    st = await get_state()
    q = await queue_view(st)
    cand = q["next"]
    if not cand:
        return None
    run = await get_run(cand["model_id"], st["cycle_number"])
    if not run or run.get("feed_status") != "OK" or run.get("mass_dm_status") not in ("PENDING", "FAILED") or (run.get("dm_due_at") and run["dm_due_at"] > now_iso()):
        return None
    return await run_dm_only(trigger)


async def run_dm_only(trigger: str = "admin") -> dict:
    """Public entry: only the mass DM of the current model (its feed must already be confirmed in this cycle). Lock-protected."""
    owner = str(uuid.uuid4())
    if not await acquire_lock(owner):
        return {"status": "LOCKED"}
    try:
        st = await get_state()
        q = await queue_view(st)
        cand = q["next"]
        if not cand:
            return {"status": "FAILED", "error_code": "NO_ELIGIBLE_MODELS"}
        run = await get_run(cand["model_id"], st["cycle_number"])
        if not run or run.get("feed_status") != "OK":
            return {"status": "FAILED", "error_code": "FEED_NOT_CONFIRMED", "model_slug": cand["slug"]}
        provider = get_provider()
        is_mock = isinstance(provider, MockOFProvider)
        of_uid = await _of_user_id(is_mock)
        model = next(x for x in q["roster"]["models"] if x["id"] == cand["model_id"])
        return await _retry_dm_only(provider, of_uid, model, cand, run, st, q["eligible"], is_mock, trigger, None)
    finally:
        await release_lock(owner)


async def _restore_gate(provider: OFProviderAdapter, of_uid: str) -> dict:
    out = {"restored": False, "verified_false": None, "error": None}
    try:
        await provider.set_write_gate(of_uid, False)
        out["restored"] = True
    except OFProviderError as e:
        out["error"] = e.code
    try:
        out["verified_false"] = (await provider.get_write_gate(of_uid)) is False
    except OFProviderError as e:
        out["error"] = out["error"] or e.code
    await set_state(write_gate_restored=out)
    return out


async def verify_real_post(provider: OFProviderAdapter, of_uid: str, pr, caption: str, of_url: str, medias: list) -> dict:
    """HTTP 200 is not enough: READ the post back and check id, author/account, caption + OF link, media presence."""
    out = {"ok": False, "post_id": pr.post_id, "exists": False, "account_ok": None, "caption_ok": None, "of_link_ok": None, "media_ok": None, "media_count": None, "detail": None}
    if not pr.post_id:
        out["detail"] = "NO_POST_ID"
        return out
    try:
        data = await provider.get_post(of_uid, pr.post_id)
    except OFProviderError as e:
        out["detail"] = f"READ_{e.code}"
        return out
    if not data or str(data.get("id")) != str(pr.post_id):
        out["detail"] = "ID_MISMATCH"
        return out
    out["exists"] = True
    author = data.get("author") or {}
    author_id, author_name = str(author.get("id") or data.get("authorId") or ""), str(author.get("username") or "").lower()
    out["account_ok"] = True if (isinstance(provider, MockOFProvider) or not (author_id or author_name)) else (author_id == str(of_uid) or author_name == connection.EXPECTED_USERNAME)
    import re as _re
    norm = lambda t: _re.sub(r"<[^>]+>|\s+", " ", str(t or "")).strip().lower()
    text = norm(data.get("text") or data.get("rawText") or "")
    first_line = norm(caption.split("\n")[0])
    out["caption_ok"] = bool(text) and (first_line in text or norm(caption)[:60] in text)
    out["of_link_ok"] = of_url.lower().replace("https://", "") in (text + " " + norm(data.get("rawText") or ""))
    media = data.get("media") or data.get("mediaFiles") or []
    out["media_ids"] = _media_ids_from_post(data)
    out["media_count"] = len(media) if isinstance(media, list) else (data.get("mediaCount") or 0)
    out["media_ok"] = (out["media_count"] or 0) >= len(medias)
    out["ok"] = bool(out["exists"] and out["account_ok"] and out["caption_ok"] and out["of_link_ok"] and out["media_ok"])
    if not out["ok"]:
        out["detail"] = "VERIFY_FIELDS_FAILED"
    return out


async def _fail(base: dict, status: str, errors: list, slot_id: Optional[str], error_code: Optional[str] = None, **extra) -> dict:
    code = error_code or (errors[-1].get("reason") if errors else status)
    await set_state(last_error=f"{status}:{code}")
    res = await _log(status=status, **base, **extra, error_code=code, media_errors=errors or None)
    await _finish_slot(slot_id, status)
    return {"status": status, "error_code": code, "model_slug": base.get("model_slug"), "media_errors": errors, "log": res}


async def skip_current(trigger: str = "admin") -> dict:
    owner = str(uuid.uuid4())
    if not await acquire_lock(owner):
        return {"status": "LOCKED"}
    try:
        st = await get_state()
        q = await queue_view(st)
        nxt = q["next"]
        if not nxt:
            return {"status": "FAILED", "error_code": "NO_ELIGIBLE_MODELS"}
        await _advance(st, q["eligible"], nxt["model_id"], False, None, "MANUAL_SKIP")
        res = await _log(status="MANUAL_SKIP", action_type="SKIP", model_id=nxt["model_id"], model_slug=nxt["slug"], model_name=nxt["name"], cycle_number=st["cycle_number"], trigger=trigger)
        return {"status": "MANUAL_SKIP", "skipped": nxt["slug"], "log": res}
    finally:
        await release_lock(owner)


# ----------------------------------------------------------------------------------------------- schedule
def _tz(st: dict):
    try:
        return ZoneInfo(st.get("timezone") or "Europe/Rome")
    except Exception:
        return ZoneInfo("Europe/Rome")


def slots_for_day(st: dict, day: datetime) -> List[dict]:
    tz = _tz(st)
    times = sorted(set((st.get("schedule_times") or DEFAULTS["schedule_times"])[: int(st.get("posts_per_day") or 3)]))
    out = []
    for t in times:
        hh, mm = [int(x) for x in t.split(":")]
        at = day.astimezone(tz).replace(hour=hh, minute=mm, second=0, microsecond=0)
        out.append({"slot_id": f"of_{at.strftime('%Y-%m-%d')}_{t}", "at": at})
    return out


async def schedule_view(st: Optional[dict] = None) -> dict:
    st = st or await get_state()
    tz = _tz(st)
    now = datetime.now(tz)
    today = slots_for_day(st, now)
    done_ids = {d["slot_id"] async for d in slots_col.find({"slot_id": {"$in": [s["slot_id"] for s in today]}, "status": {"$in": ["MOCK_CONFIRMED", "SCHEDULE_CONFIRMED", "POST_CONFIRMED", "RUNNING"]}}, {"slot_id": 1})}
    posts_today = await log_col.count_documents({"status": {"$in": ["MOCK_CONFIRMED", "SCHEDULE_CONFIRMED", "POST_CONFIRMED"]}, "timestamp": {"$gte": now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()}})
    upcoming = [s for s in today if s["at"] > now and s["slot_id"] not in done_ids] or slots_for_day(st, now + timedelta(days=1))
    nxt = upcoming[0] if upcoming else None
    return {"timezone": str(tz), "now": now.isoformat(), "today_slots": [{"slot_id": s["slot_id"], "at": s["at"].isoformat(), "done": s["slot_id"] in done_ids} for s in today], "posts_today": posts_today, "posts_per_day": len(today),
            "next_slot": {"slot_id": nxt["slot_id"], "at": nxt["at"].isoformat()} if nxt else None}


async def due_slot(st: dict) -> Optional[dict]:
    """Slot to prepare now: within [slot - LEAD, slot + GRACE] and not yet claimed. scheduledDate = max(slot time, now + 2')."""
    tz = _tz(st)
    now = datetime.now(tz)
    activated = None
    if st.get("activated_at"):
        try:
            activated = datetime.fromisoformat(st["activated_at"]).astimezone(tz)
        except ValueError:
            activated = None
    for s in slots_for_day(st, now):
        if activated and s["at"] <= activated:
            continue                                                                  # NO catch-up: slots at/before activation are never recovered
        if s["at"] - timedelta(minutes=SLOT_LEAD_MIN) <= now <= s["at"] + timedelta(minutes=SLOT_GRACE_MIN):
            if not await slots_col.find_one({"slot_id": s["slot_id"]}):
                return {"slot_id": s["slot_id"], "scheduled_at": max(s["at"], now + timedelta(minutes=2)).isoformat()}
    return None


async def tick(trigger: str = "scheduler") -> dict:
    """Scheduler entry point: SCHEDULE flow only. Requires env master switch + enabled in DB + operational readiness."""
    await ensure_indexes()
    st = await get_state()
    if not auto_scheduler_enabled():
        return {"status": "AUTO_SCHEDULER_DISABLED"}
    if not st.get("enabled"):
        return {"status": "PAUSED"}
    sch = await schedule_view(st)
    await set_state(next_run=(sch["next_slot"] or {}).get("at"))
    dm = await process_due_mass_dm(trigger)                                   # pending mass DM of the current model first (never a new feed for it)
    if dm and not dm.get("mass_dm", {}).get("advance"):
        return {"status": "MASS_DM_PENDING", **{k: dm.get(k) for k in ("model_slug", "MASS_DM_STATUS")}}
    slot = await due_slot(st)
    if not slot:
        return {"status": "NO_DUE_SLOT", "mass_dm": dm and dm.get("status")}
    return await run("SCHEDULE", trigger, slot_id=slot["slot_id"], scheduled_at=slot["scheduled_at"])


# ----------------------------------------------------------------------------------------------- status
async def status() -> dict:
    await ensure_indexes()
    st = await get_state()
    q = await queue_view(st)
    sch = await schedule_view(st)
    conn = connection.public_view(await connection.saved())
    last = await log_col.find_one({"status": {"$nin": ["SKIP_DUPLICATE_SLOT"]}}, {"_id": 0}, sort=[("timestamp", -1)])
    nxt = q["next"]
    ros = q["roster"]
    cur_run = await get_run(nxt["model_id"], st["cycle_number"]) if nxt else None
    autopilot = "PAUSED" if not st["enabled"] else ("ACTIVE" if auto_scheduler_enabled() else "READY")
    return {
        "OF_AUTOPILOT_STATUS": autopilot, "enabled": bool(st["enabled"]), "AUTO_SCHEDULER_ENABLED": auto_scheduler_enabled(), "MOCK_MODE": mock_enabled(), "mock_mode": mock_enabled(),
        "OF_REAL_POSTING_ENABLED": connection.real_posting_enabled(), "REAL_POSTING": "ON" if connection.real_posting_enabled() else "OFF", "AUTO_SCHEDULER": "ON" if auto_scheduler_enabled() else "OFF",
        "PROVIDER": conn.get("PROVIDER"), "CONNECTION_STATUS": conn.get("CONNECTION_STATUS"), "ACCOUNT_USERNAME": conn.get("ACCOUNT_USERNAME"), "ACCOUNT_STATUS": conn.get("ACCOUNT_STATUS"), "connection": conn,
        "THE_ONLY_API_REAL_WRITE_CALLS": toa.CALLS["write"], "REAL_WRITE_BREAKDOWN": {k: toa.CALLS[k] for k in ("gate", "upload", "create")},
        "REAL_TEST_MODE": real_test_mode(), "REAL_TEST_MAX_POSTS": real_test_max_posts(), "TOTAL_REAL_POSTS_CREATED": await real_posts_created(), "write_gate_restored": st.get("write_gate_restored"),
        "OF_REAL_POST_DONE": await log_col.count_documents({"status": {"$in": ["POST_CONFIRMED", "SCHEDULE_CONFIRMED"]}, "mock": {"$ne": True}}) > 0,
        "OF_MASS_DM_MOCK": mass_dm_mock(), "OF_MASS_DM_ENABLED": mass_dm_enabled(), "OF_REAL_MASS_DM_SENT": await runs_col.count_documents({"mock": {"$ne": True}, "mass_dm_id": {"$nin": [None, ""]}}) > 0,
        "THE_ONLY_API_REAL_MASS_DM_CALLS": toa.CALLS["mass_dm"], "current_run": _run_view(cur_run), "MASS_DM_TARGET": "FAN", "CATCH_UP_ENABLED": False, "activated_at": st.get("activated_at"),
        "NEXT_MODEL": nxt["slug"] if nxt else None,
        "closed_runs": [{"model_slug": r.get("model_slug"), "feed_post_id": r.get("feed_post_id"), "previous_mass_dm_status": r.get("previous_mass_dm_status"), "provider_response": r.get("provider_response"),
                         "readback_confirmed": r.get("readback_confirmed"), "closed_at": r.get("closed_at")}
                        async for r in runs_col.find({"closed_by_admin": True, "previous_mass_dm_status": {"$exists": True}}, {"_id": 0}).sort("closed_at", -1).limit(5)],
        "queue": {"position": q["position"], "total": q["n_eligible"], "cycle_number": st["cycle_number"], "done_in_cycle": q["n_done_in_cycle"],
                  "current": {"slug": nxt["slug"], "name": nxt["name"], "n_public": nxt["n_public"], "n_secret": nxt["n_secret"], "of_url": nxt["of_url"]} if nxt else None,
                  "order": [{"slug": r["slug"], "name": r["name"], "done": r["model_id"] in set(st.get("cycle_done") or [])} for r in q["eligible"]],
                  "skipped_no_public": ros["no_public"], "skipped_no_secret": ros["no_secret"], "skipped_no_of_link": ros["no_of"], "excluded": ros["excluded"], "rejected_media": ros["rejected"]},
        "schedule": sch, "settings": {k: st[k] for k in ("posts_per_day", "schedule_times", "timezone", "use_ai_copy")},
        "last_published": st.get("last_published"), "last_event": last, "last_run": st.get("last_run"), "last_success": st.get("last_success"), "last_error": st.get("last_error"), "next_run": (sch["next_slot"] or {}).get("at"),
        "next": {"model": nxt["name"] if nxt else None, "slot": sch["next_slot"]},
    }


def _run_view(run: Optional[dict]) -> dict:
    """Admin-minimal view of the current model's run: FEED OK/PENDING/FAILED · MASS MESSAGE OK/PENDING/FAILED (+ DISABLED/MOCK_ONLY/SKIPPED/UNVERIFIED)."""
    if not run:
        return {"FEED_STATUS": "PENDING", "MASS_DM_STATUS": "PENDING", "FAN_REFRESH_STATUS": "PENDING", "TARGET": "FAN", "FAN_COUNT": None, "AUDIENCE": None, "model_slug": None}
    fr = run.get("subscriber_refresh_status")
    return {"FEED_STATUS": run.get("feed_status") or "PENDING", "MASS_DM_STATUS": run.get("mass_dm_status") or "PENDING", "model_slug": run.get("model_slug"), "cycle_number": run.get("cycle_number"),
            "feed_post_id": run.get("feed_post_id"), "mass_dm_id": run.get("mass_dm_id"), "mass_dm_error": run.get("mass_dm_error"), "mass_dm_attempts": run.get("mass_dm_attempts"), "mock": run.get("mock"),
            "dm_due_at": run.get("dm_due_at"), "FAN_REFRESH_STATUS": ("OK" if fr == "OK" else "RUNNING" if fr == "RUNNING" else "FAILED" if fr else "PENDING"), "fan_refresh_detail": fr,
            "TARGET": "FAN", "FAN_COUNT": run.get("of_fans_users_count"), "AUDIENCE": run.get("of_fans_users_count") if run.get("of_fans_users_count") is not None else run.get("mass_dm_recipients"), "cached_total": run.get("cached_total"), "cached_active": run.get("cached_active"), "cached_expired": run.get("cached_expired"),
            "last_refreshed_at": run.get("last_refreshed_at"), "sent_count": run.get("mass_dm_sent_count")}


# ----------------------------------------------------------------------------------------------- MASS DM TEST from an EXISTING confirmed feed post (DM-only, never a new feed)
REAL_MASS_DM_TEST_MAX = 1            # hard cap of REAL mass DMs this route may ever have produced (DB-level, any post/model)


def _run_key(post_id: str) -> str:
    return f"post:{post_id}"         # of_model_runs key for DM-only runs (never collides with cycle numbers)


async def real_mass_dm_sent_count() -> int:
    return await runs_col.count_documents({"mock": {"$ne": True}, "mass_dm_id": {"$nin": [None, ""]}})


async def mass_dm_from_post(model_slug: str, post_id: str, execute: bool = False, trigger: str = "admin") -> dict:
    """READ-ONLY pre-checks on an existing feed post (account, model, id, media_count=2, vault ids, OF link, audience, gate false, no DM yet, scheduler off,
    hard cap) -> copy preview. With execute=True and ALL checks PASS: gate on -> ONE mass message to ALL subscribers -> READ verify -> state saved in
    of_model_runs -> gate off (finally) + READ verify. Any FAIL -> STOP, zero writes, never another model, never a new feed."""
    post_id = str(post_id).strip()
    rep = {"mode": "EXECUTE" if execute else "DRY_RUN", "checks": {}, "MODEL": model_slug, "SOURCE_POST_ID": post_id, "NEW_FEED_CREATED": False, "WRITE_GATE_ENABLED": False,
           "REAL_MASS_DM_CREATE": None, "MASS_DM_ID_RECEIVED": False, "REAL_MASS_DM_VERIFY": None, "REAL_MASS_DM_CONFIRMED": None, "WRITE_GATE_RESTORED_TO_FALSE": None,
           "OF_AUTO_SCHEDULER_ENABLED": auto_scheduler_enabled(), "SECOND_MASS_DM_SENT": False}
    ck = rep["checks"]
    owner = str(uuid.uuid4())
    if not await acquire_lock(owner):
        return {**rep, "status": "LOCKED"}
    provider = of_uid = None
    gate_opened = False
    try:
        provider = get_provider()
        is_mock = isinstance(provider, MockOFProvider)
        rep["mock"] = is_mock
        of_uid = await _of_user_id(is_mock)
        ck["OF_AUTO_SCHEDULER_ENABLED=false"] = not auto_scheduler_enabled()
        ck["OF_USER_ID_DISCOVERED"] = bool(of_uid)
        # account (live)
        conn = connection.public_view(await connection.saved()) if is_mock else await connection.discover(check_schedules=False)
        if is_mock:
            conn = {"CONNECTION_STATUS": "CONNECTED", "ACCOUNT_STATUS": "HEALTHY", "ACCOUNT_USERNAME": connection.EXPECTED_USERNAME, **({} if not conn else {})}
        rep["ACCOUNT_USERNAME"], rep["ACCOUNT_HEALTH"] = conn.get("ACCOUNT_USERNAME"), conn.get("ACCOUNT_STATUS")
        ck["ACCOUNT=latosegreto"] = (conn.get("ACCOUNT_USERNAME") or "").lower() == connection.EXPECTED_USERNAME and conn.get("CONNECTION_STATUS") == "CONNECTED"
        ck["ACCOUNT_HEALTH=HEALTHY"] = conn.get("ACCOUNT_STATUS") == "HEALTHY"
        # gate currently false
        try:
            gate_before = await provider.get_write_gate(of_uid) if of_uid else None
        except OFProviderError as e:
            gate_before = f"ERR_{e.code}"
        rep["WRITE_GATE_BEFORE"] = gate_before
        ck["WRITE_GATE_BEFORE=false"] = gate_before is False
        # model
        ros = await roster()
        row = next((r for r in ros["rows"] if r["slug"] == model_slug), None)
        model = next((m for m in ros["models"] if m.get("slug") == model_slug), None)
        ck["MODEL_FOUND_PUBLISHED"] = bool(row and model)
        of_url = row["of_url"] if row else None
        ck["MODEL_OF_LINK_VALID"] = bool(of_url)
        rep["OF_LINK"] = of_url
        # DM gates (provider selection) + hard cap + no previous DM for this post
        dmp, reason = _dm_provider(provider, is_mock)
        ck["MASS_DM_ENABLED_FOR_THIS_PROVIDER"] = dmp is not None
        rep["MASS_DM_GATE"] = reason or "OK"
        sent = await real_mass_dm_sent_count()
        rep["TOTAL_REAL_MASS_DM_SENT"] = sent
        ck[f"TOTAL_REAL_MASS_DM_SENT<{REAL_MASS_DM_TEST_MAX}"] = is_mock or sent < REAL_MASS_DM_TEST_MAX
        prev = await runs_col.find_one({"feed_post_id": post_id, "$or": [{"mass_dm_id": {"$nin": [None, ""]}}, {"mass_dm_status": {"$in": ["OK", "UNVERIFIED", "SENDING"]}}]}, {"_id": 0})
        ck["NO_MASS_DM_ALREADY_SENT_FOR_POST"] = prev is None                              # any run (cycle or test) that already sent a DM for this post -> STOP
        # source post read-back
        post, media_ids, text = None, [], ""
        if of_uid:
            try:
                post = await provider.get_post(of_uid, post_id)
            except OFProviderError as e:
                rep["SOURCE_POST_ERROR"] = e.code
        ck["SOURCE_POST_FOUND"] = bool(post) and str((post or {}).get("id")) == post_id
        if post:
            author = post.get("author") or {}
            a_id, a_name = str(author.get("id") or post.get("authorId") or ""), str(author.get("username") or "").lower()
            ck["SOURCE_POST_ACCOUNT=latosegreto"] = (a_id == str(of_uid)) or (a_name == connection.EXPECTED_USERNAME) or (is_mock and not (a_id or a_name))
            media = post.get("media") or post.get("mediaFiles") or []
            media_ids = _media_ids_from_post(post)
            rep["SOURCE_MEDIA_COUNT"] = len(media) if isinstance(media, list) else (post.get("mediaCount") or 0)
            ck["SOURCE_MEDIA_COUNT=2"] = rep["SOURCE_MEDIA_COUNT"] == 2
            ck["VAULT_MEDIA_IDS_FOUND"] = len(media_ids) == 2
            import re as _re
            text = _re.sub(r"<[^>]+>", " ", str(post.get("rawText") or post.get("text") or ""))
            text = _re.sub(r"[ \t]+", " ", text).strip()
            ck["SOURCE_POST_BELONGS_TO_MODEL(OF link in caption)"] = bool(of_url) and of_url.lower().replace("https://", "") in text.lower()
        else:
            ck["SOURCE_POST_ACCOUNT=latosegreto"] = ck["SOURCE_MEDIA_COUNT=2"] = ck["VAULT_MEDIA_IDS_FOUND"] = ck["SOURCE_POST_BELONGS_TO_MODEL(OF link in caption)"] = False
        rep["VAULT_MEDIA_IDS_MASKED"] = [f"…{str(x)[-4:]}" for x in media_ids]
        # TARGET = OnlyFans native "Fans" list (READ, resolved dynamically): FANS_LIST_FOUND, usersCount > 0
        fans = None
        if dmp is not None and of_uid:
            try:
                fans = await dmp.get_fans_list(of_uid)
            except OFProviderError as e:
                rep["FANS_LIST_ERROR"] = e.code
            try:
                rep["SUBSCRIBERS_COUNT"] = await dmp.subscribers_count(of_uid)
            except OFProviderError:
                rep["SUBSCRIBERS_COUNT"] = None
        rep["ONLYFANS_UI_TARGET"], rep["TARGET"] = "FAN", "FAN"
        rep["FANS_LIST_FOUND"], rep["FANS_LIST_ID"], rep["OF_FANS_USERS_COUNT"] = bool(fans), (fans or {}).get("id"), (fans or {}).get("usersCount")
        rep["FANS_DRY_RUN_SUPPORTED"] = bool(getattr(dmp, "FANS_DRY_RUN_SUPPORTED", False)) if dmp is not None else None
        ck["FANS_LIST_FOUND(type=fans)"] = bool(fans)
        ck["FANS_USERS_COUNT>0"] = bool(fans) and isinstance(fans.get("usersCount"), int) and fans["usersCount"] > 0
        # copy (different from the feed text read back from the post)
        cap = None
        if model and of_url:
            st = await get_state()
            cap = await build_dm_caption(model, of_url, 1, text, use_ai=st.get("use_ai_copy", True))
            rep["MASS_DM_TEXT"], rep["MASS_DM_COPY_SOURCE"] = cap["text"], cap["source"]
            ck["MASS_DM_COPY_DIFFERENT_FROM_FEED"] = bool(cap["different_from_feed"]) and cap["text"].strip() != text.strip()
            ck["MASS_DM_OF_LINK_VALID"] = cap["text"].count("http") == 1 and cap["text"].rstrip().endswith(of_url) and "onlyfans.com/latosegreto" not in cap["text"]
            ck["MASS_DM_ITALIAN_FORMAT"] = cap["text"].startswith("👀 Hai già scoperto ") and "✨ LATO PUBBLICO" in cap["text"] and "🔥 LATO SEGRETO" in cap["text"] and "❤️‍🔥 Scoprila qui:" in cap["text"]
        else:
            ck["MASS_DM_COPY_DIFFERENT_FROM_FEED"] = ck["MASS_DM_OF_LINK_VALID"] = ck["MASS_DM_ITALIAN_FORMAT"] = False
        ck["MASS_DM_MEDIA_PUBLIC_SECRET(2 ids, feed order)"] = len(media_ids) == 2
        rep["ALL_PRECHECKS_PASS"] = all(ck.values())
        if not execute:
            rep["status"] = "DRY_RUN_PASS" if rep["ALL_PRECHECKS_PASS"] else "DRY_RUN_FAIL"
            return rep
        if not rep["ALL_PRECHECKS_PASS"]:
            rep["status"] = "STOPPED_PRECHECK"
            rep["failed_checks"] = [k for k, v in ck.items() if not v]
            await _log(status="MASS_DM_TEST_STOPPED", action_type="MASS_DM_TEST", model_slug=model_slug, source_post_id=post_id, mock=is_mock, trigger=trigger, error_code="PRECHECK_FAIL", failed_checks=rep["failed_checks"])
            return rep
        # ---------------- the ONE write: shared CRM flow (gate -> refresh -> dry_run -> SENDING -> send -> read-back -> gate off)
        run_key = _run_key(post_id)
        run_filter = {"model_id": model["id"], "cycle_number": run_key}
        await runs_col.update_one(run_filter, {"$set": {"model_slug": model_slug, "model_name": row["name"], "mock": is_mock, "action_type": "MASS_DM_TEST", "feed_status": "OK", "feed_post_id": post_id,
                                  "feed_media_ids": media_ids, "feed_caption": text, "of_link": of_url, "mass_dm_text": cap["text"], "mass_dm_copy_source": cap["source"], "mass_dm_different_from_feed": True,
                                  "mass_dm_status": "PENDING", "target": "FAN", "updated_at": now_iso()},
                                  "$setOnInsert": {"id": str(uuid.uuid4()), "model_id": model["id"], "cycle_number": run_key, "created_at": now_iso(), "mass_dm_attempts": 0}}, upsert=True)
        if not is_mock and await real_mass_dm_sent_count() >= REAL_MASS_DM_TEST_MAX:                  # hard cap re-check
            rep["status"], rep["REAL_MASS_DM_CREATE"] = "BLOCKED_HARD_CAP", "SKIPPED"
            await runs_col.update_one(run_filter, {"$set": {"mass_dm_status": "FAILED", "mass_dm_error": "HARD_CAP", "updated_at": now_iso()}})
            return rep
        log_base = dict(action_type="MASS_DM_TEST", model_id=model["id"], model_slug=model_slug, model_name=row["name"], trigger=trigger, mock=is_mock, of_link=of_url, feed_post_id=post_id, media_ids=media_ids)
        res = await _execute_mass_dm(dmp, provider, of_uid, run_filter, cap["text"], media_ids, of_url, is_mock, log_base)
        rep.update({k: res.get(k) for k in ("WRITE_GATE_ENABLED", "REAL_MASS_DM_CREATE", "REAL_MASS_DM_SENT_COUNT", "QUEUE_VERIFY", "READBACK_VERIFY", "MASS_DM_MARKER", "MASS_DM_ID", "error_code", "refresh",
                                           "SUBSCRIBERS_COUNT", "write_gate", "WRITE_GATE_RESTORED_TO_FALSE", "FANS_LIST_FOUND", "FANS_LIST_ID", "OF_FANS_USERS_COUNT", "FANS_DRY_RUN_SUPPORTED")})
        rep["MASS_DM_TARGET_PAYLOAD"] = {"userLists": [rep.get("FANS_LIST_ID")], "excludedLists": []}
        rep["REAL_MASS_DM_VERIFY"] = "PASS" if res["MASS_DM_STATUS"] == "OK" else "FAIL"
        rep["REAL_MASS_DM_CONFIRMED"] = "PASS" if res["MASS_DM_STATUS"] == "OK" else "FAIL"
        rep["MASS_DM_ID_RECEIVED"] = bool(res.get("MASS_DM_ID"))
        st_map = {"OK": "MASS_DM_CONFIRMED", "UNVERIFIED": "MASS_DM_UNVERIFIED", "FAILED": "MASS_DM_FAILED", "PENDING": "MASS_DM_PENDING"}
        err = res.get("error_code") or ""
        if err.startswith("REFRESH_"):
            rep["status"] = "ABORTED_" + err
        elif err in ("FANS_LIST_NOT_FOUND", "FANS_LIST_EMPTY"):
            rep["status"] = "ABORTED_" + err
        else:
            rep["status"] = st_map.get(res["MASS_DM_STATUS"], res["MASS_DM_STATUS"])
        if rep["REAL_MASS_DM_CREATE"] is None:
            rep["REAL_MASS_DM_CREATE"] = "SKIPPED"
        return rep
    finally:
        if gate_opened and provider is not None:
            g = await _restore_gate(provider, of_uid)
            rep["write_gate"] = g
            rep["WRITE_GATE_RESTORED_TO_FALSE"] = bool(g.get("restored") and g.get("verified_false"))
        rep["TOTAL_REAL_MASS_DM_SENT"] = await real_mass_dm_sent_count()
        rep["OF_AUTO_SCHEDULER_ENABLED"] = auto_scheduler_enabled()
        await release_lock(owner)


MASS_DM_JOBS: Dict[str, dict] = {}     # post_id -> last result of a background execute (process-local); the durable state is of_model_runs


async def mass_dm_from_post_background(model_slug: str, post_id: str, trigger: str = "admin") -> None:
    try:
        rep = await mass_dm_from_post(model_slug, post_id, execute=True, trigger=trigger)
    except Exception as e:                                  # noqa: BLE001 — never lose the outcome of a real send
        rep = {"status": "INTERNAL_ERROR", "error": type(e).__name__}
    rep["finished_at"] = now_iso()
    MASS_DM_JOBS[str(post_id)] = rep
    await runs_col.update_one({"cycle_number": _run_key(str(post_id))}, {"$set": {"last_result": {k: v for k, v in rep.items() if k != "MASS_DM_TEXT"}, "updated_at": now_iso()}})


async def mass_dm_job_view(post_id: str) -> dict:
    run = await runs_col.find_one({"cycle_number": _run_key(str(post_id))}, {"_id": 0})
    return {"job": MASS_DM_JOBS.get(str(post_id)), "run": run}


async def close_mass_dm_run(post_id: str, reason: str, trigger: str = "admin") -> dict:
    """Admin closure of a DM-only run (key post:<id>) confirmed by real read-back: mass_dm_status -> OK, provider error history preserved,
    marker kept (duplicate protection stays). ZERO provider writes. If the run belongs to the current queue candidate (cycle run), the queue advances."""
    key = _run_key(str(post_id))
    run = await runs_col.find_one({"cycle_number": key}, {"_id": 0})
    if not run:
        return {"status": "NOT_FOUND", "post_id": post_id}
    prev_status, prev_err = run.get("mass_dm_status"), run.get("mass_dm_error")
    if prev_status == "OK":
        return {"status": "ALREADY_OK", "post_id": post_id, "model_slug": run.get("model_slug"), "mass_dm_id": run.get("mass_dm_id")}
    marker = run.get("mass_dm_id") or f"crm:closed:{uuid.uuid4().hex[:8]}"
    await runs_col.update_one({"cycle_number": key}, {"$set": {"mass_dm_status": "OK", "mass_dm_id": marker, "closed_by_admin": True, "close_reason": reason, "closed_at": now_iso(),
                              "provider_response": prev_err or prev_status, "previous_mass_dm_status": prev_status, "readback_confirmed": True, "mass_dm_confirmed_at": now_iso(), "updated_at": now_iso()}})
    await _log(status="MASS_DM_CLOSED_BY_READBACK", action_type="MASS_DM_TEST", model_id=run.get("model_id"), model_slug=run.get("model_slug"), model_name=run.get("model_name"), trigger=trigger, mock=run.get("mock"),
               feed_post_id=str(post_id), mass_dm_id=marker, provider_response=prev_err or prev_status, readback_confirmed=True, close_reason=reason)
    st = await get_state()
    q = await queue_view(st)
    cur = q["next"]
    advanced = False
    if cur and cur["model_id"] == run.get("model_id"):
        # The model is still the queue candidate: its cycle run becomes FEED OK (the post was verified by the DM-only pre-checks) + MASS DM OK,
        # so the scheduler can NEVER produce a second feed/DM for it; the queue moves to the next valid model (nothing is published now).
        cyc = await get_run(cur["model_id"], st["cycle_number"]) or {}
        await upsert_run(cur["model_id"], st["cycle_number"], model_slug=cur["slug"], model_name=cur["name"], mock=run.get("mock"), action_type=cyc.get("action_type") or "PUBLISH_NOW",
                         feed_status="OK", feed_post_id=cyc.get("feed_post_id") or str(post_id), feed_confirmed_at=cyc.get("feed_confirmed_at") or now_iso(), of_link=run.get("of_link"),
                         mass_dm_status="OK", mass_dm_id=cyc.get("mass_dm_id") or marker, closed_by_admin=True, close_reason=reason, readback_confirmed=True, mass_dm_confirmed_at=now_iso())
        pub_info = {"model_id": cur["model_id"], "model_slug": cur["slug"], "model_name": cur["name"], "provider_post_id": cyc.get("feed_post_id") or str(post_id), "action_type": cyc.get("action_type") or "PUBLISH_NOW",
                    "status": "POST_CONFIRMED", "at": now_iso(), "cycle_number": st["cycle_number"], "slot_id": None}
        await _advance(st, q["eligible"], cur["model_id"], True, pub_info, "POST_CONFIRMED")
        advanced = True
    st = await get_state()
    q = await queue_view(st)
    return {"status": "CLOSED", "post_id": str(post_id), "model_slug": run.get("model_slug"), "previous_mass_dm_status": prev_status, "provider_response": prev_err or prev_status, "readback_confirmed": True,
            "mass_dm_id": marker, "queue_advanced": advanced, "NEXT_MODEL": (q["next"] or {}).get("slug"), "writes": 0}
