# OF AUTOPILOT — FASE CONNESSIONE (The Only API, READ-ONLY)

Collegamento sicuro del progetto al provider **The Only API** per l'unico account OnlyFans **latosegreto**. Fondamenta del futuro OF Autopilot:
il motore dipenderà SOLO da `OFProviderAdapter` (vendor-neutral), implementato oggi da `TheOnlyAPIAdapter`.

## Stato
| Campo | Valore |
|---|---|
| PROVIDER | THE_ONLY_API (`OF_PROVIDER=the_only_api`) |
| CONNECTION_STATUS | CONNECTED (verificato: whoami → crm_id coincide; `GET /accounts`) |
| ACCOUNT_USERNAME / PLATFORM | latosegreto / onlyfans (unico account OnlyFans nel pannello) |
| ACCOUNT_STATUS | HEALTHY (`GET /api2/v2/users/me` con `user-id` = of_user_id: profilo live coerente) |
| THE_ONLY_OF_USER_ID | auto-scoperto via API e salvato server-side (`of_autopilot_connection`) + `backend/.env`; esposto solo mascherato |
| OF_REAL_POSTING_ENABLED / OF_AUTO_SCHEDULER_ENABLED | false / false |
| OF_REAL_WRITE_CALLS | 0 (metodi write bloccati prima della rete; gate pannello `allow_of_write_actions=false`) |

## Sicurezza
- `THE_ONLY_API_KEY`, `THE_ONLY_CRM_ID` solo in `backend/.env` (git-ignored); mai in frontend/log/API/report/test.
- Header `X-API-Key` esclusivo (mai query param, mai Bearer). Filtro logging redige la key (`****`) su httpx/httpcore/uvicorn/root; errori scrubbati.
- `GET /accounts` chiamato SENZA `include_session` (mai `sess`/`auth_id`/`proxy`). Nessuna route proxy/login/polling-PATCH usata.
- Regola STOP: se il pannello non contiene esattamente un account OnlyFans `latosegreto` → `ACCOUNT_MISMATCH` / `AMBIGUOUS_ACCOUNTS`, nessuna azione.

## Endpoint documentati usati (base `https://theonlyapi.com/api/crm/{crm_id}`)
READ (fase attuale): `GET https://api.theonlyapi.com/api/whoami` · `GET /accounts` · `GET /accounts/{of_user_id}/polling` · `GET /api2/v2/users/me` · `GET /api2/v2/schedules?limit&offset` · `GET /api2/v2/posts/{post_id}`.
WRITE (preparati, bloccati): `POST /accounts/{of_user_id}/media` (multipart `file` → oggetto `media` conservato COMPLETO) · `POST /api2/v2/posts` con `text`, **`mediaFiles:[<oggetto media intero>]`**, **`isScheduled:1` + `scheduledDate`** (mai `postedAt`).
Delete post programmato: **non documentato** → `delete_scheduled_post` solleva `NOT_DOCUMENTED` senza chiamate.
Le risposte passthrough `/api2/v2/*` arrivano incapsulate `{success, status_code, data}` → l'adapter restituisce `data`.

## Fail-safe scheduling (futuro)
CREATE → post id → `GET /api2/v2/schedules` (paginato, `hasMore`) → id presente ? `SCHEDULE_CONFIRMED` : `SCHEDULE_NOT_CONFIRMED` (la coda NON avanza).

## File
`backend/of_autopilot/providers/base.py` (interfaccia + dataclass) · `providers/the_only_api.py` (adapter) · `connection.py` (discovery/stato) · `routes.py`
(`GET /api/admin/of-autopilot/connection`, `POST /api/admin/of-autopilot/test-connection`, JWT admin) · `frontend/src/pages/admin/AdminOfAutopilot.js` (card minima) · `tests/test_of_provider_connection.py` (7 test, A–S).

## Prossima fase (solo su autorizzazione esplicita)
OF Autopilot: MODEL PUBLISHED → media Public + Secret → caption → upload → schedule sul solo account latosegreto → verify schedule → prossima modella.
Richiede: `OF_REAL_POSTING_ENABLED=true` + `PATCH /accounts/{of_user_id}/polling {allow_of_write_actions:true}` (mai eseguito in questa fase) + UN post reale di test.

---

# OF AUTOPILOT — MOTORE COMPLETO (FASE MOCK)

Flusso: MODELLA PUBLISHED → prossimo media PUBLIC + prossimo media SECRET della STESSA modella (due cursori, dal DB/storage Lato Segreto) →
validazione reale leggera (HEAD / GET Range 0-0 sul NOSTRO storage: https, 200/206, MIME coerente — `octet-stream` tollerato solo con estensione coerente —, size>0)
→ caption IT (LLM + template) + `Scoprila su OnlyFans:\n<link OF reale della modella>` → upload PUBLIC, upload SECRET (oggetto media COMPLETO, `of_media_uploads`)
→ PUBBLICA ORA = post immediato + verify `GET post` (POST_CONFIRMED) | SCHEDULER = `isScheduled`+`scheduledDate` + verify `GET schedules` (SCHEDULE_CONFIRMED)
→ SOLO dopo conferma: cursori + coda avanzano. Upload/create/verify falliti → nessun avanzamento, tentativi limitati (MAX_MEDIA_ATTEMPTS=3 per lato).

Stato fase: `OF_AUTOPILOT_MOCK=true` (MockOFProvider per tutte le write; provider reale solo in lettura), `OF_REAL_POSTING_ENABLED=false`, `OF_AUTO_SCHEDULER_ENABLED=false`,
THE_ONLY_API_REAL_WRITE_CALLS=0. Default 3 post/giorno 11:30 · 17:30 · 22:00 Europe/Rome (Admin). Slot `of_YYYY-MM-DD_HH:MM` (preparato fino a 30' prima, scheduledDate = ora slot).
Eleggibilità: PUBLISHED + ≥1 PUBLIC + ≥1 SECRET + link onlyfans.com della modella + non `of_autopilot_excluded`. Skip: SKIPPED_NO_PUBLIC / SKIPPED_NO_SECRET / SKIPPED_NO_OF_LINK / SKIPPED_EXCLUDED.
Nota reale emersa: per file inesistenti l'host SPA risponde `200 text/html` → scartato come `MIME_MISMATCH` (il solo status HTTP non basta).

Collezioni: `of_autopilot_state` · `of_model_media_state` · `of_media_uploads` · `of_autopilot_logs` · `of_autopilot_slots` · `of_autopilot_locks`.
API: `GET status|preview|logs|uploads|connection`, `POST start|pause|publish-now|skip|test-connection`, `PATCH settings` (nessuna route per abilitare real posting).
File: `engine.py`, `media.py`, `caption.py`, `jobs.py`, `providers/mock.py`, `routes.py`, `AdminOfAutopilot.js`, `tests/test_of_autopilot.py` (16) + `tests/test_of_provider_connection.py` (7).
Prossima fase (autorizzazione esplicita): 1 solo post reale controllato (OF_REAL_POSTING_ENABLED=true + `allow_of_write_actions` nel pannello) → verifica su OnlyFans → poi valutazione AUTO ON.
