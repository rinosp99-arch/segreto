import { useEffect, useRef } from 'react';
import { mediaUrl } from '@/lib/api';

function Layer({ item, active, reduced, grade }) {
  const videoRef = useRef(null);
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (active) { v.play?.().catch(() => {}); } else { try { v.pause?.(); } catch {} }
  }, [active]);

  if (!item || !item.url) return null;
  const src = mediaUrl(item.url);
  const common = {
    className: 'absolute inset-0 h-full w-full object-cover',
    style: {
      objectPosition: 'center 20%',
      opacity: active ? 1 : 0,
      transform: active ? 'scale(1)' : 'scale(1.04)',
      filter: grade ? 'saturate(0.82) contrast(1.06) brightness(0.9) sepia(0.16) hue-rotate(-12deg)' : 'none',
      transition: reduced ? 'opacity 260ms ease' : 'opacity 620ms cubic-bezier(0.2,0.8,0.2,1), transform 900ms cubic-bezier(0.2,0.8,0.2,1)',
    },
  };

  if (item.tipo === 'video') {
    return (
      <video ref={videoRef} src={src} poster={mediaUrl(item.poster)} muted loop playsInline preload="metadata" {...common} />
    );
  }
  return <img src={src} alt={item.alt || ''} loading="lazy" decoding="async" {...common} />;
}

// Crossfades between a public media item and its secret counterpart.
export function MediaMorph({ pub, sec, secret, reduced, className = '', ratio = '3 / 4' }) {
  const showSec = secret && sec && sec.url;
  return (
    <div className={`relative overflow-hidden bg-muted/40 ${className}`} style={{ aspectRatio: ratio }}>
      <Layer item={pub} active={!showSec} reduced={reduced} />
      {sec && sec.url && <Layer item={sec} active={showSec} reduced={reduced} grade />}
    </div>
  );
}
