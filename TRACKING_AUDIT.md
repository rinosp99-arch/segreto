# AUDIT TRACKING — LATO SEGRETO

Stato reale del tracking (frontend pubblico → `POST /api/track` → `analytics_events`) confrontato con la specifica
"tracking come parte fondamentale". Nessun evento è stato aggiunto in questo giro: **questo è solo l'audit**.

Legenda: ✅ tracciato oggi · 🟡 parziale (esiste ma manca un campo/un caso) · ❌ TRACKING MANCANTE

Fonte dati (18/09): 1.793 eventi, 32 nomi evento distinti. Il 64% degli eventi (1.156) è precedente all'enrichment
backend e quindi senza `device / browser / source / path`. Da allora tutti gli eventi hanno questi campi.

---

## 1. SESSIONE

| Campo richiesto | Stato | Note |
|---|---|---|
| anonymous_session_id | 🟡 | `session_id` = UUID in **localStorage** (`ls_session_id`): è un **visitor id persistente**, non una sessione. Due visite a distanza di giorni = stesso id. Manca un `visit_id` per sessione (sessionStorage o timeout 30 min) → oggi "sessioni" e "visitatori" coincidono. |
| timestamp | ✅ | ISO UTC dal backend |
| event_name | ✅ | `tipo` (legacy, usato dal frontend) + `event` canonico (derivato dal backend) |
| model_slug | ✅ | dove pertinente |
| mode PUBLIC/SECRET | 🟡 | presente solo in `meta.mode` di: page_view via swipe, swipe, marquee globale; `cta_source: 'segreto'/'pubblico'` nella FilmStrip. **Assente** su of_click, cta_click, social_click, secret_time, toggle Home. |
| page/path | 🟡 | derivato dall'header `Referer` lato backend (`enrich_event`), non inviato dal client. Funziona ma dipende dalla Referrer-Policy del browser. Da inviare esplicitamente come `path`. |
| source (referrer dominio) | ✅ | `source` (direct / instagram / tiktok / google …) derivato lato backend |
| ref / fonte / campagna | ✅ | letti da `sessionStorage.ls_attr` e allegati a ogni evento (`api.js → track`) |
| device_type | ✅ | `device` mobile/desktop/tablet da UA lato backend |
| browser family | ✅ | `browser` chrome/safari/firefox/other (solo famiglia) |
| fingerprint | ✅ nessuno | ok privacy: nessun IP salvato nel documento (solo `country` derivato) |

**Dove intervenire:** `frontend/src/lib/api.js → track()`: aggiungere `visit_id`, `mode`, `path` a **ogni** payload in un solo punto (nessuna modifica ai singoli componenti).

## 2. HOME

| Evento richiesto | Stato | Evento attuale | Dove aggiungerlo |
|---|---|---|---|
| home_view | ❌ | — (i 240 `visit` del 10/09 sono dati di test, non del sito) | `pages/Home.js` (mount) |
| home_public_mode / home_secret_mode | ✅ | `home_toggle_secret_on/off`, `home_mobile_toggle_secret/public` | — |
| home_model_card_impression | ❌ | — | `components/ModelCard.js` (IntersectionObserver, dedup per sessione) |
| home_model_card_click | ❌ | — (`<Link>` senza tracking) | `components/ModelCard.js` onClick, con `posizione`, `mode`, `filtro attivo` |
| home_search_use | ❌ | — | `components/layout/SearchOverlay.js` (submit / selezione risultato) |
| home_filter_use | ❌ | — | `pages/Home.js` setFiltro |
| home_category_click | ❌ | — | `components/layout/Header.js` link categorie · `pages/CategoryPage.js` |
| home_surprise_click | ✅ | `home_surprise_click` + `home_surprise_profile_open {model_slug}` | — |
| home_filmstrip_impression | ✅ | `pellicola_impression` (1× per mount) | — |
| home_filmstrip_video_start | ✅ | `pellicola_video_view` (1× per slug per mount) — **41% di tutti gli eventi**: da deduplicare per sessione | `components/FilmStrip.js` |
| home_filmstrip_model_click | ✅ | `pellicola_click_profilo {posizione, modalita}` | — |
| of_global_marquee_impression | ❌ | — | `components/GlobalOfMarquee.js` (1× per pagina) |
| of_global_marquee_home_click | ✅ | con mode/ref/fonte/campagna | — |

## 3. PROFILO MODELLA

| Evento | Stato | Note |
|---|---|---|
| profile_view | ✅ | `page_view {model_slug}`; `meta.via = 'swipe'` solo se arrivo da swipe |
| profile_view_source (entry_source) | 🟡 | solo `swipe`. Manca: home_card, filmstrip, surprise, category, search, direct, campaign → v. §16 |
| profile_scroll_25/50/75/100 | ❌ | `pages/ModelProfile.js` (listener scroll passivo, soglie una-tantum) |
| profile_time_10s/30s/60s | ❌ | proposta efficiente: **un solo** evento `profile_engaged_time {secs}` inviato con `sendBeacon` all'uscita/cambio profilo, calcolato con `visibilitychange` (tempo visibile reale). Da lì derivano 10s/30s/60s in aggregazione, zero timer multipli. Oggi esiste solo `secret_time` (tempo nel Secret). |

## 4. LATO SEGRETO

| Evento | Stato | Note |
|---|---|---|
| secret_activation | ✅ | `secret_activate {valore: secondi dall'apertura profilo, meta.via}` |
| secret_return_public | ✅ | `secret_return` |
| secret_time | ✅ | `secret_time {valore: secondi}` (beacon su unload) |
| secret_scroll_depth | ❌ | insieme a profile_scroll con `mode` |
| secret_cta_seen | 🟡 | `cta_view` emesso **solo** per la CTA gallery (3 eventi in totale; aggiunto di recente). Manca per CTA temporizzata, busta/messaggio, sticky |
| secret_cta_click | ✅ | `cta_click {cta_source}` |
| Funnel Public → Secret → OF per creator | ✅ derivabile | già nel dettaglio modella v2 |

## 5. MEDIA

| Evento | Stato |
|---|---|
| media_impression, video_start, video_25/50/75/complete, video_replay, media_slot, media_mode | ❌ **tutto mancante** nel profilo. `MediaMorph.js` ha già `onTimeUpdate` e un IntersectionObserver (threshold 0.2): i punti di aggancio esistono. Deduplica per (sessione, modella, slot, mode) nel client. Nota: la FilmStrip in Home traccia già `pellicola_video_view` ma è un evento Home, non media del profilo. |

**Dove:** `components/MediaMorph.js` (props `slot`, `mode` già disponibili dal parent `ModelProfile.js`).

## 6. ONLYFANS PERSONALE

| Campo | Stato | Note |
|---|---|---|
| of_personal_cta_impression | 🟡 | solo `cta_view` gallery (v. §4) |
| of_personal_cta_click | ✅ | `of_click` (+ `cta_click` gemello) |
| model_slug | ✅ | |
| PUBLIC/SECRET | 🟡 | non esplicito: la CTA personale vive nel Secret, quindi oggi è implicito. Da aggiungere `meta.mode` |
| source | ✅ | `source` backend + `ref/fonte/campagna` |
| posizione CTA | ✅ | `cta_source`: of_click_gallery / of_click_timed / of_click_message / of_click_sticky |
| campagna/ref | ✅ | |
| percorso di ingresso | 🟡 | `meta.swipes`, `meta.profiles_seen` (solo eventi recenti); manca `entry_source` |

## 7. ONLYFANS GLOBALE

| Campo | Stato |
|---|---|
| of_global_marquee_home_click / profile_click | ✅ con `model_slug`, `meta.mode`, ref/fonte/campagna |
| impression | ❌ → `GlobalOfMarquee.js` |
| CTR | ❌ finché manca l'impression |
| Home vs profilo, modella, Public/Secret, source/campaign | ✅ già nel dashboard v2 |

## 8. SWIPE MODELLA

| Campo | Stato | Note |
|---|---|---|
| profile_swipe_next / previous | ✅ | `meta.to, meta.mode, meta.swipes` |
| profile_swipe_button_next / previous (pulsanti ‹ ›) | ❌ | oggi gesture e pulsanti (`profile-prev-arrow`, `profile-next-arrow`, pill `profile-nav-prev/next`) emettono **lo stesso** evento via `go()` in `pages/ProfileSwipe.js`. Aggiungere `meta.input: 'gesture' | 'button' | 'nav_pill'` (senza cambiare i nomi evento) oppure gli eventi dedicati richiesti |
| modella origine / destinazione | ✅ | `model_slug` + `meta.to`; arrivo: `profile_swipe_public/secret {meta.from}` |
| posizione nel percorso | ✅ | `meta.swipes` (contatore) |
| swipe medi/sessione, creator più raggiunte/lasciate, OF dopo swipe | ✅ | nel dashboard v2 |
| n. medio profili prima del click OF | ✅ derivabile | `of_click.meta.profiles_seen` (solo eventi recenti) |

## 9. NAVIGATORE SWIPE (pill ‹ ⇆ SCORRI ›)

| Evento | Stato |
|---|---|
| profile_nav_prev_click / next_click | ❌ (oggi confluisce in profile_swipe_*) → `pages/ProfileSwipe.js` righe dei bottoni `profile-nav-prev` / `profile-nav-next` |

## 10. SOCIAL

| Stato | Note |
|---|---|
| ✅ | `social_click_{platform}` con `cta_source = platform` (instagram, tiktok, telegram registrati). Il dashboard normalizza già in `platform`. Manca `meta.mode`. |

## 11. CTA TEMPORIZZATE / MESSAGGI

| Evento | Stato | Note |
|---|---|---|
| cta_impression | 🟡 | gallery: `cta_view`. Timed: ❌. Messaggio "Ti ha lasciato qualcosa…": ✅ `message_shown` (busta visibile) + `message_open` (busta aperta). Sticky: ❌ |
| cta_click | ✅ | `cta_click {cta_source}` per tutte e 4 |
| cta_dismiss | ❌ | `pages/ModelProfile.js` (chiusura CTA timed / busta) |
| cta_type, model_slug, mode | 🟡 | `cta_source` sì; `mode` no |
| seconds_since_profile_open | ❌ | `pages/ModelProfile.js` ha già `openedAt` per `secret_activate.valore`: riusabile |

## 12. USCITA / ABBANDONO

| Dato | Stato |
|---|---|
| ultimo evento della sessione | ✅ derivabile (max timestamp per session_id) — ma con visitor-id persistente la "sessione" è tutta la storia del visitatore → serve `visit_id` (§1) |
| ultima modella vista | ✅ derivabile |
| massimo scroll | ❌ dipende da §3 |
| Secret sì/no, OF sì/no | ✅ derivabile |
| evento esplicito di uscita | ❌ opzionale: `page_leave {path, secs}` via `sendBeacon` su `pagehide` — non invasivo |

## 13–14. FUNNEL E DROP-OFF PER MODELLA

| Step | Stato |
|---|---|
| PROFILE VIEW | ✅ |
| MEDIA ENGAGED | ❌ (§5) |
| SECRET ACTIVATION | ✅ |
| CTA VIEW | 🟡 (solo gallery) |
| CTA CLICK | ✅ |
| ONLYFANS CLICK | ✅ |

Il funnel v2 attuale usa: sessioni → profilo → Secret → CTA click → OF. Gli step MEDIA ENGAGED e CTA VIEW completi
diventano reali solo dopo §5 e §11. Il pannello "DOVE PERDI GLI UTENTI" (step / utenti / % proseguono / % abbandonano)
è derivabile lato backend senza nuovi eventi per gli step già tracciati.

## 15. PERCORSI

❌ Non aggregati oggi. Derivabili con una aggregazione backend per `session_id` ordinata per timestamp, riducendo
ogni evento a un token (HOME · CARD · FILMSTRIP · SORPRENDIMI · {MODELLA} · SECRET · SWIPE · OF) e contando i top-N
percorsi (max 6 passi). Prerequisiti per percorsi fedeli: `home_view`, `home_model_card_click`, `visit_id`.

## 16. ATTRIBUZIONE / entry_source

| Stato | Note |
|---|---|
| ref/fonte/campagna | ✅ preservati su ogni evento |
| entry_source | 🟡 solo `swipe` (`page_view.meta.via`). Da aggiungere in `lib/profileNav.js` (già usato per il carry dello swipe): scrivere `entry_source` in sessionStorage al click da card / filmstrip / surprise / categoria / ricerca / related e leggerlo in `page_view`. `direct_profile` se assente, `campaign` se `ls_attr` presente. |

## 17. TABELLA TUTTE LE MODELLE

| Colonna | Stato |
|---|---|
| profile views, unique sessions, Secret activations, Secret %, CTA clicks, CTA CTR, OF clicks, OF CTR, swipe IN/OUT, social clicks, global OF clicks | ✅ nel dashboard v2 |
| engaged sessions, video starts, video completion %, average engaged time | ❌ (§3, §5) |
| CTA impressions | 🟡 |
| average profiles/session | ✅ derivabile |
| ordinamento per colonna | ✅ |

## 18. DEVICE

✅ `device` presente dall'enrichment; filtro device e split nel dettaglio modella già nel v2. Manca solo il confronto
side-by-side mobile/desktop/tablet **per metrica** (es. OF CTR per device per modella): derivabile, nessun evento nuovo.

## 19. ORARIO / GIORNO

✅ Timeseries ora/giorno/settimana/mese (Europe/Rome) nel v2; per-ora nel dettaglio modella. Nessun evento nuovo.

## 21. PERFORMANCE (stato attuale del client)

| Requisito | Stato |
|---|---|
| invio asincrono | ✅ `api.post` fire-and-forget |
| sendBeacon | 🟡 solo `secret_time` (`_beacon`) |
| batching | ❌ ogni evento = 1 richiesta (ok ai volumi attuali; la queue+flush va introdotta insieme ai nuovi eventi media/scroll, che altrimenti moltiplicano le richieste) |
| deduplica | 🟡 per mount (FilmStrip), non per sessione |
| payload piccoli | ✅ |
| backend aggregation | ✅ v2 |
| indici DB | ✅ aggiunti (timestamp+tipo, model_slug+timestamp, tipo+model_slug+timestamp, campagna/fonte/source sparse, session_id+timestamp) |

## 22. PRIVACY

✅ Nessuna password/token/contenuto privato; nessun IP nel documento evento; UA ridotto a famiglia; session id troncato
nel log admin. ⚠️ Il `session_id` persistente in localStorage è tecnicamente un identificatore a lungo termine:
va bene per il prodotto, ma un `visit_id` per sessione renderebbe l'analisi più corretta e più privacy-friendly
(si può anche ruotare il visitor id ogni 30 giorni).

---

## RIEPILOGO — COSA MANCA (in ordine di valore)

| # | Eventi mancanti | File frontend | Dati necessari |
|---|---|---|---|
| A | `visit_id` + `mode` + `path` su ogni evento | `lib/api.js` (track), `lib/session.js` | sessionStorage visit id; mode dal contesto secret; `location.pathname` |
| B | `home_view`, `home_model_card_impression`, `home_model_card_click` | `pages/Home.js`, `components/ModelCard.js` | model_slug, posizione, filtro, mode |
| C | `entry_source` su `page_view` | `lib/profileNav.js`, `ModelCard.js`, `FilmStrip.js`, `Header.js` (surprise), `SearchOverlay.js`, `CategoryPage.js` | home_card / filmstrip / surprise / search / category / related / direct / campaign |
| D | `media_impression`, `video_start`, `video_25/50/75/complete`, `video_replay` | `components/MediaMorph.js` (+ props da `ModelProfile.js`) | slot, mode, model_slug; dedup per (visit, slug, slot, mode) |
| E | `profile_scroll_25/50/75/100`, `profile_engaged_time` (1 beacon) | `pages/ModelProfile.js` | mode, secs visibili |
| F | `cta_impression` per timed/message/sticky, `cta_dismiss`, `seconds_since_profile_open` | `pages/ModelProfile.js` | cta_type, mode, openedAt |
| G | `of_global_marquee_impression` | `components/GlobalOfMarquee.js` | placement home/profile, mode |
| H | `meta.input` gesture/button/nav_pill sugli swipe (o eventi `profile_swipe_button_*`, `profile_nav_*_click`) | `pages/ProfileSwipe.js` | — |
| I | `home_search_use`, `home_filter_use`, `home_category_click` | `SearchOverlay.js`, `Home.js`, `Header.js` | query length (non la query), filtro, categoria |
| J | `meta.mode` su of_click / cta_click / social_click | `pages/ModelProfile.js` (o centralizzato in A) | — |
| K | queue + `sendBeacon`/keepalive + flush su `pagehide` | `lib/api.js` | — (necessario prima di D/E per non moltiplicare le richieste) |

Nessuno di questi eventi viene oggi "ricostruito": nel dashboard sono contrassegnati come non disponibili.
Nomi evento esistenti: **nessuna rinomina**; i nuovi campi sono additivi.
