// One-off content corrections for a database that already exists (the import only fills an empty one).
// Every step checks the old value first: it runs once and never overwrites what was edited in the admin since.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const store = require('./db');

const clean = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const hash = (s) => crypto.createHash('sha1').update(clean(s)).digest('hex').slice(0, 16);

// 10/2026: profile titles name what people search for ("<name> OnlyFans"); also fixes the typo "ara Destro".
const PROFILE_TITLES = {
  'vanessa-bella': ['Vanessa | Tatuatrice, stile e Lato Segreto', 'Vanessa Bella OnlyFans | Tatuatrice, stile e Lato Segreto'],
  'flavia-russo-4': ['Flavia Russo | LATO SEGRETO', 'Flavia Russo OnlyFans | Profilo su LATO SEGRETO'],
  'valeria-trapani': ['Valeria Trapani | LATO SEGRETO', 'Valeria Trapani OnlyFans | Profilo su LATO SEGRETO'],
  martina: ['Martina | LATO SEGRETO', 'Martina OnlyFans | Profilo su LATO SEGRETO'],
  'chiara-lamora': ['Chiara La Mora | LATO SEGRETO', 'Chiara La Mora OnlyFans | Profilo su LATO SEGRETO'],
  'ambra-giallo-2': ['AMBRA GIALLO | LATO SEGRETO', 'Ambra Giallo OnlyFans | Profilo su LATO SEGRETO'],
  'ambra-celeste': ['Ambra Celeste | LATO SEGRETO', 'Ambra Celeste OnlyFans | Profilo su LATO SEGRETO'],
  'anna-bionda': ['ANNA BIONDA | LATO SEGRETO', 'Anna Bionda OnlyFans | Profilo su LATO SEGRETO'],
  'francesca-minetti': ['Francesca Minetti | LATO SEGRETO', 'Francesca Minetti OnlyFans | Profilo su LATO SEGRETO'],
  'serena-torre': ['Serena Torre | LATO SEGRETO', 'Serena Torre OnlyFans | Profilo su LATO SEGRETO'],
  morena: ['MORENA | LATO SEGRETO', 'Morena OnlyFans | Profilo su LATO SEGRETO'],
  'daiana-rossi': ['Daiana Rossi | LATO SEGRETO', 'Daiana Rossi OnlyFans | Profilo su LATO SEGRETO'],
  'alessia-golosa': ['Alessia | Creator tatuata dallo stile dark | Lato Segreto', 'Alessia Golosa OnlyFans | Stile dark e tatuaggi | Lato Segreto'],
  'aurora-bianchini': ['Aurora Bianchini | Glamour e stile | Lato Segreto', 'Aurora Bianchini OnlyFans | Glamour e stile | Lato Segreto'],
  zaira: ['Zaira | Stile tropicale e tatuaggi | Lato Segreto', 'Zaira OnlyFans | Stile tropicale e tatuaggi | Lato Segreto'],
  'aurora-caruso': ['Aurora Caruso | Glamour, lusso e Lato Segreto', 'Aurora Caruso OnlyFans | Glamour, lusso e Lato Segreto'],
  'chiara-marino': ['Chiara Marino | Beach vibes, stile e Lato Segreto', 'Chiara Marino OnlyFans | Beach vibes, stile e Lato Segreto'],
  'greta-sala': ['Greta Sala | Beach vibes, eleganza tropicale e Lato Segreto', 'Greta Sala OnlyFans | Eleganza tropicale e Lato Segreto'],
  veronica: ['Veronica | Fitness, tatuaggi e stile | Lato Segreto', 'Veronica Atomica OnlyFans | Fitness e tatuaggi | Lato Segreto'],
  'susi-milano': ['Susi Milano | Tatuaggi e stile alternative | Lato Segreto', 'Susi Milano OnlyFans | Tatuaggi, stile alternative | Lato Segreto'],
  'lara-destro': ['ara Destro | Tatuaggi, stile e fascino naturale | Lato Segreto', 'Lara Destro OnlyFans | Tatuaggi e fascino naturale | Lato Segreto'],
};

function profileTitles() {
  let n = 0;
  for (const [slug, [from, to]] of Object.entries(PROFILE_TITLES)) {
    const doc = store.find('models', (m) => m.slug === slug);
    if (!doc || clean(doc.seo?.title) !== from) continue;
    const seo = { ...doc.seo, title: to };
    if (clean(doc.seo.og_title) === from) seo.og_title = to;
    store.put('models', { ...doc, seo, updated_at: store.nowIso() });
    store.audit('sistema', 'update', 'model', doc.id, { campo: 'seo.title', da: from, a: to });
    n += 1;
  }
  return n;
}

// 10/2026: category titles in the word order people search ("OnlyFans bionde italiane"), longer category texts.
// New values come from inhalte/seo-inhalte.json; a field is replaced only while it still holds the old text (checksum).
const CATEGORY_OLD = {
  more: { seo_title: 'b956d37c86e8392e', meta_description: '0ce8f1ae9b9fccc1', testo_seo: '1ee9da5f8d5de647' },
  bionde: { seo_title: '999e5eb1e04ab783', meta_description: '9d7ad8a88019d7ff', testo_seo: 'b035f9fdc2ea0fe3' },
  tatuate: { seo_title: 'edbcc09fbc338324', meta_description: 'fc862d75729560fb', testo_seo: 'f853fb6455905172' },
  eleganti: { seo_title: '03d50d7c3d3be5bc', meta_description: 'ee439bed2d42905d', testo_seo: '6f886a3ba8d76ba8' },
  sportive: { seo_title: '7dcf461deea81c6c', meta_description: '730bc0f72cace419', testo_seo: '79317592ece9db3c' },
  cosplay: { seo_title: '07d8bb1e2fe989ee', meta_description: '72b133feda57aca7', testo_seo: '84627321b865795c' },
};

function categoryTexts() {
  const file = path.join(__dirname, '..', 'inhalte', 'seo-inhalte.json');
  if (!fs.existsSync(file)) return 0;
  const fresh = JSON.parse(fs.readFileSync(file, 'utf8')).categories || {};
  let n = 0;
  for (const [slug, old] of Object.entries(CATEGORY_OLD)) {
    const doc = store.find('categories', (c) => c.slug === slug);
    if (!doc || !fresh[slug]) continue;
    const fields = Object.keys(old).filter((k) => fresh[slug][k] && hash(doc[k]) === old[k]);
    if (!fields.length) continue;
    store.put('categories', { ...doc, ...Object.fromEntries(fields.map((k) => [k, fresh[slug][k]])) });
    store.audit('sistema', 'update', 'category', doc.id, { campi: fields });
    n += 1;
  }
  return n;
}

function run() {
  const n = store.transaction(profileTitles);
  if (n) console.log(`Profil-Titel angepasst: ${n}.`);
  const c = store.transaction(categoryTexts);
  if (c) console.log(`Kategorie-Texte angepasst: ${c}.`);
}

module.exports = { run };
