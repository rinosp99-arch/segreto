# INSTAGRAM AUTOPILOT — LATO SEGRETO (FASE INSTAGRAM, mock)

Rotazione circolare automatica delle creator **pubblicate** su Instagram, con **solo media del lato pubblico**,
caption in italiano e CTA "link in bio". Speculare al Telegram Autopilot ma con **coda, stato, cursori media,
slot e lock completamente indipendenti** (collezioni `instagram_*`).

## Stato di questa fase
| Campo | Valore |
|---|---|
| INSTAGRAM_AUTOPILOT_MOCK | `true` (adapter MockMeta, zero rete) |
| INSTAGRAM_AUTO_SCHEDULER_ENABLED | `false` (master switch env: il tick non pubblica mai) |
| INSTAGRAM_ITALY_AUDIENCE_MODE | `true` (caption/CTA/hashtag IT, timezone obbligata Europe/Rome) |
| CONNECTION_STATUS | `NOT_CONNECTED` (nessuna credenziale Meta) — mostrato separatamente da `MOCK_MODE=TRUE` |
| META_REAL_CALLS | 0 |
| INSTAGRAM_REAL_POST_DONE | FALSE |
| SECRET_MEDIA_USED | FALSE (strutturalmente impossibile: i campi `*segret*` non vengono nemmeno proiettati dal DB) |

## Pipeline (`engine.publish_next`)
lock DB → claim slot (`instagram_YYYY-MM-DD_HH:MM`, unico, idempotente) → prossima creator eleggibile in ordine
stabile (`ordine`, `data_pubblicazione`, `slug`) non ancora processata nel ciclo → media pubblico dal cursore
(foto → `PHOTO_POST`/IMAGE, video → `REEL_POST`/REELS con cover) → caption IT (LLM Emergent con fallback template
deterministico) → adapter (mock registra il payload; reale = fase futura) → avanzamento coda/cursore/log.
Fallback: video rifiutato → foto successiva; tutti i media falliti → `SKIPPED_NO_PUBLIC_MEDIA` e si passa alla creator seguente.
Nuove creator pubblicate entrano nel ciclo corrente; bozze/disattivate/senza media pubblici escono da sole.

## Media: solo lato pubblico (`media.get_instagram_public_media`)
Fonti lette: `media_pairs[].pubblico`, `galleria_pubblica`, `foto_card`, `foto_copertina`, `foto_card_teaser`.
Mai letti: `media_pairs[].segreto`, `galleria_segreta`, `foto_segreta_hero`, `bio_segreta`.
Filtro IG-safe: path/query con marker `segret|secret|privat|nsfw|explicit|hidden` → scartato; formati non supportati
(`.pdf`, `.avi`, …) → scartato; flag/alt esplicito → scartato (`SKIPPED_NOT_INSTAGRAM_SAFE`). L'host non è ispezionato
(il dominio del sito contiene "secret-side").

## Caption (`caption.build_caption`)
`TESTO (LLM o template)\n\nCTA "link in bio"\n\n#hashtag` — 3-6 hashtag prevalentemente italiani (`#latosegreto` sempre),
nessun URL, nessuna menzione OnlyFans, nessun dato inventato (filtro FORBIDDEN su età/città/professione/volgarità).
Nessuna affermazione di distribuzione geografica esclusiva.

## Admin
Pagina `/admin/instagram-autopilot` (JWT admin): pill stato · KPI coda/ciclo/post oggi/ultima · Attiva/Pausa ·
Pubblica ora (mock) · Anteprima caption · Salta creator · impostazioni (post/giorno, orari, timezone, foto/video, AI) ·
rotazione · log tecnico essenziale.

API: `GET status`, `GET logs`, `POST test-connection|start|pause|publish-now[?dry_run]|skip`, `PATCH settings`
sotto `/api/admin/instagram-autopilot/`.

## Collezioni
`instagram_autopilot_state` (globale) · `instagram_model_media_state` (cursore per creator) · `instagram_autopilot_log` ·
`instagram_autopilot_slots` (idempotenza) · `instagram_autopilot_locks`.

## Fase successiva (solo su richiesta esplicita)
1. Credenziali Meta in `backend/.env` (`INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`, `INSTAGRAM_APP_ID`), `INSTAGRAM_AUTOPILOT_MOCK=false`.
2. Implementare in `adapter.MetaAdapter.publish` il flusso container (`/media` → poll `FINISHED` → `/media_publish`).
3. Test connessione → 1 post reale via PUBBLICA ORA → autorizzazione scheduler (`INSTAGRAM_AUTO_SCHEDULER_ENABLED=true` + Attiva).

## Test
`tests/test_instagram_autopilot.py` (16): connessione NOT_CONNECTED/MOCK · adapter reale senza credenziali non chiama Meta ·
media pubblici/segreti irraggiungibili · filtro IG-safe · foto→PHOTO_POST, video→REEL_POST, caption IT, 2 consecutive ·
rotazione completa e wrap · skip e fallback media · LLM offline→template · persistenza restart · slot duplicato e concorrenza ·
nuove/rimosse a metà ciclo · pausa/publish-now/skip/tick disabilitato · indipendenza da Telegram · API admin/settings/job.
