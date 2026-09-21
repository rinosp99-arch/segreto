"""X engine — INDEPENDENT persistent circular queue (collections x_*), two media cursors per model (PUBLIC / SECRET),
slot idempotency (x_YYYY-MM-DD_HH:MM), DB lock, PUBLIC-first pairing, photo+photo SINGLE_POST or THREAD (any video).
A THREAD is ONE logical publication: one rotation item, one slot, one queue advance.

Collections: x_autopilot_state · x_model_media_state · x_autopilot_log · x_autopilot_slots · x_autopilot_locks.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from database import db

from . import adapter as xapi
from .copy import build_copy, italy_mode_env
from .media import roster

state_col = db["x_autopilot_state"]
media_state_col = db["x_model_media_state"]
log_col = db["x_autopilot_log"]
slots_col = db["x_autopilot_slots"]
locks_col = db["x_autopilot_locks"]

DEFAULTS = {"enabled": False, "posts_per_day": 3, "schedule_times": ["12:30", "18:30", "22:00"], "timezone": "Europe/Rome", "use_ai_copy": True, "italy_audience_mode": None,
            "cycle_number": 1, "cycle_done": [], "last_position": -1, "current_position": 0, "current_model_id": None, "last_published": None, "last_processed": None,
            "last_run": None, "last_success": None, "next_run": None, "last_slot": None}
MAX_ATTEMPTS_PER_SIDE = 3
LOCK_TTL_S = 180
SLOT_GRACE_MIN = 90
SKIP_STATUSES = ("SKIPPED_NO_PUBLIC_MEDIA", "SKIPPED_NO_SECRET_MEDIA", "SKIPPED_NO_OF_LINK", "SKIPPED_NOT_X_SAFE")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def auto_scheduler_enabled() -> bool:
    return os.environ.get("X_AUTO_SCHEDULER_ENABLED", "false").lower() in ("1", "true", "yes")


def italy_mode(st: dict) -> bool:
    v = st.get("italy_audience_mode")
    return italy_mode_env() if v is None else bool(v)


async def ensure_indexes():
    await slots_col.create_index("slot_id", unique=True)
    await locks_col.create_index("id", unique=True)
    await media_state_col.create_index("model_id", unique=True)
    await log_col.create_index([("timestamp", -1)])
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
    if all(i in done for i in ids):                     # cycle complete -> restart from the first
        cycle += 1
        done = []
        pos = -1
    nxt = _next_from(eligible, set(done), pos)
    upd = {"cycle_done": done, "last_position": pos, "cycle_number": cycle, "current_position": len([i for i in ids if i in done]) + (1 if nxt else 0),
           "current_model_id": nxt["model_id"] if nxt else None, "last_processed": {"model_id": model_id, "status": processed_status, "at": now_iso()}}
    if published:
        upd["last_published"] = published_info
        upd["last_success"] = now_iso()
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


def candidate_pairs(seqs: dict) -> List[tuple]:
    """Priority 1: photo+photo (SINGLE_POST). Priority 2: any pair involving a video (THREAD). Bounded attempts per side."""
    pub, sec = seqs["public"][:MAX_ATTEMPTS_PER_SIDE + 2], seqs["secret"][:MAX_ATTEMPTS_PER_SIDE + 2]
    photo_pairs = [(p, s) for p in pub if p["type"] == "photo" for s in sec if s["type"] == "photo"]
    other = [(p, s) for p in pub for s in sec if (p, s) not in photo_pairs]
    return (photo_pairs + other)[: MAX_ATTEMPTS_PER_SIDE * MAX_ATTEMPTS_PER_SIDE]


async def mark_media_used(model_id: str, public: List[dict], secret: List[dict], pub: dict, sec: Optional[dict], cycle: int):
    upd = {"model_id": model_id, "last_public_media_id": pub["id"], "public_media_index": [x["id"] for x in public].index(pub["id"]), "last_published_at": now_iso(), "cycle_last_used": cycle}
    if sec:
        upd.update({"last_secret_media_id": sec["id"], "secret_media_index": [x["id"] for x in secret].index(sec["id"])})
    await media_state_col.update_one({"model_id": model_id}, {"$set": upd}, upsert=True)


async def _log(**fields):
    doc = {"id": str(uuid.uuid4()), "timestamp": now_iso(), **fields}
    await log_col.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _finish_slot(slot_id: Optional[str], status: str):
    if slot_id:
        await slots_col.update_one({"slot_id": slot_id}, {"$set": {"status": status, "finished_at": now_iso()}})


# ----------------------------------------------------------------------------------------------- pipeline
async def _prepare(cand: dict, model: dict, st: dict, slot_id: Optional[str]) -> dict:
    seqs = await pick_sequences(cand["model_id"], cand["public"], cand["secret"])
    cp = await build_copy(model, cand["of_url"], st["cycle_number"], use_ai=st["use_ai_copy"], italy=italy_mode(st))
    return {"seqs": seqs, "pairs": candidate_pairs(seqs), "copy": cp}


async def preview(slot_id: Optional[str] = None) -> dict:
    """ANTEPRIMA PROSSIMO POST: no publish, no state change, no adapter call."""
    st = await get_state()
    q = await queue_view(st)
    cand = q["next"]
    if not cand:
        return {"status": "NO_ELIGIBLE_MODELS"}
    model = next(x for x in q["roster"]["models"] if x["id"] == cand["model_id"])
    prep = await _prepare(cand, model, st, slot_id)
    pub, sec = prep["pairs"][0] if prep["pairs"] else (None, None)
    sch = await schedule_view(st)
    return {"status": "PREVIEW", "model": cand["name"], "model_slug": cand["slug"], "public": pub, "secret": sec, "media_order": ["PUBLIC", "SECRET"],
            "format": xapi.post_format(pub, sec) if pub and sec else None, "text": prep["copy"]["text"], "reply_text": prep["copy"]["reply_text"], "of_url": cand["of_url"],
            "hashtags": prep["copy"]["hashtags"], "copy_source": prep["copy"]["source"], "x_length": prep["copy"]["x_length"], "cycle_number": st["cycle_number"],
            "slot": sch["next_slot"], "position": q["position"], "total": q["n_eligible"]}


async def publish_next(trigger: str = "scheduler", slot_id: Optional[str] = None, dry_run: bool = False) -> dict:
    """lock -> slot claim -> next model -> PUBLIC+SECRET pair (cursors) -> copy IT + OF link -> adapter (SINGLE_POST | THREAD) -> advance ONCE."""
    if dry_run:
        return {**(await preview(slot_id)), "status": "DRY_RUN"}
    owner = str(uuid.uuid4())
    if not await acquire_lock(owner):
        return {"status": "LOCKED", "detail": "pubblicazione già in corso"}
    try:
        st = await get_state()
        if slot_id:
            try:
                await slots_col.insert_one({"slot_id": slot_id, "claimed_at": now_iso(), "trigger": trigger, "status": "RUNNING"})
            except DuplicateKeyError:
                await _log(status="SKIP_DUPLICATE_SLOT", slot_id=slot_id, trigger=trigger, cycle_number=st["cycle_number"])
                return {"status": "SKIP_DUPLICATE_SLOT", "slot_id": slot_id}
        await set_state(last_run=now_iso(), last_slot=slot_id or st.get("last_slot"))
        q = await queue_view(st)
        eligible = q["eligible"]
        if not eligible:
            res = await _log(status="FAILED", error_code="NO_ELIGIBLE_MODELS", trigger=trigger, slot_id=slot_id, cycle_number=st["cycle_number"])
            await _finish_slot(slot_id, "FAILED")
            return {"status": "FAILED", "error_code": "NO_ELIGIBLE_MODELS", "log": res}
        adapter = xapi.get_adapter()
        is_mock = isinstance(adapter, xapi.MockXAdapter)
        result = None
        for _ in range(len(eligible)):                 # bounded: at most one pass over the eligible list, no infinite loop
            st = await get_state()
            cand = _next_from(eligible, set(st.get("cycle_done") or []), st.get("last_position", -1))
            if not cand:
                break
            model = next(x for x in q["roster"]["models"] if x["id"] == cand["model_id"])
            prep = await _prepare(cand, model, st, slot_id)
            cp = prep["copy"]
            errors, main_res, reply_res, used, fmt, infra = [], None, None, None, None, False
            for pub, sec in prep["pairs"]:
                assert pub["side"] == "PUBLIC" and sec["side"] == "SECRET"
                try:
                    pub_mid = await adapter.upload_media(pub)
                except xapi.XError as e:
                    errors.append({"side": "PUBLIC", "media_id": pub["id"], "error_code": e.code, "detail": e.description[:160]})
                    infra = e.code in ("NOT_CONNECTED", "INVALID_TOKEN")
                    if infra:
                        break
                    continue
                try:
                    sec_mid = await adapter.upload_media(sec)
                except xapi.XError as e:
                    errors.append({"side": "SECRET", "media_id": sec["id"], "error_code": e.code, "detail": e.description[:160]})
                    infra = e.code in ("NOT_CONNECTED", "INVALID_TOKEN")
                    if infra:
                        break
                    continue
                payloads = xapi.build_payloads(model, pub, sec, cp["text"], cp["reply_text"], slot_id, st["cycle_number"])
                fmt = payloads["format"]
                main = {**payloads["main"], "media_ids": [pub_mid] + ([sec_mid] if fmt == "SINGLE_POST" else [])}
                try:
                    main_res = await adapter.create_post(main)
                except xapi.XError as e:
                    errors.append({"side": "MAIN", "error_code": e.code, "detail": e.description[:160]})
                    infra = e.code in ("NOT_CONNECTED", "INVALID_TOKEN")
                    break
                used = (pub, sec)
                if fmt == "THREAD":
                    reply = {**payloads["reply"], "media_ids": [sec_mid], "in_reply_to": main_res["id"]}
                    try:
                        reply_res = await adapter.create_post(reply)
                    except xapi.XError as e:
                        errors.append({"side": "REPLY", "media_id": sec["id"], "error_code": "THREAD_SECRET_FAILED", "detail": e.description[:160]})
                break
            if main_res:
                pub, sec = used
                partial = fmt == "THREAD" and reply_res is None
                status_ = "PARTIAL_FAILED" if partial else ("MOCK_PREPARED" if is_mock else "PUBLISHED")
                await mark_media_used(cand["model_id"], cand["public"], cand["secret"], pub, None if partial else sec, st["cycle_number"])
                info = {"model_id": cand["model_id"], "model_slug": cand["slug"], "model_name": cand["name"], "public_media_id": pub["id"], "secret_media_id": sec["id"],
                        "public_media_type": pub["type"], "secret_media_type": sec["type"], "format": fmt, "x_post_id": main_res.get("id"), "x_reply_id": (reply_res or {}).get("id"),
                        "of_url": cand["of_url"], "at": now_iso(), "cycle_number": st["cycle_number"], "slot_id": slot_id}
                await _advance(st, eligible, cand["model_id"], not partial, info, status_)     # ONE advance per model (thread = one item)
                res = await _log(status=status_, **{k: v for k, v in info.items() if k != "at"}, error_code="THREAD_SECRET_FAILED" if partial else None, trigger=trigger,
                                 copy_source=cp["source"], media_errors=errors or None, mock=is_mock)
                await _finish_slot(slot_id, status_)
                result = {"status": status_, **info, "text": cp["text"], "hashtags": cp["hashtags"], "copy_source": cp["source"], "media_order": ["PUBLIC", "SECRET"], "media_errors": errors, "log": res}
                break
            if infra:
                res = await _log(status="FAILED", model_id=cand["model_id"], model_slug=cand["slug"], model_name=cand["name"], cycle_number=st["cycle_number"], error_code=errors[-1]["error_code"], media_errors=errors, trigger=trigger, slot_id=slot_id)
                await _finish_slot(slot_id, "FAILED")
                result = {"status": "FAILED", "error_code": errors[-1]["error_code"], "model_slug": cand["slug"], "log": res}
                break
            # no valid pair for this model -> skip (which side failed) and continue with the next model
            sides = {e.get("side") for e in errors}
            skip_status = "SKIPPED_NOT_X_SAFE" if "MAIN" in sides else ("SKIPPED_NO_SECRET_MEDIA" if sides == {"SECRET"} else ("SKIPPED_NO_PUBLIC_MEDIA" if sides == {"PUBLIC"} else "SKIPPED_NOT_X_SAFE"))
            await _advance(st, eligible, cand["model_id"], False, None, skip_status)
            await _log(status=skip_status, model_id=cand["model_id"], model_slug=cand["slug"], model_name=cand["name"], cycle_number=st["cycle_number"], error_code="NO_VALID_PAIR", media_errors=errors, trigger=trigger, slot_id=slot_id)
        if result is None:
            result = {"status": "FAILED", "error_code": "NO_PUBLISHABLE_MODEL"}
            await _finish_slot(slot_id, "FAILED")
        return result
    finally:
        await release_lock(owner)


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
        res = await _log(status="MANUAL_SKIP", model_id=nxt["model_id"], model_slug=nxt["slug"], model_name=nxt["name"], cycle_number=st["cycle_number"], trigger=trigger)
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
        out.append({"slot_id": f"x_{at.strftime('%Y-%m-%d')}_{t}", "at": at})
    return out


async def schedule_view(st: Optional[dict] = None) -> dict:
    st = st or await get_state()
    tz = _tz(st)
    now = datetime.now(tz)
    today = slots_for_day(st, now)
    done_ids = {d["slot_id"] async for d in slots_col.find({"slot_id": {"$in": [s["slot_id"] for s in today]}, "status": {"$in": ["PUBLISHED", "MOCK_PREPARED", "PARTIAL_FAILED", "RUNNING"]}}, {"slot_id": 1})}
    posts_today = await log_col.count_documents({"status": {"$in": ["PUBLISHED", "MOCK_PREPARED", "PARTIAL_FAILED"]}, "timestamp": {"$gte": now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()}})
    upcoming = [s for s in today if s["at"] > now and s["slot_id"] not in done_ids] or slots_for_day(st, now + timedelta(days=1))
    nxt = upcoming[0] if upcoming else None
    return {"timezone": str(tz), "now": now.isoformat(), "today_slots": [{"slot_id": s["slot_id"], "at": s["at"].isoformat(), "done": s["slot_id"] in done_ids} for s in today], "posts_today": posts_today, "posts_per_day": len(today),
            "next_slot": {"slot_id": nxt["slot_id"], "at": nxt["at"].isoformat()} if nxt else None}


async def due_slot(st: dict) -> Optional[str]:
    tz = _tz(st)
    now = datetime.now(tz)
    for s in slots_for_day(st, now):
        if s["at"] <= now <= s["at"] + timedelta(minutes=SLOT_GRACE_MIN):
            if not await slots_col.find_one({"slot_id": s["slot_id"]}):
                return s["slot_id"]
    return None


async def tick(trigger: str = "scheduler") -> dict:
    """Scheduler entry point. Requires: env master switch X_AUTO_SCHEDULER_ENABLED, enabled in DB, operational adapter."""
    await ensure_indexes()
    st = await get_state()
    if not auto_scheduler_enabled():
        return {"status": "AUTO_SCHEDULER_DISABLED"}
    if not st.get("enabled"):
        return {"status": "PAUSED"}
    slot = await due_slot(st)
    sch = await schedule_view(st)
    await set_state(next_run=(sch["next_slot"] or {}).get("at"))
    if not slot:
        return {"status": "NO_DUE_SLOT"}
    conn = await xapi.connection_status()
    if not conn["operational"]:
        await _log(status="FAILED", error_code=conn["CONNECTION_STATUS"], slot_id=slot, trigger=trigger, cycle_number=st["cycle_number"])
        return {"status": "FAILED", "error_code": conn["CONNECTION_STATUS"]}
    return await publish_next(trigger, slot_id=slot)


# ----------------------------------------------------------------------------------------------- status
async def status() -> dict:
    await ensure_indexes()
    st = await get_state()
    q = await queue_view(st)
    sch = await schedule_view(st)
    conn = await xapi.connection_status()
    last = await log_col.find_one({"status": {"$nin": ["SKIP_DUPLICATE_SLOT"]}}, {"_id": 0}, sort=[("timestamp", -1)])
    nxt = q["next"]
    ros = q["roster"]
    return {
        "enabled": bool(st["enabled"]), "AUTO_SCHEDULER_ENABLED": auto_scheduler_enabled(), "mock": xapi.mock_enabled(), "MOCK_MODE": xapi.mock_enabled(), "active": bool(st["enabled"]) and auto_scheduler_enabled(),
        "connection": conn, "CONNECTION_STATUS": conn["CONNECTION_STATUS"], "operational": conn["operational"], "ITALY_AUDIENCE_MODE": italy_mode(st), "X_REAL_CALLS": xapi.X_REAL_CALLS["n"],
        "X_REAL_POST_DONE": await log_col.count_documents({"status": "PUBLISHED", "mock": {"$ne": True}}) > 0,
        "REAL_X_POSTS_CREATED": await xapi.real_posts_created(), "X_REAL_POSTING_ENABLED": xapi.xauth.real_posting_enabled(), "X_USER_AUTH_PRESENT": await xapi.xauth.user_auth_present(),
        "x_identity": await xapi.xauth.saved_identity(),
        "queue": {"position": q["position"], "total": q["n_eligible"], "cycle_number": st["cycle_number"], "done_in_cycle": q["n_done_in_cycle"],
                  "current": {"slug": nxt["slug"], "name": nxt["name"], "n_public": nxt["n_public"], "n_secret": nxt["n_secret"], "of_url": nxt["of_url"]} if nxt else None,
                  "order": [{"slug": r["slug"], "name": r["name"], "done": r["model_id"] in set(st.get("cycle_done") or [])} for r in q["eligible"]],
                  "skipped_no_public_media": ros["no_public"], "skipped_no_secret_media": ros["no_secret"], "skipped_no_of_link": ros["no_of"], "not_x_safe": ros["not_safe"]},
        "schedule": sch, "settings": {"posts_per_day": st["posts_per_day"], "schedule_times": st["schedule_times"], "timezone": st["timezone"], "use_ai_copy": st["use_ai_copy"], "italy_audience_mode": italy_mode(st)},
        "last_published": st.get("last_published"), "last_event": last, "last_run": st.get("last_run"), "last_success": st.get("last_success"), "next_run": (sch["next_slot"] or {}).get("at"),
        "next": {"model": nxt["name"] if nxt else None, "slot": sch["next_slot"]},
    }
