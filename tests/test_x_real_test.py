"""X Autopilot — FIRST CONTROLLED REAL POST flow (realtest.py) with a FAKE real adapter (zero network): gates, hard cap 1, credits STOP,
PHOTO+PHOTO requirement, SENDING marker, uploads -> ONE create -> READ verify, UNVERIFIED never resent, duplicate prevention, verify_last READ-ONLY."""
import os
import sys

import pytest
import requests

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/tests")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")
os.environ["X_AUTOPILOT_MOCK"] = "true"
os.environ["X_AUTO_SCHEDULER_ENABLED"] = "false"

from x_autopilot import adapter as xapi, engine, realtest, xauth  # noqa: E402
from database import models_col  # noqa: E402
from test_x_autopilot import _model, seed, sandbox, TAG  # noqa: E402,F401
from _creds import admin_credentials  # noqa: E402

pytestmark = pytest.mark.anyio
BASE = os.environ.get("TEST_BACKEND", "http://localhost:8001")
UID = "1234567890544"


class FakeReal(xapi.RealXAdapter):
    """Non-mock adapter (engine/realtest treat it as REAL) recording everything in memory. No network."""
    name = "FAKE_REAL"

    def __init__(self):
        self.uploads, self.posts, self.reads = [], [], 0
        self.credits_ok, self.fail_create, self.fail_upload, self.read_fail = True, None, None, False
        self.account = {"id": "**********544", "username": "latosegreto", "name": "LATO SEGRETO", "access_level": "read-write"}

    async def check(self):
        return dict(self.account)

    async def credits_probe(self):
        return {"ok": True, "status": 200, "error": None} if self.credits_ok else {"ok": False, "status": 402, "error": "CREDITS_DEPLETED", "detail": "credits depleted"}

    async def upload_media(self, item):
        self._write_allowed()
        if self.fail_upload and self.fail_upload in item["url"]:
            raise xapi.XError("MEDIA_REJECTED", "fake")
        mid = f"m{len(self.uploads) + 1}"
        self.uploads.append({"media_id": mid, **item})
        return mid

    async def create_post(self, payload):
        self._write_allowed()
        if self.fail_create:
            raise xapi.XError(self.fail_create, "fake")
        pid = f"19{len(self.posts) + 1:03d}"
        self.posts.append({**payload, "id": pid})
        return {"id": pid}

    async def read_post(self, post_id):
        self.reads += 1
        if self.read_fail:
            raise xapi.XError("API_ERROR", "read down")
        p = next((x for x in self.posts if x["id"] == post_id), None)
        if not p:
            raise xapi.XError("NOT_FOUND", "no post")
        of = next(u for u in p["text"].split() if u.startswith("http"))
        return {"data": {"id": post_id, "text": p["text"].replace(of, "https://t.co/abc"), "author_id": UID, "attachments": {"media_keys": [f"3_{m}" for m in p["media_ids"]]},
                         "entities": {"urls": [{"url": "https://t.co/abc", "expanded_url": of}]}},
                "includes": {"media": [{"media_key": f"3_{m}", "type": "photo"} for m in p["media_ids"]], "users": [{"id": UID, "username": "latosegreto"}]}}

    async def recent_posts(self, user_id, n=5):
        self.reads += 1
        return [{"id": p["id"], "text": p["text"]} for p in self.posts]


@pytest.fixture
async def real_env(sandbox, monkeypatch):  # noqa: F811
    fake = FakeReal()
    xapi.force_adapter(fake)
    monkeypatch.setenv("X_AUTOPILOT_MOCK", "false")
    monkeypatch.setenv("X_REAL_POSTING_ENABLED", "true")
    monkeypatch.setenv("X_AUTO_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("X_CONSUMER_KEY", "k" * 25)
    monkeypatch.setenv("X_CONSUMER_SECRET", "s" * 50)
    saved = [d async for d in xauth.auth_col.find({}, {"_id": 0})]
    saved_runs = [d async for d in realtest.runs_col.find({}, {"_id": 0})]
    await xauth.auth_col.delete_many({})
    await realtest.runs_col.delete_many({})
    await xauth.auth_col.insert_one({"id": "identity", "user_id": UID, "username": "latosegreto", "name": "LATO SEGRETO", "access_level": "read-write"})

    async def fake_val(item):
        return {"ok": True, "url_ok": True, "mime": "image/jpeg", "bytes": 1000, "reason": None}
    monkeypatch.setattr(xapi, "validate_media_source", fake_val)
    yield fake
    xapi.force_adapter(sandbox)
    await realtest.runs_col.delete_many({})
    await xauth.auth_col.delete_many({})
    if saved:
        await xauth.auth_col.insert_many(saved)
    if saved_runs:
        await realtest.runs_col.insert_many(saved_runs)
    await engine.log_col.delete_many({"real_test": True, "model_slug": {"$regex": f"^{TAG}"}})


async def test_gates_block_before_anything(real_env, monkeypatch):
    fake = real_env
    await seed(_model(f"{TAG}-g1", ordine=1))
    monkeypatch.setenv("X_AUTOPILOT_MOCK", "true")
    r = await realtest.real_test_post("t", execute=True)
    assert r["status"] == "STOPPED_GATES" and not fake.uploads and not fake.posts
    monkeypatch.setenv("X_AUTOPILOT_MOCK", "false")
    monkeypatch.setenv("X_REAL_POSTING_ENABLED", "false")
    assert (await realtest.real_test_post("t", execute=True))["status"] == "STOPPED_GATES"
    monkeypatch.setenv("X_REAL_POSTING_ENABLED", "true")
    monkeypatch.setenv("X_AUTO_SCHEDULER_ENABLED", "true")
    r = await realtest.real_test_post("t", execute=True)
    assert r["status"] == "STOPPED_GATES" and r["checks"]["SCHEDULER_OFF"] is False and not fake.uploads and not fake.posts


async def test_credits_depleted_stops_before_write(real_env):
    fake = real_env
    fake.credits_ok = False
    await seed(_model(f"{TAG}-c1", ordine=1))
    r = await realtest.real_test_post("t", execute=True)
    assert r["status"] == "STOPPED_CREDITS" and r["error_code"] == "CREDITS_DEPLETED" and r["X_CREDITS_READY"] is False and not fake.uploads and not fake.posts
    assert await realtest.real_runs_started() == 0


async def test_photo_pair_required_and_dry_run(real_env):
    fake = real_env
    vid = _model(f"{TAG}-v1", pub_photos=0, pub_videos=1, sec_photos=1, ordine=1)
    await seed(vid)
    r = await realtest.real_test_post("t", execute=True)
    assert r["status"] == "STOPPED_PRECHECK" and r["error_code"] == "FIRST_TEST_REQUIRES_PHOTO_PAIR" and not fake.uploads and not fake.posts
    await models_col.delete_many({"id": vid["id"]})
    m = _model(f"{TAG}-d1", ordine=1)
    await seed(m)
    d = await realtest.real_test_post("t", execute=False)
    assert d["status"] == "DRY_RUN_PASS" and d["ALL_PRECHECKS_PASS"] and d["FORMAT"] == "SINGLE_POST" and d["MODEL_OF_URL"] == m["onlyfans_url"] and d["MODEL_OF_URL"] in d["TEXT"]
    assert d["TEXT"].count("http") == 1 and "onlyfans.com/latosegreto" not in d["TEXT"].lower() and d["public_media"]["type"] == d["secret_media"]["type"] == "photo"
    assert not fake.uploads and not fake.posts and xapi.X_REAL_CALLS["n"] == 0


async def test_one_real_post_verified_then_hard_cap(real_env):
    fake = real_env
    a, b = await seed(_model(f"{TAG}-r1", ordine=1), _model(f"{TAG}-r2", ordine=2))
    r = await realtest.real_test_post("t", execute=True)
    assert r["status"] == "PUBLISHED" and r["PUBLIC_MEDIA_UPLOAD"] == "PASS" and r["SECRET_MEDIA_UPLOAD"] == "PASS" and r["REAL_X_POST_CREATE"] == "PASS"
    assert r["READBACK_VERIFY"] == "PASS" and r["MEDIA_COUNT"] == 2 and r["OF_LINK_VALID"] is True and r["POST_ID"] == "19001" and r["POST_URL"] == "https://x.com/latosegreto/status/19001"
    assert r["MODEL_NAME"] == a["nome_artistico"] and r["MODEL_OF_URL"] == a["onlyfans_url"] and r["DUPLICATE_PREVENTED"] is True and r["REAL_X_POSTS_CREATED"] == 1
    assert len(fake.posts) == 1 and fake.posts[0]["media_ids"] == ["m1", "m2"] and fake.uploads[0]["side"] == "PUBLIC" and fake.uploads[1]["side"] == "SECRET"   # PUBLIC first
    run = await realtest.last_run()
    assert run["status"] == "PUBLISHED" and run["post_id"] == "19001" and run["media_ids"] == ["m1", "m2"] and run["readback"]["ok"]
    st = await engine.get_state()
    assert st["cycle_done"] == [a["id"]] and st["last_published"]["x_post_id"] == "19001"                  # consumed once, next model NOT published
    log = await engine.log_col.find_one({"x_post_id": "19001"}, {"_id": 0})
    assert log["status"] == "PUBLISHED" and log["mock"] is False and log["real_test"] is True
    # HARD CAP: second call never uploads/posts
    r2 = await realtest.real_test_post("t", execute=True)
    assert r2["status"] == "BLOCKED_HARD_CAP" and r2["DUPLICATE_PREVENTED"] is True and len(fake.posts) == 1 and len(fake.uploads) == 2
    v = await realtest.verify_last("t")
    assert v["status"] == "PUBLISHED" and v["readback"]["ok"] and len(fake.posts) == 1


async def test_unverified_never_resent_then_readback(real_env):
    fake = real_env
    await seed(_model(f"{TAG}-u1", ordine=1))
    fake.fail_create = "NETWORK_ERROR"                                                          # timeout after the create started
    r = await realtest.real_test_post("t", execute=True)
    assert r["status"] == "UNVERIFIED" and r["REAL_X_POST_CREATE"] == "UNKNOWN_NETWORK_ERROR" and r["READBACK_VERIFY"] == "FAIL" and not fake.posts
    assert (await realtest.last_run())["status"] == "UNVERIFIED" and await realtest.real_runs_started() == 1
    r2 = await realtest.real_test_post("t", execute=True)
    assert r2["status"] == "BLOCKED_HARD_CAP" and not fake.posts and len(fake.uploads) == 2               # never resent
    # the post actually exists on X -> READ-only verify finds it by text and closes the run as PUBLISHED
    fake.posts.append({"id": "19777", "text": (await realtest.last_run())["text"], "media_ids": ["m1", "m2"]})
    v = await realtest.verify_last("t")
    assert v["status"] == "PUBLISHED" and v["POST_ID"] == "19777" and (await realtest.last_run())["status"] == "PUBLISHED"
    assert len(fake.posts) == 1


async def test_upload_failure_no_post_and_definitive_create_failure(real_env):
    fake = real_env
    await seed(_model(f"{TAG}-f1", ordine=1))
    fake.fail_upload = "sec_p0"
    r = await realtest.real_test_post("t", execute=True)
    assert r["status"] == "UPLOAD_FAILED" and r["PUBLIC_MEDIA_UPLOAD"] == "PASS" and r["SECRET_MEDIA_UPLOAD"] == "FAIL" and not fake.posts
    assert (await realtest.last_run())["status"] == "UPLOAD_FAILED" and await realtest.real_runs_started() == 0        # retry allowed, cap not consumed
    fake.fail_upload, fake.fail_create = None, "FORBIDDEN"
    r = await realtest.real_test_post("t", execute=True)
    assert r["status"] == "FAILED" and r["REAL_X_POST_CREATE"] == "FAIL" and not fake.posts and (await realtest.last_run())["status"] == "FAILED"
    assert (await engine.get_state())["cycle_done"] == []                                                     # no advance without a post


def test_admin_real_test_routes_contract():
    assert requests.post(f"{BASE}/api/admin/x-autopilot/real-test", timeout=15).status_code in (401, 403)
    assert requests.get(f"{BASE}/api/admin/x-autopilot/real-test", timeout=15).status_code in (401, 403)
    assert requests.post(f"{BASE}/api/admin/x-autopilot/real-test/verify", timeout=15).status_code in (401, 403)
    h = {"Authorization": f"Bearer {requests.post(f'{BASE}/api/admin/login', json=admin_credentials(), timeout=15).json()['token']}"}
    r = requests.post(f"{BASE}/api/admin/x-autopilot/real-test?execute=true", headers=h, timeout=60).json()      # server is MOCK -> gates stop it, nothing happens
    assert r["status"] == "STOPPED_GATES" and r["checks"]["MOCK_OFF"] is False and r["REAL_X_POSTS_CREATED"] == 0
    g = requests.get(f"{BASE}/api/admin/x-autopilot/real-test", headers=h, timeout=30).json()
    assert g["REAL_X_POSTS_CREATED"] == 0 and g["runs_started"] == 0
