// Admin authentication: bcrypt password hashes + signed JWT (Bearer token, like the old backend).
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const store = require('./db');

function loadSecret() {
  if (process.env.JWT_SECRET && process.env.JWT_SECRET.length >= 32) return process.env.JWT_SECRET;
  const file = path.join(store.DATA_DIR, '.jwt-secret');
  if (!fs.existsSync(file)) fs.writeFileSync(file, crypto.randomBytes(48).toString('hex'), { mode: 0o600 });
  return fs.readFileSync(file, 'utf8').trim();
}
const SECRET = loadSecret();
const EXPIRES = process.env.JWT_EXPIRES || '12h';

const qByEmail = store.db.prepare('SELECT * FROM admins WHERE email = ?');
const qById = store.db.prepare('SELECT id, email FROM admins WHERE id = ?');
const qInsert = store.db.prepare('INSERT INTO admins (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)');
const qSetPw = store.db.prepare('UPDATE admins SET password_hash = ? WHERE id = ?');
const qCount = store.db.prepare('SELECT COUNT(*) AS n FROM admins');

const normEmail = (e) => String(e || '').trim().toLowerCase();
const DUMMY_HASH = bcrypt.hashSync(crypto.randomBytes(16).toString('hex'), 12);

function createAdmin(email, password) {
  if (String(password).length < 10) throw new Error('Passwort muss mindestens 10 Zeichen haben');
  const id = crypto.randomUUID();
  qInsert.run(id, normEmail(email), bcrypt.hashSync(String(password), 12), store.nowIso());
  return id;
}

function setPassword(id, password) {
  qSetPw.run(bcrypt.hashSync(String(password), 12), id);
}

function checkLogin(email, password) {
  const admin = qByEmail.get(normEmail(email));
  // compare against a dummy hash too, so response time does not reveal whether the e-mail exists
  const hash = admin ? admin.password_hash : DUMMY_HASH;
  const ok = bcrypt.compareSync(String(password || ''), hash);
  return ok && admin ? admin : null;
}

const signToken = (admin) => jwt.sign({ sub: admin.id, email: admin.email, ruolo: 'amministratore' }, SECRET, { expiresIn: EXPIRES });

function decode(req) {
  const h = req.headers.authorization || '';
  if (!h.toLowerCase().startsWith('bearer ')) return null;
  try {
    const payload = jwt.verify(h.slice(7).trim(), SECRET);
    return qById.get(payload.sub) ? payload : null;
  } catch {
    return null;
  }
}

const isAdminRequest = (req) => decode(req) !== null;

function requireAdmin(req, res, next) {
  const payload = decode(req);
  if (!payload) return res.status(401).json({ detail: 'Non autorizzato' });
  req.admin = payload;
  next();
}

// brute-force protection: max 8 failed logins per IP per 15 minutes
const attempts = new Map();
function loginAllowed(ip) {
  const now = Date.now();
  const a = attempts.get(ip);
  if (!a || now - a.first > 15 * 60 * 1000) return true;
  return a.count < 8;
}
function loginFailed(ip) {
  const now = Date.now();
  const a = attempts.get(ip);
  if (!a || now - a.first > 15 * 60 * 1000) attempts.set(ip, { first: now, count: 1 });
  else a.count += 1;
}
const loginOk = (ip) => attempts.delete(ip);

module.exports = {
  createAdmin, setPassword, checkLogin, signToken, requireAdmin, isAdminRequest, adminFromRequest: decode,
  loginAllowed, loginFailed, loginOk, adminCount: () => qCount.get().n,
};
