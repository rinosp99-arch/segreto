/* Global OnlyFans marquee: premium editorial strip, seamless left->right loop, whole strip clickable (new tab).
   Public = black/champagne/gold; Secret adds bordeaux/violet to border + glow.
   MOVEMENT ENGINE = requestAnimationFrame + translate3d (like FilmStrip): independent from CSS animations, so it keeps
   scrolling on iPhone/Safari even with "Reduce Motion" (prefers-reduced-motion: reduce -> slightly slower, never static),
   Low Power Mode, and it resumes after background -> foreground (visibilitychange / pageshow). Single loop, no timers.
   Speed is computed from the real content width so it looks the same on every device. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { track } from '@/lib/api';
import { getSessionId } from '@/lib/session';
import { getAttribution } from '@/lib/attribution';
import { observeImpression } from '@/lib/analytics';

export const GLOBAL_OF_URL = 'https://onlyfans.com/latosegreto/c28';
const PHRASE_A = 'TUTTE LE MODELLE. UN SOLO LATO SEGRETO.';
const PHRASE_B = 'SCOPRILE SU ONLYFANS';
const SPEED_MOBILE = 50;   // px/s  -> ~23-26s per group on a 390px phone
const SPEED_DESKTOP = 100;  // px/s  -> ~20-22s per group on desktop (3 copies ~1830px)
const REDUCED_MOTION_FACTOR = 0.6;   // prefers-reduced-motion: keep scrolling, just a little slower (never static)

function Phrase() {
  return (
    <span className="ls-marquee__item">
      <span className="ls-marquee__soft">{PHRASE_A}</span>
      <span className="ls-marquee__sep" aria-hidden="true">{'\u2726'}</span>
      {/* the actionable part: brighter, bolder, with a discreet external-link mark and the "go" arrow */}
      <span className="ls-marquee__cta">
        {PHRASE_B}
        <span className="ls-marquee__ext" aria-hidden="true">{'\u2197'}</span>
        <span className="ls-marquee__arrow" aria-hidden="true">{'\u2192'}</span>
      </span>
      <span className="ls-marquee__gap" aria-hidden="true">{'\u2726'}</span>
    </span>
  );
}

export function GlobalOfMarquee({ placement = 'home', modelSlug = null, secret = false, className = '' }) {
  const boxRef = useRef(null);
  const probeRef = useRef(null);
  const trackRef = useRef(null);
  const groupRef = useRef(null);
  const [copies, setCopies] = useState(2);
  const [reduced, setReduced] = useState(false);
  const speedRef = useRef(SPEED_DESKTOP);   // px/s
  const groupWRef = useRef(0);              // width of one group (half of the track)
  const posRef = useRef(0);                 // current translateX (from -groupW to 0, wraps)
  const rafRef = useRef(0);
  const lastRef = useRef(0);
  const reducedRef = useRef(false);

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!mq) return undefined;
    const on = () => { reducedRef.current = !!mq.matches; setReduced(!!mq.matches); };
    on();
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);

  // enough copies to cover the container (+1 for safety) and a constant visual speed per device class
  useLayoutEffect(() => {
    const box = boxRef.current; const probe = probeRef.current;
    if (!box || !probe) return undefined;
    const measure = () => {
      const w = box.clientWidth || 0; const pw = probe.getBoundingClientRect().width || 1;
      setCopies(Math.max(2, Math.ceil(w / pw) + 1));
      speedRef.current = w < 640 ? SPEED_MOBILE : SPEED_DESKTOP;
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    return () => ro.disconnect();
  }, []);

  // real width of one group (the track holds two identical groups): re-measured when copies change / on resize
  useLayoutEffect(() => {
    const g = groupRef.current; const el = trackRef.current;
    if (!g || !el) return undefined;
    const measure = () => {
      const gw = g.getBoundingClientRect().width || 0;
      if (gw > 0) {
        groupWRef.current = gw;
        if (posRef.current > 0 || posRef.current < -gw) posRef.current = -gw;      // keep in range after a resize
        if (posRef.current === 0) posRef.current = -gw;                            // start with the track fully covering the strip
        el.style.transform = `translate3d(${posRef.current}px,0,0)`;
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(g);
    return () => ro.disconnect();
  }, [copies]);

  // rAF engine: LEFT -> RIGHT, seamless wrap, dt clamp for tab throttling, restart on pageshow / visibilitychange.
  useEffect(() => {
    const el = trackRef.current;
    if (!el) return undefined;
    let alive = true;
    const step = (ts) => {
      if (!alive) return;
      if (!lastRef.current) lastRef.current = ts;
      let dt = (ts - lastRef.current) / 1000;
      lastRef.current = ts;
      if (dt > 0.05) dt = 0.05;
      const gw = groupWRef.current;
      if (gw > 0) {
        const speed = speedRef.current * (reducedRef.current ? REDUCED_MOTION_FACTOR : 1);
        posRef.current += speed * dt;
        if (posRef.current >= 0) posRef.current -= gw;
        el.style.transform = `translate3d(${posRef.current}px,0,0)`;
      }
      rafRef.current = requestAnimationFrame(step);
    };
    const start = () => {
      if (!alive) return;
      cancelAnimationFrame(rafRef.current);      // never two loops
      lastRef.current = 0;
      rafRef.current = requestAnimationFrame(step);
    };
    const onVis = () => { if (document.visibilityState === 'visible') start(); };
    start();
    document.addEventListener('visibilitychange', onVis);
    window.addEventListener('pageshow', start);
    window.addEventListener('focus', start);
    return () => {
      alive = false;
      cancelAnimationFrame(rafRef.current);
      document.removeEventListener('visibilitychange', onVis);
      window.removeEventListener('pageshow', start);
      window.removeEventListener('focus', start);
    };
  }, []);

  // of_global_marquee_impression: strip really visible (>=50% for 300ms), once per visit per placement / model / mode
  useEffect(() => observeImpression(boxRef.current, () => {
    const attr = getAttribution() || {};
    track({ tipo: 'of_global_marquee_impression', model_slug: modelSlug || undefined, placement, mode: secret ? 'secret' : 'public', cta_source: `of_global_marquee_${placement}`, meta: { mode: secret ? 'SECRET' : 'PUBLIC', ref: attr.ref || null, fonte: attr.fonte || null, campagna: attr.campagna || null } });
  }, { threshold: 0.5, key: `marquee_imp:${placement}:${modelSlug || '-'}:${secret ? 'secret' : 'public'}` }), [placement, modelSlug, secret]);

  const [flash, setFlash] = useState(null);   // {x, y, id}: soft glow where the strip was touched
  const onPointerDown = (e) => {
    if (e.pointerType === 'mouse') return;
    const r = e.currentTarget.getBoundingClientRect();
    const id = Date.now();
    setFlash({ x: e.clientX - r.left, y: e.clientY - r.top, id });
    window.setTimeout(() => setFlash((f) => (f && f.id === id ? null : f)), 520);
  };

  const onClick = () => {
    const attr = getAttribution() || {};
    const base = { session_id: getSessionId(), cta_source: `of_global_marquee_${placement}`, placement, mode: secret ? 'secret' : 'public' };
    if (placement === 'profile') {
      track({ tipo: 'of_global_marquee_profile_click', model_slug: modelSlug, ...base, meta: { mode: secret ? 'SECRET' : 'PUBLIC', ref: attr.ref || null, fonte: attr.fonte || null, campagna: attr.campagna || null } });
    } else {
      track({ tipo: 'of_global_marquee_home_click', ...base, meta: { mode: secret ? 'SECRET' : 'PUBLIC', ref: attr.ref || null, fonte: attr.fonte || null, campagna: attr.campagna || null } });
    }
  };

  const group = Array.from({ length: copies }).map((_, i) => <Phrase key={i} />);
  return (
    <a
      ref={boxRef}
      href={GLOBAL_OF_URL}
      target="_blank"
      rel="noopener noreferrer"
      onClick={onClick}
      onPointerDown={onPointerDown}
      className={`ls-marquee ${reduced ? 'ls-marquee--reduced' : ''} ${className}`}
      aria-label={`${PHRASE_A} ${PHRASE_B}`}
      data-testid={`of-global-marquee-${placement}`}
      data-placement={placement}
    >
      {/* invisible probe: real width of one phrase */}
      <span ref={probeRef} className="ls-marquee__probe" aria-hidden="true"><Phrase /></span>
      {/* glass light sweep (every ~9s) + touch flash */}
      <span className="ls-marquee__sweep" aria-hidden="true" />
      {flash && <span className="ls-marquee__flash" aria-hidden="true" style={{ left: flash.x, top: flash.y }} />}
      <span ref={trackRef} className="ls-marquee__track" style={{ transform: 'translate3d(0,0,0)' }}>
        <span ref={groupRef} className="ls-marquee__group">{group}</span>
        <span className="ls-marquee__group" aria-hidden="true">{group}</span>
      </span>
    </a>
  );
}

export default GlobalOfMarquee;
