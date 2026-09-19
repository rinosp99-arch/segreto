# TELEGRAM AUTOPILOT — LATO SEGRETO

Pubblica a rotazione circolare TUTTE le modelle pubblicate sul canale Telegram @latosegreto: media pubblico (foto/video alternati) + copy italiano personalizzato + CTA + link OnlyFans diretto. Modulo separato `backend/telegram_autopilot/` + pagina Admin "Telegram Autopilot". Nessuna modifica al sito pubblico.

## Variabili d'ambiente (SOLO backend)
```
TELEGRAM_BOT_TOKEN=<segreto>            # mai nel codice/frontend/API/log/test (filtro di redazione sui log httpx)
TELEGRAM_CHANNEL_ID=@latosegreto
TELEGRAM_AUTOPILOT_MOCK=true            # preview: nessun post reale. In PRODUZIONE impostare false
TELEGRAM_AUTO_SCHEDULER_ENABLED=false   # master switch dello scheduler: resta false finché non autorizzato
TELEGRAM_LLM_ENABLED=true               # copy via Emergent LLM (fallback template automatico)
SEO_CRAWL_BASE_URL / TELEGRAM_MEDIA_BASE_URL   # base per i media con URL relativo (in produzione = https://secret-side.emergent.host)
```

## Eleggibilità (dati reali del DB)
`stato=pubblicata`, non cancellata, `onlyfans_url` sul dominio onlyfans.com (nessun fallback social), almeno un media PUBBLICO tra `media_pairs[].pubblico`, `galleria_pubblica`, `foto_card`, `foto_copertina`, `foto_card_teaser`. Mai materiale `segreto`.
Non eleggibili → `SKIPPED_NO_OF_LINK` / `SKIPPED_NO_MEDIA` (visibili in admin), saltate automaticamente.

## Rotazione
Ordine stabile (`ordine`, data pubblicazione, slug). Stato in `telegram_autopilot_state` (`cycle_number`, `cycle_done`, `last_position`, `current_model_id`, `last_published`, `last_run`, `last_success`, impostazioni). Nessuna modella due volte nello stesso ciclo; a fine lista `cycle_number += 1` e si riparte dalla prima. Nuove modelle entrano nel ciclo corrente; modelle in bozza/rimosse/senza OF vengono saltate. Media cursor per modella in `telegram_model_media_state` (alternanza foto→video→foto, wrap).

## Pipeline (identica per scheduler e PUBBLICA ORA)
lock DB (`telegram_autopilot_locks`, TTL 180 s) → claim slot (`telegram_autopilot_slots`, unique `slot_id` `YYYY-MM-DD_HH:MM` → `SKIP_DUPLICATE_SLOT`) → prossima modella → media dal cursor (max 3 tentativi, video rifiutato → media successivo/foto; tutti falliti → `SKIPPED_NO_MEDIA` e modella successiva) → copy (LLM, altrimenti template deterministico; solo dati reali; caption ≤ 1024, HTML) → `sendPhoto` / `sendVideo (supports_streaming)` per URL, fallback upload ≤ 50 MB → avanzamento coda → log.

## Scheduler
Job `telegram_autopilot_tick` (ogni 5 min) nello scheduler esistente `v1_jobs`. Pubblica solo se: `TELEGRAM_AUTO_SCHEDULER_ENABLED=true` **e** `enabled=true` (ATTIVA in admin) **e** `TELEGRAM_CONNECTION_STATUS=CONNECTED` **e** esiste uno slot dovuto (entro 90 min dall'orario, mai recupero di massa).

## API admin (JWT admin)
`GET status` · `POST test-connection[?real=true]` (solo getMe/getChat/getChatMember) · `POST start` · `POST pause` · `POST publish-now[?dry_run=true]` · `POST skip` · `PATCH settings` (posts_per_day, schedule_times, timezone, use_photo, use_video, use_ai_copy) · `GET logs`.

## Log tecnico minimo (`telegram_autopilot_log`)
timestamp, model_id/slug/name, media_id/type, cycle_number, message_id, status (`PUBLISHED | FAILED | SKIPPED_NO_MEDIA | SKIPPED_NO_OF_LINK | MANUAL_SKIP | SKIP_DUPLICATE_SLOT`), error_code, slot_id, mock.

## Test
`tests/test_telegram_autopilot.py` (16): connessione/stati, admin/permessi, OF link, media pubblici, foto, video, caption, link, due consecutive, rotazione completa + wrap, no OF, no media, video fail → foto, LLM offline → template, restart, slot duplicato, 5 job concorrenti → 1 post, nuova/rimossa modella nel ciclo, pausa, publish-now, skip, auth API, token mai esposto (API, sorgenti, log).

## Messa in produzione (dopo Re-publish)
1. Impostare in produzione: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID=@latosegreto`, `TELEGRAM_AUTOPILOT_MOCK=false`, `TELEGRAM_AUTO_SCHEDULER_ENABLED=false`, `SEO_CRAWL_BASE_URL=https://secret-side.emergent.host`.
2. Admin → Telegram Autopilot → "Test connessione" → CONNECTED.
3. UN solo "Pubblica ora" con una modella reale → verifica nel canale → stop.
4. Solo su autorizzazione: `TELEGRAM_AUTO_SCHEDULER_ENABLED=true` + "Attiva".
