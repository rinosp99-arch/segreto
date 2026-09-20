"""OnlyFans provider connection tests (The Only API) — READ-ONLY. No upload / post / schedule / delete / account / proxy mutation is ever made.
A key auth · B CRM scope · C connected accounts · D latosegreto discovered · E platform onlyfans · F of_user_id discovered · G health ·
H schedules READ · I adapter isolation (abstract interface) · J secrets backend-only · K key not logged · L key not in frontend ·
M/N no proxy/account mutation (only GET requests leave the adapter) · O/P no post / no scheduled post created (writes blocked before network) ·
Q/R/S Telegram / Instagram / X unchanged.
"""
import json
import logging
import os
import re
import subprocess
import sys

import pytest
import requests

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/tests")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from of_autopilot import connection  # noqa: E402
from of_autopilot.providers import the_only_api as toa  # noqa: E402
from of_autopilot.providers.base import OFMedia, OFPostRequest, OFProviderAdapter, OFProviderError  # noqa: E402
from database import db  # noqa: E402
from _creds import admin_credentials  # noqa: E402

pytestmark = pytest.mark.anyio
BASE = os.environ.get("TEST_BACKEND", "http://localhost:8001")
KEY = toa.api_key()
CRM = toa.crm_id()
EXPECTED = "latosegreto"
pytest.importorskip("httpx")
needs_creds = pytest.mark.skipif(not (KEY and CRM), reason="provider credentials not configured in this environment")


class _RequestSpy:
    """Wraps the adapter's transport: records every outbound method (to prove READ-ONLY) without exposing headers."""

    def __init__(self):
        self.methods = []

    def install(self, monkeypatch):
        import httpx
        orig = httpx.AsyncClient.request

        async def spy(client, method, url, **kw):
            self.methods.append((method.upper(), str(url).split("?")[0]))
            return await orig(client, method, url, **kw)
        monkeypatch.setattr(httpx.AsyncClient, "request", spy)


# ------------------------------------------------------------------ A-H (real READ-ONLY calls)
@needs_creds
async def test_A_to_H_read_only_discovery(monkeypatch):
    spy = _RequestSpy(); spy.install(monkeypatch)
    writes_before = toa.CALLS["write"]
    a = toa.TheOnlyAPIAdapter()
    who = await a.whoami()                                                   # A key valid (401 would raise UNAUTHORIZED)
    assert who.get("crm_id") == CRM                                          # B CRM scope
    accounts = await a.list_accounts()                                       # C connected accounts
    assert len(accounts) >= 1
    of_accounts = [x for x in accounts if x.platform == "onlyfans"]
    assert len(of_accounts) == 1 and of_accounts[0].username.lower() == EXPECTED   # D single latosegreto · E onlyfans
    uid = of_accounts[0].of_user_id
    assert uid and uid.isdigit()                                             # F of_user_id discovered via API
    health = await a.get_account_health(uid)                                 # G health (polling + live users/me)
    assert health.status == "HEALTHY" and (health.username or "").lower() == EXPECTED
    assert health.write_actions_allowed is False, "panel-side write gate must be OFF in this phase"
    sch = await a.get_scheduled_posts(uid, limit=10, offset=0)               # H schedules READ
    assert "list" in sch and "hasMore" in sch and isinstance(sch["list"], list)
    res = await connection.discover()
    assert res["CONNECTION_STATUS"] == "CONNECTED" and res["ACCOUNT_STATUS"] == "HEALTHY" and res["ACCOUNT_USERNAME"] == EXPECTED and res["PLATFORM"] == "onlyfans"
    assert res["OF_USER_ID_DISCOVERED"] is True and res["schedules_read"] is True and res["key_valid"] and res["crm_scope"] and res["error"] is None
    assert res["REAL_POSTING"] == "OFF" and res["AUTO_SCHEDULER"] == "OFF" and res["OF_REAL_WRITE_CALLS"] == 0
    saved = await connection.saved()
    assert saved["of_user_id"] == uid and await connection.of_user_id() == uid
    # M/N: ONLY GET requests left the adapter -> no proxy / account / session mutation possible
    assert spy.methods and all(m == "GET" for m, _ in spy.methods), spy.methods
    assert not any("include_session" in u or "/proxy" in u or "/login" in u or "/polling" in u and m != "GET" for m, u in spy.methods)
    assert toa.CALLS["write"] == writes_before == 0


# ------------------------------------------------------------------ I adapter isolation
def test_I_adapter_isolation():
    assert issubclass(toa.TheOnlyAPIAdapter, OFProviderAdapter)
    for m in ("test_connection", "get_account", "get_account_health", "upload_media", "create_post", "schedule_post", "get_scheduled_posts", "get_post", "delete_scheduled_post"):
        assert callable(getattr(OFProviderAdapter, m)) and callable(getattr(toa.TheOnlyAPIAdapter, m)), m
    assert connection.get_adapter().name == "THE_ONLY_API"
    src = open("/app/backend/of_autopilot/connection.py").read()
    assert "theonlyapi.com" not in src, "engine/service layer must not know vendor URLs"
    # provider swap works through the abstraction
    class Fake(OFProviderAdapter):
        name = "FAKE"
        async def test_connection(self): return {}
        async def list_accounts(self): return []
        async def get_account(self, u): raise OFProviderError("NOT_FOUND")
        async def get_account_health(self, u): raise OFProviderError("NOT_FOUND")
        async def get_scheduled_posts(self, u, limit=10, offset=0): return {"list": [], "hasMore": False}
        async def get_post(self, u, p): return {}
        async def upload_media(self, u, **k): raise OFProviderError("WRITES_DISABLED")
        async def create_post(self, u, r): raise OFProviderError("WRITES_DISABLED")
        async def schedule_post(self, u, r): raise OFProviderError("WRITES_DISABLED")
        async def delete_scheduled_post(self, u, p): raise OFProviderError("NOT_DOCUMENTED")
    connection.force_adapter(Fake())
    try:
        assert connection.get_adapter().name == "FAKE"
    finally:
        connection.force_adapter(None)


# ------------------------------------------------------------------ O/P writes blocked BEFORE any network call; contract shape of the future body
async def test_O_P_writes_blocked_without_network(monkeypatch):
    import httpx
    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("network must not be reached while OF_REAL_POSTING_ENABLED=false")
    monkeypatch.setattr(httpx.AsyncClient, "request", boom)
    monkeypatch.setenv("OF_REAL_POSTING_ENABLED", "false")
    if not (KEY and CRM):
        monkeypatch.setenv("THE_ONLY_API_KEY", "k" * 43); monkeypatch.setenv("THE_ONLY_CRM_ID", "crm_test")
    a = toa.TheOnlyAPIAdapter()
    media = OFMedia(provider_ref="p1", kind="photo", raw={"processId": "p1", "host": "convert4.onlyfans.com", "thumbId": 1, "name": "a.jpg", "extra": "x"})
    req = OFPostRequest(text="test", media=[media], scheduled_at="2030-01-01T12:00:00+00:00")
    for coro in (a.upload_media("1", file_name="a.jpg", content=b"x", content_type="image/jpeg"), a.create_post("1", req), a.schedule_post("1", req), a.delete_scheduled_post("1", "9")):
        with pytest.raises(OFProviderError) as ei:
            await coro
        assert ei.value.code == "WRITES_DISABLED"
    assert called["n"] == 0 and toa.CALLS["write"] == 0
    # future body contract: complete media object under mediaFiles, isScheduled + scheduledDate, never postedAt
    body = a._post_body(req)
    assert body["mediaFiles"] == [media.raw] and body["isScheduled"] == 1 and body["scheduledDate"] == req.scheduled_at
    assert "media" not in body and "postedAt" not in body
    # delete is NOT documented -> even with writes enabled nothing is sent
    monkeypatch.setenv("OF_REAL_POSTING_ENABLED", "true")
    with pytest.raises(OFProviderError) as ei:
        await a.delete_scheduled_post("1", "9")
    assert ei.value.code == "NOT_DOCUMENTED" and called["n"] == 0
    # read helpers never accept non-GET
    with pytest.raises(AssertionError):
        await a._request("POST", "https://theonlyapi.com/x")


async def test_verify_scheduled_fail_safe():
    class Fake(OFProviderAdapter):
        name = "FAKE"
        def __init__(self, ids): self.ids = ids
        async def test_connection(self): return {}
        async def list_accounts(self): return []
        async def get_account(self, u): return None
        async def get_account_health(self, u): return None
        async def get_scheduled_posts(self, u, limit=10, offset=0):
            page = self.ids[offset: offset + limit]
            return {"list": [{"id": i} for i in page], "hasMore": offset + limit < len(self.ids)}
        async def get_post(self, u, p): return {}
        async def upload_media(self, u, **k): return None
        async def create_post(self, u, r): return None
        async def schedule_post(self, u, r): return None
        async def delete_scheduled_post(self, u, p): return {}
    f = Fake(list(range(1, 130)))
    assert await f.verify_scheduled("u", "129", pages=5, page_size=50) is True      # SCHEDULE_CONFIRMED
    assert await f.verify_scheduled("u", "999", pages=5, page_size=50) is False     # SCHEDULE_NOT_CONFIRMED -> caller must not advance


# ------------------------------------------------------------------ J/K/L secrets backend-only, not logged, not in frontend
def test_J_K_L_secrets_hygiene(caplog):
    assert subprocess.run(["git", "check-ignore", "-q", "backend/.env"], cwd="/app").returncode == 0, "backend/.env must be git-ignored"
    if KEY:
        tracked = subprocess.run(["git", "ls-files"], cwd="/app", capture_output=True, text=True).stdout.split()
        hits = [f for f in tracked if os.path.isfile(f"/app/{f}") and KEY in open(f"/app/{f}", errors="ignore").read()]
        assert hits == [], hits
        assert subprocess.run(["grep", "-rl", KEY, "/app/frontend/src", "/app/frontend/public"], capture_output=True, text=True).stdout.strip() == ""
        assert subprocess.run(["grep", "-rl", KEY, "/var/log/supervisor/"], capture_output=True, text=True).stdout.strip() == "", "API key found in service logs"
        assert toa.scrub(f"Authorization {KEY} crm {CRM}") == f"Authorization {toa.MASK} crm {toa.MASK}"
        # logging filter redacts the key in any record
        logger = logging.getLogger("httpx")
        with caplog.at_level(logging.DEBUG):
            logger.info("HTTP Request: GET https://theonlyapi.com/x X-API-Key=%s", KEY)
        assert KEY not in caplog.text and toa.MASK in caplog.text
        # errors never carry the key
        e = OFProviderError("API_ERROR", toa.scrub(f"boom {KEY}"))
        assert KEY not in str(e)
    src = open("/app/backend/of_autopilot/providers/the_only_api.py").read()
    assert "X-API-Key" in src and "Bearer" not in src.replace("never Bearer", "") and "api_key=" not in src.lower().replace("api_key()", "")
    fe = "".join(open(f"/app/frontend/src/{p}").read() for p in ("lib/adminApi.js", "pages/admin/AdminOfAutopilot.js"))
    assert "theonlyapi.com" not in fe.lower() and "THE_ONLY_API_KEY" not in fe and "THE_ONLY_CRM_ID" not in fe and "X-API-Key" not in fe


# ------------------------------------------------------------------ admin API contract (no secrets, masked id)
def _token():
    r = requests.post(f"{BASE}/api/admin/login", json=admin_credentials(), timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def test_admin_api_contract():
    assert requests.get(f"{BASE}/api/admin/of-autopilot/connection", timeout=15).status_code in (401, 403)
    assert requests.post(f"{BASE}/api/admin/of-autopilot/test-connection", timeout=15).status_code in (401, 403)
    h = {"Authorization": f"Bearer {_token()}"}
    r = requests.get(f"{BASE}/api/admin/of-autopilot/connection", headers=h, timeout=60)
    assert r.status_code == 200
    s = r.json()
    for k in ("PROVIDER", "CONNECTION_STATUS", "ACCOUNT_STATUS", "ACCOUNT_USERNAME", "REAL_POSTING", "AUTO_SCHEDULER", "OF_REAL_WRITE_CALLS"):
        assert k in s, k
    assert s["REAL_POSTING"] == "OFF" and s["AUTO_SCHEDULER"] == "OFF" and s["OF_REAL_POSTING_ENABLED"] is False and s["OF_AUTO_SCHEDULER_ENABLED"] is False
    body = r.text
    if KEY:
        assert KEY not in body and CRM not in body
        uid = (os.environ.get("THE_ONLY_OF_USER_ID") or "").strip()
        if uid:
            assert uid not in body and s["of_user_id_masked"].endswith(uid[-3:]) and s["of_user_id_masked"].startswith("*")
        assert s["CONNECTION_STATUS"] == "CONNECTED" and s["ACCOUNT_USERNAME"] == EXPECTED and s["ACCOUNT_STATUS"] == "HEALTHY"
    for forbidden in ("sess", "auth_id", "proxy", "api_key", "apikey", "x-api-key"):
        assert forbidden not in json.dumps({k: v for k, v in s.items()}).lower(), forbidden
    # no route can enable real posting / trigger a real upload in this phase
    for ep in ("enable-real-posting", "upload", "schedule", "real-posting"):
        assert requests.post(f"{BASE}/api/admin/of-autopilot/{ep}", headers=h, timeout=15).status_code in (404, 405), ep


# ------------------------------------------------------------------ Q/R/S other autopilots unchanged (read-only snapshot comparison around a discovery)
@needs_creds
async def test_Q_R_S_other_autopilots_unchanged():
    cols = ["telegram_autopilot_state", "telegram_model_media_state", "telegram_autopilot_log", "instagram_autopilot_state", "instagram_model_media_state", "instagram_autopilot_log",
            "x_autopilot_state", "x_model_media_state", "x_autopilot_log"]
    snap = {c: [d async for d in db[c].find({}, {"_id": 0}).sort("_id", 1)] for c in cols}
    await connection.discover()
    for c in cols:
        assert [d async for d in db[c].find({}, {"_id": 0}).sort("_id", 1)] == snap[c], c
    diff = subprocess.run(["git", "status", "--short"], cwd="/app", capture_output=True, text=True).stdout
    assert not re.search(r"(telegram_autopilot|instagram_autopilot|x_autopilot|AdminTelegram|AdminInstagram|AdminXAutopilot|GlobalOfMarquee|FilmStrip)", diff), diff
