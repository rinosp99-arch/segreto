# models.prepare_complete — Matrice formale del formulario modella

Fonte dell'audit: `frontend/src/pages/admin/ModelEditor.js` (form reale), `backend/schemas.py::ModelIn` (DB),
`backend/v1_models.py` (patch_model deep-merge / readiness), `backend/v1_ai_policy.py::DEFAULT_AI_POLICY.review_fields`,
`backend/v1_seo.py::audit_model` (SEO safe fix), `backend/content_status.py::compute_readiness`.

Legenda colonna **Classe**:
- **SAFE** → applicato subito da `models.prepare_complete` (versionato, rollback.session)
- **REVIEW** → preparato completamente in preview, applicato solo dopo `approveApproval` (policy `review_fields`)
- **REAL_DATA** → dato reale non inventabile: accettato SOLO se fornito esplicitamente dall'utente; readiness = `MISSING_REAL_DATA`
- **MEDIA** → NON gestito da `fields` (usare `media[]` o l'editor); readiness = `MISSING_MEDIA`
- **SEO_AUTO** → derivato automaticamente da `seo_safe_fix=true` se non fornito
- **BLOCKED** → mai accettato dal workflow (rimosso con warning)

Colonna **Req**: R = obbligatorio per pubblicare (checklist), O = opzionale.

| Form field (sezione) | DB field | API `parameters.fields` | Handler | Classe | Req |
|---|---|---|---|---|---|
| **Dati principali** | | | | | |
| Nome | `nome` | `parameters.nome` (param, non in fields) | `create_model` | SAFE (creazione) | R |
| Nome artistico | `nome_artistico` | `fields.nome_artistico` | `patch_model` via approval `models.update` | REVIEW | O (default = nome) |
| Slug (URL) | `slug` | `fields.slug` | approval `models.update` → `unique_slug` | REVIEW | R (auto da nome) |
| Link OnlyFans | `onlyfans_url` | `fields.onlyfans_url` | approval `models.update` | REVIEW + REAL_DATA | R |
| Frase breve (claim) | `frase` | `fields.frase` | approval `models.update` | REVIEW | R |
| Testo CTA principale | `cta_testo` | `fields.cta_testo` | `patch_model` | SAFE | O |
| Bio pubblica | `bio` | `fields.bio` | approval `models.update` | REVIEW | R |
| Bio segreta | `bio_segreta` | `fields.bio_segreta` | approval `models.update` | REVIEW | R |
| Testo teaser (limite) | `teaser_copy` | `fields.teaser_copy` | `patch_model` | SAFE | O |
| **Immagini principali** | | | | | |
| Foto card / copertina / teaser / hero segreta | `foto_card`, `foto_copertina`, `foto_card_teaser`, `foto_segreta_hero` | `parameters.media[] {slot}` | `apply_media_to_slot` | MEDIA | R (foto_card) |
| **Coppie di contenuti** | `media_pairs[]` (url, poster, alt) | `parameters.media[]` | `apply_media_to_slot` | MEDIA | R (3+3 foto, 1+1 video) |
| ALT media | `media_pairs[].{pubblico,segreto}.alt` | `media[].alt` / SEO fix `MISSING_ALT_MEDIA` | `apply_issue_fix` | SEO_AUTO (solo se media presenti) | O |
| **Categorie, tag e badge** | | | | | |
| Categorie | `categorie[]` | `fields.categorie` (slug esistenti) | `patch_model` | SAFE | O |
| Tag | `tag[]` | `fields.tag` | `patch_model` | SAFE | O |
| Badge | `badge` | `fields.badge` (enum) | `patch_model` | SAFE | O |
| (tipo badge, non in form) | `badge_tipo` | `fields.badge_tipo` (editoriale/dati) | `patch_model` | SAFE | O |
| **Personalizzazione Lato Segreto (tema)** | | | | | |
| Preset | `tema.preset` | `fields.tema.preset` (bordeaux/tattoo/dolce/sportiva/cosplay) | `patch_model` | SAFE | O |
| Colore primario (HSL) | `tema.colore_primario` | `fields.tema.colore_primario` "H S% L%" | `patch_model` | SAFE | O |
| Colore secondario (HSL) | `tema.colore_secondario` | `fields.tema.colore_secondario` | `patch_model` | SAFE | O |
| Grana (0-1) | `tema.grain` | `fields.tema.grain` number 0..1 | `patch_model` | SAFE | O |
| Frase di attivazione | `tema.frase_attivazione` | `fields.tema.frase_attivazione` | `patch_model` | SAFE | O |
| Testo dopo il click | `tema.testo_dopo_click` | `fields.tema.testo_dopo_click` | `patch_model` | SAFE | O |
| Glow | `tema.glow` | `fields.tema.glow` bool | `patch_model` | SAFE | O |
| Effetti touch | `tema.effetti_touch` | `fields.tema.effetti_touch` bool | `patch_model` | SAFE | O |
| (stile sfondo, non in form) | `tema.sfondo_stile` | `fields.tema.sfondo_stile` | `patch_model` | SAFE | O |
| **Regista del Lato Segreto** | | | | | |
| Preset DELICATO/SENSUALE/INTENSO | `regia.preset` | `fields.regia.preset` | `patch_model` | SAFE | O |
| Intensità fumo / luci / glow / movimento | `regia.fumo`, `regia.luci`, `regia.glow`, `regia.movimento` | `fields.regia.{fumo,luci,glow,movimento}` int 0..100 | `patch_model` | SAFE | O |
| Ambiente sonoro attivo | `regia.audio.ambiente` | `fields.regia.audio.ambiente` bool | `patch_model` | SAFE | O |
| Traccia | `regia.audio.traccia` | `fields.regia.audio.traccia` (velluto-nero/sensuale/notturno/lusso/intimo/intenso) | `patch_model` | SAFE | O |
| Volume ambiente / click | `regia.audio.volume_ambiente`, `regia.audio.volume_effetto` | `fields.regia.audio.{volume_ambiente,volume_effetto}` 0..100 | `patch_model` | SAFE | O |
| Melodia personalizzata (upload) | `regia.audio.custom_url` | — | — | MEDIA | O |
| **CTA temporizzata** | | | | | |
| Attiva | `cta_temporizzata.attivo` | `fields.cta_temporizzata.attivo` bool | `patch_model` | SAFE | O |
| Ritardo (s) | `cta_temporizzata.ritardo` | `fields.cta_temporizzata.ritardo` int 3..120 | `patch_model` | SAFE | O |
| Testo introduttivo | `cta_temporizzata.testo_intro` | `fields.cta_temporizzata.testo_intro` | `patch_model` | SAFE | O |
| Testo pulsante | `cta_temporizzata.testo_pulsante` | `fields.cta_temporizzata.testo_pulsante` | `patch_model` | SAFE | O |
| **Social e link** | | | | | |
| Instagram, TikTok, X, Telegram, YouTube, Facebook, Threads, Snapchat, Sito | `social.{instagram,tiktok,x,telegram,youtube,facebook,threads,snapchat,sito}` | `fields.social.*` (URL https) | `patch_model` | SAFE tecnicamente, **REAL_DATA** (mai inventare) | O |
| **Pellicola Home** | | | | | |
| Mostra nella pellicola | `pellicola_home.attiva` | `fields.pellicola_home.attiva` bool | `patch_model` | SAFE | O |
| Priorità (1-10) | `pellicola_home.priorita` | `fields.pellicola_home.priorita` int 1..10 | `patch_model` | SAFE | O |
| Ordine manuale | `pellicola_home.ordine` | `fields.pellicola_home.ordine` int/null | `patch_model` | SAFE | O |
| Video/poster pubblico e segreto | `pellicola_home.{pubblico,segreto}.{video_url,poster_url}` | `parameters.media[] {slot pellicola_*}` | `apply_media_to_slot` | MEDIA | R se attiva |
| **Messaggio dopo 35 secondi** | | | | | |
| Attivo | `messaggio_35s.attivo` | `fields.messaggio_35s.attivo` bool | `patch_model` | SAFE | O |
| Timer (s) | `messaggio_35s.timer` | `fields.messaggio_35s.timer` int 10..300 | `patch_model` | SAFE | O |
| Testo del messaggio | `messaggio_35s.testo` | `fields.messaggio_35s.testo` | `patch_model` | SAFE | O |
| Testo CTA | `messaggio_35s.cta_testo` | `fields.messaggio_35s.cta_testo` | `patch_model` | SAFE | O |
| Foto / video (upload) | `messaggio_35s.foto`, `messaggio_35s.video` | — | — | MEDIA | O |
| **SEO** | | | | | |
| SEO Title | `seo.title` | `fields.seo.title` (≤65) | approval `models.update`; se assente → auto `"{nome} | LATO SEGRETO"` (create) | REVIEW / SEO_AUTO | O |
| Meta description | `seo.meta_description` | `fields.seo.meta_description` (60..160) | approval; se assente → derivata da bio (nella stessa approval se bio è REVIEW, altrimenti SEO fix `MISSING_META_DESCRIPTION`) | REVIEW / SEO_AUTO | O |
| Alt text predefinito | `seo.alt_default` | `fields.seo.alt_default` | `patch_model`; se assente → SEO fix `MISSING_ALT_DEFAULT` | SAFE / SEO_AUTO | O |
| Immagine OG (upload) | `seo.og_image` | — (SEO fix `MISSING_OG_IMAGE` solo quando esiste `foto_card`) | `apply_issue_fix` | MEDIA | O |
| (non in form) Canonical | `seo.canonical` | `fields.seo.canonical` | approval; se assente → SEO fix `MISSING_CANONICAL` (richiede `site.base_url`) | REVIEW / SEO_AUTO | O |
| (non in form) Robots | `seo.robots` | `fields.seo.robots` (index,follow / noindex,follow / …) | approval; default schema `index,follow` | REVIEW / SEO_AUTO | O |
| (non in form) Indexable | `seo.indexable` | `fields.seo.indexable` bool | approval; default `true` | REVIEW | O |
| (non in form) Keywords | `seo.keywords[]` | `fields.seo.keywords` ≤ 8 | `patch_model`; se assente → SEO fix `MISSING_KEYWORDS` (tag+categorie+nome) | SAFE / SEO_AUTO | O |
| (non in form) Topics | `seo.topics[]` | `fields.seo.topics` | `patch_model`; se assente → SEO fix `MISSING_KEYWORDS` (= categorie) | SAFE / SEO_AUTO | O |
| (non in form) OG title / OG description | `seo.og_title`, `seo.og_description` | `fields.seo.og_title`, `fields.seo.og_description` | `patch_model`; se assenti → SEO fix `MISSING_OG_TITLE` / `MISSING_OG_DESCRIPTION` | SAFE / SEO_AUTO | O |
| (non in form) Structured data | `seo.structured_data_type` | `fields.seo.structured_data_type` (ProfilePage) | `patch_model`; default schema | SAFE | O |
| **Pubblicazione** | | | | | |
| Stato | `stato` | — (rimosso: il workflow non pubblica mai) | `models.publish` separato | BLOCKED | — |
| Ordine | `ordine` | `fields.ordine` int | `patch_model` | SAFE | O |
| Conferma creator maggiorenne | `conferma_maggiorenne` | — (rimosso: dato reale, mai automatico) | `models.update` dopo conferma esplicita dell'utente | BLOCKED + REAL_DATA | R |
| **Non nel form / interni** | `analytics`, `content_overrides`, `data_pubblicazione`, `is_deleted`, `galleria_*`, `seo.internal_links` | — | — | BLOCKED | — |

## Readiness veritiera (`data.readiness_breakdown`)
- `missing_media`: Foto card Home, 3 foto Lato Pubblico, 3 foto Lato Segreto, Video pubblico 1, Video segreto 1, Video Pellicola pubblico/segreto, `seo.og_image`
- `missing_real_data`: Link OnlyFans, Creator maggiorenne confermata (+ social non forniti: solo warning opzionale)
- `pending_review`: campi REVIEW già preparati nella approval (frase, bio, bio_segreta, slug, nome_artistico, seo.title, seo.meta_description, seo.canonical, seo.robots, seo.indexable, onlyfans_url)
- `missing_text_not_provided`: campi testuali obbligatori che GPT NON ha passato in `fields` (il workflow li avrebbe compilati) → hint esplicito

## Invarianti
- Una sola chiamata → una sola `session_id`; ogni scrittura (create, SAFE update, media, SEO fix) è versionata e annullabile con `rollback.session`.
- Split SAFE/REVIEW a livello di **path** (es. `seo.keywords` SAFE applicato subito; `seo.title` REVIEW nella approval): i campi SAFE non vengono mai persi né sovrascritti dall'approvazione (deep-merge).
- `stato` e `conferma_maggiorenne` non sono mai toccati. Nessuna pubblicazione automatica.
