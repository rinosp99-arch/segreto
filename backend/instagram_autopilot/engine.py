"""Instagram engine (mirror of telegram_autopilot.engine with an INDEPENDENT queue/state and the Meta adapter).
Persistent circular queue, media cursors (PUBLIC media only), slot idempotency (slot_id instagram_YYYY-MM-DD_HH:MM), DB lock.

Collections: instagram_autopilot_state · instagram_model_media_state · instagram_autopilot_log · instagram_autopilot_slots · instagram_autopilot_locks.
Rotation: eligible models in a stable order; `cycle_done` = model_ids already processed in the current cycle.
Next = first eligible model (in order, starting after the last processed position) not in cycle_done. When every eligible
model is in cycle_done -> cycle_number += 1, cycle_done = []. New PUBLISHED models simply appear in the order and are not
in cycle_done -> published before the cycle closes; DRAFT/removed/no-OF models are not eligible -> skipped automatically.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from database import db

from . import adapter as meta
from .caption import build_caption
from .media import roster

state_col = db["instagram_autopilot_state"]
media_state_col = db["instagram_model_media_state"]
log_col = db["instagram_autopilot_log"]
slots_col = db["instagram_autopilot_slots"]
locks_col = db["instagram_autopilot_locks"]

DEFAULTS = {"enabled": False, "posts_per_day": 2, "schedule_times": ["13:00", "20:30"], "timezone": "Europe/Rome", "use_photo": True, "use_video": True, "use_ai_copy": True,
            "cycle_number": 1, "cycle_done": [], "last_position": -1, "current_model_id": None, "last_published": None, "last_processed": None, "last_run": None, "last_success": None, "last_slot": None}
MAX_MEDIA_ATTEMPTS = 3
LOCK_TTL_S = 180
SLOT_GRACE_MIN = 90       # a slot is executed only within 90 minutes after its time (never bulk-catches-up an old day)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def auto_scheduler_enabled() -> bool:
    return os.environ.get("INSTAGRAM_AUTO_SCHEDULER_ENABLED", "false").lower() in ("1", "true", "yes")


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
async def queue_view(st: Optional[dict] = None) -> dict:
    st = st or await get_state()
    ros = await roster(st["use_photo"], st["use_video"])
    eligible = ros["eligible"]
    done = set(st.get("cycle_done") or [])
    ids = [r["model_id"] for r in eligible]
    remaining = [r for r in eligible if r["model_id"] not in done]
    nxt = _next_from(eligible, done, st.get("last_position", -1))
    return {"roster": ros, "eligible": eligible, "n_eligible": len(eligible), "n_done_in_cycle": len([i for i in ids if i in done]), "remaining": remaining, "next": nxt,
            "position": (len([i for i in ids if i in done]) + 1) if nxt else len(ids)}


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


async def _advance(st: dict, eligible: List[dict], model_id: str, published: bool, published_info: Optional[dict] = None, processed_status: str = ""):
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
    upd = {"cycle_done": done, "last_position": pos, "cycle_number": cycle, "last_processed": {"model_id": model_id, "status": processed_status, "at": now_iso()}}
    if published:
        upd["last_published"] = published_info
        upd["last_success"] = now_iso()
    nxt = _next_from(eligible, set(done), pos)
    upd["current_model_id"] = nxt["model_id"] if nxt else None
    await set_state(**upd)


# ----------------------------------------------------------------------------------------------- media cursor
async def pick_media_sequence(model_id: str, media: List[dict]) -> List[dict]:
    """Media starting at the cursor (wraps). The cursor advances only on success."""
    if not media:
        return []
    ms = await media_state_col.find_one({"model_id": model_id}, {"_id": 0}) or {}
    idx = int(ms.get("media_index", -1)) + 1
    if ms.get("last_media_id") and any(x["id"] == ms["last_media_id"] for x in media):
        idx = [x["id"] for x in media].index(ms["last_media_id"]) + 1
    idx %= len(media)
    return [media[(idx + k) % len(media)] for k in range(len(media))]


async def mark_media_used(model_id: str, media: List[dict], used: dict, cycle: int):
    await media_state_col.update_one({"model_id": model_id}, {"$set": {"model_id": model_id, "last_media_id": used["id"], "media_index": [x["id"] for x in media].index(used["id"]), "last_published_at": now_iso(), "cycle_last_used": cycle},
                                                              "$addToSet": {"used_media_ids": used["id"]}}, upsert=True)


# ----------------------------------------------------------------------------------------------- publish (adapter)
async def _publish(adapter, model: dict, item: dict, caption: str, slot_id, cycle: int) -> dict:
    """Builds the Meta payload (PHOTO_POST / REEL_POST) and hands it to the adapter (mock records it; real = future)."""
    payload = meta.build_payload(model, item, caption, slot_id, cycle)
    res = await adapter.publish(payload)
    return {"payload": payload, "result": res}


async def _log(**fields):
    doc = {"id": str(uuid.uuid4()), "timestamp": now_iso(), **fields}
    await log_col.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


# ----------------------------------------------------------------------------------------------- pipeline
async def publish_next(trigger: str = "scheduler", slot_id: Optional[str] = None, dry_run: bool = False) -> dict:
    """THE pipeline (used by scheduler and by PUBBLICA ORA): lock -> slot claim -> next model -> PUBLIC media -> caption IT -> adapter (mock / Meta) -> advance."""
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
        adapter = meta.get_adapter()
        is_mock = isinstance(adapter, meta.MockMeta)
        result = None
        for _ in range(len(eligible)):                 # bounded: at most one pass over the eligible list
            st = await get_state()
            cand = _next_from(eligible, set(st.get("cycle_done") or []), st.get("last_position", -1))
            if not cand:
                break
            m = next(x for x in q["roster"]["models"] if x["id"] == cand["model_id"])
            seq = await pick_media_sequence(cand["model_id"], cand["media"])
            cap = await build_caption(m, st["cycle_number"], use_ai=st["use_ai_copy"])
            if dry_run:
                return {"status": "DRY_RUN", "model": cand["slug"], "media": seq[:1], "post_type": "REEL_POST" if seq and seq[0]["type"] == "video" else "PHOTO_POST", "caption": cap["caption"], "hashtags": cap["hashtags"], "copy_source": cap["source"], "cycle_number": st["cycle_number"]}
            errors = []
            sent = None
            used = None
            for item in seq[:MAX_MEDIA_ATTEMPTS]:
                if item.get("side") != "PUBLIC":                       # hard guarantee: never anything but public media
                    errors.append({"media_id": item["id"], "media_type": item["type"], "error_code": "SKIPPED_NOT_INSTAGRAM_SAFE", "detail": "media non pubblico"})
                    continue
                try:
                    sent = await _publish(adapter, m, item, cap["caption"], slot_id, st["cycle_number"])
                    used = item
                    break
                except meta.InstagramError as e:
                    errors.append({"media_id": item["id"], "media_type": item["type"], "error_code": e.code, "detail": e.description[:160]})
                    if e.code in ("NOT_CONNECTED", "INVALID_TOKEN"):
                        break          # infrastructure problem: do not burn the queue
            if sent:
                status_ = "MOCK_PREPARED" if is_mock else "PUBLISHED"
                await mark_media_used(cand["model_id"], cand["media"], used, st["cycle_number"])
                info = {"model_id": cand["model_id"], "model_slug": cand["slug"], "model_name": cand["name"], "media_id": used["id"], "media_type": used["type"], "post_type": sent["payload"]["post_type"],
                        "ig_media_id": (sent["result"] or {}).get("id"), "at": now_iso(), "cycle_number": st["cycle_number"], "slot_id": slot_id}
                await _advance(st, eligible, cand["model_id"], True, info, status_)
                res = await _log(status=status_, **{k: v for k, v in info.items() if k != "at"}, trigger=trigger, copy_source=cap["source"], media_errors=errors or None, mock=is_mock)
                await _finish_slot(slot_id, status_)
                result = {"status": status_, **info, "caption": cap["caption"], "hashtags": cap["hashtags"], "copy_source": cap["source"], "payload": sent["payload"], "media_errors": errors, "log": res}
                break
            infra = errors and errors[-1]["error_code"] in ("NOT_CONNECTED", "INVALID_TOKEN")
            if infra:
                res = await _log(status="FAILED", model_id=cand["model_id"], model_slug=cand["slug"], model_name=cand["name"], cycle_number=st["cycle_number"], error_code=errors[-1]["error_code"], media_errors=errors, trigger=trigger, slot_id=slot_id)
                await _finish_slot(slot_id, "FAILED")
                result = {"status": "FAILED", "error_code": errors[-1]["error_code"], "model_slug": cand["slug"], "log": res}
                break
            # all public media of this creator failed -> SKIPPED_NO_PUBLIC_MEDIA (or NOT_INSTAGRAM_SAFE), advance, try the next creator
            skip_status = "SKIPPED_NOT_INSTAGRAM_SAFE" if errors and all(x["error_code"] == "SKIPPED_NOT_INSTAGRAM_SAFE" for x in errors) else "SKIPPED_NO_PUBLIC_MEDIA"
            await _advance(st, eligible, cand["model_id"], False, None, skip_status)
            await _log(status=skip_status, model_id=cand["model_id"], model_slug=cand["slug"], model_name=cand["name"], cycle_number=st["cycle_number"], error_code="ALL_MEDIA_FAILED", media_errors=errors, trigger=trigger, slot_id=slot_id)
        if result is None:
            result = {"status": "FAILED", "error_code": "NO_PUBLISHABLE_MODEL"}
            await _finish_slot(slot_id, "FAILED")
        return result
    finally:
        await release_lock(owner)


async def _finish_slot(slot_id: Optional[str], status: str):
    if slot_id:
        await slots_col.update_one({"slot_id": slot_id}, {"$set": {"status": status, "finished_at": now_iso()}})


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
    times = sorted(set((st.get("schedule_times") or DEFAULTS["schedule_times"])[: int(st.get("posts_per_day") or 2)]))
    out = []
    for t in times:
        hh, mm = [int(x) for x in t.split(":")]
        at = day.astimezone(tz).replace(hour=hh, minute=mm, second=0, microsecond=0)
        out.append({"slot_id": f"instagram_{at.strftime('%Y-%m-%d')}_{t}", "at": at})
    return out


async def schedule_view(st: Optional[dict] = None) -> dict:
    st = st or await get_state()
    tz = _tz(st)
    now = datetime.now(tz)
    today = slots_for_day(st, now)
    done_ids = {d["slot_id"] async for d in slots_col.find({"slot_id": {"$in": [s["slot_id"] for s in today]}, "status": {"$in": ["PUBLISHED", "MOCK_PREPARED", "RUNNING"]}}, {"slot_id": 1})}
    posts_today = await log_col.count_documents({"status": {"$in": ["PUBLISHED", "MOCK_PREPARED"]}, "timestamp": {"$gte": now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()}})
    upcoming = [s for s in today if s["at"] > now and s["slot_id"] not in done_ids]
    if not upcoming:
        upcoming = slots_for_day(st, now + timedelta(days=1))
    nxt = upcoming[0] if upcoming else None
    return {"timezone": str(tz), "now": now.isoformat(), "today_slots": [{"slot_id": s["slot_id"], "at": s["at"].isoformat(), "done": s["slot_id"] in done_ids} for s in today], "posts_today": posts_today, "posts_per_day": len(today),
            "next_slot": {"slot_id": nxt["slot_id"], "at": nxt["at"].isoformat()} if nxt else None}


async def due_slot(st: dict) -> Optional[str]:
    """The slot to execute now: its time has passed (within SLOT_GRACE_MIN) and it has not been claimed."""
    tz = _tz(st)
    now = datetime.now(tz)
    for s in slots_for_day(st, now):
        if s["at"] <= now <= s["at"] + timedelta(minutes=SLOT_GRACE_MIN):
            if not await slots_col.find_one({"slot_id": s["slot_id"]}):
                return s["slot_id"]
    return None


async def tick(trigger: str = "scheduler") -> dict:
    """Scheduler entry point (every few minutes). Publishes at most one due slot. Requires: env master switch, enabled in DB, CONNECTED."""
    await ensure_indexes()
    st = await get_state()
    if not auto_scheduler_enabled():
        return {"status": "AUTO_SCHEDULER_DISABLED"}
    if not st.get("enabled"):
        return {"status": "PAUSED"}
    slot = await due_slot(st)
    if not slot:
        return {"status": "NO_DUE_SLOT"}
    conn = await meta.connection_status()
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
    conn = await meta.connection_status()
    last = await log_col.find_one({"status": {"$in": ["PUBLISHED", "MOCK_PREPARED", "FAILED", "SKIPPED_NO_PUBLIC_MEDIA", "SKIPPED_NOT_INSTAGRAM_SAFE", "MANUAL_SKIP"]}}, {"_id": 0}, sort=[("timestamp", -1)])
    nxt = q["next"]
    from .caption import italy_mode
    return {
        "enabled": bool(st["enabled"]), "AUTO_SCHEDULER_ENABLED": auto_scheduler_enabled(), "mock": meta.mock_enabled(), "MOCK_MODE": meta.mock_enabled(), "active": bool(st["enabled"]) and auto_scheduler_enabled(),
        "connection": conn, "CONNECTION_STATUS": conn["CONNECTION_STATUS"], "operational": conn["operational"], "ITALY_AUDIENCE_MODE": italy_mode(), "META_REAL_CALLS": meta.META_REAL_CALLS["n"],
        "SECRET_MEDIA_USED": False, "INSTAGRAM_REAL_POST_DONE": await log_col.count_documents({"status": "PUBLISHED", "mock": {"$ne": True}}) > 0,
        "queue": {"position": q["position"], "total": q["n_eligible"], "cycle_number": st["cycle_number"], "done_in_cycle": q["n_done_in_cycle"],
                  "current": {"slug": nxt["slug"], "name": nxt["name"], "n_photos": nxt["n_photos"], "n_videos": nxt["n_videos"]} if nxt else None,
                  "order": [{"slug": r["slug"], "name": r["name"], "done": r["model_id"] in set(st.get("cycle_done") or [])} for r in q["eligible"]],
                  "skipped_no_public_media": q["roster"]["no_media"], "not_instagram_safe": q["roster"]["not_safe"]},
        "schedule": sch, "settings": {k: st[k] for k in ("posts_per_day", "schedule_times", "timezone", "use_photo", "use_video", "use_ai_copy")},
        "last_published": st.get("last_published"), "last_event": last, "last_run": st.get("last_run"), "last_success": st.get("last_success"),
        "next": {"model": nxt["name"] if nxt else None, "slot": sch["next_slot"]},
    }
