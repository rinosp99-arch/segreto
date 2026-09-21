# X AUTOPILOT — LATO SEGRETO (FASE X, mock)

Un solo account X Lato Segreto: tutte le creator **pubblicate** a rotazione circolare. Ogni pubblicazione =
**1 media LATO PUBBLICO + 1 media LATO SEGRETO (Pubblico PRIMA, Segreto DOPO) + copy italiano + link OnlyFans REALE della creator**.
Speculare a Telegram/Instagram Autopilot ma con coda, stato, cursori, slot e lock **completamente indipendenti** (collezioni `x_*`).

## Stato di questa fase
| Campo | Valore |
|---|---|
| X_AUTOPILOT_MOCK | `true` (MockXAdapter, zero rete) |
| X_AUTO_SCHEDULER_ENABLED | `false` (master switch env: il tick non pubblica mai) |
| X_ITALY_AUDIENCE_MODE | `true` (copy/CTA/hashtag IT, timezone Europe/Rome; toggle anche in Admin) |
| CONNECTION_STATUS | `NOT_CONNECTED` (nessuna credenziale X) — mostrato separatamente da `MOCK_MODE=TRUE` |
| X_REAL_CALLS | 0 |
| X_REAL_POST_DONE | FALSE |

## Vincolo X e formati
Un post X contiene fino a 4 foto **oppure** 1 video, mai misti.
- **Priorità 1 — FOTO+FOTO → `SINGLE_POST`**: un solo post con 2 media, `media_order = [PUBLIC, SECRET]`.
- **Priorità 2 — coppia con video → `THREAD`**: post principale (media PUBLIC + copy + link OF) e risposta immediata (media SECRET).
  Il thread è **una sola pubblicazione logica** (un item di rotazione, uno slot, un avanzamento coda).
  Se il post principale esiste ma la risposta SECRET fallisce → `PARTIAL_FAILED` / `THREAD_SECRET_FAILED`, coda avanzata una volta, nessun duplicato.

## Eleggibilità (`media.classify`)
PUBLISHED + attiva + ≥1 media PUBLIC X-safe + ≥1 media SECRET X-safe + link `onlyfans.com` valido. Altrimenti
`SKIPPED_NO_PUBLIC_MEDIA` / `SKIPPED_NO_SECRET_MEDIA` / `SKIPPED_NO_OF_LINK` e si passa alla successiva.
X_SAFE (leggero): `x_safe=false`/flag esplicito → no; media disabilitato → no; marker `nsfw|explicit|xxx|porn|hardcore` in metadati/nome file → no;
formato non supportato → no. Se un media non passa si prova il successivo dello stesso lato; senza coppia valida → skip creator, coda mai bloccata.

## Due cursori per creator (`x_model_media_state`)
`public_media_index` / `secret_media_index` indipendenti (ciclo 1: public_1+secret_1, ciclo 2: public_2+secret_2, …; ognuno riparte dal primo quando finisce la propria lista).
Campi: model_id, public_media_index, secret_media_index, last_public_media_id, last_secret_media_id, last_published_at, cycle_last_used.

## Copy (`copy.build_copy`)
`TESTO (LLM Emergent o 6 template IT a rotazione, contrasto Lato Pubblico vs Lato Segreto)\n\nCTA IT\n<link OF reale della creator>\n\n#hashtag (3-5)`.
Un solo URL nel testo (quello OF della creator, validato `onlyfans.com`), lunghezza pesata ≤ 280 (URL = 23). Nessun dato inventato (filtro FORBIDDEN). Fallback template se LLM offline.

## Admin
`/admin/x-autopilot`: stato · connessione · mock · modella x/N · ciclo · post oggi · ultima · prossima · Attiva/Pausa/Pubblica ora/Anteprima prossimo post/Salta modella ·
impostazioni (post/giorno, orari, timezone, copy AI, Italy Audience Mode) · rotazione · log minimo.
API `/api/admin/x-autopilot/`: `GET status|logs`, `POST start|pause|publish-now|skip|preview|test-connection`, `PATCH settings` (JWT admin).

## Collezioni
`x_autopilot_state` · `x_model_media_state` · `x_autopilot_log` · `x_autopilot_slots` (slot `x_YYYY-MM-DD_HH:MM`) · `x_autopilot_locks`.

## Fase successiva (solo su richiesta esplicita)
1. Credenziali in `backend/.env`: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` (+ `X_USER_ID`), `X_AUTOPILOT_MOCK=false`.
2. Implementare `RealXAdapter` (upload media v1.1 chunked → `POST /2/tweets` → reply) con OAuth 1.0a user context.
3. Test connessione → 1 post reale via PUBBLICA ORA → PASS → `X_AUTO_SCHEDULER_ENABLED=true` + Attiva.

## Test
`tests/test_x_autopilot.py` (16 test, casi A–Y + PHOTO_PAIR_SINGLE_POST, VIDEO_THREAD_FALLBACK, PUBLIC_FIRST_IN_THREAD, THREAD_COUNTS_AS_ONE_ROTATION_ITEM,
PARTIAL_THREAD_FAILURE_HANDLED, indipendenza Telegram/Instagram). Testing agent: `test_reports/iteration_25_x_autopilot.json`.

## FASE COLLEGAMENTO ACCOUNT X REALE (backend-only)
- Env backend (Secrets, mai nel codice/frontend/log): `X_CONSUMER_KEY`, `X_CONSUMER_SECRET`, `X_BEARER_TOKEN` (facoltativo: `X_ACCESS_TOKEN`/`X_ACCESS_TOKEN_SECRET` in alternativa al flusso OAuth),
  `X_OAUTH_CALLBACK_URL` (opzionale, default `https://<host>/api/admin/x-autopilot/auth/callback`), `X_REAL_POSTING_ENABLED` (gate write, default false), `X_AUTOPILOT_MOCK`, `X_AUTO_SCHEDULER_ENABLED`.
- `x_autopilot/xauth.py`: OAuth 1.0a 3-legged documentato (`POST oauth/request_token` → `oauth/authorize` → callback → `POST oauth/access_token`), token utente cifrato (Fernet, chiave derivata dal consumer secret)
  in Mongo `x_autopilot_auth`, identità READ `GET /2/users/me`, livello permessi da header `x-access-level` (`read-write` ⇒ X_WRITE_CAPABILITY_READY), app auth via `POST oauth2/token`.
  Contatori: `X_REAL_CALLS` = SOLO write reali (upload/post), `X_REAL_READ_CALLS` = auth/identità. `scrub()` maschera ogni segreto (env + token caricati).
- `RealXAdapter`: upload v2 chunked (`/2/media/upload/initialize` → `/{id}/append` → `/{id}/finalize` → STATUS) con pre-check MIME/dimensione sul nostro storage, `POST /2/tweets` (+ reply per thread).
  Ogni write richiede credenziali app + token utente + `X_REAL_POSTING_ENABLED=true`, altrimenti `WRITES_DISABLED` prima di qualsiasi rete.
- API admin: `GET /connection?live=` (report READ-ONLY), `POST /auth/start` (URL autorizzazione), `GET /auth/callback` (pubblica, redirect a `/admin/x-autopilot?x_auth=…`), `GET /auth/status`, `POST /auth/disconnect`.
- Admin UI: sezione "Account X reale" (pill APP AUTH / USER AUTH / ACCOUNT / SCRITTURA / post reali / gate, bottoni Collega / Verifica / Scollega, MISSING_MANUAL_STEP).
- Requisito Developer Portal (manuale, una volta): App → User authentication settings → App permissions "Read and write", Type "Web App, Automated App or Bot",
  Callback URI = `https://secret-side.emergent.host/api/admin/x-autopilot/auth/callback` (+ preview), Website URL = `https://secret-side.emergent.host`.
- Test: `tests/test_x_connection.py` (8 test, zero rete) + `tests/test_x_autopilot.py` (16) = 24/24; testing agent `iteration_31_x_connection.json` (0 bug). REAL_X_POSTS_CREATED=0.

## PRIMO POST REALE CONTROLLATO (`x_autopilot/realtest.py`)
`POST /api/admin/x-autopilot/real-test?execute=false|true` · `GET /real-test` · `POST /real-test/verify` (READ-only).
Gate: `X_AUTOPILOT_MOCK=false`, `X_REAL_POSTING_ENABLED=true`, `X_AUTO_SCHEDULER_ENABLED=false`, hard cap 1 (log + `x_real_runs` SENDING/UNVERIFIED/PUBLISHED),
account `@latosegreto` read-write, probe crediti (1 READ v2: 402 ⇒ STOP), prossima modella in coda con PHOTO Public + PHOTO Secret (SINGLE_POST), pre-check MIME/dimensione, copy con SOLO il link OF della modella.
Write: marker SENDING → upload PUBLIC → upload SECRET → media ids → UNA `POST /2/tweets` → read-back (`GET /2/tweets/{id}`: esiste, autore = account, 2 media, testo, link OF) → PUBLISHED (coda avanza 1 volta) | UNVERIFIED (mai reinvio; `verify` cerca tra i post recenti).
Test: `tests/test_x_real_test.py` (7) — suite X 31/31; testing agent iteration_32 (0 bug).
Produzione: richiede deploy + Secrets `X_CONSUMER_KEY/X_CONSUMER_SECRET/X_BEARER_TOKEN`, `X_AUTOPILOT_MOCK=false`, `X_REAL_POSTING_ENABLED=true`, `X_AUTO_SCHEDULER_ENABLED=false`, poi OAuth ("Collega account X") sul DB di produzione.
