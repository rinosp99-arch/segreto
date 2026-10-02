// Content rules ported 1:1 from the old backend (schemas.py, content_status.py, sanitize.py, routes_public.py).

// ---------- helpers ----------
const nz = (v) => Boolean(v && String(v).trim());
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
const arr = (v) => (Array.isArray(v) ? v : []);

function slugify(text) {
  const s = String(text || '').toLowerCase().trim()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return s || 'senza-nome';
}

function sanitizeHtml(html) {
  if (!html) return '';
  return String(html)
    .replace(/<(script|style|iframe|object|embed|form)[^>]*>[\s\S]*?<\/\1>/gi, '')
    .replace(/<(script|style|iframe|object|embed|form|link|meta)[^>]*\/?>/gi, '')
    .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    .replace(/(href|src)\s*=\s*(["'])\s*javascript:[^"']*\2/gi, '')
    .trim();
}

// ---------- defaults (schemas.py) ----------
const mediaItem = (m) => {
  const o = obj(m);
  return { tipo: o.tipo || 'image', url: o.url || '', poster: o.poster || '', alt: o.alt || '' };
};
const mediaPair = (p) => {
  const o = obj(p);
  return { id: o.id || require('crypto').randomUUID(), tipo: o.tipo || 'image', pubblico: mediaItem(o.pubblico), segreto: mediaItem(o.segreto) };
};

function normalizeModel(input) {
  const d = obj(input);
  const tema = obj(d.tema);
  const msg = obj(d.messaggio_35s);
  const seo = obj(d.seo);
  const ph = obj(d.pellicola_home);
  return {
    nome: String(d.nome || ''),
    nome_artistico: d.nome_artistico || '',
    slug: d.slug || '',
    frase: d.frase || '',
    bio: d.bio || '',
    bio_segreta: d.bio_segreta || '',
    foto_copertina: d.foto_copertina || '',
    foto_card: d.foto_card || '',
    foto_card_teaser: d.foto_card_teaser || '',
    foto_segreta_hero: d.foto_segreta_hero || '',
    galleria_pubblica: arr(d.galleria_pubblica).map(mediaItem),
    galleria_segreta: arr(d.galleria_segreta).map(mediaItem),
    media_pairs: arr(d.media_pairs).map(mediaPair),
    categorie: arr(d.categorie).map(String),
    tag: arr(d.tag).map(String),
    badge: d.badge ?? null,
    badge_tipo: d.badge_tipo ?? 'editoriale',
    onlyfans_url: d.onlyfans_url || '',
    cta_testo: d.cta_testo || 'CONTINUA CON ME',
    tema: {
      preset: tema.preset || 'bordeaux',
      colore_primario: tema.colore_primario || '40 55% 60%',
      colore_secondario: tema.colore_secondario || '350 45% 28%',
      grain: tema.grain ?? 0.08,
      glow: tema.glow ?? true,
      sfondo_stile: tema.sfondo_stile || 'vignetta',
      frase_attivazione: tema.frase_attivazione ?? 'NON DOVRESTI PREMERLO',
      testo_dopo_click: tema.testo_dopo_click ?? "Te l'avevamo detto.",
      effetti_touch: tema.effetti_touch ?? true,
    },
    messaggio_35s: {
      attivo: msg.attivo ?? true,
      timer: Number.isFinite(+msg.timer) ? +msg.timer : 35,
      testo: msg.testo ?? 'Se sei ancora qui, forse dovresti venire a vedere il resto…',
      foto: msg.foto || '',
      video: msg.video || '',
      cta_testo: msg.cta_testo || 'CONTINUA CON ME',
    },
    seo: {
      ...seo,
      title: seo.title || '',
      meta_description: seo.meta_description || '',
      alt_default: seo.alt_default || '',
      og_image: seo.og_image || '',
      canonical: seo.canonical || '',
      robots: seo.robots || 'index,follow',
      og_title: seo.og_title || '',
      og_description: seo.og_description || '',
      structured_data_type: seo.structured_data_type || 'ProfilePage',
      keywords: arr(seo.keywords),
      topics: arr(seo.topics),
      indexable: seo.indexable ?? true,
      internal_links: arr(seo.internal_links),
    },
    teaser_copy: d.teaser_copy ?? 'Qui posso mostrarti solo fino a questo punto.',
    regia: obj(d.regia),
    cta_temporizzata: obj(d.cta_temporizzata),
    social: obj(d.social),
    pellicola_home: {
      attiva: ph.attiva ?? true,
      priorita: Number.isFinite(+ph.priorita) ? +ph.priorita : 5,
      ordine: ph.ordine ?? null,
      seq: ph.seq ?? null, // order on the old site, only used as tie-breaker
      pubblico: { video_url: obj(ph.pubblico).video_url || '', poster_url: obj(ph.pubblico).poster_url || '' },
      segreto: { video_url: obj(ph.segreto).video_url || '', poster_url: obj(ph.segreto).poster_url || '' },
    },
    content_overrides: obj(d.content_overrides),
    stato: d.stato || 'bozza',
    ordine: Number.isFinite(+d.ordine) ? +d.ordine : 0,
    conferma_maggiorenne: Boolean(d.conferma_maggiorenne),
    data_pubblicazione: d.data_pubblicazione || null,
    analytics: obj(d.analytics),
    is_deleted: Boolean(d.is_deleted),
  };
}

function normalizeCategory(input) {
  const d = obj(input);
  return {
    nome: String(d.nome || ''),
    slug: d.slug || '',
    descrizione: d.descrizione || '',
    testo_seo: sanitizeHtml(d.testo_seo || ''), // long SEO text below the profiles
    seo_title: d.seo_title || '',
    meta_description: d.meta_description || '',
    immagine: d.immagine || '',
    ordine: Number.isFinite(+d.ordine) ? +d.ordine : 0,
    indicizzabile: d.indicizzabile ?? true,
    stato: d.stato || 'pubblicata',
  };
}

function normalizeArticle(input) {
  const d = obj(input);
  return {
    titolo: String(d.titolo || '').trim(),
    slug: d.slug || '',
    estratto: d.estratto || '',
    contenuto: d.contenuto || '',
    immagine_principale: d.immagine_principale || '',
    immagini_interne: arr(d.immagini_interne),
    autore: d.autore || 'Redazione',
    data_pubblicazione: d.data_pubblicazione || null,
    stato: d.stato || 'bozza',
    categorie: arr(d.categorie),
    tag: arr(d.tag),
    keyword_principale: d.keyword_principale || '',
    keyword_secondarie: arr(d.keyword_secondarie),
    seo_title: d.seo_title || '',
    meta_description: d.meta_description || '',
    canonical: d.canonical || '',
    alt_text: d.alt_text || '',
    og_image: d.og_image || '',
    internal_links: arr(d.internal_links),
    cta: obj(d.cta),
    indicizzabile: d.indicizzabile ?? true,
    modelle_correlate: arr(d.modelle_correlate),
  };
}

// ---------- demo detection + readiness (content_status.py) ----------
const DEMO_MARKERS = ['images.unsplash.com', 'images.pexels.com', '/api/uploads/extern/'];
const autoDemoMedia = (url) => Boolean(url) && (String(url).startsWith('/media/') || DEMO_MARKERS.some((m) => String(url).includes(m)));
const autoDemoLink = (url) => Boolean(url) && String(url).includes('_demo');
function effDemo(url, key, ov, kind = 'media') {
  const o = (ov || {})[key] || 'auto';
  if (o === 'reale') return false;
  if (o === 'demo') return Boolean(url);
  return kind === 'link' ? autoDemoLink(url) : autoDemoMedia(url);
}

function contentStatus(doc) {
  const ov = obj(doc.content_overrides);
  const demo = [];
  const add = (l) => { if (!demo.includes(l)) demo.push(l); };
  if (effDemo(doc.foto_card, 'foto_card', ov)) add('Foto card Home');
  if (effDemo(doc.foto_copertina, 'foto_copertina', ov)) add('Foto Lato Pubblico');
  if (effDemo(doc.foto_card_teaser, 'foto_card_teaser', ov)) add('Foto teaser segreta');
  if (effDemo(doc.foto_segreta_hero, 'foto_segreta_hero', ov)) add('Foto Lato Segreto');
  if (effDemo(obj(doc.seo).og_image, 'seo_og', ov)) add('Immagine OG (SEO)');
  for (const pr of arr(doc.media_pairs)) {
    const pid = pr.id || '';
    const pub = obj(pr.pubblico);
    const sec = obj(pr.segreto);
    if (effDemo(pub.url, `pair:${pid}:pubblico`, ov)) add(pr.tipo === 'video' ? 'Video Lato Pubblico' : 'Foto Lato Pubblico (coppie)');
    if (effDemo(sec.url, `pair:${pid}:segreto`, ov)) add(pr.tipo === 'video' ? 'Video Lato Segreto' : 'Foto Lato Segreto (coppie)');
    if (pr.tipo === 'video' && (effDemo(pub.poster, `pair:${pid}:poster_pub`, ov) || effDemo(sec.poster, `pair:${pid}:poster_sec`, ov))) add('Poster video');
  }
  const ph = obj(doc.pellicola_home);
  const pp = obj(ph.pubblico);
  const ps = obj(ph.segreto);
  if (effDemo(pp.video_url, 'pel_pub_video', ov) || effDemo(pp.poster_url, 'pel_pub_poster', ov)) add('Video Pellicola Pubblico');
  if (effDemo(ps.video_url, 'pel_sec_video', ov) || effDemo(ps.poster_url, 'pel_sec_poster', ov)) add('Video Pellicola Segreto');
  const msg = obj(doc.messaggio_35s);
  if (effDemo(msg.foto, 'msg_foto', ov) || effDemo(msg.video, 'msg_video', ov)) add('Messaggio segreto (media)');
  if (effDemo(doc.onlyfans_url, 'onlyfans', ov, 'link')) add('Link OnlyFans');
  const social = obj(doc.social);
  const socialDemo = Object.entries(social).some(([k, v]) =>
    k === 'custom' ? arr(v).some((c) => autoDemoLink(obj(c).url)) : autoDemoLink(v));
  if (socialDemo) add('Social');
  return { is_demo: demo.length > 0, demo_fields: demo, demo_count: demo.length };
}

const countPairs = (doc, tipo, side) => arr(doc.media_pairs).filter((p) => p.tipo === tipo && nz(obj(p[side]).url)).length;
const pellicolaEffective = (ph, doc, side) =>
  nz(obj(ph[side]).video_url) || arr(doc.media_pairs).some((p) => p.tipo === 'video' && nz(obj(p[side]).url));

function readiness(doc) {
  let pubPhotos = countPairs(doc, 'image', 'pubblico');
  if (!pubPhotos) pubPhotos = arr(doc.galleria_pubblica).filter((g) => nz(g.url)).length;
  let secPhotos = countPairs(doc, 'image', 'segreto');
  if (!secPhotos) secPhotos = arr(doc.galleria_segreta).filter((g) => nz(g.url)).length;
  const checklist = [
    { label: 'Creator maggiorenne confermata', ok: Boolean(doc.conferma_maggiorenne), required: true },
    { label: 'Nome', ok: nz(doc.nome), required: true },
    { label: 'Slug (URL)', ok: nz(doc.slug), required: true },
    { label: 'Foto card Home', ok: nz(doc.foto_card), required: true },
    { label: '3 foto Lato Pubblico', ok: pubPhotos >= 3, required: true },
    { label: '3 foto Lato Segreto', ok: secPhotos >= 3, required: true },
    { label: 'Video pubblico 1', ok: countPairs(doc, 'video', 'pubblico') >= 1, required: true },
    { label: 'Video segreto 1', ok: countPairs(doc, 'video', 'segreto') >= 1, required: true },
    { label: 'Claim', ok: nz(doc.frase), required: true },
    { label: 'Descrizione pubblica', ok: nz(doc.bio), required: true },
    { label: 'Descrizione Lato Segreto', ok: nz(doc.bio_segreta), required: true },
    { label: 'Link OnlyFans', ok: nz(doc.onlyfans_url), required: true },
  ];
  const ph = obj(doc.pellicola_home);
  if (ph.attiva) {
    checklist.push({ label: 'Video Pellicola pubblico', ok: pellicolaEffective(ph, doc, 'pubblico'), required: true });
    checklist.push({ label: 'Video Pellicola segreto', ok: pellicolaEffective(ph, doc, 'segreto'), required: true });
  }
  const social = obj(doc.social);
  checklist.push({ label: 'Instagram (opzionale)', ok: nz(social.instagram), required: false });
  checklist.push({ label: 'TikTok (opzionale)', ok: nz(social.tiktok), required: false });
  const missing = checklist.filter((c) => c.required && !c.ok).map((c) => c.label);
  const pelLabels = new Set(['Video Pellicola pubblico', 'Video Pellicola segreto']);
  const profileMissing = missing.filter((m) => !pelLabels.has(m));
  const pellicolaMissing = missing.filter((m) => pelLabels.has(m));
  return {
    checklist, missing_required: missing, missing_count: missing.length, is_ready: missing.length === 0,
    profile_missing: profileMissing, profile_ready: profileMissing.length === 0,
    pellicola_missing: pellicolaMissing, pellicola_ready: pellicolaMissing.length === 0,
  };
}

function fullStatus(doc) {
  const rd = readiness(doc);
  return {
    content_status: contentStatus(doc),
    readiness: rd,
    stato_operativo: doc.stato === 'pubblicata' ? 'pubblicata' : rd.is_ready ? 'pronta' : 'incompleta',
  };
}

// ---------- public projection (routes_public.py) ----------
const PUBLIC_FIELDS = ['id', 'nome', 'nome_artistico', 'slug', 'frase', 'bio', 'foto_copertina', 'foto_card', 'foto_card_teaser',
  'categorie', 'tag', 'badge', 'badge_tipo', 'seo', 'ordine', 'data_pubblicazione', 'onlyfans_url', 'cta_testo', 'teaser_copy', 'social'];

function publicProjection(doc, views = 0) {
  const out = {};
  for (const k of PUBLIC_FIELDS) out[k] = doc[k] ?? null;
  out.galleria_pubblica = arr(doc.galleria_pubblica);
  out.video_pubblici = arr(doc.media_pairs).filter((p) => p.tipo === 'video').map((p) => p.pubblico);
  out.visite = views + (doc.visite_base || 0); // visite_base = views counted on the old site before the move
  out.has_secret = true;
  return out;
}

function secretProjection(d) {
  return {
    id: d.id, slug: d.slug,
    bio_segreta: d.bio_segreta || '', foto_segreta_hero: d.foto_segreta_hero || '',
    galleria_segreta: arr(d.galleria_segreta), media_pairs: arr(d.media_pairs),
    tema: obj(d.tema), regia: obj(d.regia), cta_temporizzata: obj(d.cta_temporizzata),
    social: obj(d.social), messaggio_35s: obj(d.messaggio_35s),
    onlyfans_url: d.onlyfans_url || '', cta_testo: d.cta_testo || 'CONTINUA CON ME', teaser_copy: d.teaser_copy || '',
  };
}

module.exports = {
  slugify, sanitizeHtml, normalizeModel, normalizeCategory, normalizeArticle,
  readiness, fullStatus, publicProjection, secretProjection, obj, arr,
};
