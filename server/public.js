// Public API: same URLs and response shapes the React app already uses.
const express = require('express');
const crypto = require('crypto');
const store = require('./db');
const { publicProjection, secretProjection, obj, arr } = require('./content');
const { isAdminRequest } = require('./auth');

const router = express.Router();

const published = () => store.all('models').filter((m) => m.stato === 'pubblicata' && !m.is_deleted);
const byOrder = (a, b) => (a.ordine || 0) - (b.ordine || 0);

const qViews = store.db.prepare("SELECT model_id, COUNT(*) AS n FROM events WHERE tipo = 'page_view' AND model_id IS NOT NULL GROUP BY model_id");
function viewCounts() {
  const out = {};
  for (const r of qViews.all()) out[r.model_id] = r.n;
  return out;
}

router.get('/models', (req, res) => {
  const { categoria, q } = req.query;
  const filtro = req.query.filtro || 'tutte';
  const limit = Math.min(parseInt(req.query.limit, 10) || 60, 500);
  const skip = parseInt(req.query.skip, 10) || 0;
  let docs = published();
  if (categoria && categoria !== 'tutte') docs = docs.filter((m) => arr(m.categorie).includes(categoria));
  if (q) {
    const needle = String(q).trim().toLowerCase();
    docs = docs.filter((m) => [m.nome, m.nome_artistico, m.slug, ...arr(m.tag)].some((v) => String(v || '').toLowerCase().includes(needle)));
  }
  const vc = viewCounts();
  let items = docs.map((d) => publicProjection(d, vc[d.id] || 0));
  if (filtro === 'nuove') items.sort((a, b) => String(b.data_pubblicazione || '').localeCompare(String(a.data_pubblicazione || '')));
  else if (filtro === 'piu-viste' || filtro === 'piu_viste') items.sort((a, b) => b.visite - a.visite);
  else if (filtro === 'in-tendenza' || filtro === 'in_tendenza') items = [...items.filter((x) => x.badge === 'IN TENDENZA'), ...items.filter((x) => x.badge !== 'IN TENDENZA')];
  else items.sort(byOrder);
  res.json({ items: items.slice(skip, skip + limit), total: items.length });
});

function findModel(req, slug) {
  let doc = published().find((m) => m.slug === slug);
  let anteprima = false;
  if (!doc && isAdminRequest(req)) {
    doc = store.find('models', (m) => m.slug === slug);
    anteprima = Boolean(doc);
  }
  return { doc, anteprima };
}

router.get('/models/:slug', (req, res) => {
  const { doc, anteprima } = findModel(req, req.params.slug);
  if (!doc) return res.status(404).json({ detail: 'Modella non trovata' });
  res.json({ ...publicProjection(doc, viewCounts()[doc.id] || 0), anteprima });
});

router.get('/models/:slug/segreto', (req, res) => {
  const { doc } = findModel(req, req.params.slug);
  if (!doc) return res.status(404).json({ detail: 'Modella non trovata' });
  res.json(secretProjection(doc));
});

router.get('/models/:slug/correlate', (req, res) => {
  const limit = Math.min(parseInt(req.query.limit, 10) || 4, 20);
  const doc = store.find('models', (m) => m.slug === req.params.slug);
  if (!doc) return res.status(404).json({ detail: 'Modella non trovata' });
  const cats = arr(doc.categorie);
  const others = published().filter((m) => m.slug !== doc.slug);
  const picked = cats.length ? others.filter((m) => arr(m.categorie).some((c) => cats.includes(c))).slice(0, limit) : others.slice(0, limit);
  for (const m of others) {
    if (picked.length >= limit) break;
    if (!picked.includes(m)) picked.push(m);
  }
  res.json({ items: picked.slice(0, limit).map((m) => publicProjection(m)) });
});

router.get('/surprise', (req, res) => {
  const docs = published();
  if (!docs.length) return res.status(404).json({ detail: 'Nessuna modella disponibile' });
  const m = docs[crypto.randomInt(docs.length)];
  res.json({ slug: m.slug, nome: m.nome, foto_card: m.foto_card });
});

router.get('/categories', (req, res) => {
  const counts = {};
  for (const m of published()) for (const c of arr(m.categorie)) counts[c] = (counts[c] || 0) + 1;
  const items = store.all('categories').filter((c) => c.stato === 'pubblicata').sort(byOrder)
    .map((c) => ({ ...c, conteggio: counts[c.slug] || 0 }));
  res.json({ items });
});

router.get('/categories/:slug', (req, res) => {
  const cat = store.find('categories', (c) => c.slug === req.params.slug && c.stato === 'pubblicata');
  if (!cat) return res.status(404).json({ detail: 'Categoria non trovata' });
  const vc = viewCounts();
  const items = published().filter((m) => arr(m.categorie).includes(cat.slug)).map((m) => publicProjection(m, vc[m.id] || 0));
  res.json({ categoria: cat, items });
});

const publishedArticles = () => store.all('articles').filter((a) => a.stato === 'pubblicato')
  .sort((a, b) => String(b.data_pubblicazione || '').localeCompare(String(a.data_pubblicazione || '')));

router.get('/articles', (req, res) => {
  const limit = Math.min(parseInt(req.query.limit, 10) || 30, 500);
  res.json({ items: publishedArticles().slice(0, limit).map(({ contenuto, ...rest }) => rest) });
});

router.get('/articles/:slug', (req, res) => {
  const doc = publishedArticles().find((a) => a.slug === req.params.slug);
  if (!doc) return res.status(404).json({ detail: 'Articolo non trovato' });
  const pub = published();
  const related = arr(doc.modelle_correlate).map((s) => pub.find((m) => m.slug === s)).filter(Boolean)
    .map((m) => ({ nome: m.nome, nome_artistico: m.nome_artistico, slug: m.slug, foto_card: m.foto_card, frase: m.frase, badge: m.badge }));
  res.json({ ...doc, modelle_correlate_dettaglio: related });
});

const settings = () => store.get('settings', 'global') || {};

router.get('/settings', (req, res) => {
  const s = settings();
  res.json({
    brand_name: s.brand_name || 'LATO SEGRETO',
    site_description: s.site_description || '',
    footer_contatti: s.footer_contatti || '',
    global_switch_default: s.global_switch_default || 'public',
  });
});

const DEFAULT_PELLICOLA = {
  attiva: true, titolo: 'IN MOVIMENTO', sottotitolo: 'Una foto non racconta tutto.', velocita: 6,
  max_video_attivi: 8, seconda_fila: false, pausa_su_touch: true, nomi_sempre_visibili: false, inserisci_dopo_n: 10,
};

function firstPairVideo(doc, side) {
  const pr = arr(doc.media_pairs).find((p) => p.tipo === 'video');
  const m = obj(pr && pr[side]);
  return [m.url || '', m.poster || ''];
}

router.get('/pellicola', (req, res) => {
  const cfg = { ...DEFAULT_PELLICOLA, ...obj(settings().home_pellicola) };
  cfg.max_video_attivi = Math.max(4, Math.min(12, parseInt(cfg.max_video_attivi, 10) || 8));
  const items = [];
  for (const d of published()) {
    const ph = obj(d.pellicola_home);
    if (ph.attiva === false) continue;
    let pubVid = obj(ph.pubblico).video_url || '';
    let pubPos = obj(ph.pubblico).poster_url || '';
    let segVid = obj(ph.segreto).video_url || '';
    let segPos = obj(ph.segreto).poster_url || '';
    if (!pubVid) { const [v, p] = firstPairVideo(d, 'pubblico'); pubVid = v; pubPos = pubPos || p; }
    if (!segVid) { const [v, p] = firstPairVideo(d, 'segreto'); segVid = v; segPos = segPos || p; }
    pubPos = pubPos || d.foto_card || '';
    segPos = segPos || d.foto_card_teaser || pubPos;
    if (!pubVid && !segVid) continue;
    items.push({
      slug: d.slug, nome_artistico: d.nome_artistico || d.nome, foto_card: d.foto_card || '',
      priorita: ph.priorita ?? 5, ordine_manuale: ph.ordine ?? null, ordine: d.ordine || 0, _seq: ph.seq ?? Number.MAX_SAFE_INTEGER,
      pubblico: { video_url: pubVid, poster_url: pubPos },
      segreto: { video_url: segVid || pubVid, poster_url: segPos },
    });
  }
  items.sort((a, b) => {
    const am = a.ordine_manuale == null ? 1 : 0;
    const bm = b.ordine_manuale == null ? 1 : 0;
    return am - bm || (a.ordine_manuale || 0) - (b.ordine_manuale || 0) || (b.priorita || 0) - (a.priorita || 0) || a.ordine - b.ordine || a._seq - b._seq;
  });
  res.json({ config: cfg, items: items.map(({ _seq, ...it }) => it) });
});

// landing pages + redirects (managed later from the admin; empty after import)
router.get('/landings/:slug', (req, res) => {
  const l = store.find('landings', (x) => x.slug === req.params.slug && (x.stato === 'pubblicata' || x.stato === 'published'));
  if (!l) return res.status(404).json({ detail: 'Pagina non trovata' });
  res.json(l);
});

router.get('/redirects/resolve', (req, res) => {
  const r = store.find('redirects', (x) => x.from_path === req.query.path && x.active !== false);
  res.json(r ? { redirect: r.to_path, status_code: r.status_code || 301 } : { redirect: null });
});

// ---- tracking (anonymous; used for view counts and the admin dashboard) ----
const insertEvent = store.db.prepare('INSERT INTO events (ts, tipo, model_id, model_slug, session_id, visit_id, data) VALUES (?, ?, ?, ?, ?, ?, ?)');
const BAD_KEYS = new Set(['password', 'token', 'email', 'authorization', 'cookie']);
const KEEP = ['cta_source', 'referrer', 'ref', 'fonte', 'campagna', 'path', 'mode', 'entry_source', 'device_type', 'platform',
  'cta_type', 'cta_position', 'slot', 'from_model', 'to_model', 'input', 'placement', 'profile_pos', 'seq', 'valore'];

function saveEvents(events) {
  const slugIds = Object.fromEntries(store.all('models').map((m) => [m.slug, m.id]));
  const ts = new Date().toISOString();
  store.transaction(() => {
    for (const ev of events.slice(0, 50)) {
      if (!ev || typeof ev.tipo !== 'string' || ev.tipo.length > 64) continue;
      const data = {};
      for (const k of KEEP) if (ev[k] != null && String(ev[k]).length <= 500) data[k] = ev[k];
      const meta = obj(ev.meta);
      data.meta = Object.fromEntries(Object.entries(meta).filter(([k, v]) => !BAD_KEYS.has(k.toLowerCase()) && String(v).length <= 500));
      const modelId = ev.model_id || (ev.model_slug && slugIds[ev.model_slug]) || null;
      insertEvent.run(ts, ev.tipo, modelId, ev.model_slug || null, String(ev.session_id || ev.visitor_id || ''), ev.visit_id || null, JSON.stringify(data));
    }
  });
}

router.post('/track', express.json({ limit: '64kb' }), (req, res) => {
  saveEvents([req.body]);
  res.json({ ok: true });
});

// sendBeacon posts text/plain or application/json
router.post('/track/batch', express.json({ limit: '256kb', type: () => true }), (req, res) => {
  const events = arr(obj(req.body).events);
  saveEvents(events);
  res.json({ ok: true, accepted: Math.min(events.length, 50) });
});

module.exports = router;
