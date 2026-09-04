import { useEffect, useRef, useState } from 'react';
import { mediaUrl } from '@/lib/api';

function Layer({ item, active, reduced, grade, visible }) {
  const videoRef = useRef(null);
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (active && visible) { v.play?.().catch(() => {}); } else { try { v.pause?.(); } catch {} }
  }, [active, visible]);

  if (!item || !item.url) return null;
  const src = mediaUrl(item.url);
  const common = {
    className: 'absolute inset-0 h-full w-full object-cover',
    style: {
      objectPosition: 'center 20%',
      opacity: active ? 1 : 0,
      transform: active ? 'scale(1)' : 'scale(1.05)',
      filter: grade ? 'saturate(0.82) contrast(1.06) brightness(0.9) sepia(0.16) hue-rotate(-12deg)' : 'none',
      transition: reduced ? 'opacity 260ms ease' : 'opacity 620ms cubic-bezier(0.2,0.8,0.2,1), transform 900ms cubic-bezier(0.2,0.8,0.2,1)',
    },
  };
  if (item.tipo === 'video') {
    return <video ref={videoRef} src={src} poster={mediaUrl(item.poster)} muted loop playsInline preload="metadata" {...common} />;
  }
  return <img src={src} alt={item.alt || ''} loading="lazy" decoding="async" {...common} />;
}

// Crossfades between a public media item and its secret counterpart.
// Videos autoplay (muted/loop/playsInline) only while in viewport.
export function MediaMorph({ pub, sec, secret, reduced, flash = false, className = '', ratio = '3 / 4' }) {
  const wrapRef = useRef(null);
  const [visible, setVisible] = useState(false);
  const showSec = secret && sec && sec.url;

  useEffect(() => {
    const el = wrapRef.current; if (!el) return;
    const io = new IntersectionObserver((entries) => setVisible(entries[0].isIntersecting), { threshold: 0.25 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div ref={wrapRef} className={`relative overflow-hidden bg-muted/40 ${className}`} style={{ aspectRatio: ratio }}>
      <Layer item={pub} active={!showSec} reduced={reduced} visible={visible} />
      {sec && sec.url && <Layer item={sec} active={showSec} reduced={reduced} grade visible={visible} />}
      {/* transformation flash overlay */}
      <div className="absolute inset-0 pointer-events-none" style={{
        background: 'radial-gradient(circle at 50% 40%, hsl(38 45% 90% / 0.95), hsl(350 40% 40% / 0.2))',
        opacity: flash ? 0.85 : 0,
        transition: flash ? 'opacity 90ms ease' : 'opacity 500ms ease',
      }} />
    </div>
  );
}
