// First-party, privacy-safe campaign attribution (session-scoped).
export function captureAttribution() {
  try {
    const p = new URLSearchParams(window.location.search);
    const ref = p.get('ref');
    if (ref) {
      const attr = { ref, fonte: p.get('fonte') || 'diretta', campagna: p.get('campagna') || '-' };
      sessionStorage.setItem('ls_attr', JSON.stringify(attr));
      return attr;
    }
  } catch (e) { /* noop */ }
  return getAttribution();
}

export function getAttribution() {
  try { return JSON.parse(sessionStorage.getItem('ls_attr') || 'null'); } catch { return null; }
}
