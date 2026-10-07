// End-to-end check of the admin API against a running local server (uses data/test-admin.txt).
//   node scripts/test-admin-api.js
// DATA_DIR must be the data folder of that server (default: data/), e.g. a throw-away copy for tests.
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const B = process.env.BASE || 'http://localhost:8001';
const DATA = path.resolve(process.env.DATA_DIR || path.join(__dirname, '..', 'data'));
const creds = fs.readFileSync(path.join(DATA, 'test-admin.txt'), 'utf8');
const email = creds.match(/E-Mail: (.+)/)[1].trim();
const password = creds.match(/Passwort: (.+)/)[1].trim();

let token = '';
async function call(method, p, body, extra = {}) {
  const headers = { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(extra.headers || {}) };
  let payload = body;
  if (body && !(body instanceof FormData)) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const r = await fetch(B + p, { method, headers, body: payload });
  const text = await r.text();
  let json; try { json = JSON.parse(text); } catch { json = text; }
  return { status: r.status, json, headers: r.headers };
}
const ok = (label) => console.log(`  ok  ${label}`);

(async () => {
  // no token -> blocked
  assert.equal((await call('GET', '/api/admin/models')).status, 401); ok('ohne Login gesperrt');
  assert.equal((await call('POST', '/api/admin/models', { nome: 'x' })).status, 401); ok('ohne Login nichts anlegen');
  const fake = await call('GET', '/api/admin/models', null, { headers: { Authorization: 'Bearer abc.def.ghi' } });
  assert.equal(fake.status, 401); ok('gefälschter Token gesperrt');
  assert.equal((await call('POST', '/api/admin/login', { email, password: 'falsch' })).status, 401); ok('falsches Passwort abgelehnt');

  const login = await call('POST', '/api/admin/login', { email, password });
  assert.equal(login.status, 200); token = login.json.token; ok('Login');

  // uploads
  const img = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'public', 'media', fs.readdirSync(path.join(__dirname, '..', 'frontend', 'public', 'media')).find((f) => /\.(jpe?g|png|webp)$/i.test(f))));
  const fdImg = new FormData(); fdImg.append('file', new Blob([img], { type: 'image/jpeg' }), 'foto.jpg');
  const upImg = await call('POST', '/api/admin/upload', fdImg);
  assert.equal(upImg.status, 200); assert.equal(upImg.json.tipo, 'image'); ok(`Bild hochgeladen -> ${upImg.json.url}`);
  const vidPath = path.join(DATA, 'uploads', 'lato-segreto', 'uploads');
  const vid = fs.readFileSync(path.join(vidPath, fs.readdirSync(vidPath).find((f) => f.endsWith('.mp4'))));
  const fdVid = new FormData(); fdVid.append('file', new Blob([vid], { type: 'video/mp4' }), 'clip.mp4');
  const upVid = await call('POST', '/api/admin/upload', fdVid);
  assert.equal(upVid.json.tipo, 'video'); ok(`Video hochgeladen (${(vid.length / 1e6).toFixed(1)} MB)`);
  const fdBad = new FormData(); fdBad.append('file', new Blob(['<script>'], { type: 'text/html' }), 'x.html');
  assert.equal((await call('POST', '/api/admin/upload', fdBad)).status, 400); ok('HTML-Datei als Upload abgelehnt');

  // media served, incl. range request (video seeking on iPhone)
  const media = await fetch(B + upImg.json.url); assert.equal(media.status, 200); ok('Bild öffentlich abrufbar');
  const range = await fetch(B + upVid.json.url, { headers: { Range: 'bytes=0-1023' } });
  assert.equal(range.status, 206); ok('Video spulbar (Range 206)');
  assert.equal((await fetch(`${B}/api/uploads/../data/lato.db`)).status, 404); ok('kein Zugriff auf die Datenbank-Datei über die Medien-Adresse');

  // create draft -> not public
  const img2 = { tipo: 'image', url: upImg.json.url };
  const vid2 = { tipo: 'video', url: upVid.json.url };
  const created = await call('POST', '/api/admin/models', { nome: 'Test Creator', stato: 'bozza', frase: 'Claim', bio: 'Bio', onlyfans_url: 'https://onlyfans.com/test' });
  assert.equal(created.status, 200); const id = created.json.id; ok(`Entwurf angelegt (${created.json.slug})`);
  token = ''; assert.equal((await call('GET', `/api/models/${created.json.slug}`)).status, 404); token = login.json.token; ok('Entwurf öffentlich unsichtbar');

  // publish incomplete -> blocked with checklist
  const blocked = await call('PATCH', `/api/admin/models/${id}/stato`, { stato: 'pubblicata' });
  assert.equal(blocked.status, 400); ok(`unvollständig nicht veröffentlichbar (${blocked.json.detail.missing_count} Punkte fehlen)`);

  // complete + publish
  const full = {
    ...created.json, conferma_maggiorenne: true, foto_card: upImg.json.url, bio_segreta: 'Segreto',
    media_pairs: [0, 1, 2].map(() => ({ tipo: 'image', pubblico: img2, segreto: img2 })).concat([{ tipo: 'video', pubblico: vid2, segreto: vid2 }]),
    stato: 'pubblicata', categorie: ['bionde'],
  };
  const pub = await call('PUT', `/api/admin/models/${id}`, full);
  assert.equal(pub.status, 200); assert.equal(pub.json.stato, 'pubblicata'); ok('vervollständigt und veröffentlicht');
  token = '';
  assert.equal((await call('GET', `/api/models/${pub.json.slug}`)).status, 200); ok('jetzt öffentlich sichtbar');
  const html = await (await fetch(`${B}/modelle/${pub.json.slug}`)).text();
  assert.ok(html.includes('<h1>Test Creator</h1>')); ok('Profilseite als HTML für Google da');
  assert.ok((await (await fetch(`${B}/sitemap.xml`)).text()).includes(`/modelle/${pub.json.slug}`)); ok('automatisch in der Sitemap');
  token = login.json.token;

  // reorder, copy config, category, article, settings
  const list = (await call('GET', '/api/admin/models')).json.items.map((m) => m.id);
  assert.equal((await call('POST', '/api/admin/models/reorder', { order: [id, ...list.filter((x) => x !== id)] })).status, 200);
  token = ''; assert.equal((await call('GET', '/api/models')).json.items[0].slug, pub.json.slug); token = login.json.token; ok('Reihenfolge ändern wirkt auf Startseite');
  assert.equal((await call('POST', '/api/admin/models/reorder', { order: list })).status, 200);
  const cat = await call('POST', '/api/admin/categories', { nome: 'Test Kategorie' });
  assert.equal(cat.status, 200); assert.equal((await call('DELETE', `/api/admin/categories/${cat.json.id}`)).status, 200); ok('Kategorie anlegen + löschen');
  const art = await call('POST', '/api/admin/articles', { titolo: 'Test Artikel', contenuto: '<p>Hallo</p><script>alert(1)</script><img src=x onerror=alert(1)>', stato: 'bozza' });
  assert.ok(!art.json.contenuto.includes('<script') && !art.json.contenuto.includes('onerror')); ok('Artikel: Schadcode wird entfernt');
  assert.equal((await call('DELETE', `/api/admin/articles/${art.json.id}`)).status, 200);
  const s0 = (await call('GET', '/api/admin/settings')).json;
  assert.equal((await call('PUT', '/api/admin/settings', { footer_contatti: s0.footer_contatti })).status, 200); ok('Einstellungen speichern');

  // delete -> gone from public
  assert.equal((await call('DELETE', `/api/admin/models/${id}`)).status, 200);
  token = ''; assert.equal((await call('GET', `/api/models/${pub.json.slug}`)).status, 404); ok('gelöscht -> nicht mehr öffentlich');

  // cleanup: test uploads + the soft-deleted test creator
  for (const u of [upImg.json.url, upVid.json.url]) fs.rmSync(path.join(DATA, 'uploads', u.replace('/api/uploads/', '')));
  const { DatabaseSync } = require('node:sqlite');
  new DatabaseSync(path.join(DATA, 'lato.db')).prepare("DELETE FROM docs WHERE col = 'models' AND id = ?").run(id);
  console.log('\nALLE ADMIN-TESTS BESTANDEN');
})().catch((e) => { console.error('\nFEHLER:', e.message); process.exit(1); });
