// Smaller copies of uploaded images: /api/uploads/<file>?w=640 answers with a WebP of that width (&f=jpg: JPEG,
// for Open Graph). Copies are made once and kept under DATA_DIR/cache/img. Anything unexpected (unknown width,
// video, missing file, sharp not installed) falls through to the original file.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const store = require('./db');

const WIDTHS = [320, 480, 640, 960, 1280, 1600];
const FORMATS = { webp: 'image/webp', jpg: 'image/jpeg' };
const CACHE_DIR = path.join(store.DATA_DIR, 'cache', 'img');
const IMAGE = /\.(jpe?g|png|webp)$/i;

let sharp = null;
try {
  sharp = require('sharp');
  sharp.concurrency(1);
  sharp.cache({ memory: 32 });
  fs.mkdirSync(CACHE_DIR, { recursive: true });
} catch (e) {
  console.warn(`Bildverkleinerung aus (sharp nicht verfügbar: ${e.message}) - Originale werden ausgeliefert.`);
}

// Two lanes, one conversion at a time in each: "demand" for a visitor who is waiting, "warm" for the preparation after
// the start - so a visitor never queues behind hundreds of prepared copies. The same copy is never built twice in parallel.
const running = new Map();
const lanes = { demand: Promise.resolve(), warm: Promise.resolve() };

function build(src, out, w, format, lane) {
  if (running.has(out)) return running.get(out);
  const job = lanes[lane].then(async () => {
    const tmp = `${out}.${process.pid}.tmp`;
    const img = sharp(src).rotate().resize({ width: w, withoutEnlargement: true });
    await (format === 'jpg' ? img.jpeg({ quality: 80, mozjpeg: true }) : img.webp({ quality: 78 })).toFile(tmp);
    fs.renameSync(tmp, out);
  });
  lanes[lane] = job.catch(() => {});
  running.set(out, job);
  job.finally(() => running.delete(out)).catch(() => {});
  return job;
}

// absolute path of the copy for an upload path like "lato-segreto/uploads/x.jpg" (built on demand), or null
async function resized(rel, w, format = 'webp', lane = 'demand') {
  if (!sharp || !WIDTHS.includes(w) || !FORMATS[format] || !IMAGE.test(rel)) return null;
  const src = path.resolve(store.UPLOADS_DIR, rel);
  if (!src.startsWith(store.UPLOADS_DIR + path.sep)) return null;
  let st;
  try { st = fs.statSync(src); } catch { return null; }
  if (!st.isFile()) return null;
  const key = crypto.createHash('sha1').update(`${rel}|${st.size}|${st.mtimeMs}`).digest('hex');
  const out = path.join(CACHE_DIR, `${key}-${w}.${format}`);
  if (!fs.existsSync(out)) await build(src, out, w, format, lane);
  return out;
}

function middleware(req, res, next) {
  if (!req.query.w || (req.method !== 'GET' && req.method !== 'HEAD')) return next();
  const format = req.query.f ? String(req.query.f) : 'webp';
  let rel;
  try { rel = decodeURIComponent(req.path).replace(/^\/+/, ''); } catch { return next(); }
  resized(rel, Number(req.query.w), format).then((file) => {
    if (!file) return next();
    res.set('Cache-Control', 'public, max-age=31536000, immutable');
    res.type(FORMATS[format]).sendFile(file, (err) => { if (err && !res.headersSent) next(); });
  }).catch((e) => {
    console.error(`Bild ${rel} nicht verkleinert: ${e.message}`);
    next();
  });
}

// URL of the smaller copy for HTML written by the server (same rule as imgUrl() in frontend/src/lib/api.js)
function url(src, w, format) {
  if (!src || !src.startsWith('/api/uploads/') || !IMAGE.test(src)) return src || '';
  return `${src}?w=${w}${format ? `&f=${format}` : ''}`;
}

// every uploaded image mentioned anywhere in a document
function uploadsIn(value, found = new Set()) {
  if (typeof value === 'string') { if (value.startsWith('/api/uploads/') && IMAGE.test(value)) found.add(value); }
  else if (value && typeof value === 'object') Object.values(value).forEach((v) => uploadsIn(v, found));
  return found;
}

// After the start: prepare the copies the pages ask for (cards first, then the large pictures of profiles and articles),
// so the first visitor of a page does not wait for them. Copies that exist are skipped, a restart costs nothing.
async function warmUp() {
  if (!sharp) return;
  const models = store.all('models').filter((m) => m.stato === 'pubblicata' && !m.is_deleted);
  const cards = uploadsIn(models.map((m) => [m.foto_card, m.foto_card_teaser]));
  const large = uploadsIn([models, store.all('articles').filter((a) => a.stato === 'pubblicato')]);
  const jobs = [...[...cards].flatMap((u) => [320, 480, 640].map((w) => [u, w])), ...[...large].flatMap((u) => [960, 1280].map((w) => [u, w]))];
  let n = 0;
  for (const [u, w] of jobs) {
    try { if (await resized(u.slice('/api/uploads/'.length), w, 'webp', 'warm')) n += 1; } catch { /* a broken file must not stop the rest */ }
  }
  console.log(`Verkleinerte Bilder bereit (${n} von ${jobs.length}).`);
}

module.exports = { middleware, url, warmUp, WIDTHS };
