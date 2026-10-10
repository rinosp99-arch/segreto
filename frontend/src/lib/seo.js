// Centralized SEO head management (client-side, decoupled from components).

function upsertMeta(attr, key, content) {
  if (content == null) return;
  let el = document.head.querySelector(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
}

function upsertLink(rel, href) {
  if (!href) return;
  let el = document.head.querySelector(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement('link');
    el.setAttribute('rel', rel);
    document.head.appendChild(el);
  }
  el.setAttribute('href', href);
}

// The server writes a complete head for the URL the visitor arrives on and marks it with <meta name="ls-head" content="/path">
// (server/seo.js). That head stays as it is, so search engines read the same before and after JavaScript.
// The mark is dropped as soon as another page is opened: from then on the pages write the head themselves.
function serverHead() {
  const el = document.head.querySelector('meta[name="ls-head"]');
  if (!el) return false;
  if (el.getAttribute('content') === (window.location.pathname.replace(/\/+$/, '') || '/')) return true;
  el.remove();
  return false;
}

export function setSeo({ title, description, canonical, image, type = 'website', jsonLd, noindex = false }) {
  if (serverHead() && !noindex) return;
  if (title) document.title = title;
  if (description) upsertMeta('name', 'description', description);
  upsertMeta('name', 'robots', noindex ? 'noindex,nofollow' : 'index,follow');

  // Open Graph
  upsertMeta('property', 'og:title', title);
  upsertMeta('property', 'og:description', description);
  upsertMeta('property', 'og:type', type);
  if (image) upsertMeta('property', 'og:image', image);
  // canonical = clean URL (origin + pathname, no utm/ref/query/hash) unless explicitly provided by the page
  const url = canonical || `${window.location.origin}${window.location.pathname.replace(/\/+$/, '') || '/'}`;
  upsertMeta('property', 'og:url', url);
  upsertMeta('property', 'og:site_name', 'LATO SEGRETO');

  // Twitter
  upsertMeta('name', 'twitter:card', image ? 'summary_large_image' : 'summary');
  upsertMeta('name', 'twitter:title', title);
  upsertMeta('name', 'twitter:description', description);
  if (image) upsertMeta('name', 'twitter:image', image);

  upsertLink('canonical', url);

  // JSON-LD structured data
  const existing = document.getElementById('ls-jsonld');
  if (existing) existing.remove();
  if (jsonLd) {
    const s = document.createElement('script');
    s.type = 'application/ld+json';
    s.id = 'ls-jsonld';
    s.text = JSON.stringify(jsonLd);
    document.head.appendChild(s);
  }
}

export const SITE = {
  name: 'LATO SEGRETO',
  tagline: 'Il lato che non hai ancora visto',
};

// Phase 14C — SEO state for a dynamic resource that does not exist (profile / category / article / landing).
// The static host always answers HTTP 200 for SPA routes (FRONTEND_HTTP_STATUS = 200); Google's recommended handling for
// JS sites is: noindex + no canonical + real 404 UI (SEO_NOT_FOUND_STATE = NOINDEX + NO_CANONICAL + 404_UI).
export function setNotFoundSeo() {
  const mark = document.head.querySelector('meta[name="ls-head"]');
  if (mark) mark.remove();
  document.title = 'Pagina non trovata | Lato Segreto';
  upsertMeta('name', 'description', 'Pagina non trovata');
  upsertMeta('name', 'robots', 'noindex, follow');
  document.head.querySelectorAll('link[rel="canonical"]').forEach((el) => el.remove());
  const ld = document.getElementById('ls-jsonld');
  if (ld) ld.remove();
  ['og:title', 'og:description', 'og:type', 'og:image', 'og:url'].forEach((p) => { const el = document.head.querySelector(`meta[property="${p}"]`); if (el) el.remove(); });
  ['twitter:card', 'twitter:title', 'twitter:description', 'twitter:image'].forEach((n) => { const el = document.head.querySelector(`meta[name="${n}"]`); if (el) el.remove(); });
}
