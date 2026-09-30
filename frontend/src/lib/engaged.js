/* Engaged time + scroll depth for a profile view (one controller per ModelProfile mount).

   ENGAGED TIME rule: time counts only while ALL of these hold
     - the document is visible (tab in foreground, not minimised)
     - the visitor was active in the last IDLE_MS (pointer / touch / scroll / key / wheel). A muted autoplay grid
       does NOT count as activity: we measure the person, not the player.
   Time is accumulated in intervals (no per-second events) and split by mode (public / secret).
   ONE `profile_engaged` event is sent when the profile view ends (slug change, unmount, page hide via beacon):
     valore = engaged seconds (total), meta = { public_s, secret_s, wall_s, max_scroll }

   SCROLL DEPTH: profile_scroll_25/50/75/100, each at most once per profile view, with the mode at that moment. */
import { track, currentMode } from '@/lib/analytics';

const IDLE_MS = 20000;
const SCROLL_STEPS = [25, 50, 75, 100];

export function startProfileEngagement(slug) {
  if (typeof window === 'undefined') return { stop() {}, setMode() {} };
  const openedAt = Date.now();
  const acc = { public: 0, secret: 0 };
  let activeSince = null;      // ms timestamp when the current active interval started
  let lastActivity = Date.now();
  let idleTimer = null;
  let ended = false;
  let mode = currentMode();
  let maxScroll = 0;
  const scrolled = new Set();

  const isVisible = () => document.visibilityState === 'visible';
  const close = () => { if (activeSince !== null) { acc[mode] += Date.now() - activeSince; activeSince = null; } };
  const open = () => { if (activeSince === null && !ended && isVisible()) activeSince = Date.now(); };
  const armIdle = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => close(), IDLE_MS);     // no activity for IDLE_MS -> stop counting
  };
  let lastTick = 0;
  const onActivity = () => {
    const now = Date.now();
    if (now - lastTick < 1000) return;                  // throttle: listeners are cheap, timers even cheaper
    lastTick = now; lastActivity = now;
    open(); armIdle();
  };
  const onVisibility = () => { if (isVisible()) { if (Date.now() - lastActivity < IDLE_MS) { open(); armIdle(); } } else close(); };

  const onScroll = () => {
    onActivity();
    const doc = document.documentElement;
    const h = Math.max(1, doc.scrollHeight - window.innerHeight);
    const pct = Math.min(100, Math.round(((window.scrollY || doc.scrollTop || 0) / h) * 100));
    if (pct > maxScroll) maxScroll = pct;
    SCROLL_STEPS.forEach((s) => {
      if (pct >= s && !scrolled.has(s)) {
        scrolled.add(s);
        track({ tipo: `profile_scroll_${s}`, model_slug: slug, valore: s, mode: currentMode() });
      }
    });
  };

  const emit = (beacon) => {
    if (ended) return;
    ended = true;
    close();
    if (idleTimer) clearTimeout(idleTimer);
    const pub = Math.round(acc.public / 1000); const sec = Math.round(acc.secret / 1000);
    const wall = Math.round((Date.now() - openedAt) / 1000);
    if (pub + sec === 0 && wall < 2) return;            // bounce with nothing measured: no event, no noise
    track({ tipo: 'profile_engaged', model_slug: slug, valore: pub + sec, meta: { public_s: pub, secret_s: sec, wall_s: wall, max_scroll: maxScroll }, _beacon: beacon });
  };
  const onHide = () => emit(true);

  const opts = { passive: true };
  ['pointerdown', 'pointermove', 'touchstart', 'keydown', 'wheel'].forEach((ev) => window.addEventListener(ev, onActivity, opts));
  window.addEventListener('scroll', onScroll, opts);
  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('pagehide', onHide);
  open(); armIdle();
  const firstScrollCheck = setTimeout(onScroll, 1500);   // short pages: 100% is reached without scrolling

  return {
    /* ModelProfile calls this when Lato Segreto is activated / reverted so the split is exact. */
    setMode(next) { if (next === mode) return; close(); mode = next; open(); },
    stop() {
      emit(false);
      clearTimeout(firstScrollCheck);
      ['pointerdown', 'pointermove', 'touchstart', 'keydown', 'wheel'].forEach((ev) => window.removeEventListener(ev, onActivity, opts));
      window.removeEventListener('scroll', onScroll, opts);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onHide);
    },
  };
}
