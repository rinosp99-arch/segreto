# LATO SEGRETO — ChatGPT Control API (Phase 10)

Strato di controllo **sicuro, deterministico, permissionato, auditabile e reversibile** che permette a ChatGPT (GPT Actions) di amministrare LATO SEGRETO tramite azioni esplicite. Nessun LLM lato server: ChatGPT interpreta il linguaggio, l'API esegue solo azioni strutturate. Il sito pubblico, il design, le animazioni e le API legacy (`/api`, `/api/admin`, `/api/v1`) restano invariati.

- Base: `/api/v1/ai` · OpenAPI ChatGPT: `GET /api/v1/ai/openapi.json` (pubblico, senza chiave) · Catalogo: `GET /api/v1/ai/capabilities`
- Auth: header `X-API-Key: ls_...` **oppure** `Authorization: Bearer ls_...`
- Header consigliati: `Idempotency-Key` (POST), `X-Request-ID` (correlazione; sempre restituito)
- Pannello: `/admin/motore → ChatGPT Control Layer`

## 1. Collegare ChatGPT (setup)
1. `/admin/motore` → **Crea chiave ChatGPT** (ruolo `AI_OPERATOR`). La chiave completa è visibile **una sola volta**; nel database restano solo `sha256(key)`, `prefix`, nome, ruolo, scopes, timestamp, revoca, creatore, contatori uso/errori, ultimo IP.
2. **Copia configurazione ChatGPT** (non contiene la chiave) → in ChatGPT: *Create a GPT → Actions → Import from URL* con `https://<dominio>/api/v1/ai/openapi.json` → Authentication: **API Key**, Auth type *Custom*, header `X-API-Key`, incolla la chiave.
3. **Test ChatGPT API** (pannello): crea una chiave temporanea (2 min), esegue 13 controlli reali (auth, chiave errata → 401, capabilities, scopes, CRITICAL bloccato, lettura modelle, analytics, dry-run, idempotenza, request-id, rate-limit headers, openapi, kill switch) e la elimina.
4. Kill switch / modalità FULL·READ_ONLY / batch / approvazioni / rate limit: sempre dal pannello (o `PATCH /api/v1/ai/control`, solo JWT admin).

Gestione chiave: **Ruota** (nuova chiave mostrata una volta, la vecchia smette subito), **Disattiva/Riattiva**, **Revoca** (definitiva). `GET /api/v1/auth/keys/{id}/usage` → richieste, errori, ultimo IP, richieste/min, azioni AI 24h. Nessun endpoint restituisce mai la chiave o l'hash.

## 2. Contratto di risposta
Successo:
```json
{ "ok": true, "action": "models.update", "summary": "Alessia aggiornata (tag); stato PUBLISHED; nessun requisito mancante.",
  "data": {...}, "warnings": [], "next_steps": ["Annulla: POST /api/v1/ai/rollback {version_id:'…'}"],
  "request_id": "…", "changes": [{"field":"tag","before":[...],"after":[...]}], "approval_required": false }
```
Approvazione richiesta (`approval_required: true`) → in `approval`: `{type, token (apr_…), expires_at, target, before, after, reason, confirm_with}`.
Errore:
```json
{ "ok": false, "code": "INSUFFICIENT_SCOPE", "summary": "Permessi insufficienti", "data": {"missing_scopes": ["models:publish"]},
  "warnings": [], "next_steps": ["Chiedi all'amministratore di aggiungere gli scope: models:publish"], "request_id": "…", "approval_required": false }
```
Codici: `AUTH_REQUIRED, INVALID_API_KEY, API_KEY_REVOKED, API_KEY_DISABLED, API_KEY_EXPIRED, INSUFFICIENT_SCOPE, AI_API_DISABLED (503), READ_ONLY_MODE, BATCH_DISABLED, RATE_LIMITED (429 + Retry-After), NOT_FOUND, AMBIGUOUS_REFERENCE (409 + matches), VALIDATION_FAILED (422), PUBLICATION_BLOCKED, SEO_REVIEW_REQUIRED, CRITICAL_ACTION_BLOCKED, APPROVAL_REQUIRED, APPROVAL_EXPIRED (410), APPROVAL_INVALID, APPROVAL_DISABLED, IDEMPOTENCY_CONFLICT, MEDIA_VALIDATION_FAILED, CONFLICT (409, etag stale), INTERNAL_ERROR, BAD_REQUEST, IP_NOT_ALLOWED`.

## 3. Policy di esecuzione sicura
| Livello | Comportamento | Esempi |
|---|---|---|
| **SAFE** | eseguita subito se lo scope c'è; versionata; rollback disponibile | tag, tema, categorie, ordine Home, fix SEO `SAFE_AUTO_FIX`, publish (solo se il validator passa) |
| **REVIEW_REQUIRED** | l'API prepara anteprima before/after + **token di approvazione** e **non applica nulla**; si applica solo con `POST /approvals/confirm {token}` dopo l'ok dell'utente | slug, nome, bio, bio_segreta, frase, onlyfans_url, seo.title/meta/canonical/robots/indexable, stato, issue SEO `REVIEW_REQUIRED`, publish landing senza scope `landing:publish` |
| **CRITICAL** | **mai** via API key: `403 CRITICAL_ACTION_BLOCKED` | chiavi/utenti/config/backup/webhook/delete definitivo, issue SEO `CRITICAL` (link OnlyFans, slug, pubblicazioni incomplete) |

Token di approvazione: single-use, TTL 30 min (config `ai.policy.approval_ttl_min`), legato ad **attore (chiave) + target + azione + hash del payload**; se il target cambia dopo l'anteprima → `409 CONFLICT` (precondizione `updated_at`); chiave diversa → `403 APPROVAL_INVALID`; riuso → `409 APPROVAL_INVALID`; scaduto → `410 APPROVAL_EXPIRED`. `GET /approvals` elenca i pending senza token.

`dry_run: true` (body) o `?dry_run=true` (query): nessuna scrittura, ritorna before / proposed_after / changes / warnings / livello policy / stato workflow prima→dopo. Disponibile su create/update/publish/unpublish/archive/restore/feature, SEO safe fix (singola/batch), landing create/update/publish, rollback.

Concorrenza: `expected_updated_at` (etag = `updated_at`) su update/publish/transizioni → `409 CONFLICT` se stale. Idempotenza: `Idempotency-Key` → replay identico con header `Idempotent-Replayed: true`, nessun duplicato.

## 4. Flag e modalità (safe default)
| Flag | Default | Effetto |
|---|---|---|
| `ai_api_enabled` | true | **Kill switch**: se false ogni chiamata con API key a `/api/v1/ai/*` → `503 AI_API_DISABLED`. JWT admin e API legacy continuano a funzionare. |
| `ai_write_enabled` | true | false = **READ_ONLY**: letture, audit, anteprime (`dry_run`) ok; scritture → `403 READ_ONLY_MODE`. Upload e conferme approvazioni (nessuna anteprima possibile) sempre bloccati. |
| `ai_batch_enabled` | true | false → `403 BATCH_DISABLED` |
| `ai_approval_flow_enabled` | true | false → le modifiche REVIEW non possono essere preparate (`APPROVAL_DISABLED`) |
| `public_landing_routes` | **false** | resta OFF: `GET /api/landings/{slug}` → 404 finché un admin non la attiva |

Non attivati da questa fase: `domain_it_migration`, `ssr_prerender`, `search_console_sync`, `ga4_production`, Telegram.

Rate limit dedicato AI: `ai.policy.rate_limit_per_min` (default 120, **minimo 10, non disattivabile**), per chiave `min(limite AI, limite chiave)`; header `X-RateLimit-Limit/Remaining`, `429 + Retry-After`.

## 5. Scopes (ruolo AI_OPERATOR)
`models:read|create|update|validate|publish|unpublish|archive|feature` · `media:read|upload|optimize|replace` · `seo:read|audit|safe_fix|review_prepare` · `landing:read|create|update|validate` (+ `landing:publish` **opzionale**, da concedere esplicitamente) · `analytics:read` · `system:status|daily_summary` · `rollback:read|execute` · `ai:execute` (obbligatorio su tutti gli endpoint AI) · letture: `experiments:read, health:read, alerts:read, jobs:read, config:read`.
Alias legacy Phase 9 (`models:write`, `seo:autofix`, `landings:write`, …) restano validi e implicano gli scope fini. Le API key non possono mai avere `keys:manage, users:manage, config:write, backup:manage, webhooks:manage, models:delete`.

## 6. Riferimenti naturali
`model` accetta: id · slug · nome esatto (case-insensitive) · nome parziale **non ambiguo** (sottostringa o prefissi di parola: "zeta test res 2" → "Zeta Testuale Resolver 2"). Più corrispondenze → `409 AMBIGUOUS_REFERENCE` con `data.matches [{id, nome, slug, status}]`; nessuna → `404 NOT_FOUND`. Le modelle eliminate non vengono mai scelte al posto di quelle attive.

## 7. Capacità (39 path, 35 capability) — estratto
| Frase utente | Endpoint |
|---|---|
| "Controlla Alessia" | `GET /models/{ref}/health` (pubblicazione, readiness, SEO score/issue, media/ALT/rotti, CTA, OnlyFans, sitemap/noindex, redirect, analytics, errori recenti, ultima modifica) |
| "Sistema la SEO in automatico" | `POST /seo/audit` → `POST /models/{ref}/seo/apply-safe-fixes` (score prima/dopo, conteggi SAFE/REVIEW/CRITICAL) → `GET /models/{ref}/seo/review` → `POST /models/{ref}/seo/review/{issue_id}/preview` (token) → `POST /approvals/confirm` |
| "Pubblica Vanessa" | `POST /models/publish` (sempre validator: `PUBLICATION_BLOCKED` + `missing`; `force` ignorato) |
| "Crea una landing italiana per Alessia" | `POST /landings` (bozza, targeting editoriale Italia, `geoblocking:false`) → `POST /landings/{ref}/validate` → `POST /landings/{ref}/publish` (scope o approvazione) |
| "Quale modella converte meglio in Italia negli ultimi 7 giorni?" | `POST /analytics/query {metric:"onlyfans_ctr", group_by:"model", country:"IT", period:"7d", sort:"desc", limit:10}` (sempre `sample_size`, `data_available`, `limitations`; mai dati inventati) |
| "Annulla l'ultima modifica fatta da ChatGPT" | `POST /rollback/preview {model, latest_ai:true}` → `POST /rollback {version_id}` (nuova versione, history intatta; ripetere → 409) |
| Comando strutturato | `POST /command {action, target, parameters, reason, dry_run}` — azioni: `models.find|create|update|validate|publish|unpublish|archive|restore|feature|health, media.upload, seo.audit|safe_fix|review_list|review_preview, landing.create|validate|publish, analytics.query, rollback.preview|execute, system.status|site_health|daily_summary|recommendations, batch.seo_safe_fix, approvals.confirm` |
| Salute sito / cosa sistemare | `GET /site-health`, `GET /daily-summary`, `GET /recommendations`, `GET /status` |
| Batch | `POST /batch/seo-safe-fix {selection: all|published|draft|category|ids, dry_run}` (risultati individuali, errori parziali riportati, max `ai.policy.max_batch`), `POST /batch/validate` |
| Attività | `GET /actions` (log AI), `GET /approvals` |

## 8. Audit e osservabilità
Ogni operazione in `ai_actions`: `actor, key_id, principal_type, source:"chatgpt", request_id, action, target, input (redatto: niente chiavi/token/base64), ok, summary, changes, version_ids, rollback_ref, before/after, reason, duration_ms, timestamp`. Le modifiche sono anche in `versions` (before/after, rollback non distruttivo) e `audit_logs`. Metriche (`GET /api/v1/ai/control`, JWT): richieste/min e /ora, errori, 429, success rate, p50/p95, mutazioni, rollback, approvazioni richieste/confermate, azioni critiche bloccate, top capability, ultima richiesta/errore.

## 9. Sicurezza
- Nessun accesso a shell, filesystem, Mongo raw, Python, env o segreti tramite l'API. Il testo salvato (bio, teaser, frase…) è **dato**, mai istruzione.
- Mai serializzati: `password_hash, key_hash, token_hash, api_key, jwt/webhook/env/db/storage secrets` (redazione centralizzata `redact()`; il valore `principal_type: "api_key"` è un'etichetta, non un segreto).
- Upload: solo da URL pubblico/base64 tramite `v1_media.upload_from_url` (blocco SSRF/IP privati/metadata, magic bytes, content-type, limiti dimensione, ffmpeg/Pillow, storage Emergent). In READ_ONLY sempre bloccato.
- Publish sempre tramite validator; delete definitivo, chiavi, utenti, config, backup, webhook solo JWT admin umano.

## 10. Test
- `cd /app && python -m pytest tests/test_ai_control.py -q` → 40 test (auth, scopes, CRITICAL, kill switch/READ_ONLY con dry-run, riferimenti, dry-run/etag/409, approvazioni single-use/actor/target-changed, prompt injection, publish blocked, SEO audit/safe/review/critical, landing, analytics, idempotenza, rollback history, SSRF/MIME, no secrets, dispatcher, capabilities/openapi, batch, rate limit, audit, **E2E A–F**).
- `python tests/test_phase10_agent.py` → 53 controlli (suite del testing agent, iteration_21).

---

# REAL GPT CONNECTION (Phase 11)

## Stato
- Codice pronto e verificato sull'ambiente preview (`https://secret-side.preview.emergentagent.com`).
- **Produzione `https://secret-side.emergent.host`: online e TLS valido, ma la build deployata è precedente alla Phase 9/10 (`/api/v1/ai/*` → 404). Prima del collegamento reale serve un redeploy dal pannello Emergent (operazione manuale dell'amministratore).**
- Il collegamento nell'account ChatGPT (creazione GPT, import schema, inserimento chiave) è un passaggio manuale dell'utente: **MANUAL CHATGPT STEP REQUIRED**.

## URL di produzione (dopo il deploy)
| Cosa | URL |
|---|---|
| API Base URL | `https://secret-side.emergent.host` |
| OpenAPI per GPT Actions (23 operazioni, ≤30) | `https://secret-side.emergent.host/api/v1/ai/openapi-chatgpt.json` |
| OpenAPI completa (riferimento, NON importarla nel GPT: 39 path > limite 30) | `https://secret-side.emergent.host/api/v1/ai/openapi.json` |
| Capabilities | `https://secret-side.emergent.host/api/v1/ai/capabilities` |
| Pannello | `https://secret-side.emergent.host/admin/motore` |

Il campo `servers[0].url` dello schema viene calcolato dall'host che serve la richiesta: importandolo dal dominio di produzione punta automaticamente alla produzione.

## Autenticazione (esatta)
- Metodo reale della SUPER API: `Authorization: Bearer <API_KEY>` (accettato anche `X-API-Key: <API_KEY>`).
- Nel GPT Builder: **Authentication → API Key → Auth Type: Bearer** → incolla la chiave. Lo schema dichiara un solo `securitySchemes.ApiKeyBearer` (`type: http, scheme: bearer`).
- Ruolo: `AI_OPERATOR`. Preset **Scopes READ_ONLY** (minimo privilegio, 18 scope): `models:read, models:validate, media:read, seo:read, seo:audit, seo:review_prepare, analytics:read, landing:read, landing:validate, rollback:read, system:status, system:daily_summary, health:read, alerts:read, jobs:read, experiments:read, config:read, ai:execute`.
- Con questi scope il `dry_run=true` è consentito (un'anteprima è un'operazione di lettura: `PREVIEW_SCOPE` in `v1_ai_policy.py`), mentre update/publish/upload/confirm/rollback reali rispondono `403 INSUFFICIENT_SCOPE` **anche in modalità FULL**. Nessuno scope di scrittura viene concesso nella prima sessione.

## Modalità server
`ai_api_enabled=true` · `ai_write_enabled=false` → **READ_ONLY** (verificato server-side: `GET /api/v1/ai/status → data.ai.mode = "READ_ONLY"`). Non passare a FULL automaticamente: solo decisione umana dal pannello.

## Configurazione GPT
Vedi `/app/CHATGPT_INSTRUCTIONS.md` (nome, descrizione, Instructions, conversation starters). Mai inserire la chiave nelle Instructions.

## Procedura (UI GPT Builder, settembre 2026)
1. ChatGPT → *Explore GPTs* → **Create** (o *My GPTs* → *Edit*).
2. Tab **Configure**: Name, Description, Instructions (copiare da `CHATGPT_INSTRUCTIONS.md`), Conversation starters.
3. In basso: **Create new action**.
4. **Authentication** (icona ingranaggio) → *API Key* → Auth Type **Bearer** → incolla la chiave creata in `/admin/motore` (preset READ_ONLY) → **Save**.
5. **Schema** → **Import from URL** → `https://secret-side.emergent.host/api/v1/ai/openapi-chatgpt.json` → **Import**. Le 23 operazioni compaiono in "Available actions".
6. (Solo per GPT pubblici) Privacy policy: `https://secret-side.emergent.host/privacy`.
7. **Preview** (colonna destra) → scrivi: *"Controlla lo stato di LATO SEGRETO."* → alla prima chiamata ChatGPT chiede conferma ("Allow") per il dominio.
8. `/admin/motore → ChatGPT Control Layer → Richieste ChatGPT`: deve comparire la richiesta (`GET /site-health` o `/status`, 200, kind read) con actor = nome della chiave.

## Test prompts e risultati attesi (READ_ONLY)
| Prompt | Operazione | Atteso |
|---|---|---|
| Controlla lo stato di LATO SEGRETO | getSiteHealth/getSystemStatus | dati reali, `data.ai.mode=READ_ONLY` |
| Controlla Francesca Rossi | findModel → getModelHealth | pubblicazione, SEO score, media, OnlyFans, analytics |
| Controlla tutta la SEO di Francesca Rossi | runSeoAudit | score + conteggi SAFE/REVIEW/CRITICAL, nessuna modifica |
| Sistema automaticamente gli errori SEO sicuri di Francesca | previewSafeSeoFixes `dry_run=true` | anteprima `would_fix`, DB invariato; senza dry_run → `READ_ONLY_MODE` |
| Quale modella converte meglio in Italia negli ultimi 7 giorni? | queryAnalytics strutturata (IT, 7d, onlyfans_ctr, model, desc) | ranking + sample_size + limitations; nessun vincitore se campione insufficiente |
| Fammi il riepilogo di oggi | getDailySummary | visite, Italia, funnel, click OF, SEO, alert, top, backup |
| Cosa dovrei sistemare adesso? | getRecommendations | lista per priorità, automatic/review/manual |
| Pubblica Francesca Rossi | publishModel `dry_run:true` | readiness/“già online”; publish reale → `READ_ONLY_MODE`/`INSUFFICIENT_SCOPE` |
| Controlla Alessia | findModel | `404 NOT_FOUND` (non esiste) |
| Controlla Mar | findModel | `409 AMBIGUOUS_REFERENCE` (Martina Conte, Sofia Marino) |

## Troubleshooting
- **Schema import failed**: verifica URL (https, dominio deployato con Phase 10), JSON valido (`curl <url> | python -m json.tool`), `openapi: 3.1.0`, ≤30 operazioni, operationId unici; se il dominio cambia, reimporta (il campo `servers` segue l'host).
- **Authentication failed / 401**: `AUTH_REQUIRED` = chiave non inviata (controlla Auth Type Bearer); `INVALID_API_KEY` = chiave errata/incollata male; `API_KEY_REVOKED` / `API_KEY_DISABLED` / `API_KEY_EXPIRED` = stato chiave nel pannello (ruota e reincolla).
- **403 INSUFFICIENT_SCOPE**: la chiave READ_ONLY non ha scope di scrittura: è il comportamento voluto; `data.hint` suggerisce `dry_run=true`.
- **403 READ_ONLY_MODE**: intenzionale (modalità server). Usa dry_run o attiva FULL manualmente dal pannello.
- **403 CRITICAL_ACTION_BLOCKED**: azione riservata all'admin umano (chiavi, utenti, config, backup, delete, issue SEO CRITICAL).
- **409**: `AMBIGUOUS_REFERENCE` (scegli tra `data.matches`), `CONFLICT` (etag stale / target cambiato dopo l'anteprima), `APPROVAL_INVALID` (token riusato).
- **429 RATE_LIMITED**: rispetta `Retry-After`; limite chiave/AI nel pannello (min 10/min).
- **503 AI_API_DISABLED**: kill switch OFF nel pannello.
- **Nessuna richiesta nel pannello**: la chiamata non è arrivata al server (schema che punta a un altro host, deploy non aggiornato, conferma "Allow" non data in Preview).

## Nota dati reali (dopo il primo redeploy)
Il catalogo di produzione è diverso dal preview: 10 modelle reali (VANESSA BELLA, ALESSIA GOLOSA, AURORA BIANCHINI, ZAIRA, AURORA CARUSO, CHIARA GRECO, GRETA SALA, VERONICA, SUSI, LARA). "Controlla Alessia" funziona; "Aurora" è volutamente ambiguo (409 con 2 alternative). I link OnlyFans reali usano il formato tracking `https://onlyfans.com/<user>/c<N>`, ora accettato dal validator (prima: falso positivo ERROR/CRITICAL su tutte le modelle).

## Health / alert: stato corrente vs storico
`getSiteHealth`, `getSystemStatus`, `getDailySummary`, `getRecommendations` usano `reconciled_health()`: se l'ultimo health check ha più di 10 minuti viene rieseguito (senza self-healing) e gli alert vengono riconciliati (condizione sparita → `stato: resolved`, `resolved_at`, `current: false`; la cronologia non viene mai cancellata). `health_overall` deriva SOLO dai check correnti. In `data.alerts` ci sono solo gli alert correnti (`current: true`), in `data.alerts_resolved_recent` quelli chiusi nelle ultime 24h; ogni alert espone `created_at/updated_at/checked_at/resolved_at/source`. Il check `onlyfans_links` è strutturale (regola canonica `onlyfans_url_status`, nessuna richiesta HTTP a OnlyFans); la raggiungibilità remota dei media è classificata a parte (`REMOTE_BLOCKED_WARNING`, `REMOTE_REACHABILITY_WARNING`, `REMOTE_MISSING`) e non è mai un verdetto di URL invalido.

## Verifiche automatiche Phase 11
`python tests/phase11_gpt_simulation.py` → simula le chiamate del GPT Action (Bearer) con una chiave READ_ONLY temporanea: 42/42 PASS (kill switch, READ_ONLY, dry-run, test A–I, ambiguo/inesistente, idempotenza, scope/auth negativi, rate limit, hash DB business before/after identico, metriche, attività, leak scan). Report: `/app/test_reports/phase11_simulation.json`.

---

# TOTAL SITE CONTROL API v2 (Phase 12A) — motore universale a capability

> Stato: **implementato e testato in PREVIEW** (agent-tested). **Non deployato in produzione.** Produzione: `ai_api_enabled=true`, `ai_write_enabled=false` (READ_ONLY), schema GPT **v1 (23 operazioni) invariato e ancora quello collegato al GPT reale**.
> Lo schema v2 è **separato**: quando l'utente deciderà il deploy, il GPT dovrà **re-importare** `GET /api/v2/ai/openapi-chatgpt.json` (12 operazioni). Nessun LLM interno: il backend resta deterministico.

## A. Perché v2
Al posto di un'operazione GPT per ogni funzione admin (centinaia), il GPT usa **12 primitive universali** e un **Capability Registry** allowlisted (`backend/v1_capabilities.py`) con **97 capability** in 14 categorie. Ogni capability è legata a un service esistente (nessuna logica duplicata) e dichiara: `id` e `capability_version` stabili (indipendenti dal nome della funzione Python), scope richiesti, rischio `SAFE | REVIEW_REQUIRED | CRITICAL`, `supports_dry_run`, `supports_rollback`, `supports_batch`, target (`model | media | alert | job | landing | category | none`), schema parametri, esempi, frasi naturali.

## B. Le 12 primitive (`/api/v2/ai`, Bearer = API key dedicata)
| operationId | Metodo/Path | Uso |
|---|---|---|
| `getCapabilities` | `GET /capabilities` | catalogo delle capability eseguibili dalla chiave (CRITICAL/UNBOUND/disabilitate/negate escluse) |
| `getCapability` | `GET /capabilities/{capability_id}` | contratto completo di una capability (parametri, esempi, rischio, stato binding) |
| `previewCapability` | `POST /preview` | **dry-run forzato**: stesso handler/validatore dell'esecuzione, nessuna scrittura |
| `executeCapability` | `POST /execute` | esecuzione (`dry_run` opzionale nel body); REVIEW → `approval_required` + token |
| `listApprovals` | `GET /approvals` | approvazioni pendenti (target/payload/time-bound) |
| `approveApproval` | `POST /approvals/{id}/approve` | conferma con token: **ri-verifica** READ_ONLY/scopes/deny prima di consumare il token |
| `rejectApproval` | `POST /approvals/{id}/reject` | rifiuto |
| `getJob` | `GET /jobs/{job_id}` | stato job/esecuzioni |
| `queryAnalytics` | `POST /analytics/query` | metriche reali (`model_views`, funnel, OnlyFans click…), mai valori inventati |
| `getSystemStatus` | `GET /status` | modalità, health riconciliato, registry (97 bound), alert correnti vs storici |
| `rollback` | `POST /rollback` | `rollback.session` / `rollback.version` / `rollback.window` (dry_run supportato) |
| `findModel` | `POST /models/find` | risoluzione riferimento naturale → modella (409 AMBIGUOUS_REFERENCE, 404 NOT_FOUND) |

Body di `preview`/`execute`:
```json
{"action": "models.update", "target": "Francesca", "parameters": {"changes": {"badge": "Nuova"}},
 "reason": "…", "session_id": "ses_…", "expected_updated_at": "<updated_at visto>", "dry_run": false}
```
`expected_updated_at` è accettato anche se il client lo mette dentro `parameters` o `parameters.changes` (viene estratto e applicato: 409 `CONFLICT` se il target è cambiato). Header opzionali: `Idempotency-Key` (replay identico → stessa risposta con `idempotent_replayed`, body diverso → 409 `IDEMPOTENCY_CONFLICT`), `X-Session-ID`.

## C. Ordine di enforcement del dispatcher (identico per preview ed execute)
1. registry → `UNKNOWN_CAPABILITY` 404 / `CAPABILITY_UNBOUND` 503 (binding non valido a startup: mai eseguibile) / capability disabilitata dal pannello
2. kill switch `ai_api_enabled`
3. scopes della chiave (le fine-grained; `capability_allow` **restringe soltanto**, mai amplia)
4. `capability_deny` **prevale sempre** su allow → 403 `CAPABILITY_DENIED`
5. READ_ONLY/FULL (`ai_write_enabled`): in READ_ONLY solo letture e `dry_run`; approvazione non aggira READ_ONLY
6. CRITICAL: **mai** eseguibile via API (anche in FULL, anche con JWT) — solo pannello admin umano
7. rate limit condiviso (Mongo, cluster-wide) con `Retry-After`
8. risoluzione target (naturale) → 9. validazione parametri → 10. concorrenza ottimistica (409) → 11. idempotenza
12. **unico handler** per dry-run ed esecuzione (stesso service: `patch_model(dry_run)`, `slot_changes`, `transition(dry_run)`, planner settings/config/categorie)
13. REVIEW → approval token (target+payload+TTL) → 14. audit `ai_actions` con `session_id` + versioni before/after → 15. metadati rollback → 16. envelope standard `{ok, summary, data, changes, warnings, next_steps, rollback, request_id}`

## D. Registry (97 capability, 86 SAFE · 11 REVIEW · 0 CRITICAL esposte; 30 sola lettura, 66 con dry-run, 58 con rollback, 8 batch)
`*` = REVIEW_REQUIRED (anteprima + approvazione)
- **models (27)**: list, get, create, update, set_public_side, set_secret_side, set_regia, set_cta, set_secret_message, set_social, set_seo, validate, publish (sempre via validator), unpublish*, archive*, restore, clone, copy_config, feature, unfeature, soft_delete*, undelete, tags.add, tags.remove, tags.list, tags.normalize, categories.set
- **workflow (1)**: `models.prepare_complete` (create → campi → media/slot → SEO safe-fix → validate; **mai publish**; i campi REVIEW restano soggetti ad approvazione)
- **media (14)**: list, find, inspect, upload_url (URL/base64: anti-SSRF, magic bytes, MIME, limiti, varianti), assign (slot semantici), replace_slot, remove_from_slot, reorder_pairs, update (ALT/SEO name), optimize, optimize_all, soft_delete*, restore, broken
- **homepage (5)**: homepage.reorder_models, filmstrip.get_config, filmstrip.set_config, filmstrip.set_model, filmstrip.reorder
- **settings (6)**: settings.get/update, config.get/update (senza segreti; flag `ai_*`, `public_landing_routes`, dominio/SSR/GSC/GA4/Telegram **non** modificabili), flags.list, flags.set*
- **categories (7)**: list, create, update, archive*, restore, reorder, assign_models
- **seo (12)**: audit, issues, safe_fix, safe_fix_all, fix_issue, ignore_issue*, internal_links, opportunities, sitemap_status, redirect.list, redirect.create*, redirect.delete*
- **landing (7)**: list, get, create, update, validate, publish*, unpublish (motore landing avanzato/A-B → Phase 12B)
- **alerts (4)**: list, inspect, ack, resolve (health:* si chiude solo se il check corrente conferma; manuale → approvazione)
- **jobs (5)**: list, runs, run (solo job SAFE), pause*, resume
- **backup (4)**: list, create, verify, restore_plan (piano read-only: il restore reale è CRITICAL, solo pannello)
- **system (2)**: health_run, admins.list (solo elenco redatto)
- **rollback (3)**: session (inverso cronologico, inclusi effetti secondari: link media→slot, varianti file, issue SEO, redirect da cambio slug), version, window

Mai esposto via API: shell, filesystem, codice, Mongo raw, segreti, gestione chiavi/utenti, restore backup reale, hard delete, flag di sicurezza `ai_*`.

## E. Pannello `/admin/motore` → "Capacità ChatGPT"
KPI (totale, bound/unbound, attive/disattivate, SAFE/REVIEW/CRITICAL, modalità), ricerca e filtri, **disattiva/riattiva** capability (una capability disattivata non è eseguibile nemmeno in anteprima), ultime esecuzioni ed errori, policy per chiave (`capability_allow` / `capability_deny`).

## F. Test (preview, agent-tested — non ancora confermati dall'utente)
- `tests/test_phase12_capabilities.py` 19/19 · `tests/test_ai_control.py` 42/42 · `tests/test_health_reconciliation.py` 5/5 (66/66 in un'unica sessione pytest, `tests/conftest.py`)
- `tests/phase11_gpt_simulation.py` 42/42 (v1 intatto) · `tests/phase12/smoke_v2_wiring.py` 35/35 · `tests/phase12/verify_bindings_12a.py` 30/30
- **Copertura operativa reale** `tests/phase12/coverage_12a.py` **156/156** (93 capability con payload validi: letture in READ_ONLY, mutazioni in FULL-preview per sessione, `rollback.session`, hash dello stato business identico per i gruppi A/B/C) + `tests/phase12/coverage_12a_extra.py` **22/22** (media.restore, filmstrip.reorder, alerts.inspect/ack/resolve, seo.ignore_issue) → **97/97 capability esercitate realmente**
- **E2E TEST GIULIA: PASS** — `models.prepare_complete` ("Prepara TEST GIULIA completamente ma non pubblicarla") → bozza INCOMPLETE non pubblica, campi form (frase, bio, tema, regia+audio, CTA, social, SEO, categorie, tag), 7 slot media (card, cover, public_photo_1, secret_photo_1, secret_hero, public_video_1, filmstrip_public), campi REVIEW → approvazione → `rollback.session` (12 versioni + 7 link media ripristinati, 0 errori) → **hash business before/after identico**, modella soft-deleted, 24 versioni/12 flag rolled_back e 5 azioni di sessione conservate.
- Testing agent (`test_reports/iteration_phase12a.json`, `tests/backend_test_phase12a.py` 47 test/68 asserzioni): nessun bug critico; 2 minori risolti (concorrenza `expected_updated_at` in `parameters`, filtro categoria del pannello).
- Report: `test_reports/phase12a_coverage.json`, `test_reports/phase12a_coverage_extra.json`.

## G. Attivazione (decisione utente, non automatica)
1. Deploy della build 12A in produzione (utente) → 2. verificare `GET /api/v2/ai/status` READ_ONLY e 97 bound → 3. re-import dello schema v2 nel GPT (`/api/v2/ai/openapi-chatgpt.json`) con la stessa API key → 4. test in READ_ONLY → 5. solo dopo, eventuale FULL controllato dal pannello (kill switch sempre disponibile).
