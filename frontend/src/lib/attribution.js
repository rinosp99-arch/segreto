// First-party, privacy-safe campaign attribution (session-scoped).
export function captureAttribution() {
  try {
    const p = new URLSearchParams(window.location.search);
    const ref = p.get('ref');
    const fonte = p.get('fonte') || p.get('utm_source');
    // a tagged link: ?ref=<profile> (campaign for one creator) and/or ?fonte=instagram&campagna=bio (any page, also the Home)
    if (ref || fonte) {
      const attr = { ...(ref ? { ref } : {}), fonte: (fonte || 'diretta').toLowerCase().slice(0, 40), campagna: (p.get('campagna') || p.get('utm_campaign') || '-').slice(0, 60) };
      sessionStorage.setItem('ls_attr', JSON.stringify(attr));
      return attr;
    }
  } catch (e) { /* noop */ }
  return getAttribution();
}

export function getAttribution() {
  try { return JSON.parse(sessionStorage.getItem('ls_attr') || 'null'); } catch { return null; }
}
