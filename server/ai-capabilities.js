// Capability registry of the AI interface (/api/v2/ai): what a custom GPT may do, bound to the same rules the admin uses.
// A handler never writes. It returns a plan { summary, data, changes, writes: [{ col, id, before, after }] };
// the dispatcher in ai.js stores the writes only for a real, permitted (and, if required, approved) execution.
// Preview and execution therefore always run the very same code.
const fs = require('fs');
const path = require('path');
const https = require('https');
const store = require('./db');
const C = require('./content');
const R = require('./rules');
const site = require('./site');
const seo = require('./seo');
const aiStore = require('./ai-store');
const media = require('./ai-media');

const SAFE = 'SAFE';
const REVIEW = 'REVIEW_REQUIRED';

class AiError extends Error {
  constructor(status, code, summary, data = {}, extra = {}) {
    super(summary);
    Object.assign(this, { status, code, summary, data, nextSteps: extra.next_steps || [], headers: extra.headers || {} });
  }
}
const invalid = (summary, data) => new AiError(422, 'VALIDATION_FAILED', summary, data);

// ---------------- helpers ----------------
const { obj, arr } = C;
const isObj = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const norm = (s) => String(s ?? '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim();
const etagOf = (doc) => doc?.updated_at || doc?.data_aggiornamento || null;
const displayName = (doc) => doc.nome_artistico || doc.nome || doc.titolo || doc.slug;

// deep merge for partial updates: objects are merged, everything else (arrays included) is replaced
function merge(base, changes) {
  const out = { ...base };
  for (const [k, v] of Object.entries(changes)) out[k] = isObj(v) && isObj(base?.[k]) ? merge(base[k], v) : v;
  return out;
}

// [{ field, before, after }] of what differs; nested objects are listed one level deep (seo.title, tema.preset ...)
function diff(before, after, prefix = '', depth = 0) {
  const out = [];
  for (const k of new Set([...Object.keys(before || {}), ...Object.keys(after || {})])) {
    if (k === 'updated_at' || k === 'data_aggiornamento') continue;
    const b = before?.[k];
    const a = after?.[k];
    if (same(b, a)) continue;
    if (depth < 1 && isObj(b) && isObj(a)) out.push(...diff(b, a, `${prefix}${k}.`, depth + 1));
    else out.push({ field: `${prefix}${k}`, before: b ?? null, after: a ?? null });
  }
  return out;
}

// Content written through this interface must not point at the old hosting again.
const LEGACY_HOST = /(^|\.)(emergent\.host|emergentagent\.com|emergent\.sh)$/i;
function legacyUrls(value, found = []) {
  if (typeof value === 'string') {
    for (const m of value.matchAll(/https?:\/\/([^\s/"'<>?#:]+)/gi)) if (LEGACY_HOST.test(m[1])) found.push(m[0]);
  } else if (value && typeof value === 'object') Object.values(value).forEach((v) => legacyUrls(v, found));
  return found;
}
function assertNoLegacyHost(value) {
  const found = legacyUrls(value);
  if (found.length) throw invalid('URL del vecchio hosting non consentiti: carica il file con media.upload_url e usa il percorso /api/uploads/…', { legacy_urls: [...new Set(found)].slice(0, 10) });
}

function onlyKeys(input, allowed, what) {
  if (!isObj(input)) throw invalid(`'${what}' deve essere un oggetto JSON`);
  const unknown = Object.keys(input).filter((k) => !allowed.includes(k));
  if (unknown.length) throw invalid(`Campi non modificabili o inesistenti in '${what}': ${unknown.join(', ')}`, { unknown, allowed });
}

// error of a shared rule (rules.js) -> error of this API
function ruleError(r) {
  const { status, detail } = r.error;
  if (isObj(detail) && detail.missing_required) {
    return new AiError(400, 'PUBLICATION_BLOCKED', `Non pubblicabile: mancano ${detail.missing_count} requisiti obbligatori`,
      { missing: detail.missing_required, missing_count: detail.missing_count }, { next_steps: ['Completa i requisiti mancanti (models.update, media.assign) e riprova', 'Non esiste alcuna forzatura della pubblicazione'] });
  }
  if (/già esistente/.test(String(detail))) return new AiError(409, 'CONFLICT', String(detail));
  return new AiError(status === 422 ? 422 : 400, 'VALIDATION_FAILED', String(detail));
}

// ---------------- natural references (id, slug, name; case- and accent-insensitive) ----------------
const KINDS = {
  model: { col: 'models', names: (d) => [d.nome, d.nome_artistico], label: 'Modella' },
  category: { col: 'categories', names: (d) => [d.nome], label: 'Categoria' },
  article: { col: 'articles', names: (d) => [d.titolo], label: 'Articolo' },
};

const workflowStatus = (m) => (m.is_deleted ? 'ARCHIVED' : m.stato === 'pubblicata' ? 'PUBLISHED' : C.readiness(m).is_ready ? 'READY' : 'INCOMPLETE');
const matchOf = (kind, d) => ({ id: d.id, nome: displayName(d), slug: d.slug, status: kind === 'model' ? workflowStatus(d) : d.stato });

function searchRef(kind, docs, ref) {
  const { names } = KINDS[kind];
  const needle = norm(ref);
  const bySlug = docs.filter((d) => norm(d.slug) === needle);
  if (bySlug.length === 1) return bySlug;
  const exact = docs.filter((d) => names(d).some((n) => norm(n) === needle));
  if (exact.length) return exact;
  // partial: substring of a name, or every word of the reference starts a word of the name in the same order
  const words = needle.split(' ');
  const prefixMatch = (name) => {
    const parts = norm(name).split(' ');
    let i = 0;
    for (const p of parts) if (i < words.length && p.startsWith(words[i])) i += 1;
    return i === words.length;
  };
  return docs.filter((d) => names(d).some((n) => n && (norm(n).includes(needle) || prefixMatch(n))) || norm(d.slug).includes(C.slugify(ref)));
}

function resolveRef(kind, ref, { includeDeleted = false } = {}) {
  const { col, label } = KINDS[kind];
  const text = String(ref ?? '').trim();
  if (!text) throw invalid(`Riferimento mancante (${label.toLowerCase()}: id, slug o nome)`);
  const all = store.all(col);
  const live = all.filter((d) => !d.is_deleted);
  const byId = all.find((d) => d.id === text);
  if (byId && (!byId.is_deleted || includeDeleted)) return byId;
  let found = searchRef(kind, live, text);
  // deleted entries are never picked instead of live ones
  if (!found.length && includeDeleted) found = searchRef(kind, all.filter((d) => d.is_deleted), text);
  if (found.length === 1) return found[0];
  if (found.length > 1) {
    throw new AiError(409, 'AMBIGUOUS_REFERENCE', `Riferimento ambiguo: '${text}' corrisponde a ${found.length} elementi`,
      { matches: found.slice(0, 20).map((d) => matchOf(kind, d)) }, { next_steps: ['Mostra le corrispondenze all\'utente e ripeti la richiesta con lo slug o l\'id scelto'] });
  }
  const hint = !includeDeleted && kind === 'model' && (byId || searchRef(kind, all.filter((d) => d.is_deleted), text).length)
    ? ['Esiste una modella eliminata con questo riferimento: models.undelete la recupera'] : [];
  throw new AiError(404, 'NOT_FOUND', `${label} '${text}' non trovata`, {}, { next_steps: hint });
}

const targetOf = (kind, doc) => ({ type: kind, id: doc.id, slug: doc.slug, nome: displayName(doc), etag: etagOf(doc) });
const PUBLIC_PATH = { model: 'modelle', category: 'categorie', article: 'articoli' };
const publicUrl = (ctx, kind, doc) => `${ctx.base}/${PUBLIC_PATH[kind]}/${doc.slug}`;

function modelSummary(ctx, m) {
  const st = C.fullStatus(m);
  return {
    id: m.id, slug: m.slug, nome: m.nome, nome_artistico: m.nome_artistico, stato: m.stato, stato_operativo: st.stato_operativo,
    workflow_status: workflowStatus(m), missing_count: st.readiness.missing_count, is_demo: st.content_status.is_demo,
    categorie: arr(m.categorie), tag: arr(m.tag), badge: m.badge ?? null, ordine: m.ordine || 0, etag: etagOf(m), public_url: publicUrl(ctx, 'model', m),
  };
}

// ---------------- registry ----------------
const REGISTRY = new Map();
function cap(def) {
  if (REGISTRY.has(def.id)) throw new Error(`Duplicate capability id: ${def.id}`);
  REGISTRY.set(def.id, {
    capability_version: '1.0', risk: SAFE, target: 'none', optionalTarget: false, readOnly: false, rollback: true,
    params: {}, examples: [], natural: [], ...def,
  });
}

const requiredParams = (c) => Object.entries(c.params).filter(([, spec]) => spec.required).map(([k]) => k);

function exampleParams(c) {
  const ex = { ...(c.examples[0]?.parameters || {}) };
  const placeholder = { string: '<string>', integer: 1, number: 1, boolean: true, array: [], object: {} };
  for (const k of requiredParams(c)) if (!(k in ex)) ex[k] = c.params[k].example ?? placeholder[c.params[k].type] ?? '<value>';
  return ex;
}

// the exact previewCapability body for this capability: the GPT copies it and fills in the values
function requestExample(c, target) {
  const body = { action: c.id, parameters: exampleParams(c), dry_run: true, reason: '<perché>' };
  if (c.target !== 'none') body.target = target || c.examples[0]?.target || `<${c.target}: id, slug o nome>`;
  return body;
}

const HOW_TO_CALL = 'POST /api/v2/ai/preview (o /execute) con body {action: id, target?, parameters: {<esattamente i nomi di parameters_schema>}, dry_run, reason}. '
  + 'I parametri obbligatori vanno DENTRO `parameters` (ripiego: `parameters_json` = stesso oggetto come stringa JSON).';

function describe(c) {
  return {
    id: c.id, capability: c.id, capability_version: c.capability_version, category: c.category, description: c.description, risk: c.risk,
    required_scopes: c.scopes, required_scopes_execute: c.scopes, required_scopes_preview: c.readOnly ? c.scopes : [...new Set(c.scopes.map(aiStore.previewScope))],
    read_only: c.readOnly, supports_dry_run: !c.readOnly, supports_rollback: !c.readOnly && c.rollback, requires_approval: c.risk === REVIEW,
    target: c.target, target_optional: c.optionalTarget,
    parameters_schema: { type: 'object', properties: c.params }, required_parameters: requiredParams(c), example_parameters: exampleParams(c),
    request_example: requestExample(c), how_to_call: HOW_TO_CALL, examples: c.examples, natural_references: c.natural,
  };
}

// what this principal may do with a capability: full | preview_only | none
function accessFor(principal, c) {
  const execMissing = aiStore.missingScopes(principal, ['ai:execute', ...c.scopes], false);
  const prevMissing = c.readOnly ? execMissing : aiStore.missingScopes(principal, ['ai:execute', ...c.scopes], true);
  const execute = execMissing.length ? 'none' : 'full';
  const preview = c.readOnly ? 'n/a' : prevMissing.length ? 'none' : 'preview_only';
  return {
    access: execute === 'full' ? 'full' : preview === 'preview_only' ? 'preview_only' : 'none', execute_access: execute, preview_access: preview,
    missing_scopes_execute: execMissing, missing_scopes_preview: preview === 'none' ? prevMissing : [],
  };
}

// =====================================================================================================================
// MODELS
// =====================================================================================================================
const BADGES = ['NUOVA', 'IN TENDENZA', 'PIÙ VISTA', 'SCELTA DEL GIORNO']; // the badges the admin editor offers
const MODEL_DEFAULTS = C.normalizeModel({});
// stato / deletion go through publish, unpublish, soft_delete, undelete; the age confirmation is a human statement (admin only)
const MODEL_LOCKED = ['stato', 'is_deleted', 'data_pubblicazione', 'analytics', 'conferma_maggiorenne'];
const MODEL_EDITABLE = Object.keys(MODEL_DEFAULTS).filter((k) => !MODEL_LOCKED.includes(k));
const SEO_FIELDS = Object.keys(MODEL_DEFAULTS.seo);
const MODEL_FIELDS_DOC = `Campi: ${MODEL_EDITABLE.join(', ')}. Oggetti annidati (tema, messaggio_35s, seo, pellicola_home, regia, cta_temporizzata, social) vengono uniti campo per campo; `
  + 'gli array (categorie, tag, galleria_*, media_pairs) vengono sostituiti. Non modificabili da qui: stato (usa models.publish/unpublish), conferma_maggiorenne (solo pannello admin).';

function checkModelFields(input, what) {
  if (isObj(input) && 'conferma_maggiorenne' in input) {
    throw invalid('La conferma della maggiore età può essere impostata solo da un amministratore nel pannello (non tramite API)', { field: 'conferma_maggiorenne' });
  }
  if (isObj(input) && 'stato' in input) throw invalid('Lo stato non si cambia con i campi: usa models.publish, models.unpublish o models.soft_delete', { field: 'stato' });
  onlyKeys(input, MODEL_EDITABLE, what);
  assertNoLegacyHost(input);
}

// one path for every change to an existing model: partial changes -> the admin update rule -> plan
function planModelUpdate(ctx, doc, changes, done) {
  const r = R.buildModelUpdate(doc, merge(doc, changes));
  if (r.error) throw ruleError(r);
  const changed = diff(doc, r.doc);
  const name = displayName(doc);
  if (!changed.length) return { summary: `Nessuna modifica: ${name} ha già questi valori`, data: { unchanged: true, ...modelSummary(ctx, doc) }, target: targetOf('model', doc) };
  const warnings = [];
  if (r.auto?.type === 'bozza') warnings.push(`Modella pubblicata resa incompleta dalla modifica: torna in bozza (mancano: ${r.auto.missing.join(', ')})`);
  if (r.auto?.type === 'pellicola_off') warnings.push(`Pellicola disattivata: mancano ${r.auto.missing.join(', ')}`);
  if (doc.stato === 'pubblicata' && r.doc.slug !== doc.slug) warnings.push(`L'URL pubblico cambia da /modelle/${doc.slug} a /modelle/${r.doc.slug}: nessun redirect automatico`);
  const fields = changed.map((c) => c.field).join(', ');
  return {
    summary: ctx.say(`${name}: ${done || 'aggiornata'} (${fields}); stato ${r.doc.stato}`, `${name}: cambierebbero ${changed.length} campi (${fields})`),
    data: { ...modelSummary(ctx, r.doc), readiness: C.readiness(r.doc).missing_required },
    changes: changed, warnings, writes: [{ col: 'models', id: doc.id, before: doc, after: r.doc }], target: targetOf('model', r.doc),
  };
}

cap({
  id: 'models.list', category: 'models', scopes: ['models:read'], readOnly: true,
  description: 'Elenca le modelle (non eliminate) con stato, readiness e URL pubblico. Filtri opzionali: stato, status, category, tag, q.',
  params: {
    stato: { type: 'string', enum: ['bozza', 'pubblicata', 'disattivata'] }, status: { type: 'string', enum: ['PUBLISHED', 'READY', 'INCOMPLETE'] },
    category: { type: 'string', description: 'slug categoria' }, tag: { type: 'string' }, q: { type: 'string', description: 'testo in nome/slug' },
    limit: { type: 'integer', default: 100 },
  },
  natural: ['quali modelle ci sono', 'elenca le modelle in bozza'],
  handler(ctx) {
    const p = ctx.params;
    let items = R.liveModels().sort((a, b) => (a.ordine || 0) - (b.ordine || 0));
    if (p.stato) items = items.filter((m) => m.stato === p.stato);
    if (p.category) items = items.filter((m) => arr(m.categorie).includes(p.category));
    if (p.tag) items = items.filter((m) => arr(m.tag).map(norm).includes(norm(p.tag)));
    if (p.q) items = items.filter((m) => [m.nome, m.nome_artistico, m.slug].some((v) => norm(v).includes(norm(p.q))));
    let out = items.map((m) => modelSummary(ctx, m));
    if (p.status) out = out.filter((m) => m.workflow_status === p.status);
    const total = out.length;
    out = out.slice(0, Math.max(1, Math.min(500, p.limit || 100)));
    const by = {};
    for (const m of out) by[m.stato] = (by[m.stato] || 0) + 1;
    return { summary: `${total} modelle (${Object.entries(by).map(([k, v]) => `${v} ${k}`).join(', ') || 'nessuna'})`, data: { items: out, total, by_stato: by } };
  },
});

cap({
  id: 'models.get', category: 'models', scopes: ['models:read'], readOnly: true, target: 'model',
  description: 'Scheda completa di una modella: tutti i campi, media, SEO, readiness (cosa manca per pubblicare), URL pubblico.',
  natural: ['mostrami la scheda di Francesca', 'dati completi di Aurora'],
  handler(ctx) {
    const m = ctx.target;
    return { summary: `Scheda di ${displayName(m)} (${m.stato})`, data: { ...R.withStatus(m), etag: etagOf(m), public_url: publicUrl(ctx, 'model', m) }, target: targetOf('model', m) };
  },
});

cap({
  id: 'models.create', category: 'models', scopes: ['models:create'],
  description: `Crea una nuova modella in BOZZA (non pubblica mai). ${MODEL_FIELDS_DOC}`,
  params: { nome: { type: 'string', required: true, example: 'Giulia Rossi' }, fields: { type: 'object', description: 'altri campi del formulario (facoltativi)' } },
  examples: [{ action: 'models.create', parameters: { nome: 'Giulia Rossi', fields: { frase: 'Più di quello che vedi.', categorie: ['more'], tag: ['estate'] } } }],
  natural: ['aggiungi una modella', 'crea Giulia Rossi'],
  handler(ctx) {
    const fields = ctx.params.fields ?? {};
    checkModelFields(fields, 'fields');
    const r = R.buildModelCreate({ ...fields, nome: String(ctx.params.nome).trim(), stato: 'bozza' });
    if (r.error) throw ruleError(r);
    const { doc } = r;
    const rd = C.readiness(doc);
    return {
      summary: ctx.say(`Bozza '${doc.nome}' creata (slug ${doc.slug}); mancano ${rd.missing_count} requisiti per pubblicare`, `Verrebbe creata la bozza '${doc.nome}' (slug ${doc.slug})`),
      // the id only exists once the draft is really stored
      data: { ...modelSummary(ctx, doc), id: ctx.dry ? null : doc.id, readiness: rd.missing_required },
      changes: [{ field: 'model', before: null, after: doc.slug }],
      writes: [{ col: 'models', id: doc.id, before: null, after: doc }], target: ctx.dry ? null : targetOf('model', doc),
      next_steps: ['models.update per compilare i campi', 'media.upload_url + media.assign per foto e video', 'models.validate per vedere cosa manca'],
    };
  },
});

cap({
  id: 'models.update', category: 'models', scopes: ['models:update'], target: 'model',
  description: `Modifica uno o più campi di una modella (aggiornamento parziale). ${MODEL_FIELDS_DOC}`,
  params: { changes: { type: 'object', required: true, example: { badge: 'NUOVA' }, description: 'solo i campi da cambiare' } },
  examples: [{ action: 'models.update', target: 'Francesca', parameters: { changes: { tag: ['estate', 'mare'], tema: { preset: 'bordeaux' } } } }],
  natural: ['cambia la bio di Francesca', 'imposta il preset bordeaux ad Aurora'],
  handler(ctx) {
    checkModelFields(ctx.params.changes, 'changes');
    if (!Object.keys(ctx.params.changes).length) throw invalid("Nessun campo in 'changes'", { allowed: MODEL_EDITABLE });
    return planModelUpdate(ctx, ctx.target, ctx.params.changes);
  },
});

cap({
  id: 'models.validate', category: 'models', scopes: ['models:validate'], readOnly: true, target: 'model',
  description: 'Controlla se una modella è pronta per la pubblicazione: requisiti mancanti, checklist completa, contenuti ancora demo.',
  natural: ['manca qualcosa a Giulia?', 'Giulia è pronta?'],
  handler(ctx) {
    const m = ctx.target;
    const st = C.fullStatus(m);
    const rd = st.readiness;
    return {
      summary: `${displayName(m)}: ${rd.is_ready ? 'pronta alla pubblicazione' : `non pubblicabile, mancano ${rd.missing_count} requisiti`} (stato ${m.stato})`,
      data: { ready: rd.is_ready, stato: m.stato, stato_operativo: st.stato_operativo, missing: rd.missing_required, checklist: rd.checklist, demo_fields: st.content_status.demo_fields },
      target: targetOf('model', m),
    };
  },
});

// publish / unpublish share the admin rule for the state change (publish always passes the readiness check)
function planStato(ctx, stato, done) {
  const m = ctx.target;
  const name = displayName(m);
  if (m.stato === stato) return { summary: `Nessuna modifica: ${name} è già '${stato}'`, data: { unchanged: true, ...modelSummary(ctx, m) }, target: targetOf('model', m) };
  const r = R.buildModelStato(m, stato);
  if (r.error) {
    const e = ruleError(r);
    // a preview reports the blocker as a result, an execution fails
    if (ctx.dry && e.code === 'PUBLICATION_BLOCKED') {
      return { summary: `${name} non è pubblicabile: mancano ${e.data.missing_count} requisiti`, data: { blocked: true, ...e.data }, warnings: e.data.missing.map((x) => `Manca: ${x}`), target: targetOf('model', m), next_steps: e.nextSteps };
    }
    throw e;
  }
  return {
    summary: ctx.say(`${name}: ${done} (${m.stato} → ${stato})`, `${name}: lo stato passerebbe da ${m.stato} a ${stato}`),
    data: modelSummary(ctx, r.doc), changes: [{ field: 'stato', before: m.stato, after: stato }],
    writes: [{ col: 'models', id: m.id, before: m, after: r.doc }], target: targetOf('model', r.doc),
  };
}

cap({
  id: 'models.publish', category: 'models', scopes: ['models:publish'], target: 'model',
  description: 'Pubblica una modella. Passa SEMPRE dal controllo di readiness: se manca qualcosa risponde PUBLICATION_BLOCKED con l\'elenco. Nessuna forzatura.',
  natural: ['pubblica Giulia', 'metti online Giulia'],
  handler: (ctx) => planStato(ctx, 'pubblicata', 'pubblicata'),
});

cap({
  id: 'models.unpublish', category: 'models', scopes: ['models:unpublish'], target: 'model', risk: REVIEW,
  description: 'Toglie dal sito una modella pubblicata: torna in bozza (o "disattivata"). Richiede approvazione.',
  params: { stato: { type: 'string', enum: ['bozza', 'disattivata'], default: 'bozza' } },
  natural: ['togli Vanessa dal sito', 'sospendi Francesca'],
  handler(ctx) {
    const stato = ctx.params.stato || 'bozza';
    if (!['bozza', 'disattivata'].includes(stato)) throw invalid("'stato' deve essere bozza o disattivata");
    if (ctx.target.stato !== 'pubblicata') return { summary: `Nessuna modifica: ${displayName(ctx.target)} non è pubblicata`, data: { unchanged: true, ...modelSummary(ctx, ctx.target) }, target: targetOf('model', ctx.target) };
    return planStato(ctx, stato, 'tolta dal sito');
  },
});

cap({
  id: 'models.soft_delete', category: 'models', scopes: ['models:archive'], target: 'model', risk: REVIEW,
  description: 'Eliminazione LOGICA di una modella (sparisce dal sito e dagli elenchi, recuperabile con models.undelete). Richiede approvazione. L\'eliminazione definitiva non esiste via API.',
  natural: ['elimina la modella di test'],
  handler(ctx) {
    const m = ctx.target;
    const { doc } = R.buildModelDelete(m);
    return {
      summary: ctx.say(`${displayName(m)} eliminata logicamente (recuperabile)`, `${displayName(m)} verrebbe eliminata logicamente (recuperabile con models.undelete)`),
      data: { id: m.id, slug: m.slug, is_deleted: true }, changes: [{ field: 'is_deleted', before: false, after: true }, { field: 'stato', before: m.stato, after: doc.stato }],
      writes: [{ col: 'models', id: m.id, before: m, after: doc }], target: targetOf('model', doc), next_steps: ['Recupero: models.undelete {model}'],
    };
  },
});

cap({
  id: 'models.undelete', category: 'models', scopes: ['models:archive'],
  description: 'Recupera una modella eliminata logicamente: torna in bozza (mai pubblicata in automatico).',
  params: { model: { type: 'string', required: true, description: 'id, slug o nome della modella eliminata' } },
  natural: ['recupera la modella eliminata'],
  handler(ctx) {
    const m = resolveRef('model', ctx.params.model, { includeDeleted: true });
    if (!m.is_deleted) return { summary: `Nessuna modifica: ${displayName(m)} non è eliminata`, data: { unchanged: true, ...modelSummary(ctx, m) }, target: targetOf('model', m) };
    const { deleted_at: _d, stato_precedente: _s, ...rest } = m;
    const doc = { ...rest, is_deleted: false, stato: 'bozza', slug: R.uniqueSlug(m.slug, m.id), updated_at: store.nowIso() };
    return {
      summary: ctx.say(`${displayName(m)} recuperata in bozza`, `${displayName(m)} verrebbe recuperata in bozza`), data: modelSummary(ctx, doc),
      changes: [{ field: 'is_deleted', before: true, after: false }, { field: 'stato', before: m.stato, after: 'bozza' }],
      writes: [{ col: 'models', id: m.id, before: m, after: doc }], target: targetOf('model', doc),
    };
  },
});

cap({
  id: 'models.categories.set', category: 'models', scopes: ['models:update'], target: 'model',
  description: 'Imposta le categorie di una modella (sostituisce l\'elenco). Accetta slug o nomi di categorie esistenti.',
  params: { categories: { type: 'array', items: { type: 'string' }, required: true, example: ['more'] } },
  natural: ['metti Francesca nella categoria more'],
  handler(ctx) {
    const known = store.all('categories');
    const unknown = [];
    const slugs = ctx.params.categories.map((c) => {
      const hit = known.find((k) => k.slug === String(c).trim() || norm(k.nome) === norm(c));
      if (!hit) unknown.push(c);
      return hit?.slug;
    });
    if (unknown.length) throw invalid(`Categorie inesistenti: ${unknown.join(', ')}`, { unknown, available: known.map((k) => k.slug) });
    return planModelUpdate(ctx, ctx.target, { categorie: [...new Set(slugs)] }, 'categorie impostate');
  },
});

cap({
  id: 'models.set_seo', category: 'models', scopes: ['models:update'], target: 'model',
  description: `Imposta i campi SEO di una modella (solo quelli indicati). Campi: ${SEO_FIELDS.join(', ')}.`,
  params: { seo: { type: 'object', required: true, example: { title: 'Giulia Rossi | LATO SEGRETO', meta_description: 'Scopri il lato segreto di Giulia.' } } },
  natural: ['scrivi il titolo SEO di Giulia'],
  handler(ctx) {
    onlyKeys(ctx.params.seo, SEO_FIELDS, 'seo');
    assertNoLegacyHost(ctx.params.seo);
    return planModelUpdate(ctx, ctx.target, { seo: ctx.params.seo }, 'SEO aggiornata');
  },
});

cap({
  id: 'models.feature', category: 'models', scopes: ['models:feature'], target: 'model',
  description: `Mette in evidenza una modella: badge (${BADGES.join(' | ')}), posizione in Home (ordine: 0 = prima) e/o presenza nella pellicola (filmstrip). Indica almeno un parametro.`,
  params: { badge: { type: 'string', enum: BADGES }, ordine: { type: 'integer' }, filmstrip: { type: 'boolean' } },
  examples: [{ action: 'models.feature', target: 'Aurora', parameters: { badge: 'IN TENDENZA' } }],
  natural: ['metti Aurora in tendenza', 'porta Francesca in cima'],
  handler(ctx) {
    const p = ctx.params;
    const ch = {};
    if (p.badge != null) {
      if (!BADGES.includes(p.badge)) throw invalid(`Badge non valido: usa uno tra ${BADGES.join(', ')}`, { allowed: BADGES });
      ch.badge = p.badge;
    }
    if (p.ordine != null) ch.ordine = p.ordine;
    if (p.filmstrip != null) ch.pellicola_home = { attiva: p.filmstrip };
    if (!Object.keys(ch).length) throw invalid('Indica almeno uno tra badge, ordine, filmstrip', { allowed_badges: BADGES });
    return planModelUpdate(ctx, ctx.target, ch, 'messa in evidenza');
  },
});

cap({
  id: 'models.unfeature', category: 'models', scopes: ['models:feature'], target: 'model',
  description: 'Rimuove il badge di una modella.',
  natural: ["togli l'evidenza ad Aurora"],
  handler: (ctx) => planModelUpdate(ctx, ctx.target, { badge: null }, 'badge rimosso'),
});

cap({
  id: 'models.reorder', category: 'models', scopes: ['models:feature'],
  description: 'Ordine delle modelle in Home: la prima dell\'elenco prende ordine 0, la seconda 1, ecc. (come il trascinamento nel pannello). Le modelle non elencate restano invariate.',
  params: { order: { type: 'array', items: { type: 'string' }, required: true, description: 'id, slug o nomi nell\'ordine desiderato', example: ['francesca-rossi', 'aurora-caruso'] } },
  natural: ['metti Francesca prima di Aurora in Home'],
  handler(ctx) {
    const docs = ctx.params.order.map((ref) => resolveRef('model', ref));
    if (new Set(docs.map((d) => d.id)).size !== docs.length) throw invalid("'order' contiene la stessa modella più volte");
    const writes = [];
    const changes = [];
    docs.forEach((m, idx) => {
      if ((m.ordine || 0) === idx) return;
      writes.push({ col: 'models', id: m.id, before: m, after: { ...m, ordine: idx } });
      changes.push({ field: `${m.slug}.ordine`, before: m.ordine || 0, after: idx });
    });
    return {
      summary: writes.length ? ctx.say(`Ordine aggiornato per ${writes.length} modelle`, `Cambierebbe l'ordine di ${writes.length} modelle`) : 'Nessuna modifica: l\'ordine è già questo',
      data: { order: docs.map((m, idx) => ({ slug: m.slug, ordine: idx })) }, changes, writes,
    };
  },
});

// =====================================================================================================================
// MEDIA
// =====================================================================================================================
const VIDEO_EXT = ['mp4', 'webm', 'mov'];
// slot name -> [path inside the model, expected type]; left the real field path, right the aliases of the old API
const SLOTS = {
  foto_card: ['foto_card', 'image'], card: ['foto_card', 'image'],
  foto_copertina: ['foto_copertina', 'image'], cover: ['foto_copertina', 'image'], copertina: ['foto_copertina', 'image'],
  foto_card_teaser: ['foto_card_teaser', 'image'], teaser: ['foto_card_teaser', 'image'],
  foto_segreta_hero: ['foto_segreta_hero', 'image'], secret_hero: ['foto_segreta_hero', 'image'], hero_segreta: ['foto_segreta_hero', 'image'],
  'seo.og_image': ['seo.og_image', 'image'], og_image: ['seo.og_image', 'image'],
  'messaggio_35s.foto': ['messaggio_35s.foto', 'image'], message_photo: ['messaggio_35s.foto', 'image'],
  'messaggio_35s.video': ['messaggio_35s.video', 'video'], message_video: ['messaggio_35s.video', 'video'],
  'pellicola_home.pubblico.video_url': ['pellicola_home.pubblico.video_url', 'video'], filmstrip_public: ['pellicola_home.pubblico.video_url', 'video'], pellicola_pubblica: ['pellicola_home.pubblico.video_url', 'video'],
  'pellicola_home.segreto.video_url': ['pellicola_home.segreto.video_url', 'video'], filmstrip_secret: ['pellicola_home.segreto.video_url', 'video'], pellicola_segreta: ['pellicola_home.segreto.video_url', 'video'],
  'pellicola_home.pubblico.poster_url': ['pellicola_home.pubblico.poster_url', 'image'], filmstrip_poster_public: ['pellicola_home.pubblico.poster_url', 'image'],
  'pellicola_home.segreto.poster_url': ['pellicola_home.segreto.poster_url', 'image'], filmstrip_poster_secret: ['pellicola_home.segreto.poster_url', 'image'],
};
const GALLERIES = { galleria_pubblica: 'galleria_pubblica', gallery_public: 'galleria_pubblica', galleria_segreta: 'galleria_segreta', gallery_secret: 'galleria_segreta' };
const PAIR_SLOT = /^(public|secret|pubblic[ao]|segret[ao])_(photo|foto|video)_(\d{1,2})$/;
const SLOT_DOC = 'Slot: foto_card, foto_copertina, foto_card_teaser, foto_segreta_hero, seo.og_image, messaggio_35s.foto, messaggio_35s.video, '
  + 'pellicola_home.pubblico.video_url, pellicola_home.segreto.video_url, pellicola_home.pubblico.poster_url, pellicola_home.segreto.poster_url, '
  + 'galleria_pubblica, galleria_segreta (aggiunge in coda), coppie media_pairs: public_photo_N, secret_photo_N, public_video_N, secret_video_N (N = 1, 2, 3…). '
  + 'Alias accettati: card, cover, teaser, secret_hero, og_image, filmstrip_public, filmstrip_secret, message_photo, message_video, gallery_public, gallery_secret.';

// an uploaded file of this server: /api/uploads/... that really exists below the uploads folder
function uploadedFile(url) {
  const u = String(url ?? '').trim();
  if (!/^\/api\/uploads\/[A-Za-z0-9._/-]+$/.test(u) || u.includes('..')) {
    throw invalid('Serve l\'URL di un file caricato su questo sito (/api/uploads/…): carica prima il file con media.upload_url', { received: u.slice(0, 200) });
  }
  const file = path.resolve(store.UPLOADS_DIR, u.slice('/api/uploads/'.length));
  if (!file.startsWith(store.UPLOADS_DIR + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) throw new AiError(404, 'NOT_FOUND', `File non trovato: ${u}`);
  return { url: u, tipo: VIDEO_EXT.includes(path.extname(file).slice(1).toLowerCase()) ? 'video' : 'image' };
}

const nested = (dotted, value) => dotted.split('.').reduceRight((acc, key) => ({ [key]: acc }), value);

cap({
  id: 'media.upload_url', category: 'media', scopes: ['media:upload'], rollback: false,
  description: 'Carica una foto o un video da un URL pubblico http(s) oppure da base64 (jpg, png, webp, avif, gif, mp4, webm, mov; max 200MB). '
    + 'Restituisce il percorso /api/uploads/… da usare con media.assign. Non assegna nulla a una modella.',
  params: {
    url: { type: 'string', description: 'URL pubblico del file' }, base64_data: { type: 'string', description: 'in alternativa: contenuto in base64 (anche data:…;base64,…), file piccoli' },
  },
  examples: [{ action: 'media.upload_url', parameters: { url: 'https://example.com/foto.jpg' } }],
  natural: ['carica questa foto', 'aggiungi il video da questo link'],
  async handler(ctx) {
    const { url, base64_data: b64 } = ctx.params;
    if (Boolean(url) === Boolean(b64)) throw invalid("Indica 'url' oppure 'base64_data' (uno solo)");
    try {
      if (url) media.checkUrl(url);
      if (ctx.dry) {
        return { summary: 'Anteprima: nessun file scaricato. Con l\'esecuzione il file viene scaricato, controllato e salvato', data: { would_upload: url || '<base64>' }, next_steps: ['Dopo il caricamento: media.assign {url, slot}'] };
      }
      const f = url ? await media.fromUrl(url) : media.fromBase64(b64);
      return {
        summary: `File caricato: ${f.tipo} ${f.mime}, ${Math.round(f.size / 1024)} KB`,
        data: { url: f.url, tipo: f.tipo, mime: f.mime, size: f.size, public_url: `${ctx.base}${f.url}` },
        changes: [{ field: 'file', before: null, after: f.url }], next_steps: [`media.assign {url: '${f.url}', slot} per usarlo in una modella`],
      };
    } catch (e) {
      if (e instanceof media.MediaError) throw new AiError(422, 'MEDIA_VALIDATION_FAILED', e.message);
      throw e;
    }
  },
});

cap({
  id: 'media.assign', category: 'media', scopes: ['media:upload', 'models:update'], target: 'model',
  description: `Mette un file già caricato (/api/uploads/…) in uno slot della modella. ${SLOT_DOC}`,
  params: {
    url: { type: 'string', required: true, example: '/api/uploads/lato-segreto/uploads/abc.jpg', description: 'percorso restituito da media.upload_url' },
    slot: { type: 'string', required: true, example: 'foto_card' }, alt: { type: 'string' }, poster: { type: 'string', description: 'per i video delle coppie: immagine poster già caricata' },
  },
  examples: [{ action: 'media.assign', target: 'Giulia Rossi', parameters: { url: '/api/uploads/lato-segreto/uploads/abc.jpg', slot: 'secret_photo_2' } }],
  natural: ['metti questa foto come seconda foto segreta di Giulia', 'usa questa immagine come card'],
  handler(ctx) {
    const m = ctx.target;
    const slot = String(ctx.params.slot).trim().toLowerCase();
    const file = uploadedFile(ctx.params.url);
    const poster = ctx.params.poster ? uploadedFile(ctx.params.poster).url : '';
    const alt = ctx.params.alt || '';
    const need = (tipo) => { if (file.tipo !== tipo) throw invalid(`Lo slot '${slot}' richiede ${tipo === 'video' ? 'un video' : 'un\'immagine'}, il file è ${file.tipo}`); };
    let changes;
    const pair = slot.match(PAIR_SLOT);
    if (SLOTS[slot]) {
      need(SLOTS[slot][1]);
      changes = nested(SLOTS[slot][0], file.url);
    } else if (GALLERIES[slot]) {
      need('image');
      changes = { [GALLERIES[slot]]: [...arr(m[GALLERIES[slot]]), { tipo: 'image', url: file.url, poster: '', alt }] };
    } else if (pair) {
      const side = pair[1].startsWith('pub') ? 'pubblico' : 'segreto';
      const tipo = pair[2] === 'video' ? 'video' : 'image';
      const n = parseInt(pair[3], 10);
      need(tipo);
      const pairs = arr(m.media_pairs).map((p) => ({ ...p }));
      const ofType = pairs.filter((p) => p.tipo === tipo);
      if (n < 1 || n > ofType.length + 1) throw invalid(`Slot '${slot}' non disponibile: esistono ${ofType.length} coppie ${tipo}, la prossima è la numero ${ofType.length + 1}`);
      const item = { tipo, url: file.url, poster, alt };
      if (n <= ofType.length) ofType[n - 1][side] = { ...obj(ofType[n - 1][side]), ...item, poster: poster || obj(ofType[n - 1][side]).poster || '' };
      else pairs.push({ tipo, [side]: item });
      changes = { media_pairs: pairs };
    } else {
      throw invalid(`Slot '${slot}' non valido`, { slots: [...Object.keys(SLOTS).filter((k) => k === SLOTS[k][0]), 'galleria_pubblica', 'galleria_segreta', 'public_photo_N', 'secret_photo_N', 'public_video_N', 'secret_video_N'] });
    }
    const plan = planModelUpdate(ctx, m, changes, `media assegnato a ${slot}`);
    plan.data = { ...plan.data, slot, url: file.url, tipo: file.tipo };
    return plan;
  },
});

// every media reference of a model with the field it sits in
function mediaOf(m) {
  const items = [];
  const add = (field, url, extra = {}) => { if (url) items.push({ field, url, ...extra }); };
  for (const [slot, [field, tipo]] of Object.entries(SLOTS)) if (slot === field) add(field, field.split('.').reduce((o, k) => obj(o)[k], m), { tipo });
  for (const g of ['galleria_pubblica', 'galleria_segreta']) arr(m[g]).forEach((x, i) => add(`${g}[${i}]`, x.url, { tipo: x.tipo || 'image', alt: x.alt || '' }));
  const count = {};
  for (const p of arr(m.media_pairs)) {
    const kind = p.tipo === 'video' ? 'video' : 'photo';
    count[kind] = (count[kind] || 0) + 1;
    for (const [side, name] of [['pubblico', 'public'], ['segreto', 'secret']]) {
      const x = obj(p[side]);
      add(`media_pairs:${name}_${kind}_${count[kind]}`, x.url, { tipo: p.tipo, alt: x.alt || '', poster: x.poster || '' });
    }
  }
  return items.map((it) => {
    const local = it.url.startsWith('/api/uploads/');
    return { ...it, local, exists: local ? fs.existsSync(path.join(store.UPLOADS_DIR, it.url.slice('/api/uploads/'.length))) : null };
  });
}

cap({
  id: 'media.list', category: 'media', scopes: ['media:read'], readOnly: true, target: 'model',
  description: 'Elenca i file (foto e video) usati da una modella: campo/slot, tipo, URL, se il file esiste sul server.',
  natural: ['quali foto ha Giulia', 'media di Francesca'],
  handler(ctx) {
    const items = mediaOf(ctx.target);
    const missing = items.filter((i) => i.exists === false).length;
    return {
      summary: `${displayName(ctx.target)}: ${items.length} media${missing ? `, ${missing} file mancanti sul server` : ''}`,
      data: { items, count: items.length, missing_files: missing }, target: targetOf('model', ctx.target),
    };
  },
});

// =====================================================================================================================
// CATEGORIES + ARTICLES
// =====================================================================================================================
const CATEGORY_FIELDS = Object.keys(C.normalizeCategory({}));
const ARTICLE_FIELDS = Object.keys(C.normalizeArticle({}));

function planDocUpdate(ctx, kind, existing, r) {
  if (r.error) throw ruleError(r);
  const changed = diff(existing, r.doc);
  const name = displayName(existing);
  if (!changed.length) return { summary: `Nessuna modifica: '${name}' ha già questi valori`, data: { unchanged: true, id: existing.id, slug: existing.slug }, target: targetOf(kind, existing) };
  const fields = changed.map((c) => c.field).join(', ');
  return {
    summary: ctx.say(`'${name}' aggiornata (${fields})`, `'${name}': cambierebbero ${changed.length} campi (${fields})`),
    data: { ...r.doc, etag: etagOf(r.doc), public_url: publicUrl(ctx, kind, r.doc) }, changes: changed,
    writes: [{ col: KINDS[kind].col, id: existing.id, before: existing, after: r.doc }], target: targetOf(kind, r.doc),
  };
}

function planDocCreate(ctx, kind, r, label) {
  if (r.error) throw ruleError(r);
  const { doc } = r;
  return {
    summary: ctx.say(`${label} '${displayName(doc)}' creata (slug ${doc.slug}, stato ${doc.stato})`, `Verrebbe creata ${label.toLowerCase()} '${displayName(doc)}' (slug ${doc.slug})`),
    data: { ...doc, id: ctx.dry ? null : doc.id, public_url: publicUrl(ctx, kind, doc) }, changes: [{ field: kind, before: null, after: doc.slug }],
    writes: [{ col: KINDS[kind].col, id: doc.id, before: null, after: doc }], target: ctx.dry ? null : targetOf(kind, doc),
  };
}

cap({
  id: 'categories.list', category: 'categories', scopes: ['categories:read'], readOnly: true,
  description: 'Elenca le categorie con stato e numero di modelle pubblicate.',
  natural: ['quali categorie ci sono'],
  handler(ctx) {
    const counts = {};
    for (const m of R.liveModels().filter((x) => x.stato === 'pubblicata')) for (const c of arr(m.categorie)) counts[c] = (counts[c] || 0) + 1;
    const items = store.all('categories').sort((a, b) => (a.ordine || 0) - (b.ordine || 0))
      .map((c) => ({ id: c.id, nome: c.nome, slug: c.slug, stato: c.stato, ordine: c.ordine, indicizzabile: c.indicizzabile, modelle_pubblicate: counts[c.slug] || 0, public_url: publicUrl(ctx, 'category', c) }));
    return { summary: `${items.length} categorie`, data: { items, count: items.length } };
  },
});

cap({
  id: 'categories.create', category: 'categories', scopes: ['categories:write'],
  description: `Crea una categoria. Campi: ${CATEGORY_FIELDS.join(', ')}. Lo slug deve essere unico.`,
  params: { nome: { type: 'string', required: true, example: 'Rosse' }, fields: { type: 'object', description: 'altri campi (facoltativi)' } },
  natural: ['crea la categoria Rosse'],
  handler(ctx) {
    const fields = ctx.params.fields ?? {};
    onlyKeys(fields, CATEGORY_FIELDS, 'fields');
    assertNoLegacyHost(fields);
    return planDocCreate(ctx, 'category', R.buildCategoryCreate({ ...fields, nome: String(ctx.params.nome).trim() }), 'Categoria');
  },
});

cap({
  id: 'categories.update', category: 'categories', scopes: ['categories:write'], target: 'category',
  description: `Modifica una categoria (solo i campi indicati). Campi: ${CATEGORY_FIELDS.join(', ')}.`,
  params: { changes: { type: 'object', required: true, example: { descrizione: 'Le creator dai capelli rossi.' } } },
  natural: ['cambia la descrizione della categoria more'],
  handler(ctx) {
    onlyKeys(ctx.params.changes, CATEGORY_FIELDS, 'changes');
    assertNoLegacyHost(ctx.params.changes);
    const cat = ctx.target;
    const plan = planDocUpdate(ctx, 'category', cat, R.buildCategoryUpdate(cat, { ...cat, ...ctx.params.changes }));
    const after = plan.writes?.[0]?.after;
    if (after && after.slug !== cat.slug) {
      const used = R.liveModels().filter((m) => arr(m.categorie).includes(cat.slug)).length;
      plan.warnings = [`Lo slug cambia da ${cat.slug} a ${after.slug}: ${used} modelle usano ancora il vecchio slug (aggiornale con models.categories.set)`];
    }
    return plan;
  },
});

const articleBrief = ({ contenuto, ...a }) => ({ ...a, contenuto_caratteri: String(contenuto || '').length });

cap({
  id: 'articles.list', category: 'articles', scopes: ['content:read'], readOnly: true,
  description: 'Elenca gli articoli della rivista (senza il testo completo). Filtri opzionali: stato (bozza | pubblicato), q.',
  params: { stato: { type: 'string', enum: ['bozza', 'pubblicato'] }, q: { type: 'string' }, limit: { type: 'integer', default: 50 } },
  natural: ['quali articoli ci sono', 'articoli in bozza'],
  handler(ctx) {
    const p = ctx.params;
    let items = store.all('articles').sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
    if (p.stato) items = items.filter((a) => a.stato === p.stato);
    if (p.q) items = items.filter((a) => [a.titolo, a.slug, a.keyword_principale].some((v) => norm(v).includes(norm(p.q))));
    const total = items.length;
    items = items.slice(0, Math.max(1, Math.min(200, p.limit || 50)))
      .map((a) => ({ id: a.id, titolo: a.titolo, slug: a.slug, stato: a.stato, data_pubblicazione: a.data_pubblicazione, etag: etagOf(a), public_url: publicUrl(ctx, 'article', a) }));
    return { summary: `${total} articoli`, data: { items, total } };
  },
});

cap({
  id: 'articles.get', category: 'articles', scopes: ['content:read'], readOnly: true, target: 'article',
  description: 'Articolo completo (testo HTML, SEO, immagini, modelle correlate).',
  natural: ['mostrami l\'articolo sulla guida'],
  handler(ctx) {
    const a = ctx.target;
    return { summary: `Articolo '${a.titolo}' (${a.stato})`, data: { ...a, etag: etagOf(a), public_url: publicUrl(ctx, 'article', a) }, target: targetOf('article', a) };
  },
});

cap({
  id: 'articles.create', category: 'articles', scopes: ['content:write'],
  description: `Crea un articolo (in bozza se non indichi stato: pubblicato). L'HTML viene ripulito da script. Campi: ${ARTICLE_FIELDS.join(', ')}.`,
  params: { titolo: { type: 'string', required: true, example: 'Come funziona LATO SEGRETO' }, fields: { type: 'object', description: 'altri campi (facoltativi)' } },
  natural: ['scrivi un articolo su…'],
  handler(ctx) {
    const fields = ctx.params.fields ?? {};
    onlyKeys(fields, ARTICLE_FIELDS, 'fields');
    assertNoLegacyHost(fields);
    const plan = planDocCreate(ctx, 'article', R.buildArticleCreate({ ...fields, titolo: ctx.params.titolo }), 'Articolo');
    plan.data = articleBrief(plan.data);
    return plan;
  },
});

cap({
  id: 'articles.update', category: 'articles', scopes: ['content:write'], target: 'article',
  description: `Modifica un articolo (solo i campi indicati). stato: bozza | pubblicato. Campi: ${ARTICLE_FIELDS.join(', ')}.`,
  params: { changes: { type: 'object', required: true, example: { estratto: 'Nuovo estratto.' } } },
  natural: ['cambia il titolo dell\'articolo', 'pubblica l\'articolo'],
  handler(ctx) {
    onlyKeys(ctx.params.changes, ARTICLE_FIELDS, 'changes');
    assertNoLegacyHost(ctx.params.changes);
    const a = ctx.target;
    const merged = { ...a, ...ctx.params.changes };
    if (!String(merged.titolo || '').trim()) throw invalid('Il titolo non può essere vuoto');
    const plan = planDocUpdate(ctx, 'article', a, R.buildArticleUpdate(a, merged));
    plan.data = articleBrief(plan.data);
    return plan;
  },
});

// =====================================================================================================================
// SETTINGS + SITE CONFIG
// =====================================================================================================================
const publicSettings = (s) => Object.fromEntries([...R.SETTINGS_ALLOWED, 'updated_at'].filter((k) => s?.[k] != null).map((k) => [k, s[k]]));

cap({
  id: 'settings.get', category: 'settings', scopes: ['settings:read'], readOnly: true,
  description: `Impostazioni del sito: ${R.SETTINGS_ALLOWED.join(', ')}.`,
  natural: ['mostrami le impostazioni del sito'],
  handler: () => ({ summary: 'Impostazioni del sito', data: publicSettings(store.get('settings', 'global')) }),
});

cap({
  id: 'settings.update', category: 'settings', scopes: ['settings:update'],
  description: `Modifica le impostazioni del sito (solo i campi indicati): ${R.SETTINGS_ALLOWED.join(', ')}. home_pellicola viene unito campo per campo.`,
  params: { changes: { type: 'object', required: true, example: { footer_contatti: 'info@esempio.it' } } },
  natural: ['cambia i contatti nel footer'],
  handler(ctx) {
    const { changes } = ctx.params;
    if (isObj(changes) && Object.keys(changes).some((k) => k.startsWith('ai_'))) {
      throw new AiError(403, 'CRITICAL_ACTION_BLOCKED', 'Gli interruttori dell\'interfaccia AI si cambiano solo dal pannello admin');
    }
    onlyKeys(changes, R.SETTINGS_ALLOWED, 'changes');
    if (Object.values(changes).some((v) => v == null)) throw invalid('I valori null non sono consentiti');
    assertNoLegacyHost(changes);
    const cur = store.get('settings', 'global') || {};
    const input = isObj(changes.home_pellicola) ? { ...changes, home_pellicola: merge(obj(cur.home_pellicola), changes.home_pellicola) } : changes;
    const { doc } = R.buildSettings(input);
    const changed = diff(cur, doc);
    if (!changed.length) return { summary: 'Nessuna modifica: le impostazioni hanno già questi valori', data: { unchanged: true, ...publicSettings(cur) } };
    const fields = changed.map((c) => c.field).join(', ');
    return {
      summary: ctx.say(`Impostazioni aggiornate (${fields})`, `Cambierebbero ${changed.length} impostazioni (${fields})`), data: publicSettings(doc), changes: changed,
      writes: [{ col: 'settings', id: 'global', before: store.get('settings', 'global'), after: doc }],
    };
  },
});

const BASE_URL_AREAS = [
  'canonical di tutte le pagine', 'sitemap.xml e robots.txt', 'OpenGraph (og:url, og:image)', 'dati strutturati (JSON-LD)',
  'redirect 301 di tutti gli altri host verso questo dominio', 'URL pubblici nelle risposte di questa API e schema GPT (servers)',
];

cap({
  id: 'config.site.get', category: 'config', scopes: ['config:read'], readOnly: true,
  description: 'URL base pubblico del sito (site.base_url): valore attuale, origine (config | env | request), ultima modifica, aree che lo usano.',
  natural: ['qual è il dominio del sito', 'che URL base usa il sito'],
  handler(ctx) {
    const info = site.baseUrlInfo(ctx.req);
    return { summary: `URL base: ${info.value} (origine: ${info.source})`, data: { field: 'site.base_url', ...info, used_for: BASE_URL_AREAS } };
  },
});

// The new domain must already answer with THIS app, otherwise the host redirect would take the site offline.
function verifyHost(value) {
  const host = new URL(value).host;
  const fail = (why) => invalid(`Il dominio ${host} non risponde ancora da questa applicazione (${why}). Collega prima il dominio all'hosting (dominio personalizzato + DNS), poi riprova.`, { checked: `${value}/api/health` });
  return new Promise((resolve, reject) => {
    const req = https.get(`${value}/api/health`, { lookup: media.safeLookup, timeout: 6000, headers: { Accept: 'application/json' } }, (res) => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { if (text.length < 4096) text += c; });
      res.on('end', () => {
        if (res.statusCode !== 200) return reject(fail(`HTTP ${res.statusCode}`));
        let body;
        try { body = JSON.parse(text); } catch { return reject(fail('risposta non valida')); }
        if (body?.status !== 'ok') return reject(fail('risposta non valida'));
        if (body.instance !== site.INSTANCE_ID) return reject(fail('risponde un\'altra applicazione o un\'altra istanza'));
        return resolve();
      });
      res.on('error', () => reject(fail('connessione interrotta')));
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', (e) => reject(fail(e.message === 'timeout' ? 'nessuna risposta entro 6 secondi' : 'host non raggiungibile o certificato non valido')));
  });
}

cap({
  id: 'config.site.update', category: 'config', scopes: ['config:update'], risk: REVIEW,
  description: 'Cambia l\'URL base pubblico del sito (unico campo: site.base_url). Solo https://dominio, senza percorso. Richiede approvazione; '
    + 'in produzione viene eseguito solo se il nuovo dominio risponde già da questa applicazione.',
  params: { base_url: { type: 'string', required: true, example: 'https://www.esempio.it', description: 'nuovo valore di site.base_url' } },
  examples: [{ action: 'config.site.update', parameters: { base_url: 'https://www.esempio.it' } }],
  natural: ['imposta il dominio del sito', 'cambia l\'URL base in https://…'],
  async handler(ctx) {
    const extra = Object.keys(ctx.params).filter((k) => k !== 'base_url');
    if (extra.length) throw invalid(`config.site.update accetta solo 'base_url' (site.base_url). Non consentiti: ${extra.join(', ')}`, { unknown: extra });
    const v = site.validateBaseUrl(ctx.params.base_url);
    if (v.error) throw invalid(v.error, { field: 'site.base_url' });
    assertNoLegacyHost(v.value);
    const info = site.baseUrlInfo(ctx.req);
    if (info.source === 'config' && info.value === v.value) return { summary: `Nessuna modifica: l'URL base è già ${v.value}`, data: { unchanged: true, field: 'site.base_url', ...info } };
    const warnings = [];
    if (!ctx.dry && process.env.NODE_ENV === 'production') await verifyHost(v.value);
    else if (process.env.NODE_ENV === 'production') warnings.push(`Prima dell'esecuzione viene verificato che ${v.value}/api/health risponda da questa applicazione`);
    else warnings.push('Ambiente non di produzione: la verifica del dominio viene saltata');
    const before = site.siteConfig(); // read after the check, right before planning
    return {
      summary: ctx.say(`URL base impostato: ${v.value}`, `L'URL base passerebbe da ${info.value} a ${v.value}`),
      data: { field: 'site.base_url', value: ctx.dry ? info.value : v.value, current: info.value, current_source: info.source, proposed: v.value, affected: BASE_URL_AREAS },
      changes: [{ field: 'site.base_url', before: info.source === 'config' ? info.value : null, after: v.value }], warnings,
      writes: [{ col: 'config', id: 'site', before, after: { id: 'site', base_url: v.value, updated_at: store.nowIso() } }],
      next_steps: ['Dopo il cambio: reimporta lo schema nel GPT e invia la nuova sitemap a Google Search Console'],
    };
  },
});

// =====================================================================================================================
// SEO (read only)
// =====================================================================================================================
const hostOf = (url) => { try { return new URL(url).host.toLowerCase(); } catch { return null; } };
const isAbsolute = (v) => typeof v === 'string' && /^https?:\/\//i.test(v);

cap({
  id: 'seo.audit', category: 'seo', scopes: ['seo:audit'], readOnly: true, target: 'model', optionalTarget: true,
  description: 'Audit SEO in sola lettura (tutto il sito, o una modella se indichi il target): media/canonical con URL assoluti su un host diverso dall\'URL base, '
    + 'link al vecchio hosting, campi meta mancanti (title, meta_description, alt).',
  natural: ['fai un audit SEO', 'controlla la SEO di Francesca'],
  handler(ctx) {
    const baseHost = hostOf(ctx.base);
    const issues = [];
    const add = (entity, doc, type, field, value) => issues.push({ entity, id: doc.id, slug: doc.slug, type, field, ...(value ? { value: String(value).slice(0, 200) } : {}) });
    // stored absolute URL of an own resource (media, canonical) that points to another host
    const foreign = (entity, doc, field, value) => {
      if (isAbsolute(value) && hostOf(value) !== baseHost) add(entity, doc, legacyUrls(value).length ? 'legacy_host_url' : 'foreign_host_url', field, value);
    };
    const missing = (entity, doc, field, value) => { if (!String(value ?? '').trim()) add(entity, doc, 'missing_meta', field); };

    const models = ctx.target ? [ctx.target] : R.liveModels();
    for (const m of models) {
      for (const it of mediaOf(m)) { foreign('model', m, it.field, it.url); foreign('model', m, `${it.field}.poster`, it.poster); }
      foreign('model', m, 'seo.canonical', obj(m.seo).canonical);
      for (const f of ['title', 'meta_description', 'alt_default']) missing('model', m, `seo.${f}`, obj(m.seo)[f]);
    }
    let articles = [];
    let categories = [];
    if (!ctx.target) {
      articles = store.all('articles');
      for (const a of articles) {
        for (const f of ['immagine_principale', 'og_image', 'canonical']) foreign('article', a, f, a[f]);
        arr(a.immagini_interne).forEach((x, i) => foreign('article', a, `immagini_interne[${i}]`, isObj(x) ? x.url : x));
        for (const u of new Set(legacyUrls(a.contenuto))) add('article', a, 'legacy_host_url', 'contenuto', u);
        for (const f of ['seo_title', 'meta_description']) missing('article', a, f, a[f]);
      }
      categories = store.all('categories');
      for (const c of categories) {
        foreign('category', c, 'immagine', c.immagine);
        for (const u of new Set(legacyUrls(c.testo_seo))) add('category', c, 'legacy_host_url', 'testo_seo', u);
        for (const f of ['seo_title', 'meta_description']) missing('category', c, f, c[f]);
      }
    }
    const byType = {};
    for (const i of issues) byType[i.type] = (byType[i.type] || 0) + 1;
    return {
      summary: issues.length ? `Audit SEO: ${issues.length} segnalazioni (${Object.entries(byType).map(([k, v]) => `${v} ${k}`).join(', ')})` : 'Audit SEO: nessuna segnalazione',
      data: {
        base_url: ctx.base, checked: { models: models.length, articles: articles.length, categories: categories.length }, by_type: byType,
        issues: issues.slice(0, 300), truncated: issues.length > 300,
        legend: { foreign_host_url: 'URL assoluto salvato su un host diverso dall\'URL base', legacy_host_url: 'URL del vecchio hosting', missing_meta: 'campo meta vuoto' },
      },
      target: ctx.target ? targetOf('model', ctx.target) : null,
      next_steps: issues.length ? ['Campi meta: models.set_seo / articles.update / categories.update', 'Media su altri host: media.upload_url + media.assign'] : [],
    };
  },
});

cap({
  id: 'seo.sitemap_status', category: 'seo', scopes: ['seo:read'], readOnly: true,
  description: 'Stato della sitemap: URL di sitemap.xml e robots.txt, numero di pagine per tipo, pagine pubblicate escluse perché non indicizzabili.',
  natural: ['com\'è la sitemap', 'quante pagine sono in sitemap'],
  handler(ctx) {
    const urls = seo.sitemapUrls(ctx.base);
    const count = (prefix) => urls.filter((u) => u.loc.startsWith(`${ctx.base}/${prefix}/`)).length;
    const excluded = R.liveModels().filter((m) => m.stato === 'pubblicata' && obj(m.seo).indexable === false).map((m) => m.slug);
    return {
      summary: `Sitemap: ${urls.length} URL (${count('modelle')} modelle, ${count('categorie')} categorie, ${count('articoli')} articoli)`,
      data: {
        sitemap_url: `${ctx.base}/sitemap.xml`, robots_url: `${ctx.base}/robots.txt`, base_url: ctx.base, total_urls: urls.length,
        models: count('modelle'), categories: count('categorie'), articles: count('articoli'), models_excluded_noindex: excluded,
      },
    };
  },
});

// =====================================================================================================================
// SYSTEM
// =====================================================================================================================
function systemStatus(ctx) {
  const f = aiStore.flags();
  const models = store.all('models');
  const live = models.filter((m) => !m.is_deleted);
  const drafts = live.filter((m) => m.stato !== 'pubblicata');
  const articles = store.all('articles');
  const caps = [...REGISTRY.values()];
  const info = site.baseUrlInfo(ctx.req);
  return {
    mode: f.mode,
    ai: { enabled: f.ai_api_enabled, mode: f.mode, write_enabled: f.ai_write_enabled, rate_limit_per_min: f.ai_rate_limit_per_min },
    health: { status: 'ok', database: 'ok' },
    site: { base_url: info.value, base_url_source: info.source },
    content: {
      models: {
        total: live.length, published: live.length - drafts.length, drafts: drafts.length,
        ready_to_publish: drafts.filter((m) => C.readiness(m).is_ready).length, deleted: models.length - live.length,
      },
      categories: store.all('categories').length,
      articles: { total: articles.length, published: articles.filter((a) => a.stato === 'pubblicato').length },
    },
    capabilities_registry: { total: caps.length, safe: caps.filter((c) => c.risk === SAFE).length, review: caps.filter((c) => c.risk === REVIEW).length, read_only: caps.filter((c) => c.readOnly).length },
    permissions: { key: ctx.principal.name, scopes: ctx.principal.scopes },
    pending_approvals: aiStore.pendingApprovals(ctx.principal.type === 'key' ? ctx.principal.id : null).length,
  };
}
const statusSummary = (s) => `Sito attivo. Modalità ${s.mode}. ${s.content.models.published} modelle pubblicate, ${s.content.models.drafts} non pubblicate, ${s.content.articles.published} articoli pubblicati.`;

cap({
  id: 'system.status', category: 'system', scopes: ['system:status'], readOnly: true,
  description: 'Stato del sistema: modalità (READ_ONLY/FULL), URL base, numeri dei contenuti, capability disponibili, permessi della chiave.',
  natural: ['come sta il sito', 'stato generale'],
  handler(ctx) {
    const s = systemStatus(ctx);
    return { summary: statusSummary(s), data: s };
  },
});

// =====================================================================================================================
// ROLLBACK
// =====================================================================================================================
const readDoc = (col, id) => (col === 'config' && id === 'site' ? site.siteConfig() : store.get(col, id));

// Undo plan for versions given newest first. A version is only undone while the stored state is still exactly what that
// change left behind; anything edited afterwards is skipped and reported, never overwritten.
function planRollback(ctx, versions) {
  const writes = [];
  const restored = [];
  const skipped = [];
  const planned = new Map(); // state after the writes planned so far (several versions of one entity in a session)
  for (const v of versions) {
    const key = `${v.entity_col}/${v.entity_id}`;
    const ref = { version_id: v.id, action: v.action, entity: v.entity_col, entity_id: v.entity_id };
    if (v.rolled_back) { skipped.push({ ...ref, why: 'già annullata' }); continue; }
    const current = planned.has(key) ? planned.get(key) : readDoc(v.entity_col, v.entity_id);
    if (!same(current, v.after)) { skipped.push({ ...ref, why: 'modificato dopo questa modifica: non ripristinato' }); continue; }
    let after = v.before;
    if (after === null && v.entity_col === 'models') after = R.buildModelDelete(current).doc; // undo of a creation: soft delete, like the admin
    if (after && after.slug && KINDS_BY_COL[v.entity_col] && store.find(v.entity_col, (d) => d.slug === after.slug && d.id !== after.id && !d.is_deleted)) {
      after = { ...after, slug: `${after.slug}-r${v.id.slice(0, 4)}` }; // the old slug was taken in the meantime
    }
    writes.push({ col: v.entity_col, id: v.entity_id, before: current, after, rollbackOf: v.id });
    planned.set(key, after);
    restored.push({ ...ref, slug: (v.after || v.before)?.slug || null, operation: v.before === null ? 'annulla creazione' : 'ripristina stato precedente' });
  }
  return {
    summary: writes.length
      ? ctx.say(`Annullate ${writes.length} modifiche${skipped.length ? `, ${skipped.length} saltate` : ''}`, `Verrebbero annullate ${writes.length} modifiche${skipped.length ? `, ${skipped.length} saltate` : ''}`)
      : `Niente da annullare${skipped.length ? ` (${skipped.length} saltate)` : ''}`,
    data: { restored, skipped, restored_count: restored.length, skipped_count: skipped.length },
    changes: restored.map((r) => ({ field: `${r.entity}:${r.slug || r.entity_id}`, before: 'stato attuale', after: r.operation })),
    warnings: skipped.filter((s) => s.why !== 'già annullata').map((s) => `Non annullata (${s.action} su ${s.entity}): ${s.why}`), writes,
  };
}
const KINDS_BY_COL = { models: true, categories: true, articles: true };

cap({
  id: 'rollback.session', category: 'rollback', scopes: ['rollback:execute'],
  description: 'Annulla tutte le modifiche fatte in una sessione (session_id), dalla più recente alla più vecchia. La cronologia resta. I file caricati non vengono cancellati.',
  params: { session_id: { type: 'string', required: true, example: 'ses_1a2b3c4d5e6f' } },
  natural: ['annulla tutto quello che hai fatto', 'torna indietro'],
  handler(ctx) {
    const versions = aiStore.sessionVersions(ctx.params.session_id);
    if (!versions.length) throw new AiError(404, 'NOT_FOUND', `Nessuna modifica registrata per la sessione '${ctx.params.session_id}'`);
    return planRollback(ctx, versions);
  },
});

cap({
  id: 'rollback.version', category: 'rollback', scopes: ['rollback:execute'],
  description: 'Annulla una singola modifica (version_id restituito in rollback.version_ids).',
  params: { version_id: { type: 'string', required: true } },
  natural: ['annulla l\'ultima modifica'],
  handler(ctx) {
    const v = aiStore.getVersion(ctx.params.version_id);
    if (!v) throw new AiError(404, 'NOT_FOUND', 'Versione non trovata');
    if (v.rolled_back) throw new AiError(409, 'CONFLICT', 'Questa modifica è già stata annullata');
    const plan = planRollback(ctx, [v]);
    if (!plan.writes.length) throw new AiError(409, 'CONFLICT', 'Il contenuto è stato modificato dopo questa versione: non può essere annullata da sola', plan.data);
    return plan;
  },
});

// =====================================================================================================================
// ANALYTICS (events table, same source as the admin dashboard)
// =====================================================================================================================
const MIN_SAMPLE = 30; // below this a ranking is reported, but never called reliable
const EVENT = { visite: 'page_view', attivazioni: 'secret_activate', interazioni: 'interazione', messaggi: 'message_open', click_of: 'of_click' };
const METRICS = {
  visits: { num: EVENT.visite, def: 'numero di eventi page_view' }, model_views: { num: EVENT.visite, def: 'numero di eventi page_view' },
  secret_opens: { num: EVENT.attivazioni, def: 'numero di attivazioni del Lato Segreto (secret_activate)' },
  interactions: { num: EVENT.interazioni, def: 'numero di eventi interazione' }, message_opens: { num: EVENT.messaggi, def: 'numero di messaggi aperti (message_open)' },
  onlyfans_clicks: { num: EVENT.click_of, def: 'numero di click verso OnlyFans (of_click)' }, cta_clicks: { num: EVENT.click_of, def: 'numero di click verso OnlyFans (of_click)' },
  onlyfans_ctr: { num: EVENT.click_of, den: EVENT.visite, def: 'of_click / page_view × 100' }, conversion_rate: { num: EVENT.click_of, den: EVENT.visite, def: 'of_click / page_view × 100' },
  activation_rate: { num: EVENT.attivazioni, den: EVENT.visite, def: 'secret_activate / page_view × 100' },
};
const RANGES = { oggi: 'oggi', today: 'oggi', '7g': '7g', '7d': '7g', '30g': '30g', '30d': '30g', '90g': '90g', '90d': '90g', tutto: 'tutto', all: 'tutto' };

function queryAnalytics(ctx, body) {
  const q = obj(body);
  const range = RANGES[String(q.period || q.range || '30g').toLowerCase()];
  if (!range) throw invalid("Periodo non valido: usa oggi, 7g, 30g, 90g o tutto (anche 7d/30d/90d)", { allowed: Object.keys(RANGES) });
  const since = R.cutoff(range);
  const limitations = [];
  const model = q.model ? resolveRef('model', q.model, { includeDeleted: true }) : null;
  let metric = q.metric ? String(q.metric).toLowerCase() : null;
  let groupBy = String(q.group_by || 'none').toLowerCase();
  if (!metric && q.question) {
    const text = norm(q.question);
    if (/convert|ctr|onlyfans/.test(text)) { metric = 'onlyfans_ctr'; groupBy = 'model'; }
    else if (/visit|vist/.test(text)) { metric = 'visits'; groupBy = 'model'; }
    if (metric) limitations.push(`Domanda libera interpretata come metric=${metric}, group_by=${groupBy}: per risultati precisi usa i parametri strutturati`);
  }
  const base = { period: range, filters: model ? { model: model.slug } : {} };
  // dimensions this system does not collect: say so instead of answering with unfiltered numbers
  const unsupported = ['country', 'region', 'city', 'device', 'source'].filter((k) => q[k]);
  if (['country', 'region', 'city', 'device', 'source'].includes(groupBy)) unsupported.push(`group_by=${groupBy}`);
  if (unsupported.length) {
    return {
      summary: `Dato non disponibile: questo sistema non raccoglie ${unsupported.join(', ')}`,
      data: { ...base, metric, group_by: groupBy, items: [], sample_size: 0, data_available: false, limitations: [`Dimensioni non raccolte: ${unsupported.join(', ')}. Sono disponibili solo totali, per modella e per giorno.`] },
    };
  }

  if (!metric) {
    const c = R.countsByType(since, model?.id);
    const funnel = Object.fromEntries(Object.entries(EVENT).map(([k, tipo]) => [k, c[tipo] || 0]));
    const sample = funnel.visite;
    if (sample < MIN_SAMPLE) limitations.push(`Campione ridotto (${sample} visite)`);
    return {
      summary: sample || Object.values(funnel).some(Boolean)
        ? `Panoramica ${range}${model ? ` di ${displayName(model)}` : ''}: ${funnel.visite} visite, ${funnel.attivazioni} attivazioni Lato Segreto, ${funnel.click_of} click OnlyFans`
        : `Nessun dato nel periodo ${range}`,
      data: { ...base, funnel, sample_size: sample, data_available: Object.values(funnel).some(Boolean), limitations },
    };
  }

  const m = METRICS[metric];
  if (!m) throw invalid(`Metrica '${metric}' non disponibile`, { available: Object.keys(METRICS) });
  if (!['none', 'model', 'day'].includes(groupBy)) throw invalid(`group_by '${groupBy}' non disponibile`, { available: ['none', 'model', 'day'] });
  const groupSql = { none: "'totale'", model: 'model_id', day: 'substr(ts, 1, 10)' }[groupBy];
  const where = ['ts >= ?', ...(model ? ['model_id = ?'] : []), ...(groupBy === 'model' ? ['model_id IS NOT NULL'] : [])].join(' AND ');
  const rows = store.db.prepare(`SELECT ${groupSql} AS g, SUM(tipo = ?) AS num, SUM(tipo = ?) AS den FROM events WHERE ${where} GROUP BY g`)
    .all(m.num, m.den || m.num, since, ...(model ? [model.id] : []));
  const names = groupBy === 'model' ? Object.fromEntries(store.all('models').map((d) => [d.id, d])) : {};
  let items = rows.filter((r) => groupBy !== 'model' || names[r.g]).map((r) => {
    const sample = m.den ? r.den : r.num;
    const value = m.den ? (r.den ? Math.round((r.num / r.den) * 1000) / 10 : null) : r.num;
    const doc = names[r.g];
    return {
      label: doc ? displayName(doc) : r.g, ...(doc ? { id: doc.id, slug: doc.slug } : {}),
      value, numerator: r.num, denominator: m.den ? r.den : null, sample_size: sample, reliable: sample >= MIN_SAMPLE,
    };
  }).filter((it) => it.sample_size > 0 || it.numerator > 0);
  const dir = String(q.sort || 'desc').toLowerCase() === 'asc' ? 1 : -1;
  if (groupBy === 'day') items.sort((a, b) => a.label.localeCompare(b.label));
  else items.sort((a, b) => (a.value === null) - (b.value === null) || dir * ((a.value ?? 0) - (b.value ?? 0)));
  items = items.slice(0, Math.max(1, Math.min(100, parseInt(q.limit, 10) || 10)));
  const sample = items.reduce((n, it) => n + it.sample_size, 0);
  if (!items.length) limitations.push('Nessun evento registrato nel periodo');
  else if (items.some((it) => !it.reliable)) limitations.push(`Campione ridotto per alcune voci (meno di ${MIN_SAMPLE}): non indicare un vincitore certo`);
  const top = groupBy !== 'day' ? items.find((it) => it.value !== null) : null;
  return {
    summary: !items.length ? `Nessun dato per ${metric} nel periodo ${range}`
      : top ? `${metric} (${range}): ${groupBy === 'model' ? `in testa ${top.label} con ` : ''}${top.value}${m.den ? '%' : ''} (campione ${top.sample_size})`
        : `${metric} per giorno (${range}): ${items.length} giorni con dati`,
    data: { ...base, metric, group_by: groupBy, definition: m.def, unit: m.den ? 'percent' : 'count', items, sample_size: sample, data_available: items.length > 0, limitations },
  };
}

module.exports = {
  AiError, SAFE, REVIEW, REGISTRY, describe, accessFor, requestExample, resolveRef, targetOf, etagOf, modelSummary,
  systemStatus, statusSummary, queryAnalytics, same,
};
