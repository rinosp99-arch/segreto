// Lightweight, privacy-safe client state (no sensitive data)
import { getVisitorId } from '@/lib/analytics';

// Anonymous visitor id. Same value as analytics.getVisitorId() (permanent only after "Accetta"); kept for the existing call sites.
export const getSessionId = () => getVisitorId();

// 18+ gate
export const isAgeConfirmed = () => localStorage.getItem('ls_age_ok') === '1';
export const confirmAge = () => localStorage.setItem('ls_age_ok', '1');

// cookie consent: null | 'accept' | 'reject'
export const getConsent = () => localStorage.getItem('ls_consent');
export const setConsent = (v) => { localStorage.setItem('ls_consent', v); getVisitorId(); };   // "Rifiuta" drops a stored id at once

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
