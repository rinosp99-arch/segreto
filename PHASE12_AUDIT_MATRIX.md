# PHASE 12 — AUDIT ADMIN → MATRICE CAPABILITY (pre-implementazione)

Fonti auditate: `routes_admin.py` (33 route), pagine admin (`Dashboard, AdminModels, ModelEditor, AdminCategories, AdminArticles/ArticleEditor, AdminAnalytics, AdminCampaigns, AdminSettings, AdminMotore/ChatGptPanel`), `schemas.py` (ModelIn 36 campi + TemaSegreto 9 + Messaggio35s 6 + SeoFields 14 + PellicolaHome 5, CategoryIn 9, ArticleIn 24, SettingsIn 6), collection (`models, files, categories, articles, landings, settings, config, api_keys, admins, versions, audit_logs, events, seo_issues, redirects, alerts, health, jobs, job_runs, backups, experiments, campaigns, ai_actions, ai_requests, ai_approvals, ai_metrics, idempotency_keys, rate_buckets`), service v1 (`v1_models, v1_media, v1_seo, v1_landings, v1_config, v1_health, v1_jobs, v1_versioning, v1_tracking, v1_experiments`), job scheduler (9 job), impostazioni (`settings.global` + `config.global`).

Legenda RISK: **S** = SAFE (auto) · **R** = REVIEW_REQUIRED (approval token) · **C** = CRITICAL (mai via API key). DRY = dry_run · RB = rollback (versione) · APPR = approvazione. STATO: ✔ già esposto (Phase 10/11) · ➕ nuovo in 12A · ⏭ 12B · ✖ escluso (infrastruttura/segreti).

| Funzione admin | Service esistente | Capability (12A) | Scope | RISK | DRY | RB | APPR | Stato |
|---|---|---|---|---|---|---|---|---|
| **MODELLE** | | | | | | | | |
| Lista/cerca modelle (AdminModels) | `list_models`, `resolve_model` | `models.list`, `models.find`, `models.get` | models:read | S | – | – | – | ✔ |
| Crea modella (ModelEditor new) | `create_model` | `models.create` | models:create | S (bozza) | ✔ | ✔ | – | ✔ |
| Modifica QUALSIASI campo formulario (nome, artistico, slug, frase, bio, bio_segreta, teaser_copy, categorie, tag, badge/badge_tipo, onlyfans_url, cta_testo, tema.* (preset, colori, grain, glow, sfondo_stile, frase_attivazione, testo_dopo_click, effetti_touch), messaggio_35s.*, seo.*, regia.* (fumo, luci, glow, movimento, audio.*), cta_temporizzata.*, social.*, pellicola_home.*, content_overrides, analytics, ordine, conferma_maggiorenne) | `patch_model` (deep-merge + `ALLOWED_FIELDS`, versioning, precondizione) | `models.update` (+ alias semantici `models.set_public_side`, `models.set_secret_side`, `models.set_cta`, `models.set_social`, `models.set_seo`, `models.set_regia`) | models:update | S per campi tecnici · **R** per slug/nome/bio/bio_segreta/frase/onlyfans_url/seo.title-meta-canonical-robots-indexable/stato | ✔ | ✔ | R | ✔ + ➕ alias |
| Valida / readiness | `validate_model` | `models.validate` | models:validate | S | – | – | – | ✔ |
| Pubblica / sospendi / archivia / ripristina | `transition` (validator, mai force) | `models.publish/unpublish/archive/restore` | models:publish / unpublish / archive | publish **R**? → S con validator ma bloccabile da policy; unpublish/archive S; | ✔ | ✔ | opz. | ✔ |
| Duplica / clona | route `duplicate` (logica inline) | `models.clone` | models:create | S | ✔ | ✔ | – | ➕ |
| Copia configurazione (copy-config admin) | logica inline `admin_copy_config` | `models.copy_config` (tema, regia, cta_temporizzata, cta_testo, messaggio timing, pellicola flag) | models:update | S | ✔ | ✔ | – | ➕ |
| Metti in evidenza / badge / Home top | route `feature` | `models.feature`, `models.unfeature` | models:feature | S | ✔ | ✔ | – | ✔ + ➕ unfeature |
| Riordina modelle (drag Home) | `admin_reorder` (inline) | `homepage.reorder_models` | models:feature | S | ✔ | ✔ (versione settings-order) | – | ➕ |
| Soft delete | `soft_delete` | `models.soft_delete` | models:archive | **R** | ✔ | ✔ | R | ➕ |
| Hard delete | – (non esiste in admin) | – | models:delete | **C** | – | – | – | ✖ (solo JWT umano) |
| Tag: aggiungi/rimuovi/rinomina/normalizza/dedup | via `patch_model` | `models.tags.add/remove/rename`, `tags.list`, `tags.normalize` | models:update | S | ✔ | ✔ | – | ➕ |
| Categorie assegnate alla modella | via `patch_model` | `models.categories.set` | models:update | S | ✔ | ✔ | – | ➕ |
| Salute modella | `ai_model_health` | `models.health` | models:read | S | – | – | – | ✔ |
| **MEDIA** | | | | | | | | |
| Libreria media (lista/cerca) | `list_media`, `files_col` | `media.list`, `media.find` (id/nome/alt/url/tipo/modella) | media:read | S | – | – | – | ➕ |
| Upload file (multipart) | `store_media` via `POST /api/v1/media/upload` | endpoint diretto (già esistente, API key con `media:upload`) | media:upload | S | – | soft-del | – | ✔ |
| Upload da URL / base64 | `fetch_url_bytes` (anti-SSRF) + `store_media` | `media.upload_url` | media:upload | S | – | soft-del | – | ✔ |
| Assegna media a slot (semantici: public_photo_N, secret_photo_N, public_video_N, secret_video_N, card, cover, teaser, hero_segreta, og_image, pellicola_public/secret, messaggio_foto/video, galleria_*) | `attach_to_model` (slot tecnici) + mapping semantico | `media.assign` | media:upload+models:update | S | ✔ | ✔ | – | ➕ |
| Sostituisci media in slot | `attach_to_model` / `replace_media` | `media.replace_slot`, `media.replace` | media:replace | S | ✔ | ✔ | – | ➕ |
| Rimuovi da slot / riordina coppie | `patch_model` | `media.remove_from_slot`, `media.reorder_pairs` | models:update | S | ✔ | ✔ | – | ➕ |
| ALT / SEO filename / metadata | `patch_media` | `media.update` | media:update | S | ✔ | ✔ (file version) | – | ➕ |
| Ottimizza / rigenera varianti (web, mobile, thumb, poster) | `optimize_media` | `media.optimize`, `media.optimize_all` (batch) | media:optimize | S | – | – | – | ➕ |
| Elimina (soft) / ripristina | `delete_media` (soft) / `files_col` | `media.soft_delete`, `media.restore` | media:delete | **R** / S | ✔ | ✔ | R | ➕ |
| Delete definitivo | `delete_media(force)` | – | media:delete | **C** | – | – | – | ✖ |
| Media rotti | `check_media` | `media.broken` | media:read | S | – | – | – | ➕ |
| **HOMEPAGE / FILMSTRIP** | | | | | | | | |
| Ordine, visibilità in Home | `ordine`, `stato`, `pellicola_home` | `homepage.reorder_models`, `homepage.hide_model` (=unpublish R) | models:feature/unpublish | S / R | ✔ | ✔ | – | ➕ |
| Config FilmStrip (attiva, titolo, sottotitolo, velocità, max_video_attivi 4-12, seconda_fila, pausa_su_touch, nomi_sempre_visibili, inserisci_dopo_n) | `settings.home_pellicola` (AdminSettings) | `filmstrip.get_config`, `filmstrip.set_config` | settings:update | S | ✔ | ✔ (settings version) | – | ➕ |
| FilmStrip per modella (attiva, priorità, ordine, video/poster pubblico/segreto) | `pellicola_home` via `patch_model`/`attach_to_model` | `filmstrip.set_model`, `filmstrip.list`, `filmstrip.reorder` | models:feature | S | ✔ | ✔ | – | ➕ |
| Validazione codec / durata video | `_ffprobe` (in `store_media`) | `media.inspect` | media:read | S | – | – | – | ➕ |
| Testi/SEO homepage, switch predefinito, footer | `settings` (brand_name, site_description, footer_contatti, global_switch_default) | `settings.get`, `settings.update` | settings:update | S | ✔ | ✔ | – | ➕ |
| **CATEGORIE** | `categories_col` (route admin inline) | `categories.list/create/update/reorder/archive/restore/assign_models` | categories:write | S (slug/nome R) | ✔ | ✔ (entity category) | – | ➕ |
| **SEO** | | | | | | | | |
| Audit, safe fix, review list/preview, batch | `run_audit`, `apply_safe_fixes`, `apply_issue_fix` | `seo.audit/safe_fix/review_list/review_preview/batch_safe_fix` | seo:audit/safe_fix/review_prepare | S / R / C | ✔ | ✔ | R | ✔ |
| Applica issue REVIEW approvata | `apply_issue_fix` | via approvazione (`approvals.approve`) | seo:review_prepare | R | – | ✔ | ✔ | ✔ |
| Ignora issue | `ignore_issue` | `seo.ignore_issue` | seo:update | **R** | – | – | R | ➕ |
| Redirect crea/elimina | `ensure_redirect`, `redirects_col` | `seo.redirect.create/list/delete` | seo:update | R | ✔ | – | R | ➕ |
| Sitemap status, internal links, opportunità, page SEO | `sitemap_status`, `internal_link_suggestions`, `opportunities` | `seo.sitemap_status`, `seo.internal_links`, `seo.opportunities` | seo:read | S | – | – | – | ➕ |
| Title/meta/canonical/robots/index/ALT default/schema | `patch_model` (seo.*) | `models.set_seo` | models:update | **R** (title/meta/canonical/robots/indexable) · S (keywords/topics/alt_default/og) | ✔ | ✔ | R | ➕ |
| **LANDING** | `create_landing`, `patch_landing`, `set_landing_state` | `landing.list/get/create/update/validate/publish/unpublish` | landing:* | S / R (publish senza scope) | ✔ | ✔ | R | ✔ + ➕ list/get/update/unpublish |
| Clone / varianti A/B | – | – | – | – | – | – | – | ⏭ 12B |
| **ARTICOLI** | route admin | lettura `articles.list/get`; CRUD completo | content:* | – | – | – | – | ⏭ 12B |
| **ANALYTICS** | `v1_tracking`, `ai_query` | `analytics.query` (metric/group_by/period/country/region/device/source/model/landing) | analytics:read | S | – | – | – | ✔ |
| **A/B TEST** | `v1_experiments` | – | experiments:* | – | – | – | – | ⏭ 12B (lettura `experiments.list` già ok) |
| **ALERT** | `alerts_col`, `ack`, `resolve`, `run_health_checks` | `alerts.list` (current+resolved), `alerts.inspect`, `alerts.ack`, `alerts.resolve` (solo se il check corrente conferma; altrimenti R) | alerts:read / alerts:write | S / R | ✔ | – | R | ➕ |
| **JOB** | `run_job`, `patch_job`, `job_runs` | `jobs.list`, `jobs.runs`, `jobs.run` (health_check, seo_scan, sitemap_verify, media_verify, broken_link_scan, analytics_sync, anomaly_detection, backup), `jobs.pause/resume` | jobs:read / jobs:execute | S (pause **R**) | ✔ | – | R | ➕ |
| **BACKUP** | `create_backup`, `list_backups`, `restore_backup(dry_run)` | `backup.list/create/verify/restore_plan` | backup:read / backup:create | S | ✔ | – | – | ➕ (`backup:manage` resta C) |
| Restore reale | `restore_backup` | – | backup:manage | **C** | – | – | – | ✖ (solo JWT umano) |
| **SETTINGS / CONFIG** | `settings_col`, `config_col` | `settings.get/update`; `config.get` (senza segreti); `config.update` (solo chiavi AI_MANAGEABLE: `site.base_url`, `seo.defaults.*`, `analytics.thresholds.*`, `media.limits.*`, `ai.policy.approval_ttl_min/max_batch`) | settings:update / config:update | S / R (site.base_url) | ✔ | ✔ | R | ➕ |
| **FEATURE FLAG** | `flags` | `flags.list`; `flags.set` solo AI_MANAGEABLE (`seo_autopilot`, `self_healing`, `landing_engine`, `ab_testing`, `italy_engine`); MAI `ai_api_enabled/ai_write_enabled/ai_batch_enabled/ai_approval_flow_enabled/public_landing_routes/domain_it_migration/ssr_prerender/search_console_sync/ga4_production/super_api/webhooks` | config:update | **R** | ✔ | ✔ | R | ➕ |
| **ADMIN USERS** | `list_users`, `create/patch/delete_user` | `admins.list` (solo email/ruolo/created, mai hash) | users:read | S | – | – | – | ➕ · create/delete/SUPER_ADMIN = **C** ✖ |
| **API KEY / WEBHOOK** | `v1_config` | – | keys:manage / webhooks:manage | **C** | – | – | – | ✖ |
| **SISTEMA** | `run_health_checks`, `site-health`, `daily-summary`, `recommendations` | `system.status/site_health/daily_summary/recommendations/health_run` | system:status / health:run | S | – | – | – | ✔ + ➕ health_run |
| **ROLLBACK** | `rollback_version`, `versions_col`, `ai_actions` | `rollback.preview/execute`, `rollback.session` (tutte le modifiche di un session_id), `rollback.window` (modella + minuti + attore) | rollback:read / rollback:execute | S (nuove versioni) | ✔ | ✔ | – | ✔ + ➕ session/window |
| **WORKFLOW** | composizione dei service sopra | `models.prepare_complete` (crea bozza → campi → media slot → SEO safe → ALT → validate → readiness; MAI publish) | models:create+update, media:upload, seo:safe_fix | S | ✔ | ✔ (session) | – | ➕ |
| **BULK** | `_select_models` + capability | `batch.run` (capability su selezione: all/published/draft/category/ids, max_batch, progress, errori parziali, dry_run, audit individuale) | scope della capability | come capability | ✔ | ✔ | – | ➕ |
| **ASYNC** | – | `ai_jobs` (job_id, queued/running/done/failed, progress) per batch pesanti (`async: true`) | ai:execute | – | – | – | – | ➕ base |
| **ESCLUSI (per design)** | shell, Python, Mongo raw, filesystem, .env, secrets, password/hash, api key, codice, pacchetti, firewall/K8s/DNS, bypass auth, disabilitazione audit, secret rotation | – | – | ✖ | | | | ✖ |

Principi applicati: nessuna business logic duplicata (ogni capability chiama un service esistente o ne estrae uno dalle route inline `duplicate/feature/reorder/copy-config/categories`); ogni mutazione → `record_version` (rollback) + `audit_log` + `ai_actions` (session_id); ogni capability dichiara `capability_version`, `params_schema`, `examples`; scope fini + allow/deny per chiave + disabilitazione per capability da pannello.
