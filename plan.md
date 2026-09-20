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
- **Nuovo obiettivo OF (Phase 22):** estendere l’OF Autopilot in modo **semplice** per eseguire, per ogni modella, **FEED post + Mass DM** (a tutti i fan/subscriber) con stati separati e retry DM senza duplicare il feed — **MOCK ONLY per Mass DM** in questa fase.

**Stato attuale (snapshot)**
- Phase 1–8: completate (agent-tested). Pubblico + Admin stabili.
- Phase 9–11: SUPER API + ChatGPT control layer v1: completate e verificate in produzione.
- Phase 12A: Total Site Control API v2: completata, deployata in produzione, contratto GPT v2 robusto.
- Phase 13: GOOGLE SEO CORE: modulo `backend/google_search/` presente (status/sitemap sync/inspection/analytics) e pronto a essere riusato.
- Phase 4 + Tracking: Admin Analytics v2 e Tracking v2 completati (agent-tested), funnel chiuso 6 step, percorsi, device compare, video/scroll/engaged.
- Stato produzione: `https://secret-side.emergent.host`
- OnlyFans:
  - Provider The Only API con connessione read-only verificata.
  - **1 post reale** eseguito con successo su produzione (Vanessa Bella) come test controllato (Phase 20).
  - Copy caption OF aggiornato in workspace (Phase 21) — richiede redeploy per prod.

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

#### 14.1–14.19
*(immutato — vedi sezioni già implementate nel file precedente)*

---

## 3) Phase 14 — SEO AUTOPILOT READ_ONLY (Status: COMPLETED — PASS, PUBLIC_MUTATIONS=0)

### Phase 23 — 1 SOLO MASS MESSAGE REALE DI TEST (Vanessa Bella, post 2759765107) — Status: ROUTE PRONTA, IN ATTESA DI REDEPLOY UTENTE (0 write reali)
Decisione utente: via produzione (traccia in DB prod). Route admin `POST /api/admin/of-autopilot/mass-dm-test` {model_slug, provider_post_id, execute=false|true}
→ `engine.mass_dm_from_post`: pre-check READ-ONLY (account HEALTHY, gate false, post esistente/di latosegreto/media_count=2/vault id/link OF nel testo, DM abilitato, audience>0,
copy diverso dal feed, nessun DM già inviato per il post, hard cap 1 DM reale, scheduler off) → con execute=true e tutti PASS: gate on → 1 mass message ALL subscribers → verifica READ →
stato in `of_model_runs` (key `post:<id>`) → gate off in finally + verifica READ. Mai nuovo feed, mai altra modella.
- [x] Test mock: `tests/test_of_mass_dm.py` 8 PASS (dry run zero write, execute, duplicato STOP, modella errata STOP, post inesistente STOP, DM disabilitato STOP, gate ripristinato anche su FAIL)
- [x] Dry run READ-ONLY reale dal workspace sul post 2759765107: SOURCE_POST_FOUND, account latosegreto, SOURCE_MEDIA_COUNT=2, VAULT_MEDIA_IDS_FOUND=2, HEALTHY, gate false (FAIL attesi solo per modello assente nel DB workspace e DM disabilitato)
- [x] Utente: Secrets prod `OF_MASS_DM_ENABLED=true`, `OF_MASS_DM_MOCK=false` impostati (verificati via status prod). MA il redeploy dei Secrets ha ripubblicato il codice precedente: `POST /mass-dm-test` → 404 in prod (200 nel workspace). STOP a zero write.
- [x] Redeploy codice fatto: route disponibile in prod (200). Dry-run prod: 19/20 PASS; FAIL `MASS_DM_TARGET_ALL_FANS` perché `POST /api2/v2/messages/queue/size` è bloccato dal gate account (403 FORBIDDEN con `allow_of_write_actions=false`). STOP, zero write.
- [x] Fix: audience pre-gate via READ `users/me.subscribersCount` (prod = 2301 subscriber); dopo apertura gate ri-controllo esatto `queue/size` (>0 altrimenti ABORT senza invio, gate ripristinato). Test mock 8 PASS, regressione 36 PASS.
- [x] Utente "DEPLOY FATTO" (2°): dry-run prod eseguito 2 volte + polling 10 min → produzione risponde ancora con il codice PRECEDENTE (check `MASS_DM_TARGET_ALL_FANS(audience>0)`, `AUDIENCE_ERROR=FORBIDDEN`, nessun `SUBSCRIBERS_COUNT`) sebbene il fix sia in HEAD (commit 9e1f3a9). 19/20 PASS, STOP zero write.
- [x] Deploy ok (21:00): dry-run prod 20/20 PASS (SUBSCRIBERS_COUNT=2301) → execute=true → gate aperto → `POST /api2/v2/messages/queue/size {queueBuyers: []}` = **0** → **ABORTED_EMPTY_AUDIENCE** (safety): nessun DM inviato, gate ripristinato e verificato false. TOTAL_REAL_MASS_DM_SENT=0.
- Causa: la modalità passthrough documentata "queueBuyers [] = all subscribers" non risolve l'audience su OnlyFans (size 0). Alternativa documentata dal provider: CRM `POST /accounts/{id}/messages/mass` con `audience.type` (`active`=subscriber correnti | `all`=anche scaduti) + `dry_run` (recipients + sample) → invio sincrono seriale (fino a 5.000 in una request), nessun queue id, verifica via READ chat di un fan campione.
- [x] Decisione utente: CRM `/messages/mass`, `audience.type=all`, dry_run provider obbligatorio poi invio, senza test ridotto.
- [x] Implementato: adapter `mass_message_crm` (dry_run read_post / send write, timeout 3600s) + `get_chat_messages` (verifica read-back chat fan campione); engine: run `SENDING` prima dell'invio (duplicati bloccati anche durante/dopo timeout), dry_run recipients>0 altrimenti ABORT, invio, read-back su 3 fan campione, marker `crm:<id>`, UNVERIFIED mai rispedito, FAIL definitivo solo su 4xx; route `background=true` + `GET /mass-dm-test/{post_id}` (polling). Test mock 9 PASS, regressione 37 PASS.
- [x] Deploy ok (21:27): pre-check 20/20 PASS → gate on → provider `dry_run:true` (`audience.type=all`) → **recipients=0** → ABORTED_EMPTY_AUDIENCE, nessun invio, gate ripristinato e verificato false. TOTAL_REAL_MASS_DM_SENT=0.
- Causa (READ-ONLY): la CRM risolve l'audience dalla **subscriber cache** del provider, che per latosegreto è vuota (`total=0`, `last_refreshed_at=null`, `polling_enabled=0`). OnlyFans riporta 2301 subscriber. Serve `POST /accounts/{id}/subscribers/refresh` (sync asincrono documentato, 202 + status) prima di poter inviare.
- [x] Decisione utente: REFRESH AUTOMATICO della subscriber cache prima di OGNI mass DM (definitivo), CRM audience.type=all, dry_run obbligatorio, SENDING prima dell'invio, timeout→UNVERIFIED, refresh fail→no DM/no feed/no advance, retry solo refresh+DM.
- [x] Implementato: adapter `subscribers_refresh_start` (POST subscribers/refresh 202) + `subscribers_refresh_status` (GET, stato job normalizzato + cache {total, active, expired, last_refreshed_at}); mock async pending→completed con knob (fail/stuck/empty/new fans); engine `_refresh_subscribers` (poll controllato, `OF_REFRESH_MAX_WAIT_MINUTES` default 10, `OF_REFRESH_POLL_SECONDS` 10) + flusso condiviso `_execute_mass_dm` (gate→refresh→dry_run>0→SENDING→invio→read-back→gate off) usato da ciclo e da `mass-dm-test`; campi refresh in `of_model_runs`; attesa vault id (4×8s); admin pill FAN REFRESH + Audience.
- [x] Test mock `tests/test_of_mass_dm.py` 16 PASS; regressione OF 44 PASS (2 failure pre-esistenti ambientali); testing agent iteration_29: 0 bug, 0 write reali.
- [ ] Utente: Deploy ultima versione → "DEPLOY FATTO" → `/tmp/prod_mass_dm_crm.py` (dry-run → execute background → poll → report) → STOP
- [ ] Poi: dry run prod → se tutti PASS → execute=true (1 solo DM) → report → STOP

### Phase 22 — OF AUTOPILOT FEED + MASS MESSAGE (MOCK ONLY) — Status: COMPLETED in workspace (mock only; testing agent iteration_28 0 bug; OF_REAL_MASS_DM_SENT=false; scheduler OFF; no deploy)
**Obiettivo:** per ogni modella della coda:
1) FEED POST → verifica `FEED_CONFIRMED`
2) MASS MESSAGE a **tutti i fan/subscriber** → verifica `MASS_DM_CONFIRMED`
3) solo dopo entrambi → avanza coda.

**Vincoli assoluti (questa fase):**
- NON creare analytics, segmentazione avanzata, dashboard pesanti.
- NON inviare Mass Message reali: `OF_MASS_DM_MOCK=true`, `OF_MASS_DM_ENABLED=false`, `OF_REAL_MASS_DM_SENT=false`.
- NON attivare scheduler: `OF_AUTO_SCHEDULER_ENABLED=false`.
- NON modificare il comportamento del FEED reale già esistente.
- Provider: sempre `OFProviderAdapter → TheOnlyAPIAdapter`, **solo endpoint documentati**.
- Protezione duplicati:
  - Feed e DM con stato separato: `FEED_STATUS` / `MASS_DM_STATUS`.
  - Se FEED ok ma DM fail: **ritenta solo DM**, mai ripubblicare feed.
  - Se DM già inviato: **mai inviarlo due volte**.

#### 22.1 Storage (semplice)
- Nuova collezione leggera (nome indicativo): `of_model_runs` con chiave composta `(model_id, cycle_number)`:
  - `feed_status`: PENDING|CONFIRMED|FAILED
  - `mass_dm_status`: PENDING|CONFIRMED|FAILED
  - `feed_post_id` (provider_post_id)
  - `mass_dm_id` (queue_id o message id, se disponibile)
  - `public_upload_id` / `secret_upload_id` (riuso tracking già esistente in `of_media_uploads`, nessun nuovo sistema)
  - `feed_caption_hash` / `dm_copy_hash` per dedupe
  - timestamps e last_error.

#### 22.2 Copy
- Feed: usa già Phase 21 (format LATO PUBBLICO → LATO SEGRETO + hook + 💋 CTA + link DB).
- Mass DM: copy **più diretto** e **diverso** dal feed:
  - Formato:
    - `👀 Hai già scoperto [NOME]?`
    - `✨ LATO PUBBLICO` + 1 frase
    - `🔥 LATO SEGRETO` + 1 frase
    - `❤️‍🔥 Scoprila qui:`
    - link OF reale DB
  - Regola: `FEED_AND_DM_COPY_DIFFERENT` (hash/text differente; mai riusare identico).

#### 22.3 Media Mass DM
- Usa la **stessa coppia** della modella corrente: 1 Public + 1 Secret.
- Stesso `model_id` (SAME_MODEL guard), stesso ordine Public→Secret.
- **Nota provider/documentazione:** i mass DM endpoint documentati richiedono `mediaFiles` come **vault media IDs** (non l’oggetto upload). In MOCK useremo IDs simulati.

#### 22.4 Provider (documentato) — progettazione
- The Only API docs (Messaging & mass DM / Posting) indicano due possibili superfici:
  1) **CRM normalized**: `POST /accounts/{of_user_id}/messages/mass` con `dry_run` (default true) + audience filters. (documentato)
  2) **OnlyFans passthrough**: `POST /api2/v2/messages/queue` e `GET /api2/v2/messages/queue` + `POST /api2/v2/messages/queue/size` (presenti in OpenAPI).
- Per questo progetto: implementare Mass DM sulla superficie **documentata e verificabile** in mock:
  - create: `POST /api2/v2/messages/queue` (passthrough) con `queueBuyers: []` (tutti subscriber), `text`, `mediaFiles: [vault ids]`, `price: null`.
  - verify: `GET /api2/v2/messages/queue` (id presente) e/o audience size `POST /api2/v2/messages/queue/size`.
- In questa fase **non inviare**: gate `OF_MASS_DM_ENABLED=false` e `OF_MASS_DM_MOCK=true` impediscono qualunque chiamata reale.

#### 22.5 Engine flow (semplice, senza nuovi sistemi)
- Estendere `engine.run()` (o funzione dedicata minima) in modo che per la modella corrente:
  1) esegua FEED come oggi (mock o real) → `FEED_CONFIRMED` solo su verify.
  2) se `OF_MASS_DM_ENABLED=false` → saltare DM e **non cambiare** comportamento esistente (compatibilità).
  3) se DM abilitato:
     - se feed non confermato → DM non parte.
     - se DM già `CONFIRMED` → non reinvia.
     - se DM `FAILED` → ritenta solo DM.
- Scheduler: ogni slot = 1 modella, 1 feed + 1 dm. **Ma per questa fase** scheduler resta OFF per env.
- Publish-now: feed immediato → verify → dm immediato → verify → STOP su 1 modella.

#### 22.6 Admin UI (minima)
- Nel box “Prossima” mostra per la modella corrente:
  - `FEED: OK/PENDING/FAILED`
  - `MASS MESSAGE: OK/PENDING/FAILED`
- Niente dashboard complesse.

#### 22.7 Env gates (obbligatori)
- `OF_MASS_DM_MOCK=true`
- `OF_MASS_DM_ENABLED=false`
- `OF_REAL_MASS_DM_SENT=false`
- `OF_AUTO_SCHEDULER_ENABLED=false`
- Feed reale non modificato.

#### 22.8 Test (MOCK ONLY)
- Nuovo file: `tests/test_of_mass_dm.py` con check richiesti:
  - `FEED_CREATE=PASS`
  - `FEED_VERIFY=PASS`
  - `MASS_DM_CREATE=PASS` (mock)
  - `MASS_DM_VERIFY=PASS` (mock)
  - `MASS_DM_TARGET_ALL_FANS=PASS` (queueBuyers/audience = all)
  - `FEED_AND_DM_COPY_DIFFERENT=PASS`
  - `SAME_MODEL_MEDIA=PASS`
  - `CORRECT_MODEL_OF_LINK=PASS`
  - `NO_DUPLICATE_FEED=PASS`
  - `NO_DUPLICATE_MASS_DM=PASS`
  - `FEED_SUCCESS_DM_FAIL_RETRY_ONLY_DM=PASS`
- Mock provider: aggiungere knobs `fail_mass_dm`, `hide_mass_dm` per simulare failure/non-confirm.
- Nessuna chiamata reale: `OF_REAL_WRITE_CALLS` deve restare 0 durante i test.

#### 22.9 Stop condition
- Dopo test + regressione: STOP e report con:
  - `OF_MASS_DM_READY = TRUE/FALSE`
  - `OF_MASS_DM_MOCK = TRUE`
  - `OF_MASS_DM_ENABLED = FALSE`
  - `OF_REAL_MASS_DM_SENT = FALSE`
  - `MASS_DM_TARGET_ALL_FANS = PASS/FAIL`
  - `MASS_DM_MEDIA_PUBLIC_SECRET = PASS/FAIL`
  - `MASS_DM_COPY_DIFFERENT_FROM_FEED = PASS/FAIL`
  - `MASS_DM_DUPLICATE_PREVENTION = PASS/FAIL`
  - `FEED_SUCCESS_DM_FAIL_RETRY_ONLY_DM = PASS/FAIL`

---

### Phase 21 — OF CAPTION STYLE v2 (brand format ✨ LATO PUBBLICO / 🔥 LATO SEGRETO) — Status: COMPLETED in workspace (solo copy, motore intatto, 0 post reali)
- [x] Solo `backend/of_autopilot/caption.py`: struttura fissa NOME → ✨ LATO PUBBLICO → 🔥 LATO SEGRETO (+emoji) → hook/domanda → 💋 Scoprila su OnlyFans: + link OF reale dal DB (deterministico, fuori dalla parte creativa)
- [x] LLM: JSON {public, secret, hook}, solo dati reali (nome, frase, bio, categorie, tag, stile→aggettivi), emoji e stile hook suggeriti per ciclo, validazione hard (FORBIDDEN, inglese, URL/@, lunghezza) → fallback
- [x] Fallback deterministico combinabile: 13 public · 13 secret · 12 hook · 5 emoji, diversi per modella e per ciclo
- [x] `tests/test_of_caption_style.py` 4 PASS (10 check richiesti) · suite OF: caption/engine test PASS; 4 failure ambientali pre-esistenti/non legate al copy (workspace backend in modalità reale + OF_REAL_TEST_MAX_POSTS=1 nell'env: `admin_api_contract` x2, `writes_blocked` x2 — passano con env mock)
- [x] 5 anteprime LLM su 5 modelle mostrate all’utente; STOP (nessun publish). Produzione: richiede redeploy per usare il nuovo copy.

### Phase 20 — PRIMO POST REALE ONLYFANS CONTROLLATO (VANESSA BELLA, 1 solo post) — Status: COMPLETED — REAL_TEST_POST=PASS (1 post reale, provider_post_id 2759765107, gate ripristinato false, scheduler OFF)
Esito: utente ha rimosso il requisito bloccante OF_REAL_TEST_MAX_POSTS in produzione e autorizzato 1 tentativo. Pre-check 19/19 PASS -> publish-now unico -> POST_CONFIRMED (read-back: exists, account_ok, caption_ok, of_link_ok, media_count=2) -> write_gate restored=true verified_false=true -> TOTAL_REAL_POSTS_CREATED=1, SECOND_POST_CREATED=false, AUTOPILOT PAUSED. STOP: attesa revisione visiva utente su OnlyFans prima di qualsiasi automazione.

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
*(immutato)*

### Phase 16 — INSTAGRAM AUTOPILOT (Status: COMPLETED in preview — MOCK, Meta NOT_CONNECTED, scheduler OFF, 0 chiamate Meta, nessun post reale)
*(immutato)*

### Phase 15 — TELEGRAM AUTOPILOT (Status: COMPLETED in preview, mock — READY; scheduler OFF; nessun post reale)
*(immutato)*

### Phase 14C — Technical SEO Cleanup finale (Status: COMPLETED in preview — attende Re-publish utente)
*(immutato)*

### Phase 14B — Technical SEO Foundation (Status: COMPLETED in preview — attende Re-publish utente)
*(immutato)*

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
- **Phase 22 (OF FEED + MASS MESSAGE) è completata solo se (MOCK ONLY):**
  - `OF_MASS_DM_READY = TRUE`
  - `OF_MASS_DM_MOCK = TRUE`, `OF_MASS_DM_ENABLED = FALSE`, `OF_REAL_MASS_DM_SENT = FALSE`
  - `MASS_DM_TARGET_ALL_FANS = PASS` (in mock: queueBuyers/audience = all)
  - `MASS_DM_MEDIA_PUBLIC_SECRET = PASS`
  - `MASS_DM_COPY_DIFFERENT_FROM_FEED = PASS`
  - `MASS_DM_DUPLICATE_PREVENTION = PASS`
  - `FEED_SUCCESS_DM_FAIL_RETRY_ONLY_DM = PASS`
  - zero provider writes reali durante i test
