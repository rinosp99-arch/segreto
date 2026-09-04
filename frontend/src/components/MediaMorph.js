import { useEffect, useRef, useState } from 'react';
import { mediaUrl } from '@/lib/api';

function Layer({ item, active, reduced, grade, visible, extraFilter }) {
  const videoRef = useRef(null);
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (active && visible) { v.play?.().catch(() => {}); } else { try { v.pause?.(); } catch {} }
  }, [active, visible]);

  if (!item || !item.url) return null;
  const src = mediaUrl(item.url);
  const baseGrade = grade ? 'saturate(0.82) contrast(1.06) brightness(0.9) sepia(0.16) hue-rotate(-12deg)' : '';
  const common = {
    className: 'absolute inset-0 h-full w-full object-cover',
    style: {
      objectPosition: 'center 20%',
      opacity: active ? 1 : 0,
      transform: active ? 'scale(1)' : 'scale(1.05)',
      filter: `${baseGrade} ${extraFilter || ''}`.trim() || 'none',
      transition: reduced ? 'opacity 300ms ease' : 'opacity 900ms cubic-bezier(0.2,0.8,0.2,1), transform 1300ms cubic-bezier(0.2,0.8,0.2,1), filter 600ms ease',
    },
  };
  if (item.tipo === 'video') {
    return <video ref={videoRef} src={src} poster={mediaUrl(item.poster)} autoPlay muted loop playsInline preload="metadata" {...common} />;
  }
  return <img src={src} alt={item.alt || ''} loading="lazy" decoding="async" {...common} />;
}

export function MediaMorph({ pub, sec, secret, reduced, effect = 'flash', delay = 0, ambient = false, className = '', ratio = '3 / 4' }) {
  const wrapRef = useRef(null);
  const [visible, setVisible] = useState(false);
  const [shown, setShown] = useState(secret);
  const [fx, setFx] = useState(false);

  useEffect(() => {
    const el = wrapRef.current; if (!el) return;
    const io = new IntersectionObserver((e) => setVisible(e[0].isIntersecting), { threshold: 0.2 });
    io.observe(el);
    return () => io.disconnect();
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

  return (
    <div ref={wrapRef} className={`relative overflow-hidden bg-muted/40 ${showSec && ambient ? 'secret-tile' : ''} ${className}`} style={{ aspectRatio: ratio, ...glitch, transition: 'transform 120ms ease, filter 120ms ease, box-shadow 600ms ease' }} data-testid="media-tile">
      <Layer item={pub} active={!showSec} reduced={reduced} visible={visible} />
      {sec && sec.url && <Layer item={sec} active={showSec} reduced={reduced} grade visible={visible} extraFilter={showSec ? blurFilter : ''} />}

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
    </div>
  );
}
