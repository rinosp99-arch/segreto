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
Catalogo completo: `GET /api/v1/ai/capabilities`. Risposta sempre `{ ok, action, request_id, summary, data, warnings, next_steps }`.

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
