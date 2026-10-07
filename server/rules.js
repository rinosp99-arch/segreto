// Write rules shared by the admin API (admin.js) and the AI interface (ai-capabilities.js).
// Every build* function only computes the document that would be stored and never writes:
// it returns { doc } (plus extras) or { error: { status, detail } } in the exact shape the admin API answers.
const crypto = require('crypto');
const path = require('path');
const store = require('./db');
const C = require('./content');

const fail = (status, detail) => ({ error: { status, detail } });

// ---------------- upload ----------------
const EXT = {
  'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/avif': 'avif', 'image/gif': 'gif',
  'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov',
};
const UPLOAD_SUBDIR = path.join('lato-segreto', 'uploads');
const UPLOAD_DIR = path.join(store.UPLOADS_DIR, UPLOAD_SUBDIR);
const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;
const uploadName = (mime) => `${crypto.randomUUID().replace(/-/g, '')}.${EXT[mime]}`;
const uploadUrl = (filename) => `/api/uploads/lato-segreto/uploads/${filename}`;

// ---------------- models ----------------
const liveModels = () => store.all('models').filter((m) => !m.is_deleted);

function uniqueSlug(base, excludeId) {
  const b = C.slugify(base);
  let slug = b;
  for (let i = 2; store.find('models', (m) => m.slug === slug && m.id !== excludeId); i++) slug = `${b}-${i}`;
  return slug;
}

// null when the model may be published, otherwise the checklist error of the admin API
function publishBlock(data) {
  const rd = C.readiness(data);
  if (rd.is_ready) return null;
  return fail(400, { message: 'NON PUOI ANCORA PUBBLICARE', missing_required: rd.missing_required, missing_count: rd.missing_count });
}

const withStatus = (doc) => ({ ...doc, ...C.fullStatus(doc) });

function buildModelCreate(input) {
  const data = C.normalizeModel(input);
  if (!data.nome.trim()) return fail(422, 'Nome obbligatorio');
  data.slug = uniqueSlug(data.slug || data.nome);
  if (data.stato === 'pubblicata') {
    const blocked = publishBlock(data);
    if (blocked) return blocked;
  }
  const now = store.nowIso();
  Object.assign(data, { id: crypto.randomUUID(), created_at: now, updated_at: now });
  if (data.stato === 'pubblicata' && !data.data_pubblicazione) data.data_pubblicazione = now;
  return { doc: data };
}

function buildModelUpdate(existing, input) {
  const data = C.normalizeModel(input);
  if (!data.nome.trim()) return fail(422, 'Nome obbligatorio');
  data.slug = data.slug ? uniqueSlug(data.slug, existing.id) : existing.slug;
  const wasPublished = existing.stato === 'pubblicata';
  if (data.stato === 'pubblicata' && !wasPublished) {
    const blocked = publishBlock(data);
    if (blocked) return blocked;
  }
  if (data.stato === 'pubblicata' && !existing.data_pubblicazione) data.data_pubblicazione = store.nowIso();
  else data.data_pubblicazione = data.data_pubblicazione || existing.data_pubblicazione || null;

  // safety for already-published models: incomplete edit -> back to draft; pellicola without video -> pellicola off
  let auto = null;
  if (wasPublished && data.stato === 'pubblicata') {
    const rd = C.readiness(data);
    if (!rd.profile_ready) {
      data.stato = 'bozza';
      auto = { type: 'bozza', missing: rd.profile_missing };
    } else if (data.pellicola_home.attiva && !rd.pellicola_ready) {
      data.pellicola_home.attiva = false;
      auto = { type: 'pellicola_off', missing: rd.pellicola_missing };
    }
  }
  return { doc: { ...existing, ...data, id: existing.id, created_at: existing.created_at, updated_at: store.nowIso() }, auto };
}

const MODEL_STATES = ['bozza', 'pubblicata', 'disattivata'];

function buildModelStato(existing, stato) {
  if (!MODEL_STATES.includes(stato)) return fail(400, 'Stato non valido');
  if (stato === 'pubblicata') {
    const blocked = publishBlock(existing);
    if (blocked) return blocked;
  }
  const doc = { ...existing, stato, updated_at: store.nowIso() };
  if (stato === 'pubblicata' && !doc.data_pubblicazione) doc.data_pubblicazione = doc.updated_at;
  return { doc };
}

// soft delete: stays in the database, can be restored
function buildModelDelete(existing) {
  const now = store.nowIso();
  return { doc: { ...existing, is_deleted: true, deleted_at: now, stato_precedente: existing.stato, stato: 'archiviata', updated_at: now } };
}

// ---------------- categories ----------------
function buildCategoryCreate(input) {
  const data = C.normalizeCategory(input);
  if (!data.nome.trim()) return fail(422, 'Nome obbligatorio');
  data.slug = C.slugify(data.slug || data.nome);
  if (store.find('categories', (c) => c.slug === data.slug)) return fail(400, 'Slug categoria già esistente');
  Object.assign(data, { id: crypto.randomUUID(), created_at: store.nowIso() });
  return { doc: data };
}

function buildCategoryUpdate(existing, input) {
  const data = C.normalizeCategory(input);
  data.slug = C.slugify(data.slug || data.nome);
  if (store.find('categories', (c) => c.slug === data.slug && c.id !== existing.id)) return fail(400, 'Slug categoria già esistente');
  return { doc: { ...existing, ...data, id: existing.id } };
}

// ---------------- articles ----------------
function buildArticleCreate(input) {
  const data = C.normalizeArticle(input);
  if (!data.titolo) return fail(422, 'Titolo obbligatorio');
  data.slug = C.slugify(data.slug || data.titolo);
  if (store.find('articles', (a) => a.slug === data.slug)) data.slug = `${data.slug}-${crypto.randomBytes(3).toString('hex')}`;
  data.contenuto = C.sanitizeHtml(data.contenuto);
  const now = store.nowIso();
  Object.assign(data, { id: crypto.randomUUID(), created_at: now, data_aggiornamento: now, fonte: 'manuale' });
  if (data.stato === 'pubblicato' && !data.data_pubblicazione) data.data_pubblicazione = now;
  return { doc: data };
}

function buildArticleUpdate(existing, input) {
  const data = C.normalizeArticle(input);
  data.slug = C.slugify(data.slug || data.titolo);
  data.contenuto = C.sanitizeHtml(data.contenuto);
  data.data_aggiornamento = store.nowIso();
  if (data.stato === 'pubblicato' && !existing.data_pubblicazione) data.data_pubblicazione = data.data_aggiornamento;
  else data.data_pubblicazione = data.data_pubblicazione || existing.data_pubblicazione || null;
  return { doc: { ...existing, ...data, id: existing.id } };
}

// ---------------- settings ----------------
const SETTINGS_ALLOWED = ['brand_name', 'auto_publish_articles', 'site_description', 'footer_contatti', 'global_switch_default', 'home_pellicola'];

function buildSettings(input) {
  const upd = Object.fromEntries(SETTINGS_ALLOWED.filter((k) => input?.[k] != null).map((k) => [k, input[k]]));
  return { doc: { ...(store.get('settings', 'global') || {}), ...upd, id: 'global', updated_at: store.nowIso() } };
}

// ---------------- analytics (events table) ----------------
function cutoff(range) {
  const d = new Date();
  if (range === 'oggi') { d.setHours(0, 0, 0, 0); return d.toISOString(); }
  const days = { '7g': 7, '30g': 30, '90g': 90 }[range];
  return days ? new Date(Date.now() - days * 864e5).toISOString() : '0000';
}

function countsByType(since, modelId) {
  const sql = `SELECT tipo, COUNT(*) AS n FROM events WHERE ts >= ?${modelId ? ' AND model_id = ?' : ''} GROUP BY tipo`;
  const rows = store.db.prepare(sql).all(...(modelId ? [since, modelId] : [since]));
  return Object.fromEntries(rows.map((r) => [r.tipo, r.n]));
}

module.exports = {
  EXT, UPLOAD_SUBDIR, UPLOAD_DIR, MAX_UPLOAD_BYTES, uploadName, uploadUrl,
  liveModels, uniqueSlug, publishBlock, withStatus, MODEL_STATES,
  buildModelCreate, buildModelUpdate, buildModelStato, buildModelDelete,
  buildCategoryCreate, buildCategoryUpdate, buildArticleCreate, buildArticleUpdate,
  SETTINGS_ALLOWED, buildSettings, cutoff, countsByType,
};
