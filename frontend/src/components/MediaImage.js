import { useState, useEffect, useRef } from 'react';
import { imgUrl, imgSrcSet } from '@/lib/api';

// width of a creator card in the grids (2 columns on phones up to 5 on wide screens)
const CARD_SIZES = '(min-width: 1280px) 224px, (min-width: 1024px) 25vw, (min-width: 768px) 33vw, 50vw';

// Lazy image with fade-in + skeleton background, fixed aspect to avoid CLS.
export function MediaImage({ src, alt = '', className = '', style = {}, eager = false, sizes = CARD_SIZES }) {
  const [loaded, setLoaded] = useState(false);
  const imgRef = useRef(null);
  const resolved = imgUrl(src, 640);
  const srcSet = imgSrcSet(src);
  // Fix: an image served from cache can fire `load` BEFORE this effect runs; resetting to false would hide it forever.
  useEffect(() => { const el = imgRef.current; setLoaded(Boolean(el && el.complete && el.naturalWidth > 0)); }, [resolved]);
  return (
    <div className={`relative overflow-hidden bg-muted/40 ${className}`} style={style}>
      {!loaded && <div className="absolute inset-0 animate-pulse bg-muted/50" />}
      <img
        ref={imgRef}
        sizes={srcSet ? sizes : undefined}
        srcSet={srcSet}
        src={resolved}
        alt={alt}
        loading={eager ? 'eager' : 'lazy'}
        decoding="async"
        onLoad={() => setLoaded(true)}
        className={`h-full w-full object-cover transition-opacity duration-700 ${loaded ? 'opacity-100' : 'opacity-0'}`}
        style={{ objectPosition: 'center 20%' }}
      />
    </div>
  );
}
