import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { mediaUrl, track } from '@/lib/api';
import { getSessionId } from '@/lib/session';

/* Detect reduced motion preference */
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

/* ---------------- Tile ---------------- */
function Tile({ item, secret, index, tileW, mgr, sectionInView, reduced, onOpen, onVideoView, namesAlways }) {
  const key = `${item.slug}-${index}`;
  const tileRef = useRef(null);
  const vidRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);
  const [touched, setTouched] = useState(false);

  const side = secret ? item.segreto : item.pubblico;
  const vsrc = mediaUrl(side?.video_url || '');
  const poster = mediaUrl(side?.poster_url || item.foto_card || '');

  // Horizontal visibility -> request/release a play slot (capped)
  useEffect(() => {
    const el = tileRef.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries[0].isIntersecting;
        if (vis && sectionInView && !reduced) {
          if (mgr.acquire(key)) setPlaying(true);
        } else {
          mgr.release(key);
          setPlaying(false);
        }
      },
      { root: null, rootMargin: '120px 260px', threshold: 0.05 },
    );
    io.observe(el);
    return () => { io.disconnect(); mgr.release(key); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, sectionInView, reduced]);

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
      const p = v.play?.();
      if (p && p.catch) p.catch(() => {});
      onVideoView?.(item.slug);
    } else {
      try { v.pause(); } catch (e) { /* noop */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  // Mode switch (public<->secret): reload source but keep playing & keep poster visible (no black)
  useEffect(() => {
    setReady(false);
    const v = vidRef.current;
    if (!v || !playing) return;
    try { v.load(); const p = v.play?.(); if (p && p.catch) p.catch(() => {}); } catch (e) { /* noop */ }
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
      {/* poster fallback (always present, never a black frame) */}
      <img className="ls-poster" src={poster} alt={item.nome_artistico} loading="lazy" draggable="false" />

      {playing && vsrc ? (
        <video
          ref={vidRef}
          className={`ls-video ${ready ? 'ready' : ''}`}
          src={vsrc}
          poster={poster}
          muted
          loop
          playsInline
          autoPlay
          preload="auto"
          draggable="false"
          onCanPlay={() => setReady(true)}
          onPlaying={() => setReady(true)}
          onError={() => setReady(false)}
        />
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

/* ---------------- Row (one seamless marquee track) ---------------- */
function Row({ items, secret, tileW, reps, velocita, direction, mgr, sectionInView, reduced, pausaTouch, namesAlways, onOpen, onVideoView }) {
  const [paused, setPaused] = useState(false);

  // one "half" = items repeated `reps` times; track = [half, half] -> animate to -50% seamlessly
  const half = useMemo(() => {
    const arr = [];
    for (let r = 0; r < reps; r += 1) arr.push(...items);
    return arr;
  }, [items, reps]);
  const loop = useMemo(() => [...half, ...half], [half]);

  const halfCount = half.length || 1;
  const dur = Math.max(24, halfCount * velocita);

  const hoverProps = pausaTouch
    ? {
        onMouseEnter: () => setPaused(true),
        onMouseLeave: () => setPaused(false),
        onTouchStart: () => setPaused(true),
        onTouchEnd: () => setPaused(false),
      }
    : {};

  const cls = [
    'ls-strip-track',
    direction === 'right' ? 'rev' : '',
    (paused || !sectionInView) ? 'paused' : '',
  ].join(' ');

  return (
    <div className="relative z-10 overflow-hidden" {...hoverProps}>
      <div className={cls} style={{ '--strip-dur': `${dur}s` }} data-testid="pellicola-track">
        {loop.map((m, i) => (
          <Tile
            key={`${direction}-${m.slug}-${i}`}
            item={m}
            index={i % (items.length || 1)}
            secret={secret}
            tileW={tileW}
            mgr={mgr}
            sectionInView={sectionInView}
            reduced={reduced}
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

  // section visibility -> pause when off-screen
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(
      (e) => setSectionInView(e[0].isIntersecting),
      { threshold: 0.12 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // impression (once per mount when it first enters viewport)
  const impressed = useRef(false);
  useEffect(() => {
    if (sectionInView && !impressed.current) {
      impressed.current = true;
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
    navigate(`/modelle/${m.slug}`);
  }, [navigate, secret]);

  // reversed order copy for the optional second row (opposite direction)
  const itemsRev = useMemo(() => [...(items || [])].reverse(), [items]);

  if (!items || items.length === 0) return null;

  return (
    <section
      ref={wrapRef}
      data-testid="pellicola-section"
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
        reduced={reduced}
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
            reduced={reduced}
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
