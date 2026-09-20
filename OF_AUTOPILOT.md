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

## FEED + MASS MESSAGE (fase MOCK ONLY)
Per ogni modella della coda: FEED post → `FEED_STATUS=OK` (verifica read-back) → MASS MESSAGE a tutti i fan/subscriber con la **stessa coppia Public+Secret**
(vault ids letti dal post confermato) e copy **diverso** (`👀 Hai già scoperto NOME? / ✨ LATO PUBBLICO / 🔥 LATO SEGRETO / ❤️‍🔥 Scoprila qui: + link OF DB`) →
`MASS_DM_STATUS=OK` (verifica read-back) → solo allora la coda avanza. Stato per (modella, ciclo) in `of_model_runs`.
- Feed OK + DM fallito → nessun nuovo feed, si ritenta solo il DM (PUBBLICA ORA / tick). DM già inviato (id presente) → mai una seconda volta (`UNVERIFIED` non viene mai rispedito).
- Provider: `OFProviderAdapter` → `TheOnlyAPIAdapter`, solo endpoint documentati OnlyFans passthrough: `POST /api2/v2/messages/queue` (`queueBuyers: []` = tutti i subscriber),
  `GET /api2/v2/messages/queue` (verifica), `POST /api2/v2/messages/queue/size` (audience).
- Gate: `OF_MASS_DM_MOCK=true` + `OF_MASS_DM_ENABLED=false` (default). DM reale solo con `OF_MASS_DM_ENABLED=true` **e** `OF_MASS_DM_MOCK=false` **e** `OF_REAL_POSTING_ENABLED=true`;
  altrimenti l'adapter alza `MASS_DM_DISABLED` prima di qualsiasi rete. DM disattivato → comportamento feed-only invariato. DM mock dopo feed reale → non eseguito (`MOCK_ONLY`).
- Scheduler (quando attivo): feed programmato → DM dovuto 2' dopo la pubblicazione, gestito dal tick prima di ogni nuovo slot. Ora resta `OF_AUTO_SCHEDULER_ENABLED=false`.
- Admin: riga "Modella corrente: FEED · MASS MESSAGE" (OK/PENDING/FAILED). Test: `tests/test_of_mass_dm.py`.

### Test DM-only da post esistente
`POST /api/admin/of-autopilot/mass-dm-test` `{model_slug, provider_post_id, execute}` — `execute=false` = solo pre-check READ-ONLY + anteprima copy (zero write);
`execute=true` = se tutti i check PASS: gate on → **1** mass message a tutti i subscriber con i vault id del post → verifica READ → stato in `of_model_runs` (`post:<id>`) → gate off + verifica.
Hard cap: 1 mass DM reale totale (`REAL_MASS_DM_TEST_MAX`), nessun nuovo feed, nessuna altra modella, STOP su qualsiasi check FAIL.

### Mass DM reale via CRM (modalità scelta dopo il test)
Il passthrough `queueBuyers: []` su OnlyFans risolve 0 destinatari (`queue/size`=0) → il test è stato abortito in sicurezza. La route `mass-dm-test` ora usa la modalità CRM documentata
`POST /accounts/{id}/messages/mass` con `audience.type=all` e `dry_run:true` (recipients + campione, nessun invio) → stesso body `dry_run:false`. Nessun queue id: verifica via `GET chats/{fan}/messages`
sui fan campione; marker `crm:<id>` in `of_model_runs` → mai un secondo invio (anche dopo timeout: stato `UNVERIFIED`). `background=true` + `GET /mass-dm-test/{post_id}` per invii lunghi.
