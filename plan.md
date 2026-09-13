# plan.md — LATO SEGRETO (React + FastAPI + MongoDB)

## 1) Objectives
- Consegnare una web app premium 18+ **tutta in italiano** (pubblico + admin) per promuovere creator/modelle con profili OnlyFans.
- Mantenere e migliorare la feature distintiva: **trasformazione cinematografica** Lato Pubblico → Lato Segreto **sulla stessa pagina/URL, no refresh**.
- Conversione e attribuzione first‑party: funnel verso OnlyFans con tracking (ref/fonte/campagna) persistente e analytics reali (no fake stats).
- Architettura “future‑proof SEO”: dati/slug/metadata/contenuti nel backend; frontend responsabile del rendering (migrazione futura a SSR/prerender possibile senza cloaking).
- Performance mobile-first: lazy media, nessun jank, rispetto autoplay policy (muted/playsInline), fallback robusti.
- **UX Home:** sezione “**IN MOVIMENTO**” come **pellicola cinematografica** seamless/infinita (non carosello), che si trasforma insieme allo switch Pubblico/Segreto.
- **Obiettivo operativo (admin + GPT):** tramite API v2 + Capability Registry + Universal Dispatcher, permettere a ChatGPT di gestire in modo sicuro operazioni business (testi/SEO/landing/categorie/internal linking/rollback/approvals) senza mai diventare un backdoor (no DB raw, no shell, no secrets).
- **Nuovo obiettivo SEO (Phase 13 — GOOGLE SEO CORE):** rendere LATO SEGRETO tecnicamente “perfetto per Google” (scopribilità, indicizzabilità, sitemap corretta, landing pubbliche controllate) + integrazione Search Console (Sitemap sync, URL Inspection, Search Analytics) **minimizzando lo scope** e riusando Phase 9–12.

**Stato attuale (snapshot)**
- Phase 1–8: completate (agent-tested). Pubblico + Admin stabili.
- Phase 9–11: SUPER API + ChatGPT control layer v1: completate e verificate in produzione.
- Phase 12A: Total Site Control API v2: completata, deployata in produzione, contratto GPT v2 robusto (parameters/parameters_json/request_example), FULL business mode abilitato (`ai_write_enabled=true`) con chiave READ_ONLY di fallback.
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

**Stato:** completata (agent-tested).

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
- v2 `/api/v2/ai/*` (12 primitive universali) + registry 97 capability.
- Preview/execute policy corretta (preview scopes deterministici + conditional scopes).
- Contratto GPT Action v2 robusto: `parameters` required, descrizioni esplicite, `parameters_json` fallback, `getCapability` include `required_parameters`, `example_parameters`, `request_example`, `execute_access`, `preview_access`.
- Produzione: `ai_write_enabled=true` (FULL), chiave `ChatGPT Production READ_ONLY` ancora attiva; bozza `test-v2-giulia` presente, non pubblica.

---

### Phase 13 — GOOGLE SEO CORE — Status: IMPLEMENTATA IN PREVIEW (agent-tested; richiede deploy + env Google dell'utente) (reduced scope, user-approved) — Status: PLANNED
**Obiettivo:** rendere il sito tecnicamente indicizzabile, scopribile e monitorabile con dati reali Google (Search Console: sitemap sync, URL inspection, analytics) senza costruire un “mega growth autopilot”.

#### 13.0 Google SEO CORE — Audit (prima di modifiche)
**Fatti osservati / rischi attuali (produzione)**
- SEO head è **client-side** (SPA): `frontend/src/lib/seo.js`.
- Canonical attuale di default = `window.location.href` (include query): rischio canonical non stabile.
- Age gate: overlay `fixed` ma contenuto sotto esiste; va verificato se Google indicizza contenuto o vede ostacoli (non “cloaking”, ma può impattare rendering).
- Sitemap: esistono **due implementazioni divergenti**:
  - `/api/sitemap.xml` (routes_seo.py) senza `lastmod`, senza landing, e logica separata.
  - `v1_seo.sitemap_entries()` ha `lastmod` e include landing ma usa **flag/config diverso** (oggi controlla `(cfg.get('landings') or {}).get('public_routes')`, mentre il gating reale è `flags.public_landing_routes`).
- Root `/sitemap.xml` restituisce HTML SPA (non sitemap) → ok se robots punta a `/api/sitemap.xml`, ma è un footgun.
- Robots: `frontend/public/robots.txt` punta correttamente a `https://secret-side.emergent.host/api/sitemap.xml`.
- Landing: backend espone `GET /api/landings/{slug}` (pubblico) dietro flag `flags.public_landing_routes` (oggi OFF di default).
- Frontend: **manca route `/l/:slug`** → anche se API pubblica fosse attiva, la pagina landing non sarebbe renderizzata come route SPA.
- Google credentials: nessuna configurazione attiva lato env; Google libs presenti (google-auth, google-api-python-client) ma integrazione strutturata assente.

**Deliverable audit:** `GOOGLE SEO CORE AUDIT` (doc) con:
- sitemap/robots/canonical/noindex status
- landing route status
- readiness per GSC (property, service account)
- elenco gap che blocca indicizzazione/monitoraggio

#### 13.1 Sitemap Engine — consolidamento (core)
**Obiettivo:** un’unica sorgente di verità sitemap, con lastmod e inclusione corretta delle landing.
- Unificare `/api/sitemap.xml` per usare `v1_seo.sitemap_entries()` (o spostare la logica in un unico modulo) e includere:
  - home
  - modelle pubblicate e indexable (noindex/robots)
  - landing pubblicate e indexable **solo se** `flags.public_landing_routes=true`
  - categorie indicizzabili (se appropriato)
- lastmod reale (almeno `updated_at` per modelle, `data_aggiornamento` per articoli, `updated_at` per landing se presente).
- Escludere: draft, archived/is_deleted, noindex.
- Validazione XML + deduplicazione.
- Opzionale: sitemap index se URL crescono.

#### 13.2 Landing pubbliche `/l/{slug}` (core)
**Obiettivo:** render pubblico coerente + indexability controllata.
- Frontend: aggiungere route SPA `/l/:slug` con pagina `LandingPage` che:
  - chiama `/api/landings/{slug}`
  - usa `setSeo()` con canonical pulito (senza query) e JSON-LD coerente con `LandingIn.seo`.
- Backend: mantenere gating con `flags.public_landing_routes`.
- Attivazione `flags.public_landing_routes=true` **solo dopo test**.

#### 13.3 Google Search Console integration layer (core)
**Struttura:** `backend/google_search/` (modulare, niente chiamate sparse)
- `config.py`: flag e property url (solo admin umano modifica; AI non può gestire segreti)
- `auth.py`: service account (ADC / JSON via env)
- `client.py`: httpx + retry/backoff, timeout, user-agent, error mapping
- `sitemap.py`: list/submit sitemap, debounce, sync log
- `inspection.py`: URL Inspection (cache + quota guard)
- `analytics.py`: Search Analytics (summary + queries)
- `schemas.py`: dataclass/pydantic per risultati normalizzati
- `mock.py`: adapter mock per test senza credenziali

**Config (solo env, mai esposta):**
- `GOOGLE_SEARCH_ENABLED`
- `GOOGLE_SEARCH_PROPERTY` = `https://secret-side.emergent.host/`
- `GOOGLE_APPLICATION_CREDENTIALS_JSON` (o path gestito dalla piattaforma)
- `GOOGLE_SEARCH_SITEMAP_SYNC_ENABLED`
- `GOOGLE_SEARCH_ANALYTICS_ENABLED`
- `GOOGLE_SEARCH_INSPECTION_ENABLED`

#### 13.4 Persistenza stato Google per URL (core minimal)
Nuove collections (minime):
- `google_search_status`: per URL (entity_type, entity_id/slug, indexability snapshot, google inspection snapshot, timestamps)
- `google_search_sync_log`: submit/list sitemap + errori + last submit
- `google_search_analytics_cache`: aggregati (28d) + top queries per pagina

Retention e indici:
- index su `url`, `entity_type+entity_id`, `last_inspection_at`, `last_sync_at`.

#### 13.5 Capability v2 (solo indispensabili)
Aggiungere capability al registry (no nuovi GPT endpoints, solo Universal Dispatcher):
- `google.status` (connessione + property + quote status + ultimo sync)
- `google.sitemap.sync` (submit/debounce; SAFE o REVIEW in base all’impatto)
- `google.url.inspect` (inspect 1 url; cache-aware)
- `google.analytics.summary` (clicks/impressions/ctr/position range)
- `google.analytics.queries` (top queries for page)
- `seo.indexability.audit` (HTTP 200, robots/noindex, canonical, title/meta/H1, JSON-LD validate, internal links count)
- `growth.prepare_model` (workflow orchestrato: SEO fields + safe fixes + readiness + sitemap include + optional submit)

Risk policy:
- read/inspect/analytics: SAFE
- sitemap submit: REVIEW_REQUIRED o SAFE con rate guard (da definire in audit)

#### 13.6 Workflow “Completa e prepara per Google” (core)
Nuovo workflow orchestrato (capability `growth.prepare_model`) che:
1) find model
2) audit readiness (mancanze real data segnate `MISSING_REAL_DATA`)
3) aggiorna testi/SEO SAFE
4) `seo.audit` + `seo.safe_fix` (solo SAFE)
5) verifica indexability tecnica
6) prepara landing solo se pubblicamente attivabile e utile (minimo: non creare spam)
7) valida
8) aggiorna sitemap
9) se Google enabled: submit sitemap (debounced) + opzionale inspect (manual/limit)

Invarianti:
- Mai inventare OnlyFans/Instagram/TikTok/età (richiedere input).
- Media upload non obbligatorio (utente carica manualmente).

#### 13.7 Test (minimi indispensabili)
- `tests/test_phase13_google_core.py`:
  - sitemap unificata: no draft/archived/noindex, lastmod presente, landing incluse solo se flag ON
  - landing route `/l/:slug` (frontend route + backend gating)
  - google adapter mock: status/sitemap sync/inspection/analytics
  - capabilities v2: parsing parameters/parameters_json, scopes, READ_ONLY/FULL invariati, no secrets
  - regressioni Phase 12: `verify_production_v2.py`, `gpt_action_contract_v2.py`
- Estendere `verify_production_v2.py` con check sitemap/robots/canonical/landing.

#### 13.8 Deliverables
- `PHASE13_GOOGLE_SEO_CORE_REPORT.md`:
  - audit iniziale
  - cosa riusato vs nuovo
  - file modificati
  - nuove collections + indici
  - capabilities aggiunte + scopes + risk
  - stato landing route
  - istruzioni passo-passo per Service Account (azioni utente su Google)
  - output test (PASS/FAIL) + regressioni

---

## 3) Next Actions
1. Phase 13.0: produrre audit (no code changes) + checklist azioni utente per Service Account e proprietà GSC.
2. Implementare Phase 13.1–13.3 (sitemap unificata + landing route SPA + layer google_search con mock).
3. Aggiungere capabilities core Phase 13.5 e workflow Phase 13.6.
4. Test minimi Phase 13.7 + regressioni Phase 12.
5. Deploy controllato e verifica produzione (nessun segreto nei log; nessuna API pericolosa).

---

## 4) Success Criteria
- Trasformazione Lato Pubblico→Segreto: stessa URL, zero refresh, 600–1200ms, percezione “luxury cinematic”.
- Home: griglia premium + filtri+search.
- Conversion: CTA OnlyFans tracciate.
- Admin: workflow publish robusto.
- SEO best-possible (senza SSR): meta dinamici, canonical, OG, structured data, sitemap/robots.
- ChatGPT control: universal dispatcher + registry + scopes + SAFE/REVIEW + audit/session + rollback; GPT contract v2 robusto.
- **Phase 13 (GOOGLE SEO CORE) è completata solo se:**
  1) sitemap corretta e automatica (modelle+landing pubblicate; no draft/archived/noindex; lastmod reale)
  2) `robots.txt` coerente e punta alla sitemap corretta
  3) landing `/l/{slug}` realmente raggiungibili **solo** per landing pubblicate e con flag ON
  4) integrazione GSC pronta con service account (zero secrets via API)
  5) GPT può chiedere URL Inspection/Analytics e ricevere dati reali (o `UNKNOWN` se non disponibile)
  6) regressioni Phase 12 e API v1/v2 PASS

**Chiusura 13 (11/09, preview):** modulo `backend/google_search/` (config env-only, auth SA, client retry/log, mock, service), 4 collection + indici, sitemap unificata con lastmod/landing-flag/dedupe + `sitemap_dirty` (publish/unpublish/slug/canonical) + job `google_sitemap_sync` (debounce 6h), 7 capability (`google.status`, `google.sitemap.sync`, `google.url.inspect`, `google.analytics.summary`, `google.analytics.queries`, `seo.indexability`, `growth.prepare_model`) → registry 104/104 bound, frontend `LandingPage` `/l/:slug` + canonical pulito. Test `test_phase13_google_core.py` 7/7 + regressioni tutte verdi; harness produzione esteso (sezione p13). Audit: produzione senza X-Robots noindex, robots ok, sitemap ok; preview è noindex per piattaforma (atteso). Google NON ancora configurato: servono service account + variabili env (vedi CHATGPT_API.md §B) e aggiunta del SA alla proprietà GSC. Flag `public_landing_routes` OFF in produzione fino a decisione utente.

---

## Phase 12B — FIX DEFINITIVO `models.prepare_complete` compila TUTTO il formulario (Status: COMPLETED in preview, 13/09)
Bug reale (FLAVIA RUSSO): applicati solo badge/categorie/tag/CTA; SEO/bio/timing non compilati. Cause trovate:
1. split SAFE/REVIEW per **root** (`seo` intero in REVIEW perché `seo.title` è REVIEW → keywords/topics/alt/og mai applicati);
2. `seo.safe_fix` applicava solo issue già presenti in `seo_issues` → su bozza nuova (mai auditata) 0 fix;
3. `parameters_schema.fields` opaco + `MODEL_FIELDS_DOC` con nomi errati (`ritardo_secondi`, `audio.volume`…) → GPT non sapeva cosa inviare / inviava chiavi sbagliate accettate nei dict liberi (`regia`, `cta_temporizzata`);
4. readiness indistinta (media vs dati reali vs review).
Fix (solo questa capability, nessuna feature nuova):
- `backend/v1_prepare_fields.py` (nuovo): schema esplicito `PREPARE_FIELDS_SCHEMA` (FORM→DB, tipi, enum, range, esempi), filtro deterministico (media/stato/conferma_maggiorenne/chiavi sconosciute → `fields_dropped` con motivo), split per **path**, `readiness_breakdown` (MISSING_MEDIA / MISSING_REAL_DATA / PENDING_REVIEW / missing_text_not_provided), `EXAMPLE_FIELDS_FULL`.
- `backend/v1_capabilities.py`: workflow riscritto — 1 chiamata = 1 session: create → tutti i SAFE path in 1 patch → tutti i REVIEW path in **una** approval (con meta/og description derivate dalla bio proposta) → media → `run_audit(entity)` + `apply_issue_fix` per ogni SAFE issue (esclusi i campi già in approval) → readiness veritiera. `example_parameters` completo. `MODEL_FIELDS_DOC` corretto. Bindings estesi.
- Matrice formale: `/app/PREPARE_COMPLETE_MATRIX.md`.
- Test: `tests/test_prepare_complete_full_form.py` 3/3 (fixture `ZZTEST PREPARE …`, 37 path SAFE applicati, 8+2 REVIEW in 1 approval, approve senza perdita SAFE, altri modelli intatti, no publish, rollback.session → soft-delete, cleanup); `gpt_action_contract_v2.py` 35/35 (aggiornato per example_parameters completo); Phase 12 + 13 pytest 32/32; smoke 35/35; bindings 30/30; coverage 157/157. FLAVIA RUSSO non toccata (3 approval pendenti intatte).
- Da fare dall'utente: deploy in produzione, poi rilanciare `models.prepare_complete` su FLAVIA RUSSO (riuso bozza esistente per nome esatto: applica SAFE + 1 approval REVIEW).

**Verifica produzione 13/09 (post-deploy fix 12B):** `models.prepare_complete` BOUND v1.0 SAFE; `parameters_schema.fields` identico allo schema (20 proprietà, nested esplicite); `example_parameters` completo (17 campi + seo_safe_fix) = `request_example.parameters`; registry 104/104 bound / 0 unbound / 0 CRITICAL; GPT contract 35/35 in prod (READ_ONLY key, zero mutation); `verify_production_v2.py` 98/98 PASS; preview full-fields in prod: 37 SAFE + 9 REVIEW path, 0 dropped, nulla scritto. Mode produzione: FULL.
**Incidente e rimedio (13/09):** il primo run di `verify_production_v2.py` (harness scritto per READ_ONLY) ha usato una chiave operator con scope di scrittura su produzione FULL → 2 mutazioni reali: VANESSA BELLA badge `IN TENDENZA`→`prodcheck`→`x` e bozza `PRODCHECK NO` creata. Ripristino immediato via API versionata: rollback delle 2 versioni (badge di nuovo `IN TENDENZA`, analytics/seo come prima), `PRODCHECK NO` soft-deleted; nessun file caricato; chiavi temporanee revocate. Harness reso production-safe: chiave operator SOLO scope read-only + guardia ZERO MUTATION (snapshot prima/dopo) + codici blocco INSUFFICIENT_SCOPE/READ_ONLY_MODE. Le 3 approval REVIEW di FLAVIA RUSSO risultavano già scadute per TTL (30 min) prima di questa sessione: nessuna azione su Flavia.
