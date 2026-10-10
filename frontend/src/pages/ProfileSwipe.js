/* Horizontal swipe between profiles (mobile: finger, desktop: mouse drag + discreet arrows + keyboard).
   The whole profile page follows the gesture; the next/previous creator shows through underneath; past the
   threshold the page slides out and the new profile slides in. Layout of the profile page is untouched:
   this is a transparent wrapper around <ModelProfile />. Public/Secret mode is carried over (see lib/profileNav). */
import { useEffect, useRef, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import ModelProfile from '@/pages/ModelProfile';
import { getRing, neighborsOf, preloadCard, setCarry } from '@/lib/profileNav';
import { track, imgUrl } from '@/lib/api';
import { getSessionId } from '@/lib/session';
import { noteNavigation, setEntry, currentProfile, secondsSinceProfileOpen } from '@/lib/analytics';
import { debugLog } from '@/lib/log';

const THRESHOLD = 0.32;      // fraction of the viewport width
const LOCK_PX = 12;          // movement before deciding horizontal vs vertical
const OUT_MS = 240;
const IN_MS = 320;

const isSecretNow = () => document.documentElement.classList.contains('theme-secret');

/* Public / Secret follows the <html class="theme-secret"> toggled by the profile page (no coupling with its state). */
function useSecretMode() {
  const [secret, setSecret] = useState(isSecretNow());
  useEffect(() => {
    const mo = new MutationObserver(() => setSecret(isSecretNow()));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => mo.disconnect();
  }, []);
  return secret;
}

/* Keeps the navigator above other fixed bottom layers (timed CTA bar, cookie banner) without touching them. */
function useBottomOffset() {
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const measure = () => {
      let h = 0;
      document.querySelectorAll('[data-testid="cta-timed"], [data-testid="cookie-banner"]').forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.height > 0 && r.bottom > window.innerHeight - 48) h = Math.max(h, window.innerHeight - r.top);   // any layer anchored to the bottom edge
      });
      setOffset(h);
    };
    measure();
    const mo = new MutationObserver(() => window.requestAnimationFrame(measure));
    mo.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('resize', measure);
    return () => { mo.disconnect(); window.removeEventListener('resize', measure); };
  }, []);
  return offset;
}

export default function ProfileSwipe() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [ring, setRing] = useState([]);
  const [x, setX] = useState(0);                 // current translation (px)
  const [dragging, setDragging] = useState(false);
  const [anim, setAnim] = useState(null);        // 'out' | 'in' | null
  const [dir, setDir] = useState(null);          // 'next' | 'prev' (target shown underneath)
  const [hoverArrows, setHoverArrows] = useState(false);
  const g = useRef(null);                        // gesture state
  const swiped = useRef(false);
  const busy = useRef(false);
  const secretMode = useSecretMode();
  const bottomOffset = useBottomOffset();

  useEffect(() => { let alive = true; getRing().then((r) => { if (alive) setRing(r); }); return () => { alive = false; }; }, []);
  const { prev, next } = neighborsOf(ring, slug);
  useEffect(() => { preloadCard(prev); preloadCard(next); }, [prev, next]);

  const vw = () => Math.max(320, window.innerWidth || 390);
  const target = dir === 'next' ? next : dir === 'prev' ? prev : null;
  const progress = Math.min(1, Math.abs(x) / vw());

  /* input: 'gesture' (finger / mouse drag) | 'button' (arrows, ‹ ⇆ SCORRI › pill) | 'keyboard' */
  const go = useCallback((direction, input = 'gesture') => {
    const t = direction === 'next' ? next : prev;
    if (!t || busy.current) return;
    busy.current = true;
    const secret = isSecretNow();
    setDir(direction);
    setDragging(false);
    setAnim('out');
    setX(direction === 'next' ? -vw() : vw());
    window.setTimeout(() => {
      // GESTURE -> profile_swipe_next/previous · BUTTONS / keyboard -> profile_nav_next_click/prev_click
      // (the arrival is the next profile's page_view with entry_source swipe | swipe_button — no duplicate arrival event)
      const swipes = noteNavigation(input);
      const cur = currentProfile();
      const gesture = input === 'gesture';
      const tipo = gesture ? (direction === 'next' ? 'profile_swipe_next' : 'profile_swipe_previous') : (direction === 'next' ? 'profile_nav_next_click' : 'profile_nav_prev_click');
      track({ tipo, model_slug: slug, session_id: getSessionId(), from_model: slug, to_model: t.slug, input, mode: secret ? 'secret' : 'public', profile_pos: cur?.pos, valore: secondsSinceProfileOpen(), meta: { to: t.slug, from: slug, direction, mode: secret ? 'secret' : 'public', swipes, input } });
      setEntry(gesture ? 'swipe' : 'swipe_button', { direction, input });
      setCarry({ secret, via: gesture ? 'swipe' : 'swipe_button', direction });
      navigate(`/modelle/${t.slug}`);
      try { window.scrollTo({ top: 0, behavior: 'instant' }); } catch (err) { debugLog('swipe.scroll', err); window.scrollTo(0, 0); }
      // incoming: start slightly offset on the opposite side, then settle
      setAnim('in');
      setX(direction === 'next' ? vw() * 0.35 : -vw() * 0.35);
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
        setAnim('settle');
        setX(0);
        window.setTimeout(() => { setAnim(null); setDir(null); busy.current = false; }, IN_MS + 20);
      }));
    }, OUT_MS);
  }, [next, prev, slug, navigate]);

  // ---- pointer gesture with directional lock (touch-action: pan-y lets the browser own vertical scroll)
  const onDown = (e) => {
    if (busy.current || e.button > 0) return;
    if (!prev && !next) return;
    g.current = { x0: e.clientX, y0: e.clientY, lock: null, id: e.pointerId, type: e.pointerType };
    swiped.current = false;
  };
  const onMove = (e) => {
    const s = g.current; if (!s || s.id !== e.pointerId) return;
    const dx = e.clientX - s.x0; const dy = e.clientY - s.y0;
    if (!s.lock) {
      if (Math.abs(dx) < LOCK_PX && Math.abs(dy) < LOCK_PX) return;
      s.lock = Math.abs(dx) > Math.abs(dy) * 1.25 ? 'h' : 'v';   // horizontal must clearly dominate
      if (s.lock === 'h') {
        setDragging(true);
        try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch (err) { debugLog('swipe.capture', err); }
      }
    }
    if (s.lock !== 'h') return;
    swiped.current = true;
    const d = dx < 0 ? 'next' : 'prev';
    if ((d === 'next' && !next) || (d === 'prev' && !prev)) { setX(dx * 0.15); setDir(null); return; }   // rubber band when no target
    setDir(d);
    setX(dx);
  };
  const finish = (e) => {
    const s = g.current; if (!s || (e && s.id !== e.pointerId)) return;
    g.current = null;
    if (s.lock !== 'h') { setDragging(false); return; }
    const commit = Math.abs(x) > vw() * THRESHOLD && ((x < 0 && next) || (x > 0 && prev));
    setDragging(false);
    if (commit) go(x < 0 ? 'next' : 'prev');
    else { setAnim('settle'); setX(0); window.setTimeout(() => { setAnim(null); setDir(null); }, 280); }
    window.setTimeout(() => { swiped.current = false; }, 60);
  };
  const onClickCapture = (e) => { if (swiped.current) { e.preventDefault(); e.stopPropagation(); } };

  // keyboard (desktop)
  useEffect(() => {
    const onKey = (e) => {
      if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      if (e.key === 'ArrowRight') go('next', 'keyboard');
      if (e.key === 'ArrowLeft') go('prev', 'keyboard');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go]);

  const moving = dragging || anim !== null || x !== 0;
  const pageStyle = moving ? {
    transform: `translate3d(${x}px, 0, 0) scale(${1 - progress * 0.04})`,
    opacity: anim === 'in' ? 0.55 : 1 - progress * 0.22,
    transition: dragging || anim === 'in' ? 'none' : anim === 'out' ? `transform ${OUT_MS}ms cubic-bezier(0.2,0.8,0.2,1), opacity ${OUT_MS}ms ease` : `transform ${IN_MS}ms cubic-bezier(0.2,0.8,0.2,1), opacity ${IN_MS}ms ease`,
    willChange: 'transform, opacity',
  } : undefined;   // at rest: no transform, so the profile's fixed overlays (CTA, envelope, blackout) behave normally

  const showUnder = target && (dragging || anim === 'out');
  const underOpacity = anim === 'out' ? 1 : Math.min(1, progress * 2.2);

  return (
    <div
      className="relative"
      style={{ touchAction: 'pan-y', userSelect: dragging ? 'none' : undefined, WebkitUserSelect: dragging ? 'none' : undefined }}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      onClickCapture={onClickCapture}
      onDragStart={(e) => e.preventDefault()}   /* desktop: native image/link drag would cancel the pointer gesture */
      onMouseEnter={() => setHoverArrows(true)}
      onMouseLeave={() => setHoverArrows(false)}
      data-testid="profile-swipe"
    >
      {/* target creator glimpsed underneath during the gesture */}
      {showUnder && (
        <div className="fixed inset-0 z-0 pointer-events-none overflow-hidden" style={{ opacity: underOpacity, transition: dragging ? 'none' : 'opacity 200ms ease' }} data-testid="swipe-underlay">
          {target.foto_card && (
            <img src={imgUrl(target.foto_card, 640)} alt="" className="absolute inset-0 h-full w-full object-cover" style={{ objectPosition: 'center 20%', filter: 'blur(14px) brightness(0.45) saturate(0.85)', transform: `scale(${1.08 - progress * 0.04})` }} />
          )}
          <div className="absolute inset-0" style={{ background: 'linear-gradient(180deg, rgba(5,2,6,0.35), rgba(5,2,6,0.75))' }} />
          <div className={`absolute inset-x-0 top-1/2 -translate-y-1/2 flex flex-col items-center gap-2 px-6 ${dir === 'next' ? 'text-right' : 'text-left'}`}>
            <div className="caps-label text-[10px]" style={{ color: 'hsl(var(--primary))', letterSpacing: '0.28em' }} data-testid="swipe-indicator">
              {dir === 'next' ? 'PROSSIMA \u2192' : '\u2190 PRECEDENTE'}
            </div>
            <div className="font-serif text-3xl sm:text-5xl leading-none text-center" style={{ color: 'hsl(38 40% 92%)', textShadow: '0 2px 24px rgba(0,0,0,0.6)' }}>{target.nome_artistico}</div>
          </div>
        </div>
      )}

      <div className="relative z-10" style={pageStyle} data-testid="profile-swipe-page">
        <ModelProfile />
      </div>

      {/* desktop: discreet arrows, only when useful (ring > 1), visible on hover / focus, never affecting the layout */}
      {(prev || next) && (
        <>
          <button type="button" onClick={() => go('prev', 'button')} aria-label="Modella precedente" data-testid="profile-prev-arrow"
            className="hidden sm:flex fixed left-3 lg:left-6 top-1/2 -translate-y-1/2 z-30 h-11 w-11 items-center justify-center rounded-full glass border border-border/60 text-muted-foreground hover:text-foreground focus-visible:opacity-100"
            style={{ opacity: hoverArrows ? 0.72 : 0.18, transition: 'opacity 250ms ease, transform 160ms ease' }}>
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button type="button" onClick={() => go('next', 'button')} aria-label="Prossima modella" data-testid="profile-next-arrow"
            className="hidden sm:flex fixed right-3 lg:right-6 top-1/2 -translate-y-1/2 z-30 h-11 w-11 items-center justify-center rounded-full glass border border-border/60 text-muted-foreground hover:text-foreground focus-visible:opacity-100"
            style={{ opacity: hoverArrows ? 0.72 : 0.18, transition: 'opacity 250ms ease, transform 160ms ease' }}>
            <ChevronRight className="h-5 w-5" />
          </button>
        </>
      )}

      {/* Fixed floating navigator: tells the visitor profiles can be browsed (tap arrows or swipe). Pure UI layer:
          no layout change. Champagne/gold in Lato Pubblico, bordeaux/violet in Lato Segreto; the arrow of the
          swipe direction lights up softly while dragging. Sits above the timed CTA / cookie banner when present. */}
      {(prev || next) && (() => {
        const gold = { border: 'hsl(var(--gold) / 0.55)', glow: 'hsl(var(--champagne) / 0.22)', text: 'hsl(var(--champagne))' };
        const wine = { border: 'hsl(350 55% 55% / 0.7)', glow: 'hsl(285 45% 40% / 0.35)', text: 'hsl(38 40% 90%)' };
        const c = secretMode ? wine : gold;
        const lit = (side) => (dragging || anim === 'out') && dir === side;
        const arrowStyle = (side) => ({ color: c.text, opacity: lit(side) ? 1 : 0.7, textShadow: lit(side) ? `0 0 12px ${c.text}` : 'none', transform: lit(side) ? 'scale(1.18)' : 'scale(1)', transition: 'opacity 180ms ease, transform 180ms ease, text-shadow 180ms ease' });
        return (
          <div
            className="fixed left-1/2 -translate-x-1/2 z-[50] pointer-events-none"
            style={{ bottom: `calc(env(safe-area-inset-bottom, 0px) + ${12 + bottomOffset}px)`, transition: 'bottom 240ms ease' }}
            data-testid="profile-nav-pill"
          >
            <div
              className="pointer-events-auto flex items-center gap-1 rounded-full glass"
              style={{
                padding: '4px 6px',
                background: 'rgba(5, 2, 6, 0.62)',
                border: `1px solid ${c.border}`,
                boxShadow: `0 0 0 1px rgba(255,255,255,0.03) inset, 0 0 18px ${c.glow}, 0 8px 24px rgba(0,0,0,0.35)`,
                transition: 'border-color 500ms ease, box-shadow 500ms ease',
              }}
            >
              <button type="button" onClick={() => go('prev', 'button')} aria-label="Modella precedente" data-testid="profile-nav-prev"
                className="flex items-center gap-1 h-9 min-w-9 px-2.5 rounded-full text-base leading-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/60 active:scale-95"
                style={arrowStyle('prev')}>
                <span aria-hidden="true">{"\u2039"}</span>
                <span className="hidden sm:inline caps-label text-[10px]">Precedente</span>
              </button>
              <span className="flex items-center gap-1.5 px-2 caps-label text-[10px] select-none" style={{ color: c.text, opacity: 0.8, letterSpacing: '0.24em' }} data-testid="profile-nav-hint">
                <span aria-hidden="true" style={{ fontSize: '13px', letterSpacing: 0 }}>{"\u21c6"}</span> Scorri
              </span>
              <button type="button" onClick={() => go('next', 'button')} aria-label="Prossima modella" data-testid="profile-nav-next"
                className="flex items-center gap-1 h-9 min-w-9 px-2.5 rounded-full text-base leading-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/60 active:scale-95"
                style={arrowStyle('next')}>
                <span className="hidden sm:inline caps-label text-[10px]">Prossima</span>
                <span aria-hidden="true">{"\u203a"}</span>
              </button>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
