# plan.md — LATO SEGRETO (React + FastAPI + MongoDB)

## 1) Objectives
- Consegnare una web app premium 18+ **tutta in italiano** (pubblico + admin) per promuovere creator/modelle con profili OnlyFans.
- Mantenere e migliorare la feature distintiva: **trasformazione cinematografica** Lato Pubblico → Lato Segreto **sulla stessa pagina/URL, no refresh**.
- Conversione e attribuzione first‑party: funnel verso OnlyFans con tracking (ref/fonte/campagna) persistente e analytics reali (no fake stats).
- Architettura “future‑proof SEO”: dati/slug/metadata/contenuti nel backend; frontend responsabile del rendering (migrazione futura a SSR/prerender possibile senza cloaking).
- Performance mobile-first: lazy media, nessun jank, rispetto autoplay policy (muted/playsInline), fallback robusti.
- **UX Home:** sezione “**IN MOVIMENTO**” come **pellicola cinematografica** seamless/infinita (non carosello), che si trasforma insieme allo switch Pubblico/Segreto.
- **Obiettivo operativo (admin + GPT):** tramite API v2 + Capability Registry + Universal Dispatcher, permettere a ChatGPT di gestire in modo sicuro operazioni business (testi/SEO/landing/categorie/internal linking/rollback/approvals) senza mai diventare un backdoor (no DB raw, no shell, no secrets).
- **Nuovo obiettivo SEO (Phase 14 — SEO AUTOPILOT / ORGANIC GROWTH ENGINE):** costruire un “cervello SEO” autonomo **READ_ONLY** che usa Search Console + audit tecnici + clustering + intent + opportunity engine + planning future landing (non pubblicate) e backlog auditabile; nessuna modifica al sito pubblico.

**Stato attuale (snapshot)**
- Phase 1–8: completate (agent-tested). Pubblico + Admin stabili.
- Phase 9–11: SUPER API + ChatGPT control layer v1: completate e verificate in produzione.
- Phase 12A: Total Site Control API v2: completata, deployata in produzione, contratto GPT v2 robusto.
- Phase 13: GOOGLE SEO CORE: modulo `backend/google_search/` presente (status/sitemap sync/inspection/analytics) e pronto a essere riusato.
- Phase 4 + Tracking: Admin Analytics v2 e Tracking v2 completati (agent-tested), funnel chiuso 6 step, percorsi, device compare, video/scroll/engaged.
- Stato produzione: `https://secret-side.emergent.host`

---

## 2) Implementation Steps

### Phase 1 — Core POC (isolato) della Trasformazione + Tracking
**User stories (POC)**
1. Come utente, apro un profilo modella e vedo chiaramente il **Lato Pubblico**.
2. Come utente, premo “**NON DOVRESTI PREMERLO**” e la pagina si trasforma senza cambiare URL.
3. Come utente, percepisco blackout + “Te l’avevamo detto.” + cambio foto/testi/palette in <1.2s.
4. Come utente, posso tornare al Lato Pubblico senza ricaricare.
5. Come owner, vedo eventi tracciati (view, secret_activate, of_click_*).

**Stato:** completata (agent-tested).

---

### Phase 2 — V1 App Development (pubblico)
**User stories (V1 pubblico)**
1. Come utente, supero un gate 18+ premium e torno senza ripeterlo ad ogni pagina (persistenza).
2. Come utente, nella Home vedo una griglia premium 2-col mobile con ricerca/filtri.
3. Come utente, apro una modella e vivo la trasformazione Lato Segreto completa con foto/video/copy.
4. Come utente, dopo ~35s nel Lato Segreto ricevo “Ti ha lasciato qualcosa…” e posso aprire il messaggio.
5. Come utente, clicco “CONTINUA CON ME” e vado su OnlyFans (link tracciato, non rotto).

**Stato:** completata (agent-tested).

---

### Phase 3 — Admin + Auth + Media Management
**User stories (Admin)**
1. Come admin, posso fare login/logout e le route admin sono protette lato backend.
2. Come admin, creo/modifico una modella (bozza/pubblica/disattiva) senza toccare JSON.
3. Come admin, gestisco coppie media pubblico↔segreto e vedo un’anteprima trasformazione.
4. Come admin, configuro CTA, timer/messaggio 35s, tema/palette del Lato Segreto.
5. Come admin, imposto SEO title/meta e l’ordine in Home.

**Stato:** completata (agent-tested).

---

### Phase 4 — Analytics Dashboard + Funnel
**User stories (Analytics)**
1. Come owner, vedo visite e attivazioni Lato Segreto per modella.
2. Come owner, vedo funnel VISITA→SEGRETO→MESSAGGIO→CLICK OF.
3. Come owner, confronto OGGI/7G/30G e leaderboard CTR.
4. Come owner, distinguo sorgenti click OnlyFans.
5. Come owner, so quali articoli generano click verso modelle e OF.

**Stato:** completata (agent-tested) — **v2**.

---

### Phase 5 — SEO tecnico + Categorie + Editorial/Blog + Webhook integrazione
**User stories (SEO/Editoriale)**
1. Come utente, apro /categorie/{slug} e trovo modelle pertinenti + breadcrumb.
2. Come motore di ricerca, trovo sitemap aggiornata con modelle/categorie/articoli pubblicati.
3. Come admin, creo un articolo in bozza, lo anteprimo e lo pubblico.
4. Come sistema esterno, invio un articolo via webhook e arriva come BOZZA.
5. Come owner, misuro ARTICOLO→MODELLA→LATO SEGRETO→CLICK OF.

**Stato:** completata (agent-tested).

---

### Phase 6 — Performance, Mobile Polish, Security Hardening, Final QA
**User stories (Qualità)**
1. Come utente mobile, scrollo fluido e i media caricano lazy senza layout shift.
2. Come utente, vedo una UI accessibile.
3. Come owner, non espongo secrets nel frontend e l’admin è protetto.
4. Come utente, la trasformazione resta fluida anche con video.
5. Come utente, trovo pagine legali e un 404 coerente.

**Stato:** completata in gran parte; quality gate continuo.

---

### Phase 7 — HOME “IN MOVIMENTO” (Pellicola cinematografica)
**Scope**
Sezione in Home con fascia orizzontale di teaser video verticali che scorre lentamente e continuamente, trasformazione Pubblico↔Segreto continua.

**Stato:** COMPLETATA (agent-tested).

---

### Phase 8 — Admin Content Workflow (DEMO/REALE + INCOMPLETA/PRONTA + Produttività)
**Vincolo:** non modificare il design pubblico già approvato.

**Stato:** COMPLETATA (agent-tested) — override manuale DEMO/REALE per media, checklist required, blocco pubblicazione con 400 strutturato, filtri+conteggi, import rapido file+URL, copia configurazione, anteprima admin bozza noindex.

---

### Phase 9 — SUPER API (motore API-first) — Status: COMPLETATA
**Stato:** completata (agent-tested). API v1 /api/v1/* e pannello admin /admin/motore.

---

### Phase 10 — CHATGPT CONTROL LAYER (v1) — Status: COMPLETATA
**Stato:** completata (agent-tested). READ_ONLY supportato. OpenAPI v1 (23 operazioni) ancora valido.

---

### Phase 11 — CHATGPT REAL CONNECTION (READ_ONLY) — Status: COMPLETATA
**Stato:** produzione verificate regressioni e health reconciliation. READ_ONLY stabile. Nessun deploy automatico.

---

### Phase 12A — TOTAL SITE CONTROL API v2 + FULL BUSINESS ACCESS — Status: COMPLETATA E VERIFICATA IN PRODUZIONE
**Stato:**
- v2 `/api/v2/ai/*` (12 primitive universali) + registry capability.
- Preview/execute policy corretta (preview scopes deterministici + conditional scopes).
- Contratto GPT Action v2 robusto.

---

### Phase 13 — GOOGLE SEO CORE — Status: PRESENTE (riusabile)
**Obiettivo:** Search Console come fonte dati ufficiale (sitemap sync, URL inspection, search analytics) con modulo backend modulare.

**Stato:** `backend/google_search/` presente con:
- `status()` (connessione + property + quote)
- `analytics()` (Search Analytics con cache)
- `inspect()` (URL Inspection con cache+budget)
- `indexability()` (audit tecnico read-only)
- adapter `mock` per test senza credenziali

---

## Phase: Admin Analytics v2 + Tracking Audit (Status: COMPLETED — agent-tested)
- Root cause black screen (storico): Recharts riceveva `data=null` → TypeError → unmount root.
- Dashboard v2 + backend v2 + CSV + log tecnico + widget isolation.

## Phase: Tracking v2 implementation (Status: COMPLETED — agent-tested)
- `visitor_id` persistente + `visit_id` per visita (timeout 30 min / nuova scheda / campagna).
- Schema comune centralizzato + queue + batch + beacon.
- entry_source propagato (home_card/filmstrip/surprise/swipe/swipe_button/related/search/category/campaign/direct).
- CTA/OF/social/swipe/video/scroll/engaged completati.
- Backend analytics v2 aggiornato: funnel chiuso 6 step + drop-off, percorsi, device compare, video per slot, engaged/scroll.
- Test: pytest 89/89 + 3 percorsi E2E ricostruiti in DB.

---

### Phase 14 — SEO AUTOPILOT / ORGANIC GROWTH ENGINE — READ_ONLY “BRAIN” (NUOVA FASE)
**Regola assoluta (questa fase):** nessun cambiamento al sito pubblico. Nessuna landing pubblica. Nessuna modifica a URL/title/meta/H1/testi/media/sitemap/robots/canonical/structured data/internal linking/blog/CTA/Analytics.

#### 14.0 Modalità e safety rails
- Implementare `SEO_AUTOPILOT_MODE` con tre stati: `OFF`, `READ_ONLY`, `FULL`.
- **Stato attuale forzato:** `SEO_AUTOPILOT_MODE=READ_ONLY`.
- `FULL` deve restare **bloccato** in questa fase: non attivabile per errore.
- Ogni azione di write deve fallire esplicitamente se `SEO_AUTOPILOT_MODE != FULL`.

#### 14.1 Dato primario: Google Search Console (riuso integrazione esistente)
- Riutilizzare `backend/google_search/` (nessuna integrazione duplicata).
- Preview: `GSC_STATUS=NOT_CONNECTED` (non bloccare il motore).
- Produzione: `GSC_STATUS=CONNECTED` quando credenziali/env presenti.
- Importare Search Analytics (quando disponibile): query/page/date/clicks/impressions/CTR/position/country/device.
- Nessun scraping SERP.

#### 14.2 Storage SEO storico (snapshots non sovrascritti)
- Nuove collezioni dedicate (read-only):
  - `seo_gsc_snapshots` (giornaliero): rows normalizzate per dimensioni; retention 400 giorni.
  - `seo_keyword_universe` (keyword candidate + fonte + stato).
  - `seo_clusters` (cluster_id, intent, primary/secondary keywords, query associate, metriche GSC, trend, pagina associata, cannibalizzazione).
  - `seo_opportunities` (daily findings + score HIGH/MEDIUM/LOW/HOLD + motivazione).
  - `seo_page_map` (cluster → current_page → action: KEEP/UPDATE/EXPAND/CREATE/MERGE/REVIEW/HOLD).
  - `seo_landing_drafts` (SEO_DRAFT_PROPOSAL: slug proposto, struttura, link suggeriti, creator pertinenti, quality gate).
  - `seo_audits` (tech/render/adult audit, snapshot, findings).
  - `seo_decision_log` (audit completo di ogni decisione: metriche usate, motivi, confidence, esito quality gate).

#### 14.3 Keyword discovery engine (seed + espansione controllata)
- Seed iniziali (OnlyFans/creator italiane) + espansione tramite:
  - query reali GSC
  - database modelle (nome, categorie, tag, descrizioni)
  - sinonimi e varianti linguistiche italiane
  - long-tail pertinenti (no keyword stuffing)
- **Regola:** nessun search volume inventato. Metriche solo da GSC; altrimenti `UNKNOWN`.

#### 14.4 Semantica: deterministico + LLM (decisione 1b)
- Base deterministica auditabile (normalizzazioni, tokenizzazione IT, stopwords, stemming leggero, n-gram, regole merge/split).
- LLM come supporto per:
  - sinonimi/varianti
  - intent
  - proposte cluster/merge
- Ogni output LLM marcato `source=LLM_SUGGESTION`.
- LLM **non** può inventare metriche: impressions/clicks/ctr/position restano `UNKNOWN` finché non arrivano da GSC.
- La decisione finale (CREATE/UPDATE/MERGE/HOLD) deve essere deterministica e auditabile.
- Modello: `gpt-5.4-mini` via `emergentintegrations` (cost-conscious), fallback automatico se key/budget non disponibile.

#### 14.5 Intent classification
- Classi indicative: DISCOVERY, CATEGORY, CREATOR, INFORMATIONAL, BRANDED, COMMERCIAL/NAV.
- Estendibili se emergono categorie utili.

#### 14.6 Clustering + Cannibalization engine
- Raggruppare query semanticamente equivalenti.
- Rilevare:
  - più URL sullo stesso intent
  - title/H1 simili
  - cluster sovrapposti
- Output: rischio LOW/MEDIUM/HIGH, URL coinvolti e motivo (solo report).

#### 14.7 Opportunity engine + score
- Ogni giorno:
  - A) impression alte + pos 5–20
  - B) impression alte + CTR basso
  - C) query nuove in crescita
  - D) intent pertinente + nessuna pagina adeguata (future CREATE)
  - E) cannibalizzazione
  - F) pagina in declino
- Score interno HIGH/MEDIUM/LOW/HOLD con motivazione leggibile.

#### 14.8 Keyword → Page map (solo raccomandazioni)
- Mappa: CLUSTER → PAGINA ATTUALE → AZIONE FUTURA.
- Azioni consentite in READ_ONLY: KEEP/UPDATE/EXPAND/CREATE/MERGE/REVIEW/HOLD.
- Nessuna esecuzione.

#### 14.9 Landing page planner + Quality Gate (solo draft)
- Generare proposte `SEO_DRAFT_PROPOSAL` (non pubbliche): slug, intent, title/H1 proposti, outline, link suggeriti, creator/categorie pertinenti.
- Quality gate: evita doorway/keyword stuffing/duplicazione/cannibalizzazione grave.
- Se fallisce: `REJECTED_BY_QUALITY_GATE`.

#### 14.10 Model database analysis
- Analizzare solo dati reali modelle pubblicate: nome/slug/categorie/tag/bio/descrizioni.
- Costruire matrice: keyword/category ↔ creator pertinenti.

#### 14.11 Technical SEO auditor (crawler) — READ ONLY
- Crawler interno controllato:
  - status code
  - title/meta/H1
  - canonical
  - robots directives
  - indexability
  - structured data presence
  - internal links/orphan/broken links
  - duplicate title/desc/H1
  - immagini senza alt
- **Base URL configurabile:** `SEO_CRAWL_BASE_URL` (decisione 3a: preview→preview, prod→prod).

#### 14.12 React / Google render audit (decisione 4a)
Confronto **INITIAL_HTML vs RENDERED_DOM vs GOOGLE_INSPECTION**:
- Headless Chromium (Playwright): campione limitato **≤30 pagine/giorno**, background.
- URL Inspection API (quando GSC connessa): usata con priorità su anomalie/pagine ad alto valore, non indiscriminata.

#### 14.13 Adult / OnlyFans SEO audit — READ ONLY
- Audit specifico rischio SafeSearch/explicit:
  - crawling bloccato o meno
  - fetch media/video
  - impatto age gate (solo audit)
  - differenza contenuto pubblico vs Secret
- Nessuna modifica.

#### 14.14 Daily Autopilot + Weekly learning
- Jobs schedulati (no impatto request utente):
  - `seo_ap_gsc_sync` (12h)
  - `seo_ap_tech` (8h)
  - `seo_ap_deep` (24h)
  - `seo_ap_render` (24h)
  - `seo_ap_weekly` (7d)
- GSC 1–2 volte/giorno (rispetto delay dati e quota).

#### 14.15 Admin UI semplice: “SEO Autopilot”
- In admin aggiungere sezione: **SEO AUTOPILOT** (nessun grafico complesso):
  - STATO (READ_ONLY)
  - GSC (CONNECTED / NOT_CONNECTED)
  - ultima analisi
  - oggi: query analizzate, cluster, opportunità, problemi tecnici, proposte CREATE/UPDATE/MERGE, reject quality gate
  - top opportunità
  - ultime azioni del motore
  - errori

#### 14.16 Log completo + auditabilità
- Ogni decisione salvata con: timestamp, azione proposta, pagina/cluster, motivo, metriche, confidence, quality check.

#### 14.17 Zero mutation test (fondamentale)
- Prima e dopo ogni run READ_ONLY: snapshot/hash delle risorse pubbliche principali:
  - models/categorie/articoli/landings/redirects
  - config “pubblica”
  - `robots.txt`, `/api/sitemap.xml`
  - (opzionale) campione di pagine HTML initial
- Risultato: `PUBLIC_MUTATIONS = 0` obbligatorio, altrimenti FAIL.

#### 14.18 Test
- GSC non collegata / collegata
- zero data
- query nuove
- cluster duplicati/sovrapposti
- cannibalizzazione
- modelle senza tag / con molti tag
- broken link
- API Google down / retry
- job idempotente
- FULL non attivabile
- **PUBLIC_MUTATIONS=0**

#### 14.19 Deliverables
- `SEO_AUTOPILOT.md` (architettura, mode, collezioni, jobs, audit log, quality gate, regole privacy)
- Endpoint admin read-only `/api/admin/seo-autopilot/*`
- Pagina admin “SEO Autopilot”
- Report finale: fonti dati, stato GSC, keyword/clusters/opportunità/draft landing/cannibalizzazioni/tech+render+adult findings, job creati, `PUBLIC_MUTATIONS=0`, PASS/FAIL.

---

## 3) Phase 14 — SEO AUTOPILOT READ_ONLY (Status: COMPLETED — PASS, PUBLIC_MUTATIONS=0)

### Phase 20 — PRIMO POST REALE ONLYFANS CONTROLLATO (VANESSA BELLA, 1 solo post) — Status: STOPPED AT PRECHECK (0 write reali)
Autorizzazione utente: 1 solo publish-now reale su `latosegreto`, Public+Secret Vanessa, caption IT + link OF DB, scheduler OFF, `OF_REAL_TEST_MAX_POSTS=1`, gate write temporaneo + ripristino false, STOP dopo il tentativo. Nessuna conferma extra se tutti i pre-check PASS.
- [x] Codice: `engine.real_test_mode()` (candidato singolo, no fallback a modella successiva, SCHEDULE bloccato), hard cap DB (`real_posts_created`) + process (`_check_create_limit`), gate `set_write_gate` aperto solo pre-upload e ripristinato in ogni esito + verifica read (`_restore_gate`), `verify_real_post` (id/account/caption/link/media). Compile OK, lint F OK (solo 1 import inutilizzato in caption.py).
- [x] Pre-check READ-ONLY produzione eseguiti (`/tmp/prod_precheck.py`, output mascherato):
  - PASS: CONNECTED · latosegreto · onlyfans · HEALTHY · `write_actions_allowed=false` · OF_REAL_WRITE_CALLS=0 · MOCK_MODE=false · OF_REAL_POSTING_ENABLED=true · AUTO_SCHEDULER=false · TOTAL_REAL_POSTS_CREATED=0 · coda 1/16 = VANESSA BELLA · link OF = quello atteso del DB · Public (photo, 200, image/jpeg, 396 KB) + Secret (photo, 200, image/jpeg, 135 KB) stesso model_id · SAME_MODEL=true · caption IT (LLM) con 1 solo link
  - **FAIL: `OF_REAL_TEST_MAX_POSTS` NON presente nell'env di produzione → REAL_TEST_MODE=false, REAL_TEST_MAX_POSTS=None** → hard cap 1 non attivo e motore in modalità rotazione (potrebbe saltare a modella successiva). STOP: nessun gate aperto, nessun upload, nessun post.
- [x] Aggiunta `OF_REAL_TEST_MAX_POSTS=1` a `/app/backend/.env` (workspace) + restart backend → status workspace: REAL_TEST_MODE=true, MAX=1, TOTAL=0, writes=0.
- [ ] PRODUZIONE: l'agente NON può modificare env/redeploy di produzione (confermato da support). Utente: Manage Publishes → Secrets → Custom Keys → `OF_REAL_TEST_MAX_POSTS=1` → Save & Redeploy → poi ripetere pre-check → se tutti PASS eseguire l'unico publish-now.


### Phase 19 — OF AUTOPILOT MOTORE COMPLETO (Status: COMPLETED in preview — MOCK, 0 write reali, nessun post reale)
Decisioni utente: link OF reale della modella in caption; PUBBLICA ORA = post immediato (scheduler separato); HEAD reali sui nostri media; tutto MOCK.
- [x] `of_autopilot/{media,caption,engine,jobs}.py` + `providers/mock.py` + base estesa (`upload_media_from_url`, `verify_post`) + routes complete; env `OF_AUTOPILOT_MOCK=true`
- [x] media source = DB/storage Lato Segreto, due cursori, SAME_MODEL guard, validazione reale, video, source_url + file fallback, media object completo, cursori solo dopo conferma
- [x] Admin `AdminOfAutopilot.js` espansa (stato, KPI, Attiva/Pausa/Anteprima/Pubblica ora MOCK/Salta, impostazioni, rotazione, log) — nessun controllo real posting
- [x] test 23/23 (`test_of_autopilot.py` 16 + connessione 7) · testing agent 61/61 PASS 0 bug (`iteration_27_of_autopilot_mock.json`) · regressione 153 PASS
- STOP: primo post reale solo su autorizzazione esplicita.

### Phase 18 — ONLYFANS PROVIDER CONNECTION (The Only API) (Status: COMPLETED — READ-ONLY PASS; OF_REAL_WRITE_CALLS=0; nessun post/upload/schedule)
- [x] secrets solo in `backend/.env` (git-ignored): THE_ONLY_API_KEY/CRM_ID; `THE_ONLY_OF_USER_ID` auto-scoperto; `OF_PROVIDER=the_only_api`, `OF_CONNECTION_ENABLED=true`, `OF_REAL_POSTING_ENABLED=false`, `OF_AUTO_SCHEDULER_ENABLED=false`
- [x] `backend/of_autopilot/` : `providers/base.py` (OFProviderAdapter astratto), `providers/the_only_api.py` (X-API-Key only, redazione log, write-guard, unwrap passthrough), `connection.py` (discovery + STOP rule), `routes.py` (`/api/admin/of-autopilot/connection|test-connection`)
- [x] verificato REALE read-only: key valida, CRM scope, 1 account onlyfans `latosegreto`, HEALTHY (users/me), schedules leggibili (0), gate pannello write OFF
- [x] Admin card minima `AdminOfAutopilot.js` (PROVIDER/CONNECTION/ACCOUNT/HEALTH/REAL POSTING OFF/AUTO SCHEDULER OFF), nav + route + api
- [x] `tests/test_of_provider_connection.py` 7/7 · testing agent 29/29 PASS 0 bug (`test_reports/iteration_26_onlyfans_autopilot.json`) · regressione 153 PASS (1 failure preesistente telemetry) · key assente da log/report/frontend
- [x] `OF_AUTOPILOT.md`
- STOP qui: primo post reale e OF Autopilot completo solo su autorizzazione esplicita.

### Phase 17 — X AUTOPILOT (Status: COMPLETED in preview — MOCK, X NOT_CONNECTED, scheduler OFF, 0 chiamate X, nessun post reale)
Decisioni utente: FOTO+FOTO → SINGLE_POST (priorità 1); con video → THREAD (main PUBLIC + reply SECRET), thread = una sola pubblicazione logica; PARTIAL_FAILED/THREAD_SECRET_FAILED senza duplicati; X_SAFE leggero; CONNECTION_STATUS=NOT_CONNECTED separato da MOCK_MODE=TRUE.
- [x] `backend/x_autopilot/` (MockXAdapter + RealXAdapter skeleton, media PUBLIC+SECRET con X-safe e link OF validato, copy IT contrasto + OF reale ≤280, engine con due cursori/lock/slot `x_*`, jobs tick 300s, routes `/api/admin/x-autopilot/*` incl. `preview`)
- [x] env preview: `X_AUTOPILOT_MOCK=true`, `X_AUTO_SCHEDULER_ENABLED=false`, `X_ITALY_AUDIENCE_MODE=true` (nessuna credenziale X)
- [x] Admin: `AdminXAutopilot.js` + nav + route + `adminApi.js` (xAp*)
- [x] `tests/test_x_autopilot.py` 16/16 PASS · testing agent 37/37 PASS 0 bug (`test_reports/iteration_25_x_autopilot.json`) · regressione 136 PASS (failure preesistenti non correlate: telemetry password_scrubbing; test Telegram env preview)
- [x] `X_AUTOPILOT.md`
- Prossima fase (solo su richiesta utente): credenziali X, RealXAdapter operativo, MOCK=false, 1 post reale via PUBBLICA ORA, poi scheduler.

### Phase 16 — INSTAGRAM AUTOPILOT (Status: COMPLETED in preview — MOCK, Meta NOT_CONNECTED, scheduler OFF, 0 chiamate Meta, nessun post reale)
Decisioni utente: CONNECTION_STATUS=NOT_CONNECTED + MOCK_MODE=TRUE mostrati separatamente; Telegram completamente fuori fase (non toccato).
- [x] pacchetto `backend/instagram_autopilot/` (adapter Meta skeleton + MockMeta, media PUBLIC-only con filtro IG-safe, caption IT LLM/template + CTA "link in bio" + 3-6 hashtag, engine con coda/stato/cursori/lock/slot INDIPENDENTI `instagram_*`, jobs tick 300s nello scheduler esistente, routes `/api/admin/instagram-autopilot/*`)
- [x] env preview: `INSTAGRAM_AUTOPILOT_MOCK=true`, `INSTAGRAM_AUTO_SCHEDULER_ENABLED=false`, `INSTAGRAM_ITALY_AUDIENCE_MODE=true` (nessuna credenziale Meta)
- [x] Admin: `AdminInstagramAutopilot.js` + nav + route + `adminApi.js` (igAp*)
- [x] `tests/test_instagram_autopilot.py` 16/16 PASS · testing agent PASS 0 bug (`test_reports/iteration_24_instagram_autopilot.json`) · regressione 121 PASS (2 failure preesistenti non correlate: telemetry password_scrubbing; test Telegram che legge env preview)
- [x] `INSTAGRAM_AUTOPILOT.md`
- Prossima fase (solo su richiesta utente): collegamento Meta (INSTAGRAM_ACCESS_TOKEN/USER_ID/APP_ID), MOCK=false, 1 post reale via PUBBLICA ORA, poi scheduler.

### Phase 15 — TELEGRAM AUTOPILOT (Status: COMPLETED in preview, mock — READY; scheduler OFF; nessun post reale)
- [x] modulo `telegram_autopilot/` (client+mock, eligibility, copy LLM/template, engine, jobs, routes) + Admin page + 16 test + testing agent 30/30
- [x] token solo in backend/.env, filtro redazione log httpx, nessuna esposizione
- Prossimi passi utente: Re-publish, env produzione (MOCK=false, AUTO_SCHEDULER false), test reale con 1 modella via PUBBLICA ORA, poi autorizzazione scheduler

### Phase 14C — Technical SEO Cleanup finale (Status: COMPLETED in preview — attende Re-publish utente)
- [x] soft-404 SPA (noindex,follow + no canonical/JSON-LD/og + 404 UI) su profili/categorie/articoli/landing/generica
- [x] Age Gate h1 → div (VISUAL_DIFF = NONE, 0 px diff vs produzione)
- [x] sitemap/orfane/H1 verificati su DOM renderizzato; regression 22/22 PASS; pytest 121 PASS
- Dopo il deploy: SEO Autopilot resta READ_ONLY, nessuna nuova landing, monitoraggio GSC

### Phase 14B — Technical SEO Foundation (Status: COMPLETED in preview — attende Re-publish utente)
- [x] audit produzione sola lettura (HTTP + Chromium + URL Inspection 15 URL): **BASE SEO INDICIZZABILE**, 0 blocchi tecnici; Home INDEXED, 12 URL discovered-not-indexed, 2 orfane, /articoli fuori sitemap, soft-404
- [x] fix minimi in preview: `/articoli` in sitemap (v1_seo.py) + link categorie nel Footer (Footer.js) — produzione NON modificata (verificato dopo: sitemap prod 30 URL, senza /articoli)
- [x] `foundation.py` + endpoint `/foundation` + `run/foundation` + 2 test (26/26 PASS)
- Da fare (utente): Re-publish; poi ri-eseguire foundation su produzione e richiedere indicizzazione delle URL 'Rilevata ma non indicizzata'
Fatto (agent-tested):
- [x] 14.0 mode OFF/READ_ONLY/FULL (FULL_LOCKED nel codice, `require_full` → WriteBlocked/423)
- [x] store `seo_ap_*` + decision log + run log + **snapshot pubblico hash before/after** (PUBLIC_MUTATIONS)
- [x] GSC sync riusando `google_search` (adapter raw, paginato, snapshot giornalieri non sovrascritti, 7v7/28v28/90)
- [x] matrice creator, keyword universe (seed+GSC+DB+LLM_SUGGESTION), intent a regole, clustering deterministico + merge LLM guardati
- [x] opportunity engine A–F, page map, cannibalizzazione, weekly learning, backlog
- [x] landing planner + quality gate (SEO_DRAFT_PROPOSAL / REJECTED_BY_QUALITY_GATE, hold senza GSC)
- [x] crawler tecnico + audit adult + render audit (Playwright ≤30/g) + URL Inspection selettiva (solo host = proprietà)
- [x] 4 job nello scheduler `v1_jobs` + `/api/admin/seo-autopilot/*` + pagina Admin “SEO Autopilot”
- [x] `tests/test_seo_autopilot.py` 24 PASS · suite completa 119 PASS (1 failure pre-esistente `test_telemetry_phase12b::password_scrubbing`, event-loop del harness, riproducibile anche senza i nuovi test)
- [x] `SEO_AUTOPILOT.md`
- [x] testing agent: 36/36 PASS (backend + frontend + regressione pubblica) — `test_reports/iteration_phase14_seo_autopilot.json`
- Nota: in preview la piattaforma serve `X-Robots-Tag: noindex` (atteso, riportato come INFO); GSC proprietà produzione con 0 impression → metriche UNKNOWN/HOLD (onesto).

---

## 4) Success Criteria
- Trasformazione Lato Pubblico→Segreto: stessa URL, zero refresh, 600–1200ms, percezione “luxury cinematic”.
- Home: griglia premium + filtri+search.
- Conversion: CTA OnlyFans tracciate.
- Admin: workflow publish robusto.
- SEO best-possible (senza SSR): meta dinamici, canonical, OG, structured data, sitemap/robots.
- ChatGPT control: universal dispatcher + registry + scopes + SAFE/REVIEW + audit/session + rollback.
- **Phase 14 (SEO AUTOPILOT READ_ONLY) è completata solo se:**
  1) `SEO_AUTOPILOT_MODE=READ_ONLY` con `FULL` bloccato (nessuna write accidentale)
  2) integrazione GSC riusata e funziona quando connessa, oppure degrada a `NOT_CONNECTED` senza blocchi
  3) snapshot storico giornaliero non sovrascritto (confronti 7/28/90gg)
  4) keyword universe + clustering + intent + opportunity engine producono risultati auditabili
  5) landing planner genera solo draft (non pubblici) e quality gate blocca doorway/keyword spam
  6) crawler tecnico + render audit (initial vs rendered vs Google inspection) produce report
  7) admin “SEO Autopilot” mostra stato + KPI semplici + backlog + log
  8) test PASS, idempotenza PASS
  9) **PUBLIC_MUTATIONS = 0** (hash prima/dopo) — altrimenti FAIL
