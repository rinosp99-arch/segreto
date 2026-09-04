# plan.md — LATO SEGRETO (React + FastAPI + MongoDB)

## 1) Objectives
- Consegnare una web app premium 18+ **tutta in italiano** (pubblico + admin) per promuovere creator/modelle con profili OnlyFans.
- Mantenere e migliorare la feature distintiva: **trasformazione cinematografica** Lato Pubblico → Lato Segreto **sulla stessa pagina/URL, no refresh**.
- Conversione e attribuzione first‑party: funnel verso OnlyFans con tracking (ref/fonte/campagna) persistente e analytics reali (no fake stats).
- Architettura “future‑proof SEO”: dati/slug/metadata/contenuti nel backend; frontend responsabile del rendering (migrazione futura a SSR/prerender possibile senza cloaking).
- Performance mobile-first: lazy media, nessun jank, rispetto autoplay policy (muted/playsInline), fallback robusti.
- **UX Home:** sezione “**IN MOVIMENTO**” come **pellicola cinematografica** seamless/infinita (non carosello), che si trasforma insieme allo switch Pubblico/Segreto.
- **Nuovo obiettivo operativo (admin):** rendere **rapidissimo** sostituire contenuti DEMO con contenuti REALI per decine di creator, con:
  - stato DEMO/REALE robusto (non solo heuristics URL)
  - checklist “Pronta alla pubblicazione” basata SOLO su requisiti obbligatori
  - blocco pubblicazione con messaggi chiari e lista campi mancanti
  - import massivo media e strumenti di produttività (copia configurazione, anteprima admin bozza)

**Stato attuale (snapshot)**
- Phase 1–6: implementate (home griglia, profili con trasformazione, admin/auth, analytics base/funnel, categorie/articoli/SEO endpoints, campagne/referral). Agent-tested.
- Phase 7 “IN MOVIMENTO”: **completata** end-to-end e verificata da testing agent (iteration_6).
- Admin: aggiunto **controllo DEMO/REALE automatico** + badge/summary lista + pannello editor “Stato contenuti” (agent-tested via curl + screenshot). Da evolvere con override manuale e workflow PRONTA/INCOMPLETA.

---

## 2) Implementation Steps

### Phase 1 — Core POC (isolato) della Trasformazione + Tracking
**User stories (POC)**
1. Come utente, apro un profilo modella e vedo chiaramente il **Lato Pubblico**.
2. Come utente, premo “**NON DOVRESTI PREMERLO**” e la pagina si trasforma senza cambiare URL.
3. Come utente, percepisco blackout + “Te l’avevamo detto.” + cambio foto/testi/palette in <1.2s.
4. Come utente, posso tornare al Lato Pubblico senza ricaricare.
5. Come owner, vedo eventi tracciati (view, secret_activate, of_click_*).

**Stato:** completata (agent-tested).

---

### Phase 2 — V1 App Development (pubblico)
**User stories (V1 pubblico)**
1. Come utente, supero un gate 18+ premium e torno senza ripeterlo ad ogni pagina (persistenza).
2. Come utente, nella Home vedo una griglia premium 2-col mobile con ricerca/filtri.
3. Come utente, apro una modella e vivo la trasformazione Lato Segreto completa con foto/video/copy.
4. Come utente, dopo ~35s nel Lato Segreto ricevo “Ti ha lasciato qualcosa…” e posso aprire il messaggio.
5. Come utente, clicco “CONTINUA CON ME” e vado su OnlyFans (link tracciato, non rotto).

**Stato:** completata (agent-tested).

---

### Phase 3 — Admin + Auth + Media Management
**User stories (Admin)**
1. Come admin, posso fare login/logout e le route admin sono protette lato backend.
2. Come admin, creo/modifico una modella (bozza/pubblica/disattiva) senza toccare JSON.
3. Come admin, gestisco coppie media pubblico↔segreto e vedo un’anteprima trasformazione.
4. Come admin, configuro CTA, timer/messaggio 35s, tema/palette del Lato Segreto.
5. Come admin, imposto SEO title/meta e l’ordine in Home.

**Stato:** completata (agent-tested). Nota: workflow pubblicazione verrà raffinato in Phase 8 con checklist e blocchi “solo obbligatori”.

---

### Phase 4 — Analytics Dashboard + Funnel
**User stories (Analytics)**
1. Come owner, vedo visite e attivazioni Lato Segreto per modella.
2. Come owner, vedo funnel VISITA→SEGRETO→MESSAGGIO→CLICK OF.
3. Come owner, confronto OGGI/7G/30G e leaderboard CTR.
4. Come owner, distinguo sorgenti click OnlyFans.
5. Come owner, so quali articoli generano click verso modelle e OF.

**Stato:** completata (agent-tested) + campagne/referral integrati.

---

### Phase 5 — SEO tecnico + Categorie + Editorial/Blog + Webhook integrazione
**User stories (SEO/Editoriale)**
1. Come utente, apro /categorie/{slug} e trovo modelle pertinenti + breadcrumb.
2. Come motore di ricerca, trovo sitemap.xml aggiornata con modelle/categorie/articoli pubblicati.
3. Come admin, creo un articolo in bozza, lo anteprimo e lo pubblico.
4. Come sistema esterno, invio un articolo via webhook e arriva come BOZZA (default OFF auto-publish).
5. Come owner, misuro ARTICOLO→MODELLA→LATO SEGRETO→CLICK OF.

**Stato:** completata (agent-tested).

---

### Phase 6 — Performance, Mobile Polish, Security Hardening, Final QA
**User stories (Qualità)**
1. Come utente mobile, scrollo fluido e i media caricano lazy senza layout shift.
2. Come utente, vedo una UI accessibile (focus, contrasto, keyboard, reduced motion).
3. Come owner, non espongo secrets nel frontend e l’admin è protetto.
4. Come utente, la trasformazione resta fluida anche con video (poster + lazy).
5. Come utente, trovo pagine legali e un 404 coerente.

**Stato:** completata in gran parte; quality gate continuo ad ogni nuova feature.

---

### Phase 7 — HOME “IN MOVIMENTO” (Pellicola cinematografica)
**Scope**
Nuova sezione in Home (dopo ~8–12 modelle) con fascia orizzontale di teaser video verticali (10–15s; demo ~12s) che scorre lentamente e continuamente da destra verso sinistra, senza reset visibile. Non è un carousel standard (niente frecce/pallini). Deve trasformarsi in modo cinematografico insieme allo switch Pubblico/Segreto senza scatti o video neri e mantenendo la posizione nel movimento.

**Stato:** COMPLETATA — implementata end-to-end e verificata dal testing agent (iteration_6): pellicola seamless, cap 8 video attivi rispettato, poster fallback (no black), pausa fuori viewport, trasformazione Pubblico↔Segreto continua, analytics impression/video_view/click attive, teaser demo rigenerati a ~12s seamless. Seconda fila predisposta ma OFF di default.

---

### Phase 8 — Admin Content Workflow (DEMO/REALE + INCOMPLETA/PRONTA + Produttività)
**Vincolo:** non modificare il design pubblico già approvato. Questa iterazione riguarda soprattutto il workflow amministrativo.

#### 8.1 Concetti di stato (distinti e non sovrapposti)
- **DEMO**: utilizza ancora contenuti temporanei (ma non necessariamente incompleta).
- **INCOMPLETA**: mancano contenuti obbligatori.
- **PRONTA**: tutti i contenuti obbligatori (e reali) sono presenti.
- **PUBBLICATA**: è effettivamente visibile nel sito.

#### 8.2 DEMO/REALE: rilevamento + override manuale per media
**Problema:** non affidarsi solo al riconoscimento automatico dell’URL (CDN/URL esterni). 

**Soluzione**
- Mantenere heuristics automatiche (stock hosts + /media/ + *_demo), ma introdurre per ogni media un campo:
  - `stato_contenuto`: `AUTO` | `DEMO` | `REALE` (default: `AUTO`)
- Se `REALE` manuale: il sistema lo tratta come reale anche se URL “sospetto”.
- Se `DEMO` manuale: forzare demo anche se URL sembra reale.

**Copertura:**
- Foto card / hero / teaser / secret hero
- Media pairs (pubblico+segreto) incl. poster video
- Pellicola Home (pubblico+segreto) incl. poster
- Media messaggio segreto (foto/video)
- (Opzionale) link esterni: mantenere solo AUTO demo-detection per “*_demo”, ma non bloccare PRONTA per social.

#### 8.3 Checklist “Pronta alla pubblicazione” (SOLO obbligatori)
**Default requisiti obbligatori**
- conferma maggiorenne
- nome
- slug
- foto card
- **≥ 3 foto pubbliche** (da `media_pairs` tipo image lato pubblico)
- **≥ 3 foto segrete** (da `media_pairs` tipo image lato segreto)
- **≥ 1 video pubblico** (da `media_pairs` tipo video lato pubblico)
- **≥ 1 video segreto** (da `media_pairs` tipo video lato segreto)
- descrizione pubblica
- descrizione segreta
- claim (frase breve)
- link OnlyFans

**Requisiti condizionali (Pellicola)**
- Se “Mostra nella pellicola” = SÌ:
  - video pellicola pubblico
  - video pellicola segreto

**Non obbligatori (mai blocco):** Instagram/TikTok/social, 2° video opzionale, Snapchat ecc.

#### 8.4 Blocco pubblicazione (solo obbligatori) + errore strutturato
- Backend:
  - quando si tenta di impostare stato `pubblicata`, validare la checklist obbligatoria.
  - se mancano campi: rispondere **HTTP 400** con payload strutturato:
    - `detail`: "NON PUOI ANCORA PUBBLICARE"
    - `missing_required`: ["Foto Segreta 2", "Video Segreto", "Link OnlyFans", ...]
    - `missing_count`: N
- Frontend admin:
  - mostrare dialog/alert premium con titolo, lista mancanti e CTA **COMPLETA PROFILO**.

#### 8.5 Lista MODELLE: filtri + conteggi
Aggiungere filtri:
- TUTTE
- SOLO DEMO
- SOLO REALI
- INCOMPLETE
- PRONTE ALLA PUBBLICAZIONE

Mostrare conteggi nel UI (es. “TUTTE 48 · DEMO 31 · REALI 17 · INCOMPLETE 8”).

#### 8.6 Editor modella: checklist chiara + stato complessivo
- Nuovo pannello “CHECKLIST PUBBLICAZIONE” (required + optional):
  - ✅ / ⚠ / ❌ con label esplicite (come esempio utente)
  - in fondo: “PRONTA ✅” oppure “MANCANO N ELEMENTI OBBLIGATORI”
- Integrare con pannello DEMO già presente, ma separando:
  - “DEMO/REALE” (per contenuti temporanei)
  - “INCOMPLETA/PRONTA” (per requisiti)

#### 8.7 Import Rapido media (multi-file drag & drop)
Obiettivo: evitare 15 upload singoli.
- UI: “IMPORT RAPIDO” nell’editor modella
- supporto multi-selezione file + drag & drop
- flow:
  1) carica batch (object storage) 
  2) mostra lista file con anteprima
  3) assegnazione rapida a “slot” (Foto Pubblica 1, Foto Segreta 1, ... Video Pubblico, Video Segreto, Pellicola, poster)
  4) supporto drag & drop + dropdown per slot

#### 8.8 Import multiplo da URL (incolla più link)
- UI: textarea “INCOLLA PIÙ LINK” (uno per riga)
- backend service (o FE fetch) per scaricare e validare (dimensione/MIME), poi upload su storage
- prima del salvataggio: **anteprima** + assegnazione a slot

#### 8.9 Duplica configurazione (no contenuti personali)
Funzione: “COPIA IMPOSTAZIONI DA UN’ALTRA MODELLA”
- Copiare SOLO configurazione:
  - preset tema segreto
  - regia (fumo/luci/glow/movimento + suoni)
  - CTA temporizzata (timer/copy/stile)
  - messaggio 35s (timer/testo/CTA **senza** media)
  - impostazioni pellicola (toggle/priorità/ordine, ma **senza** media)
- Non copiare: foto/video/poster, bio, claim, onlyfans, social.

#### 8.10 Anteprima completa admin per bozze (non indicizzabile)
- Obiettivo: aprire il profilo come utente, anche se in bozza, ma **solo per admin**.
- Backend:
  - estendere GET model endpoints per accettare `stato=bozza` se request ha token admin valido.
  - response con header/meta `noindex` (o flag API) per la pagina.
- Frontend:
  - bottone “ANTEPRIMA SITO” in ModelEditor
  - apre `/modelle/{slug}?preview=1` (o route dedicata) e il frontend imposta `noindex` via `setSeo({noindex:true})`.

#### 8.11 Test end-to-end (obbligatorio)
Scenario completo:
1) crea nuova modella → stato iniziale INCOMPLETA
2) import rapido media (multi-file)
3) pairing Pubblico↔Segreto + poster
4) inserisci descrizioni + claim + link OF
5) conferma maggiorenne
6) attiva pellicola + inserisci video pellicola
7) stato diventa PRONTA
8) apri anteprima (solo admin, noindex)
9) pubblica
10) modella appare in Home
11) Lato Segreto funziona
12) Pellicola funziona
13) analytics funzionano

**Stato:** COMPLETATA — implementata end-to-end e verificata dal testing agent (iteration_7): backend 100% (46/46), frontend 100%. Override manuale per-media rispettato (nessun falso positivo con URL demo-looking), blocco pubblicazione solo su obbligatori con 400 strutturato + modale "COMPLETA PROFILO", filtri+conteggi lista, checklist editor, Import Rapido (file+URL), Copia configurazione (solo config), Anteprima admin bozze non indicizzabile. Design pubblico invariato.

---

## 3) Next Actions
1. Implementare Phase 8 (override manuale per-media, checklist required, filtri lista, blocco pubblicazione con errori strutturati, import rapido file+URL, copia configurazione, anteprima admin bozza).
2. Test end-to-end dello scenario di creazione modella fino a pubblicazione senza modificare codice.
3. Aggiornare questo plan.md con stato “COMPLETATA” per Phase 8 solo dopo testing agent.

---

## 4) Success Criteria
- Trasformazione Lato Pubblico→Segreto: stessa URL, zero refresh, 600–1200ms, percezione “luxury cinematic”, reverse ok, reduced-motion ok.
- Home: griglia premium + filtri+search+Sorprendimi + stato “scoperto” persistente.
- Conversion: CTA OnlyFans tracciate per sorgente + messaggio ~35s con regole corrette.
- Admin: login sicuro + CRUD completo + pairing media + publish workflow robusto.
- Analytics: funnel e leaderboard basati su eventi reali + campagne/referral.
- SEO best-possible (senza SSR): meta dinamici, canonical, OG, structured data, sitemap/robots, categorie+articoli indicizzabili.
- **IN MOVIMENTO:** pellicola seamless (nessun salto/reset/spazio vuoto), autoplay affidabile, poster fallback (no video neri), max 8 video attivi, pausa fuori viewport, trasformazione Pubblico↔Segreto continua e cinematografica, tracking completo (impression/view/click) e attribuzione end-to-end.
- **Workflow contenuti (Phase 8):**
  - DEMO/REALE affidabile con override manuale per-media
  - distinzione chiara DEMO vs INCOMPLETA/PRONTA/PUBBLICATA
  - blocco pubblicazione solo su required, con lista mancanti e CTA “Completa profilo”
  - filtri admin con conteggi
  - import rapido file/URL + assegnazione slot + anteprima
  - copia configurazione senza contenuti personali
  - anteprima admin bozza non indicizzabile
