import { useState, useEffect } from 'react';
import { mediaUrl } from '@/lib/api';

// Lazy image with fade-in + skeleton background, fixed aspect to avoid CLS.
export function MediaImage({ src, alt = '', className = '', style = {}, eager = false }) {
  const [loaded, setLoaded] = useState(false);
  const resolved = mediaUrl(src);
  useEffect(() => { setLoaded(false); }, [resolved]);
  return (
    <div className={`relative overflow-hidden bg-muted/40 ${className}`} style={style}>
      {!loaded && <div className="absolute inset-0 animate-pulse bg-muted/50" />}
      <img
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
