// Server-side SEO: every public URL is answered with real HTML (title, description, canonical, Open Graph,
// JSON-LD and a readable content snapshot inside #root). React replaces the snapshot when it starts.
const fs = require('fs');
const path = require('path');
const store = require('./db');
const { arr } = require('./content');

const SITE = 'LATO SEGRETO';
const HOME_TITLE = 'LATO SEGRETO — Il lato che non hai ancora visto';
const HOME_DESC = 'Creator premium con un lato pubblico elegante e un lato segreto tutto da svelare. Scopri, incuriosisciti, premi.';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clean = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const cut = (s, n = 160) => { const t = clean(s); return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t; };
const stripTags = (html) => clean(String(html || '').replace(/<[^>]+>/g, ' '));

const published = () => store.all('models').filter((m) => m.stato === 'pubblicata' && !m.is_deleted).sort((a, b) => (a.ordine || 0) - (b.ordine || 0));
const categories = () => store.all('categories').filter((c) => c.stato === 'pubblicata').sort((a, b) => (a.ordine || 0) - (b.ordine || 0));
const articles = () => store.all('articles').filter((a) => a.stato === 'pubblicato')
  .sort((a, b) => String(b.data_pubblicazione || '').localeCompare(String(a.data_pubblicazione || '')));
const name = (m) => clean(m.nome_artistico || m.nome);

function baseUrl(req) {
  return (process.env.PUBLIC_BASE_URL || `${req.protocol}://${req.get('host')}`).replace(/\/+$/, '');
}
const abs = (base, url) => (!url ? '' : /^https?:\/\//.test(url) ? url : `${base}${url.startsWith('/') ? '' : '/'}${url}`);

const modelList = (items) => `<ul>${items.map((m) =>
  `<li><a href="/modelle/${esc(m.slug)}">${m.foto_card ? `<img src="${esc(m.foto_card)}" alt="${esc(name(m))}" width="300" height="400" loading="lazy">` : ''}<strong>${esc(name(m))}</strong>${m.frase ? ` — ${esc(clean(m.frase))}` : ''}</a></li>`).join('')}</ul>`;
const categoryNav = () => `<nav><h2>Categorie</h2><ul>${categories().map((c) => `<li><a href="/categorie/${esc(c.slug)}">${esc(c.nome)}</a></li>`).join('')}</ul></nav>`;

const LEGAL = {
  privacy: 'Privacy', cookie: 'Cookie', termini: 'Termini e condizioni', '18-plus': 'Solo per maggiorenni (18+)',
};

// Returns { status, title, description, image, type, noindex, jsonLd, body } for a path, or a 404 page.
function pageFor(pathname, base) {
  const p = decodeURIComponent(pathname).replace(/\/+$/, '') || '/';
  let m;

  if (p === '/') {
    const models = published();
    return {
      title: HOME_TITLE, description: HOME_DESC,
      image: models[0]?.foto_card,
      jsonLd: { '@context': 'https://schema.org', '@type': 'WebSite', name: SITE, url: base },
      body: `<h1>${esc(SITE)}</h1><p>${esc(HOME_DESC)}</p><section><h2>Le creator</h2>${modelList(models)}</section>${categoryNav()}`,
    };
  }

  if ((m = p.match(/^\/modelle\/([^/]+)$/))) {
    const doc = published().find((x) => x.slug === m[1]);
    if (!doc) return null;
    const seo = doc.seo || {};
    const title = clean(seo.title) || `${name(doc)} | ${SITE}`;
    const description = cut(seo.meta_description || doc.bio);
    const related = published().filter((x) => x.slug !== doc.slug && arr(x.categorie).some((c) => arr(doc.categorie).includes(c))).slice(0, 4);
    const cats = categories().filter((c) => arr(doc.categorie).includes(c.slug));
    return {
      title, description, image: clean(seo.og_image) || doc.foto_card, type: 'profile', noindex: seo.indexable === false,
      jsonLd: {
        '@context': 'https://schema.org', '@type': 'ProfilePage',
        mainEntity: { '@type': 'Person', name: name(doc), description: cut(doc.bio, 300), image: abs(base, doc.foto_card) },
      },
      body: `<article><h1>${esc(name(doc))}</h1>${doc.frase ? `<p><em>${esc(clean(doc.frase))}</em></p>` : ''}`
        + `${doc.foto_copertina ? `<img src="${esc(doc.foto_copertina)}" alt="${esc(clean(seo.alt_default) || name(doc))}">` : ''}`
        + `<p>${esc(clean(doc.bio))}</p>`
        + `${cats.length ? `<p>Categorie: ${cats.map((c) => `<a href="/categorie/${esc(c.slug)}">${esc(c.nome)}</a>`).join(', ')}</p>` : ''}`
        + `${arr(doc.tag).length ? `<p>${arr(doc.tag).map((t) => esc(t)).join(' · ')}</p>` : ''}</article>`
        + `${related.length ? `<section><h2>Potrebbero piacerti</h2>${modelList(related)}</section>` : ''}`,
    };
  }

  if ((m = p.match(/^\/categorie\/([^/]+)$/))) {
    const cat = categories().find((c) => c.slug === m[1]);
    if (!cat) return null;
    const items = published().filter((x) => arr(x.categorie).includes(cat.slug));
    return {
      title: clean(cat.seo_title) || `${cat.nome} | ${SITE}`,
      description: cut(cat.meta_description || cat.descrizione || `${cat.nome}: le creator di ${SITE}.`),
      image: cat.immagine || items[0]?.foto_card, noindex: cat.indicizzabile === false,
      jsonLd: {
        '@context': 'https://schema.org', '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Inizio', item: base },
          { '@type': 'ListItem', position: 2, name: cat.nome, item: `${base}/categorie/${cat.slug}` },
        ],
      },
      body: `<h1>${esc(cat.nome)}</h1>${cat.descrizione ? `<p>${esc(clean(cat.descrizione))}</p>` : ''}${modelList(items)}${cat.testo_seo ? `<section>${cat.testo_seo}</section>` : ''}${categoryNav()}`,
    };
  }

  if (p === '/articoli') {
    const list = articles();
    return {
      title: `Rivista | ${SITE}`, description: 'Approfondimenti, guide e storie dal mondo LATO SEGRETO.',
      body: `<h1>Rivista</h1><ul>${list.map((a) => `<li><a href="/articoli/${esc(a.slug)}">${esc(a.titolo)}</a>${a.estratto ? `<p>${esc(cut(a.estratto, 220))}</p>` : ''}</li>`).join('')}</ul>`,
    };
  }

  if ((m = p.match(/^\/articoli\/([^/]+)$/))) {
    const a = articles().find((x) => x.slug === m[1]);
    if (!a) return null;
    return {
      title: clean(a.seo_title) || `${a.titolo} | ${SITE}`, description: cut(a.meta_description || a.estratto || stripTags(a.contenuto)),
      image: a.og_image || a.immagine_principale, type: 'article', noindex: a.indicizzabile === false,
      jsonLd: {
        '@context': 'https://schema.org', '@type': 'Article', headline: a.titolo, image: abs(base, a.immagine_principale),
        datePublished: a.data_pubblicazione, dateModified: a.data_aggiornamento || a.data_pubblicazione,
        author: { '@type': 'Organization', name: SITE }, publisher: { '@type': 'Organization', name: SITE },
      },
      body: `<article><h1>${esc(a.titolo)}</h1>${a.contenuto || ''}</article>`,
    };
  }

  const legal = p.slice(1);
  if (LEGAL[legal]) return { title: `${LEGAL[legal]} | ${SITE}`, description: `${LEGAL[legal]} — ${SITE}`, body: `<h1>${esc(LEGAL[legal])}</h1>` };

  if ((m = p.match(/^\/([^/]+)$/))) {
    const l = store.find('landings', (x) => x.slug === m[1] && (x.stato === 'pubblicata' || x.stato === 'published'));
    if (l) {
      return {
        title: clean(l.seo_title || l.titolo) || SITE, description: cut(l.meta_description || l.sottotitolo || HOME_DESC),
        body: `<h1>${esc(l.titolo || l.slug)}</h1>${l.contenuto ? `<div>${l.contenuto}</div>` : ''}`,
      };
    }
  }
  return null;
}

function render(template, page, url, base) {
  const noindex = page.noindex;
  const image = abs(base, page.image);
  const head = [
    `<title>${esc(page.title)}</title>`,
    `<meta name="description" content="${esc(page.description)}" />`,
    `<meta name="robots" content="${noindex ? 'noindex,follow' : 'index,follow'}" />`,
    noindex ? '' : `<link rel="canonical" href="${esc(url)}" />`,
    `<meta property="og:title" content="${esc(page.title)}" />`,
    `<meta property="og:description" content="${esc(page.description)}" />`,
    `<meta property="og:type" content="${esc(page.type || 'website')}" />`,
    `<meta property="og:url" content="${esc(url)}" />`,
    `<meta property="og:site_name" content="${SITE}" />`,
    image ? `<meta property="og:image" content="${esc(image)}" />` : '',
    `<meta name="twitter:card" content="${image ? 'summary_large_image' : 'summary'}" />`,
    page.jsonLd ? `<script type="application/ld+json" id="ls-jsonld">${JSON.stringify(page.jsonLd).replace(/</g, '\\u003c')}</script>` : '',
  ].filter(Boolean).join('\n        ');
  return template
    .replace(/<title>[\s\S]*?<\/title>/, '')
    .replace(/<meta name="description"[^>]*>/, '')
    .replace('</head>', `        ${head}\n    </head>`)
    .replace('<div id="root"></div>', `<div id="root"><div class="seo-snapshot">${page.body || ''}</div></div>`);
}

let templateCache = null;
function template(frontendDir) {
  if (!templateCache || process.env.NODE_ENV !== 'production') templateCache = fs.readFileSync(path.join(frontendDir, 'index.html'), 'utf8');
  return templateCache;
}

function htmlHandler(frontendDir) {
  return (req, res) => {
    const base = baseUrl(req);
    const tpl = template(frontendDir);
    res.set('Cache-Control', 'no-cache');
    if (req.path.startsWith('/admin')) {
      return res.type('html').send(tpl.replace('</head>', '<meta name="robots" content="noindex,nofollow" /></head>'));
    }
    const page = pageFor(req.path, base);
    if (!page) {
      const nf = { title: `Pagina non trovata | ${SITE}`, description: 'Pagina non trovata', noindex: true, body: '<h1>Pagina non trovata</h1><p><a href="/">Torna alla home</a></p>' };
      return res.status(404).type('html').send(render(tpl, nf, base + req.path, base));
    }
    const url = base + (req.path.replace(/\/+$/, '') || '/');
    res.type('html').send(render(tpl, page, url, base));
  };
}

function sitemap(req, res) {
  const base = baseUrl(req);
  const urls = [
    { loc: `${base}/`, lastmod: new Date().toISOString().slice(0, 10), pr: '1.0' },
    ...published().filter((m) => m.seo?.indexable !== false).map((m) => ({ loc: `${base}/modelle/${m.slug}`, lastmod: (m.updated_at || m.data_pubblicazione || '').slice(0, 10), pr: '0.9' })),
    ...categories().filter((c) => c.indicizzabile !== false).map((c) => ({ loc: `${base}/categorie/${c.slug}`, pr: '0.8' })),
    { loc: `${base}/articoli`, pr: '0.6' },
    ...articles().filter((a) => a.indicizzabile !== false).map((a) => ({ loc: `${base}/articoli/${a.slug}`, lastmod: (a.data_aggiornamento || a.data_pubblicazione || '').slice(0, 10), pr: '0.7' })),
    ...store.all('landings').filter((l) => l.stato === 'pubblicata' || l.stato === 'published').map((l) => ({ loc: `${base}/${l.slug}`, pr: '0.8' })),
  ];
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.map((u) =>
    `<url><loc>${esc(u.loc)}</loc>${u.lastmod ? `<lastmod>${u.lastmod}</lastmod>` : ''}<priority>${u.pr}</priority></url>`).join('\n')}\n</urlset>\n`;
  res.type('application/xml').set('Cache-Control', 'public, max-age=3600').send(xml);
}

function robots(req, res) {
  res.type('text/plain').send(`User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\nAllow: /api/uploads/\n\nSitemap: ${baseUrl(req)}/sitemap.xml\n`);
}

module.exports = { htmlHandler, sitemap, robots, pageFor };
