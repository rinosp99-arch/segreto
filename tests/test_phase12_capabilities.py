"""Phase 12A - Universal engine v2 (registry + dispatcher) tests. Run BEFORE wiring the router into server.py:
    cd /app && python -m pytest tests/test_phase12_capabilities.py -q -p no:cacheprovider

In-process FastAPI app that mounts ONLY caps_router (server.py untouched). Uses the preview Mongo (never production).
Mutation tests temporarily switch the preview flag ai_write_enabled -> True and ALWAYS restore READ_ONLY in teardown.
No secret is printed: keys are generated in-process and stored hashed, exactly like the real key service does.
"""
import json
import os
import sys
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

sys.path.insert(0, "/app/backend")
os.environ.setdefault("TESTING", "1")

import v1_capabilities as C  # noqa: E402
from database import api_keys_col, config_col, models_col, files_col, versions_col, ai_actions_col, seo_issues_col, idempotency_col, now_iso  # noqa: E402
from v1_security import hash_key, generate_api_key, scopes_for_role  # noqa: E402
from v1_ai_policy import approvals_col  # noqa: E402
from auth import create_token  # noqa: E402

pytestmark = pytest.mark.anyio

TAG = f"t12a-{uuid.uuid4().hex[:6]}"
_created_keys = []


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(C.caps_router)
    return app


async def _mk_key(scopes, role="AI_OPERATOR", allow=None, deny=None, rate=600):
    raw = generate_api_key()
    doc = {"id": str(uuid.uuid4()), "name": f"{TAG}-{role}", "role": role, "scopes": scopes, "key_hash": hash_key(raw), "prefix": raw[:10], "expires_at": None,
           "rate_limit_per_min": rate, "ip_allowlist": [], "source": "chatgpt", "created_at": now_iso(), "created_by": "pytest", "active": True, "uses": 0,
           "request_count": 0, "error_count": 0, "last_ip": None, "revoked_at": None, "disabled_at": None, "capability_allow": allow, "capability_deny": deny or []}
    await api_keys_col.insert_one(doc)
    _created_keys.append(doc["id"])
    return raw, doc["id"]


class _Redacted(dict):
    """Never let pytest print ephemeral test keys in tracebacks."""
    def __repr__(self):
        return "<keys redacted>"


def _h(raw):
    return {"Authorization": f"Bearer {raw}"}


async def _set_mode(full: bool):
    await config_col.update_one({"id": "global"}, {"$set": {"flags.ai_write_enabled": bool(full)}}, upsert=True)


async def _mode():
    c = await config_col.find_one({"id": "global"}, {"_id": 0, "flags": 1}) or {}
    return bool((c.get("flags") or {}).get("ai_write_enabled", False))


def _code(r):
    d = r.json().get("detail", r.json())
    return d.get("code") if isinstance(d, dict) else None


@pytest.fixture(scope="session", autouse=True)
async def _guard_read_only():
    """Whatever happens, preview ends the session in READ_ONLY exactly like production."""
    before = await _mode()
    assert before is False, "preview must start READ_ONLY"
    yield
    await _set_mode(False)
    await api_keys_col.delete_many({"id": {"$in": _created_keys}})
    await idempotency_col.delete_many({"key": {"$regex": "^v2:"}})
    # purge ONLY this run's soft-deleted test models (history of real sessions is never touched)
    ids = [m["id"] async for m in models_col.find({"nome": {"$regex": f"^Test Giulia {TAG}"}, "is_deleted": True}, {"_id": 0, "id": 1})]
    if ids:
        await models_col.delete_many({"id": {"$in": ids}})
        await versions_col.delete_many({"entity": "model", "entity_id": {"$in": ids}})
        await seo_issues_col.delete_many({"entity_id": {"$in": ids}})
        await ai_actions_col.delete_many({"session_id": f"ses_{TAG}"})
        await approvals_col.delete_many({"actor": {"$regex": TAG}})
    assert await _mode() is False


@pytest.fixture(scope="session")
async def client():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
async def keys():
    C.verify_bindings()
    full_raw, full_id = await _mk_key(scopes_for_role("SUPER_ADMIN"), role="SUPER_ADMIN")
    read_raw, _ = await _mk_key(["ai:execute", "models:read", "seo:read", "system:status", "analytics:read"], role="ANALYST")
    deny_raw, _ = await _mk_key(scopes_for_role("SUPER_ADMIN"), role="SUPER_ADMIN", allow=["models.*", "media.*"], deny=["models.publish", "media.soft_delete"])
    return _Redacted({"full": full_raw, "full_id": full_id, "read": read_raw, "deny": deny_raw})


# ---------------------------------------------------------------- registry
async def test_registry_loads_97():
    assert len(C.REGISTRY) == 97


async def test_registry_no_duplicates_and_stable_ids():
    ids = list(C.REGISTRY)
    assert len(ids) == len(set(ids))
    for cid, c in C.REGISTRY.items():
        assert c.id == cid and "." in cid and cid == cid.lower()
        assert c.version and c.version != c.handler.__name__   # version is declared, not derived from the function name
    with pytest.raises(RuntimeError):
        C.cap("models.list", "models", "dup", ["models:read"])(lambda ctx: None)


async def test_startup_verification_all_bound():
    rep = C.verify_bindings()
    assert rep["total"] == 97 and rep["unbound"] == 0 and rep["problems"] == {}
    assert all(c.status == C.BOUND for c in C.REGISTRY.values())


async def test_binding_checker_detects_bad_signature_and_module():
    assert C._check_binding("v1_seo.apply_safe_fixes(entity_id, dry_run)") is None
    assert "parametri mancanti" in C._check_binding("v1_seo.apply_safe_fixes(model_id)")
    assert "inesistente" in C._check_binding("v1_seo.does_not_exist")
    assert "non consentito" in C._check_binding("os.system")
    assert "non consentito" in C._check_binding("subprocess.run")


async def test_unbound_capability_is_blocked_not_crashing(client, keys):
    """Simulate a capability whose binding breaks at startup: it must become UNBOUND and never execute; the engine keeps working."""
    cap = C.REGISTRY["models.list"]
    C.BINDINGS["models.list"] = ["v1_models.this_function_does_not_exist"]
    try:
        rep = C.verify_bindings()
        assert cap.status == C.UNBOUND and "models.list" in rep["problems"] and rep["bound"] == 96
        r = await client.post("/api/v2/ai/execute", json={"action": "models.list"}, headers=_h(keys["full"]))
        assert r.status_code == 503 and _code(r) == "CAPABILITY_UNBOUND"
        r = await client.post("/api/v2/ai/preview", json={"action": "models.list"}, headers=_h(keys["full"]))
        assert r.status_code == 503
        cat = (await client.get("/api/v2/ai/capabilities", headers=_h(keys["full"]))).json()
        assert "models.list" not in [c["id"] for c in cat["data"]["capabilities"]]
        # another capability still works
        r = await client.post("/api/v2/ai/execute", json={"action": "settings.get"}, headers=_h(keys["full"]))
        assert r.status_code == 200 and r.json()["ok"]
    finally:
        C.BINDINGS.pop("models.list", None)
        C.verify_bindings()
        assert cap.status == C.BOUND


# ---------------------------------------------------------------- catalog / auth
async def test_catalog_requires_auth_and_lists(client, keys):
    assert (await client.get("/api/v2/ai/capabilities")).status_code == 401
    r = await client.get("/api/v2/ai/capabilities", headers=_h(keys["full"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["count"] >= 90 and d["mode"] == "READ_ONLY"
    assert all(c["risk"] != "CRITICAL" for c in d["capabilities"])
    r = await client.get("/api/v2/ai/capabilities/models.update", headers=_h(keys["full"]))
    assert r.status_code == 200 and r.json()["data"]["status"] == "BOUND" and r.json()["data"]["capability_version"]
    assert (await client.get("/api/v2/ai/capabilities/nope.x", headers=_h(keys["full"]))).status_code == 404


async def test_unknown_capability(client, keys):
    r = await client.post("/api/v2/ai/execute", json={"action": "models.hard_delete"}, headers=_h(keys["full"]))
    assert r.status_code == 404 and _code(r) == "UNKNOWN_CAPABILITY"


# ---------------------------------------------------------------- scopes / allow-deny
async def test_scope_denial_and_allow_never_broadens(client, keys):
    # read-only key: reads ok
    r = await client.post("/api/v2/ai/execute", json={"action": "models.list"}, headers=_h(keys["read"]))
    assert r.status_code == 200
    # write capability without write scope -> INSUFFICIENT_SCOPE even as preview? preview needs read scopes only -> allowed
    r = await client.post("/api/v2/ai/execute", json={"action": "models.update", "target": "francesca-rossi", "parameters": {"changes": {"badge": "x"}}}, headers=_h(keys["read"]))
    assert r.status_code == 403 and _code(r) == "INSUFFICIENT_SCOPE"
    # allow-list containing a capability the scopes don't cover must NOT grant it
    raw, _ = await _mk_key(["ai:execute", "models:read"], role="ANALYST", allow=["models.*", "settings.*"])
    r = await client.post("/api/v2/ai/execute", json={"action": "settings.update", "parameters": {"changes": {"brand_name": "X"}}}, headers=_h(raw))
    assert r.status_code == 403 and _code(r) == "INSUFFICIENT_SCOPE"
    # catalog for that key shows only what BOTH scopes and allow permit
    cat = (await client.get("/api/v2/ai/capabilities", headers=_h(raw))).json()["data"]
    ids = {c["id"] for c in cat["capabilities"]}
    assert ids and all(i.startswith("models.") for i in ids) and "settings.get" not in ids


async def test_deny_precedes_allow(client, keys):
    h = _h(keys["deny"])   # scopes *, allow models.*/media.*, deny models.publish/media.soft_delete
    r = await client.post("/api/v2/ai/preview", json={"action": "models.publish", "target": "francesca-rossi"}, headers=h)
    assert r.status_code == 403 and _code(r) == "CAPABILITY_DENIED"
    r = await client.post("/api/v2/ai/preview", json={"action": "seo.audit"}, headers=h)
    assert r.status_code == 403 and _code(r) == "CAPABILITY_NOT_ALLOWED"
    r = await client.post("/api/v2/ai/execute", json={"action": "models.get", "target": "francesca-rossi"}, headers=h)
    assert r.status_code == 200
    cat = (await client.get("/api/v2/ai/capabilities", headers=h)).json()["data"]
    ids = {c["id"] for c in cat["capabilities"]}
    assert "models.publish" not in ids and "media.soft_delete" not in ids and "seo.audit" not in ids and "models.get" in ids


# ---------------------------------------------------------------- READ_ONLY / preview / CRITICAL
async def test_read_only_blocks_mutation_but_allows_preview(client, keys):
    assert await _mode() is False
    body = {"action": "models.update", "target": "francesca-rossi", "parameters": {"changes": {"badge": f"{TAG}"}}}
    r = await client.post("/api/v2/ai/execute", json=body, headers=_h(keys["full"]))
    assert r.status_code == 403 and _code(r) == "READ_ONLY_MODE"
    before = await models_col.find_one({"slug": "francesca-rossi"}, {"_id": 0, "badge": 1, "updated_at": 1})
    r = await client.post("/api/v2/ai/preview", json=body, headers=_h(keys["full"]))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["dry_run"] is True and d["rollback"]["available"] is False and d["mode"] == "READ_ONLY"
    assert [c["field"] for c in r.json()["changes"]] == ["badge"]
    after = await models_col.find_one({"slug": "francesca-rossi"}, {"_id": 0, "badge": 1, "updated_at": 1})
    assert before == after   # nothing written
    # upload has no safe preview -> blocked even as preview in READ_ONLY
    r = await client.post("/api/v2/ai/preview", json={"action": "media.upload_url", "parameters": {"url": "https://example.com/x.jpg"}}, headers=_h(keys["full"]))
    assert r.status_code in (403, 422)


async def test_read_only_reads_ok_and_status_unwrapped(client, keys):
    r = await client.get("/api/v2/ai/status", headers=_h(keys["full"]))
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] and "data" in j and "ok" not in j["data"]   # no double envelope
    assert j["data"]["capabilities_registry"]["total"] == 97 and j["data"]["capability"] == "system.status"
    r = await client.post("/api/v2/ai/analytics/query", json={"metric": "model_views", "range": "7g"}, headers=_h(keys["full"]))
    assert r.status_code == 200 and "data" in r.json() and "summary" not in r.json()["data"]
    r = await client.post("/api/v2/ai/models/find", json={"reference": "Francesca"}, headers=_h(keys["full"]))
    assert r.status_code == 200 and r.json()["data"]["slug"] == "francesca-rossi"


async def test_unwrap_envelope_helper():
    env = {"ok": True, "action": "x", "summary": "s", "data": {"a": 1}, "warnings": ["w"], "next_steps": [], "request_id": "r"}
    u = C.unwrap_envelope(env)
    assert u == {"ok": True, "summary": "s", "data": {"a": 1}, "warnings": ["w"], "next_steps": [], "code": None}
    assert C.unwrap_envelope({"plain": 1})["data"] == {"plain": 1}
    assert C.unwrap_envelope([1, 2])["data"] == {"value": [1, 2]}


async def test_critical_never_executable_even_full(client, keys):
    fake = C.Capability(id="zz.critical_test", category="system", description="t", scopes=["config:write"], risk=C.CRITICAL, handler=None)
    C.REGISTRY[fake.id] = fake
    try:
        C.verify_bindings()
        assert fake.status == C.CRITICAL_BLOCKED
        await _set_mode(True)
        r = await client.post("/api/v2/ai/execute", json={"action": fake.id}, headers=_h(keys["full"]))
        assert r.status_code == 403 and _code(r) == "CRITICAL_ACTION_BLOCKED"
        # human admin JWT: still blocked (CRITICAL = panel only)
        tok = create_token("pytest-admin", "pytest@local", "amministratore")
        r = await client.post("/api/v2/ai/execute", json={"action": fake.id}, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403 and _code(r) == "CRITICAL_ACTION_BLOCKED"
        cat = (await client.get("/api/v2/ai/capabilities", headers=_h(keys["full"]))).json()["data"]
        assert fake.id not in {c["id"] for c in cat["capabilities"]}
    finally:
        await _set_mode(False)
        C.REGISTRY.pop(fake.id, None)


# ---------------------------------------------------------------- validation / concurrency / idempotency / approval (FULL, preview only)
async def test_param_validation(client, keys):
    r = await client.post("/api/v2/ai/preview", json={"action": "models.create", "parameters": {}}, headers=_h(keys["full"]))
    assert r.status_code == 422 and _code(r) == "VALIDATION_FAILED"
    r = await client.post("/api/v2/ai/preview", json={"action": "models.update", "target": "francesca-rossi", "parameters": {"changes": "not-an-object"}}, headers=_h(keys["full"]))
    assert r.status_code == 422 and _code(r) == "VALIDATION_FAILED"


async def test_concurrency_conflict(client, keys):
    r = await client.post("/api/v2/ai/preview", json={"action": "models.update", "target": "francesca-rossi", "parameters": {"changes": {"badge": "x"}}, "expected_updated_at": "2000-01-01T00:00:00+00:00"}, headers=_h(keys["full"]))
    assert r.status_code == 409 and _code(r) == "CONFLICT"


async def test_full_mode_execute_idempotency_approval_and_session_rollback(client, keys):
    """FULL (preview only): create -> update SAFE (idempotent replay + conflict) -> REVIEW approval flow -> media link -> seo fix -> rollback.session
    verifies business state == before while versions/audit remain."""
    await _set_mode(True)
    sid = f"ses_{TAG}"
    h = {**_h(keys["full"]), "X-Session-ID": sid}
    nome = f"Test Giulia {TAG}"
    try:
        n_models_before = await models_col.count_documents({"is_deleted": {"$ne": True}})
        # create
        r = await client.post("/api/v2/ai/execute", json={"action": "models.create", "parameters": {"nome": nome, "fields": {"categorie": ["more"]}}, "session_id": sid, "reason": "pytest"}, headers=h)
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        mid = d["id"]
        assert d["rollback"]["available"] and d["session_id"] == sid and d["mode"] == "FULL"
        assert (await models_col.find_one({"id": mid}))["stato"] != "pubblicata"
        # SAFE update with idempotency key
        ik = f"idem-{TAG}"
        body = {"action": "models.update", "target": mid, "parameters": {"changes": {"badge": "Nuova", "tag": ["estate"]}}, "session_id": sid}
        r1 = await client.post("/api/v2/ai/execute", json=body, headers={**h, "Idempotency-Key": ik})
        assert r1.status_code == 200 and r1.json()["data"]["rollback"]["available"], r1.text
        r2 = await client.post("/api/v2/ai/execute", json=body, headers={**h, "Idempotency-Key": ik})
        assert r2.status_code == 200 and r2.json()["data"].get("idempotent_replayed") is True
        assert r2.json()["data"]["rollback"]["version_ids"] == r1.json()["data"]["rollback"]["version_ids"]
        r3 = await client.post("/api/v2/ai/execute", json={**body, "parameters": {"changes": {"badge": "Altra"}}}, headers={**h, "Idempotency-Key": ik})
        assert r3.status_code == 409 and _code(r3) == "IDEMPOTENCY_CONFLICT"
        assert (await models_col.find_one({"id": mid}))["badge"] == "Nuova"   # conflict wrote nothing
        # REVIEW field -> approval required, nothing written
        r = await client.post("/api/v2/ai/execute", json={"action": "models.update", "target": mid, "parameters": {"changes": {"frase": "Il lato che non mostro."}}, "session_id": sid}, headers=h)
        assert r.status_code == 200 and r.json()["approval_required"] is True
        appr = r.json()["approval"]
        assert appr.get("token", "").startswith("apr_") and appr["capability"] == "models.update"
        assert (await models_col.find_one({"id": mid})).get("frase", "") != "Il lato che non mostro."
        # approval must not bypass READ_ONLY
        await _set_mode(False)
        r = await client.post(f"/api/v2/ai/approvals/{appr['id']}/approve", json={"token": appr["token"]}, headers=h)
        assert r.status_code == 403 and _code(r) == "READ_ONLY_MODE"
        assert (await approvals_col.find_one({"id": appr["id"]}))["status"] == "pending"   # token not consumed
        await _set_mode(True)
        # list + approve (FULL)
        lst = (await client.get("/api/v2/ai/approvals", headers=h)).json()["data"]
        assert appr["id"] in {a["id"] for a in lst["items"]}
        r = await client.post(f"/api/v2/ai/approvals/{appr['id']}/approve", json={"token": appr["token"]}, headers=h)
        assert r.status_code == 200 and r.json()["ok"], r.text
        assert (await models_col.find_one({"id": mid}))["frase"] == "Il lato che non mostro."
        r = await client.post(f"/api/v2/ai/approvals/{appr['id']}/approve", json={"token": appr["token"]}, headers=h)
        assert r.status_code in (400, 409, 410)   # single use
        # media link (secondary resource) using an existing library image
        f = await files_col.find_one({"is_deleted": {"$ne": True}, "parent_id": {"$exists": False}, "tipo": "image"}, {"_id": 0})
        assert f, "preview library needs at least one image"
        link_before = {"model_id": f.get("model_id"), "slot": f.get("slot")}
        r = await client.post("/api/v2/ai/execute", json={"action": "media.assign", "target": mid, "parameters": {"media": f["id"], "slot": "public_photo_1"}, "session_id": sid}, headers=h)
        assert r.status_code == 200, r.text
        m = await models_col.find_one({"id": mid}, {"_id": 0})
        assert any((p.get("pubblico") or {}).get("url") for p in m.get("media_pairs") or [])
        fl = await files_col.find_one({"id": f["id"]}, {"_id": 0, "model_id": 1, "slot": 1})
        assert fl["model_id"] == mid
        # seo audit + safe fix (creates/fixes issues for the new model)
        r = await client.post("/api/v2/ai/execute", json={"action": "seo.audit", "target": mid, "session_id": sid}, headers=h)
        assert r.status_code == 200
        r = await client.post("/api/v2/ai/execute", json={"action": "seo.safe_fix", "target": mid, "session_id": sid}, headers=h)
        assert r.status_code == 200
        # audit trail grouped by session
        acts = await ai_actions_col.find({"session_id": sid, "ok": True}).to_list(100)
        assert {a["action"] for a in acts} >= {"models.create", "models.update", "media.assign", "seo.audit", "seo.safe_fix"}
        n_versions = await versions_col.count_documents({"entity_id": mid})
        assert n_versions >= 3
        # rollback plan (dry) then rollback.session
        r = await client.post("/api/v2/ai/rollback", json={"session_id": sid, "dry_run": True}, headers=h)
        assert r.status_code == 200 and r.json()["data"]["dry_run"] is True and len(r.json()["data"]["plan"]) >= 3
        assert not (await models_col.find_one({"id": mid})).get("is_deleted")
        r = await client.post("/api/v2/ai/rollback", json={"session_id": sid, "reason": "annulla tutto"}, headers=h)
        assert r.status_code == 200, r.text
        rb = r.json()["data"]
        assert rb["errors"] == [], rb
        # business state == before: model gone (soft), file link restored, no open SEO issue for it, model count unchanged
        m = await models_col.find_one({"id": mid}, {"_id": 0, "is_deleted": 1})
        assert m and m.get("is_deleted") is True
        assert await models_col.count_documents({"is_deleted": {"$ne": True}}) == n_models_before
        fl = await files_col.find_one({"id": f["id"]}, {"_id": 0, "model_id": 1, "slot": 1, "is_deleted": 1})
        assert fl.get("model_id") == link_before["model_id"] and fl.get("slot") == link_before["slot"] and not fl.get("is_deleted")
        assert await seo_issues_col.count_documents({"entity_id": mid, "status": {"$in": ["open", "fixed"]}}) == 0
        assert {s["kind"] for s in rb["side_effects"]} & {"file_link_restored", "seo_issues_resolved", "file_links_cleared"}
        # history preserved: versions and audit still there, rolled_back flags set
        assert await versions_col.count_documents({"entity_id": mid}) > n_versions
        assert await versions_col.count_documents({"entity_id": mid, "rolled_back": True}) >= 3
        assert await ai_actions_col.count_documents({"session_id": sid}) >= 6
        # second rollback is idempotent
        r = await client.post("/api/v2/ai/rollback", json={"session_id": sid}, headers=h)
        assert r.status_code == 200 and all(d["action"] == "already_rolled_back" for d in r.json()["data"]["done"] if d.get("entity") != "file")
    finally:
        await _set_mode(False)
        assert await _mode() is False


async def test_reject_approval(client, keys):
    await _set_mode(True)
    try:
        r = await client.post("/api/v2/ai/execute", json={"action": "models.update", "target": "francesca-rossi", "parameters": {"changes": {"frase": f"x {TAG}"}}}, headers=_h(keys["full"]))
        assert r.status_code == 200 and r.json()["approval_required"]
        aid = r.json()["approval"]["id"]
        r = await client.post(f"/api/v2/ai/approvals/{aid}/reject", json={"reason": "no"}, headers=_h(keys["full"]))
        assert r.status_code == 200 and r.json()["data"]["status"] == "rejected"
        assert (await models_col.find_one({"slug": "francesca-rossi"})).get("frase", "") != f"x {TAG}"
    finally:
        await _set_mode(False)


# ---------------------------------------------------------------- secrets / openapi v2
async def test_zero_secret_leak(client, keys):
    blobs = []
    for path in ("/api/v2/ai/capabilities?compact=false", "/api/v2/ai/status", "/api/v2/ai/capabilities/models.update", "/api/v2/ai/approvals"):
        r = await client.get(path, headers=_h(keys["full"]))
        blobs.append(r.text)
    r = await client.post("/api/v2/ai/execute", json={"action": "config.get"}, headers=_h(keys["full"]))
    blobs.append(r.text)
    r = await client.post("/api/v2/ai/execute", json={"action": "settings.get"}, headers=_h(keys["full"]))
    blobs.append(r.text)
    text = "\n".join(blobs)
    for forbidden in (keys["full"], keys["read"], keys["deny"], hash_key(keys["full"]), os.environ.get("MONGO_URL", "mongodb://never"), os.environ.get("JWT_SECRET", "never-jwt")):
        assert forbidden not in text
    for k in ("key_hash", "token_hash", "password_hash", "jwt_secret", "mongo_url"):
        assert f'"{k}"' not in text.lower() or '"***"' in text
    acts = await ai_actions_col.find({"key_id": keys["full_id"]}, {"_id": 0}).to_list(50)
    assert acts and all("key_hash" not in json.dumps(a) for a in acts)


async def test_openapi_v2_compact_and_separate(client):
    r = await client.get("/api/v2/ai/openapi-chatgpt.json")
    assert r.status_code == 200
    spec = r.json()
    ops = [op["operationId"] for p in spec["paths"].values() for op in p.values()]
    assert len(ops) == 12 and len(set(ops)) == 12
    assert set(ops) == {"getCapabilities", "getCapability", "previewCapability", "executeCapability", "listApprovals", "approveApproval", "rejectApproval", "getJob", "queryAnalytics", "getSystemStatus", "rollback", "findModel"}
    assert all(p.startswith("/api/v2/ai/") for p in spec["paths"])
    assert "ApiKeyBearer" in spec["components"]["securitySchemes"] and spec["openapi"] == "3.1.0"
    assert "ls_" not in json.dumps(spec).replace("ls_...", "")


# =====================================================================================================================
# Phase 12A fix (found by the REAL production READ_ONLY test): preview scopes must be derived deterministically from the
# execute scopes, and optional parameters must not require their scope when absent (models.prepare_complete / media:upload).
# =====================================================================================================================
async def _counts():
    return (await models_col.count_documents({}), await versions_col.count_documents({}), await files_col.count_documents({}), await ai_actions_col.count_documents({"action": {"$regex": "^models\\.(create|update)$"}}))


async def test_preview_scopes_are_deterministic():
    from v1_ai_policy import preview_scope_for, preview_scopes
    assert preview_scope_for("media:upload") == "media:read" and preview_scope_for("jobs:execute") == "jobs:read" and preview_scope_for("categories:write") == "categories:read"
    assert preview_scope_for("models:publish") == "models:validate" and preview_scope_for("seo:safe_fix") == "seo:audit"      # explicit richer read scopes
    assert preview_scope_for("models:read") == "models:read" and preview_scope_for("ai:execute") == "ai:execute"           # read-level stay
    assert preview_scopes(["models:create", "models:update", "media:upload", "seo:safe_fix"]) == ["models:read", "media:read", "seo:audit"]
    c = C.REGISTRY["models.prepare_complete"]
    assert c.required_scopes({"nome": "x"}) == ["models:create", "models:update", "seo:safe_fix"]
    assert c.required_scopes({"nome": "x", "seo_safe_fix": False}) == ["models:create", "models:update"]
    assert "media:upload" in c.required_scopes({"nome": "x", "media": [{"media": "a", "slot": "card"}]})
    assert "media:upload" not in c.required_scopes({"nome": "x", "media": []})
    pub = c.public()
    assert pub["required_scopes_execute"] == ["models:create", "models:update"] and pub["required_scopes_preview"] == ["models:read"] and "media:upload" in pub["conditional_scopes"]


async def test_read_only_key_can_preview_prepare_complete_without_media_upload(client):
    from v1_security import AI_READ_ONLY_SCOPES
    raw, _ = await _mk_key(list(AI_READ_ONLY_SCOPES), role="AI_OPERATOR")   # the exact minimum-privilege preset of the panel
    h = _h(raw)
    before = await _counts()
    # metadata: execute none / preview preview_only (never an ambiguous access:none)
    r = await client.get("/api/v2/ai/capabilities/models.prepare_complete", headers=h)
    d = r.json()["data"]
    assert r.status_code == 200 and d["execute_access"] == "none" and d["preview_access"] == "preview_only" and d["access"] == "preview_only", d
    assert "media:upload" not in d["missing_scopes_preview"] and d["missing_scopes_execute"] == ["models:create", "models:update"]
    # catalog keeps it (preview_only) instead of hiding it
    cat = (await client.get("/api/v2/ai/capabilities", headers=h)).json()["data"]["capabilities"]
    pc = next((c for c in cat if c["id"] == "models.prepare_complete"), None)
    assert pc and pc["execute_access"] == "none" and pc["preview_access"] == "preview_only"
    # READ_ONLY + {nome} -> preview PASS, no media:upload requested
    r = await client.post("/api/v2/ai/preview", json={"action": "models.prepare_complete", "parameters": {"nome": f"TEST V2 GIULIA {TAG}"}}, headers=h)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["data"]["dry_run"] is True and r.json()["data"]["would_create"] is True and r.json()["data"]["publishes"] is False, r.text
    assert r.json()["data"]["required_scopes_preview"] == ["models:read", "seo:audit"] and "media:upload" not in json.dumps(r.json()["data"]["required_scopes_preview"])
    # READ_ONLY + {nome, fields} -> preview PASS (SAFE/REVIEW split visible, nothing applied)
    r = await client.post("/api/v2/ai/preview", json={"action": "models.prepare_complete", "parameters": {"nome": f"TEST V2 GIULIA {TAG}", "fields": {"frase": "Quello che non vedi.", "tag": ["test"], "tema": {"preset": "bordeaux"}}}}, headers=h)
    assert r.status_code == 200 and r.json()["ok"] and "frase" in r.json()["data"]["fields_review"] and "tag" in r.json()["data"]["fields_safe"], r.text
    # media present but READ_ONLY: preview allowed (media:read), media validated against the library, NOTHING fetched/uploaded
    r = await client.post("/api/v2/ai/preview", json={"action": "models.prepare_complete", "parameters": {"nome": f"TEST V2 GIULIA {TAG}", "media": [{"media": "does-not-exist-zz", "slot": "card"}, {"url": "https://example.com/x.jpg", "slot": "cover"}]}}, headers=h)
    assert r.status_code == 200 and r.json()["ok"], r.text
    mp = r.json()["data"]["media_plan"]
    assert mp[0]["found"] is False and mp[1]["url_ok"] is True and r.json()["warnings"]
    # real execute -> blocked (READ_ONLY key lacks execute scopes; server is READ_ONLY anyway)
    r = await client.post("/api/v2/ai/execute", json={"action": "models.prepare_complete", "parameters": {"nome": f"TEST V2 GIULIA {TAG}"}}, headers=h)
    assert r.status_code == 403 and _code(r) in ("INSUFFICIENT_SCOPE", "READ_ONLY_MODE")
    if _code(r) == "INSUFFICIENT_SCOPE":
        assert set(r.json()["detail"]["missing_scopes"]) >= {"models:create", "models:update"} and r.json()["detail"]["mode"] == "execute"
    # zero mutation in preview
    assert await _counts() == before
    assert not await models_col.find_one({"nome": {"$regex": f"TEST V2 GIULIA {TAG}"}})


async def test_full_mode_scope_enforcement_prepare_complete_and_approval_no_bypass(client, keys):
    """FULL (preview DB only): execute without execute scopes -> blocked; with correct scopes -> allowed (then undone);
    an approval never bypasses scopes. READ_ONLY is restored by the session guard AND here."""
    from v1_security import AI_READ_ONLY_SCOPES
    ro_raw, _ = await _mk_key(list(AI_READ_ONLY_SCOPES), role="AI_OPERATOR")
    ok_raw, ok_id = await _mk_key(["ai:execute", "models:read", "models:create", "models:update", "models:validate", "seo:audit", "seo:safe_fix", "rollback:read", "rollback:execute"], role="AI_OPERATOR")
    nome = f"TEST V2 GIULIA FULL {TAG}"
    sid = f"ses_{TAG}_v2giulia"
    appr = None
    await _set_mode(True)
    try:
        before = await _counts()
        # FULL without execute scopes -> blocked with the execute scopes listed (preview still fine)
        r = await client.post("/api/v2/ai/execute", json={"action": "models.prepare_complete", "parameters": {"nome": nome}, "session_id": sid}, headers=_h(ro_raw))
        assert r.status_code == 403 and _code(r) == "INSUFFICIENT_SCOPE" and set(r.json()["detail"]["missing_scopes"]) == {"models:create", "models:update", "seo:safe_fix"}, r.text
        assert (await client.post("/api/v2/ai/preview", json={"action": "models.prepare_complete", "parameters": {"nome": nome}}, headers=_h(ro_raw))).status_code == 200
        assert await _counts() == before
        # FULL, media passed but key lacks media:upload -> blocked BEFORE anything is created (conditional scope enforced)
        r = await client.post("/api/v2/ai/execute", json={"action": "models.prepare_complete", "parameters": {"nome": nome, "media": [{"media": "x", "slot": "card"}]}, "session_id": sid}, headers=_h(ok_raw))
        assert r.status_code == 403 and r.json()["detail"]["missing_scopes"] == ["media:upload"], r.text
        assert await _counts() == before
        # FULL with the correct execute scopes -> allowed (real draft, never published)
        r = await client.post("/api/v2/ai/execute", json={"action": "models.prepare_complete", "parameters": {"nome": nome, "fields": {"tag": ["test"], "frase": "REVIEW field"}}, "session_id": sid}, headers=_h(ok_raw))
        assert r.status_code == 200 and r.json()["ok"] and r.json()["data"]["published"] is False, r.text
        mid = r.json()["data"]["id"]
        assert r.json().get("approval_required") and r.json()["approval"].get("token")   # REVIEW field -> approval proposal
        appr = r.json()["approval"]
        # approval must NOT bypass scopes: strip models:update from the key, then approve -> 403, field untouched
        await api_keys_col.update_one({"id": ok_id}, {"$set": {"scopes": ["ai:execute", "models:read", "models:create", "models:validate", "seo:audit", "seo:safe_fix", "rollback:read", "rollback:execute"]}})
        r = await client.post(f"/api/v2/ai/approvals/{appr['id']}/approve", json={"token": appr["token"]}, headers=_h(ok_raw))
        assert r.status_code == 403 and _code(r) == "INSUFFICIENT_SCOPE", r.text
        doc = await models_col.find_one({"id": mid}, {"_id": 0, "frase": 1, "stato": 1})
        assert doc["stato"] == "bozza" and doc.get("frase") != "REVIEW field"
        # deny > allow still holds with the new access computation
        await api_keys_col.update_one({"id": ok_id}, {"$set": {"capability_allow": ["models.*"], "capability_deny": ["models.prepare_complete"]}})
        r = await client.post("/api/v2/ai/preview", json={"action": "models.prepare_complete", "parameters": {"nome": nome}}, headers=_h(ok_raw))
        assert r.status_code == 403 and _code(r) == "CAPABILITY_DENIED"
        await api_keys_col.update_one({"id": ok_id}, {"$set": {"capability_allow": None, "capability_deny": []}})
        # undo everything of the session (history kept), then purge this test's soft-deleted draft
        r = await client.post("/api/v2/ai/rollback", json={"session_id": sid}, headers=_h(ok_raw))
        assert r.status_code == 200 and not r.json()["data"]["errors"], r.text
        assert (await models_col.find_one({"id": mid}, {"_id": 0, "is_deleted": 1}) or {}).get("is_deleted") is True
    finally:
        await _set_mode(False)
        ids = [m["id"] async for m in models_col.find({"nome": nome, "is_deleted": True}, {"_id": 0, "id": 1})]
        await models_col.delete_many({"id": {"$in": ids}})
        await versions_col.delete_many({"entity_id": {"$in": ids}})
        await seo_issues_col.delete_many({"entity_id": {"$in": ids}})
        await approvals_col.delete_many({"id": appr["id"]} if appr else {"actor": {"$regex": TAG}})
    assert await _mode() is False
