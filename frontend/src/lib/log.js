/* Dev-only diagnostics for "expected" failures we deliberately swallow at runtime (autoplay refusals, AudioContext
   quirks, storage access). Silent in production, visible while developing. */
export function debugLog(scope, err) {
  if (process.env.NODE_ENV === 'production') return;
  try { console.debug(`[${scope}]`, err && err.message ? err.message : err); } catch { /* console unavailable */ }
}
