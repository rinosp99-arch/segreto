# plan.md — LATO SEGRETO (React + FastAPI + MongoDB)

## 1) Objectives
- Consegnare una v1 completa (frontend + backend + admin + analytics + SEO best-possible senza SSR) **tutta in italiano**.
- Rendere impeccabile la feature distintiva: **trasformazione cinematografica** Lato Pubblico → Lato Segreto **stessa URL, no refresh**.
- Architettura “future-proof SEO”: dati/slug/metadata/contenuti nel backend, frontend solo rendering (facile migrazione futura a SSR/prerender).
- Demo realistica adult-safe: immagini/video coerenti pubblico↔segreto, niente contenuti espliciti.

---

## 2) Implementation Steps

### Phase 1 — Core POC (isolato) della Trasformazione + Tracking
**User stories (POC)**
1. Come utente, apro un profilo modella e vedo chiaramente il **Lato Pubblico**.
2. Come utente, premo “**NON DOVRESTI PREMERLO**” e la pagina si trasforma senza cambiare URL.
3. Come utente, percepisco blackout + “Te l’avevamo detto.” + cambio foto/testi/palette in <1.2s.
4. Come utente, posso tornare al Lato Pubblico senza ricaricare.
5. Come owner, vedo eventi tracciati (view, secret_activate, of_click_*).

**Steps**
- Websearch breve best-practice: React cinematic transitions (View Transition API fallback), Framer Motion patterns, performance for media crossfade.
- Implementare POC minimo (solo FE) con:
  - 1 route profilo (/modelle/francesca) + dataset locale temporaneo.
  - Transizione: blackout 150–250ms, flash soft, crossfade immagine A→B, cambio palette, copy swap, indicatore “LATO SEGRETO”.
  - prefers-reduced-motion: versione semplificata (fade senza flash/parallax).
- Aggiungere micro-tracking first-party (endpoint fittizio/locale) e verificare payload eventi.
- Test rapido con testing agent: URL invariata, no refresh, trasformazione fluida su viewport mobile 390×844.
- **Gate di qualità**: se la trasformazione non è “wow” e stabile, iterare finché lo è.

---

### Phase 2 — V1 App Development (senza auth admin inizialmente)
**User stories (V1 pubblico)**
1. Come utente, supero un gate 18+ premium e torno senza ripeterlo ad ogni pagina (persistenza).
2. Come utente, nella Home vedo una griglia premium 2-col mobile con ricerca e filtri rapidi.
3. Come utente, apro una modella e vivo la trasformazione Lato Segreto completa con foto/video/copy.
4. Come utente, dopo ~35s nel Lato Segreto ricevo “Ti ha lasciato qualcosa…” e posso aprire il messaggio.
5. Come utente, clicco “CONTINUA CON ME” e vado su OnlyFans (link tracciato, non rotto).

**Backend (FastAPI + MongoDB)**
- Modelli dati (decoupled): Model/Category/Badge/AnalyticsEvent/Article/AuditLog.
- API pubbliche:
  - GET /api/models (filtri, search, sorting, pagination)
  - GET /api/models/{slug}
  - GET /api/categories + GET /api/categories/{slug}
  - POST /api/track (eventi: view, secret_activate, message_open, of_click_*)
  - GET /sitemap.xml, /robots.txt, /rss.xml (se attivato)
- Sanitizzazione contenuti editoriali (HTML) prevista fin da ora (whitelist tag/attributi).

**Frontend (React)**
- Design system: layout, card, badge, filter chips, search, skeleton, modal, gallery viewer, envelope message.
- Home:
  - Griglia responsive + hover/press microinterazioni + teaser blur.
  - Filtri (TUTTE/NUOVE/PIÙ VISTE/IN TENDENZA) + categorie configurabili.
  - Search realtime (debounce) su nome/alias/tag.
  - “SORPRENDIMI” → random modella pubblicata.
  - Stato localStorage “LATO SEGRETO SCOPERTO” (discreto) per card già sbloccate.
- Profilo:
  - /modelle/{slug} con SEO meta dinamici.
  - Lato Pubblico completo + elemento “NON DOVRESTI PREMERLO” (glass).
  - Lato Segreto: media swap + palette + atmosfera + teaser limit + CTA.
  - Messaggio 35s (regole: solo dopo activation, 1x sessione/modella, no se OF già cliccato).
- Tracking:
  - Eventi inviati a backend con session id privacy-safe (localStorage) + referrer/utm.

**Concludere Phase 2**
- 1 round testing agent end-to-end: Home→modella→secret→messaggio→OF click, mobile 390×844.

---

### Phase 3 — Admin + Auth + Media Management
**User stories (Admin)**
1. Come admin, posso fare login/logout e le route admin sono protette lato backend.
2. Come admin, creo/modifico una modella (bozza/pubblica/disattiva) senza toccare JSON.
3. Come admin, gestisco coppie media pubblico↔segreto e vedo un’anteprima trasformazione.
4. Come admin, configuro CTA, timer/messaggio 35s, tema/palette del Lato Segreto.
5. Come admin, imposto SEO title/meta/canonical e l’ordine in Home.

**Steps**
- Auth:
  - Email+password, bcrypt, JWT con scadenza, logout, rate limiting login.
  - Struttura ruoli estendibile (solo AMMINISTRATORE ora).
- Admin UI /admin:
  - CRUD modelle + reorder + stato + “Conferma creator maggiorenne: SÌ” (blocco pubblicazione).
  - CRUD categorie/badge.
  - Gestione media: upload/URL, validazione MIME/dimensioni, poster video, drag&drop pairing.
  - Audit log azioni admin.
- Testing agent: flusso admin create→publish→compare in Home + modifica media→profilo aggiornato.

---

### Phase 4 — Analytics Dashboard + Funnel
**User stories (Analytics)**
1. Come owner, vedo visite e attivazioni Lato Segreto per modella.
2. Come owner, vedo funnel VISITA→SEGRETO→MESSAGGIO→CLICK OF con tassi.
3. Come owner, confronto OGGI/7G/30G e una classifica modelli per CTR.
4. Come owner, distinguo sorgenti click OnlyFans (gallery/message/sticky/end/locked).
5. Come owner, so quali articoli generano click verso modelle e OF.

**Steps**
- Aggregazioni backend (pipeline Mongo) per timeframe.
- Dashboard admin: cards KPI + chart + leaderboard + drilldown per modella.
- Validazione “no fake stats”: tutto deriva dagli eventi tracciati.
- Testing agent: generare eventi (navigazione) e verificare aggiornamento KPI.

---

### Phase 5 — SEO tecnico + Categorie + Editorial/Blog + Webhook integrazione
**User stories (SEO/Editoriale)**
1. Come utente, apro /categorie/{slug} e trovo modelle pertinenti + breadcrumb.
2. Come motore di ricerca, trovo sitemap.xml aggiornata con modelle/categorie/articoli pubblicati.
3. Come admin, creo un articolo in bozza, lo anteprimo e lo pubblico.
4. Come sistema esterno, invio un articolo via webhook e arriva come BOZZA (default OFF auto-publish).
5. Come owner, misuro ARTICOLO→MODELLA→LATO SEGRETO→CLICK OF.

**Steps**
- SEO centralizzata FE: title/meta/OG/canonical per Home, categoria, modella, articolo.
- Structured data: Organization, WebSite, BreadcrumbList (+ Person dove sensato, senza dati sensibili).
- robots.txt: blocco /admin, endpoint interni, preview.
- Editorial module:
  - /articoli + /articoli/{slug} (DB-backed).
  - Sanitizzazione HTML + immagini con alt.
  - RSS/feed opzionale.
- Webhook sicuro: POST /api/integrations/seo/articles con API key, validate, sanitize, dedupe, audit log; auto-publish default OFF.
- Testing agent: verificare meta dinamici, sitemap, pubblicazione articolo, navigazione interna articolo→modella.

---

### Phase 6 — Performance, Mobile Polish, Security Hardening, Final QA
**User stories (Qualità)**
1. Come utente mobile, scrollo fluido e i media caricano lazy senza layout shift.
2. Come utente, vedo una UI accessibile (focus, contrasto, keyboard, reduced motion).
3. Come owner, non espongo secrets nel frontend e l’admin è protetto.
4. Come utente, la trasformazione resta fluida anche con video (poster + lazy).
5. Come utente, trovo pagine legali e un 404 coerente.

**Steps**
- Performance: code-splitting, lazy media, dimensioni fisse, WebP/AVIF, preload controllato post-click.
- Security: headers, input validation, CSRF dove serve, upload limits, sanitizzazione editoriale.
- Final testing agent: suite completa acceptance tests (home, search/filters, profile transform, 35s message, OF click events, admin CRUD, analytics, SEO endpoints).

---

## 3) Next Actions
1. Eseguire websearch e definire pattern esatto trasformazione (timing/animazioni) + fallback.
2. Implementare Phase 1 POC (profilo singolo) e validarlo con testing agent.
3. Preparare seed demo (8–12 modelle + categorie + 3 temi segreti diversi) e lista media adult-safe.
4. Costruire Phase 2 (public v1) end-to-end e testare.

---

## 4) Success Criteria
- Trasformazione Lato Pubblico→Segreto: stessa URL, zero refresh, 600–1200ms, percezione “luxury cinematic”, reverse ok, reduced-motion ok.
- Home: 2-col mobile, filtri+search+Sorprendimi, card microinterazioni, stato “scoperto” persistente.
- Conversion: CTA OnlyFans tracciate per sorgente + messaggio 35s con regole corrette.
- Admin: login sicuro + CRUD completo + pairing media + publish workflow con check “creator maggiorenne”.
- Analytics: funnel e leaderboard basati su eventi reali, timeframe OGGI/7G/30G.
- SEO best-possible: meta dinamici, canonical, OG, structured data, sitemap/robots, categorie+articoli indicizzabili (public side).