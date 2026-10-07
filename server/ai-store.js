// AI interface storage: switches, API keys (hash only), activity log, versions for rollback, approvals, idempotency.
const crypto = require('crypto');
const store = require('./db');

const { db, nowIso } = store;
const sha256 = (s) => crypto.createHash('sha256').update(String(s)).digest('hex');
const json = (v) => (v == null ? null : JSON.stringify(v));
const parse = (s) => (s == null ? null : JSON.parse(s));

// ---------------- switches (config doc "ai") ----------------
// Safe defaults: the interface answers, but only reads and previews until an admin switches to FULL.
const MIN_RATE = 10; // the rate limit can be lowered or raised, never switched off
const DEFAULT_FLAGS = { ai_api_enabled: true, ai_write_enabled: false, ai_rate_limit_per_min: 120 };

function flags() {
  const f = { ...DEFAULT_FLAGS, ...(store.get('config', 'ai') || {}) };
  const limit = Math.max(MIN_RATE, Math.min(600, parseInt(f.ai_rate_limit_per_min, 10) || DEFAULT_FLAGS.ai_rate_limit_per_min));
  return {
    ai_api_enabled: f.ai_api_enabled !== false, ai_write_enabled: f.ai_write_enabled === true, ai_rate_limit_per_min: limit,
    mode: f.ai_write_enabled === true ? 'FULL' : 'READ_ONLY',
  };
}

function setFlags(input) {
  const changed = {};
  for (const k of ['ai_api_enabled', 'ai_write_enabled']) {
    if (input?.[k] == null) continue;
    if (typeof input[k] !== 'boolean') return { error: `${k} deve essere true o false` };
    changed[k] = input[k];
  }
  if (input?.ai_rate_limit_per_min != null) {
    const n = Number(input.ai_rate_limit_per_min);
    if (!Number.isInteger(n) || n < MIN_RATE || n > 600) return { error: `ai_rate_limit_per_min deve essere un intero tra ${MIN_RATE} e 600` };
    changed.ai_rate_limit_per_min = n;
  }
  store.put('config', { ...(store.get('config', 'ai') || {}), ...changed, id: 'ai', updated_at: nowIso() });
  return { changed };
}

// ---------------- scopes ----------------
const READ_ONLY_SCOPES = [
  'ai:execute', 'models:read', 'models:validate', 'media:read', 'categories:read', 'content:read', 'settings:read', 'config:read',
  'seo:read', 'seo:audit', 'analytics:read', 'system:status', 'rollback:read',
];
const FULL_SCOPES = [
  ...READ_ONLY_SCOPES, 'models:create', 'models:update', 'models:publish', 'models:unpublish', 'models:archive', 'models:feature',
  'media:upload', 'categories:write', 'content:write', 'settings:update', 'config:update', 'rollback:execute',
];
const PRESETS = { read_only: READ_ONLY_SCOPES, full: FULL_SCOPES };

// A dry run never writes, so the read scope of the same area is enough for it (old API: preview_scope_for).
const PREVIEW_SCOPE = { 'models:publish': 'models:validate' };
const READ_VERBS = new Set(['read', 'validate', 'audit', 'status']);
function previewScope(scope) {
  if (PREVIEW_SCOPE[scope]) return PREVIEW_SCOPE[scope];
  const [area, verb] = scope.split(':');
  return !verb || READ_VERBS.has(verb) || scope === 'ai:execute' ? scope : `${area}:read`;
}
const hasScope = (principal, scope) => principal.scopes.includes('*') || principal.scopes.includes(scope);
// scopes still missing; for a dry run a write scope is satisfied by its read counterpart
function missingScopes(principal, scopes, dry) {
  const out = [];
  for (const s of scopes) {
    if (hasScope(principal, s)) continue;
    const p = dry ? previewScope(s) : s;
    if (dry && hasScope(principal, p)) continue;
    if (!out.includes(p)) out.push(p);
  }
  return out;
}

// ---------------- API keys ----------------
const KEY_COLS = 'id, name, prefix, preset, scopes, created_at, created_by, last_used_at, disabled'; // never key_hash
const keyRow = (r) => (r ? { ...r, scopes: JSON.parse(r.scopes), disabled: Boolean(r.disabled) } : null);
const qKeyByHash = db.prepare(`SELECT ${KEY_COLS} FROM ai_keys WHERE key_hash = ?`);
const qKeyById = db.prepare(`SELECT ${KEY_COLS} FROM ai_keys WHERE id = ?`);
const qKeyUsed = db.prepare('UPDATE ai_keys SET last_used_at = ? WHERE id = ?');

function createKey(name, preset, createdBy) {
  const key = `ls_${crypto.randomBytes(32).toString('base64url')}`;
  const id = crypto.randomUUID();
  db.prepare('INSERT INTO ai_keys (id, name, prefix, key_hash, preset, scopes, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
    .run(id, name, key.slice(0, 9), sha256(key), preset, JSON.stringify(PRESETS[preset]), nowIso(), createdBy || null);
  return { key, record: keyRow(qKeyById.get(id)) };
}

const listKeys = () => db.prepare(`SELECT ${KEY_COLS} FROM ai_keys ORDER BY created_at DESC`).all().map(keyRow);
const findKey = (plain) => keyRow(qKeyByHash.get(sha256(plain)));
const touchKey = (id) => qKeyUsed.run(nowIso(), id);
function setKeyDisabled(id, disabled) {
  db.prepare('UPDATE ai_keys SET disabled = ? WHERE id = ?').run(disabled ? 1 : 0, id);
  return keyRow(qKeyById.get(id));
}
const deleteKey = (id) => db.prepare('DELETE FROM ai_keys WHERE id = ?').run(id).changes > 0;

// ---------------- rate limit (sliding minute, in memory, per key) ----------------
const hits = new Map();
function rateLimit(id, limit) {
  const now = Date.now();
  const list = (hits.get(id) || []).filter((t) => now - t < 60000);
  const allowed = list.length < limit;
  if (allowed) list.push(now);
  hits.set(id, list);
  return { allowed, limit, remaining: Math.max(0, limit - list.length), retryAfter: allowed ? 0 : Math.max(1, Math.ceil((60000 - (now - list[0])) / 1000)) };
}

// ---------------- activity log ----------------
// Parameters are stored redacted: no secrets, no file contents, long texts shortened.
const SECRET_KEYS = new Set(['password', 'password_hash', 'key_hash', 'token', 'token_hash', 'api_key', 'authorization', 'secret', 'jwt_secret', 'cookie']);
function redact(v, depth = 0) {
  if (typeof v === 'string') return v.length > 400 ? `${v.slice(0, 400)}… (${v.length} caratteri)` : v;
  if (Array.isArray(v)) return depth > 6 ? '[…]' : v.slice(0, 50).map((x) => redact(x, depth + 1));
  if (v && typeof v === 'object') {
    if (depth > 6) return '{…}';
    return Object.fromEntries(Object.entries(v).map(([k, x]) => {
      if (SECRET_KEYS.has(k.toLowerCase())) return [k, '***'];
      if (k === 'base64_data') return [k, '<base64>'];
      return [k, redact(x, depth + 1)];
    }));
  }
  return v;
}

const qAction = db.prepare(`INSERT INTO ai_actions (ts, request_id, key_id, key_prefix, key_name, action, target, kind, ok, code, session_id, reason, params, approval_id, summary)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
function logAction(principal, a) {
  qAction.run(nowIso(), a.request_id || null, principal?.id || null, principal?.prefix || null, principal?.name || null, a.action || null,
    a.target == null ? null : String(a.target).slice(0, 200), a.kind || 'execute', a.ok ? 1 : 0, a.code || null, a.session_id || null,
    String(a.reason || '').slice(0, 500), json(redact(a.params ?? {})), a.approval_id || null, String(a.summary || '').slice(0, 500));
}
const listActions = (limit = 20) => db.prepare('SELECT * FROM ai_actions ORDER BY id DESC LIMIT ?').all(limit)
  .map((r) => ({ ...r, ok: Boolean(r.ok), params: parse(r.params) }));

// ---------------- versions (before/after of every write, basis of the rollback) ----------------
const qVersion = db.prepare('INSERT INTO ai_versions (id, session_id, action, request_id, key_id, entity_col, entity_id, before, after, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)');
function recordVersion(v) {
  const id = crypto.randomUUID();
  qVersion.run(id, v.session_id || null, v.action, v.request_id || null, v.key_id || null, v.col, v.id, json(v.before), json(v.after), nowIso());
  return id;
}
const versionRow = (r) => (r ? { ...r, before: parse(r.before), after: parse(r.after), rolled_back: Boolean(r.rolled_back) } : null);
const getVersion = (id) => versionRow(db.prepare('SELECT * FROM ai_versions WHERE id = ?').get(id));
// newest first: a session is undone in inverse chronological order
const sessionVersions = (sessionId) => db.prepare('SELECT * FROM ai_versions WHERE session_id = ? ORDER BY rowid DESC').all(sessionId).map(versionRow);
const markRolledBack = (id) => db.prepare('UPDATE ai_versions SET rolled_back = 1 WHERE id = ?').run(id);

// ---------------- approvals (REVIEW_REQUIRED) ----------------
const APPROVAL_TTL_MIN = 30;
const payloadHash = (payload) => sha256(JSON.stringify(payload));
const approvalRow = (r) => (r ? { ...r, payload: parse(r.payload), before: parse(r.before), after: parse(r.after) } : null);
const APPROVAL_PUBLIC = 'id, key_id, action, target, before, after, reason, session_id, created_at, expires_at, status'; // never token_hash

// The token is returned once and stored as hash; the approval is bound to key + action + target + payload hash + expiry.
function createApproval(a) {
  const id = crypto.randomUUID();
  const token = `apr_${crypto.randomBytes(24).toString('base64url')}`;
  const expires = new Date(Date.now() + APPROVAL_TTL_MIN * 60000).toISOString();
  db.prepare(`INSERT INTO ai_approvals (id, token_hash, key_id, action, target, payload, payload_hash, before, after, reason, session_id, request_id, created_at, expires_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .run(id, sha256(token), a.key_id, a.action, a.target || null, JSON.stringify(a.payload), payloadHash(a.payload), json(a.before), json(a.after),
      a.reason || '', a.session_id || null, a.request_id || null, nowIso(), expires);
  return { id, token, expires_at: expires };
}
const getApproval = (id) => approvalRow(db.prepare('SELECT * FROM ai_approvals WHERE id = ?').get(id));
function pendingApprovals(keyId) {
  const sql = `SELECT ${APPROVAL_PUBLIC} FROM ai_approvals WHERE status = 'pending' AND expires_at >= ?${keyId ? ' AND key_id = ?' : ''} ORDER BY created_at DESC LIMIT 50`;
  return db.prepare(sql).all(...(keyId ? [nowIso(), keyId] : [nowIso()])).map((r) => ({ ...r, before: parse(r.before), after: parse(r.after) }));
}
const tokenMatches = (approval, token) => {
  const a = Buffer.from(approval.token_hash, 'hex');
  const b = Buffer.from(sha256(token || ''), 'hex');
  return a.length === b.length && crypto.timingSafeEqual(a, b);
};
// single use: only the first caller moves the approval out of "pending"
const closeApproval = (id, status) => db.prepare("UPDATE ai_approvals SET status = ?, used_at = ? WHERE id = ? AND status = 'pending'").run(status, nowIso(), id).changes === 1;

// ---------------- idempotency (real writes only) ----------------
const getIdempotent = (key) => db.prepare('SELECT body_hash, response FROM ai_idempotency WHERE key = ?').get(key) || null;
const saveIdempotent = (key, bodyHash, response) =>
  db.prepare('INSERT OR IGNORE INTO ai_idempotency (key, body_hash, response, created_at) VALUES (?, ?, ?, ?)').run(key, bodyHash, JSON.stringify(response), nowIso());

module.exports = {
  sha256, flags, setFlags, MIN_RATE, PRESETS, previewScope, missingScopes,
  createKey, listKeys, findKey, touchKey, setKeyDisabled, deleteKey, rateLimit,
  redact, logAction, listActions, recordVersion, getVersion, sessionVersions, markRolledBack,
  APPROVAL_TTL_MIN, payloadHash, createApproval, getApproval, pendingApprovals, tokenMatches, closeApproval,
  getIdempotent, saveIdempotent,
};
