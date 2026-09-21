"""X Autopilot — REAL connection layer (OAuth 1.0a 3-legged, encrypted token storage, identity, write gate). ZERO network: every X call is faked.
X_PROVIDER_CONNECTION · X_APP_AUTH · X_USER_AUTH · X_ACCOUNT_IDENTITY · X_SCHEDULER_OFF · secrets never leak · REAL_X_POSTS_CREATED stays 0."""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import requests

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/tests")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")
os.environ["X_AUTOPILOT_MOCK"] = "true"
os.environ["X_AUTO_SCHEDULER_ENABLED"] = "false"

from x_autopilot import adapter as xapi, xauth  # noqa: E402
from _creds import admin_credentials  # noqa: E402

pytestmark = pytest.mark.anyio
BASE = os.environ.get("TEST_BACKEND", "http://localhost:8001")
FAKE_KEY, FAKE_SECRET = "k" * 25, "s" * 50


@pytest.fixture
async def isolated(monkeypatch):
    """Fake app credentials + no network + clean auth collection (restored after)."""
    monkeypatch.setenv("X_CONSUMER_KEY", FAKE_KEY)
    monkeypatch.setenv("X_CONSUMER_SECRET", FAKE_SECRET)
    monkeypatch.setenv("X_BEARER_TOKEN", "B" * 40)
    for k in ("X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "X_OAUTH_CALLBACK_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("X_REAL_POSTING_ENABLED", "false")
    saved = [d async for d in xauth.auth_col.find({}, {"_id": 0})]
    await xauth.auth_col.delete_many({})

    async def no_net(*a, **k):
        raise AssertionError("network reached")
    monkeypatch.setattr(httpx.AsyncClient, "request", no_net)
    writes = xauth.CALLS["n"]
    yield
    assert xauth.CALLS["n"] == writes, "a REAL X write call happened"
    await xauth.auth_col.delete_many({})
    if saved:
        await xauth.auth_col.insert_many(saved)


def _resp(status, text="", headers=None, json_body=None):
    import json as _j
    body = _j.dumps(json_body) if json_body is not None else text
    return httpx.Response(status, text=body, headers=headers or {}, request=httpx.Request("GET", "https://api.x.com/x"))


def _fake_http(routes):
    async def fake(method, url, **kw):
        for key, fn in routes.items():
            if key in url:
                return fn(method, url, kw) if callable(fn) else fn
        raise AssertionError(f"unexpected X call {method} {url}")
    return fake


# ------------------------------------------------------------------ secrets hygiene + encryption at rest
async def test_scrub_and_encryption(isolated):
    tok = "TOKEN" + uuid.uuid4().hex
    xauth._loaded_secrets.add(tok)
    msg = xauth.scrub(f"key={FAKE_KEY} secret={FAKE_SECRET} tok={tok}")
    assert FAKE_KEY not in msg and FAKE_SECRET not in msg and tok not in msg and "***REDACTED***" in msg
    assert FAKE_SECRET not in str(xauth.XAuthError("X", f"boom {FAKE_SECRET}")) and FAKE_SECRET not in str(xapi.XError("X", FAKE_SECRET))
    enc = xauth.encrypt({"token": tok, "secret": "S1"})
    assert tok not in enc and xauth.decrypt(enc) == {"token": tok, "secret": "S1"}
    os.environ["X_CONSUMER_SECRET"] = "z" * 50                                   # different consumer secret -> stored tokens unreadable, never plaintext
    with pytest.raises(xauth.XAuthError) as ei:
        xauth.decrypt(enc)
    assert ei.value.code == "TOKEN_UNREADABLE"
    os.environ["X_CONSUMER_SECRET"] = FAKE_SECRET
    assert xauth.mask("1234567890") == "*******890" and xauth.mask(None) is None


def test_oauth1_headers_and_callback_url(monkeypatch):
    monkeypatch.setenv("X_CONSUMER_KEY", FAKE_KEY)
    monkeypatch.setenv("X_CONSUMER_SECRET", FAKE_SECRET)
    h = xauth._oauth1_headers("POST", xauth.REQUEST_TOKEN_URL, callback="https://h/api/admin/x-autopilot/auth/callback")
    a = h["Authorization"]
    assert a.startswith("OAuth ") and 'oauth_signature_method="HMAC-SHA1"' in a and "oauth_signature=" in a and "oauth_callback=" in a and FAKE_SECRET not in a
    h2 = xauth._oauth1_headers("POST", xauth.ACCESS_TOKEN_URL, token="rt", token_secret="REQSECRET-XYZ", verifier="v1", body="oauth_verifier=v1", content_type="application/x-www-form-urlencoded")
    assert 'oauth_token="rt"' in h2["Authorization"] and 'oauth_verifier="v1"' in h2["Authorization"] and "REQSECRET-XYZ" not in h2["Authorization"]
    monkeypatch.delenv("X_OAUTH_CALLBACK_URL", raising=False)
    assert xauth.callback_url({"X-Forwarded-Host": "secret-side.emergent.host", "host": "internal:8001"}) == "https://secret-side.emergent.host/api/admin/x-autopilot/auth/callback"
    assert xauth.callback_url({"host": "secret-side.preview.emergentagent.com"}) == "https://secret-side.preview.emergentagent.com/api/admin/x-autopilot/auth/callback"
    monkeypatch.setenv("X_OAUTH_CALLBACK_URL", "https://custom/cb")
    assert xauth.callback_url({"host": "x"}) == "https://custom/cb"
    monkeypatch.delenv("X_CONSUMER_KEY")
    with pytest.raises(xauth.XAuthError) as ei:
        xauth._oauth1_headers("GET", xauth.ME_URL)
    assert ei.value.code == "NOT_CONFIGURED"


# ------------------------------------------------------------------ APP auth (oauth2/token) — faked
async def test_app_auth_check(isolated, monkeypatch):
    seen = {}

    def token_ok(method, url, kw):
        seen["auth"] = kw["headers"]["Authorization"]
        return _resp(200, json_body={"token_type": "bearer", "access_token": "B" * 40})
    monkeypatch.setattr(xauth, "_http", _fake_http({"/oauth2/token": token_ok}))
    r = await xauth.app_auth_check()
    assert r["X_APP_AUTH_READY"] is True and r["bearer_matches_env"] is True and r["bearer_source"] == "oauth2/token" and seen["auth"].startswith("Basic ")
    assert (await xauth.auth_col.find_one({"id": "app_bearer"}))["enc"] and "B" * 40 not in str(await xauth.auth_col.find_one({"id": "app_bearer"}))
    monkeypatch.setattr(xauth, "_http", _fake_http({"/oauth2/token": _resp(403, json_body={"errors": [{"code": 99, "message": "Unable to verify your credentials"}]})}))
    r = await xauth.app_auth_check()
    assert r["X_APP_AUTH_READY"] is False and r["error"].startswith("FORBIDDEN")


# ------------------------------------------------------------------ USER auth: 3-legged flow faked end-to-end, token stored encrypted, identity READ
async def test_user_auth_flow_identity_and_report(isolated, monkeypatch):
    routes = {
        "/oauth/request_token": _resp(200, "oauth_token=REQTOK&oauth_token_secret=REQSEC&oauth_callback_confirmed=true"),
        "/oauth/access_token": _resp(200, "oauth_token=ACC-TOKEN-123&oauth_token_secret=ACC-SECRET-456&user_id=1234567890&screen_name=latosegreto"),
        "/2/users/me": _resp(200, headers={"x-access-level": "read-write"}, json_body={"data": {"id": "1234567890", "name": "Lato Segreto", "username": "latosegreto"}}),
        "/oauth2/token": _resp(200, json_body={"access_token": "B" * 40}),
    }
    monkeypatch.setattr(xauth, "_http", _fake_http(routes))
    cb = "https://secret-side.emergent.host/api/admin/x-autopilot/auth/callback"
    s = await xauth.start_user_auth(cb)
    assert s["authorize_url"] == f"{xauth.AUTHORIZE_URL}?oauth_token=REQTOK" and s["callback"] == cb
    pend = await xauth.auth_col.find_one({"id": "pending"}, {"_id": 0})
    assert pend["oauth_token"] == "REQTOK" and "REQSEC" not in str(pend)                          # request secret encrypted
    with pytest.raises(xauth.XAuthError) as ei:
        await xauth.finish_user_auth("OTHER", "v")
    assert ei.value.code == "STATE_MISMATCH"
    r = await xauth.finish_user_auth("REQTOK", "VERIFIER")
    assert r["status"] == "CONNECTED" and r["X_USERNAME"] == "latosegreto" and r["X_USER_ID_MASKED"].endswith("890") and r["X_USER_ID_MASKED"].startswith("*")
    assert r["X_WRITE_CAPABILITY_READY"] is True and r["access_level"] == "read-write" and "ACC-TOKEN-123" not in str(r) and "ACC-SECRET-456" not in str(r)
    doc = await xauth.auth_col.find_one({"id": "user_token"}, {"_id": 0})
    assert doc and "ACC-TOKEN-123" not in str(doc) and "ACC-SECRET-456" not in str(doc) and doc["username"] == "latosegreto"   # encrypted at rest
    assert await xauth.auth_col.find_one({"id": "pending"}) is None
    t, sec, src = await xauth.load_user_token()
    assert (t, sec, src) == ("ACC-TOKEN-123", "ACC-SECRET-456", "db")
    # signed user-context headers never contain the secrets
    h = await xauth.signed_headers("GET", xauth.ME_URL)
    assert 'oauth_token="ACC-TOKEN-123"' in h["Authorization"] and "ACC-SECRET-456" not in h["Authorization"]
    # RealXAdapter.check() = identity READ; connection_status() in REAL mode -> CONNECTED (masked id)
    monkeypatch.setenv("X_AUTOPILOT_MOCK", "false")
    c = await xapi.connection_status()
    assert c["CONNECTION_STATUS"] == "CONNECTED" and c["account"]["username"] == "latosegreto" and c["account"]["id"].startswith("*") and c["operational"] is True
    # full READ-ONLY report (media pre-check faked as ok via monkeypatch)
    async def fake_val(item):
        return {"ok": True, "url_ok": True, "mime": "image/jpeg", "bytes": 1000, "reason": None}
    monkeypatch.setattr(xapi, "validate_media_source", fake_val)
    rep = await xapi.real_connection_report(live=True, sample_media=[{"side": "PUBLIC", "type": "photo", "url": "https://x/a.jpg"}, {"side": "SECRET", "type": "photo", "url": "https://x/b.jpg"}])
    assert rep["X_CONNECTION_READY"] and rep["X_APP_AUTH_READY"] and rep["X_USER_AUTH_READY"] and rep["X_ACCOUNT_CONNECTED"] and rep["X_WRITE_CAPABILITY_READY"]
    assert rep["X_MEDIA_UPLOAD_READY"] and rep["X_POST_CREATE_READY"] and rep["X_THREAD_READY"] and rep["MISSING_MANUAL_STEP"] == "NONE"
    assert rep["X_USERNAME"] == "latosegreto" and rep["X_AUTOPILOT_MOCK"] is False and rep["X_REAL_POSTING_ENABLED"] is False and rep["REAL_X_POSTS_CREATED"] == 0 and rep["X_REAL_CALLS"] == 0
    body = str(rep)
    for secret in ("ACC-TOKEN-123", "ACC-SECRET-456", FAKE_SECRET, "B" * 40):
        assert secret not in body
    # read-only permissions -> manual step reported (never a write to find out)
    routes["/2/users/me"] = _resp(200, headers={"x-access-level": "read"}, json_body={"data": {"id": "1234567890", "name": "Lato Segreto", "username": "latosegreto"}})
    rep2 = await xapi.real_connection_report(live=True)
    assert rep2["X_WRITE_CAPABILITY_READY"] is False and rep2["MISSING_MANUAL_STEP"].startswith("APP_PERMISSIONS_READ_ONLY") and rep2["X_POST_CREATE_READY"] is False
    # disconnect = DB only
    assert (await xauth.disconnect())["deleted"] >= 1 and not await xauth.user_auth_present()


async def test_pending_expiry_and_callback_not_approved(isolated, monkeypatch):
    monkeypatch.setattr(xauth, "_http", _fake_http({"/oauth/request_token": _resp(403, json_body={"errors": [{"code": 415, "message": "Callback URL not approved for this client application."}]})}))
    with pytest.raises(xauth.XAuthError) as ei:
        await xauth.start_user_auth("https://h/cb")
    assert ei.value.code == "CALLBACK_NOT_APPROVED"
    with pytest.raises(xauth.XAuthError) as ei:
        await xauth.start_user_auth("")
    assert ei.value.code == "CALLBACK_MISSING"
    old = (datetime.now(timezone.utc) - timedelta(seconds=xauth.PENDING_TTL_S + 5)).isoformat()
    await xauth.auth_col.update_one({"id": "pending"}, {"$set": {"id": "pending", "oauth_token": "T", "enc": xauth.encrypt({"secret": "s"}), "created_at": old}}, upsert=True)
    with pytest.raises(xauth.XAuthError) as ei:
        await xauth.finish_user_auth("T", "v")
    assert ei.value.code == "EXPIRED" and await xauth.auth_col.find_one({"id": "pending"}) is None


# ------------------------------------------------------------------ write gate: no upload / no post while X_REAL_POSTING_ENABLED=false (before any network)
async def test_real_adapter_write_gate(isolated, monkeypatch):
    monkeypatch.setattr(xauth, "_http", _fake_http({}))                                          # any X call would raise
    a = xapi.RealXAdapter()
    for coro in (a.upload_media({"url": "https://x/a.jpg", "type": "photo", "side": "PUBLIC"}), a.create_post({"text": "t", "media_ids": ["1"]})):
        with pytest.raises(xapi.XError) as ei:
            await coro
        assert ei.value.code == "WRITES_DISABLED"
    monkeypatch.delenv("X_CONSUMER_KEY")
    with pytest.raises(xapi.XError) as ei:
        await a.create_post({"text": "t"})
    assert ei.value.code == "NOT_CONNECTED"
    assert xauth.CALLS["n"] == 0 and await xapi.real_posts_created() == 0


async def test_real_adapter_payloads_when_enabled(isolated, monkeypatch):
    """With the gate open the REAL adapter builds the documented v2 payloads (faked transport): initialize/append/finalize -> /2/tweets (+ reply)."""
    monkeypatch.setenv("X_REAL_POSTING_ENABLED", "true")
    await xauth.auth_col.update_one({"id": "user_token"}, {"$set": {"id": "user_token", "enc": xauth.encrypt({"token": "T", "secret": "S"})}}, upsert=True)
    calls = []

    async def fake_http(method, url, **kw):
        calls.append((method, url, kw.get("json_body"), kw.get("data"), kw.get("write")))
        if url.endswith("/initialize"):
            return _resp(200, json_body={"data": {"id": "MEDIA1", "media_key": "3_MEDIA1"}})
        if url.endswith("/append"):
            return _resp(204)
        if url.endswith("/finalize"):
            return _resp(200, json_body={"data": {"id": "MEDIA1", "processing_info": {"state": "succeeded"}}})
        if url.endswith("/tweets"):
            return _resp(201, json_body={"data": {"id": "999", "text": "x"}})
        raise AssertionError(url)
    monkeypatch.setattr(xauth, "_http", fake_http)

    async def fake_val(item):
        return {"ok": True, "url_ok": True, "mime": "image/jpeg", "bytes": 3, "reason": None}
    monkeypatch.setattr(xapi, "validate_media_source", fake_val)

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **k): return _resp(200, text="abc")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    a = xapi.RealXAdapter()
    mid = await a.upload_media({"url": "https://x/a.jpg", "type": "photo", "side": "PUBLIC"})
    assert mid == "MEDIA1" and calls[0][2] == {"media_type": "image/jpeg", "total_bytes": 3, "media_category": "tweet_image"} and calls[1][3] == {"segment_index": "0"}
    r = await a.create_post({"text": "ciao", "media_ids": ["MEDIA1", "MEDIA2"]})
    assert r["id"] == "999" and calls[-1][2] == {"text": "ciao", "media": {"media_ids": ["MEDIA1", "MEDIA2"]}}
    r2 = await a.create_post({"text": "reply", "media_ids": ["MEDIA2"], "in_reply_to": "999"})
    assert r2["id"] == "999" and calls[-1][2] == {"text": "reply", "media": {"media_ids": ["MEDIA2"]}, "reply": {"in_reply_to_tweet_id": "999"}}
    assert all(c[4] is True for c in calls) and len(calls) == 5                                 # every one goes through _http(write=True) -> counted as a REAL write


# ------------------------------------------------------------------ admin API contract (running server, READ-ONLY; X_AUTOPILOT_MOCK=true, scheduler OFF)
def test_admin_connection_routes_contract():
    assert requests.get(f"{BASE}/api/admin/x-autopilot/connection", timeout=15).status_code in (401, 403)
    assert requests.get(f"{BASE}/api/admin/x-autopilot/auth/status", timeout=15).status_code in (401, 403)
    for ep in ("auth/start", "auth/disconnect"):
        assert requests.post(f"{BASE}/api/admin/x-autopilot/{ep}", timeout=15).status_code in (401, 403), ep
    r = requests.get(f"{BASE}/api/admin/x-autopilot/auth/callback", timeout=15, allow_redirects=False)
    assert r.status_code == 302 and "x_auth=denied" in r.headers["location"]
    r = requests.get(f"{BASE}/api/admin/x-autopilot/auth/callback?oauth_token=nope&oauth_verifier=v", timeout=15, allow_redirects=False)
    assert r.status_code == 302 and "x_auth=error" in r.headers["location"] and "STATE_MISMATCH" in r.headers["location"]
    tok = requests.post(f"{BASE}/api/admin/login", json=admin_credentials(), timeout=15).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    a = requests.get(f"{BASE}/api/admin/x-autopilot/auth/status", headers=h, timeout=30).json()
    assert a["X_AUTOPILOT_MOCK"] is True and a["X_REAL_POSTING_ENABLED"] is False and a["REAL_X_POSTS_CREATED"] == 0
    s = requests.get(f"{BASE}/api/admin/x-autopilot/status", headers=h, timeout=60).json()
    assert s["MOCK_MODE"] is True and s["AUTO_SCHEDULER_ENABLED"] is False and s["REAL_X_POSTS_CREATED"] == 0 and s["X_REAL_CALLS"] == 0 and s["X_REAL_POSTING_ENABLED"] is False
    body = requests.get(f"{BASE}/api/admin/x-autopilot/connection?live=false", headers=h, timeout=120).text
    for k in ("X_CONSUMER_SECRET", "X_BEARER_TOKEN", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"):
        v = os.environ.get(k, "")
        if v:
            assert v not in body, k
    for forbidden in ("oauth_token_secret", '"access_token"', '"secret":', '"token":', '"enc":'):
        assert forbidden not in body.lower()
