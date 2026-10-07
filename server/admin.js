// Admin API: same URLs and response shapes as the old backend, only the parts the admin UI uses.
const express = require('express');
const fs = require('fs');
const multer = require('multer');
const store = require('./db');
const auth = require('./auth');
const C = require('./content');
const R = require('./rules');
const site = require('./site');
const aiStore = require('./ai-store');

const router = express.Router();
router.use(express.json({ limit: '2mb' }));

// ---------------- auth ----------------
router.post('/login', (req, res) => {
  const ip = req.ip || 'unknown';
  if (!auth.loginAllowed(ip)) return res.status(429).json({ detail: 'Troppi tentativi. Riprova tra 15 minuti.' });
  const admin = auth.checkLogin(req.body?.email, req.body?.password);
  if (!admin) {
    auth.loginFailed(ip);
    return res.status(401).json({ detail: 'Credenziali non valide' });
  }
  auth.loginOk(ip);
  store.audit(admin.email, 'login', 'admin', admin.id);
  res.json({ token: auth.signToken(admin), email: admin.email, ruolo: 'amministratore' });
});

router.use(auth.requireAdmin);
const actor = (req) => req.admin.email;

router.get('/me', (req, res) => res.json({ email: req.admin.email, ruolo: 'amministratore' }));

router.post('/change-password', (req, res) => {
  const pw = String(req.body?.password || '');
  if (pw.length < 10) return res.status(400).json({ detail: 'La password deve avere almeno 10 caratteri' });
  auth.setPassword(req.admin.sub, pw);
  store.audit(actor(req), 'change_password', 'admin', req.admin.sub);
  res.json({ ok: true });
});

// ---------------- upload ----------------
fs.mkdirSync(R.UPLOAD_DIR, { recursive: true });

const upload = multer({
  storage: multer.diskStorage({
    destination: R.UPLOAD_DIR,
    filename: (req, file, cb) => cb(null, R.uploadName(file.mimetype)),
  }),
  limits: { fileSize: R.MAX_UPLOAD_BYTES },
  fileFilter: (req, file, cb) => (R.EXT[file.mimetype] ? cb(null, true) : cb(new Error(`Tipo file non consentito: ${file.mimetype}`))),
});

router.post('/upload', (req, res) => {
  upload.single('file')(req, res, (err) => {
    if (err) return res.status(400).json({ detail: err.code === 'LIMIT_FILE_SIZE' ? 'File troppo grande (max 200MB)' : err.message });
    if (!req.file) return res.status(400).json({ detail: 'Nessun file' });
    const tipo = req.file.mimetype.startsWith('video/') ? 'video' : 'image';
    store.audit(actor(req), 'upload', 'file', req.file.filename, { tipo, size: req.file.size, nome: req.file.originalname });
    res.json({ url: R.uploadUrl(req.file.filename), tipo, size: req.file.size });
  });
});

// ---------------- models ----------------
// the write rules live in rules.js (shared with the AI interface); a rule error is answered as { detail }
const rejected = (res, r) => (r.error ? (res.status(r.error.status).json({ detail: r.error.detail }), true) : false);
const { withStatus } = R;

router.get('/models', (req, res) => {
  let items = R.liveModels().sort((a, b) => (a.ordine || 0) - (b.ordine || 0));
  if (req.query.stato) items = items.filter((m) => m.stato === req.query.stato);
  const counts = { tutte: items.length, demo: 0, reali: 0, incomplete: 0, pronte: 0 };
  items = items.map((m) => {
    const fs_ = C.fullStatus(m);
    if (fs_.content_status.is_demo) counts.demo += 1; else counts.reali += 1;
    if (fs_.stato_operativo === 'incompleta') counts.incomplete += 1;
    if (fs_.readiness.is_ready && m.stato !== 'pubblicata') counts.pronte += 1;
    return {
      ...m, content_status: fs_.content_status, stato_operativo: fs_.stato_operativo,
      readiness: { is_ready: fs_.readiness.is_ready, missing_count: fs_.readiness.missing_count, missing_required: fs_.readiness.missing_required },
    };
  });
  res.json({ items, counts, demo_totale: counts.demo, totale: counts.tutte });
});

router.get('/models/:id', (req, res) => {
  const doc = store.get('models', req.params.id);
  if (!doc) return res.status(404).json({ detail: 'Modella non trovata' });
  res.json(withStatus(doc));
});

router.post('/models', (req, res) => {
  const r = R.buildModelCreate(req.body);
  if (rejected(res, r)) return;
  store.put('models', r.doc);
  store.audit(actor(req), 'create', 'model', r.doc.id, { nome: r.doc.nome });
  res.json(r.doc);
});

router.put('/models/:id', (req, res) => {
  const existing = store.get('models', req.params.id);
  if (!existing) return res.status(404).json({ detail: 'Modella non trovata' });
  const r = R.buildModelUpdate(existing, req.body);
  if (rejected(res, r)) return;
  const { doc, auto } = r;
  store.put('models', doc);
  store.audit(actor(req), auto ? `auto_${auto.type}` : 'update', 'model', doc.id, auto ? { missing: auto.missing } : {});
  res.json(auto ? { ...withStatus(doc), _auto: auto } : withStatus(doc));
});

router.patch('/models/:id/stato', (req, res) => {
  const stato = req.body?.stato;
  if (!R.MODEL_STATES.includes(stato)) return res.status(400).json({ detail: 'Stato non valido' });
  const existing = store.get('models', req.params.id);
  if (!existing) return res.status(404).json({ detail: 'Modella non trovata' });
  const r = R.buildModelStato(existing, stato);
  if (rejected(res, r)) return;
  store.put('models', r.doc);
  store.audit(actor(req), `stato:${stato}`, 'model', r.doc.id);
  res.json({ ok: true, stato });
});

router.delete('/models/:id', (req, res) => {
  const existing = store.get('models', req.params.id);
  if (!existing) return res.status(404).json({ detail: 'Modella non trovata' });
  const { doc } = R.buildModelDelete(existing);
  store.put('models', doc);
  store.audit(actor(req), 'delete', 'model', doc.id);
  res.json({ ok: true, soft_deleted: true });
});

router.post('/models/reorder', (req, res) => {
  const order = C.arr(req.body?.order);
  store.transaction(() => order.forEach((id, idx) => {
    const m = store.get('models', id);
    if (m) store.put('models', { ...m, ordine: idx });
  }));
  store.audit(actor(req), 'reorder', 'model', '-');
  res.json({ ok: true });
});

// copy only configuration (theme, direction, timed CTA, message timing, pellicola flags) - never personal media/text
function configPatch(src, dst, sections) {
  const upd = {};
  if (sections.regista) {
    upd.tema = src.tema || {};
    upd.regia = src.regia || {};
  }
  if (sections.conversione) {
    upd.cta_temporizzata = src.cta_temporizzata || {};
    upd.cta_testo = src.cta_testo || dst.cta_testo || 'CONTINUA CON ME';
    const sm = C.obj(src.messaggio_35s);
    const dm = C.obj(dst.messaggio_35s);
    upd.messaggio_35s = { ...dm, attivo: sm.attivo ?? dm.attivo ?? true, timer: sm.timer ?? dm.timer ?? 35, cta_testo: sm.cta_testo ?? dm.cta_testo ?? 'CONTINUA CON ME' };
  }
  if (sections.pellicola) {
    const sp = C.obj(src.pellicola_home);
    const dp = C.obj(dst.pellicola_home);
    upd.pellicola_home = { ...dp, attiva: sp.attiva ?? dp.attiva ?? true, priorita: sp.priorita ?? dp.priorita ?? 5 };
  }
  return upd;
}

router.post('/models/:id/copy-config', (req, res) => {
  const src = store.get('models', req.body?.source_id);
  const dst = store.get('models', req.params.id);
  if (!src || !dst) return res.status(404).json({ detail: 'Modella non trovata' });
  const doc = { ...dst, ...configPatch(src, dst, { regista: true, conversione: true, pellicola: true }), updated_at: store.nowIso() };
  store.put('models', doc);
  store.audit(actor(req), 'copy_config', 'model', doc.id, { from: src.id });
  res.json(withStatus(doc));
});

router.post('/models/copy-config-bulk', (req, res) => {
  const src = store.get('models', req.body?.source_id);
  if (!src) return res.status(404).json({ detail: 'Modella sorgente non trovata' });
  const sections = C.obj(req.body?.sections);
  const names = ['regista', 'conversione', 'pellicola'].filter((s) => sections[s]);
  if (!names.length) return res.status(400).json({ detail: 'Seleziona almeno una sezione da copiare' });
  const updated = [];
  for (const tid of C.arr(req.body?.target_ids)) {
    if (tid === src.id) continue;
    const dst = store.get('models', tid);
    if (!dst) continue;
    store.put('models', { ...dst, ...configPatch(src, dst, sections), updated_at: store.nowIso() });
    updated.push(tid);
  }
  store.audit(actor(req), 'copy_config_bulk', 'model', src.id, { targets: updated, sections: names });
  res.json({ updated: updated.length, sections: names });
});

// ---------------- categories ----------------
router.get('/categories', (req, res) => {
  res.json({ items: store.all('categories').sort((a, b) => (a.ordine || 0) - (b.ordine || 0)) });
});

router.post('/categories', (req, res) => {
  const r = R.buildCategoryCreate(req.body);
  if (rejected(res, r)) return;
  store.put('categories', r.doc);
  store.audit(actor(req), 'create', 'category', r.doc.id);
  res.json(r.doc);
});

router.put('/categories/:id', (req, res) => {
  const existing = store.get('categories', req.params.id);
  if (!existing) return res.status(404).json({ detail: 'Categoria non trovata' });
  const r = R.buildCategoryUpdate(existing, req.body);
  if (rejected(res, r)) return;
  store.put('categories', r.doc);
  store.audit(actor(req), 'update', 'category', r.doc.id);
  res.json(r.doc);
});

router.delete('/categories/:id', (req, res) => {
  if (!store.del('categories', req.params.id)) return res.status(404).json({ detail: 'Categoria non trovata' });
  store.audit(actor(req), 'delete', 'category', req.params.id);
  res.json({ ok: true });
});

// ---------------- articles ----------------
router.get('/articles', (req, res) => {
  res.json({ items: store.all('articles').sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))) });
});

router.get('/articles/:id', (req, res) => {
  const doc = store.get('articles', req.params.id);
  if (!doc) return res.status(404).json({ detail: 'Articolo non trovato' });
  res.json(doc);
});

router.post('/articles', (req, res) => {
  const r = R.buildArticleCreate(req.body);
  if (rejected(res, r)) return;
  store.put('articles', r.doc);
  store.audit(actor(req), 'create', 'article', r.doc.id);
  res.json(r.doc);
});

router.put('/articles/:id', (req, res) => {
  const existing = store.get('articles', req.params.id);
  if (!existing) return res.status(404).json({ detail: 'Articolo non trovato' });
  const { doc } = R.buildArticleUpdate(existing, req.body);
  store.put('articles', doc);
  store.audit(actor(req), 'update', 'article', doc.id);
  res.json(doc);
});

router.delete('/articles/:id', (req, res) => {
  if (!store.del('articles', req.params.id)) return res.status(404).json({ detail: 'Articolo non trovato' });
  store.audit(actor(req), 'delete', 'article', req.params.id);
  res.json({ ok: true });
});

// ---------------- settings + audit ----------------
router.get('/settings', (req, res) => res.json(store.get('settings', 'global') || {}));

router.put('/settings', (req, res) => {
  const { doc } = R.buildSettings(req.body);
  store.put('settings', doc);
  store.audit(actor(req), 'update', 'settings', 'global');
  res.json(doc);
});

router.get('/audit', (req, res) => res.json({ items: store.auditList(Math.min(parseInt(req.query.limit, 10) || 100, 500)) }));

// ---------------- AI interface (custom GPT): switches, keys, activity ----------------
// The keys themselves are used on /api/v2/ai (ai.js). Here an admin creates, disables and deletes them.
const aiControl = (req) => {
  const base = site.baseUrl(req);
  return { ...aiStore.flags(), base_url: base, schema_url: `${base}/api/v2/ai/openapi-chatgpt.json` };
};

router.get('/ai/control', (req, res) => res.json(aiControl(req)));

router.patch('/ai/control', (req, res) => {
  const r = aiStore.setFlags(req.body);
  if (r.error) return res.status(400).json({ detail: r.error });
  store.audit(actor(req), 'ai_control', 'config', 'ai', r.changed);
  res.json(aiControl(req));
});

router.get('/ai/keys', (req, res) => res.json({ items: aiStore.listKeys(), presets: Object.keys(aiStore.PRESETS) }));

router.post('/ai/keys', (req, res) => {
  const name = String(req.body?.name || '').trim().slice(0, 80);
  const preset = req.body?.preset || 'read_only';
  if (!name) return res.status(422).json({ detail: 'Nome della chiave obbligatorio' });
  if (!Object.hasOwn(aiStore.PRESETS, preset)) return res.status(422).json({ detail: 'Preset non valido (read_only | full)' });
  const { key, record } = aiStore.createKey(name, preset, actor(req));
  store.audit(actor(req), 'ai_key_create', 'ai_key', record.id, { name, preset, prefix: record.prefix });
  // the plain key leaves the server exactly once, in this response
  res.json({ ...record, key });
});

router.post('/ai/keys/:id/:op(disable|enable)', (req, res) => {
  const record = aiStore.setKeyDisabled(req.params.id, req.params.op === 'disable');
  if (!record) return res.status(404).json({ detail: 'Chiave non trovata' });
  store.audit(actor(req), `ai_key_${req.params.op}`, 'ai_key', record.id);
  res.json(record);
});

router.delete('/ai/keys/:id', (req, res) => {
  if (!aiStore.deleteKey(req.params.id)) return res.status(404).json({ detail: 'Chiave non trovata' });
  store.audit(actor(req), 'ai_key_delete', 'ai_key', req.params.id);
  res.json({ ok: true });
});

router.get('/ai/actions', (req, res) => res.json({ items: aiStore.listActions(Math.min(parseInt(req.query.limit, 10) || 20, 200)) }));

// ---------------- dashboard analytics ----------------
const { cutoff, countsByType } = R;

router.get('/analytics/overview', (req, res) => {
  const range = req.query.range || 'oggi';
  const since = cutoff(range);
  const c = countsByType(since);
  const visite = c.page_view || 0;
  const perModel = store.db.prepare(`SELECT model_id,
      SUM(tipo = 'page_view') AS visite, SUM(tipo = 'of_click') AS click
    FROM events WHERE ts >= ? AND model_id IS NOT NULL GROUP BY model_id`).all(since);
  const names = Object.fromEntries(store.all('models').map((m) => [m.id, m]));
  let top = null;
  let topCtr = null;
  for (const r of perModel) {
    const m = names[r.model_id];
    if (!m || !r.visite) continue;
    const row = { id: m.id, slug: m.slug, nome_artistico: m.nome_artistico || m.nome, foto_card: m.foto_card, visite: r.visite, ctr_of: Math.round((r.click / r.visite) * 1000) / 10 };
    if (!top || row.visite > top.visite) top = row;
    if (!topCtr || row.ctr_of > topCtr.ctr_of) topCtr = row;
  }
  const pct = (a, b) => (b ? Math.round((a / b) * 1000) / 10 : 0);
  res.json({
    range, visite, attivazioni: c.secret_activate || 0, perc_attivazione: pct(c.secret_activate || 0, visite),
    click_of: c.of_click || 0, ctr_medio: pct(c.of_click || 0, visite), messaggi_aperti: c.message_open || 0,
    modella_top_visite: top, modella_top_ctr: topCtr,
  });
});

router.get('/analytics/funnel', (req, res) => {
  const range = req.query.range || '30g';
  const c = countsByType(cutoff(range), req.query.model_id);
  const steps = [
    { nome: 'Visita', valore: c.page_view || 0 },
    { nome: 'Lato Segreto', valore: c.secret_activate || 0 },
    { nome: 'Interazione', valore: c.interazione || 0 },
    { nome: 'Messaggio', valore: c.message_open || 0 },
    { nome: 'Click OnlyFans', valore: c.of_click || 0 },
  ];
  const top = steps[0].valore || 1;
  steps.forEach((s, i) => {
    s.percentuale = Math.round((s.valore / top) * 1000) / 10;
    s.conversione = i === 0 ? 100 : Math.round((s.valore / (steps[i - 1].valore || 1)) * 1000) / 10;
  });
  res.json({ range, steps });
});

module.exports = router;
