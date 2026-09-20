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
