// SQLite storage (built into Node 22+). Content is stored as JSON documents, same shape as the old API returns.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { DatabaseSync } = require('node:sqlite');

const DATA_DIR = path.resolve(process.env.DATA_DIR || path.join(__dirname, '..', 'data'));
const UPLOADS_DIR = path.join(DATA_DIR, 'uploads');
fs.mkdirSync(UPLOADS_DIR, { recursive: true });

const db = new DatabaseSync(path.join(DATA_DIR, 'lato.db'));
db.exec(`
  PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS docs (col TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (col, id));
  CREATE TABLE IF NOT EXISTS admins (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, entity TEXT, entity_id TEXT, meta TEXT);
  CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, tipo TEXT NOT NULL,
    model_id TEXT, model_slug TEXT, session_id TEXT, visit_id TEXT, data TEXT
  );
  CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
  CREATE INDEX IF NOT EXISTS events_tipo_model ON events (tipo, model_id);

  -- AI interface (/api/v2/ai): keys are stored as SHA-256 hash only, the plain key is never written anywhere
  CREATE TABLE IF NOT EXISTS ai_keys (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, prefix TEXT NOT NULL, key_hash TEXT UNIQUE NOT NULL, preset TEXT, scopes TEXT NOT NULL,
    created_at TEXT NOT NULL, created_by TEXT, last_used_at TEXT, disabled INTEGER NOT NULL DEFAULT 0
  );
  CREATE TABLE IF NOT EXISTS ai_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, request_id TEXT, key_id TEXT, key_prefix TEXT, key_name TEXT,
    action TEXT, target TEXT, kind TEXT, ok INTEGER, code TEXT, session_id TEXT, reason TEXT, params TEXT, approval_id TEXT, summary TEXT
  );
  CREATE INDEX IF NOT EXISTS ai_actions_session ON ai_actions (session_id);
  CREATE TABLE IF NOT EXISTS ai_versions (
    id TEXT PRIMARY KEY, session_id TEXT, action TEXT, request_id TEXT, key_id TEXT, entity_col TEXT NOT NULL, entity_id TEXT NOT NULL,
    before TEXT, after TEXT, ts TEXT NOT NULL, rolled_back INTEGER NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS ai_versions_session ON ai_versions (session_id);
  CREATE TABLE IF NOT EXISTS ai_approvals (
    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, key_id TEXT NOT NULL, action TEXT NOT NULL, target TEXT, payload TEXT NOT NULL,
    payload_hash TEXT NOT NULL, before TEXT, after TEXT, reason TEXT, session_id TEXT, request_id TEXT,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', used_at TEXT
  );
  CREATE TABLE IF NOT EXISTS ai_idempotency (key TEXT PRIMARY KEY, body_hash TEXT NOT NULL, response TEXT NOT NULL, created_at TEXT NOT NULL);
`);

const nowIso = () => new Date().toISOString();
const uuid = () => crypto.randomUUID();

// ---- documents (models, categories, articles, settings, landings, redirects, config) ----
const qAll = db.prepare('SELECT data FROM docs WHERE col = ? ORDER BY rowid');
const qGet = db.prepare('SELECT data FROM docs WHERE col = ? AND id = ?');
const qPut = db.prepare('INSERT INTO docs (col, id, data) VALUES (?, ?, ?) ON CONFLICT (col, id) DO UPDATE SET data = excluded.data');
const qDel = db.prepare('DELETE FROM docs WHERE col = ? AND id = ?');

const all = (col) => qAll.all(col).map((r) => JSON.parse(r.data));
const get = (col, id) => {
  const r = qGet.get(col, id);
  return r ? JSON.parse(r.data) : null;
};
const find = (col, pred) => all(col).find(pred) || null;
const put = (col, doc) => {
  qPut.run(col, doc.id, JSON.stringify(doc));
  return doc;
};
const del = (col, id) => qDel.run(col, id).changes > 0;

function transaction(fn) {
  db.exec('BEGIN');
  try {
    const out = fn();
    db.exec('COMMIT');
    return out;
  } catch (e) {
    db.exec('ROLLBACK');
    throw e;
  }
}

// ---- audit ----
const qAudit = db.prepare('INSERT INTO audit (ts, actor, action, entity, entity_id, meta) VALUES (?, ?, ?, ?, ?, ?)');
const audit = (actor, action, entity, entityId, meta = {}) =>
  qAudit.run(nowIso(), actor, action, entity, String(entityId), JSON.stringify(meta));
const auditList = (limit = 100) =>
  db.prepare('SELECT ts AS timestamp, actor, action, entity, entity_id, meta FROM audit ORDER BY id DESC LIMIT ?')
    .all(limit).map((r) => ({ ...r, meta: JSON.parse(r.meta || '{}') }));

module.exports = { db, DATA_DIR, UPLOADS_DIR, nowIso, uuid, all, get, find, put, del, transaction, audit, auditList };
