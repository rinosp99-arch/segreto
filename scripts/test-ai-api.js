// End-to-end check of the AI interface (/api/v2/ai) against a running LOCAL server.
//   BASE=http://localhost:8001 ADMIN_EMAIL=... ADMIN_PASSWORD=... node scripts/test-ai-api.js
//   optional: TEST_MEDIA_URL=https://.../bild.png also tests a real download (needs internet)
// Starts nothing itself. Use a server with a throw-away DATA_DIR: the test creates keys (deleted at the end), switches the
// AI mode (restored at the end) and leaves behind soft-deleted test creators, one small test image and log entries.
const assert = require('assert');
const crypto = require('crypto');

const B = (process.env.BASE || 'http://localhost:8001').replace(/\/+$/, '');
const email = process.env.ADMIN_EMAIL;
const password = process.env.ADMIN_PASSWORD;
if (!/^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(B)) { console.error('Nur gegen einen lokalen Server erlaubt (BASE=http://localhost:PORT).'); process.exit(1); }
if (!email || !password) { console.error('ADMIN_EMAIL und ADMIN_PASSWORD müssen gesetzt sein.'); process.exit(1); }

const AI = '/api/v2/ai';
const ENVELOPE = ['ok', 'action', 'summary', 'data', 'changes', 'warnings', 'next_steps', 'approval_required', 'rollback', 'request_id'];
const sha256 = (s) => crypto.createHash('sha256').update(s).digest('hex');
const forbidden = []; // key hashes that must never show up in any response
let count = 0;
const ok = (label) => { count += 1; console.log(`  ok  ${label}`); };

async function call(token, method, p, body, headers = {}) {
  const h = { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers };
  if (body !== undefined) h['Content-Type'] = 'application/json';
  const r = await fetch(B + p, { method, headers: h, body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body), redirect: 'manual' });
  const text = await r.text();
  let json; try { json = JSON.parse(text); } catch { json = null; }
  for (const bad of forbidden) assert.ok(!text.includes(bad), `Antwort von ${p} enthält einen Schlüssel-Hash`);
  assert.ok(!/key_hash|token_hash/.test(text), `Antwort von ${p} enthält ein Hash-Feld`);
  return { status: r.status, json, text, headers: r.headers };
}

// AI call: every answer must be the standard envelope
async function ai(key, method, p, body, headers) {
  const r = await call(key, method, AI + p, body, headers);
  assert.ok(r.json, `${p}: kein JSON (${r.status})`);
  for (const k of ENVELOPE) assert.ok(k in r.json, `${p}: Feld '${k}' fehlt in der Antwort`);
  if (!r.json.ok) assert.ok(r.json.code, `${p}: Fehler ohne code`);
  return r;
}
const exec = (key, action, target, parameters = {}, extra = {}, headers) => ai(key, 'POST', '/execute', { action, target, parameters, ...extra }, headers);
const preview = (key, action, target, parameters = {}, extra = {}) => ai(key, 'POST', '/preview', { action, target, parameters, ...extra });
const expectErr = (r, status, code, label) => { assert.equal(r.status, status, `${label}: Status ${r.status} ${r.text.slice(0, 300)}`); assert.equal(r.json.code, code, label); ok(label); };

(async () => {
  // ---------- setup ----------
  const login = await call(null, 'POST', '/api/admin/login', { email, password });
  assert.equal(login.status, 200, 'Admin-Login fehlgeschlagen');
  const jwt = login.json.token;
  const admin = (method, p, body) => call(jwt, method, `/api/admin${p}`, body);
  const control0 = (await admin('GET', '/ai/control')).json;
  const setControl = async (patch) => assert.equal((await admin('PATCH', '/ai/control', patch)).status, 200);
  const keys = [];
  const newKey = async (name, preset) => {
    const r = await admin('POST', '/ai/keys', { name, preset });
    assert.equal(r.status, 200); assert.match(r.json.key, /^ls_[A-Za-z0-9_-]{40,}$/);
    keys.push(r.json.id); forbidden.push(sha256(r.json.key));
    return r.json;
  };

  try {
    await setControl({ ai_api_enabled: true, ai_write_enabled: false, ai_rate_limit_per_min: 600 });
    const ro = await newKey('Test READ_ONLY', 'read_only');
    const full = await newKey('Test FULL', 'full');
    const RO = ro.key; const FULL = full.key;
    ok('Schlüssel über den Admin angelegt (Klartext nur in der Antwort der Erstellung)');
    const listed = await admin('GET', '/ai/keys');
    assert.ok(listed.json.items.some((k) => k.id === ro.id && k.prefix === RO.slice(0, 9)));
    assert.ok(!listed.text.includes(RO) && !listed.text.includes(FULL)); ok('Schlüsselliste zeigt nur Präfix, nie den Schlüssel');
    assert.equal((await call(null, 'GET', '/api/admin/ai/keys')).status, 401);
    assert.equal((await call(FULL, 'GET', '/api/admin/ai/keys')).status, 401); ok('Admin-Endpunkte: ohne Login und mit API-Schlüssel gesperrt');
    assert.equal((await admin('POST', '/ai/keys', { name: 'x', preset: 'root' })).status, 422); ok('unbekanntes Preset abgelehnt');

    // ---------- OpenAPI ----------
    const spec = await call(null, 'GET', `${AI}/openapi-chatgpt.json`);
    assert.equal(spec.status, 200); assert.ok(spec.json); assert.equal(spec.json.openapi, '3.1.0');
    const ops = Object.values(spec.json.paths).flatMap((p) => Object.values(p));
    assert.deepEqual(ops.map((o) => o.operationId).sort(), ['approveApproval', 'executeCapability', 'findModel', 'getCapabilities', 'getCapability', 'getJob', 'getSystemStatus',
      'listApprovals', 'previewCapability', 'queryAnalytics', 'rejectApproval', 'rollback'].sort());
    assert.ok(ops.length <= 30);
    const longTexts = [];
    (function walk(v, where) {
      if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) { if ((k === 'description' || k === 'summary') && typeof x === 'string' && x.length > 300) longTexts.push(x); walk(x, k); }
    }(spec.json, ''));
    assert.equal(longTexts.length, 0, 'Beschreibung über 300 Zeichen');
    assert.deepEqual(Object.keys(spec.json.components.securitySchemes), ['ApiKeyBearer']); assert.equal(spec.json.components.securitySchemes.ApiKeyBearer.scheme, 'bearer');
    assert.equal(spec.json.servers[0].url, control0.base_url);
    const eb = spec.json.paths[`${AI}/execute`].post.requestBody.content['application/json'].schema;
    assert.deepEqual(eb.required, ['action', 'parameters']); assert.equal(eb.properties.parameters.type, 'object'); assert.equal(eb.properties.parameters_json.type, 'string');
    ok('openapi-chatgpt.json: gültiges JSON, 3.1.0, genau die 12 operationIds, Bearer, servers, parameters + parameters_json');

    // ---------- authentication ----------
    expectErr(await ai(null, 'GET', '/status'), 401, 'AUTH_REQUIRED', 'ohne Schlüssel -> 401');
    expectErr(await ai('ls_nichtvorhanden0000000000000000000000000000', 'GET', '/status'), 401, 'INVALID_API_KEY', 'ungültiger Schlüssel -> 401');
    expectErr(await ai('abc.def.ghi', 'GET', '/status'), 401, 'INVALID_API_KEY', 'gefälschter Login-Token -> 401');
    const tmp = await newKey('Test deaktiviert', 'read_only');
    assert.equal((await ai(tmp.key, 'GET', '/status')).status, 200);
    assert.equal((await admin('POST', `/ai/keys/${tmp.id}/disable`)).json.disabled, true);
    expectErr(await ai(tmp.key, 'GET', '/status'), 401, 'API_KEY_DISABLED', 'deaktivierter Schlüssel -> 401');
    assert.equal((await admin('POST', `/ai/keys/${tmp.id}/enable`)).json.disabled, false);
    assert.equal((await ai(tmp.key, 'GET', '/status')).status, 200); ok('wieder aktivierter Schlüssel funktioniert');
    assert.equal((await admin('DELETE', `/ai/keys/${tmp.id}`)).status, 200);
    expectErr(await ai(tmp.key, 'GET', '/status'), 401, 'INVALID_API_KEY', 'gelöschter Schlüssel -> 401');
    const st = await ai(jwt, 'GET', '/status');
    assert.equal(st.status, 200); assert.equal(st.json.data.mode, 'READ_ONLY'); ok('Admin-Login darf den Status lesen');

    // ---------- catalogue ----------
    const cat = await ai(RO, 'GET', '/capabilities');
    assert.equal(cat.status, 200); assert.equal(cat.json.data.mode, 'READ_ONLY');
    const ids = cat.json.data.capabilities.map((c) => c.id);
    for (const id of ['models.list', 'models.get', 'models.create', 'models.update', 'models.validate', 'models.publish', 'models.unpublish', 'models.soft_delete', 'models.undelete',
      'models.categories.set', 'models.set_seo', 'media.upload_url', 'media.assign', 'media.list', 'categories.list', 'categories.create', 'categories.update',
      'articles.list', 'articles.get', 'articles.create', 'articles.update', 'settings.get', 'settings.update', 'config.site.get', 'config.site.update',
      'seo.audit', 'seo.sitemap_status', 'system.status', 'rollback.session', 'rollback.version']) assert.ok(ids.includes(id), `Capability ${id} fehlt im Katalog`);
    assert.equal(cat.json.data.capabilities.find((c) => c.id === 'models.update').access, 'preview_only');
    assert.equal(cat.json.data.capabilities.find((c) => c.id === 'models.list').access, 'full');
    ok(`Katalog listet ${ids.length} Capabilities (READ_ONLY-Schlüssel: Schreiben nur als Vorschau)`);
    const one = await ai(RO, 'GET', '/capabilities/models.update');
    assert.deepEqual(one.json.data.required_parameters, ['changes']); assert.equal(one.json.data.request_example.action, 'models.update');
    assert.ok(one.json.data.parameters_schema.properties.changes && one.json.data.how_to_call && one.json.data.risk === 'SAFE'); ok('getCapability: Schema, Pflichtparameter, request_example');
    assert.equal((await ai(RO, 'GET', '/capabilities/config.site.update')).json.data.risk, 'REVIEW_REQUIRED');
    expectErr(await ai(RO, 'GET', '/capabilities/gibt.es.nicht'), 404, 'UNKNOWN_CAPABILITY', 'getCapability unbekannt -> 404');

    // ---------- READ_ONLY: read + preview yes, write no ----------
    const list = await exec(RO, 'models.list');
    assert.equal(list.status, 200); assert.ok(list.json.data.items.length > 0, 'Der Testserver braucht importierte Inhalte (scripts/import.js --ja --nur-db)');
    const sample = list.json.data.items[0];
    assert.ok(sample.public_url.startsWith(`${control0.base_url}/modelle/`)); ok(`READ_ONLY-Schlüssel liest (${list.json.data.total} Modelle, public_url aus der Basis-URL)`);
    const before = (await admin('GET', `/models/${sample.id}`)).text;
    const pv = await preview(RO, 'models.update', sample.slug, { changes: { frase: 'Vorschau schreibt nichts' } });
    assert.equal(pv.status, 200); assert.equal(pv.json.data.dry_run, true); assert.ok(pv.json.changes.some((c) => c.field === 'frase'));
    assert.deepEqual(pv.json.rollback.version_ids, []);
    const pv2 = await exec(RO, 'models.update', sample.slug, { changes: { frase: 'auch nicht' } }, { dry_run: true });
    assert.equal(pv2.status, 200);
    assert.equal((await admin('GET', `/models/${sample.id}`)).text, before); ok('Vorschau (preview und dry_run) schreibt nichts: Modell vorher = nachher');
    expectErr(await exec(RO, 'models.update', sample.slug, { changes: { frase: 'x' } }), 403, 'INSUFFICIENT_SCOPE', 'READ_ONLY-Schlüssel: Ausführen -> INSUFFICIENT_SCOPE');
    expectErr(await exec(FULL, 'models.update', sample.slug, { changes: { frase: 'x' } }), 403, 'READ_ONLY_MODE', 'Modus READ_ONLY: auch der volle Schlüssel schreibt nicht');
    expectErr(await exec(FULL, 'media.upload_url', null, { url: 'https://example.com/a.jpg' }), 403, 'READ_ONLY_MODE', 'Modus READ_ONLY: kein Upload');
    assert.equal((await admin('GET', `/models/${sample.id}`)).text, before); ok('nach den abgelehnten Schreibversuchen unverändert');

    // ---------- findModel ----------
    const found = await ai(RO, 'POST', '/models/find', { reference: sample.slug.toUpperCase() });
    assert.equal(found.status, 200); assert.equal(found.json.data.id, sample.id); ok('findModel: Slug ohne Rücksicht auf Groß/Klein');
    assert.equal((await ai(RO, 'POST', '/models/find', { reference: sample.id })).json.data.slug, sample.slug); ok('findModel: id');
    expectErr(await ai(RO, 'POST', '/models/find', { reference: 'Zzyzx Niemand Qwertz' }), 404, 'NOT_FOUND', 'findModel: unbekannt -> 404');

    // ---------- FULL: create -> update -> validate -> publish blocked ----------
    await setControl({ ai_write_enabled: true });
    assert.equal((await ai(FULL, 'GET', '/status')).json.data.mode, 'FULL');
    const tag = crypto.randomBytes(3).toString('hex');
    const S = `ses_test_${tag}`;
    const pvCreate = await preview(FULL, 'models.create', null, { nome: `Zù Prova ${tag} Uno` });
    assert.equal(pvCreate.json.data.id, null);
    const created = await exec(FULL, 'models.create', null, { nome: `Zù Prova ${tag} Uno`, fields: { frase: 'Claim di prova', tag: ['prova'] } }, { session_id: S, reason: 'test' });
    assert.equal(created.status, 200, created.text); assert.equal(created.json.data.stato, 'bozza'); assert.equal(created.json.rollback.version_ids.length, 1);
    assert.equal(created.json.data.session_id, S);
    const id = created.json.data.id; const slug = created.json.data.slug;
    assert.equal((await admin('GET', '/models')).json.items.filter((m) => m.nome === `Zù Prova ${tag} Uno`).length, 1); ok(`models.create legt genau einen Entwurf an (${slug}), Vorschau davor keinen`);
    assert.equal((await call(null, 'GET', `/api/models/${slug}`)).status, 404); ok('Entwurf öffentlich unsichtbar');
    const second = await exec(FULL, 'models.create', null, { nome: `Zù Prova ${tag} Due` }, { session_id: S });
    assert.equal(second.status, 200);
    const amb = await ai(FULL, 'POST', '/models/find', { reference: `zu prova ${tag}` });
    expectErr(amb, 409, 'AMBIGUOUS_REFERENCE', 'findModel: mehrdeutig -> 409');
    assert.equal(amb.json.data.matches.length, 2); assert.ok(amb.json.data.matches.every((m) => m.id && m.slug && m.nome)); ok('AMBIGUOUS_REFERENCE liefert data.matches');
    assert.equal((await ai(FULL, 'POST', '/models/find', { reference: `ZU PROVA ${tag} uno` })).json.data.id, id); ok('findModel: Name ohne Akzente und Groß/Klein');

    const upd = await exec(FULL, 'models.update', slug, { changes: { bio: 'Bio di prova', seo: { title: 'Titolo di prova' }, tema: { preset: 'bordeaux' } } }, { session_id: S });
    assert.equal(upd.status, 200, upd.text); assert.ok(upd.json.changes.some((c) => c.field === 'bio') && upd.json.changes.some((c) => c.field === 'seo.title'));
    let doc = (await admin('GET', `/models/${id}`)).json;
    assert.equal(doc.bio, 'Bio di prova'); assert.equal(doc.seo.title, 'Titolo di prova'); assert.equal(doc.seo.robots, 'index,follow'); assert.equal(doc.frase, 'Claim di prova');
    ok('models.update: Teiländerung, verschachtelte Felder werden zusammengeführt, Rest bleibt');
    expectErr(await exec(FULL, 'models.update', slug, { changes: { conferma_maggiorenne: true } }), 422, 'VALIDATION_FAILED', 'Volljährigkeits-Bestätigung nicht über die API setzbar');
    expectErr(await exec(FULL, 'models.update', slug, { changes: { stato: 'pubblicata' } }), 422, 'VALIDATION_FAILED', 'Status nicht über models.update (kein Umgehen der Prüfung)');
    expectErr(await exec(FULL, 'models.update', slug, { changes: { gibt_es_nicht: 1 } }), 422, 'VALIDATION_FAILED', 'unbekanntes Feld abgelehnt');
    expectErr(await exec(FULL, 'models.update', slug, { changes: { foto_card: 'https://secret-side.emergent.host/api/uploads/x.jpg' } }), 422, 'VALIDATION_FAILED', 'URL des alten Hostings abgelehnt');
    const val = await exec(FULL, 'models.validate', slug);
    assert.equal(val.json.data.ready, false); assert.ok(val.json.data.missing.length > 0); ok(`models.validate: nicht bereit (${val.json.data.missing.length} Punkte fehlen)`);
    const pubPv = await preview(FULL, 'models.publish', slug);
    assert.equal(pubPv.status, 200); assert.equal(pubPv.json.data.blocked, true); ok('models.publish Vorschau meldet die Sperre');
    const pub = await exec(FULL, 'models.publish', slug, { force: true });
    expectErr(pub, 400, 'PUBLICATION_BLOCKED', 'models.publish unvollständig -> gesperrt (force wirkungslos)');
    assert.ok(pub.json.data.missing.length > 0); assert.equal((await admin('GET', `/models/${id}`)).json.stato, 'bozza');

    // ---------- request contract: parameters_json, leaked keys, validation errors ----------
    const pj = await exec(FULL, 'models.update', slug, undefined, { parameters_json: JSON.stringify({ changes: { teaser_copy: 'Via parameters_json' } }), session_id: S });
    assert.equal(pj.status, 200, pj.text); assert.equal((await admin('GET', `/models/${id}`)).json.teaser_copy, 'Via parameters_json'); ok('parameters_json als Ersatz für parameters');
    const leaked = await ai(FULL, 'POST', '/preview', { action: 'models.update', target: slug, changes: { cta_testo: 'ENTRA' } });
    assert.equal(leaked.status, 200); assert.ok(leaked.json.warnings.some((w) => w.includes('top-level'))); ok('Parameter auf oberster Ebene werden übernommen, mit Hinweis');
    const miss = await exec(FULL, 'models.update', slug, {});
    expectErr(miss, 422, 'VALIDATION_FAILED', 'fehlender Pflichtparameter -> 422');
    assert.deepEqual(miss.json.data.missing, ['changes']); assert.ok(miss.json.data.received && miss.json.data.request_example.parameters.changes); ok('VALIDATION_FAILED enthält received + request_example');
    expectErr(await exec(FULL, 'models.update', slug, undefined, { parameters_json: '{kaputt' }), 422, 'VALIDATION_FAILED', 'kaputtes parameters_json -> 422');
    expectErr(await ai(FULL, 'POST', '/execute', { parameters: {} }), 422, 'VALIDATION_FAILED', 'fehlende action -> 422');
    expectErr(await call(FULL, 'POST', `${AI}/execute`, '{kein json').then((r) => { assert.ok(r.json && 'request_id' in r.json); return r; }), 400, 'BAD_REQUEST', 'kaputtes JSON -> 400 im Standardformat');
    expectErr(await exec(FULL, 'gibt.es.nicht'), 404, 'UNKNOWN_CAPABILITY', 'unbekannte Capability -> 404');
    expectErr(await exec(FULL, 'keys.create', null, { name: 'x' }), 403, 'CRITICAL_ACTION_BLOCKED', 'kritische Aktion (Schlüssel anlegen) -> gesperrt');
    expectErr(await exec(FULL, 'settings.update', null, { changes: { ai_write_enabled: true } }), 403, 'CRITICAL_ACTION_BLOCKED', 'AI-Schalter nicht über die API änderbar');

    // ---------- optimistic concurrency ----------
    doc = (await admin('GET', `/models/${id}`)).json;
    expectErr(await exec(FULL, 'models.update', slug, { changes: { frase: 'veraltet' } }, { expected_updated_at: '2020-01-01T00:00:00.000Z' }), 409, 'CONFLICT', 'expected_updated_at veraltet -> 409');
    expectErr(await exec(FULL, 'models.update', slug, { changes: { frase: 'veraltet', expected_updated_at: '2020-01-01T00:00:00.000Z' } }), 409, 'CONFLICT', 'expected_updated_at in parameters.changes -> 409');
    expectErr(await exec(FULL, 'models.update', slug, { expected_updated_at: '2020-01-01T00:00:00.000Z', changes: { frase: 'veraltet' } }), 409, 'CONFLICT', 'expected_updated_at in parameters -> 409');
    assert.equal((await admin('GET', `/models/${id}`)).json.frase, 'Claim di prova');
    const fresh = await exec(FULL, 'models.update', slug, { changes: { frase: 'Claim aggiornato', expected_updated_at: doc.updated_at } }, { session_id: S });
    assert.equal(fresh.status, 200, fresh.text); doc = (await admin('GET', `/models/${id}`)).json;
    assert.equal(doc.frase, 'Claim aggiornato'); assert.ok(!('expected_updated_at' in doc)); ok('passendes expected_updated_at wird angenommen und nicht als Feld gespeichert');

    // ---------- idempotency ----------
    const idem = { 'Idempotency-Key': `idem-${tag}` };
    const i1 = await exec(FULL, 'models.update', slug, { changes: { tag: ['prova', 'idem'] } }, { session_id: S }, idem);
    assert.equal(i1.status, 200, i1.text);
    const i2 = await exec(FULL, 'models.update', slug, { changes: { tag: ['prova', 'idem'] } }, { session_id: S }, idem);
    assert.equal(i2.status, 200); assert.equal(i2.json.data.idempotent_replayed, true); assert.equal(i2.headers.get('idempotent-replayed'), 'true');
    assert.deepEqual(i2.json.rollback.version_ids, i1.json.rollback.version_ids); assert.deepEqual(i2.json.changes, i1.json.changes); ok('Idempotency-Key: Wiederholung liefert dieselbe Antwort, keine zweite Änderung');
    expectErr(await exec(FULL, 'models.update', slug, { changes: { tag: ['anders'] } }, { session_id: S }, idem), 409, 'IDEMPOTENCY_CONFLICT', 'Idempotency-Key mit anderem Inhalt -> 409');

    // ---------- media ----------
    const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';
    const up = await exec(FULL, 'media.upload_url', null, { base64_data: png });
    assert.equal(up.status, 200, up.text); assert.equal(up.json.data.tipo, 'image'); assert.match(up.json.data.url, /^\/api\/uploads\/lato-segreto\/uploads\/[a-f0-9]{32}\.png$/);
    assert.equal((await fetch(B + up.json.data.url)).status, 200); ok('media.upload_url (base64): gespeichert und unter /api/uploads abrufbar');
    const asg = await exec(FULL, 'media.assign', slug, { url: up.json.data.url, slot: 'card' }, { session_id: S });
    assert.equal(asg.status, 200, asg.text); assert.equal((await admin('GET', `/models/${id}`)).json.foto_card, up.json.data.url);
    const pair = await exec(FULL, 'media.assign', slug, { url: up.json.data.url, slot: 'secret_photo_1', alt: 'Prova' }, { session_id: S });
    assert.equal(pair.status, 200, pair.text); doc = (await admin('GET', `/models/${id}`)).json;
    assert.equal(doc.media_pairs.length, 1); assert.equal(doc.media_pairs[0].segreto.url, up.json.data.url); assert.equal(doc.media_pairs[0].pubblico.url, ''); ok('media.assign: Feld foto_card und Paar-Slot secret_photo_1');
    const ml = await exec(FULL, 'media.list', slug);
    assert.ok(ml.json.data.items.some((i) => i.field === 'foto_card' && i.exists === true)); ok('media.list zeigt die verwendeten Dateien');
    expectErr(await exec(FULL, 'media.assign', slug, { url: up.json.data.url, slot: 'public_video_1' }), 422, 'VALIDATION_FAILED', 'Bild in Video-Slot abgelehnt');
    expectErr(await exec(FULL, 'media.assign', slug, { url: 'https://example.com/x.jpg', slot: 'card' }), 422, 'VALIDATION_FAILED', 'media.assign nur mit hochgeladener Datei');
    expectErr(await exec(FULL, 'media.assign', slug, { url: '/api/uploads/../lato.db', slot: 'card' }), 422, 'VALIDATION_FAILED', 'kein Pfad-Ausbruch aus dem Upload-Ordner');
    expectErr(await exec(FULL, 'media.upload_url', null, { url: `${B}/api/health` }), 422, 'MEDIA_VALIDATION_FAILED', 'Upload von localhost abgelehnt (SSRF)');
    expectErr(await exec(FULL, 'media.upload_url', null, { url: 'http://169.254.169.254/latest/meta-data/' }), 422, 'MEDIA_VALIDATION_FAILED', 'Upload von Metadaten-Adresse abgelehnt (SSRF)');
    expectErr(await exec(FULL, 'media.upload_url', null, { url: 'http://[::ffff:10.0.0.1]/a.jpg' }), 422, 'MEDIA_VALIDATION_FAILED', 'Upload von privater IPv6-Adresse abgelehnt');
    expectErr(await exec(FULL, 'media.upload_url', null, { url: 'file:///etc/passwd' }), 422, 'MEDIA_VALIDATION_FAILED', 'Upload nur über http(s)');
    expectErr(await exec(FULL, 'media.upload_url', null, { base64_data: Buffer.from('<html><script>alert(1)</script></html>').toString('base64') }), 422, 'MEDIA_VALIDATION_FAILED', 'Upload: Dateityp nach Inhalt geprüft (HTML abgelehnt)');

    // optional: a real download needs the internet, so it only runs when a public image URL is given
    if (process.env.TEST_MEDIA_URL) {
      const dl = await exec(FULL, 'media.upload_url', null, { url: process.env.TEST_MEDIA_URL });
      assert.equal(dl.status, 200, dl.text); assert.match(dl.json.data.url, /^\/api\/uploads\//); assert.equal((await fetch(B + dl.json.data.url)).status, 200);
      ok(`media.upload_url (URL): ${dl.json.data.mime}, ${dl.json.data.size} Bytes heruntergeladen und gespeichert`);
    } else console.log('  --  übersprungen: media.upload_url von echter URL (TEST_MEDIA_URL nicht gesetzt)');

    // ---------- REVIEW_REQUIRED -> approval ----------
    const del = await exec(FULL, 'models.soft_delete', slug, {}, { session_id: S, reason: 'test approvazione' });
    assert.equal(del.status, 200, del.text); assert.equal(del.json.approval_required, true); assert.match(del.json.approval.token, /^apr_/);
    assert.deepEqual(del.json.rollback.version_ids, []);
    const apr = del.json.approval; forbidden.push(sha256(apr.token));
    assert.equal((await admin('GET', `/models/${id}`)).json.is_deleted, false); ok('REVIEW-Capability: approval_required + Token, nichts geändert');
    const pend = await ai(FULL, 'GET', '/approvals');
    assert.ok(pend.json.data.items.some((a) => a.id === apr.id)); assert.ok(!pend.text.includes(apr.token)); ok('listApprovals zeigt die Anfrage ohne Token');
    assert.equal((await ai(RO, 'GET', '/approvals')).json.data.items.length, 0); ok('anderer Schlüssel sieht fremde Anfragen nicht');
    expectErr(await ai(FULL, 'POST', `/approvals/${apr.id}/approve`, { token: 'apr_falsch' }), 403, 'APPROVAL_INVALID', 'falscher Token -> abgelehnt');
    expectErr(await ai(FULL, 'POST', `/approvals/${apr.id}/approve`, {}), 400, 'APPROVAL_INVALID', 'fehlender Token -> abgelehnt');
    expectErr(await ai(RO, 'POST', `/approvals/${apr.id}/approve`, { token: apr.token }), 403, 'APPROVAL_INVALID', 'Token an den Schlüssel gebunden');
    await setControl({ ai_write_enabled: false });
    expectErr(await ai(FULL, 'POST', `/approvals/${apr.id}/approve`, { token: apr.token }), 403, 'READ_ONLY_MODE', 'Freigabe umgeht READ_ONLY nicht');
    await setControl({ ai_write_enabled: true });
    assert.equal((await admin('GET', `/models/${id}`)).json.is_deleted, false);
    const done = await ai(FULL, 'POST', `/approvals/${apr.id}/approve`, { token: apr.token });
    assert.equal(done.status, 200, done.text); assert.equal(done.json.rollback.version_ids.length, 1); assert.equal(done.json.data.approval_id, apr.id);
    assert.equal((await admin('GET', `/models/${id}`)).json.is_deleted, true); ok('approve führt die Änderung genau einmal aus');
    expectErr(await ai(FULL, 'POST', `/approvals/${apr.id}/approve`, { token: apr.token }), 409, 'APPROVAL_INVALID', 'Token nicht wiederverwendbar');
    expectErr(await exec(FULL, 'models.get', slug), 404, 'NOT_FOUND', 'gelöschtes Modell wird nicht mehr aufgelöst');
    // approval invalid once the content changed after the proposal
    const und = await exec(FULL, 'models.undelete', null, { model: slug }, { session_id: S });
    assert.equal(und.status, 200, und.text); assert.equal((await admin('GET', `/models/${id}`)).json.stato, 'bozza'); ok('models.undelete holt es als Entwurf zurück');
    const del2 = await exec(FULL, 'models.soft_delete', slug, {}, { session_id: S });
    forbidden.push(sha256(del2.json.approval.token));
    assert.equal((await exec(FULL, 'models.update', slug, { changes: { frase: 'Cambiato dopo la proposta' } }, { session_id: S })).status, 200);
    expectErr(await ai(FULL, 'POST', `/approvals/${del2.json.approval.id}/approve`, { token: del2.json.approval.token }), 409, 'CONFLICT', 'Freigabe ungültig, wenn sich der Inhalt nach der Vorschau geändert hat');
    const rej = await ai(FULL, 'POST', `/approvals/${del2.json.approval.id}/reject`, { reason: 'test' });
    assert.equal(rej.status, 200); assert.equal(rej.json.data.status, 'rejected');
    expectErr(await ai(FULL, 'POST', `/approvals/${del2.json.approval.id}/approve`, { token: del2.json.approval.token }), 409, 'APPROVAL_INVALID', 'abgelehnte Anfrage nicht mehr freigebbar');

    // ---------- rollback.session restores the previous state ----------
    const S2 = `ses_rb_${tag}`;
    const target = list.json.data.items[1] || sample;
    const orig = (await admin('GET', `/models/${target.id}`)).text;
    assert.equal((await exec(FULL, 'models.update', target.slug, { changes: { frase: 'Rollback prova 1' } }, { session_id: S2 })).status, 200);
    assert.equal((await exec(FULL, 'models.set_seo', target.slug, { seo: { og_title: 'Rollback prova' } }, { session_id: S2 })).status, 200);
    const cats = (await exec(FULL, 'categories.list')).json.data.items;
    assert.equal((await exec(FULL, 'models.categories.set', target.slug, { categories: [cats[0].nome.toUpperCase()] }, { session_id: S2 })).status, 200);
    const mid = (await admin('GET', `/models/${target.id}`)).json;
    assert.equal(mid.frase, 'Rollback prova 1'); assert.equal(mid.seo.og_title, 'Rollback prova'); assert.deepEqual(mid.categorie, [cats[0].slug]);
    const plan = await ai(FULL, 'POST', '/rollback', { session_id: S2, dry_run: true });
    assert.equal(plan.status, 200, plan.text); assert.equal(plan.json.data.restored_count, 3); assert.equal(plan.json.data.dry_run, true);
    assert.equal((await admin('GET', `/models/${target.id}`)).json.frase, 'Rollback prova 1'); ok('rollback Vorschau: Plan mit 3 Schritten, nichts geändert');
    expectErr(await ai(RO, 'POST', '/rollback', { session_id: S2 }), 403, 'INSUFFICIENT_SCOPE', 'READ_ONLY-Schlüssel darf nicht zurückrollen');
    const rb = await ai(FULL, 'POST', '/rollback', { session_id: S2 });
    assert.equal(rb.status, 200, rb.text); assert.equal(rb.json.data.restored_count, 3);
    assert.equal((await admin('GET', `/models/${target.id}`)).text, orig); ok('rollback.session stellt den Zustand von vorher exakt wieder her');
    const rb2 = await ai(FULL, 'POST', '/rollback', { session_id: S2 });
    assert.equal(rb2.json.data.restored_count, 0); assert.equal(rb2.json.data.skipped_count, 3); ok('zweites Rollback derselben Sitzung ändert nichts');
    expectErr(await ai(FULL, 'POST', '/rollback', { version_id: plan.json.data.restored[0].version_id }), 409, 'CONFLICT', 'rollback.version einer schon zurückgerollten Änderung -> 409');
    expectErr(await ai(FULL, 'POST', '/rollback', { session_id: 'ses_gibt_es_nicht' }), 404, 'NOT_FOUND', 'unbekannte Sitzung -> 404');
    expectErr(await ai(FULL, 'POST', '/rollback', {}), 422, 'VALIDATION_FAILED', 'rollback ohne Angabe -> 422');
    // a later manual edit is never overwritten
    const S3 = `ses_skip_${tag}`;
    assert.equal((await exec(FULL, 'models.update', target.slug, { changes: { teaser_copy: 'Dalla AI' } }, { session_id: S3 })).status, 200);
    const manual = (await admin('GET', `/models/${target.id}`)).json;
    assert.equal((await admin('PUT', `/models/${target.id}`, { ...manual, teaser_copy: 'Dal pannello' })).status, 200);
    const rb3 = await ai(FULL, 'POST', '/rollback', { session_id: S3 });
    assert.equal(rb3.json.data.restored_count, 0); assert.equal(rb3.json.data.skipped_count, 1);
    assert.equal((await admin('GET', `/models/${target.id}`)).json.teaser_copy, 'Dal pannello'); ok('Rollback überschreibt keine spätere Änderung aus dem Admin');
    assert.equal((await admin('PUT', `/models/${target.id}`, JSON.parse(orig))).status, 200);

    // ---------- categories, articles, settings ----------
    const S4 = `ses_misc_${tag}`;
    const c1 = await exec(FULL, 'categories.create', null, { nome: `Prova ${tag}`, fields: { descrizione: 'Categoria di prova' } }, { session_id: S4 });
    assert.equal(c1.status, 200, c1.text);
    expectErr(await exec(FULL, 'categories.create', null, { nome: `Prova ${tag}` }), 409, 'CONFLICT', 'doppelter Kategorie-Slug -> 409');
    const c2 = await exec(FULL, 'categories.update', `prova ${tag}`, { changes: { meta_description: 'Meta di prova' } }, { session_id: S4 });
    assert.equal(c2.status, 200, c2.text);
    let catDoc = (await admin('GET', '/categories')).json.items.find((c) => c.id === c1.json.data.id);
    assert.equal(catDoc.meta_description, 'Meta di prova'); assert.equal(catDoc.descrizione, 'Categoria di prova'); ok('categories.create + update (Teiländerung)');
    const a1 = await exec(FULL, 'articles.create', null, { titolo: `Articolo prova ${tag}`, fields: { contenuto: '<p>Ciao</p><script>alert(1)</script>' } }, { session_id: S4 });
    assert.equal(a1.status, 200, a1.text); assert.equal(a1.json.data.stato, 'bozza');
    const a2 = await exec(FULL, 'articles.update', a1.json.data.slug, { changes: { estratto: 'Estratto di prova' } }, { session_id: S4 });
    assert.equal(a2.status, 200, a2.text);
    const art = (await admin('GET', `/articles/${a1.json.data.id}`)).json;
    assert.ok(!art.contenuto.includes('<script')); assert.equal(art.estratto, 'Estratto di prova'); assert.equal(art.titolo, `Articolo prova ${tag}`); ok('articles.create + update: Schadcode entfernt, Teiländerung');
    assert.ok((await exec(FULL, 'articles.list', null, { q: tag })).json.data.total >= 1);
    const set0 = (await admin('GET', '/settings')).text;
    const s1 = await exec(FULL, 'settings.update', null, { changes: { footer_contatti: `prova-${tag}@example.test`, home_pellicola: { titolo: 'PROVA' } } }, { session_id: S4 });
    assert.equal(s1.status, 200, s1.text);
    const set1 = (await admin('GET', '/settings')).json;
    assert.equal(set1.footer_contatti, `prova-${tag}@example.test`); assert.equal(set1.home_pellicola.titolo, 'PROVA');
    expectErr(await exec(FULL, 'settings.update', null, { changes: { jwt_secret: 'x' } }), 422, 'VALIDATION_FAILED', 'settings.update nur erlaubte Felder');
    const rb4 = await ai(FULL, 'POST', '/rollback', { session_id: S4 });
    assert.equal(rb4.status, 200, rb4.text); assert.equal(rb4.json.data.restored_count, 5);
    assert.equal((await admin('GET', '/settings')).text, set0);
    assert.equal((await admin('GET', `/articles/${a1.json.data.id}`)).status, 404);
    catDoc = (await admin('GET', '/categories')).json.items.find((c) => c.id === c1.json.data.id);
    assert.equal(catDoc, undefined); ok('rollback.session über Kategorie, Artikel und Einstellungen: alles wie vorher');

    // ---------- config.site (base URL) ----------
    const cg = await exec(RO, 'config.site.get');
    assert.equal(cg.status, 200); assert.equal(cg.json.data.value, control0.base_url); assert.ok(['config', 'env', 'request'].includes(cg.json.data.source)); ok(`config.site.get: ${cg.json.data.source}`);
    for (const [bad, why] of [['http://www.example.it', 'http://'], ['https://user:pass@www.example.it', 'Zugangsdaten'], ['https://www.example.it/?a=1', 'Query'],
      ['https://www.example.it/percorso', 'Pfad'], ['https://www.example.it/#x', 'Fragment'], ['www.example.it', 'ohne Schema'], ['https://localhost', 'kein öffentlicher Hostname'],
      ['https://10.0.0.1', 'IP-Adresse'], ['https://www.example.it:8443', 'Port'], ['https://secret-side.emergent.host', 'altes Hosting']]) {
      expectErr(await preview(FULL, 'config.site.update', null, { base_url: bad }), 422, 'VALIDATION_FAILED', `config.site.update lehnt ab: ${why}`);
    }
    expectErr(await exec(FULL, 'config.site.update', null, { base_url: 'https://www.example.it', ai_write_enabled: true }), 422, 'VALIDATION_FAILED', 'config.site.update nimmt nur base_url');
    expectErr(await exec(FULL, 'config.update', null, { path: 'ai.x', value: 1 }), 403, 'CRITICAL_ACTION_BLOCKED', 'allgemeines config.update gibt es nicht');
    const S5 = `ses_site_${tag}`;
    const sitePv = await preview(RO, 'config.site.update', null, { base_url: 'https://www.lato-prova.invalid/' });
    assert.equal(sitePv.status, 200, sitePv.text); assert.equal(sitePv.json.data.proposed, 'https://www.lato-prova.invalid'); assert.ok(sitePv.json.data.affected.length >= 4);
    assert.equal((await exec(RO, 'config.site.get')).json.data.value, control0.base_url); ok('config.site.update Vorschau: aktuell -> neu, betroffene Bereiche, nichts gespeichert');
    const siteEx = await exec(FULL, 'config.site.update', null, { base_url: 'https://www.lato-prova.invalid/' }, { session_id: S5 });
    if (siteEx.status === 422) {
      // server runs with NODE_ENV=production: the live check must refuse a domain that does not answer from this app
      assert.match(siteEx.json.summary, /non risponde/); ok('config.site.update in Produktion: Domain ohne diese App wird abgelehnt (Speichern/Rollback hier nicht prüfbar)');
    } else {
      assert.equal(siteEx.status, 200, siteEx.text); assert.equal(siteEx.json.approval_required, true); forbidden.push(sha256(siteEx.json.approval.token));
      assert.equal((await exec(RO, 'config.site.get')).json.data.value, control0.base_url);
      const siteOk = await ai(FULL, 'POST', `/approvals/${siteEx.json.approval.id}/approve`, { token: siteEx.json.approval.token });
      assert.equal(siteOk.status, 200, siteOk.text); assert.equal(siteOk.json.data.value, 'https://www.lato-prova.invalid');
      const cg2 = (await exec(RO, 'config.site.get')).json.data;
      assert.equal(cg2.value, 'https://www.lato-prova.invalid'); assert.equal(cg2.source, 'config'); assert.ok(cg2.updated_at);
      assert.ok((await (await fetch(`${B}/sitemap.xml`)).text()).includes('<loc>https://www.lato-prova.invalid/</loc>'));
      assert.ok((await (await fetch(`${B}/robots.txt`)).text()).includes('Sitemap: https://www.lato-prova.invalid/sitemap.xml'));
      assert.equal((await call(null, 'GET', `${AI}/openapi-chatgpt.json`)).json.servers[0].url, 'https://www.lato-prova.invalid');
      assert.ok((await exec(RO, 'models.list')).json.data.items[0].public_url.startsWith('https://www.lato-prova.invalid/modelle/'));
      ok('config.site.update nach Freigabe: Sitemap, robots, Schema und public_url nutzen die neue Basis-URL');
      const rb5 = await ai(FULL, 'POST', '/rollback', { session_id: S5 });
      assert.equal(rb5.status, 200, rb5.text); assert.equal(rb5.json.data.restored_count, 1);
      const cg3 = (await exec(RO, 'config.site.get')).json.data;
      assert.equal(cg3.value, control0.base_url); assert.equal(cg3.source, cg.json.data.source); ok('Rollback stellt die vorherige Basis-URL wieder her');
    }

    // ---------- SEO, analytics, jobs ----------
    const au = await exec(RO, 'seo.audit');
    assert.equal(au.status, 200, au.text); assert.ok(Array.isArray(au.json.data.issues) && au.json.data.checked.models > 0); ok(`seo.audit: ${au.json.data.issues.length} Hinweise, nur lesend`);
    const sm = await exec(RO, 'seo.sitemap_status');
    assert.equal(sm.status, 200); assert.ok(sm.json.data.total_urls > 0 && sm.json.data.sitemap_url.endsWith('/sitemap.xml')); ok('seo.sitemap_status');
    const an = await ai(RO, 'POST', '/analytics/query', { metric: 'onlyfans_ctr', group_by: 'model', country: 'IT', period: '7d' });
    assert.equal(an.status, 200, an.text); assert.equal(an.json.data.data_available, false); assert.ok(an.json.data.limitations.length > 0); assert.deepEqual(an.json.data.items, []);
    ok('queryAnalytics: nicht erhobene Dimension -> data_available:false + limitations, keine Zahlen');
    const an2 = await ai(RO, 'POST', '/analytics/query', { metric: 'visits', group_by: 'model', range: '30g' });
    assert.equal(an2.status, 200, an2.text); assert.equal(typeof an2.json.data.data_available, 'boolean'); assert.equal(an2.json.data.data_available, an2.json.data.items.length > 0);
    assert.ok('sample_size' in an2.json.data && Array.isArray(an2.json.data.limitations));
    if (!an2.json.data.data_available) assert.equal(an2.json.data.sample_size, 0);
    ok(`queryAnalytics visits/model: data_available=${an2.json.data.data_available}, sample_size=${an2.json.data.sample_size}`);
    expectErr(await ai(RO, 'POST', '/analytics/query', { metric: 'umsatz' }), 422, 'VALIDATION_FAILED', 'queryAnalytics: unbekannte Metrik -> 422');
    expectErr(await ai(RO, 'GET', '/jobs/aij_123'), 404, 'NOT_FOUND', 'getJob: keine Jobs in diesem System -> NOT_FOUND');

    // ---------- activity log ----------
    const acts = await admin('GET', '/ai/actions?limit=200');
    assert.equal(acts.status, 200);
    const mine = acts.json.items.filter((a) => a.session_id === S);
    assert.ok(mine.some((a) => a.action === 'models.create' && a.ok && a.kind === 'execute' && a.key_prefix === FULL.slice(0, 9)));
    assert.ok(acts.json.items.some((a) => a.kind === 'dry_run') && acts.json.items.some((a) => !a.ok && a.code === 'PUBLICATION_BLOCKED'));
    assert.ok(!acts.text.includes(FULL) && !acts.text.includes(apr.token) && !acts.text.includes(png)); ok('Protokoll: Aktionen mit Schlüssel-Präfix, ohne Schlüssel, Token oder Dateiinhalt');

    // ---------- rollback of the creation session (cleanup of the test creators) ----------
    const rbS = await ai(FULL, 'POST', '/rollback', { session_id: S });
    assert.equal(rbS.status, 200, rbS.text); assert.ok(rbS.json.data.restored_count >= 2);
    assert.equal((await admin('GET', '/models')).json.items.filter((m) => m.nome.includes(`Prova ${tag}`)).length, 0); ok('Rollback der Erstell-Sitzung: Test-Creators wieder weg (soft-deleted)');

    // ---------- rate limit ----------
    const rl = await newKey('Test Rate-Limit', 'read_only');
    await setControl({ ai_rate_limit_per_min: 10 });
    let limited = null;
    for (let i = 0; i < 12 && !limited; i++) { const r = await ai(rl.key, 'GET', '/status'); if (r.status === 429) limited = { r, after: i }; }
    assert.ok(limited, 'kein 429 nach 12 Anfragen'); assert.equal(limited.after, 10); assert.equal(limited.r.json.code, 'RATE_LIMITED');
    assert.ok(Number(limited.r.headers.get('retry-after')) >= 1); ok('Rate-Limit: 11. Anfrage in der Minute -> 429 mit Retry-After');
    assert.equal((await admin('PATCH', '/ai/control', { ai_rate_limit_per_min: 0 })).status, 400); ok('Rate-Limit lässt sich nicht abschalten');
    await setControl({ ai_rate_limit_per_min: 600 });

    // ---------- kill switch ----------
    await setControl({ ai_api_enabled: false });
    expectErr(await ai(FULL, 'GET', '/status'), 503, 'AI_API_DISABLED', 'Not-Aus: Status -> AI_API_DISABLED');
    expectErr(await ai(FULL, 'GET', '/capabilities'), 503, 'AI_API_DISABLED', 'Not-Aus: Katalog -> AI_API_DISABLED');
    expectErr(await exec(FULL, 'models.list'), 503, 'AI_API_DISABLED', 'Not-Aus: execute -> AI_API_DISABLED');
    expectErr(await preview(RO, 'models.list'), 503, 'AI_API_DISABLED', 'Not-Aus: preview -> AI_API_DISABLED');
    expectErr(await exec(FULL, 'gibt.es.nicht'), 404, 'UNKNOWN_CAPABILITY', 'Not-Aus: unbekannte Capability bleibt 404');
    assert.equal((await ai(jwt, 'GET', '/status')).status, 200); assert.equal((await call(null, 'GET', '/api/models')).status, 200); ok('Not-Aus trifft nur die Schlüssel: Admin und Website laufen weiter');
    await setControl({ ai_api_enabled: true });
    assert.equal((await ai(FULL, 'GET', '/status')).status, 200); ok('Not-Aus wieder aus: Schlüssel funktioniert');
  } finally {
    // restore switches, remove test keys
    await admin('PATCH', '/ai/control', { ai_api_enabled: control0.ai_api_enabled, ai_write_enabled: control0.ai_write_enabled, ai_rate_limit_per_min: control0.ai_rate_limit_per_min });
    for (const kid of keys) await admin('DELETE', `/ai/keys/${kid}`);
  }
  assert.equal((await admin('GET', '/ai/keys')).json.items.filter((k) => k.name.startsWith('Test ')).length, 0);
  console.log(`\nALLE KI-TESTS BESTANDEN (${count} Prüfungen)`);
})().catch((e) => { console.error('\nFEHLER:', e.message); process.exit(1); });
