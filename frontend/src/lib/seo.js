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

export function setSeo({ title, description, canonical, image, type = 'website', jsonLd, noindex = false }) {
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
