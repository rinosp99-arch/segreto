// LATO SEGRETO server: React app + API + media, one process.
const path = require('path');
const fs = require('fs');
const express = require('express');
const compression = require('compression');
const store = require('./db');
const seo = require('./seo');

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

// www -> apex (or the other way round) once the real domain is set
app.use((req, res, next) => {
  const canonical = process.env.PUBLIC_BASE_URL;
  if (canonical && process.env.NODE_ENV === 'production') {
    const want = new URL(canonical).host;
    if (req.hostname && req.get('host') !== want && !req.path.startsWith('/api/health')) {
      return res.redirect(301, `${canonical.replace(/\/+$/, '')}${req.originalUrl}`);
    }
  }
  next();
});

// media: range requests (video seeking / iOS) are handled by express.static
app.use('/api/uploads', express.static(store.UPLOADS_DIR, {
  immutable: true, maxAge: '365d', index: false, dotfiles: 'ignore', fallthrough: false,
}));

app.get('/api/health', (req, res) => res.json({ status: 'ok' }));
app.use('/api/admin', require('./admin'));
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

app.listen(PORT, () => console.log(`LATO SEGRETO läuft auf http://localhost:${PORT}`));
