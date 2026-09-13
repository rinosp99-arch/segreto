"""models.prepare_complete — explicit field contract (FORM -> DB -> API), deterministic filtering, path-level SAFE/REVIEW split,
truthful readiness breakdown. No LLM, no invention: media, real links and the adult confirmation are NEVER produced here.
Reference matrix: /app/PREPARE_COMPLETE_MATRIX.md"""
from typing import Any, Dict, List, Tuple

BADGES = ["NUOVA", "IN TENDENZA", "PIÙ VISTA", "SCELTA DEL GIORNO"]
TEMA_PRESETS = ["bordeaux", "tattoo", "dolce", "sportiva", "cosplay"]
REGIA_PRESETS = ["DELICATO", "SENSUALE", "INTENSO"]
AUDIO_TRACKS = ["velluto-nero", "sensuale", "notturno", "lusso", "intimo", "intenso"]
ROBOTS = ["index,follow", "noindex,follow", "index,nofollow", "noindex,nofollow"]
SOCIAL_KEYS = ["instagram", "tiktok", "x", "telegram", "youtube", "facebook", "threads", "snapchat", "sito"]

_R = " [REVIEW_REQUIRED: preparato in anteprima, applicato dopo approveApproval]"
_S = " [SAFE: applicato subito]"
_REAL = " [DATO REALE: solo se fornito dall'utente, MAI inventare]"


def _s(desc: str, **kw) -> dict:
    return {"type": "string", "description": desc, **kw}


def _b(desc: str, **kw) -> dict:
    return {"type": "boolean", "description": desc, **kw}


def _i(desc: str, lo: int, hi: int, **kw) -> dict:
    return {"type": "integer", "minimum": lo, "maximum": hi, "description": desc, **kw}


# FORM FIELD -> stored field. Keys = exactly the stored (DB) names: `fields` is deep-merged onto the model document.
PREPARE_FIELDS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "Tutti i campi NON-media del formulario modella (nomi = campi salvati nel DB, deep-merge). Compila TUTTO ciò che puoi generare in sicurezza. "
                   "Esclusi (rimossi con warning): foto/video/media (usa `media[]`), stato, conferma_maggiorenne, analytics. Link reali (onlyfans_url, social.*) SOLO se forniti dall'utente.",
    "properties": {
        "nome_artistico": _s("Form 'Nome artistico' -> nome_artistico. Default = nome." + _R, example="Giulia"),
        "slug": _s("Form 'Slug (URL)' -> slug (minuscole-trattini; reso unico automaticamente). Default generato dal nome." + _R, pattern="^[a-z0-9-]+$", example="giulia-rossi"),
        "frase": _s("Form 'Frase breve' (claim) -> frase. Obbligatorio per pubblicare." + _R, maxLength=120, example="Dolce finché non premi."),
        "cta_testo": _s("Form 'Testo CTA principale' -> cta_testo." + _S, maxLength=40, example="CONTINUA CON ME"),
        "bio": _s("Form 'Bio pubblica' -> bio (>=120 caratteri consigliati). Obbligatorio per pubblicare." + _R, minLength=1, example="Giulia è ..."),
        "bio_segreta": _s("Form 'Bio segreta' -> bio_segreta (testo del Lato Segreto). Obbligatorio per pubblicare." + _R, example="Qui Giulia ..."),
        "teaser_copy": _s("Form 'Testo teaser (limite)' -> teaser_copy." + _S, maxLength=160, example="Qui posso mostrarti solo fino a questo punto."),
        "categorie": {"type": "array", "items": {"type": "string"}, "description": "Form 'Categorie' -> categorie[] (slug di categorie esistenti: categories.list)." + _S, "example": ["more"]},
        "tag": {"type": "array", "items": {"type": "string"}, "maxItems": 20, "description": "Form 'Tag' -> tag[]." + _S, "example": ["eleganza", "notte"]},
        "badge": {"type": ["string", "null"], "enum": [None, *BADGES], "description": "Form 'Badge' -> badge (null = nessuno)." + _S, "example": "NUOVA"},
        "badge_tipo": {"type": "string", "enum": ["editoriale", "dati"], "description": "badge_tipo (editoriale = scelto a mano, dati = calcolato)." + _S, "example": "editoriale"},
        "onlyfans_url": _s("Form 'Link OnlyFans' -> onlyfans_url (https://onlyfans.com/<username>)." + _R + _REAL, pattern="^https://onlyfans\\.com/[A-Za-z0-9._-]+/?$", example="https://onlyfans.com/username"),
        "social": {"type": "object", "description": "Form 'Social e link' -> social.*" + _REAL, "additionalProperties": False,
                   "properties": {k: _s(f"URL https {k}", format="uri") for k in SOCIAL_KEYS}},
        "tema": {"type": "object", "description": "Form 'Personalizzazione Lato Segreto (tema)' -> tema.*" + _S, "additionalProperties": False, "properties": {
            "preset": {"type": "string", "enum": TEMA_PRESETS, "description": "Preset tema", "example": "bordeaux"},
            "colore_primario": _s("Colore primario HSL 'H S% L%'", pattern="^\\d{1,3} \\d{1,3}% \\d{1,3}%$", example="40 55% 60%"),
            "colore_secondario": _s("Colore secondario HSL 'H S% L%'", pattern="^\\d{1,3} \\d{1,3}% \\d{1,3}%$", example="350 45% 28%"),
            "grain": {"type": "number", "minimum": 0, "maximum": 1, "description": "Grana 0-1", "example": 0.08},
            "glow": _b("Glow attivo", example=True),
            "sfondo_stile": _s("Stile sfondo (vignetta)", example="vignetta"),
            "frase_attivazione": _s("Frase di attivazione (sul pulsante del Lato Segreto)", maxLength=60, example="NON DOVRESTI PREMERLO"),
            "testo_dopo_click": _s("Testo dopo il click", maxLength=80, example="Te l'avevamo detto."),
            "effetti_touch": _b("Effetti touch attivi", example=True)}},
        "regia": {"type": "object", "description": "Form 'Regista del Lato Segreto' -> regia.* (atmosfera: fumo/luci/glow/movimento + audio)" + _S, "additionalProperties": False, "properties": {
            "preset": {"type": "string", "enum": REGIA_PRESETS, "description": "Preset regia (DELICATO 20/60/30/15, SENSUALE 35/55/40/25, INTENSO 60/50/65/45)", "example": "SENSUALE"},
            "fumo": _i("Intensità fumo 0-100", 0, 100, example=35), "luci": _i("Intensità luci 0-100", 0, 100, example=55),
            "glow": _i("Intensità glow 0-100", 0, 100, example=40), "movimento": _i("Intensità movimento 0-100", 0, 100, example=25),
            "audio": {"type": "object", "additionalProperties": False, "description": "Audio ambiente del Lato Segreto", "properties": {
                "ambiente": _b("Ambiente sonoro attivo", example=True),
                "traccia": {"type": "string", "enum": AUDIO_TRACKS, "description": "Traccia atmosfera", "example": "velluto-nero"},
                "volume_ambiente": _i("Volume ambiente %", 0, 100, example=20), "volume_effetto": _i("Volume click attivazione %", 0, 100, example=60)}}}},
        "cta_temporizzata": {"type": "object", "description": "Form 'CTA temporizzata' -> cta_temporizzata.*" + _S, "additionalProperties": False, "properties": {
            "attivo": _b("CTA temporizzata attiva", example=True), "ritardo": _i("Ritardo in secondi", 3, 120, example=10),
            "testo_intro": _s("Testo introduttivo", maxLength=120, example="Vuoi vedere dove continua?"),
            "testo_pulsante": _s("Testo pulsante", maxLength=40, example="CONTINUA CON ME")}},
        "messaggio_35s": {"type": "object", "description": "Form 'Messaggio dopo 35 secondi' -> messaggio_35s.* (foto/video esclusi: media)" + _S, "additionalProperties": False, "properties": {
            "attivo": _b("Messaggio attivo", example=True), "timer": _i("Timer secondi", 10, 300, example=35),
            "testo": _s("Testo del messaggio", maxLength=240, example="Se sei ancora qui, forse dovresti venire a vedere il resto…"),
            "cta_testo": _s("Testo CTA del messaggio", maxLength=40, example="CONTINUA CON ME")}},
        "pellicola_home": {"type": "object", "description": "Form 'Pellicola Home' -> pellicola_home.* (solo configurazione; i video sono media)" + _S, "additionalProperties": False, "properties": {
            "attiva": _b("Mostra nella pellicola Home (richiede video pellicola per pubblicare)", example=True),
            "priorita": _i("Priorità 1-10", 1, 10, example=5), "ordine": {"type": ["integer", "null"], "description": "Ordine manuale (null = usa priorità)", "example": None}}},
        "seo": {"type": "object", "description": "Form 'SEO' + metadati -> seo.* (og_image escluso: media). Con seo_safe_fix=true i campi assenti vengono derivati automaticamente.", "additionalProperties": False, "properties": {
            "title": _s("SEO Title (<=65)" + _R, maxLength=65, example="Giulia Rossi | LATO SEGRETO"),
            "meta_description": _s("Meta description 60-160" + _R, minLength=1, maxLength=170, example="Scopri Giulia Rossi: il lato che non mostra a tutti. Foto, video e il suo Lato Segreto su LATO SEGRETO."),
            "alt_default": _s("ALT predefinito per le immagini" + _S, maxLength=120, example="Giulia Rossi - creator LATO SEGRETO"),
            "canonical": _s("Canonical assoluto (di norma derivato: {site.base_url}/modelle/{slug})" + _R, format="uri"),
            "robots": {"type": "string", "enum": ROBOTS, "description": "Direttiva robots" + _R, "example": "index,follow"},
            "indexable": _b("Indicizzabile (in sitemap quando pubblicata)" + _R, example=True),
            "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 8, "description": "Keyword SEO (<=8)" + _S, "example": ["giulia rossi", "creator", "lato segreto"]},
            "topics": {"type": "array", "items": {"type": "string"}, "maxItems": 8, "description": "Topic/argomenti" + _S, "example": ["more"]},
            "og_title": _s("OpenGraph title (default = title)" + _S, maxLength=90),
            "og_description": _s("OpenGraph description (default = meta_description)" + _S, maxLength=200),
            "structured_data_type": {"type": "string", "enum": ["ProfilePage"], "description": "Tipo structured data" + _S, "example": "ProfilePage"}}},
        "ordine": {"type": "integer", "description": "Ordine nelle liste (form 'Ordine')." + _S, "example": 0},
    },
}

# Never accepted via `fields` (reason shown to GPT). Media -> `media[]`; real data -> explicit user action.
BLOCKED_ROOTS: Dict[str, str] = {
    "stato": "il workflow non pubblica mai (models.publish separato)",
    "conferma_maggiorenne": "dato reale: conferma esplicita dell'utente via models.update, mai automatica",
    "data_pubblicazione": "gestito dalla pubblicazione", "is_deleted": "protetto", "analytics": "configurazione tracking: models.update dedicato",
    "content_overrides": "stato DEMO/REALE dei media: non testuale", "nome": "usa parameters.nome",
    "foto_copertina": "media: usa media[] slot cover", "foto_card": "media: usa media[] slot card", "foto_card_teaser": "media: usa media[] slot teaser",
    "foto_segreta_hero": "media: usa media[] slot secret_hero", "galleria_pubblica": "media: usa media[]", "galleria_segreta": "media: usa media[]", "media_pairs": "media: usa media[]",
}
BLOCKED_PATHS: Dict[str, str] = {
    "messaggio_35s.foto": "media: usa media[] slot messaggio_foto", "messaggio_35s.video": "media: usa media[] slot messaggio_video", "regia.audio.custom_url": "media (upload audio)",
    "pellicola_home.pubblico": "media: usa media[] slot filmstrip_public", "pellicola_home.segreto": "media: usa media[] slot filmstrip_secret",
    "seo.og_image": "media: derivato da foto_card dal SEO safe fix quando esiste", "seo.internal_links": "interno",
}

MEDIA_LABELS = {"Foto card Home", "3 foto Lato Pubblico", "3 foto Lato Segreto", "Video pubblico 1", "Video segreto 1", "Video Pellicola pubblico", "Video Pellicola segreto"}
REAL_DATA_LABELS = {"Link OnlyFans": "onlyfans_url", "Creator maggiorenne confermata": "conferma_maggiorenne"}
TEXT_LABELS = {"Claim": "frase", "Descrizione pubblica": "bio", "Descrizione Lato Segreto": "bio_segreta", "Nome": "nome", "Slug (URL)": "slug"}


def flatten_paths(d: Any, prefix: str = "") -> List[str]:
    out: List[str] = []
    if isinstance(d, dict):
        for k, v in d.items():
            p = f"{prefix}.{k}" if prefix else k
            out += flatten_paths(v, p) if isinstance(v, dict) and v else [p]
    return out


def _set_path(d: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _get_path(d: dict, path: str) -> Any:
    cur: Any = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _schema_at(path: str) -> Any:
    """JSON-schema node for a dotted path in PREPARE_FIELDS_SCHEMA (None if not declared)."""
    node: Any = PREPARE_FIELDS_SCHEMA
    for p in path.split("."):
        props = (node or {}).get("properties") or {}
        if p not in props:
            return None
        node = props[p]
    return node


def _type_ok(spec: dict, v: Any) -> bool:
    t = spec.get("type")
    types = t if isinstance(t, list) else [t]
    for ty in types:
        if ty == "null" and v is None:
            return True
        if ty == "string" and isinstance(v, str):
            return True
        if ty == "boolean" and isinstance(v, bool):
            return True
        if ty == "integer" and isinstance(v, int) and not isinstance(v, bool):
            return True
        if ty == "number" and isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
        if ty == "array" and isinstance(v, list):
            return True
        if ty == "object" and isinstance(v, dict):
            return True
    return False


def filter_prepare_fields(fields: dict) -> Tuple[dict, List[dict]]:
    """Keep only declared non-media paths (typed, enum/range checked). Returns (accepted nested dict, dropped [{path, reason}])."""
    accepted: dict = {}
    dropped: List[dict] = []
    if not isinstance(fields, dict):
        return accepted, [{"path": "fields", "reason": "deve essere un oggetto"}]
    for path in flatten_paths(fields):
        root = path.split(".")[0]
        val = _get_path(fields, path)
        if root in BLOCKED_ROOTS:
            dropped.append({"path": path, "reason": BLOCKED_ROOTS[root]})
            continue
        blocked = next((r for bp, r in BLOCKED_PATHS.items() if path == bp or path.startswith(bp + ".")), None)
        if blocked:
            dropped.append({"path": path, "reason": blocked})
            continue
        spec = _schema_at(path)
        if spec is None or spec.get("type") == "object":
            dropped.append({"path": path, "reason": "campo non presente nel formulario (vedi parameters_schema.fields)"})
            continue
        if val is None and "null" not in (spec.get("type") if isinstance(spec.get("type"), list) else [spec.get("type")]):
            dropped.append({"path": path, "reason": "valore nullo"})
            continue
        if not _type_ok(spec, val):
            dropped.append({"path": path, "reason": f"tipo non valido (atteso {spec.get('type')})"})
            continue
        if isinstance(val, str) and spec.get("type") == "string" and not val.strip():
            dropped.append({"path": path, "reason": "stringa vuota"})
            continue
        if "enum" in spec and val not in spec["enum"]:
            dropped.append({"path": path, "reason": f"valore fuori enum {[e for e in spec['enum'] if e is not None]}"})
            continue
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if "minimum" in spec and val < spec["minimum"] or "maximum" in spec and val > spec["maximum"]:
                dropped.append({"path": path, "reason": f"fuori intervallo {spec.get('minimum')}..{spec.get('maximum')}"})
                continue
        if isinstance(val, list):
            if not all(isinstance(x, str) for x in val):
                dropped.append({"path": path, "reason": "lista di stringhe attesa"})
                continue
            val = [x.strip() for x in val if x and x.strip()][: spec.get("maxItems") or 50]
        if isinstance(val, str):
            val = val.strip()
        _set_path(accepted, path, val)
    return accepted, dropped


def split_by_review_paths(fields: dict, review_paths: List[str]) -> Tuple[dict, dict]:
    """Path-level split: a nested object is NOT sent whole to REVIEW because one of its keys is REVIEW
    (e.g. seo.keywords SAFE now, seo.title REVIEW -> approval)."""
    review = set(review_paths or [])
    safe: dict = {}
    rev: dict = {}
    for path in flatten_paths(fields):
        target = rev if (path in review or path.split(".")[0] in review) else safe
        _set_path(target, path, _get_path(fields, path))
    return safe, rev


def readiness_breakdown(doc: dict, validation: dict, pending_review_paths: List[str], provided_paths: List[str], dropped: List[dict]) -> dict:
    """Truthful readiness: MISSING_MEDIA vs MISSING_REAL_DATA vs PENDING_REVIEW vs text the caller did not provide."""
    pending = set(pending_review_paths or [])
    provided = set(provided_paths or [])
    missing_media, missing_real, pending_rev, not_provided = [], [], [], []
    for e in validation.get("errors") or []:
        lbl = e.get("field")
        if lbl in MEDIA_LABELS:
            missing_media.append(lbl)
        elif lbl in REAL_DATA_LABELS:
            f = REAL_DATA_LABELS[lbl]
            (pending_rev if f in pending else missing_real).append({"label": lbl, "field": f} if f in pending else lbl)
        elif lbl in TEXT_LABELS:
            f = TEXT_LABELS[lbl]
            if f in pending:
                pending_rev.append({"label": lbl, "field": f})
            elif f in provided:
                not_provided.append({"label": lbl, "field": f, "hint": "valore fornito ma scartato: vedi fields_dropped"})
            else:
                not_provided.append({"label": lbl, "field": f, "hint": f"passa fields.{f} a models.prepare_complete: il workflow lo compila"})
        elif e.get("code") == "ONLYFANS_URL_INVALID":
            missing_real.append("Link OnlyFans (formato non valido)")
        else:
            not_provided.append({"label": lbl, "field": e.get("field"), "hint": e.get("message")})
    seo = doc.get("seo") or {}
    seo_state = {
        "title": "SET" if seo.get("title") else ("PENDING_REVIEW" if "seo.title" in pending else "MISSING"),
        "meta_description": "SET" if seo.get("meta_description") else ("PENDING_REVIEW" if "seo.meta_description" in pending else "MISSING"),
        "canonical": "SET" if seo.get("canonical") else ("PENDING_REVIEW" if "seo.canonical" in pending else "MISSING_SITE_BASE_URL"),
        "robots": "SET" if seo.get("robots") else "MISSING", "indexable": "SET" if seo.get("indexable") is not None else "MISSING",
        "keywords": "SET" if seo.get("keywords") else "MISSING", "topics": "SET" if seo.get("topics") else "MISSING",
        "alt_default": "SET" if seo.get("alt_default") else "MISSING", "og_title": "SET" if seo.get("og_title") else "MISSING",
        "og_description": "SET" if seo.get("og_description") else ("PENDING_REVIEW" if "seo.og_description" in pending else "MISSING"),
        "og_image": "SET" if seo.get("og_image") else "MISSING_MEDIA",
    }
    social = doc.get("social") or {}
    return {
        "ready": bool(validation.get("ready")),
        "missing_media": missing_media,
        "missing_real_data": missing_real,
        "pending_review": pending_rev + [{"field": p} for p in sorted(pending) if p not in {x.get("field") for x in pending_rev if isinstance(x, dict)}],
        "missing_text_not_provided": not_provided,
        "seo": seo_state,
        "social_missing_optional": [k for k in SOCIAL_KEYS if not social.get(k)],
        "fields_dropped": dropped,
        "note": "MISSING_MEDIA = foto/video/FilmStrip/og_image da caricare manualmente; MISSING_REAL_DATA = OnlyFans/social/conferma maggiorenne (mai inventati); "
                "PENDING_REVIEW = valori già preparati, attendono approveApproval; missing_text_not_provided = testi che il workflow avrebbe compilato se passati in fields.",
    }


EXAMPLE_FIELDS_FULL: Dict[str, Any] = {
    "nome_artistico": "Giulia Rossi", "slug": "giulia-rossi",
    "frase": "Dolce finché non premi.", "cta_testo": "CONTINUA CON ME",
    "bio": "Giulia Rossi è una creator italiana dallo sguardo gentile e dall'eleganza naturale. Nel suo lato pubblico trovi ritratti luminosi, "
           "momenti di quotidianità e uno stile che unisce dolcezza e carattere. Ma c'è un'altra Giulia, quella che si mostra solo a chi osa premere.",
    "bio_segreta": "Qui Giulia smette di essere la ragazza della porta accanto. Luci basse, sguardi che non chiedono permesso e un ritmo più lento, "
                   "più intimo. Il suo Lato Segreto è un invito: il resto continua dove nessuno può guardare.",
    "teaser_copy": "Qui posso mostrarti solo fino a questo punto.",
    "categorie": ["more"], "tag": ["eleganza", "notte", "sguardo"], "badge": "NUOVA", "badge_tipo": "editoriale",
    "tema": {"preset": "bordeaux", "colore_primario": "40 55% 60%", "colore_secondario": "350 45% 28%", "grain": 0.08, "glow": True,
             "frase_attivazione": "NON DOVRESTI PREMERLO", "testo_dopo_click": "Te l'avevamo detto.", "effetti_touch": True},
    "regia": {"preset": "SENSUALE", "fumo": 35, "luci": 55, "glow": 40, "movimento": 25,
              "audio": {"ambiente": True, "traccia": "velluto-nero", "volume_ambiente": 20, "volume_effetto": 60}},
    "cta_temporizzata": {"attivo": True, "ritardo": 10, "testo_intro": "Vuoi vedere dove continua?", "testo_pulsante": "CONTINUA CON ME"},
    "messaggio_35s": {"attivo": True, "timer": 35, "testo": "Se sei ancora qui, forse dovresti venire a vedere il resto…", "cta_testo": "CONTINUA CON ME"},
    "pellicola_home": {"attiva": True, "priorita": 5},
    "seo": {"title": "Giulia Rossi | LATO SEGRETO", "meta_description": "Scopri Giulia Rossi: dolcezza in pubblico, un Lato Segreto che si accende solo per chi osa. Foto, video e la sua storia su LATO SEGRETO.",
            "alt_default": "Giulia Rossi - creator LATO SEGRETO", "robots": "index,follow", "indexable": True,
            "keywords": ["giulia rossi", "creator italiana", "lato segreto", "eleganza"], "topics": ["more"], "structured_data_type": "ProfilePage"},
}
