// One-off content corrections for a database that already exists (the import only fills an empty one).
// Every step checks the old value first: it runs once and never overwrites what was edited in the admin since.
const store = require('./db');

const clean = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();

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

function run() {
  const n = store.transaction(profileTitles);
  if (n) console.log(`Profil-Titel angepasst: ${n}.`);
}

module.exports = { run };
