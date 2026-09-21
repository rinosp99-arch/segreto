"""X Autopilot — FIRST CONTROLLED REAL POST (one model, one post, hard cap 1, idempotent, READ-verified).

Gates (all must pass, READ-ONLY, before any write): X_AUTOPILOT_MOCK=false · X_REAL_POSTING_ENABLED=true · X_AUTO_SCHEDULER_ENABLED=false ·
hard cap REAL_X_POSTS_CREATED < 1 (DB: log + real runs) · account connected (@latosegreto, read-write) · credits probe (one v2 READ, 402 -> STOP) ·
next queue model with PHOTO Public + PHOTO Secret (SINGLE_POST) · both media pass MIME/size pre-check · copy contains ONLY the model's OF link.
Write: SENDING marker (x_real_runs) -> upload PUBLIC -> upload SECRET -> verify media ids -> ONE POST /2/tweets -> READ back
(exists, author = connected account, 2 media, text, OF link) -> PUBLISHED (queue advances once) | UNVERIFIED (never resent; verify() re-reads)."""
import uuid
from typing import Optional

from database import db

from . import adapter as xapi
from . import engine, xauth

runs_col = db["x_real_runs"]
RUN_STATES_BLOCKING = ("SENDING", "UNVERIFIED", "PUBLISHED")
HARD_CAP = 1


def _run_id(model_id: str, cycle: int) -> str:
    return f"{model_id}:{cycle}"


async def real_runs_started() -> int:
    return await runs_col.count_documents({"status": {"$in": list(RUN_STATES_BLOCKING)}})


async def last_run() -> Optional[dict]:
    return await runs_col.find_one({}, {"_id": 0}, sort=[("started_at", -1)])


def _post_url(username: Optional[str], post_id: str) -> str:
    return f"https://x.com/{username or 'i'}/status/{post_id}"


def _verify_read(data: dict, expected_author_id: Optional[str], text: str, of_url: str) -> dict:
    t = (data or {}).get("data") or {}
    inc = (data or {}).get("includes") or {}
    media = inc.get("media") or []
    users = {u.get("id"): u for u in (inc.get("users") or [])}
    author_id = str(t.get("author_id") or "")
    author_username = (users.get(author_id) or {}).get("username")
    urls = [u.get("expanded_url") or u.get("unwound_url") or "" for u in ((t.get("entities") or {}).get("urls") or [])]
    needle = of_url.lower().rstrip("/")
    of_ok = any(needle in (u or "").lower() for u in urls) or needle in (t.get("text") or "").lower()
    first_line = (text.split("\n")[0] or "").strip().lower()
    text_ok = bool(first_line) and first_line in (t.get("text") or "").lower()
    media_keys = ((t.get("attachments") or {}).get("media_keys") or [])
    media_count = len(media) or len(media_keys)
    account_ok = (author_id == str(expected_author_id)) if expected_author_id else (author_username == "latosegreto")
    return {"exists": bool(t.get("id")), "post_id": t.get("id"), "account_ok": account_ok, "author_username": author_username, "media_count": media_count,
            "media_types": [m.get("type") for m in media], "text_ok": text_ok, "of_link_ok": of_ok,
            "ok": bool(t.get("id")) and account_ok and media_count == 2 and text_ok and of_ok}


async def real_test_post(trigger: str = "admin", execute: bool = False) -> dict:
    rep = {"status": None, "execute": execute, "checks": {}, "MODEL_NAME": None, "MODEL_OF_URL": None, "PUBLIC_MEDIA_UPLOAD": None, "SECRET_MEDIA_UPLOAD": None,
           "REAL_X_POST_CREATE": None, "POST_ID": None, "POST_URL": None, "READBACK_VERIFY": None, "MEDIA_COUNT": None, "OF_LINK_VALID": None, "DUPLICATE_PREVENTED": False,
           "X_CREDITS_READY": None, "X_AUTO_SCHEDULER_ENABLED": engine.auto_scheduler_enabled(), "X_AUTOPILOT_MOCK": xapi.mock_enabled(), "X_REAL_POSTING_ENABLED": xauth.real_posting_enabled()}
    ck = rep["checks"]
    ck["MOCK_OFF"] = not xapi.mock_enabled()
    ck["REAL_POSTING_ENABLED"] = xauth.real_posting_enabled()
    ck["SCHEDULER_OFF"] = not engine.auto_scheduler_enabled()
    created = await xapi.real_posts_created()
    started = await real_runs_started()
    rep["REAL_X_POSTS_CREATED"] = created
    ck["HARD_CAP_FREE"] = created < HARD_CAP and started < HARD_CAP
    if not (ck["MOCK_OFF"] and ck["REAL_POSTING_ENABLED"] and ck["SCHEDULER_OFF"]):
        rep["status"] = "STOPPED_GATES"
        return rep
    if not ck["HARD_CAP_FREE"]:
        rep["status"], rep["DUPLICATE_PREVENTED"] = "BLOCKED_HARD_CAP", True
        rep["last_run"] = await last_run()
        return rep
    adapter = xapi.get_adapter()
    if isinstance(adapter, xapi.MockXAdapter):
        rep["status"] = "STOPPED_GATES"
        ck["REAL_ADAPTER"] = False
        return rep
    ck["REAL_ADAPTER"] = True
    # ---- account (READ)
    try:
        acc = await adapter.check()
    except xapi.XError as e:
        rep["status"], rep["error_code"] = "STOPPED_PRECHECK", e.code
        ck["ACCOUNT_CONNECTED"] = False
        return rep
    user_id_full = ((await xauth.auth_col.find_one({"id": "identity"}, {"_id": 0, "user_id": 1})) or {}).get("user_id")
    ck["ACCOUNT_CONNECTED"] = (acc.get("username") or "").lower() == "latosegreto"
    ck["WRITE_CAPABILITY"] = (acc.get("access_level") or "").startswith("read-write")
    rep["X_USERNAME"], rep["X_ACCESS_LEVEL"] = acc.get("username"), acc.get("access_level")
    if not (ck["ACCOUNT_CONNECTED"] and ck["WRITE_CAPABILITY"]):
        rep["status"], rep["error_code"] = "STOPPED_PRECHECK", "ACCOUNT_OR_PERMISSIONS"
        return rep
    # ---- credits (ONE READ on the posts product)
    probe = await adapter.credits_probe()
    rep["credits_probe"] = probe
    rep["X_CREDITS_READY"] = ck["CREDITS_READY"] = bool(probe["ok"])
    if not probe["ok"]:
        rep["status"], rep["error_code"] = "STOPPED_CREDITS" if probe["error"] == "CREDITS_DEPLETED" else "STOPPED_PRECHECK", probe["error"]
        return rep
    # ---- candidate: next queue model, PHOTO+PHOTO required for the first test
    st = await engine.get_state()
    q = await engine.queue_view(st)
    cand = q["next"]
    if not cand:
        rep["status"], rep["error_code"] = "STOPPED_PRECHECK", "NO_ELIGIBLE_MODELS"
        return rep
    model = next(x for x in q["roster"]["models"] if x["id"] == cand["model_id"])
    prep = await engine._prepare(cand, model, st, None)
    photo_pairs = [(p, s) for p, s in prep["pairs"] if p["type"] == "photo" and s["type"] == "photo"]
    rep.update(MODEL_NAME=cand["name"], MODEL_SLUG=cand["slug"], MODEL_OF_URL=cand["of_url"], cycle_number=st["cycle_number"])
    ck["PHOTO_PAIR_AVAILABLE"] = bool(photo_pairs)
    if not photo_pairs:
        rep["status"], rep["error_code"] = "STOPPED_PRECHECK", "FIRST_TEST_REQUIRES_PHOTO_PAIR"
        return rep
    pub, sec = None, None
    for p, s_ in photo_pairs:
        vp, vs = await xapi.validate_media_source(p), await xapi.validate_media_source(s_)
        if vp["ok"] and vs["ok"]:
            pub, sec = p, s_
            rep["media_precheck"] = {"public": vp, "secret": vs}
            break
    ck["MEDIA_PRECHECK"] = bool(pub and sec)
    if not (pub and sec):
        rep["status"], rep["error_code"] = "STOPPED_PRECHECK", "NO_VALID_PHOTO_PAIR"
        return rep
    assert pub["side"] == "PUBLIC" and sec["side"] == "SECRET" and pub["type"] == sec["type"] == "photo"
    cp = prep["copy"]
    text = cp["text"]
    ck["OF_LINK_IN_COPY"] = cand["of_url"] in text and text.count("http") == 1 and "onlyfans.com/latosegreto" not in text.lower()
    ck["COPY_LENGTH_OK"] = xapi.x_len(text) <= xapi.TEXT_LIMIT
    rep.update(TEXT=text, copy_source=cp["source"], public_media={k: pub[k] for k in ("id", "type", "side")}, secret_media={k: sec[k] for k in ("id", "type", "side")}, FORMAT="SINGLE_POST")
    rep["ALL_PRECHECKS_PASS"] = all(v is True for v in ck.values())
    if not rep["ALL_PRECHECKS_PASS"]:
        rep["status"] = "STOPPED_PRECHECK"
        rep["failed_checks"] = [k for k, v in ck.items() if v is not True]
        return rep
    if not execute:
        rep["status"] = "DRY_RUN_PASS"
        return rep
    # ---------------- WRITE (lock, SENDING marker, uploads, ONE create, READ back)
    owner = str(uuid.uuid4())
    if not await engine.acquire_lock(owner):
        rep["status"] = "LOCKED"
        return rep
    run_id = _run_id(cand["model_id"], st["cycle_number"])
    try:
        if await runs_col.find_one({"id": run_id, "status": {"$in": list(RUN_STATES_BLOCKING)}}) or await real_runs_started() >= HARD_CAP or await xapi.real_posts_created() >= HARD_CAP:
            rep["status"], rep["DUPLICATE_PREVENTED"] = "BLOCKED_HARD_CAP", True
            return rep
        await runs_col.update_one({"id": run_id}, {"$set": {"id": run_id, "status": "SENDING", "started_at": xauth.now_iso(), "model_id": cand["model_id"], "model_slug": cand["slug"], "model_name": cand["name"],
                                  "of_url": cand["of_url"], "text": text, "public_media_id": pub["id"], "secret_media_id": sec["id"], "trigger": trigger, "cycle_number": st["cycle_number"], "media_ids": []}}, upsert=True)
        try:
            mid_pub = await adapter.upload_media(pub)
            rep["PUBLIC_MEDIA_UPLOAD"] = "PASS"
        except xapi.XError as e:
            rep.update(PUBLIC_MEDIA_UPLOAD="FAIL", status="UPLOAD_FAILED", error_code=e.code, error=e.description[:200])
            await runs_col.update_one({"id": run_id}, {"$set": {"status": "UPLOAD_FAILED", "error": f"PUBLIC:{e.code}", "finished_at": xauth.now_iso()}})
            return rep
        try:
            mid_sec = await adapter.upload_media(sec)
            rep["SECRET_MEDIA_UPLOAD"] = "PASS"
        except xapi.XError as e:
            rep.update(SECRET_MEDIA_UPLOAD="FAIL", status="UPLOAD_FAILED", error_code=e.code, error=e.description[:200])
            await runs_col.update_one({"id": run_id}, {"$set": {"status": "UPLOAD_FAILED", "error": f"SECRET:{e.code}", "finished_at": xauth.now_iso()}})
            return rep
        media_ids = [str(mid_pub), str(mid_sec)]
        rep["MEDIA_IDS_OK"] = len(set(media_ids)) == 2 and all(media_ids)
        if not rep["MEDIA_IDS_OK"]:
            rep.update(status="UPLOAD_FAILED", error_code="MEDIA_IDS_INVALID")
            await runs_col.update_one({"id": run_id}, {"$set": {"status": "UPLOAD_FAILED", "error": "MEDIA_IDS_INVALID", "finished_at": xauth.now_iso()}})
            return rep
        await runs_col.update_one({"id": run_id}, {"$set": {"media_ids": media_ids, "create_started_at": xauth.now_iso()}})
        payload = {"kind": "MAIN", "text": text, "media_ids": media_ids, "model_slug": cand["slug"], "cycle_number": st["cycle_number"], "in_reply_to": None}
        post_id, create_error = None, None
        try:
            res = await adapter.create_post(payload)
            post_id = res.get("id")
        except xapi.XError as e:
            create_error = e.code
        if post_id:
            rep["REAL_X_POST_CREATE"] = "PASS"
        else:
            definitive = create_error in ("WRITES_DISABLED", "NOT_CONNECTED", "INVALID_TOKEN", "FORBIDDEN", "CREDITS_DEPLETED", "MEDIA_REJECTED")
            status = "FAILED" if definitive else "UNVERIFIED"                       # timeout / 5xx after the create started -> never resend
            rep.update(REAL_X_POST_CREATE="FAIL" if definitive else f"UNKNOWN_{create_error}", status=status, error_code=create_error)
            await runs_col.update_one({"id": run_id}, {"$set": {"status": status, "error": create_error, "finished_at": xauth.now_iso()}})
            if status == "UNVERIFIED":
                rep.update(await _readback_recent(adapter, run_id, user_id_full, text, cand["of_url"], acc.get("username")))
            await engine._log(status="FAILED" if status == "FAILED" else "UNVERIFIED", model_id=cand["model_id"], model_slug=cand["slug"], model_name=cand["name"], cycle_number=st["cycle_number"],
                              error_code=create_error, trigger=trigger, mock=False, real_test=True)
            return rep
        return await _confirm(adapter, rep, run_id, post_id, cand, model, pub, sec, text, cp, st, q, user_id_full, acc.get("username"), trigger)
    finally:
        await engine.release_lock(owner)


async def _confirm(adapter, rep, run_id, post_id, cand, model, pub, sec, text, cp, st, q, user_id_full, username, trigger) -> dict:
    rep["POST_ID"], rep["POST_URL"] = str(post_id), _post_url(username, str(post_id))
    try:
        data = await adapter.read_post(str(post_id))
        v = _verify_read(data, user_id_full, text, cand["of_url"])
    except xapi.XError as e:
        v = {"ok": False, "exists": None, "error": e.code}
    rep["readback"] = v
    rep["READBACK_VERIFY"] = "PASS" if v.get("ok") else "FAIL"
    rep["MEDIA_COUNT"], rep["OF_LINK_VALID"] = v.get("media_count"), v.get("of_link_ok")
    status = "PUBLISHED" if v.get("ok") else "UNVERIFIED"
    await runs_col.update_one({"id": run_id}, {"$set": {"status": status, "post_id": str(post_id), "post_url": rep["POST_URL"], "readback": v, "finished_at": xauth.now_iso()}})
    info = {"model_id": cand["model_id"], "model_slug": cand["slug"], "model_name": cand["name"], "public_media_id": pub["id"], "secret_media_id": sec["id"], "public_media_type": pub["type"],
            "secret_media_type": sec["type"], "format": "SINGLE_POST", "x_post_id": str(post_id), "x_reply_id": None, "of_url": cand["of_url"], "at": xauth.now_iso(), "cycle_number": st["cycle_number"], "slot_id": None}
    await engine.mark_media_used(cand["model_id"], cand["public"], cand["secret"], pub, sec, st["cycle_number"])
    await engine._advance(st, q["eligible"], cand["model_id"], True, info, status)         # the model is consumed either way: never a second post for it
    await engine._log(status=status, **{k: v_ for k, v_ in info.items() if k != "at"}, trigger=trigger, copy_source=cp["source"], mock=False, real_test=True, post_url=rep["POST_URL"], readback=v)
    rep["status"] = status
    rep["REAL_X_POSTS_CREATED"] = await xapi.real_posts_created()
    rep["DUPLICATE_PREVENTED"] = True
    return rep


async def _readback_recent(adapter, run_id, user_id_full, text, of_url, username) -> dict:
    """UNVERIFIED create (no id): look for our text among the account's recent posts (READ). Found -> PUBLISHED, else stays UNVERIFIED."""
    out = {"READBACK_VERIFY": "UNAVAILABLE"}
    if not user_id_full:
        return out
    try:
        recent = await adapter.recent_posts(user_id_full, 5)
    except xapi.XError as e:
        out["readback_error"] = e.code
        return out
    first_line = (text.split("\n")[0] or "").strip().lower()
    for t in recent:
        if first_line and first_line in (t.get("text") or "").lower():
            pid = str(t.get("id"))
            await runs_col.update_one({"id": run_id}, {"$set": {"status": "PUBLISHED", "post_id": pid, "post_url": _post_url(username, pid), "readback": {"via": "recent", "ok": True}}})
            out.update(READBACK_VERIFY="PASS", POST_ID=pid, POST_URL=_post_url(username, pid), status="PUBLISHED", REAL_X_POST_CREATE="PASS")
            return out
    out["READBACK_VERIFY"] = "FAIL"
    return out


async def verify_last(trigger: str = "admin") -> dict:
    """READ-ONLY: re-read the last real run's post (or search recent posts for an UNVERIFIED run). Never writes to X."""
    run = await last_run()
    if not run:
        return {"status": "NO_RUN"}
    if xapi.mock_enabled():
        return {"status": "MOCK_MODE", "run": run}
    adapter = xapi.get_adapter()
    user_id_full = ((await xauth.auth_col.find_one({"id": "identity"}, {"_id": 0, "user_id": 1})) or {}).get("user_id")
    username = (await xauth.saved_identity()).get("X_USERNAME")
    if run.get("post_id"):
        try:
            v = _verify_read(await adapter.read_post(run["post_id"]), user_id_full, run.get("text") or "", run.get("of_url") or "")
        except xapi.XError as e:
            return {"status": run["status"], "readback": {"ok": False, "error": e.code}, "run": run}
        status = "PUBLISHED" if v["ok"] else run["status"]
        await runs_col.update_one({"id": run["id"]}, {"$set": {"status": status, "readback": v, "verified_at": xauth.now_iso()}})
        return {"status": status, "readback": v, "POST_ID": run["post_id"], "POST_URL": run.get("post_url"), "run": {**run, "status": status}}
    if run.get("status") == "UNVERIFIED":
        out = await _readback_recent(adapter, run["id"], user_id_full, run.get("text") or "", run.get("of_url") or "", username)
        return {"status": out.get("status", "UNVERIFIED"), **out, "run": await runs_col.find_one({"id": run["id"]}, {"_id": 0})}
    return {"status": run["status"], "run": run}
