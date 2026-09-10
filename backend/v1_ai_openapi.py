"""PHASE 11 - GPT Action-ready OpenAPI (sanitized view of existing /api/v1/ai endpoints).

Constraints of ChatGPT GPT Actions (verified Sept 2026): max 30 operations per Action, summary/description <= 300 chars,
parameter description <= 700 chars, JSON only, unique operationId, a `servers` entry, one clear security scheme.
This document is a READ_ONLY-first subset: reads, audits, validation, review preparation and dry-run previews.
No business logic lives here: every operation maps 1:1 to an existing route in v1_ai.py.
"""
from typing import Dict, Any, List

RESPONSE = {"$ref": "#/components/schemas/AIResponse"}
ERROR = {"$ref": "#/components/schemas/AIError"}


def _resp(desc: str = "Risposta standard {ok, summary, data, warnings, next_steps, request_id, changes, approval_required}") -> dict:
    return {
        "200": {"description": desc, "content": {"application/json": {"schema": RESPONSE}}},
        "4XX": {"description": "Errore machine-readable {ok:false, code, summary, data, request_id}", "content": {"application/json": {"schema": ERROR}}},
    }


def _op(op_id: str, summary: str, description: str, params: List[dict] = None, body: dict = None, tag: str = "System") -> dict:
    assert len(summary) <= 300 and len(description) <= 300, op_id
    o: Dict[str, Any] = {"operationId": op_id, "summary": summary, "description": description, "tags": [tag], "responses": _resp()}
    if params:
        o["parameters"] = params
    if body:
        o["requestBody"] = {"required": True, "content": {"application/json": {"schema": body}}}
    return o


def _p(name: str, where: str, desc: str, required: bool = False, typ: str = "string", enum: List[str] = None, default=None) -> dict:
    s: Dict[str, Any] = {"type": typ}
    if enum:
        s["enum"] = enum
    if default is not None:
        s["default"] = default
    return {"name": name, "in": where, "required": required, "description": desc[:700], "schema": s}


MODEL_REF = "Model reference: id, slug, exact name or an unambiguous partial name (e.g. 'Alessia'). If ambiguous the API returns 409 AMBIGUOUS_REFERENCE with data.matches: show them, never pick one yourself."
DRY = "Set true to preview only (before/proposed_after/changes, no data written). In READ_ONLY mode only dry_run:true is accepted."


def build_chatgpt_openapi(base_url: str, error_codes: List[str], mode: str) -> dict:
    paths: Dict[str, Any] = {}

    # ---------------- SYSTEM ----------------
    paths["/api/v1/ai/capabilities"] = {"get": _op("getCapabilities", "List the capabilities available to this key",
        "Use first in a session to learn available operations, your scopes, current mode (FULL/READ_ONLY) and error codes.")}
    paths["/api/v1/ai/status"] = {"get": _op("getSystemStatus", "Platform status",
        "Use when the user asks if LATO SEGRETO is online or healthy: API, database, health, open alerts, jobs, SEO counts, models by status, AI mode and your permissions.")}
    paths["/api/v1/ai/site-health"] = {"get": _op("getSiteHealth", "Overall site health",
        "Use for a site-wide check: models by status, broken media, SEO issues (safe/review/critical), sitemap, job/webhook failures, API errors, alerts, backup status.")}
    paths["/api/v1/ai/daily-summary"] = {"get": _op("getDailySummary", "Daily summary with comparisons",
        "Use when the user asks for today's recap: sessions, profile views, Italy share, funnel, OnlyFans clicks/CTR, top and declining models, SEO, media, alerts, jobs, changes, backup. Comparisons are omitted when the sample is too small.",
        [_p("fresh", "query", "true = recompute now (default)", typ="boolean", default=True)])}
    paths["/api/v1/ai/recommendations"] = {"get": _op("getRecommendations", "What should be fixed now",
        "Use when the user asks what to fix or improve. Returns deterministic recommendations computed by the platform, ordered by priority, each with automatic true/false and a capability_id to act on.",
        [_p("limit", "query", "Max items (default 30)", typ="integer", default=30)])}

    # ---------------- MODELS ----------------
    paths["/api/v1/ai/models/find"] = {"post": _op("findModel", "Resolve a model by name, slug or id",
        "Use whenever the user names a model. Returns id, slug, artistic name, workflow status and etag. Handles partial names; 409 AMBIGUOUS_REFERENCE lists candidates; 404 NOT_FOUND means it does not exist (never invent one).",
        body={"type": "object", "required": ["model"], "properties": {"model": {"type": "string", "description": MODEL_REF}}}, tag="Models")}
    paths["/api/v1/ai/models"] = {"get": _op("listModels", "List all models with workflow status",
        "Use to list models or count them by status (DRAFT, INCOMPLETE, READY, PUBLISHED, ARCHIVED, ERROR).",
        [_p("status", "query", "Filter by workflow status", enum=["DRAFT", "INCOMPLETE", "READY", "PUBLISHED", "ARCHIVED", "ERROR"])], tag="Models")}
    paths["/api/v1/ai/models/{reference}/health"] = {"get": _op("getModelHealth", "Complete health of one model",
        "Use when the user asks to check/inspect a model: publication, readiness and missing fields, SEO score and issues, media counts/ALT/broken, CTA, OnlyFans link, sitemap/noindex, redirects, analytics, recent errors, last change.",
        [_p("reference", "path", MODEL_REF, True), _p("range", "query", "Analytics period: 7g or 30g", default="7g")], tag="Models")}
    paths["/api/v1/ai/models/validate"] = {"post": _op("validateModel", "Publication readiness of a model",
        "Use to know if a model can be published and what is missing. Read-only. Returns ready, status, errors (missing fields), warnings and next steps.",
        body={"type": "object", "required": ["model"], "properties": {"model": {"type": "string", "description": MODEL_REF}}}, tag="Models")}
    paths["/api/v1/ai/models/missing"] = {"get": _op("listMissingRequirements", "Missing requirements (all models or one)",
        "Use to list which models are incomplete and what each one is missing.",
        [_p("model", "query", MODEL_REF)], tag="Models")}
    paths["/api/v1/ai/models/update"] = {"post": _op("updateModel", "Preview or apply a model change",
        "Always send dry_run:true first to show before/after. Editorial fields (bio, frase, slug, name, onlyfans_url, seo.*) need human approval (approval token). In READ_ONLY only dry_run:true works; never claim a change was applied unless ok:true and a version_id is returned.",
        body={"type": "object", "required": ["model", "changes", "dry_run"], "properties": {
            "model": {"type": "string", "description": MODEL_REF},
            "changes": {"type": "object", "description": "Fields to change (deep-merge), e.g. {\"tag\":[\"estate\"]} or {\"seo\":{\"title\":\"...\"}}", "additionalProperties": True},
            "reason": {"type": "string", "description": "Why (stored in audit)"},
            "dry_run": {"type": "boolean", "description": DRY, "default": True},
            "expected_updated_at": {"type": "string", "description": "etag from findModel to avoid overwriting concurrent edits (409 CONFLICT if stale)"}}}, tag="Models")}
    paths["/api/v1/ai/models/publish"] = {"post": _op("publishModel", "Check publishability or publish a model",
        "Use dry_run:true to check if a model would pass the publication validator. Publishing always goes through the validator (PUBLICATION_BLOCKED lists missing fields); there is no force. In READ_ONLY only dry_run:true is accepted.",
        body={"type": "object", "required": ["model", "dry_run"], "properties": {"model": {"type": "string", "description": MODEL_REF}, "dry_run": {"type": "boolean", "description": DRY, "default": True}, "reason": {"type": "string"}}}, tag="Models")}

    # ---------------- SEO ----------------
    paths["/api/v1/ai/seo/audit"] = {"post": _op("runSeoAudit", "SEO audit (one model or whole site)",
        "Use to analyze SEO issues. Does not modify data. Returns SEO score, issues grouped as SAFE_AUTO_FIX (auto-fixable), REVIEW_REQUIRED (needs approval) and CRITICAL (manual only).",
        body={"type": "object", "properties": {"model": {"type": "string", "description": MODEL_REF + " Omit for a site-wide audit."}, "scope": {"type": "string", "description": "all | models | articles | categories | landings", "default": "all"}}}, tag="SEO")}
    paths["/api/v1/ai/models/{reference}/seo/apply-safe-fixes"] = {"post": _op("previewSafeSeoFixes", "Preview (or apply) SAFE SEO fixes for a model",
        "Use when asked to fix SEO automatically. With dry_run=true shows which SAFE_AUTO_FIX issues would be corrected and the score before, without writing. REVIEW and CRITICAL issues are never touched. In READ_ONLY only dry_run=true works.",
        [_p("reference", "path", MODEL_REF, True), _p("dry_run", "query", DRY, True, "boolean", default=True)], tag="SEO")}
    paths["/api/v1/ai/models/{reference}/seo/review"] = {"get": _op("listSeoReviewIssues", "SEO issues that need human approval",
        "Use to list REVIEW_REQUIRED and CRITICAL SEO issues of a model with impact and risk. Read-only.",
        [_p("reference", "path", MODEL_REF, True)], tag="SEO")}
    paths["/api/v1/ai/models/{reference}/seo/review/{issue_id}/preview"] = {"post": _op("prepareSeoReview", "Prepare a REVIEW SEO change (preview + approval token)",
        "Use to show current vs proposed value for one REVIEW_REQUIRED issue and obtain an approval token. Nothing is applied. CRITICAL issues return CRITICAL_ACTION_BLOCKED: explain a human must act.",
        [_p("reference", "path", MODEL_REF, True), _p("issue_id", "path", "Issue id from listSeoReviewIssues", True)],
        {"type": "object", "properties": {"proposed_value": {"type": "string", "description": "Value to propose (optional if the issue has a suggestion)"}, "reason": {"type": "string"}}}, tag="SEO")}
    paths["/api/v1/ai/approvals"] = {"get": _op("listPendingApprovals", "Pending approvals prepared by this key",
        "Use to show what is waiting for human approval (type, target, before/after, expiry). Tokens are never returned here.", tag="SEO")}

    # ---------------- ANALYTICS ----------------
    paths["/api/v1/ai/analytics/query"] = {"post": _op("queryAnalytics", "Real analytics (structured query preferred)",
        "Use for traffic/conversion questions. Prefer structured fields (metric, group_by, country, period, sort, limit) over question. Never infer missing metrics: report period, filters, sample_size, data_available and limitations exactly as returned.",
        body={"type": "object", "properties": {
            "metric": {"type": "string", "description": "visits | model_views | sessions | secret_opens | cta_views | cta_clicks | onlyfans_clicks | onlyfans_ctr | conversion_rate | ctr | activation_rate | cta_view_rate"},
            "group_by": {"type": "string", "description": "model | country | region | city | device | source | day | none"},
            "period": {"type": "string", "description": "today | yesterday | 24h | 7d | 30d"},
            "country": {"type": "string", "description": "ISO country filter, e.g. IT for Italy"},
            "region": {"type": "string"}, "device": {"type": "string", "description": "mobile | desktop | tablet"}, "source": {"type": "string"},
            "model": {"type": "string", "description": MODEL_REF},
            "sort": {"type": "string", "description": "asc | desc", "default": "desc"}, "limit": {"type": "integer", "default": 10},
            "question": {"type": "string", "description": "Fallback natural question (e.g. 'traffico italiano', 'funnel') when structured fields are not applicable"}}}, tag="Analytics")}

    # ---------------- LANDINGS ----------------
    paths["/api/v1/ai/landings"] = {"post": _op("createLanding", "Preview or create an Italian editorial landing (draft)",
        "Use to draft a landing for one or more models: title, H1, intro, CTA, meta description, keywords, FAQ. Editorial Italy targeting only, never geoblocking. Send dry_run:true first. Public landing routes stay OFF in this phase.",
        body={"type": "object", "required": ["dry_run"], "properties": {
            "model": {"type": "string", "description": MODEL_REF}, "models": {"type": "array", "items": {"type": "string"}},
            "slug": {"type": "string"}, "title": {"type": "string", "description": "SEO title"}, "h1": {"type": "string"}, "hero_text": {"type": "string"}, "intro": {"type": "string"},
            "cta_text": {"type": "string"}, "cta_url": {"type": "string"}, "meta_description": {"type": "string"}, "keywords": {"type": "array", "items": {"type": "string"}},
            "noindex": {"type": "boolean", "default": False}, "faq": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "reason": {"type": "string"}, "dry_run": {"type": "boolean", "description": DRY, "default": True}}}, tag="Landings")}
    paths["/api/v1/ai/landings/{reference}"] = {"get": _op("getLanding", "Landing detail with full validation",
        "Use to read a landing (by id, slug or title) and its validation score, errors and warnings.",
        [_p("reference", "path", "Landing id, slug or title", True)], tag="Landings")}
    paths["/api/v1/ai/landings/{reference}/validate"] = {"post": _op("validateLanding", "Pre-publication validation of a landing",
        "Use to check if a landing is publishable: SEO, duplicates, slug, canonical, CTA, target models, media, accessibility, index, internal links. Read-only.",
        [_p("reference", "path", "Landing id, slug or title", True)], tag="Landings")}

    # ---------------- ROLLBACK / ACTIVITY ----------------
    paths["/api/v1/ai/rollback/preview"] = {"post": _op("previewRollback", "What a rollback would restore",
        "Use when the user asks to undo a change: shows the version (who, when, why, fields) and the values that would be restored. Nothing is changed. Executing a rollback needs the rollback:execute scope and FULL mode.",
        body={"type": "object", "properties": {"version_id": {"type": "string"}, "model": {"type": "string", "description": MODEL_REF}, "latest_ai": {"type": "boolean", "description": "true = last change made via ChatGPT/AI (default)", "default": True}, "request_id": {"type": "string"}, "actor": {"type": "string"}}}, tag="Rollback")}
    paths["/api/v1/ai/actions"] = {"get": _op("listAiActions", "Recent ChatGPT activity log",
        "Use to show what was done via the API recently: action, target, result, changes, request_id, rollback availability.",
        [_p("limit", "query", "Max items (default 50)", typ="integer", default=50)], tag="Rollback")}

    n_ops = sum(len(v) for v in paths.values())
    assert n_ops <= 30, n_ops
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "LATO SEGRETO — ChatGPT Control API (READ_ONLY-first)", "version": "1.1.0",
                 "description": (f"Sanitized GPT Action schema ({n_ops} operations) for LATO SEGRETO. Current server mode: {mode}. Auth: API Key as Bearer token "
                                 "(Authorization: Bearer <key>; header X-API-Key also accepted). Every response: {ok, summary, data, warnings, next_steps, request_id, changes, approval_required}. "
                                 "Errors: {ok:false, code, summary, data}. Use dry_run:true for previews; never state a change happened unless ok:true with a version_id.")},
        "servers": [{"url": base_url, "description": "LATO SEGRETO API"}] if base_url else [],
        "paths": paths,
        "components": {
            "securitySchemes": {"ApiKeyBearer": {"type": "http", "scheme": "bearer", "description": "API Key (ls_...) sent as Bearer token. Create/rotate it in /admin/motore → ChatGPT Control Layer."}},
            "schemas": {
                "AIResponse": {"type": "object", "properties": {
                    "ok": {"type": "boolean"}, "action": {"type": "string"}, "summary": {"type": "string", "description": "Italian human-readable summary"},
                    "data": {"type": "object", "additionalProperties": True}, "warnings": {"type": "array", "items": {"type": "string"}},
                    "next_steps": {"type": "array", "items": {"type": "string"}}, "request_id": {"type": "string"},
                    "changes": {"type": "array", "items": {"type": "object", "additionalProperties": True}}, "approval_required": {"type": "boolean"},
                    "approval": {"type": "object", "additionalProperties": True, "description": "Present when approval_required: type, token, expires_at, before, after, reason"},
                    "code": {"type": "string", "description": "Only on errors"}}},
                "AIError": {"type": "object", "properties": {
                    "ok": {"type": "boolean"}, "code": {"type": "string", "enum": error_codes}, "summary": {"type": "string"},
                    "data": {"type": "object", "additionalProperties": True}, "warnings": {"type": "array", "items": {"type": "string"}},
                    "next_steps": {"type": "array", "items": {"type": "string"}}, "request_id": {"type": "string"}, "approval_required": {"type": "boolean"}}},
            },
        },
        "security": [{"ApiKeyBearer": []}],
        "tags": [{"name": "System"}, {"name": "Models"}, {"name": "SEO"}, {"name": "Analytics"}, {"name": "Landings"}, {"name": "Rollback"}],
    }
    return spec
