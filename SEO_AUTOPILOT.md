# SEO AUTOPILOT / ORGANIC GROWTH ENGINE — Fase 14 (READ_ONLY)

Il "cervello" SEO di LATO SEGRETO: analizza, impara, propone. **Non ha le mani**: in questa fase non modifica nulla del sito pubblico.

## Stati del motore (`SEO_AUTOPILOT_MODE`)

| Stato | Comportamento |
|---|---|
| `OFF` | i job ritornano subito, nessuna analisi |
| `READ_ONLY` (**attuale**) | analizza tutto, scrive SOLO nelle proprie collezioni `seo_ap_*` |
| `FULL` | futuro. **Bloccato nel codice** (`mode.FULL_LOCKED = True`): anche se l'env dice FULL, il motore degrada a READ_ONLY e registra il downgrade. Ogni azione di scrittura pubblica passa da `mode.require_full()` e fallisce con `WriteBlocked` (HTTP 423). |

Gate obbligatorio: **`PUBLIC_MUTATIONS = 0`**. Ogni run calcola prima e dopo lo snapshot/hash delle risorse pubbliche (modelli e loro campi pubblici, categorie, articoli, landing, redirect, config pubblica, `/api/sitemap.xml` senza lastmod, `/robots.txt`). Se un solo gruppo cambia il run è marcato `FAIL_PUBLIC_MUTATION`.

## Componenti (`backend/seo_autopilot/`)

| Modulo | Ruolo |
|---|---|
| `mode.py` | stati OFF/READ_ONLY/FULL, guard `require_full`, decoratore `write_action` |
| `store.py` | collezioni `seo_ap_*`, indici, decision log, run log, **snapshot pubblico** + diff, `SEO_CRAWL_BASE_URL` |
| `gsc_sync.py` | import Search Console (riusa `backend/google_search/`, stessa auth e request-log): snapshot giornalieri **mai sovrascritti** per query/page/query+page/device/country; finestre 7/28/90 e confronti 7v7 · 28v28 |
| `models_matrix.py` | matrice creator ↔ categorie/tag/termini reali (solo dati DB pubblicati) |
| `textnorm.py` · `intent.py` | normalizzazione italiana deterministica (OF=OnlyFans, ragazze≈modelle≈creator), intent a regole |
| `keywords.py` | universo keyword: seed utente + query GSC reali + nomi/categorie reali + suggerimenti LLM (filtrati per pertinenza). Metriche solo GSC, altrimenti `UNKNOWN` / `DATA_SOURCE_UNAVAILABLE` |
| `clustering.py` | cluster deterministici (chiave canonica + Jaccard ≥ 0.75 stesso intent); merge LLM applicati solo se stesso intent + token condivisi + confidence ≥ 0.7, tutti loggati |
| `opportunities.py` | regole A (impression + pos 5-20), B (CTR basso vs atteso), C (query nuove), D (cluster senza pagina), E (cannibalizzazione), F (pagine in calo); mappa cluster→pagina→azione (KEEP/UPDATE/EXPAND/CREATE/MERGE/REVIEW/HOLD); cannibalizzazione (SAME_QUERY, OVERLAPPING_CLUSTERS, SIMILAR_TITLE); learning settimanale; backlog |
| `planner.py` | proposte landing interne `SEO_DRAFT_PROPOSAL` con quality gate (INTENTO_DISTINTO, CREATOR_REALI, CONTENUTO_SUFFICIENTE, NO_KEYWORD_STUFFING, NO_DOORWAY, NO_DATI_INVENTATI, CANNIBALIZZAZIONE, DATI_REALI→hold). Rifiuti = `REJECTED_BY_QUALITY_GATE`. Mai pubbliche |
| `crawler.py` | crawl tecnico read-only (status, redirect, title/description/H1/canonical/robots/JSON-LD/alt/link, sitemap, robots.txt, link rotti, orfane) + **audit adult** (noindex meta vs header, termini espliciti, separazione pubblico/segreto, media raggiungibili) |
| `render_audit.py` | INITIAL_HTML vs RENDERED_DOM (Chromium headless, max 30 pagine/giorno, 10 per run) vs GOOGLE_INSPECTION (URL Inspection selettiva, solo se host di crawl = proprietà GSC) |
| `llm.py` | layer semantico advisory: ogni output `source=LLM_SUGGESTION`, cache, budget 40 chiamate/giorno, numeri "metrici" scartati, fail-soft (il job non fallisce mai per l'LLM) |
| `engine.py` | orchestratore dei run con snapshot before/after |
| `jobs.py` | job nello scheduler esistente (`v1_jobs`) |
| `routes.py` | `/api/admin/seo-autopilot/*` (JWT admin) |

Frontend: `frontend/src/pages/admin/AdminSeoAutopilot.js` (voce "SEO Autopilot" nel menu admin).

## Job (background, mai su richieste pubbliche)

| Job | Intervallo | Contenuto |
|---|---|---|
| `seo_ap_tech_health` | 6 h | crawl tecnico + campione rendering + audit adult |
| `seo_ap_gsc_sync` | 12 h | import Search Console (ultimi 7 giorni disponibili, idempotente) |
| `seo_ap_daily_analysis` | 24 h | GSC → matrice → keyword → cluster → opportunità → mappa → cannibalizzazione → planner → backlog |
| `seo_ap_weekly_learning` | 7 g | trend 7v7 / 28v28 per query e pagine |

Avvio manuale: `POST /api/admin/seo-autopilot/run/{tech_health|gsc_sync|daily_analysis|weekly_learning|full}` (background, lock anti-sovrapposizione).

## Variabili d'ambiente

```
SEO_AUTOPILOT_MODE=READ_ONLY          # OFF | READ_ONLY | FULL(bloccato)
SEO_CRAWL_BASE_URL=https://…           # preview analizza preview, produzione analizza produzione
SEO_AUTOPILOT_LLM_MODEL=gpt-5.4-mini   # via EMERGENT_LLM_KEY (solo suggerimenti)
SEO_AUTOPILOT_LLM_ENABLED=true
SEO_AUTOPILOT_LLM_DAILY_CALLS=40
SEO_AUTOPILOT_RENDER_DAILY=30          # pagine renderizzate/giorno (max)
SEO_AUTOPILOT_RENDER_PER_RUN=10
SEO_AUTOPILOT_INSPECT_PER_RUN=5
```

## Regole "nessun dato inventato"
- Le impression GSC sono del **sito**, non volume di ricerca globale (`search_volume = DATA_SOURCE_UNAVAILABLE`).
- Senza dati GSC: `metrics.source = UNKNOWN`, opportunità in `HOLD`, proposte con `hold=true`.
- LLM: mai metriche, mai decisioni di pubblicazione; se non risponde → pipeline deterministica.

## Collezioni
`seo_ap_gsc_snapshots` (storico non sovrascritto), `seo_ap_keywords`, `seo_ap_clusters`, `seo_ap_opportunities`, `seo_ap_page_map`, `seo_ap_landing_proposals`, `seo_ap_cannibalization`, `seo_ap_tech_pages`, `seo_ap_render_audits`, `seo_ap_audits`, `seo_ap_backlog`, `seo_ap_decision_log`, `seo_ap_runs`, `seo_ap_state`, `seo_ap_creator_matrix`, `seo_ap_llm_cache`.

## Test
`tests/test_seo_autopilot.py` — guard FULL, GSC assente/connesso(mock)/zero dati/errore temporaneo, idempotenza snapshot, regole opportunità, cannibalizzazione, planner + quality gate (doorway), parser crawler + link rotti, LLM fail-soft + strip metriche, snapshot pubblico, run completo idempotente con `PUBLIC_MUTATIONS=0`, API admin protette, `execute` → 423, integrità sitemap/robots/models prima/dopo un run, job registrati.
