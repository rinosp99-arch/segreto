// AI interface for a custom GPT (GPT Actions): /api/v2/ai, 12 operations, compatible with the old "v2" API.
// One dispatcher serves preview and execute, in this order:
// registry -> kill switch -> key scopes -> READ_ONLY/FULL -> rate limit -> target -> parameters -> expected_updated_at
// -> Idempotency-Key -> handler (plans, never writes) -> approval for REVIEW_REQUIRED -> writes + versions -> activity log.
// Keys, tokens and Authorization headers are never logged.
const crypto = require('crypto');
const express = require('express');
const store = require('./db');
const auth = require('./auth');
const site = require('./site');
const aiStore = require('./ai-store');
const openapi = require('./ai-openapi');
const K = require('./ai-capabilities');

const { AiError, REGISTRY, REVIEW } = K;
const router = express.Router();
const isObj = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v);

// ---------------- envelope ----------------
function envelope(req, action, summary, data = {}, extra = {}) {
  const out = {
    ok: true, action, summary, data, changes: extra.changes || [], warnings: extra.warnings || [], next_steps: extra.next_steps || [],
    approval_required: Boolean(extra.approval), rollback: extra.rollback || null, request_id: req.rid,
  };
  if (extra.approval) out.approval = extra.approval;
  return out;
}

const DEFAULT_NEXT = {
  READ_ONLY_MODE: ['Puoi eseguire letture e anteprime (dry_run=true). La modalità FULL si attiva dal pannello admin: Impostazioni → Interfaccia AI.'],
  RATE_LIMITED: ['Attendi i secondi indicati in Retry-After e riprova'],
  AI_API_DISABLED: ["L'interfaccia AI è stata disattivata dall'amministratore"],
  VALIDATION_FAILED: ['Leggi data.received e data.request_example e ripeti la chiamata corretta'],
};

function sendError(req, res, err) {
  let e = err;
  if (!(e instanceof AiError)) {
    if (e?.type === 'entity.parse.failed') e = new AiError(400, 'BAD_REQUEST', 'Il body non è JSON valido');
    else if (e?.type === 'entity.too.large') e = new AiError(413, 'VALIDATION_FAILED', 'Body troppo grande (max 15MB): per file grandi usa media.upload_url con un URL');
    else {
      console.error(`AI API ${req.method} ${req.path} [${req.rid}]:`, err?.stack || err); // path only, never headers or body
      e = new AiError(500, 'INTERNAL_ERROR', 'Errore interno');
    }
  }
  res.set(e.headers).status(e.status).json({
    ok: false, action: req.aiAction || null, code: e.code, summary: e.summary, data: e.data || {}, changes: [], warnings: [],
    next_steps: e.nextSteps.length ? e.nextSteps : DEFAULT_NEXT[e.code] || [], approval_required: false, rollback: null, request_id: req.rid,
  });
}

// async route wrapper: every failure becomes an error envelope
const route = (fn) => (req, res) => Promise.resolve().then(() => fn(req, res)).then((out) => { if (out !== undefined) res.json(out); }).catch((err) => sendError(req, res, err));

router.use((req, res, next) => {
  const given = String(req.get('X-Request-ID') || '');
  req.rid = /^[A-Za-z0-9._-]{8,64}$/.test(given) ? given : crypto.randomUUID();
  res.set({ 'X-Request-ID': req.rid, 'Cache-Control': 'no-store' });
  next();
});

// public: the schema a GPT imports (no secrets in it)
router.get('/openapi-chatgpt.json', (req, res) => res.json(openapi.build(site.baseUrl(req), aiStore.flags().mode)));

// ---------------- authentication: API key (ls_...) or admin login token ----------------
// (before the body is parsed: an unauthenticated caller cannot make the server read a large body)
router.use((req, res, next) => {
  const header = req.headers.authorization || '';
  const token = header.toLowerCase().startsWith('bearer ') ? header.slice(7).trim() : String(req.get('X-API-Key') || '').trim();
  try {
    if (!token) throw new AiError(401, 'AUTH_REQUIRED', 'Autenticazione richiesta: Authorization: Bearer <chiave API>');
    if (token.startsWith('ls_')) {
      const key = aiStore.findKey(token);
      if (!key) throw new AiError(401, 'INVALID_API_KEY', 'Chiave API non valida');
      if (key.disabled) throw new AiError(401, 'API_KEY_DISABLED', 'Chiave API disattivata');
      aiStore.touchKey(key.id);
      req.principal = { type: 'key', id: key.id, name: key.name, prefix: key.prefix, scopes: key.scopes };
    } else {
      const admin = auth.adminFromRequest(req);
      if (!admin) throw new AiError(401, 'INVALID_API_KEY', 'Chiave API non valida');
      // a logged-in admin may read, preview and inspect; the kill switch is meant for keys and does not lock the admin out
      req.principal = { type: 'admin', id: `admin:${admin.sub}`, name: admin.email, prefix: 'admin', scopes: ['*'] };
    }
    next();
  } catch (e) {
    sendError(req, res, e);
  }
});

router.use(express.json({ limit: '15mb' }));

// ---------------- shared enforcement ----------------
const isKey = (req) => req.principal.type === 'key';

function killSwitch(req, flags) {
  if (isKey(req) && !flags.ai_api_enabled) throw new AiError(503, 'AI_API_DISABLED', "Interfaccia AI disattivata dall'amministratore (kill switch)");
}

function needScopes(req, scopes, dry, extra = {}) {
  const missing = aiStore.missingScopes(req.principal, ['ai:execute', ...scopes], dry);
  if (missing.length) {
    throw new AiError(403, 'INSUFFICIENT_SCOPE', 'Permessi insufficienti', { missing_scopes: missing, ...extra },
      { next_steps: [`Chiedi all'amministratore una chiave con gli scope: ${missing.join(', ')}`, ...(dry ? [] : ['Con dry_run=true bastano gli scope di lettura (anteprima, nessuna modifica)'])] });
  }
}

function readOnlyGuard(flags) {
  if (!flags.ai_write_enabled) throw new AiError(403, 'READ_ONLY_MODE', 'Modalità READ_ONLY: sono consentite solo letture e anteprime (dry_run=true)');
}

function rateLimit(req, res, flags) {
  if (!isKey(req)) return;
  const rl = aiStore.rateLimit(req.principal.id, flags.ai_rate_limit_per_min);
  res.set({ 'X-RateLimit-Limit': String(rl.limit), 'X-RateLimit-Remaining': String(rl.remaining) });
  if (!rl.allowed) throw new AiError(429, 'RATE_LIMITED', `Troppe richieste: limite ${rl.limit} al minuto`, { retry_after: rl.retryAfter }, { headers: { 'Retry-After': String(rl.retryAfter) } });
}

// enforcement for the simple operations (catalogue, status, approvals, analytics, find)
function gate(req, res, scopes, { write = false } = {}) {
  const flags = aiStore.flags();
  killSwitch(req, flags);
  needScopes(req, scopes, false);
  if (write) readOnlyGuard(flags);
  rateLimit(req, res, flags);
  return flags;
}

// ---------------- dispatcher ----------------
const RESERVED = new Set(['action', 'capability', 'target', 'parameters', 'parameters_json', 'dry_run', 'reason', 'session_id', 'expected_updated_at', 'run_async']);
const TYPES = {
  string: (v) => typeof v === 'string', integer: (v) => Number.isInteger(v), number: (v) => typeof v === 'number' && Number.isFinite(v),
  boolean: (v) => typeof v === 'boolean', array: Array.isArray, object: isObj,
};
// actions that exist on purpose only for a human in the admin panel
const CRITICAL = /^(keys|users|admins|backup|flags|webhooks)\.|^(models\.(delete|hard_delete)|config\.(update|set)|media\.(delete|hard_delete))$/;

// GPT Actions send nested objects unreliably: accept parameters, parameters_json and declared keys at the top level.
function normalizeParameters(body, capability) {
  const notes = [];
  const received = {
    parameters: isObj(body.parameters) ? aiStore.redact(body.parameters) : null, parameters_json_present: Boolean(body.parameters_json),
    top_level_keys: Object.keys(body).filter((k) => !RESERVED.has(k)).sort(),
  };
  const bad = (summary, data = {}) => new AiError(422, 'VALIDATION_FAILED', summary, { ...data, received, request_example: K.requestExample(capability) });
  if (body.parameters != null && !isObj(body.parameters)) throw bad("'parameters' deve essere un oggetto JSON");
  const params = { ...(body.parameters || {}) };
  if (body.parameters_json) {
    let decoded;
    try { decoded = JSON.parse(String(body.parameters_json)); } catch { throw bad("'parameters_json' non è JSON valido"); }
    if (!isObj(decoded)) throw bad("'parameters_json' deve decodificare in un oggetto JSON");
    const added = Object.keys(decoded).filter((k) => !(k in params));
    for (const k of added) params[k] = decoded[k];
    if (added.length) notes.push(`parameters_json: usati ${added.sort().join(', ')}`);
  }
  const leaked = Object.keys(body).filter((k) => !RESERVED.has(k) && k in capability.params && !(k in params));
  for (const k of leaked) params[k] = body[k];
  if (leaked.length) notes.push(`Parametri ricevuti al top-level e spostati in 'parameters': ${leaked.sort().join(', ')}. Inviali dentro 'parameters'.`);
  return { params, notes, received };
}

function validateParams(capability, params) {
  const empty = (v) => v == null || v === '' || (Array.isArray(v) && !v.length) || (isObj(v) && !Object.keys(v).length);
  const missing = Object.entries(capability.params).filter(([k, spec]) => spec.required && empty(params[k])).map(([k]) => k);
  if (missing.length) return { summary: `Parametri obbligatori mancanti per '${capability.id}': ${missing.join(', ')}`, data: { missing, parameters_schema: capability.params } };
  const wrong = [];
  for (const [k, spec] of Object.entries(capability.params)) {
    const v = params[k];
    if (v == null) continue;
    if (TYPES[spec.type] && !TYPES[spec.type](v)) wrong.push({ param: k, expected: spec.type, got: Array.isArray(v) ? 'array' : typeof v });
    else if (spec.enum && !spec.enum.includes(v)) wrong.push({ param: k, expected: spec.enum.join(' | '), got: String(v).slice(0, 80) });
    else if (spec.type === 'array' && spec.items?.type && !v.every(TYPES[spec.items.type])) wrong.push({ param: k, expected: `array di ${spec.items.type}`, got: 'array misto' });
  }
  if (wrong.length) return { summary: `Parametri non validi: ${wrong.map((w) => `${w.param} (atteso ${w.expected})`).join(', ')}`, data: { wrong_types: wrong, parameters_schema: capability.params } };
  return null;
}

const clip = (v) => (typeof v === 'string' && v.length > 300 ? `${v.slice(0, 300)}… (${v.length} caratteri)` : v);
const sessionOf = (req, body) => {
  const given = String(body.session_id || req.get('X-Session-ID') || '');
  return /^[A-Za-z0-9._:-]{4,64}$/.test(given) ? given : `ses_${crypto.randomBytes(6).toString('hex')}`;
};

// Stores the planned writes of one capability call in one transaction, with a before/after version each.
function applyWrites(writes, meta, beforeApply) {
  const versionIds = [];
  store.transaction(() => {
    if (beforeApply) beforeApply();
    for (const w of writes) {
      if (w.col === 'config' && w.id === 'site') site.putSiteConfig(w.after);
      else if (w.after === null) store.del(w.col, w.id);
      else store.put(w.col, w.after);
      versionIds.push(aiStore.recordVersion({ ...meta, col: w.col, id: w.id, before: w.before, after: w.after }));
      if (w.rollbackOf) aiStore.markRolledBack(w.rollbackOf);
    }
  });
  return versionIds;
}

// options: forceDry (preview), approval (stored approval that is being confirmed)
async function run(req, res, rawBody, { forceDry = false, approval = null } = {}) {
  const body = isObj(rawBody) ? rawBody : {};
  const action = String(body.action || body.capability || '').trim();
  req.aiAction = action || null;
  const principal = req.principal;
  let audit = { action, target: body.target, kind: forceDry || body.dry_run === true ? 'dry_run' : 'execute', reason: body.reason, params: isObj(body.parameters) ? body.parameters : {} };
  const log = (ok, extra) => aiStore.logAction(principal, { ...audit, request_id: req.rid, ok, approval_id: approval?.id, ...extra });

  try {
    if (!action) {
      throw new AiError(422, 'VALIDATION_FAILED', "Campo 'action' obbligatorio (id della capability, es. models.update)",
        { missing: ['action'], received: { top_level_keys: Object.keys(body).sort() }, request_example: { action: 'models.list', parameters: {}, dry_run: true } });
    }
    // 1. registry
    const capability = REGISTRY.get(action);
    if (!capability) {
      if (CRITICAL.test(action)) throw new AiError(403, 'CRITICAL_ACTION_BLOCKED', `'${action}' è un'operazione critica: solo un amministratore dal pannello, mai via API`);
      const area = action.split('.')[0];
      throw new AiError(404, 'UNKNOWN_CAPABILITY', `Capability '${action}' inesistente`,
        { suggestions: [...REGISTRY.keys()].filter((id) => id.startsWith(`${area}.`)).slice(0, 10) }, { next_steps: ['Elenco: GET /api/v2/ai/capabilities'] });
    }
    const flags = aiStore.flags();
    // 2. kill switch
    killSwitch(req, flags);
    const { params, notes, received } = normalizeParameters(body, capability);
    const write = !capability.readOnly;
    const dry = write && (forceDry || body.dry_run === true || ['1', 'true'].includes(String(req.query.dry_run || '').toLowerCase()));
    audit = { ...audit, kind: dry || forceDry ? 'dry_run' : 'execute', params };
    // 3. scopes: a dry run only needs the read scope of the same area
    needScopes(req, capability.scopes, dry, { capability: action, mode: dry ? 'preview' : 'execute', required_scopes_execute: capability.scopes });
    // 4. READ_ONLY / FULL (an approval never turns READ_ONLY into a write)
    if (write && !dry) readOnlyGuard(flags);
    // 5. rate limit
    rateLimit(req, res, flags);
    const sessionId = sessionOf(req, body);
    audit.session_id = sessionId;

    // 6. target (natural reference). expected_updated_at is also accepted inside parameters / parameters.changes.
    let expected = body.expected_updated_at ? String(body.expected_updated_at) : null;
    for (const holder of [params, isObj(params.changes) ? params.changes : null]) {
      if (holder && 'expected_updated_at' in holder) {
        expected = expected || (holder.expected_updated_at ? String(holder.expected_updated_at) : null);
        delete holder.expected_updated_at;
      }
    }
    let target = null;
    if (capability.target !== 'none') {
      const ref = body.target || params[capability.target] || params.model;
      if (ref) target = K.resolveRef(capability.target, ref);
      else if (!capability.optionalTarget) {
        throw new AiError(422, 'VALIDATION_FAILED', `'${action}' richiede un target (${capability.target}: id, slug o nome)`, { missing: ['target'], received, request_example: K.requestExample(capability) });
      }
      if (target) audit.target = target.slug || target.id;
    }
    // 7. parameters
    const problem = validateParams(capability, params);
    if (problem) throw new AiError(422, 'VALIDATION_FAILED', problem.summary, { ...problem.data, received: { ...received, parameters_normalized: aiStore.redact(params) }, request_example: K.requestExample(capability, body.target) });
    // 8. optimistic concurrency
    const etag = K.etagOf(target);
    if (expected && etag && expected !== etag) {
      throw new AiError(409, 'CONFLICT', 'Il target è cambiato rispetto alla versione indicata (expected_updated_at)', { current_updated_at: etag, expected_updated_at: expected },
        { next_steps: ['Rileggi il target (models.get) e ripeti la modifica sulla versione attuale'] });
    }
    // 9. idempotency (real writes only; never for the confirmation of an approval)
    const idemHeader = String(req.get('Idempotency-Key') || '').slice(0, 200);
    const idemKey = idemHeader && write && !dry && !approval ? `${principal.id}:${idemHeader}` : null;
    const bodyHash = aiStore.sha256(JSON.stringify({ action, target: body.target ?? null, params, reason: body.reason ?? '', expected }));
    if (idemKey) {
      const cached = aiStore.getIdempotent(idemKey);
      if (cached) {
        if (cached.body_hash !== bodyHash) throw new AiError(409, 'IDEMPOTENCY_CONFLICT', 'Idempotency-Key già usata con un contenuto diverso', { idempotency_key: idemHeader });
        const replay = JSON.parse(cached.response);
        replay.request_id = req.rid;
        replay.data.idempotent_replayed = true;
        res.set('Idempotent-Replayed', 'true');
        return replay;
      }
    }

    // 10. handler: plans the change with the admin rules; identical for preview and execution
    const pending = capability.risk === REVIEW && !dry && !approval; // only a proposal is created
    const ctx = {
      principal, req, params, dry, target, reason: String(body.reason || ''), session_id: sessionId, base: site.baseUrl(req),
      say: (done, preview) => (dry || pending ? `Anteprima: ${preview}` : done),
    };
    const result = await capability.handler(ctx);
    const writes = result.writes || [];
    const warnings = [...(result.warnings || []), ...notes];
    const nextSteps = [...(result.next_steps || [])];
    const changes = (result.changes || []).map((c) => ({ ...c, before: clip(c.before), after: clip(c.after) }));
    const data = { ...(result.data || {}), capability: action, capability_version: capability.capability_version, risk: capability.risk, dry_run: dry, session_id: sessionId, mode: flags.mode };
    if (result.target) data.target = result.target;
    // a preview or a proposal shows the planned values, but the target (and its etag) is still the stored one
    if ((dry || pending) && writes.length) {
      data.not_applied = true;
      if (target) Object.assign(data, { target: K.targetOf(capability.target, target), ...('etag' in data ? { etag: K.etagOf(target) } : {}) });
    }
    let approvalOut = null;
    let versionIds = [];
    let summary = result.summary;

    if (dry) {
      if (writes.length) nextSteps.unshift(capability.risk === REVIEW ? 'Esegui senza dry_run per preparare la richiesta di approvazione' : 'Esegui senza dry_run per applicare');
      if (!flags.ai_write_enabled) warnings.push("Modalità READ_ONLY: l'applicazione reale richiede la modalità FULL (pannello admin)");
    } else if (pending && writes.length) {
      // 11. REVIEW_REQUIRED: nothing is written, the caller gets a single-use token bound to key + action + target + payload
      const payload = { action, target: target ? target.id : null, parameters: params, reason: ctx.reason, session_id: sessionId };
      const before = writes.map((w) => w.before);
      const made = aiStore.createApproval({
        key_id: principal.id, action, target: target ? target.slug || target.id : null, payload, before, after: writes.map((w) => w.after),
        reason: ctx.reason, session_id: sessionId, request_id: req.rid,
      });
      audit.approval_id = made.id;
      approvalOut = {
        id: made.id, approval_id: made.id, type: 'CAPABILITY', capability: action, token: made.token, expires_at: made.expires_at, target: result.target || null,
        changes, reason: ctx.reason, confirm_with: `POST /api/v2/ai/approvals/${made.id}/approve {token}`,
      };
      summary = `'${action}' richiede approvazione: nessuna modifica applicata. ${result.summary}`;
      nextSteps.unshift("Mostra all'utente prima/dopo e chiedi conferma esplicita", 'Conferma: approveApproval {token} · Rifiuto: rejectApproval');
    } else if (writes.length) {
      // an approval is only valid while the content is still what the user saw in the proposal
      if (approval && !K.same(writes.map((w) => w.before), approval.before)) {
        throw new AiError(409, 'CONFLICT', "Il contenuto è cambiato dopo l'anteprima approvata: prepara di nuovo la modifica");
      }
      // 12. writes + versions (and, for an approval, its single use) in one transaction
      versionIds = applyWrites(writes, { session_id: sessionId, action, request_id: req.rid, key_id: principal.id }, approval ? () => {
        if (!aiStore.closeApproval(approval.id, 'used')) throw new AiError(409, 'APPROVAL_INVALID', 'Approvazione già utilizzata');
      } : null);
      for (const w of writes) store.audit(`ai:${principal.name}`, action, w.col, w.id, { request_id: req.rid, session_id: sessionId });
    } else if (approval) {
      aiStore.closeApproval(approval.id, 'used'); // nothing left to change: the approval is spent anyway
    }

    // 13. rollback metadata + activity log
    const rollback = {
      available: versionIds.length > 0 && capability.rollback, version_ids: versionIds, session_id: sessionId,
      undo: versionIds.length ? `POST /api/v2/ai/rollback {session_id: '${sessionId}'}` : null,
    };
    data.rollback = rollback;
    if (approval) data.approval_id = approval.id;
    const out = envelope(req, action, summary, data, { changes, warnings, next_steps: nextSteps, approval: approvalOut, rollback });
    log(true, { summary });
    if (idemKey && !approvalOut) aiStore.saveIdempotent(idemKey, bodyHash, out); // a proposal carries a token: never stored
    return out;
  } catch (e) {
    const code = e instanceof AiError ? e.code : 'INTERNAL_ERROR';
    // refused before anything ran: not worth a log line per attempt
    if (!['AI_API_DISABLED', 'RATE_LIMITED'].includes(code)) log(false, { code, summary: e instanceof AiError ? e.summary : 'Errore interno' });
    throw e;
  }
}

// ---------------- the 12 operations ----------------
router.get('/capabilities', route((req, res) => {
  const flags = gate(req, res, []);
  const { category, q } = req.query;
  const compact = !['0', 'false'].includes(String(req.query.compact ?? 'true').toLowerCase());
  const items = [];
  for (const c of REGISTRY.values()) {
    if (category && c.category !== category) continue;
    if (q && !`${c.id} ${c.description} ${c.natural.join(' ')}`.toLowerCase().includes(String(q).toLowerCase())) continue;
    const access = K.accessFor(req.principal, c);
    if (access.access === 'none') continue;
    const d = compact
      ? { id: c.id, category: c.category, description: c.description, risk: c.risk, target: c.target, read_only: c.readOnly, parameters: Object.keys(c.params), capability_version: c.capability_version }
      : K.describe(c);
    Object.assign(d, { access: access.access, execute_access: access.execute_access, preview_access: access.preview_access });
    if (flags.mode === 'READ_ONLY' && !c.readOnly) d.read_only_note = 'Modalità READ_ONLY: solo dry_run=true';
    items.push(d);
  }
  const byCategory = {};
  for (const i of items) byCategory[i.category] = (byCategory[i.category] || 0) + 1;
  return envelope(req, 'capabilities.list', `${items.length} capability disponibili (${flags.mode})`, {
    capabilities: items, count: items.length, by_category: byCategory, mode: flags.mode,
    risk_levels: { SAFE: 'eseguita subito (FULL) o anteprima (READ_ONLY)', REVIEW_REQUIRED: 'anteprima + approvazione esplicita', CRITICAL: 'mai via API' },
    how_to: {
      preview: 'POST /api/v2/ai/preview {action, target, parameters}', execute: 'POST /api/v2/ai/execute {action, target, parameters, reason, session_id}',
      undo: 'POST /api/v2/ai/rollback {session_id}',
    },
  }, { next_steps: ['Dettaglio: GET /api/v2/ai/capabilities/{id}', 'Sempre anteprima prima di una modifica: POST /api/v2/ai/preview'] });
}));

router.get('/capabilities/:id', route((req, res) => {
  const flags = gate(req, res, []);
  const c = REGISTRY.get(req.params.id);
  if (!c) {
    const area = req.params.id.split('.')[0];
    throw new AiError(404, 'UNKNOWN_CAPABILITY', `Capability '${req.params.id}' inesistente`, { suggestions: [...REGISTRY.keys()].filter((id) => id.startsWith(`${area}.`)).slice(0, 10) });
  }
  return envelope(req, 'capabilities.get', `${c.id}: ${c.description.slice(0, 120)}`, { ...K.describe(c), ...K.accessFor(req.principal, c), mode: flags.mode });
}));

router.post('/preview', route((req, res) => run(req, res, req.body, { forceDry: true })));
router.post('/execute', route((req, res) => run(req, res, req.body)));

router.get('/approvals', route((req, res) => {
  gate(req, res, []);
  const items = aiStore.pendingApprovals(isKey(req) ? req.principal.id : null);
  return envelope(req, 'approvals.list', `${items.length} proposte in attesa`, { items, count: items.length });
}));

function ownApproval(req) {
  const a = aiStore.getApproval(req.params.id);
  if (!a) throw new AiError(404, 'NOT_FOUND', 'Approvazione non trovata');
  if (a.status !== 'pending') throw new AiError(409, 'APPROVAL_INVALID', `Approvazione già chiusa (${a.status})`);
  if (a.expires_at < store.nowIso()) {
    aiStore.closeApproval(a.id, 'expired');
    throw new AiError(410, 'APPROVAL_EXPIRED', 'Approvazione scaduta: prepara di nuovo la modifica');
  }
  return a;
}

router.post('/approvals/:id/approve', route(async (req, res) => {
  req.aiAction = 'approvals.approve';
  gate(req, res, [], { write: true }); // kill switch, READ_ONLY and rate limit before the token is even looked at
  const a = ownApproval(req);
  const token = String(req.body?.token || '');
  if (a.key_id !== req.principal.id) throw new AiError(403, 'APPROVAL_INVALID', 'Questa proposta appartiene a un\'altra chiave');
  if (!token) throw new AiError(400, 'APPROVAL_INVALID', 'Token di approvazione mancante');
  if (!aiStore.tokenMatches(a, token)) throw new AiError(403, 'APPROVAL_INVALID', 'Token di approvazione non valido');
  if (aiStore.payloadHash(a.payload) !== a.payload_hash) throw new AiError(409, 'APPROVAL_INVALID', 'La proposta approvata è stata alterata');
  // the stored payload goes through the whole dispatcher again: scopes, mode, validation and rules are re-checked
  return run(req, res, { ...a.payload, dry_run: false }, { approval: a });
}));

router.post('/approvals/:id/reject', route((req, res) => {
  req.aiAction = 'approvals.reject';
  gate(req, res, []);
  const a = ownApproval(req);
  if (isKey(req) && a.key_id !== req.principal.id) throw new AiError(403, 'APPROVAL_INVALID', 'Questa proposta appartiene a un\'altra chiave');
  if (!aiStore.closeApproval(a.id, 'rejected')) throw new AiError(409, 'APPROVAL_INVALID', 'Approvazione già chiusa');
  aiStore.logAction(req.principal, { request_id: req.rid, action: 'approvals.reject', target: a.target, ok: true, approval_id: a.id, session_id: a.session_id, reason: req.body?.reason, summary: `Proposta ${a.action} rifiutata` });
  return envelope(req, 'approvals.reject', `Proposta rifiutata: nessuna modifica applicata (${a.action})`, { approval_id: a.id, status: 'rejected' });
}));

router.get('/jobs/:id', route((req, res) => {
  req.aiAction = 'jobs.get';
  gate(req, res, []);
  throw new AiError(404, 'NOT_FOUND', 'Job non trovato: in questo sistema ogni operazione è sincrona, non esistono job', {}, { next_steps: ['Il risultato è già nella risposta di executeCapability'] });
}));

router.post('/analytics/query', route((req, res) => {
  req.aiAction = 'analytics.query';
  gate(req, res, ['analytics:read']);
  const r = K.queryAnalytics({ principal: req.principal, req }, req.body);
  return envelope(req, 'analytics.query', r.summary, { ...r.data, capability: 'analytics.query' }, { warnings: r.data.limitations });
}));

router.get('/status', route((req, res) => {
  req.aiAction = 'system.status';
  gate(req, res, ['system:status']);
  const s = K.systemStatus({ principal: req.principal, req });
  return envelope(req, 'system.status', K.statusSummary(s), { ...s, capability: 'system.status' });
}));

router.post('/rollback', route((req, res) => {
  const b = isObj(req.body) ? req.body : {};
  const common = { dry_run: b.dry_run === true, reason: b.reason };
  if (b.version_id) return run(req, res, { action: 'rollback.version', parameters: { version_id: String(b.version_id) }, ...common });
  if (b.session_id) return run(req, res, { action: 'rollback.session', parameters: { session_id: String(b.session_id) }, ...common });
  req.aiAction = 'rollback';
  throw new AiError(422, 'VALIDATION_FAILED', 'Indica version_id oppure session_id', { supported: ['version_id', 'session_id'], request_example: { session_id: 'ses_…', dry_run: true } });
}));

router.post('/models/find', route((req, res) => {
  req.aiAction = 'models.find';
  gate(req, res, ['models:read']);
  const b = isObj(req.body) ? req.body : {};
  const m = K.resolveRef('model', b.reference ?? b.model ?? b.target ?? b.name);
  const s = K.modelSummary({ base: site.baseUrl(req) }, m);
  return envelope(req, 'models.find', `Trovata: ${s.nome_artistico || s.nome} (${s.slug}, ${s.stato})`, s,
    { next_steps: ['Dettaglio: executeCapability models.get', 'Modifica: previewCapability models.update {changes}'] });
}));

router.use((req, res) => sendError(req, res, new AiError(404, 'NOT_FOUND', 'Operazione inesistente')));
router.use((err, req, res, next) => sendError(req, res, err)); // eslint-disable-line no-unused-vars

module.exports = router;
