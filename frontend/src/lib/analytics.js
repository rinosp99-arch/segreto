/* LATO SEGRETO — central analytics client (privacy-safe product telemetry).

   ONE place builds the common schema for every event, so no component has to assemble ids / mode / path /
   attribution by hand. Events are queued and shipped in small batches (fetch keepalive, sendBeacon on page hide),
   never blocking the UI. Nothing personal is collected: anonymous random ids only, no fingerprinting, no IP
   (the backend only derives device/browser FAMILY from the user agent).

   IDENTITY
   - visitor_id : anonymous random UUID, persistent (localStorage `ls_visitor_id`). Same value as the historical
                  `ls_session_id`, so old and new data join on the same visitor. Still sent as `session_id` for
                  backward compatibility with legacy dashboards.
   - visit_id   : one per VISIT. Stored in sessionStorage (`ls_visit`, i.e. per browser tab) and rotated when the
                  visitor has been inactive for more than VISIT_TIMEOUT_MIN minutes (30, industry standard) or a new
                  campaign landing (`?ref=`) starts. Everything inside a visit shares the same visit_id and a
                  monotonic `seq`, so the journey can be rebuilt in order.

   COMMON FIELDS added to every event (when meaningful):
   tipo (event name) · visitor_id · visit_id · seq · ts_client · path · mode (public|secret) · model_slug
   entry_source (how the visitor reached the current profile) · profile_pos (n-th distinct profile of the visit)
   ref / fonte / campagna (first-party attribution, session-scoped) · session_id (= visitor_id, legacy)
   The backend adds: timestamp, device, browser, os, source (referrer domain family), country (header/lang only). */

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const TRACK_URL = `${BACKEND_URL}/api/track/batch`;

export const VISIT_TIMEOUT_MIN = 30;
const FLUSH_DELAY_MS = 900;      // small batches: a burst of impressions becomes one request
const FLUSH_MAX = 20;            // flush immediately when this many events are waiting
const QUEUE_CAP = 100;           // never let the queue grow without bound (drop oldest)
const MAX_RETRY = 2;             // limited retry (network error / 5xx), then drop
const ENTRY_TTL_MS = 15000;      // an entry hint must be consumed by the next profile view within 15s
const ONCE_CAP = 600;            // dedup keys kept per visit

const hasWindow = typeof window !== 'undefined';

function uuid() {
  try { if (crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (e) { /* fallthrough */ }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}
function readJson(store, key, fallback) {
  try { const v = JSON.parse(store.getItem(key) || 'null'); return v === null ? fallback : v; } catch { return fallback; }
}
function writeJson(store, key, v) { try { store.setItem(key, JSON.stringify(v)); } catch (e) { /* storage full / private mode */ } }

/* ------------------------------------------------------------------ identity */
export function getVisitorId() {
  if (!hasWindow) return '';
  try {
    let v = localStorage.getItem('ls_visitor_id');
    if (!v) {
      v = localStorage.getItem('ls_session_id') || uuid();     // continuity with the historical id
      localStorage.setItem('ls_visitor_id', v);
    }
    if (!localStorage.getItem('ls_session_id')) localStorage.setItem('ls_session_id', v);
    return v;
  } catch { return ''; }
}

/* External referrer HOST only (e.g. "instagram.com"), captured once at visit start: enough for the source family,
   no full URLs / no paths (privacy). Same-origin referrers are ignored. */
function externalReferrerHost() {
  try {
    const r = document.referrer; if (!r) return '';
    const h = new URL(r).hostname.toLowerCase();
    return h && h !== window.location.hostname ? h : '';
  } catch { return ''; }
}

function newVisit(reason) {
  return { id: uuid(), started: Date.now(), last: Date.now(), seq: 0, profiles: [], reason, ref_host: externalReferrerHost(), n: (readJson(sessionStorage, 'ls_visit', null)?.n || 0) + 1 };
}

/* Visit rule: sessionStorage-scoped (new tab = new visit) + 30 min of inactivity = new visit. */
export function getVisit() {
  if (!hasWindow) return { id: '', seq: 0, profiles: [] };
  let v = readJson(sessionStorage, 'ls_visit', null);
  const now = Date.now();
  if (!v || !v.id || (now - (v.last || 0)) > VISIT_TIMEOUT_MIN * 60 * 1000) {
    v = newVisit(v ? 'timeout' : 'new');
    writeJson(sessionStorage, 'ls_visit', v);
    try { sessionStorage.removeItem('ls_once'); } catch (e) { /* noop */ }
  }
  return v;
}
function saveVisit(v) { writeJson(sessionStorage, 'ls_visit', v); }

/* A campaign landing (?ref=…) starts a fresh visit so the campaign is never mixed with the previous journey. */
export function startCampaignVisit(ref) {
  if (!hasWindow) return;
  const v = readJson(sessionStorage, 'ls_visit', null);
  if (v && v.campaign_ref === ref) return;
  const nv = newVisit('campaign');
  nv.campaign_ref = ref;
  saveVisit(nv);
  try { sessionStorage.removeItem('ls_once'); } catch (e) { /* noop */ }
}

/* ------------------------------------------------------------------ context */
export const currentMode = () => (hasWindow && document.documentElement.classList.contains('theme-secret') ? 'secret' : 'public');
const currentPath = () => (hasWindow ? window.location.pathname : '');
const isProfilePath = (p) => /^\/modelle\/[^/]+/.test(p || currentPath());
export const deviceType = () => {
  if (!hasWindow) return 'unknown';
  const w = window.innerWidth || 0;
  const touch = 'ontouchstart' in window || (navigator.maxTouchPoints || 0) > 0;
  if (w >= 1024 && !touch) return 'desktop';
  if (w >= 768) return touch ? 'tablet' : 'desktop';
  return 'mobile';
};

function attribution() {
  return readJson(sessionStorage, 'ls_attr', null);
}

/* ------------------------------------------------------------------ entry source (attribution inside the site) */
export const ENTRY_SOURCES = ['home_card', 'filmstrip', 'surprise', 'swipe', 'swipe_button', 'related_models', 'direct_profile', 'campaign', 'search', 'category', 'landing'];

/* Called by the element that triggers the navigation, right before navigate()/Link click. */
export function setEntry(src, extra = {}) {
  if (!hasWindow) return;
  writeJson(sessionStorage, 'ls_entry_next', { src, at: Date.now(), ...extra });
}

/* Called once per profile view (ModelProfile mount). Consumes the pending hint, or infers direct/campaign. */
export function beginProfile(slug) {
  const v = getVisit();
  const pending = readJson(sessionStorage, 'ls_entry_next', null);
  try { sessionStorage.removeItem('ls_entry_next'); } catch (e) { /* noop */ }
  let src = null; let extra = {};
  if (pending && pending.src && (Date.now() - (pending.at || 0)) < ENTRY_TTL_MS) {
    src = pending.src;
    extra = { ...pending }; delete extra.src; delete extra.at;
  } else {
    const attr = attribution();
    const firstInVisit = (v.profiles || []).length === 0 && !v.saw_home;
    if (attr && attr.ref && firstInVisit) src = 'campaign';
    else if (v.saw_home) src = 'home_card';          // navigated from Home without a hint (e.g. browser back/forward)
    else src = 'direct_profile';
  }
  const from = v.current_profile && v.current_profile.slug !== slug ? v.current_profile.slug : null;
  if (!v.profiles.includes(slug)) v.profiles.push(slug);
  const profilePos = v.profiles.indexOf(slug) + 1;
  v.current_profile = { slug, src, pos: profilePos, opened_at: Date.now(), from };
  v.profile_views = (v.profile_views || 0) + 1;
  saveVisit(v);
  return { entry_source: src, profile_pos: profilePos, profiles_seen: v.profiles.length, profile_views: v.profile_views, from_model: from, ...extra };
}
export function noteHomeSeen() { const v = getVisit(); v.saw_home = true; saveVisit(v); }
export function currentProfile() { return getVisit().current_profile || null; }
export function secondsSinceProfileOpen() {
  const c = currentProfile();
  return c && c.opened_at ? Math.round((Date.now() - c.opened_at) / 1000) : null;
}

/* Swipe / nav bookkeeping shared by ProfileSwipe and the OF click (was ls_swipe_count / ls_profiles_seen). */
export function noteNavigation(input) {
  const v = getVisit();
  v.swipes = (v.swipes || 0) + 1;
  v.last_nav_input = input;              // 'gesture' | 'button' | 'keyboard'
  saveVisit(v);
  return v.swipes;
}
export function journey() {
  const v = getVisit();
  return { swipes: v.swipes || 0, profiles_seen: (v.profiles || []).length, last_nav_input: v.last_nav_input || null };
}

/* ------------------------------------------------------------------ dedup */
/* once('video_start:vanessa:2:secret') → true the first time within the current visit, false afterwards. */
export function once(key) {
  if (!hasWindow) return true;
  getVisit();                                       // rotates ls_once when the visit rotates
  const seen = readJson(sessionStorage, 'ls_once', []);
  if (seen.includes(key)) return false;
  seen.push(key);
  if (seen.length > ONCE_CAP) seen.splice(0, seen.length - ONCE_CAP);
  writeJson(sessionStorage, 'ls_once', seen);
  return true;
}

/* Impression helper: fires cb once when el is really visible (threshold) — optional dedup key per visit. */
export function observeImpression(el, cb, { threshold = 0.5, key = null, minMs = 300 } = {}) {
  if (!el || typeof IntersectionObserver === 'undefined') return () => {};
  if (key && readJson(sessionStorage, 'ls_once', []).includes(key)) return () => {};
  let timer = null; let done = false;
  const io = new IntersectionObserver((entries) => {
    const on = entries.some((e) => e.isIntersecting && e.intersectionRatio >= threshold);
    if (on && !timer && !done) {
      timer = setTimeout(() => {
        timer = null;
        if (done) return;
        if (key && !once(key)) { done = true; io.disconnect(); return; }
        done = true; io.disconnect(); cb();
      }, minMs);                                    // must stay visible for minMs (no drive-by impressions)
    } else if (!on && timer) { clearTimeout(timer); timer = null; }
  }, { threshold: [threshold] });
  io.observe(el);
  return () => { io.disconnect(); if (timer) clearTimeout(timer); };
}

/* ------------------------------------------------------------------ queue */
let queue = [];
let timer = null;
let listenersInstalled = false;

function build(evt) {
  const v = getVisit();
  v.seq = (v.seq || 0) + 1;
  v.last = Date.now();
  saveVisit(v);
  const attr = attribution() || {};
  const path = currentPath();
  const cur = v.current_profile;
  const onProfile = isProfilePath(path);
  const e = {
    ref: attr.ref, fonte: attr.fonte, campagna: attr.campagna,
    ...evt,
    session_id: getVisitorId(),
    visitor_id: getVisitorId(),
    visit_id: v.id,
    seq: v.seq,
    ts_client: Date.now(),
    path,
    mode: evt.mode || currentMode(),
    device_type: deviceType(),
  };
  if (v.ref_host && !e.referrer) e.referrer = `https://${v.ref_host}/`;   // backend derives `source` (instagram, tiktok, google…)
  if (onProfile && cur) {
    if (!e.model_slug) e.model_slug = cur.slug;
    if (e.entry_source === undefined && cur.slug === e.model_slug) e.entry_source = cur.src;
    if (e.profile_pos === undefined && cur.slug === e.model_slug) e.profile_pos = cur.pos;
  }
  delete e._beacon;
  Object.keys(e).forEach((k) => { if (e[k] === undefined || e[k] === null) delete e[k]; });
  return e;
}

function payload(events) {
  return JSON.stringify({ events, sent_at: Date.now() });
}

function sendBeacon(events) {
  try {
    if (navigator.sendBeacon) return navigator.sendBeacon(TRACK_URL, new Blob([payload(events)], { type: 'application/json' }));
  } catch (e) { /* fallthrough */ }
  return false;
}

async function sendFetch(events) {
  const res = await fetch(TRACK_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: payload(events), keepalive: true, credentials: 'omit' });
  if (res.status >= 500) throw new Error(`track ${res.status}`);
  return true;
}

export function flush({ beacon = false } = {}) {
  if (timer) { clearTimeout(timer); timer = null; }
  if (!queue.length) return;
  const batch = queue.splice(0, FLUSH_MAX);
  if (beacon) {
    if (sendBeacon(batch)) { if (queue.length) flush({ beacon: true }); return; }
    // beacon refused (size/limits): fall back to keepalive fetch
  }
  sendFetch(batch).catch(() => {
    const retry = batch.filter((e) => (e._retry || 0) < MAX_RETRY).map((e) => ({ ...e, _retry: (e._retry || 0) + 1 }));
    if (retry.length) { queue = retry.concat(queue).slice(0, QUEUE_CAP); schedule(3000); }
  });
  if (queue.length) schedule(FLUSH_DELAY_MS);
}

function schedule(ms) {
  if (timer) return;
  timer = setTimeout(() => { timer = null; flush(); }, ms);
}

function installListeners() {
  if (listenersInstalled || !hasWindow) return;
  listenersInstalled = true;
  const onHide = () => flush({ beacon: true });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') onHide(); });
  window.addEventListener('pagehide', onHide);
  window.addEventListener('beforeunload', onHide);
}

/* Burst dedup: the same event for the same target within BURST_MS is one event (React StrictMode double effects,
   double taps, remounts). Milestones/impressions have their own per-visit dedup (once()). */
const BURST_MS = 800;
let lastKey = ''; let lastAt = 0;
function isBurstDuplicate(evt) {
  const key = [evt.tipo, evt.model_slug || '', evt.slot || '', evt.mode || '', evt.valore ?? '', evt.cta_source || '', evt.to_model || ''].join('|');
  const now = Date.now();
  const dup = key === lastKey && (now - lastAt) < BURST_MS;
  lastKey = key; lastAt = now;
  return dup;
}

/* Public API: fire-and-forget. `_beacon: true` forces an immediate beacon flush (unload paths). */
export function track(evt) {
  if (!hasWindow || !evt || !evt.tipo) return;
  try {
    installListeners();
    if (isBurstDuplicate(evt)) return;
    const e = build(evt);
    queue.push(e);
    if (queue.length > QUEUE_CAP) queue.splice(0, queue.length - QUEUE_CAP);
    if (evt._beacon) { flush({ beacon: true }); return; }
    if (queue.length >= FLUSH_MAX) flush(); else schedule(FLUSH_DELAY_MS);
  } catch (e) { /* analytics must never break the site */ }
}

/* Testing / debugging hook (read-only): pending events count. */
export const __pending = () => queue.length;
