// Where the visitors come from (admin dashboard, weekly review): visits per source for a period and the period before.
// A visit = all events with the same visit_id. Its source is, in this order: the tagged link it arrived on
// (?fonte=instagram), the site it came from (referrer host, sent once per visit by the React app), otherwise "direct".
const store = require('./db');

const DAYS = { oggi: 1, '7g': 7, '30g': 30 };

// referrer host -> source family
const FAMILIES = [
  ['instagram', 'Instagram', /(^|\.)instagram\.com$/],
  ['facebook', 'Facebook', /(^|\.)(facebook\.com|fb\.com|fb\.me)$/],
  ['tiktok', 'TikTok', /(^|\.)tiktok\.com$/],
  ['telegram', 'Telegram', /(^|\.)(t\.me|telegram\.org|telegram\.me)$/],
  ['onlyfans', 'OnlyFans', /(^|\.)onlyfans\.com$/],
  ['google', 'Google', /(^|\.)google\.[a-z.]+$/],
  ['bing', 'Bing', /(^|\.)bing\.com$/],
  ['x', 'X / Twitter', /(^|\.)(twitter\.com|x\.com|t\.co)$/],
  ['youtube', 'YouTube', /(^|\.)(youtube\.com|youtu\.be)$/],
  ['reddit', 'Reddit', /(^|\.)reddit\.com$/],
  ['linktree', 'Linktree', /(^|\.)linktr\.ee$/],
];
const NAMES = Object.fromEntries(FAMILIES.map(([key, name]) => [key, name]));
const DIRECT = { key: 'diretto', name: 'Diretto / origine non rilevata' };

const host = (referrer) => { try { return new URL(referrer).hostname.toLowerCase().replace(/^www\./, ''); } catch { return ''; } };
const tag = (s) => String(s || '').trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').slice(0, 40);

function sourceOf(visit) {
  const fonte = tag(visit.fonte);
  if (fonte) return { key: fonte, name: NAMES[fonte] || fonte, tagged: true };
  const h = host(visit.referrer);
  if (!h) return { ...DIRECT, tagged: false };
  const family = FAMILIES.find(([, , re]) => re.test(h));
  return family ? { key: family[0], name: family[1], tagged: false } : { key: h, name: h, tagged: false };
}

const qVisits = store.db.prepare(`
  SELECT COALESCE(NULLIF(visit_id, ''), NULLIF(session_id, ''), 'e' || id) AS v, MIN(ts) AS inizio,
    MAX(json_extract(data, '$.referrer')) AS referrer,
    MAX(NULLIF(json_extract(data, '$.fonte'), 'diretta')) AS fonte, MAX(json_extract(data, '$.campagna')) AS campagna,
    SUM(tipo = 'page_view') AS profili, SUM(tipo = 'of_click') AS click_of,
    SUM(tipo IN ('of_global_marquee_profile_click', 'of_global_marquee_home_click')) AS click_canale
  FROM events WHERE ts >= ? GROUP BY v`);
const qProfiles = store.db.prepare(`
  SELECT model_id, SUM(tipo = 'page_view') AS visite, SUM(tipo = 'of_click') AS click_of
  FROM events WHERE ts >= ? AND model_id IS NOT NULL AND tipo IN ('page_view', 'of_click') GROUP BY model_id`);

const empty = () => ({ visite: 0, profili: 0, click_of: 0, click_canale: 0 });
const add = (sum, v) => { sum.visite += 1; sum.profili += v.profili; sum.click_of += v.click_of; sum.click_canale += v.click_canale; };

function report(range) {
  const days = DAYS[range] || 7;
  const now = new Date();
  // "oggi" = since midnight (as in the other dashboard numbers), compared with the same hours of yesterday
  const start = range === 'oggi' ? new Date(now).setHours(0, 0, 0, 0) : now.getTime() - days * 864e5;
  const length = now.getTime() - start;
  const since = new Date(start).toISOString();
  const before = new Date(start - (range === 'oggi' ? 864e5 : length)).toISOString();
  const beforeEnd = range === 'oggi' ? new Date(now.getTime() - 864e5).toISOString() : since;

  const total = empty();
  const previous = empty();
  const sources = new Map();
  const campaigns = new Map();
  const perDay = new Map();
  for (const v of qVisits.all(before)) {
    const s = sourceOf(v);
    const row = sources.get(s.key) || sources.set(s.key, { chiave: s.key, nome: s.name, ...empty(), marcate: 0, visite_prec: 0 }).get(s.key);
    if (v.inizio >= since) {
      add(total, v); add(row, v);
      if (s.tagged) {
        row.marcate += 1;
        const c = `${s.key}|${tag(v.campagna) || '-'}`;
        const camp = campaigns.get(c) || campaigns.set(c, { fonte: s.name, campagna: tag(v.campagna) || '-', ...empty() }).get(c);
        add(camp, v);
      }
      const day = v.inizio.slice(0, 10);
      perDay.set(day, (perDay.get(day) || 0) + 1);
    } else if (v.inizio < beforeEnd) {
      add(previous, v); row.visite_prec += 1;
    }
  }

  const models = Object.fromEntries(store.all('models').map((m) => [m.id, m]));
  const byVisits = (a, b) => b.visite - a.visite || b.click_of - a.click_of;
  return {
    range, da: since, a: now.toISOString(), totale: total, precedente: previous,
    sorgenti: [...sources.values()].filter((r) => r.visite || r.visite_prec).sort(byVisits),
    campagne: [...campaigns.values()].sort(byVisits),
    giorni: [...perDay.entries()].sort().map(([giorno, visite]) => ({ giorno, visite })),
    top_profili: qProfiles.all(since).filter((r) => models[r.model_id] && r.visite)
      .map((r) => ({ slug: models[r.model_id].slug, nome: models[r.model_id].nome_artistico || models[r.model_id].nome, visite: r.visite, click_of: r.click_of }))
      .sort(byVisits).slice(0, 10),
  };
}

module.exports = { report, sourceOf };
