// Lightweight, privacy-safe client state (no sensitive data)

function uuid() {
  if (crypto && crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxxyxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// Anonymous visitor id (persistent). Same value as analytics.getVisitorId(); kept for the existing call sites.
export function getSessionId() {
  let sid = localStorage.getItem('ls_visitor_id') || localStorage.getItem('ls_session_id');
  if (!sid) {
    sid = uuid();
  }
  if (!localStorage.getItem('ls_session_id')) localStorage.setItem('ls_session_id', sid);
  if (!localStorage.getItem('ls_visitor_id')) localStorage.setItem('ls_visitor_id', sid);
  return sid;
}

// 18+ gate
export const isAgeConfirmed = () => localStorage.getItem('ls_age_ok') === '1';
export const confirmAge = () => localStorage.setItem('ls_age_ok', '1');

// cookie consent: null | 'accept' | 'reject'
export const getConsent = () => localStorage.getItem('ls_consent');
export const setConsent = (v) => localStorage.setItem('ls_consent', v);

// discovered secret sides
export function getDiscovered() {
  try { return JSON.parse(localStorage.getItem('ls_discovered') || '[]'); } catch { return []; }
}
export function isDiscovered(slug) { return getDiscovered().includes(slug); }
export function markDiscovered(slug) {
  const d = getDiscovered();
  if (!d.includes(slug)) { d.push(slug); localStorage.setItem('ls_discovered', JSON.stringify(d)); }
}

// per-session message shown flags
function sessionFlags(key) {
  try { return JSON.parse(sessionStorage.getItem(key) || '[]'); } catch { return []; }
}
export function messageShownFor(slug) { return sessionFlags('ls_msg_shown').includes(slug); }
export function markMessageShown(slug) {
  const f = sessionFlags('ls_msg_shown');
  if (!f.includes(slug)) { f.push(slug); sessionStorage.setItem('ls_msg_shown', JSON.stringify(f)); }
}

// track that OF was clicked for a model (session) -> suppress 35s message
export function ofClickedFor(slug) { return sessionFlags('ls_of_clicked').includes(slug); }
export function markOfClicked(slug) {
  const f = sessionFlags('ls_of_clicked');
  if (!f.includes(slug)) { f.push(slug); sessionStorage.setItem('ls_of_clicked', JSON.stringify(f)); }
}
