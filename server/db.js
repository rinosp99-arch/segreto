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
`);

const nowIso = () => new Date().toISOString();
const uuid = () => crypto.randomUUID();

// ---- documents (models, categories, articles, settings, landings, redirects) ----
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
