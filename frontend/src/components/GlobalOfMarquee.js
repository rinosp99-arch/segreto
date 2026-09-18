/* Global OnlyFans marquee: premium editorial strip, seamless left->right loop (translate3d, no timers),
   whole strip clickable (new tab). Public = black/champagne/gold; Secret adds bordeaux/violet to border + glow.
   Speed is computed from the real content width so it looks the same on every device. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { track } from '@/lib/api';
import { getSessionId } from '@/lib/session';
import { getAttribution } from '@/lib/attribution';

export const GLOBAL_OF_URL = 'https://onlyfans.com/latosegreto/c28';
const PHRASE_A = 'TUTTE LE MODELLE. UN SOLO LATO SEGRETO.';
const PHRASE_B = 'SCOPRILE SU ONLYFANS';
const SPEED_MOBILE = 50;   // px/s  -> ~23-26s per group on a 390px phone
const SPEED_DESKTOP = 85;  // px/s  -> ~20-22s per group on desktop (3 copies ~1830px)

function Phrase() {
  return (
    <span className="ls-marquee__item">
      <span>{PHRASE_A}</span>
      <span className="ls-marquee__sep" aria-hidden="true">{'\u2726'}</span>
      <span>{PHRASE_B} <span className="ls-marquee__arrow" aria-hidden="true">{'\u2192'}</span></span>
      <span className="ls-marquee__gap" aria-hidden="true">{'\u2726'}</span>
    </span>
  );
}

export function GlobalOfMarquee({ placement = 'home', modelSlug = null, secret = false, className = '' }) {
  const boxRef = useRef(null);
  const probeRef = useRef(null);
  const [copies, setCopies] = useState(2);
  const [duration, setDuration] = useState(22);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!mq) return undefined;
    const on = () => setReduced(!!mq.matches);
    on();
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);

  // enough copies to cover the container (+1 for safety) and a duration that keeps a constant visual speed
  useLayoutEffect(() => {
    const box = boxRef.current; const probe = probeRef.current;
    if (!box || !probe) return undefined;
    const measure = () => {
      const w = box.clientWidth || 0; const pw = probe.getBoundingClientRect().width || 1;
      const n = Math.max(2, Math.ceil(w / pw) + 1);
      setCopies(n);
      const speed = w < 640 ? SPEED_MOBILE : SPEED_DESKTOP;
      setDuration(Math.min(30, Math.max(18, (n * pw) / speed)));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    return () => ro.disconnect();
  }, []);

  const onClick = () => {
    const attr = getAttribution() || {};
    const base = { session_id: getSessionId(), cta_source: `of_global_marquee_${placement}` };
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
      className={`ls-marquee ${reduced ? 'ls-marquee--static' : ''} ${className}`}
      aria-label={`${PHRASE_A} ${PHRASE_B}`}
      data-testid={`of-global-marquee-${placement}`}
      data-placement={placement}
    >
      {/* invisible probe: real width of one phrase */}
      <span ref={probeRef} className="ls-marquee__probe" aria-hidden="true"><Phrase /></span>
      {reduced ? (
        <span className="ls-marquee__static"><Phrase /></span>
      ) : (
        <span className="ls-marquee__track" style={{ animationDuration: `${duration}s` }}>
          <span className="ls-marquee__group">{group}</span>
          <span className="ls-marquee__group" aria-hidden="true">{group}</span>
        </span>
      )}
    </a>
  );
}

export default GlobalOfMarquee;
