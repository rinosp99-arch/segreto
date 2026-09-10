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
