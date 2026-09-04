# plan.md — LATO SEGRETO (React + FastAPI + MongoDB)

## 1) Objectives
- Consegnare una web app premium 18+ **tutta in italiano** (pubblico + admin) per promuovere creator/modelle con profili OnlyFans.
- Mantenere e migliorare la feature distintiva: **trasformazione cinematografica** Lato Pubblico → Lato Segreto **sulla stessa pagina/URL, no refresh**.
- Conversione e attribuzione first‑party: funnel verso OnlyFans con tracking (ref/fonte/campagna) persistente e analytics reali (no fake stats).
- Architettura “future‑proof SEO”: dati/slug/metadata/contenuti nel backend; frontend responsabile del rendering (migrazione futura a SSR/prerender possibile senza cloaking).
- Performance mobile-first: lazy media, nessun jank, rispetto autoplay policy (muted/playsInline), fallback robusti.
- **Nuovo obiettivo UX Home:** sezione “**IN MOVIMENTO**” come **pellicola cinematografica** seamless/infinita (non carosello), che si trasforma insieme allo switch Pubblico/Segreto.

**Stato attuale (snapshot)**
- Phase 1–6: implementate in gran parte (home griglia, profili con trasformazione, admin/auth, analytics base/funnel, categorie/articoli/SEO endpoints, campagne/referral). Test agent disponibili fino a iteration_5 (agent-tested; non user-confirmed).
- “IN MOVIMENTO”: presente solo bozza iniziale FE (`/frontend/src/components/FilmStrip.js`) **non integrata** e senza backend/admin/settings/analytics dedicati.

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

**Stato:** completata (implementata e iterata nelle fasi successive; agent-tested).

---

### Phase 2 — V1 App Development (pubblico)
**User stories (V1 pubblico)**
1. Come utente, supero un gate 18+ premium e torno senza ripeterlo ad ogni pagina (persistenza).
2. Come utente, nella Home vedo una griglia premium 2-col mobile con ricerca/filtri.
3. Come utente, apro una modella e vivo la trasformazione Lato Segreto completa con foto/video/copy.
4. Come utente, dopo ~35s nel Lato Segreto ricevo “Ti ha lasciato qualcosa…” e posso aprire il messaggio.
5. Come utente, clicco “CONTINUA CON ME” e vado su OnlyFans (link tracciato, non rotto).

**Backend (FastAPI + MongoDB)**
- Modelli dati decoupled: Model/Category/AnalyticsEvent/Article/AuditLog/Settings.
- API pubbliche:
  - GET /api/models (filtri, search, sorting, pagination)
  - GET /api/models/{slug}
  - GET /api/models/{slug}/segreto
  - GET /api/categories + GET /api/categories/{slug}
  - POST /api/track (eventi: page_view, secret_activate, message_open, of_click, ecc.)
  - GET /sitemap.xml, /robots.txt, /rss.xml (se attivato)
- Sanitizzazione contenuti editoriali (HTML) prevista.

**Frontend (React)**
- Design system: layout, card, badge, filter chips, search, skeleton, modal, envelope message.
- Home:
  - Griglia responsive + hover/press microinterazioni + teaser blur in modalità segreta.
  - Filtri (TUTTE/NUOVE/PIÙ VISTE/IN TENDENZA).
  - “SORPRENDIMI”.
  - Stato localStorage “LATO SEGRETO SCOPERTO”.
- Profilo:
  - /modelle/{slug} con SEO meta dinamici.
  - Lato Pubblico + trigger “NON DOVRESTI PREMERLO”.
  - Lato Segreto: media swap (coppie), atmosfera, video autoplay muted/loop/playsInline con IntersectionObserver.
  - Messaggio ~35s con regole.
- Tracking:
  - Eventi a backend con session id privacy-safe (localStorage) + attribuzione.

**Stato:** completata (agent-tested).

---

### Phase 3 — Admin + Auth + Media Management
**User stories (Admin)**
1. Come admin, posso fare login/logout e le route admin sono protette lato backend.
2. Come admin, creo/modifico una modella (bozza/pubblica/disattiva) senza toccare JSON.
3. Come admin, gestisco coppie media pubblico↔segreto e vedo un’anteprima trasformazione.
4. Come admin, configuro CTA, timer/messaggio 35s, tema/palette del Lato Segreto.
5. Come admin, imposto SEO title/meta e l’ordine in Home.

**Steps**
- Auth: email+password, bcrypt, JWT, logout, rate limiting login; struttura ruoli estendibile (1 ruolo: AMMINISTRATORE).
- Admin UI /admin:
  - CRUD modelle + reorder + stato + blocco pubblicazione senza conferma maggiorenne.
  - CRUD categorie.
  - Gestione media: upload tramite object storage (no filesystem locale), pairing per posizione.
  - Audit log.

**Stato:** completata (agent-tested).

---

### Phase 4 — Analytics Dashboard + Funnel
**User stories (Analytics)**
1. Come owner, vedo visite e attivazioni Lato Segreto per modella.
2. Come owner, vedo funnel VISITA→SEGRETO→MESSAGGIO→CLICK OF.
3. Come owner, confronto OGGI/7G/30G e leaderboard CTR.
4. Come owner, distinguo sorgenti click OnlyFans.
5. Come owner, so quali articoli generano click verso modelle e OF.

**Steps**
- Aggregazioni backend per timeframe.
- Dashboard admin: KPI + leaderboard + drilldown.
- Validazione “no fake stats”.

**Stato:** completata (agent-tested) + campagne/referral integrati.

---

### Phase 5 — SEO tecnico + Categorie + Editorial/Blog + Webhook integrazione
**User stories (SEO/Editoriale)**
1. Come utente, apro /categorie/{slug} e trovo modelle pertinenti + breadcrumb.
2. Come motore di ricerca, trovo sitemap.xml aggiornata con modelle/categorie/articoli pubblicati.
3. Come admin, creo un articolo in bozza, lo anteprimo e lo pubblico.
4. Come sistema esterno, invio un articolo via webhook e arriva come BOZZA (default OFF auto-publish).
5. Come owner, misuro ARTICOLO→MODELLA→LATO SEGRETO→CLICK OF.

**Steps**
- SEO FE: title/meta/OG/canonical per Home/categoria/modella/articolo.
- Structured data: Organization, WebSite, BreadcrumbList.
- robots.txt: blocco /admin.
- Editorial DB-backed + sanitizzazione.
- Webhook sicuro per articoli esterni (auto-publish OFF di default).

**Stato:** completata (agent-tested).

---

### Phase 6 — Performance, Mobile Polish, Security Hardening, Final QA
**User stories (Qualità)**
1. Come utente mobile, scrollo fluido e i media caricano lazy senza layout shift.
2. Come utente, vedo una UI accessibile (focus, contrasto, keyboard, reduced motion).
3. Come owner, non espongo secrets nel frontend e l’admin è protetto.
4. Come utente, la trasformazione resta fluida anche con video (poster + lazy).
5. Come utente, trovo pagine legali e un 404 coerente.

**Steps**
- Performance: lazy media, dimensioni fisse, preload controllato post-click.
- Security: validation, upload limits, sanitizzazione.
- Testing agent: suite completa.

**Stato:** completata in gran parte; quality gate continuo ad ogni nuova feature.

---

### Phase 7 — HOME “IN MOVIMENTO” (Pellicola cinematografica)
**Scope**
Nuova sezione in Home (dopo ~8–12 modelle) con fascia orizzontale di teaser video verticali (10–15s; demo ~12s) che scorre lentamente e continuamente da destra verso sinistra, senza reset visibile. Non è un carousel standard (niente frecce/pallini). Deve trasformarsi in modo cinematografico insieme allo switch Pubblico/Segreto senza scatti o video neri e mantenendo la posizione nel movimento.

#### 7.1 User stories (Pubblico)
1. Come utente, scorrendo la Home, vedo “IN MOVIMENTO” con sottotitolo “Una foto non racconta tutto.” inserito dopo ~10 card e poi la griglia continua.
2. Come utente, vedo una pellicola video verticale autoplay/muted/loop/playsInline senza controlli.
3. Come utente mobile (390×844), vedo ~2 video completi + parte del successivo.
4. Come utente, quando passo il dito/hover, la pellicola rallenta o si ferma temporaneamente; la tile ha micro-zoom/glow, overlay con nome e CTA “Scopri il suo Lato Segreto”; click porta al profilo modella.
5. Come utente, quando attivo la modalità segreta Home, la pellicola **si trasforma davanti ai miei occhi** usando media segreti e atmosfera (glow leggero, fumo sottile, bordeaux/viola/oro, luce diagonale/vignetta) mantenendo continuità del movimento.

#### 7.2 User stories (Admin)
1. Come admin, per ogni modella configuro “PELLICOLA HOME”: mostra sì/no, video pubblico+poster, video segreto+poster, priorità 1–10, ordine manuale opzionale.
2. Come admin, configuro impostazioni globali pellicola: attiva, titolo, sottotitolo, velocità, massimo video attivi (default 8), seconda fila (predisposta ma OFF), pausa su touch/hover, nomi sempre visibili, posizione inserimento (dopo N card).

#### 7.3 Data model & Seed
- Estendere `ModelIn` (backend schemas) con campo `pellicola_home` (dict o sub-schema) contenente:
  - `attiva` (bool)
  - `priorita` (1–10)
  - `ordine` (int, opzionale)
  - `pubblico`: {`video_url`, `poster_url`}
  - `segreto`: {`video_url`, `poster_url`}
- Estendere settings globali (`SettingsIn` + documento settings `id=global`) con `home_pellicola`:
  - `attiva` (bool)
  - `titolo` (string)
  - `sottotitolo` (string)
  - `velocita` (float o preset: lenta/medio)
  - `max_video_attivi` (int, default 8; range 6–10)
  - `seconda_fila` (bool, default false)
  - `pausa_su_touch` (bool, default true)
  - `nomi_sempre_visibili` (bool, default false)
  - `inserisci_dopo_n` (int, default 10; range suggerito 8–12)
- Seed demo:
  - associare a ~8–12 modelle video/poster pubblici e segreti usando asset locali `/frontend/public/media/*`.
  - rigenerare teaser demo a ~12s (vedi 7.6).

#### 7.4 API pubbliche
- `GET /api/pellicola`
  - Response: settings pellicola + items ordinati (ordine manuale poi priorità) con slug/nome/urls pubbliche+segrete.
  - Deve includere solo modelle pubblicate e solo item `attiva=true`.

#### 7.5 Analytics (eventi + aggregazioni)
- Eventi FE → `POST /api/track`:
  - `pellicola_impression` (quando sezione entra in viewport; include campagna/ref se presente; modalità home)
  - `pellicola_video_view` (quando un tile video raggiunge soglia visibilità/durata minima o start play effettivo)
  - `pellicola_click_profilo` (criterio richiesto): payload con `creator/slug`, `posizione`, `modalità` (pubblico|segreto), `campagna/ref/fonte`.
- Admin analytics:
  - Nuovo endpoint `GET /api/admin/analytics/pellicola` con aggregazioni per range (oggi/7g/30g): impression, view video, click, CTR; breakdown per modella + modalità.

#### 7.6 Frontend FilmStrip (definitivo)
- Riscrittura `FilmStrip`:
  - Marquee “infinito” **seamless** (duplicazione contenuti + animazione translateX(-50%) senza gap/reset visibile).
  - Nessun controllo UI da carousel (no frecce/pallini).
  - Autoplay `muted`, `loop`, `playsInline`, senza controlli visibili.
  - Touch/hover: pausa o rallenta temporaneamente (configurabile), micro-zoom/glow + overlay.
  - Modalità segreta: overlay/gradient/fumo e palette bordeaux/viola/oro; nessun cambio “a scatto”.
  - **Continuity requirement:** lo switch Pubblico/Segreto non deve resettare la posizione del movimento né mostrare video neri.
  - Performance:
    - massimo **8 video attivi** (config) con un “active-cap manager”: solo i tile vicini al viewport riproducono/sono caricati.
    - IntersectionObserver per:
      - pausa totale quando sezione fuori viewport;
      - play/pause delle tile in viewport;
      - lazy-load `src` solo quando necessario.
    - Poster fallback sempre presente (immagine) prima del play e in caso di errore (no black frame).
  - A11y:
    - `prefers-reduced-motion`: scorrimento disattivato o molto ridotto + tile statiche.
    - focus-visible su tile, navigazione tastiera non bloccata.
  - Tracking:
    - impression/video view/click con `session_id` e attribuzione.

#### 7.7 Integrazione Home
- Inserire “IN MOVIMENTO” nella Home dopo ~10 modelle:
  - render: prime N card → FilmStrip → resto griglia.
  - Deve funzionare con filtri Home senza rompere layout.
  - In modalità segreta Home, FilmStrip usa i media segreti, stessa velocità/posizione.

#### 7.8 Admin UI
- ModelEditor: nuova sezione “PELLICOLA HOME” per modella:
  - Toggle mostra sì/no;
  - UploadField video/poster pubblico e segreto;
  - priorità 1–10;
  - ordine manuale.
- AdminSettings: nuova sezione “HOME → PELLICOLA”:
  - attiva, titolo, sottotitolo;
  - velocità;
  - max video attivi (default 8);
  - pausa su touch;
  - nomi sempre visibili;
  - seconda fila (predisposta ma OFF di default);
  - posizione inserimento (dopo N card).

#### 7.9 Teaser demo (rigenerazione)
- Aggiornare `/scripts/gen_clips.sh` per produrre clip verticali **10–15s** (target demo ~12s) con motion naturale:
  - Ken Burns delicato + crop/zoom; evitare slow-motion “brutto” e ripetizioni evidenti.
  - Se si usa loop: render loop **seamless** (boomerang o crossfade) per evitare stacco.
  - Compressione mobile: H.264, CRF adeguato, `+faststart`, dimensione contenuta.
  - Rigenerare poster coerenti.

#### 7.10 Test end-to-end (obbligatorio)
- Build + smoke test.
- Testing agent su scenari:
  - Home 390×844: pellicola visibile con 2 video + partial, autoplay ok.
  - Scroll: nessun overflow/jank; se fuori viewport: video in pausa.
  - Touch/hover: pausa/ripresa; overlay e click verso profilo.
  - Switch Home Pubblico→Segreto: trasformazione pellicola **senza reset** e senza video neri.
  - Cap 8 video attivi rispettato.
  - Analytics: impression/video view/click registrati; attribuzione ref/fonte/campagna mantenuta fino a click OF (funnel).
  - Regressioni: trasformazione profilo, admin CRUD, campagne, articoli/SEO, analytics esistenti.

**Stato:** COMPLETATA — implementata end-to-end e verificata dal testing agent (iteration_6): frontend 100%, admin 100%, backend 98.5% (unico rilievo = falso positivo su age-validation, confermato HTTP 400 via curl). Pellicola seamless, cap 8 video attivi rispettato, poster fallback (no black), pausa fuori viewport, trasformazione Pubblico↔Segreto continua, analytics impression/video_view/click attive, teaser demo rigenerati a ~12s seamless. Seconda fila predisposta ma OFF di default.

---

## 3) Next Actions
1. Implementare Phase 7 end-to-end (backend schema+seed+routes, admin settings/editor, frontend FilmStrip definitivo + integrazione Home, rigenerazione teaser ~12s, analytics + aggregazioni).
2. Eseguire build e poi **testing agent** focalizzato su mobile 390×844 e seamless continuity.
3. Aggiornare questo plan.md marcando Phase 7 come completata solo dopo report di test.

---

## 4) Success Criteria
- Trasformazione Lato Pubblico→Segreto: stessa URL, zero refresh, 600–1200ms, percezione “luxury cinematic”, reverse ok, reduced-motion ok.
- Home: griglia premium + filtri+search+Sorprendimi + stato “scoperto” persistente.
- Conversion: CTA OnlyFans tracciate per sorgente + messaggio ~35s con regole corrette.
- Admin: login sicuro + CRUD completo + pairing media + publish workflow con check “creator maggiorenne”.
- Analytics: funnel e leaderboard basati su eventi reali + campagne/referral.
- SEO best-possible (senza SSR): meta dinamici, canonical, OG, structured data, sitemap/robots, categorie+articoli indicizzabili.
- **IN MOVIMENTO:** pellicola seamless (nessun salto/reset/spazio vuoto), autoplay affidabile, poster fallback (no video neri), max 8 video attivi, pausa fuori viewport, trasformazione Pubblico↔Segreto continua e cinematografica, tracking completo (impression/view/click) e attribuzione end-to-end.
