/* Profile-to-profile navigation (swipe / arrows): published-only ring in the Home default order, circular.
   Keeps only what the gesture needs (slug, name, card image) — never the full profiles. */
import { getModels, mediaUrl } from '@/lib/api';

let ringCache = null;          // [{ slug, nome_artistico, foto_card }]
let ringPromise = null;
let ringAt = 0;
const RING_TTL = 5 * 60 * 1000;

export async function getRing() {
  const fresh = ringCache && (Date.now() - ringAt) < RING_TTL;
  if (fresh) return ringCache;
  if (!ringPromise) {
    ringPromise = getModels({ limit: 500 })
      .then((d) => {
        // /api/models returns published models only, already sorted by `ordine` (Home "Tutte")
        ringCache = (d.items || []).map((m) => ({ slug: m.slug, nome_artistico: m.nome_artistico || m.nome, foto_card: m.foto_card || m.foto_copertina || '' }));
        ringAt = Date.now();
        return ringCache;
      })
      .catch(() => ringCache || [])
      .finally(() => { ringPromise = null; });
  }
  return ringPromise;
}

/* Circular neighbours: last -> first, first -> last. null when the slug is not a published model (e.g. admin preview). */
export function neighborsOf(ring, slug) {
  if (!ring || ring.length < 2) return { prev: null, next: null };
  const i = ring.findIndex((m) => m.slug === slug);
  if (i < 0) return { prev: null, next: null };
  return { prev: ring[(i - 1 + ring.length) % ring.length], next: ring[(i + 1) % ring.length] };
}

export function preloadCard(m) {
  if (!m || !m.foto_card) return;
  try { const im = new Image(); im.decoding = 'async'; im.src = mediaUrl(m.foto_card); } catch { /* noop */ }
}

/* Mode carry-over between profiles: set right before navigate(), consumed once by the next ModelProfile mount.
   Public -> public, Secret -> the new model opens directly in ITS Lato Segreto (audio continuity handled by sound.js). */
let carry = null;
export function setCarry(c) { carry = { ...c, at: Date.now() }; }
export function peekCarry() { return carry && (Date.now() - carry.at) < 8000 ? carry : null; }
export function consumeCarry() { const c = peekCarry(); carry = null; return c; }

/* Session counters for attribution: how many profiles a visitor sees (and swipes) before the OnlyFans click. */
function readJson(key, fallback) { try { return JSON.parse(sessionStorage.getItem(key) || 'null') ?? fallback; } catch { return fallback; } }
function writeJson(key, v) { try { sessionStorage.setItem(key, JSON.stringify(v)); } catch { /* noop */ } }

export function noteProfileSeen(slug) {
  const seen = readJson('ls_profiles_seen', []);
  if (!seen.includes(slug)) { seen.push(slug); writeJson('ls_profiles_seen', seen); }
  return seen.length;
}
export function bumpSwipe() {
  const n = (readJson('ls_swipe_count', 0) || 0) + 1;
  writeJson('ls_swipe_count', n);
  return n;
}
export function journeyMeta() {
  return { profiles_seen: (readJson('ls_profiles_seen', []) || []).length, swipes: readJson('ls_swipe_count', 0) || 0 };
}
