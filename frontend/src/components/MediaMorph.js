import { useEffect, useRef, useState, useCallback } from 'react';
import { bigUrl } from '@/lib/api';
import { tryPlayVideo, pauseVideo, primeVideo, useVisibilityRetry } from '@/lib/videoAutoplay';
import { track, once } from '@/lib/analytics';

/* Video telemetry (profile grid): video_impression / video_start / video_25 / video_50 / video_75 / video_complete /
   video_replay — each AT MOST ONCE per (visit, model, slot, media mode). No progress stream: milestones only.
   `video_replay` = the loop wrapped after playing past 80% (the tile was watched more than once). */
function useVideoTelemetry({ enabled, slug, slot, mediaMode }) {
  const st = useRef({ fired: new Set(), prev: 0 });
  const emit = useCallback((ev, extra) => {
    if (!enabled || !slug) return;
    const s = st.current;
    if (s.fired.has(ev)) return;
    s.fired.add(ev);                                   // in-memory short-circuit (onTimeUpdate fires ~4x/s)
    if (!once(`${ev}:${slug}:${slot}:${mediaMode}`)) return;
    track({ tipo: ev, model_slug: slug, slot, mode: mediaMode, meta: { media_mode: mediaMode, ...(extra || {}) } });
  }, [enabled, slug, slot, mediaMode]);
  const onProgress = useCallback((cur, dur) => {
    if (!enabled || !dur || !isFinite(dur)) return;
    const s = st.current;
    if (cur + 1 < s.prev && s.prev > dur * 0.8) emit('video_replay', { dur: Math.round(dur) });
    s.prev = cur;
    const p = cur / dur;
    if (p >= 0.25) emit('video_25');
    if (p >= 0.5) emit('video_50');
    if (p >= 0.75) emit('video_75');
    if (p >= 0.95) emit('video_complete', { dur: Math.round(dur) });
  }, [enabled, emit]);
  return { emit, onProgress };
}

function Layer({ item, active, reduced, grade, visible, impVisible = false, extraFilter, fit = 'cover', objPos = 'center 20%', onNatural, onTime, slug = null, slot = null, mediaMode = 'public' }) {
  const videoRef = useRef(null);
  const [ready, setReady] = useState(false);   // first decoded frame available -> video shown above its poster
  const isVideo = item?.tipo === 'video';
  const wantPlay = isVideo && active && visible;
  const vt = useVideoTelemetry({ enabled: isVideo && !!slug, slug, slot, mediaMode });
  useEffect(() => { if (isVideo && active && impVisible) vt.emit('video_impression'); }, [isVideo, active, impVisible, vt]);

  // Same strategy as the Home FilmStrip (proven on iPhone): prime muted/inline as PROPERTIES, then play(); never throw.
  const tryPlay = useCallback(() => { tryPlayVideo(videoRef.current); }, []);

  // Prime the element as soon as it exists (before iOS evaluates the autoplay attribute).
  useEffect(() => { if (isVideo) primeVideo(videoRef.current); }, [isVideo]);

  useEffect(() => {
    if (!isVideo) return undefined;
    if (wantPlay) tryPlay(); else pauseVideo(videoRef.current);
    return undefined;
  }, [isVideo, wantPlay, tryPlay]);

  // Safari suspends autoplay in background / on pageshow -> retry
  useVisibilityRetry(wantPlay, tryPlay);

  // For videos, derive the native ratio from the poster image right away
  // (video metadata can be slow / blocked, but the poster reflects the frame ratio)
  useEffect(() => {
    if (item?.tipo !== 'video' || !item?.poster || !onNatural) return undefined;
    let alive = true;
    const im = new Image();
    im.onload = () => { if (alive && im.naturalWidth && im.naturalHeight) onNatural(im.naturalWidth, im.naturalHeight); };
    im.src = bigUrl(item.poster);
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item]);

  if (!item || !item.url) return null;
  const src = bigUrl(item.url);   // images: smaller copy; videos: unchanged
  const baseGrade = grade ? 'saturate(0.82) contrast(1.06) brightness(0.9) sepia(0.16) hue-rotate(-12deg)' : '';
  const common = {
    className: `absolute inset-0 h-full w-full object-${fit}`,
    style: {
      objectPosition: fit === 'contain' ? 'center' : objPos,
      opacity: active ? 1 : 0,
      transform: active ? 'scale(1)' : (fit === 'contain' ? 'scale(1.02)' : 'scale(1.05)'),
      filter: `${baseGrade} ${extraFilter || ''}`.trim() || 'none',
      transition: reduced ? 'opacity 300ms ease' : 'opacity 900ms cubic-bezier(0.2,0.8,0.2,1), transform 1300ms cubic-bezier(0.2,0.8,0.2,1), filter 600ms ease',
    },
  };
  if (item.tipo === 'video') {
    const poster = bigUrl(item.poster);
    return (
      <>
        {/* poster behind the video: visible while loading / if playback is refused -> never a black tile (FilmStrip pattern) */}
        {poster ? (
          <img
            src={poster}
            alt={item.alt || ''}
            loading={active ? 'eager' : 'lazy'}
            decoding="async"
            draggable="false"
            data-testid="tile-video-poster"
            {...common}
          />
        ) : null}
        <video
          ref={videoRef}
          poster={poster || undefined}
          autoPlay={active}
          muted
          loop
          playsInline
          preload={active ? 'auto' : 'none'}   /* only the ACTIVE side loads: iOS has a small budget of concurrent decoders */
          draggable="false"
          data-testid="tile-video"
          data-state={ready ? 'ready' : 'loading'}
          onLoadedMetadata={(e) => { onNatural?.(e.target.videoWidth, e.target.videoHeight); if (wantPlay) tryPlay(); }}
          onLoadedData={() => { setReady(true); if (wantPlay) tryPlay(); }}
          onCanPlay={() => { setReady(true); if (wantPlay) tryPlay(); }}
          onPlaying={() => { setReady(true); if (active) vt.emit('video_start'); }}
          onError={() => setReady(false)}
          onTimeUpdate={(e) => { if (active) { onTime?.(e.target.currentTime, e.target.duration); vt.onProgress(e.target.currentTime, e.target.duration); } }}
          {...common}
          style={{ ...common.style, opacity: active && ready ? 1 : 0 }}
        >
          {/* MP4 (H.264) only: guaranteed playable on Safari/iOS; currentSrc is always the .mp4 */}
          <source src={src} type="video/mp4" />
        </video>
      </>
    );
  }
  return (
    <img
      src={src}
      alt={item.alt || ''}
      loading="lazy"
      decoding="async"
      onLoad={(e) => onNatural?.(e.target.naturalWidth, e.target.naturalHeight)}
      {...common}
    />
  );
}

export function MediaMorph({ pub, sec, secret, reduced, effect = 'flash', delay = 0, ambient = false, className = '', ratio = '3 / 4', fit = 'cover', maxVh = null, adaptRatio = false, onTime, children, modelSlug = null, slot = null }) {
  const wrapRef = useRef(null);
  const [visible, setVisible] = useState(false);
  const [impVisible, setImpVisible] = useState(false);   // >=50% in viewport: the impression threshold (telemetry only)
  const [shown, setShown] = useState(secret);
  const [fx, setFx] = useState(false);
  const [pubRatio, setPubRatio] = useState(null);
  const [secRatio, setSecRatio] = useState(null);

  useEffect(() => {
    const el = wrapRef.current; if (!el) return undefined;
    const io = new IntersectionObserver((e) => setVisible(e[0].isIntersecting), { threshold: 0.2 });
    io.observe(el);
    if (!modelSlug) return () => io.disconnect();
    const io2 = new IntersectionObserver((e) => setImpVisible(e[0].isIntersecting && e[0].intersectionRatio >= 0.5), { threshold: [0.5] });
    io2.observe(el);
    return () => { io.disconnect(); io2.disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const d = reduced ? Math.min(delay, 120) : delay;
    const t1 = setTimeout(() => {
      setShown(secret);
      if (!reduced) { setFx(true); setTimeout(() => setFx(false), 420); }
    }, d);
    return () => clearTimeout(t1);
  }, [secret, delay, reduced]);

  const showSec = shown && sec && sec.url;
  const blurFilter = (fx && effect === 'blur') ? 'blur(14px)' : '';
  const glitch = (fx && effect === 'glitch') ? { transform: 'translateX(1.5px) skewX(-1deg)', filter: 'hue-rotate(20deg)' } : {};

  // object-fit: contain adds dark bands (no crop). By default the grid keeps a FIXED ratio
  // (uniform tiles); only when adaptRatio=true the container adopts the media's native ratio.
  const containerFit = fit === 'contain';
  const activeRatio = showSec ? (secRatio || pubRatio) : (pubRatio || secRatio);
  const effRatio = (adaptRatio && containerFit && activeRatio) ? activeRatio : ratio;

  const wrapStyle = {
    aspectRatio: effRatio,
    ...glitch,
    transition: 'transform 120ms ease, filter 120ms ease, box-shadow 600ms ease, aspect-ratio 400ms ease',
  };
  if (containerFit) {
    // Uniform tile: the CONTAINER always takes the full grid cell (same width/height/ratio as the photo tiles);
    // only the media inside uses object-fit: contain (no crop, no zoom, dark bands on the tile background).
    // NOTE: no `margin: auto` here — on a grid item it becomes shrink-to-fit and, with only absolutely
    // positioned children, the tile collapsed to ~2×3px (row 3 video tiles invisible).
    wrapStyle.background = '#050206';
    wrapStyle.width = '100%';
    if (maxVh) wrapStyle.maxHeight = `${maxVh}vh`;
  }

  return (
    <div
      ref={wrapRef}
      className={`relative overflow-hidden ${containerFit ? '' : 'bg-muted/40'} ${showSec && ambient ? 'secret-tile' : ''} ${className}`}
      style={wrapStyle}
      data-testid="media-tile"
    >
      <Layer item={pub} active={!showSec} reduced={reduced} visible={visible} impVisible={impVisible} fit={fit} onTime={onTime} slug={modelSlug} slot={slot} mediaMode="public" onNatural={(w, h) => { if (w && h) setPubRatio(`${w} / ${h}`); }} />
      {sec && sec.url && <Layer item={sec} active={showSec} reduced={reduced} grade visible={visible} impVisible={impVisible} fit={fit} onTime={onTime} slug={modelSlug} slot={slot} mediaMode="secret" extraFilter={showSec ? blurFilter : ''} onNatural={(w, h) => { if (w && h) setSecRatio(`${w} / ${h}`); }} />}

      {/* persistent stage-light sheen on secret tiles */}
      {showSec && ambient && !reduced && <div className="secret-sheen" />}

      {/* flash */}
      {(effect === 'flash') && (
        <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(circle at 50% 40%, hsl(38 45% 92% / 0.95), hsl(350 40% 40% / 0.15))', opacity: fx ? 0.85 : 0, transition: fx ? 'opacity 90ms ease' : 'opacity 400ms ease' }} />
      )}
      {/* fade to black */}
      {(effect === 'fadeblack') && (
        <div className="absolute inset-0 pointer-events-none" style={{ background: '#050206', opacity: fx ? 1 : 0, transition: fx ? 'opacity 110ms ease' : 'opacity 480ms ease' }} />
      )}
      {/* light sweep */}
      {(effect === 'sweep') && (
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          <div style={{ position: 'absolute', top: '-30%', bottom: '-30%', width: '45%', transform: fx ? 'translateX(260%) rotate(8deg)' : 'translateX(-160%) rotate(8deg)', background: 'linear-gradient(90deg, transparent, hsl(40 60% 85% / 0.55), transparent)', transition: fx ? 'transform 480ms cubic-bezier(0.2,0.8,0.2,1)' : 'none', opacity: fx ? 1 : 0 }} />
        </div>
      )}

      {/* custom overlay (e.g. teaser finale) */}
      {children}
    </div>
  );
}
