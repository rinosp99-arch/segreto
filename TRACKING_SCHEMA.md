# TRACKING v2 — SCHEMA, REGOLE, EVENTI

Documento di riferimento del tracking comportamentale di LATO SEGRETO (privacy-safe). Client: `frontend/src/lib/analytics.js`
(+ `lib/engaged.js`). Ingestione: `POST /api/track/batch` (`backend/routes_public.py`). Aggregazioni: `backend/routes_analytics_v2.py`.

## 1. Identità e sessione

| Campo | Dove vive | Regola |
|---|---|---|
| `visitor_id` | `localStorage.ls_visitor_id` | UUID casuale anonimo, persistente. Stesso valore dello storico `ls_session_id` (continuità con i dati vecchi). Inviato anche come `session_id` per compatibilità. |
| `visit_id` | `sessionStorage.ls_visit` | UUID per **singola visita**. Nuova visita quando: (a) non esiste nella scheda (nuova scheda/finestra = nuova visita); (b) **inattività > 30 minuti** dall'ultimo evento; (c) landing con `?ref=` di campagna (`startCampaignVisit`) — così una campagna non si mescola al percorso precedente. Alla rotazione si azzerano anche le chiavi di deduplica (`ls_once`). |
| `seq` | `ls_visit.seq` | Contatore monotono dentro la visita: ordina gli eventi anche dentro lo stesso batch. |
| `ts_client` | — | Epoch ms del client. Il backend calcola `timestamp = ricezione − (sent_at − ts_client)` (offset relativo, robusto allo skew; ignorato oltre 1h). |

Nessun IP, nessun fingerprint, nessun dato personale. Il backend deriva solo `device` (mobile/tablet/desktop), `browser` (famiglia), `os`
(famiglia), `source` (famiglia del dominio referrer esterno: instagram/tiktok/google/…) e `country` (header CDN/lingua).

## 2. Schema comune (aggiunto automaticamente da `track()` a OGNI evento)

```
tipo            nome evento (legacy, invariato)         visitor_id, visit_id, seq, ts_client
path            location.pathname                       mode        public | secret (classe theme-secret al momento dell'evento; sovrascrivibile)
model_slug      modella corrente (se sul profilo)       entry_source come si è arrivati alla modella corrente (vedi §3)
profile_pos     n-esimo profilo distinto della visita   device_type mobile | tablet | desktop (lato client; il backend usa lo UA)
ref / fonte / campagna   attribuzione first-party (sessionStorage.ls_attr, da ?ref= ?fonte= ?campagna=)
referrer        solo host esterno della visita (es. https://instagram.com/) → source lato backend
```
Campi opzionali specifici: `cta_type`, `cta_position`, `cta_source`, `slot`, `from_model`, `to_model`, `input`, `platform`, `placement`, `valore`, `meta`.
Il backend scarta chiavi sensibili in `meta` (`password`, `token`, `email`, `authorization`, `cookie`) e tronca valori > 500 caratteri.

## 3. entry_source (attribuzione interna)

Impostato dall'elemento che avvia la navigazione (`setEntry`) e consumato dalla `page_view` del profilo (`beginProfile`, TTL 15s):

| Valore | Da dove |
|---|---|
| `home_card` | card della griglia Home (`ModelCard placement="home"`) |
| `filmstrip` | tile della pellicola in Home |
| `surprise` | pulsante Sorprendimi |
| `swipe` | gesto (`profile_swipe_*`) |
| `swipe_button` | frecce ‹ › / pill SCORRI / tastiera (`profile_nav_*_click`) |
| `related_models` | card "altre modelle" nel profilo |
| `search` | risultato della ricerca |
| `category` | card di una pagina categoria |
| `campaign` | primo profilo della visita con attribuzione `ref` e senza navigazione interna |
| `direct_profile` | URL diretto / nessun hint |

Tutti gli eventi successivi sul profilo (CTA, OF, social, video, scroll, swipe, marquee) ereditano l'`entry_source` della modella corrente.

## 4. Eventi (nome `tipo`) — nuovi ★, esistenti ✓, deduplica

| Evento | Stato | Dedup | Campi chiave |
|---|---|---|---|
| `home_view` | ★ | 1 per mount Home (remount < 15s ignorato) | mode |
| `home_model_card_impression` | ★ | 1 per visita per (modella, mode) — card ≥50% visibile per 500ms | model_slug, placement, meta.position/context |
| `home_model_card_click` / `model_card_click` | ★ | — | model_slug, placement (home / related / category) |
| `home_search_use` | ★ | — | meta.esito (selezione / abbandono / nessun_risultato), q_len, risultati, position — **mai il testo cercato** |
| `home_filter_use` | ★ | — | meta.filtro, meta.da |
| `home_category_click` | ★ | — | meta.categoria, meta.source |
| `home_surprise_click`, `home_surprise_profile_open` | ✓ | — | |
| `home_toggle_secret_on/off`, `home_mobile_toggle_*` | ✓ | — | |
| `pellicola_impression` | ✓ (norm.) | ★ 1 per visita per mode (era per mount) | |
| `pellicola_video_view` | ✓ (norm.) | ★ 1 per visita per modella (era per mount → −41% eventi) | |
| `pellicola_click_profilo` | ✓ | — | + entry_source=filmstrip |
| `of_global_marquee_impression` | ★ | 1 per visita per (placement, modella, mode) — ≥50% per 300ms | placement home/profile, model_slug |
| `of_global_marquee_home_click` / `profile_click` | ✓ | — | + placement, mode top-level |
| `page_view` | ✓ | — | ★ entry_source, profile_pos, from_model, mode |
| `secret_activate`, `secret_return`, `secret_time` | ✓ | — | + mode=secret; secret_return.valore = secondi dall'apertura |
| `cta_impression` | ★ (sostituisce `cta_view`, che resta riconosciuto) | 1 per visita per (cta_type, modella) — gallery ≥40% per 300ms; timed alla comparsa | cta_type gallery/timed, cta_position, cta_source, valore=secondi dal profilo |
| `message_shown` / `message_open` | ✓ | — | + cta_type=message, cta_position=envelope (message_shown = impression della CTA busta) |
| `cta_click`, `of_click` | ✓ | — | ★ cta_type, cta_position, valore=secondi dal profilo, meta.swipes, meta.profiles_seen, meta.last_nav_input (gesture/button/keyboard), mode, entry_source |
| `cta_dismiss` | ★ | — | cta_type=message (la barra temporizzata non ha chiusura) |
| `teaser_finale_click` | ✓ | — | + cta_type=teaser |
| `social_click_{platform}` | ✓ | — | ★ platform, mode, entry_source, valore |
| `profile_swipe_next` / `previous` | ✓ | — | ★ from_model, to_model, input=gesture, mode, profile_pos, meta.swipes |
| `profile_nav_next_click` / `prev_click` | ★ | — | from_model, to_model, input=button|keyboard, mode, profile_pos |
| `profile_swipe_public` / `secret` | rimossi (l'arrivo è la `page_view` con entry_source swipe/swipe_button); i dati storici restano letti | | |
| `video_impression` | ★ | 1 per visita per (modella, slot, mode) — tile ≥50% visibile e layer attivo | slot, mode, meta.media_mode |
| `video_start` | ★ | idem | primo `playing` |
| `video_25` / `50` / `75` / `video_complete` | ★ | idem (complete = ≥95%) | |
| `video_replay` | ★ | idem — loop riavvolto dopo aver superato l'80% | |
| `profile_scroll_25/50/75/100` | ★ | 1 per vista profilo | mode al momento, valore |
| `profile_engaged` | ★ | 1 per vista profilo (alla fine: cambio profilo / unmount / pagehide via beacon) | valore = secondi engaged totali; meta.public_s, secret_s, wall_s, max_scroll |
| `landing` | ✓ | ★ burst-dedup | + entry_source=campaign |

Dedup generale: eventi identici consecutivi entro 800ms sono scartati (StrictMode, doppi tap, remount).

## 5. ENGAGED TIME — regola

Il tempo conta solo se **pagina visibile** (`visibilitychange`) **e** attività utente negli ultimi **20s** (pointer / touch / scroll / tasto / wheel).
La riproduzione automatica muta NON è attività. Accumulo per intervalli, diviso per modalità (public/secret) — nessun heartbeat, un solo evento a fine vista.
Un rimbalzo < 2s senza attività non genera evento.

## 6. Coda e performance

`FLUSH_DELAY_MS 900` · `FLUSH_MAX 20` eventi per richiesta · `QUEUE_CAP 100` · `MAX_RETRY 2` (rete/5xx) · flush con `navigator.sendBeacon` (fallback
`fetch keepalive`) su `visibilitychange:hidden` / `pagehide` / `beforeunload`. Costo `track()` ≈ 15 µs/evento (1000 eventi = 15 ms, benchmark Node).
Percorso completo Home→profilo→Secret→swipe→OF = 36 eventi in 9–11 richieste, ~420 B/evento. Backend batch 20 eventi p50 ≈ 165 ms (RTT incluso),
1 query per i model_id dell'intero batch, `insert_many`. Indici Mongo: `visit_id+timestamp`, `entry_source+timestamp`, `tipo+visit_id`, oltre a
`timestamp+tipo`, `model_slug+timestamp`, `tipo+model_slug+timestamp`, `session_id+timestamp`, campagna/fonte/source.

## 7. Definizioni usate dal dashboard

- **Visita**: `visit_id` distinto (gli eventi legacy senza visit_id contano 1 visita per session_id legacy).
- **Visitatore**: `visitor_id` distinto.
- **ENGAGED** (step funnel): visita sul profilo con almeno uno tra video_start, scroll ≥50%, engaged ≥10s, o un'azione a valle.
- **Funnel chiuso**: ogni step richiede i precedenti nella stessa visita → drop-off esatto; il conteggio "grezzo" è mostrato accanto.
- **CTA impression / OF impression**: `cta_impression` ∪ `cta_view` (legacy) ∪ `message_shown`. Ogni CTA del profilo porta a OnlyFans.
- **Swipe IN**: eventi swipe/nav con `to_model` = modella (nessun evento di arrivo separato).
- **Percorsi**: token per visita (HOME · CARD · FILMSTRIP · SORPRENDIMI · RICERCA · {MODELLA} · SECRET · SWIPE · SWIPE ‹› · OF · OF GLOBALE), max 8 passi, ultime 5000 visite.
