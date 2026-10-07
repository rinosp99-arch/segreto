// Public base URL of the site, one place for everything that builds absolute URLs
// (canonical, sitemap, Open Graph, structured data, host redirect, AI responses).
// Order: value stored from the admin/AI interface (config doc "site") -> env PUBLIC_BASE_URL -> host of the request.
const crypto = require('crypto');
const store = require('./db');

// random per process: lets /api/health prove that a domain really points to THIS app before it becomes the base URL
const INSTANCE_ID = crypto.randomBytes(12).toString('hex');

const strip = (u) => String(u || '').trim().replace(/\/+$/, '');

let cache; // undefined = not read yet; the config doc is read once and refreshed on every write
function siteConfig() {
  if (cache === undefined) cache = store.get('config', 'site') || null;
  return cache;
}

// only writer of the config doc "site" (also used by the AI rollback), so the cache can never be stale
function putSiteConfig(doc) {
  if (doc) store.put('config', { ...doc, id: 'site' });
  else store.del('config', 'site');
  cache = undefined;
}

// base URL that was explicitly configured (stored value or env), '' when the site just answers on its request host
function configuredBaseUrl() {
  return strip(siteConfig()?.base_url) || strip(process.env.PUBLIC_BASE_URL);
}

function baseUrl(req) {
  return configuredBaseUrl() || (req ? `${req.protocol}://${req.get('host')}` : '');
}

function baseUrlInfo(req) {
  const cfg = siteConfig();
  if (strip(cfg?.base_url)) return { value: strip(cfg.base_url), source: 'config', updated_at: cfg.updated_at || null };
  if (strip(process.env.PUBLIC_BASE_URL)) return { value: strip(process.env.PUBLIC_BASE_URL), source: 'env', updated_at: null };
  return { value: baseUrl(req), source: 'request', updated_at: null };
}

// Returns { value } (normalised, no trailing slash) or { error } with an Italian message.
function validateBaseUrl(input) {
  const raw = String(input ?? '').trim();
  if (!raw) return { error: 'site.base_url è obbligatorio (es. https://www.esempio.it)' };
  if (/\s/.test(raw)) return { error: 'L\'URL non può contenere spazi' };
  let u;
  try { u = new URL(raw); } catch { return { error: 'URL non valido: serve un URL assoluto, es. https://www.esempio.it' }; }
  if (u.protocol !== 'https:') return { error: 'Solo https:// è consentito' };
  if (u.username || u.password) return { error: 'L\'URL non può contenere credenziali (utente:password@)' };
  if (u.search || raw.includes('?')) return { error: 'L\'URL non può contenere una query (?...)' };
  if (u.hash || raw.includes('#')) return { error: 'L\'URL non può contenere un frammento (#...)' };
  if (u.pathname !== '/' && u.pathname !== '') return { error: 'L\'URL non può contenere un percorso: solo https://dominio' };
  if (u.port && u.port !== '443') return { error: 'Porta non consentita' };
  const host = u.hostname;
  const label = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;
  const labels = host.split('.');
  if (host.length > 253 || labels.length < 2 || !labels.every((l) => label.test(l)) || !/^([a-z]{2,}|xn--[a-z0-9-]+)$/.test(labels[labels.length - 1])) {
    return { error: 'Nome host non valido: serve un dominio pubblico (es. www.esempio.it)' };
  }
  return { value: `https://${host}` };
}

module.exports = { INSTANCE_ID, baseUrl, baseUrlInfo, configuredBaseUrl, validateBaseUrl, siteConfig, putSiteConfig };
