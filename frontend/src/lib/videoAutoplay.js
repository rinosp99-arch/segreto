/* Shared inline-autoplay helpers (extracted from the FilmStrip strategy that is proven on iPhone).
   iOS Safari rules we rely on:
   - muted / defaultMuted / playsInline MUST be set as PROPERTIES (and attributes) BEFORE play();
     React renders `muted` as a property only, so we (re)assert it here every time.
   - play() may reject (autoplay policy, Low Power Mode, tab in background): always swallow and retry
     on loadedmetadata / loadeddata / canplay / visibilitychange.
   - MP4 (H.264) must stay the priority source on Safari/iOS: WebM only where the browser really supports it. */
import { useEffect } from 'react';
import { debugLog } from '@/lib/log';

export function primeVideo(v) {
  if (!v) return;
  try {
    v.muted = true;
    v.defaultMuted = true;
    v.playsInline = true;
    if (!v.hasAttribute('muted')) v.setAttribute('muted', '');
    if (!v.hasAttribute('playsinline')) v.setAttribute('playsinline', '');
    if (!v.hasAttribute('webkit-playsinline')) v.setAttribute('webkit-playsinline', '');
  } catch (e) { debugLog('video.prime', e); }
}

export function tryPlayVideo(v) {
  if (!v) return;
  primeVideo(v);
  try {
    const p = v.play?.();
    if (p && p.catch) p.catch((e) => debugLog('video.play', e));   // autoplay refused: expected on some devices, poster stays
  } catch (e) { debugLog('video.play', e); }
}

export function pauseVideo(v) {
  if (!v) return;
  try { v.pause?.(); } catch (e) { debugLog('video.pause', e); }
}

/* Safari suspends media when the tab/app goes to background: retry when it comes back. */
export function useVisibilityRetry(enabled, retry) {
  useEffect(() => {
    if (!enabled) return undefined;
    const onVis = () => { if (document.visibilityState === 'visible') retry(); };
    document.addEventListener('visibilitychange', onVis);
    window.addEventListener('pageshow', onVis);
    return () => {
      document.removeEventListener('visibilitychange', onVis);
      window.removeEventListener('pageshow', onVis);
    };
  }, [enabled, retry]);
}

/* Does THIS browser really support WebM? Safari/iOS returns '' -> MP4 only. */
export const SUPPORTS_WEBM = (() => {
  try {
    const v = document.createElement('video');
    return v.canPlayType('video/webm; codecs="vp8, vp9"') !== '';
  } catch (e) { debugLog('video.canPlayType', e); return false; }
})();
