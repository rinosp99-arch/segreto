// Import the content downloaded from the old site (inhalte/) into the new database + media folder.
//   cd server && npm run import            (dry run)
//   cd server && npm run import -- --ja    (write)
const fs = require('fs');
const path = require('path');

const SRC = path.resolve(process.argv.find((a) => a.startsWith('--von='))?.slice(6) || path.join(__dirname, '..', 'inhalte'));
const really = process.argv.includes('--ja');

const store = require('../server/db');
const C = require('../server/content');

const read = (f) => JSON.parse(fs.readFileSync(path.join(SRC, 'daten', f), 'utf8'));
const mediaMap = JSON.parse(fs.readFileSync(path.join(SRC, 'medien-liste.json'), 'utf8'));

// external demo images (unsplash/pexels) were downloaded too -> point to the local copy
function localize(value) {
  if (typeof value === 'string') {
    const local = mediaMap[value];
    if (local && /^https?:\/\//.test(value)) return `/api/uploads/${local.replace(/^medien\//, '')}`;
    return value;
  }
  if (Array.isArray(value)) return value.map(localize);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, localize(v)]));
  return value;
}

const pellicola = (() => { try { return read('pellicola.json'); } catch { return { config: {}, items: [] }; } })();
const pelBySlug = Object.fromEntries((pellicola.items || []).map((i) => [i.slug, i]));

const models = read('modelle.json').map(({ pubblico, segreto }) => {
  const { visite, has_secret, anteprima, video_pubblici, ...pub } = pubblico;
  const secret = {
    bio_segreta: segreto.bio_segreta, foto_segreta_hero: segreto.foto_segreta_hero, galleria_segreta: segreto.galleria_segreta,
    media_pairs: segreto.media_pairs, tema: segreto.tema, regia: segreto.regia, cta_temporizzata: segreto.cta_temporizzata,
    messaggio_35s: segreto.messaggio_35s, social: segreto.social || pub.social,
  };
  const pel = pelBySlug[pub.slug];
  const merged = localize({
    ...pub, ...secret,
    stato: 'pubblicata',
    conferma_maggiorenne: true, // all creators were already live and confirmed on the old site
    pellicola_home: pel
      ? { attiva: true, priorita: pel.priorita, ordine: pel.ordine_manuale, seq: pellicola.items.indexOf(pel), pubblico: pel.pubblico, segreto: pel.segreto }
      : { attiva: false },
  });
  const now = store.nowIso();
  return {
    ...C.normalizeModel(merged),
    id: pub.id, created_at: pub.data_pubblicazione || now, updated_at: now, visite_base: visite || 0,
  };
});

const categories = read('kategorien.json').map(({ conteggio, ...c }) => ({ ...c, ...C.normalizeCategory(c), id: c.id }));
const articles = read('artikel.json').map(({ modelle_correlate_dettaglio, ...a }) => localize({ ...a, ...C.normalizeArticle(a), id: a.id }));
const settings = {
  ...read('einstellungen.json'),
  home_pellicola: pellicola.config || {},
  id: 'global',
};

console.log(`Quelle: ${SRC}`);
console.log(`Ziel:   ${store.DATA_DIR}\n`);
console.log(`  ${models.length} Creatorinnen (alle veröffentlicht)`);
console.log(`  ${categories.length} Kategorien, ${articles.length} Artikel, Einstellungen`);
for (const m of models) {
  const rd = C.readiness(m);
  if (!rd.is_ready) console.log(`  Hinweis: ${m.slug} fehlt für die Veröffentlichungs-Prüfung: ${rd.missing_required.join(', ')}`);
}

const mediaSrc = path.join(SRC, 'medien');
const fromSite = process.argv.find((a) => a.startsWith('--medien-von='))?.slice(13).replace(/\/+$/, '');
// every media file the content refers to: old URL -> path below uploads/
const media = Object.entries(mediaMap).map(([url, rel]) => ({ url, rel: rel.replace(/^medien\//, '') }));
const localCount = media.filter((m) => fs.existsSync(path.join(mediaSrc, m.rel))).length;
console.log(`  ${media.length} Mediendateien, davon ${localCount} lokal vorhanden${fromSite ? `, Rest wird von ${fromSite} geladen` : ''}`);

if (!really) {
  console.log('\nProbelauf - nichts geschrieben. Zum Ausführen: npm run import -- --ja');
  process.exit(0);
}

store.transaction(() => {
  for (const col of ['models', 'categories', 'articles', 'settings']) store.db.prepare('DELETE FROM docs WHERE col = ?').run(col);
  models.forEach((m) => store.put('models', m));
  categories.forEach((c) => store.put('categories', c));
  articles.forEach((a) => store.put('articles', a));
  store.put('settings', settings);
});
console.log('\nDatenbank geschrieben.');

(async () => {
  let copied = 0;
  let downloaded = 0;
  const missing = [];
  for (const [i, m] of media.entries()) {
    const target = path.join(store.UPLOADS_DIR, m.rel);
    if (fs.existsSync(target) && fs.statSync(target).size > 0) continue;
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const local = path.join(mediaSrc, m.rel);
    try {
      if (fs.existsSync(local)) {
        fs.copyFileSync(local, target);
        copied += 1;
      } else if (fromSite) {
        const url = /^https?:\/\//.test(m.url) ? m.url : fromSite + encodeURI(m.url);
        const r = await fetch(url);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        fs.writeFileSync(`${target}.part`, Buffer.from(await r.arrayBuffer()));
        fs.renameSync(`${target}.part`, target);
        downloaded += 1;
      } else {
        throw new Error('nicht lokal vorhanden (--medien-von=<alte Seite> angeben)');
      }
    } catch (e) {
      missing.push(`${m.url}  ${e.message}`);
    }
    if ((i + 1) % 50 === 0) console.log(`  ${i + 1}/${media.length} Medien geprüft`);
  }
  console.log(`\nImport fertig: ${copied} Medien kopiert, ${downloaded} geladen, ${missing.length} fehlen.`);
  missing.slice(0, 20).forEach((l) => console.log(`  FEHLT ${l}`));
  if (missing.length) process.exitCode = 1;
})();
