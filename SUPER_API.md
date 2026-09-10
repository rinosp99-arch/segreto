# LATO SEGRETO — SUPER API v1 (guida rapida)

Base: `/api/v1` · Docs interattive: `/api/docs` · OpenAPI: `/api/openapi.json`
Auth: `Authorization: Bearer <JWT admin>` **oppure** `X-API-Key: ls_...` (creata da /admin/motore o `POST /api/v1/auth/keys`).
Header utili: `Idempotency-Key` (POST/PATCH ripetibili in sicurezza), `X-Request-ID` (sempre in risposta).

## Endpoint AI (ChatGPT-friendly) — `/api/v1/ai`
| Frase | Endpoint | Body |
|---|---|---|
| "Crea Vanessa" | POST /models/create | `{ "nome": "Vanessa", "frase": "...", "categorie": ["more"] }` |
| "Modifica Alessia / Aggiorna la bio" | POST /models/update | `{ "model": "alessia", "changes": { "bio": "..." } }` |
| "Carica queste foto" | POST /media/upload-batch | `{ "model": "vanessa", "items": [{ "model":"vanessa","slot":"pair","side":"pubblico","url":"https://..." }] }` |
| "Carica una foto/video" | POST /media/upload | `{ "model":"vanessa", "slot":"foto_card", "side":"pubblico", "url":"https://..." }` (o `base64_data`) |
| "Controlla se manca qualcosa" | POST /models/validate · GET /models/missing | `{ "model": "vanessa" }` |
| "Mettila online" | POST /models/publish | `{ "model": "vanessa" }` |
| "Metti in homepage" | POST /models/feature | `{ "model":"vanessa", "position":0, "badge":"IN TENDENZA" }` |
| "Sistema gli errori SEO sicuri" | POST /seo/apply-safe-fixes | `{ "dry_run": false }` |
| "Fammi vedere le statistiche" | GET /daily-summary · GET /status | — |
| "Quale modella converte meglio?" | POST /analytics/query | `{ "question": "best_converting_model", "range": "30g" }` |
| "Mostrami solo il traffico italiano" | POST /analytics/query | `{ "question": "italian_traffic" }` |
| "Annulla" | POST /rollback | `{ "version_id": "..." }` |
Catalogo completo: `GET /api/v1/ai/capabilities`. Risposta sempre `{ ok, action, request_id, summary, data, warnings, next_steps, changes, approval_required }`.

## Phase 10 — ChatGPT Control Layer (vedi `CHATGPT_API.md`)
- OpenAPI dedicata a ChatGPT: `GET /api/v1/ai/openapi.json` (solo endpoint AI, operationId leggibili, schemi errore/risposta, securitySchemes).
- Policy centrale SAFE / REVIEW_REQUIRED (token di approvazione single-use, TTL, legato a chiave+target+payload, `POST /api/v1/ai/approvals/confirm`) / CRITICAL (mai via API key → `403 CRITICAL_ACTION_BLOCKED`).
- `dry_run` su create/update/publish/transizioni/feature/SEO/landing/rollback/batch; `expected_updated_at` → `409 CONFLICT`; `Idempotency-Key` → replay senza duplicati.
- Flag (default sicuri): `ai_api_enabled` (kill switch → 503 `AI_API_DISABLED` solo per API key), `ai_write_enabled` (READ_ONLY → 403 `READ_ONLY_MODE`, anteprime consentite), `ai_batch_enabled`, `ai_approval_flow_enabled`. Rate limit AI dedicato (min 10/min). Controllo: `GET/PATCH /api/v1/ai/control` (JWT).
- Scopes fini AI_OPERATOR (`models:create|update|validate|publish|unpublish|archive|feature`, `media:upload|optimize|replace`, `seo:audit|safe_fix|review_prepare`, `landing:read|create|update|validate` [+`landing:publish` opzionale], `system:status|daily_summary`, `rollback:read|execute`); alias legacy mantenuti.
- Chiavi: `POST /auth/keys` (chiave in chiaro **solo** nella risposta di creazione), `POST /auth/keys/{id}/rotate|disable|enable`, `DELETE /auth/keys/{id}`, `GET /auth/keys/{id}/usage`. DB: solo hash/prefix/metadati.
- Nuovi endpoint AI: `/command`, `/models/{ref}/health`, `/site-health`, `/recommendations`, `/models/{ref}/seo/review[/{issue_id}/preview]`, `/approvals[/confirm]`, `/landings[...]`, `/analytics/query` strutturata, `/rollback/preview`, `/batch/seo-safe-fix`, `/batch/validate`, `/actions`, `/test-connection` (JWT).
- Pannello `/admin/motore → ChatGPT Control Layer`: kill switch, modalità FULL/READ_ONLY, batch, approvazioni, rate limit, metriche p50/p95, stato connessione, setup copiabile senza chiave, test connessione (13 controlli), chiave dedicata (mostrata una volta, ruota/disattiva/revoca, uso/errori/IP), attività ChatGPT.
- `GET /api/landings/{slug}` ora dietro flag `public_landing_routes` (OFF → 404).

## Phase 11 — Collegamento reale ChatGPT (vedi `CHATGPT_API.md` → REAL GPT CONNECTION, `CHATGPT_INSTRUCTIONS.md`)
- `GET /api/v1/ai/openapi-chatgpt.json`: schema GPT Action-ready (23 operazioni ≤ 30, descrizioni ≤ 300 caratteri, un solo security scheme Bearer, sanitizzato, READ_ONLY-first). La `openapi.json` completa resta come riferimento.
- Minimo privilegio: preset scopes READ_ONLY (`AI_READ_ONLY_SCOPES`); `dry_run=true` accettato con gli scope di lettura corrispondenti (`PREVIEW_SCOPE`), scritture reali → `INSUFFICIENT_SCOPE`.
- Log richieste `ai_requests` (tutte le chiamate con API key, letture incluse) visibile nel pannello; `principal_type` = machine|user.
- Server lasciato in **READ_ONLY** (`ai_write_enabled=false`). Test: `python tests/phase11_gpt_simulation.py` (42/42).

## Aree
- Modelle: `/models` (GET/POST/PATCH/DELETE soft), `/validate`, `/publish`, `/unpublish`, `/archive`, `/restore`, `/duplicate`, `/feature`, `/versions`. Stati: DRAFT → INCOMPLETE → READY → PUBLISHED → ARCHIVED (+ERROR).
- Media: `/media/upload` (multipart), `/media/from-url`, `PATCH/DELETE /media/{id}`, `/replace`, `/optimize`, `POST /models/{id}/media`. Varianti web/mobile/thumb (WebP), poster + mobile per video (ffmpeg), ALT, SEO filename, controllo magic-bytes.
- SEO: `/seo/audit`, `/seo/issues`, `/seo/opportunities`, `/seo/fix` (REVIEW solo con `apply_review=true`, 1 alla volta), `/seo/fix-all` (solo SAFE), `/seo/sitemap`, `/seo/internal-links`, `/seo/redirects`, `/seo/pages/{type}/{id}`.
- Tracking/Italy Engine: `POST /api/v1/track`, `/analytics/overview|funnel|models|models/{id}|breakdown|italy|timeseries|onlyfans|events` con filtri `range,country,region,city,device,source,model_id,landing,campaign`.
- Landings: `/landings` CRUD + publish; pubblico `GET /api/landings/{slug}`; rotta frontend `/l/{slug}` dietro flag `public_landing_routes` (OFF).
- A/B: `/experiments` (+start/pause/conclude/results), pubblico `GET /api/experiments/assign?session_id=`. Nessun vincitore automatico.
- Health/Self-healing: `/health`, `POST /health/run`, `/alerts` (+ack/resolve). Jobs: `/jobs`, `POST /jobs/{name}/run`.
- Versioni: `/versions`, `POST /versions/{id}/rollback`, `/audit`.
- Config center: `/config`, `/config/flags`. Webhook firmati: `/webhooks`. Backup: `/backup`, `/backup/{id}/restore` (dry-run + backup di sicurezza).
- Ruoli/chiavi/utenti: `/auth/me`, `/auth/roles`, `/auth/keys`, `/auth/users`.

## Predisposto ma OFF (fase successiva)
Flag: `domain_it_migration`, `ssr_prerender`, `search_console_sync`, `ga4_production`, `public_landing_routes`. Config: `site.base_url`, `site.future_domain`, `analytics_production`.
