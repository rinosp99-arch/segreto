// LATO SEGRETO server: React app + API + media, one process.
const path = require('path');
const fs = require('fs');
const express = require('express');
const compression = require('compression');
const store = require('./db');
const seo = require('./seo');
const site = require('./site');
const images = require('./images');

const PORT = process.env.PORT || 8001;
const FRONTEND_DIR = path.resolve(process.env.FRONTEND_DIR || path.join(__dirname, '..', 'frontend', 'build'));

const app = express();
app.disable('x-powered-by');
app.set('trust proxy', 1);
app.use(compression());

app.use((req, res, next) => {
  res.set({
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'X-Frame-Options': 'SAMEORIGIN',
    'Strict-Transport-Security': 'max-age=31536000',
  });
  next();
});

// www -> apex (or the other way round) once the real domain is set.
// Never redirected: the health check, and the AI interface (a GPT keeps calling the host it imported,
// and a wrong base URL must stay correctable from the previous host).
const NO_HOST_REDIRECT = ['/api/health', '/api/v2/ai/'];
app.use((req, res, next) => {
  const canonical = site.configuredBaseUrl();
  if (canonical && process.env.NODE_ENV === 'production') {
    const want = new URL(canonical).host;
    if (req.hostname && req.get('host') !== want && !NO_HOST_REDIRECT.some((p) => req.path.startsWith(p))) {
      return res.redirect(301, `${canonical}${req.originalUrl}`);
    }
  }
  next();
});

// media: ?w=<width> answers with a smaller copy of an image; range requests (video seeking / iOS) are handled by express.static
app.use('/api/uploads', images.middleware);
app.use('/api/uploads', express.static(store.UPLOADS_DIR, {
  immutable: true, maxAge: '365d', index: false, dotfiles: 'ignore', fallthrough: false,
}));

app.get('/api/health', (req, res) => res.json({ status: 'ok', instance: site.INSTANCE_ID }));
app.use('/api/admin', require('./admin'));
app.use('/api/v2/ai', require('./ai'));
app.use('/api', require('./public'));
app.use('/api', (req, res) => res.status(404).json({ detail: 'Not Found' }));

app.get('/sitemap.xml', seo.sitemap);
app.get('/robots.txt', seo.robots);

if (fs.existsSync(path.join(FRONTEND_DIR, 'index.html'))) {
  app.use('/static', express.static(path.join(FRONTEND_DIR, 'static'), { immutable: true, maxAge: '365d', fallthrough: false }));
  app.use(express.static(FRONTEND_DIR, { index: false, maxAge: '7d' }));
  app.get('*', seo.htmlHandler(FRONTEND_DIR));
} else {
  console.warn(`Frontend build not found in ${FRONTEND_DIR} - only the API is served.`);
}

// errors (e.g. missing media file -> 404)
app.use((err, req, res, next) => { // eslint-disable-line no-unused-vars
  const status = err.status || err.statusCode || 500;
  if (status >= 500) console.error(err);
  res.status(status).json({ detail: status === 404 ? 'Not Found' : 'Errore interno' });
});

app.listen(PORT, () => {
  console.log(`LATO SEGRETO läuft auf http://localhost:${PORT}`);
  images.warmUp().catch((e) => console.error('Vorschaubilder:', e.message));
});
