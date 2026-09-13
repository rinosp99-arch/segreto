"""Phase 12A - GPT-Action-like contract test for previewCapability / executeCapability (HTTP, exact public OpenAPI body form).

Reproduces the real GPT flow: GET getCapability -> build the request from request_example / parameters_schema ->
POST previewCapability -> backend receives parameters.nome -> 200. Plus the tolerant fallbacks (parameters_json, alias
`capability`, leaked top-level keys), malformed JSON, nested/typed parameters integrity, same parsing on execute,
no scope/READ_ONLY/approval bypass, zero mutation. READ_ONLY only (no FULL). Never prints a key.

Run: BASE_URL=<base> python tests/phase12/gpt_action_contract_v2.py   (default: local backend)
"""
import json
import os
import sys
import uuid

import requests

sys.path.insert(0, "/app/tests")
sys.path.insert(0, "/app/backend")
from _creds import admin_credentials  # noqa: E402

BASE = os.environ.get("BASE_URL", "http://localhost:8001").rstrip("/")
S = requests.Session()
RES = []
NAME = "TEST V2 GIULIA"


def ok(name, cond, extra=""):
    RES.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  -> {str(extra)[:220]}" if not cond and extra else ""))


def j(r):
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:300]}


def code(r):
    d = j(r).get("detail", j(r))
    return d.get("code") if isinstance(d, dict) else None


creds = admin_credentials()
r = S.post(f"{BASE}/api/admin/login", json=creds, timeout=30)
assert r.status_code == 200, "admin login failed"
JWT = {"Authorization": f"Bearer {r.json().get('token') or r.json().get('access_token')}"}
from v1_security import AI_READ_ONLY_SCOPES  # noqa: E402
r = S.post(f"{BASE}/api/v1/auth/keys", json={"name": f"gptcontract-{uuid.uuid4().hex[:6]}", "role": "AI_OPERATOR", "source": "chatgpt", "scopes": list(AI_READ_ONLY_SCOPES), "rate_limit_per_min": 600}, headers=JWT, timeout=30)
assert r.status_code in (200, 201), r.text[:200]
KID, K = r.json()["id"], {"Authorization": f"Bearer {r.json()['api_key']}"}


def post(path, body, headers=None, raw=None):
    if raw is not None:
        return S.post(f"{BASE}{path}", data=raw, headers={**K, "Content-Type": "application/json"}, timeout=120)
    return S.post(f"{BASE}{path}", json=body, headers=headers or K, timeout=120)


def public_state():
    pm = j(S.get(f"{BASE}/api/models", timeout=60))
    am = j(S.get(f"{BASE}/api/admin/models", headers=JWT, timeout=60))
    items = am.get("items", am.get("models", am)) if isinstance(am, dict) else am
    return pm.get("total"), len(items), sorted(m.get("slug") for m in items)


try:
    st0 = public_state()
    # ---------------------------------------------------------------- OpenAPI contract (public document)
    spec = j(S.get(f"{BASE}/api/v2/ai/openapi-chatgpt.json", timeout=60))
    body_schema = spec["paths"]["/api/v2/ai/preview"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    ok("OpenAPI: previewCapability body requires action + parameters, parameters described with explicit example", set(body_schema["required"]) == {"action", "parameters"} and "parameters_schema" in body_schema["properties"]["parameters"]["description"] and body_schema["properties"]["parameters"].get("example") == {"nome": NAME}, body_schema.get("required"))
    ok("OpenAPI: parameters_json fallback declared as string", body_schema["properties"]["parameters_json"]["type"] == "string")
    ok("OpenAPI: executeCapability uses the same body schema", spec["paths"]["/api/v2/ai/execute"]["post"]["requestBody"]["content"]["application/json"]["schema"] == body_schema)
    ok("OpenAPI: operation descriptions <= 300 chars (GPT Actions limit), 12 operations", all(len(o.get("description", "")) <= 300 for v in spec["paths"].values() for o in v.values()) and sum(len(v) for v in spec["paths"].values()) == 12)
    ok("OpenAPI: preview/execute descriptions tell to put required fields INSIDE parameters", "INSIDE `parameters`" in spec["paths"]["/api/v2/ai/preview"]["post"]["description"] and "INSIDE `parameters`" in spec["paths"]["/api/v2/ai/execute"]["post"]["description"])
    # ---------------------------------------------------------------- GPT flow: getCapability -> request_example -> preview
    r = S.get(f"{BASE}/api/v2/ai/capabilities/models.prepare_complete", headers=K, timeout=60)
    meta = j(r)["data"]
    ex = meta.get("example_parameters") or {}
    fsch = ((meta.get("parameters_schema") or {}).get("properties") or {}).get("fields") or {}
    ok("getCapability: required_parameters=['nome'], COMPLETE example_parameters (nome + fields{frase,bio,bio_segreta,tema,regia,cta_temporizzata,messaggio_35s,seo,...} + seo_safe_fix), request_example present",
       r.status_code == 200 and meta["required_parameters"] == ["nome"] and ex.get("nome") and ex.get("seo_safe_fix") is True and set(ex.get("fields") or {}) >= {"frase", "bio", "bio_segreta", "teaser_copy", "cta_testo", "categorie", "tag", "badge", "tema", "regia", "cta_temporizzata", "messaggio_35s", "seo"}
       and meta["request_example"]["action"] == "models.prepare_complete" and meta["request_example"]["parameters"] == ex and meta["request_example"]["dry_run"] is True, {k: meta.get(k) for k in ("required_parameters",)})
    ok("getCapability: parameters_schema.fields is EXPLICIT (properties with type/description, nested tema/regia/seo/cta_temporizzata/messaggio_35s, enums/ranges)",
       fsch.get("type") == "object" and set(fsch.get("properties") or {}) >= {"frase", "bio", "bio_segreta", "tema", "regia", "cta_temporizzata", "messaggio_35s", "seo", "categorie", "tag", "badge", "teaser_copy", "cta_testo", "slug", "nome_artistico", "pellicola_home", "social", "onlyfans_url"}
       and "properties" in fsch["properties"]["regia"] and "properties" in fsch["properties"]["seo"] and fsch["properties"]["regia"]["properties"]["fumo"].get("maximum") == 100 and "enum" in fsch["properties"]["badge"] and "og_image" not in fsch["properties"]["seo"]["properties"] and "stato" not in fsch["properties"], sorted(fsch.get("properties") or {}))
    ok("getCapability: how_to_call + execute_access none / preview_access preview_only for READ_ONLY key", "parameters" in meta.get("how_to_call", "") and meta["execute_access"] == "none" and meta["preview_access"] == "preview_only")
    req = dict(meta["request_example"])            # exactly what a GPT copies
    req["reason"] = "gpt contract test"
    r = post("/api/v2/ai/preview", req)
    A = j(r)
    ok("A. previewCapability with request_example (parameters.nome + full fields) -> 200 dry_run, publishes=false, every field classified SAFE or REVIEW (none silently lost)", r.status_code == 200 and A.get("ok") and A["data"]["dry_run"] is True and ex["nome"] in A["summary"] and A["data"]["publishes"] is False and not A["data"].get("fields_dropped") and len(A["data"].get("fields_safe_paths", [])) >= 25 and len(A["data"].get("fields_review_paths", [])) >= 5, r.text[:300])
    # user's exact body form (capability alias + target null + session_id null)
    r = post("/api/v2/ai/preview", {"capability": "models.prepare_complete", "target": None, "parameters": {"nome": NAME}, "dry_run": True, "reason": "...", "session_id": None})
    ok("A2. user body form {capability, target:null, parameters:{nome}, dry_run, reason, session_id:null} -> 200", r.status_code == 200 and j(r).get("ok") and j(r)["action"] == "models.prepare_complete", r.text[:200])
    # ---------------------------------------------------------------- B. missing nome -> 422 with received body echoed + request_example
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters": {}, "dry_run": True})
    B = j(r)
    det = B.get("data", B)
    ok("B. missing nome -> 422 VALIDATION_FAILED missing=['nome'] + received body echoed + request_example", r.status_code == 422 and code(r) == "VALIDATION_FAILED" and det.get("missing") == ["nome"] and det.get("received", {}).get("parameters") == {} and (det.get("request_example", {}).get("parameters") or {}).get("nome") and "fields" in det.get("request_example", {}).get("parameters", {}), r.text[:300])
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "dry_run": True})
    ok("B2. parameters absent entirely -> 422 missing=['nome'] (received.parameters=null)", r.status_code == 422 and j(r).get("data", {}).get("missing") == ["nome"] and j(r)["data"]["received"]["parameters"] is None, r.text[:200])
    # audited with the received body (redacted): visible in the activity log
    acts = j(S.get(f"{BASE}/api/v1/ai/actions?limit=10", headers=K, timeout=60)).get("data", {})
    acts = acts.get("items") or acts.get("actions") or []
    ok("B3. validation failure audited with received body (ai_actions)", any(a.get("action") == "models.prepare_complete" and a.get("ok") is False and "received" in json.dumps(a) for a in acts), [a.get("action") for a in acts][:5])
    # ---------------------------------------------------------------- C. nested fields arrive intact
    fields = {"frase": "Quello che non vedi.", "tag": ["test", "v2"], "tema": {"preset": "bordeaux"}, "cta_testo": "ENTRA", "categorie": ["more"]}
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters": {"nome": NAME, "fields": fields}, "dry_run": True})
    C = j(r)
    ok("C. fields nested object arrives intact (SAFE/REVIEW split over all keys)", r.status_code == 200 and set(C["data"]["fields_safe"]) | set(C["data"]["fields_review"]) == set(fields), r.text[:200])
    # ---------------------------------------------------------------- D. media array intact, no download / no mutation in READ_ONLY
    media = [{"url": "https://example.com/giulia.jpg", "slot": "card", "alt": "Giulia"}, {"media": "does-not-exist-zz", "slot": "secret_photo_1"}]
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters": {"nome": NAME, "media": media}, "dry_run": True})
    D = j(r)
    mp = D.get("data", {}).get("media_plan", [])
    ok("D. media array arrives intact in preview (2 items, slots parsed, url syntax-only, unknown media flagged), nothing fetched", r.status_code == 200 and len(mp) == 2 and mp[0]["url_ok"] is True and mp[0]["technical_slot"] and mp[1]["found"] is False and D.get("warnings"), r.text[:300])
    # ---------------------------------------------------------------- E. boolean / integer / array / nested object integrity
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters": {"nome": NAME, "seo_safe_fix": False, "fields": {"tag": ["a", "b"], "tema": {"preset": "bordeaux", "accent": "#7a1f2b"}}}, "dry_run": True})
    E = j(r)
    ok("E. boolean false honoured (seo_safe_fix=false -> no seo.safe_fix step, seo:safe_fix not required)", r.status_code == 200 and E["data"]["seo_safe_fix"] is False and "seo.safe_fix" not in E["data"]["plan"] and "seo:safe_fix" not in E["data"]["required_scopes_execute"], r.text[:200])
    r = post("/api/v2/ai/preview", {"action": "models.list", "parameters": {"limit": 3, "stato": "pubblicata"}, "dry_run": True})
    ok("E2. integer/string parameters honoured on a read capability (models.list limit=3)", r.status_code == 200 and len(j(r)["data"]["items"]) <= 3, r.text[:160])
    r = post("/api/v2/ai/preview", {"action": "models.list", "parameters": {"limit": "three"}, "dry_run": True})
    ok("E3. wrong type -> 422 VALIDATION_FAILED wrong_types", r.status_code == 422 and code(r) == "VALIDATION_FAILED" and j(r)["data"].get("wrong_types"), r.text[:160])
    # ---------------------------------------------------------------- F. executeCapability uses exactly the same parsing (dry_run true)
    r = post("/api/v2/ai/execute", {"capability": "models.prepare_complete", "parameters_json": json.dumps({"nome": NAME}), "parameters": {}, "dry_run": True})
    F = j(r)
    ok("F. executeCapability same parsing (alias + parameters_json, dry_run=true) -> 200 preview", r.status_code == 200 and F.get("ok") and F["data"]["dry_run"] is True and NAME in F["summary"], r.text[:200])
    r = post("/api/v2/ai/execute", {"action": "models.prepare_complete", "parameters": {}, "dry_run": True})
    ok("F2. executeCapability missing nome -> same 422", r.status_code == 422 and j(r)["data"].get("missing") == ["nome"])
    # ---------------------------------------------------------------- G. parameters_json fallback
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters_json": json.dumps({"nome": NAME, "fields": {"tag": ["x"]}}), "dry_run": True})
    G = j(r)
    ok("G. parameters_json fallback -> 200, nested fields decoded", r.status_code == 200 and G.get("ok") and G["data"]["fields_safe"] == ["tag"], r.text[:200])
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters": {"nome": NAME}, "parameters_json": json.dumps({"nome": "OTHER NAME"}), "dry_run": True})
    ok("G2. both present -> parameters wins", r.status_code == 200 and NAME in j(r)["summary"] and "OTHER" not in j(r)["summary"], r.text[:160])
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "nome": NAME, "dry_run": True})
    G3 = j(r)
    ok("G3. leaked top-level declared key hoisted into parameters (+ warning teaching the right form)", r.status_code == 200 and G3.get("ok") and NAME in G3["summary"] and any("parameters" in w for w in G3.get("warnings", [])), r.text[:200])
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters": {"nome": NAME}, "shell": "rm -rf /", "__proto__": {"x": 1}, "dry_run": True})
    ok("G4. unknown top-level keys are ignored (never hoisted)", r.status_code == 200 and "shell" not in json.dumps(j(r)["data"]))
    # ---------------------------------------------------------------- H. malformed JSON -> 422
    r = post("/api/v2/ai/preview", None, raw='{"action": "models.prepare_complete", "parameters": {"nome": "TEST V2 GIULIA"')
    ok("H. malformed request JSON -> 422", r.status_code == 422, (r.status_code, r.text[:120]))
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters_json": '{"nome": ', "dry_run": True})
    ok("H2. malformed parameters_json -> 422 VALIDATION_FAILED", r.status_code == 422 and code(r) == "VALIDATION_FAILED" and "parameters_json" in r.text, r.text[:160])
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters_json": '["nome"]', "dry_run": True})
    ok("H3. parameters_json not an object -> 422", r.status_code == 422 and code(r) == "VALIDATION_FAILED")
    r = post("/api/v2/ai/preview", {"action": "models.prepare_complete", "parameters": "nome=TEST", "dry_run": True})
    ok("H4. parameters as a plain string -> 422", r.status_code == 422)
    r = post("/api/v2/ai/preview", {"parameters": {"nome": NAME}, "dry_run": True})
    ok("H5. action/capability absent -> 422 missing=['action']", r.status_code == 422 and j(r)["data"].get("missing") == ["action"], r.text[:160])
    # ---------------------------------------------------------------- I. no bypass: scopes / READ_ONLY / approval
    r = post("/api/v2/ai/execute", {"action": "models.prepare_complete", "parameters_json": json.dumps({"nome": NAME}), "parameters": {}})
    ok("I. real execute via parameters_json -> still blocked (READ_ONLY key: INSUFFICIENT_SCOPE / READ_ONLY_MODE)", r.status_code == 403 and code(r) in ("INSUFFICIENT_SCOPE", "READ_ONLY_MODE"), r.text[:160])
    r = post("/api/v2/ai/execute", {"action": "models.prepare_complete", "parameters": {"nome": NAME, "media": [{"media": "x", "slot": "card"}]}})
    ok("I2. media present on real execute -> conditional media:upload still required (blocked)", r.status_code == 403, r.text[:160])
    r = post("/api/v2/ai/execute", {"action": "models.update", "target": st0[2][0] if st0[2] else "x", "changes": {"badge": "leak"}})
    ok("I3. leaked `changes` on real execute -> normalized then blocked by READ_ONLY/scope (no write)", r.status_code == 403, r.text[:160])
    r = post("/api/v2/ai/preview", {"action": "models.publish", "target": st0[2][0] if st0[2] else "x", "parameters": {}})
    ok("I4. approval path untouched: REVIEW/validate preview still works or is scope-limited, never executes", r.status_code in (200, 403, 422) and not (j(r).get("ok") and (j(r).get("data") or {}).get("rollback", {}).get("available")), r.text[:120])
    # ---------------------------------------------------------------- J. zero mutation
    st1 = public_state()
    ok("J. zero mutation: public total, admin count and slugs identical; no TEST V2 GIULIA", st0 == st1 and not any("giulia" in s and "v2" in s for s in st1[2]), (st0[:2], st1[:2]))
finally:
    rr = S.delete(f"{BASE}/api/v1/auth/keys/{KID}", headers=JWT, timeout=30)
    ok("temp key revoked", rr.status_code in (200, 204))
    try:
        sys.path.insert(0, "/app/backend")
        import asyncio
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        from database import api_keys_col
        if BASE.startswith("http://localhost"):
            asyncio.new_event_loop().run_until_complete(api_keys_col.delete_many({"id": KID}))
    except Exception:
        pass

n = sum(1 for _, p in RES if p)
print(f"\nGPT-ACTION CONTRACT: {n}/{len(RES)} -> {'PASS' if n == len(RES) else 'FAIL'}")
json.dump({"base": BASE, "pass": n, "total": len(RES), "results": [{"check": c, "result": "PASS" if p else "FAIL"} for c, p in RES]}, open("/app/test_reports/phase12a_gpt_action_contract.json", "w"), indent=1)
sys.exit(0 if n == len(RES) else 1)
