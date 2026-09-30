import { useEffect, useLayoutEffect, useMemo, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { mediaUrl, track } from '@/lib/api';
import { getSessionId } from '@/lib/session';
import { once, setEntry } from '@/lib/analytics';

/* Detect reduced motion (diagnostic only — it must NOT turn videos into posters
   nor stop the marquee; the rAF engine below runs regardless). */
function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setReduced(mq.matches);
    on();
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return reduced;
}

/* Does THIS browser really support WebM? Safari/iOS returns '' -> use MP4.
   Chromium (incl. headless) returns 'maybe'/'probably' -> WebM first (H.264 may be
   undecodable in headless). This keeps MP4 as the priority source on Safari/iOS. */
const SUPPORTS_WEBM = (() => {
  try {
    const v = document.createElement('video');
    return v.canPlayType('video/webm; codecs="vp8, vp9"') !== '';
  } catch { return false; }
})();

/* ---------------- Tile ---------------- */
function Tile({ item, secret, index, tileW, mgr, sectionInView, onOpen, onVideoView, namesAlways }) {
  const key = `${item.slug}-${index}`;
  const tileRef = useRef(null);
  const vidRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);
  const [touched, setTouched] = useState(false);

  const side = secret ? item.segreto : item.pubblico;
  const vsrc = mediaUrl(side?.video_url || '');
  const poster = mediaUrl(side?.poster_url || item.foto_card || '');

  // iOS Safari: muted/playsInline MUST be set (as properties) BEFORE play()
  const tryPlay = useCallback(() => {
    const v = vidRef.current;
    if (!v) return;
    try { v.muted = true; v.defaultMuted = true; v.playsInline = true; } catch { /* noop */ }
    const p = v.play?.();
    if (p && p.catch) p.catch(() => {});
  }, []);

  // Horizontal visibility -> request/release a play slot (capped).
  // NOTE: video playback is intentionally DECOUPLED from prefers-reduced-motion
  // (videos are muted; reduced motion must never turn them into permanent posters).
  useEffect(() => {
    const el = tileRef.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries[0].isIntersecting;
        if (vis && sectionInView) {
          if (mgr.acquire(key)) setPlaying(true);
        } else {
          mgr.release(key);
          setPlaying(false);
        }
      },
      { root: null, rootMargin: '120px 300px', threshold: 0.02 },
    );
    io.observe(el);
    return () => { io.disconnect(); mgr.release(key); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, sectionInView]);

  // Section out of viewport -> hard pause everything
  useEffect(() => {
    if (!sectionInView) { mgr.release(key); setPlaying(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionInView]);

  // play / pause based on state
  useEffect(() => {
    const v = vidRef.current;
    if (!v) return;
    if (playing) {
      tryPlay();
      onVideoView?.(item.slug);
    } else {
      try { v.pause(); } catch (e) { /* noop */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  // Retry playback when tab returns to foreground (Safari suspends on background)
  useEffect(() => {
    const onVis = () => { if (document.visibilityState === 'visible' && playing) tryPlay(); };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [playing, tryPlay]);

  // Mode switch (public<->secret): reload source but keep playing & keep poster visible (no black)
  useEffect(() => {
    setReady(false);
    const v = vidRef.current;
    if (!v || !playing) return;
    try { v.load(); tryPlay(); } catch (e) { /* noop */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secret]);

  return (
    <button
      ref={tileRef}
      type="button"
      data-testid="pellicola-tile"
      aria-label={`Apri il profilo di ${item.nome_artistico}`}
      onClick={() => onOpen(item, index)}
      onTouchStart={() => setTouched(true)}
      onTouchEnd={() => setTouched(false)}
      className={`ls-tile card-elev group ${secret ? 'secret' : ''} ${touched ? 'touched' : ''}`}
      style={{ width: tileW }}
    >
      {/* poster fallback (behind the video, only visible during loading — never a black frame) */}
      <img className="ls-poster" src={poster} alt={item.nome_artistico} loading="lazy" draggable="false" />

      {playing && vsrc ? (
        <video
          ref={vidRef}
          className={`ls-video ${ready ? 'ready' : ''}`}
          poster={poster}
          muted
          loop
          playsInline
          autoPlay
          preload="auto"
          draggable="false"
          onCanPlay={() => { setReady(true); tryPlay(); }}
          onLoadedData={() => { setReady(true); tryPlay(); }}
          onLoadedMetadata={() => tryPlay()}
          onPlaying={() => setReady(true)}
          onError={() => setReady(false)}
        >
          {/* MP4 priority for Safari/iOS; WebM first only where the browser supports it */}
          {SUPPORTS_WEBM && vsrc.endsWith('.mp4') ? <source src={vsrc.replace('.mp4', '.webm')} type="video/webm" /> : null}
          <source src={vsrc} type="video/mp4" />
        </video>
      ) : null}

      <div className="ls-grade" />
      <div
        className="absolute inset-x-0 bottom-0 p-2.5 text-left"
        style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.72), transparent 72%)' }}
      >
        <div
          className={`transition-opacity duration-200 ${namesAlways ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 group-active:opacity-100'}`}
        >
          <div className="font-serif text-base sm:text-lg leading-none text-white drop-shadow">{item.nome_artistico}</div>
          <div className="text-[10px] gold-text caps-label mt-1">Scopri il suo Lato Segreto</div>
        </div>
      </div>
    </button>
  );
}

/* ---------------- Row (one seamless rAF marquee track) ---------------- */
function Row({ items, secret, tileW, reps, velocita, direction, mgr, sectionInView, pausaTouch, namesAlways, onOpen, onVideoView }) {
  const [slowed, setSlowed] = useState(false);
  const resumeTimer = useRef(null);
  const trackRef = useRef(null);
  const posRef = useRef(0);
  const halfRef = useRef(0);
  const rafRef = useRef(0);
  const lastRef = useRef(0);
  const slowedRef = useRef(false);
  const inViewRef = useRef(sectionInView);

  useEffect(() => { slowedRef.current = slowed; }, [slowed]);
  useEffect(() => { inViewRef.current = sectionInView; }, [sectionInView]);

  // temporary slow-down on press/hover; ALWAYS auto-resumes so it can never get stuck
  const slowNow = useCallback(() => { if (resumeTimer.current) clearTimeout(resumeTimer.current); setSlowed(true); }, []);
  const resumeSoon = useCallback(() => {
    if (resumeTimer.current) clearTimeout(resumeTimer.current);
    resumeTimer.current = setTimeout(() => setSlowed(false), 450);
  }, []);
  useEffect(() => () => { if (resumeTimer.current) clearTimeout(resumeTimer.current); }, []);

  // one "half" = items repeated `reps` times; track = [half, half] -> wrap at -halfWidth (seamless)
  const half = useMemo(() => {
    const arr = [];
    for (let r = 0; r < reps; r += 1) arr.push(...items);
    return arr;
  }, [items, reps]);
  const loop = useMemo(() => [...half, ...half], [half]);

  const halfCount = half.length || 1;
  const durSeconds = Math.max(18, halfCount * velocita); // time to traverse one half

  // measure exact half width (distance to the first child of the 2nd half) for a seamless wrap
  useLayoutEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    const kids = el.children;
    const n = half.length;
    let hw = 0;
    if (kids.length > n && kids[n]) hw = kids[n].offsetLeft - kids[0].offsetLeft;
    if (!hw) hw = el.scrollWidth / 2;
    halfRef.current = hw;
    // keep current position within range; init right-direction offset
    if (direction === 'right') { if (posRef.current === 0) posRef.current = -hw; }
    if (posRef.current <= -hw) posRef.current = 0;
    if (posRef.current > 0) posRef.current = -hw;
    el.style.transform = `translate3d(${posRef.current}px,0,0)`;
  }, [loop, tileW, reps, half.length, direction]);

  // rAF engine — independent of CSS animation, prefers-reduced-motion and video state.
  // Uses transform: translate3d (NOT scrollLeft) so iOS Low Power Mode can't turn it
  // into a manual carousel.
  useEffect(() => {
    const el = trackRef.current;
    if (!el) return undefined;
    lastRef.current = 0;
    const step = (ts) => {
      if (!lastRef.current) lastRef.current = ts;
      let dt = (ts - lastRef.current) / 1000;
      lastRef.current = ts;
      if (dt > 0.05) dt = 0.05; // clamp big gaps (tab throttle)
      const hw = halfRef.current;
      if (hw > 0 && inViewRef.current) {
        const speed = hw / durSeconds; // px per second for a full half
        const f = slowedRef.current ? 0.18 : 1;
        if (direction === 'right') {
          posRef.current += speed * f * dt;
          if (posRef.current >= 0) posRef.current -= hw;
        } else {
          posRef.current -= speed * f * dt;
          if (posRef.current <= -hw) posRef.current += hw;
        }
        el.style.transform = `translate3d(${posRef.current}px,0,0)`;
      }
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
  }, [durSeconds, direction]);

  // Pointer events cover both mouse and touch (incl. iOS Safari). Never a hard freeze.
  const hoverProps = pausaTouch
    ? {
        onPointerDown: slowNow,
        onPointerUp: resumeSoon,
        onPointerCancel: resumeSoon,
        onPointerLeave: resumeSoon,
        onMouseEnter: slowNow,
        onMouseLeave: resumeSoon,
      }
    : {};

  return (
    <div className="relative z-10 overflow-hidden" {...hoverProps}>
      <div ref={trackRef} className="ls-strip-track" data-testid="pellicola-track" style={{ transform: 'translate3d(0,0,0)' }}>
        {loop.map((m, i) => (
          <Tile
            key={`${direction}-${m.slug}-${i}`}
            item={m}
            index={i % (items.length || 1)}
            secret={secret}
            tileW={tileW}
            mgr={mgr}
            sectionInView={sectionInView}
            namesAlways={namesAlways}
            onOpen={onOpen}
            onVideoView={onVideoView}
          />
        ))}
      </div>
    </div>
  );
}

/* ---------------- FilmStrip ---------------- */
export default function FilmStrip({ items, config, secret }) {
  const navigate = useNavigate();
  const reduced = usePrefersReducedMotion();
  const wrapRef = useRef(null);
  const [sectionInView, setSectionInView] = useState(false);
  const [tileW, setTileW] = useState(158);
  const [reps, setReps] = useState(2);

  const cfg = config || {};
  const maxVideo = Math.max(4, Math.min(12, cfg.max_video_attivi || 8));
  const velocita = Math.max(3, Math.min(14, cfg.velocita || 6));
  const namesAlways = !!cfg.nomi_sempre_visibili;
  const pausaTouch = cfg.pausa_su_touch !== false;
  const secondRow = !!cfg.seconda_fila;
  const titolo = cfg.titolo || 'IN MOVIMENTO';
  const sottotitolo = cfg.sottotitolo || 'Una foto non racconta tutto.';

  // active-video cap manager (shared across tiles)
  const mgr = useRef(null);
  if (!mgr.current) {
    const active = new Set();
    const state = { max: maxVideo };
    mgr.current = {
      _state: state,
      acquire(k) {
        if (active.has(k)) return true;
        if (active.size >= state.max) return false;
        active.add(k);
        return true;
      },
      release(k) { active.delete(k); },
    };
  }
  mgr.current._state.max = maxVideo; // keep cap in sync

  // responsive tile width + repeats so a single half always exceeds viewport (seamless, no gap)
  useEffect(() => {
    const recalc = () => {
      const vw = window.innerWidth || 390;
      const w = vw < 640 ? 152 : vw < 1024 ? 168 : 182;
      setTileW(w);
      const base = (items && items.length) || 1;
      const gap = 12;
      const need = Math.ceil((vw + 400) / (base * (w + gap)));
      setReps(Math.max(2, need));
    };
    recalc();
    window.addEventListener('resize', recalc, { passive: true });
    return () => window.removeEventListener('resize', recalc);
  }, [items]);

  // section visibility -> pause the marquee & videos when off-screen
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(
      (e) => setSectionInView(e[0].isIntersecting),
      { threshold: 0.08 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // impression (once per mount when it first enters viewport)
  const impressed = useRef(false);
  useEffect(() => {
    if (sectionInView && !impressed.current) {
      impressed.current = true;
      if (!once(`pellicola_impression:${secret ? 'secret' : 'public'}`)) return;     // once per visit per Home mode
      track({
        tipo: 'pellicola_impression',
        session_id: getSessionId(),
        cta_source: secret ? 'segreto' : 'pubblico',
        meta: { count: (items && items.length) || 0 },
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionInView]);

  // video-view tracking (once per slug per mount)
  const viewed = useRef(new Set());
  const onVideoView = useCallback((slug) => {
    if (viewed.current.has(slug)) return;
    viewed.current.add(slug);
    if (!once(`pellicola_video_view:${slug}`)) return;                             // once per visit per creator (was: per mount)
    track({
      tipo: 'pellicola_video_view',
      model_slug: slug,
      session_id: getSessionId(),
      cta_source: secret ? 'segreto' : 'pubblico',
    });
  }, [secret]);

  const onOpen = useCallback((m, idx) => {
    track({
      tipo: 'pellicola_click_profilo',
      model_slug: m.slug,
      session_id: getSessionId(),
      cta_source: secret ? 'segreto' : 'pubblico',
      meta: { creator: m.nome_artistico, posizione: idx, modalita: secret ? 'segreto' : 'pubblico' },
    });
    setEntry('filmstrip', { position: idx });
    navigate(`/modelle/${m.slug}`);
  }, [navigate, secret]);

  // reversed order copy for the optional second row (opposite direction)
  const itemsRev = useMemo(() => [...(items || [])].reverse(), [items]);

  if (!items || items.length === 0) return null;

  return (
    <section
      ref={wrapRef}
      data-testid="pellicola-section"
      data-reduced-motion={reduced ? '1' : '0'}
      className="relative -mx-4 lg:-mx-8 my-12 sm:my-16 py-8 sm:py-10 overflow-hidden"
      style={secret ? { background: 'linear-gradient(180deg, hsl(350 45% 8% / 0.7), transparent 85%)' } : {}}
    >
      {secret && (
        <div className="secret-ambience" style={{ position: 'absolute', opacity: 0.55 }} aria-hidden="true">
          <div className="blob b1" />
          <div className="blob b2" />
          <div className="beam" />
        </div>
      )}

      <div className="relative z-10 px-4 lg:px-8 mb-5 sm:mb-6">
        <div className="caps-label gold-text mb-1" data-testid="pellicola-title">{titolo}</div>
        <h2 className="font-serif text-2xl sm:text-3xl lg:text-4xl">{sottotitolo}</h2>
      </div>

      <Row
        items={items}
        secret={secret}
        tileW={tileW}
        reps={reps}
        velocita={velocita}
        direction="left"
        mgr={mgr.current}
        sectionInView={sectionInView}
        pausaTouch={pausaTouch}
        namesAlways={namesAlways}
        onOpen={onOpen}
        onVideoView={onVideoView}
      />

      {secondRow && (
        <div className="mt-3">
          <Row
            items={itemsRev}
            secret={secret}
            tileW={tileW}
            reps={reps}
            velocita={velocita}
            direction="right"
            mgr={mgr.current}
            sectionInView={sectionInView}
            pausaTouch={pausaTouch}
            namesAlways={namesAlways}
            onOpen={onOpen}
            onVideoView={onVideoView}
          />
        </div>
      )}
    </section>
  );
}
