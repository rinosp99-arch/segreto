"""Italian OnlyFans captions for the latosegreto account — brand format LATO SEGRETO (recognisable every time):

    NOME MODELLA
    ✨ LATO PUBBLICO
    <1 short teaser about what everyone sees + her real style>
    🔥 LATO SEGRETO
    <1 short, more intriguing sentence>  <emoji>
    <1 engaging hook / question>
    💋 Scoprila su OnlyFans:
    <REAL OF link of the model from the DB>

Copy = LLM (existing Emergent key, JSON with public/secret/hook) validated hard, else deterministic combinable templates (12+ per part).
Only real model data (name, frase, bio, categorie, tag, tema.preset) - never invented details. Link added deterministically, outside the creative part.
Caption style only: queue/media/link/scheduler/provider are untouched."""
import asyncio
import hashlib
import json
import os
import re
from typing import Dict, List, Optional

MODEL = ("openai", os.environ.get("OF_LLM_MODEL", os.environ.get("TELEGRAM_LLM_MODEL", "gpt-5.4-mini")))
TIMEOUT_S = 25
CAPTION_LIMIT = 900
SENTENCE_LIMIT = 120
CTA = "💋 Scoprila su OnlyFans:"
DM_CTA = "❤️‍🔥 Scoprila qui:"
DM_OPENER = "👀 Hai già scoperto {NAME}?"
H_PUBLIC = "✨ LATO PUBBLICO"
H_SECRET = "🔥 LATO SEGRETO"
EMOJI_POOL = ["👀", "🖤", "❤️‍🔥", "🌙", "🔐", "🥀", "🔥", "✨"]
MAX_EMOJI = 8                                   # whole caption, headers + CTA included (moderation guard, checked in tests)
FORBIDDEN = re.compile(r"\b(\d{2}\s*anni|anni\b|città|vive a|abita a|di professione|lavora come|studentessa|infermiera|insegnante|cm\b|kg\b|taglia|seno|culo|sesso|scopa|porno|xxx|nud[aoie]|nude|onlyfans|instagram|telegram|twitter|video|foto\b)\b", re.I)
ENGLISH_HINT = re.compile(r"\b(the|and|with|her|discover|you|now|this|what|side|secret|public)\b", re.I)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\uFE0F\u200D]+")

SYSTEM = ("Sei il copywriter OnlyFans di LATO SEGRETO, brand italiano elegante che presenta creator con il format 'Lato Pubblico / Lato Segreto'. "
          "Scrivi in ITALIANO, tono seducente, coinvolgente, elegante, naturale, leggermente provocante, MAI volgare. Stile teaser/provocazione, NON scheda descrittiva: "
          "niente elenchi di dettagli o aggettivi in fila. Usa SOLO i dati forniti (nome, frase, bio, categorie, tag, stile) e NON inventare età, città, professione, "
          "caratteristiche fisiche, attività o contenuti. Niente URL, hashtag, @menzioni, nomi di piattaforme. "
          "Il nome della creator è già nell'intestazione: nelle frasi usa al massimo il solo nome proprio, una volta. Le etichette 'lato pubblico'/'lato segreto' sono già nelle intestazioni: "
          "NON ripeterle nelle frasi (niente 'nel suo lato pubblico…'). 'Stile' è solo un'atmosfera, non un oggetto da citare. "
          "Rispondi SOLO con JSON: {\"public\": \"1 frase (max 110 caratteri) su quello che tutti vedono + la sua personalità reale\", "
          "\"secret\": \"1 frase (max 110 caratteri) più intrigante che aumenta la curiosità, chiusa con l'emoji suggerita\", "
          "\"hook\": \"1 breve domanda/frase finale che invita a scegliere o cliccare, max 80 caratteri, nello stile suggerito, con al massimo 1 emoji\"}. "
          "Le tre frasi devono essere diverse tra loro e diverse da ciclo a ciclo.")
HOOK_STYLES = ["domanda diretta 'quale lato scegli?'", "scelta Pubblico o Segreto", "provocazione 'pensavi fosse tutto qui?'", "tease sul lato che non ha ancora visto",
               "invito a schierarsi 'da che parte stai?'", "affermazione breve e magnetica, senza domanda"]

# ------------------------------------------------------------------------------------------------ deterministic fallback (combinable)
PUBLIC_TEMPLATES = [
    "{Adj}, sicura di sé e impossibile da ignorare.",
    "Uno sguardo basta per capire che non passa inosservata.",
    "Dolce all'apparenza, ma con qualcosa che ti fa fermare a guardare.",
    "{Adj} alla luce del giorno, e lo sa benissimo.",
    "Quella che tutti vedono: {adj}, magnetica, sempre un passo avanti.",
    "«{frase}» Il suo lato che conoscono tutti parte da qui.",
    "Stile {adj}, sguardo diretto: la {Name} che vedi ovunque.",
    "Alla luce è {adj}. Ed è solo l'inizio.",
    "La versione che mostra a tutti è già difficile da dimenticare.",
    "{Adj} senza sforzo, come se fosse la cosa più naturale del mondo.",
    "Un'eleganza {adj} che non ha bisogno di alzare la voce.",
    "Il suo lato pubblico è {adj}: quello che vedi è vero, ma non è tutto.",
    "Curata, {adj}, sempre al centro della scena senza cercarla.",
]
SECRET_TEMPLATES = [
    "Ma quello che mostra quando smette di trattenersi è tutta un'altra storia.",
    "Dietro quel sorriso c'è un lato che non mostra proprio a tutti.",
    "Se pensavi di aver già visto tutto, probabilmente hai guardato solo il lato sbagliato.",
    "Il lato che pochi conoscono è proprio quello che lascia il segno.",
    "Quando cala la luce, la {Name} che conosci cambia completamente registro.",
    "C'è una versione di lei che non finisce nei posti dove la vedi di solito.",
    "Quello che tiene per pochi non ha niente di prevedibile.",
    "Il suo lato più audace non lo trovi dove guardano tutti.",
    "Ogni cosa che non dice alla luce del giorno la racconta altrove.",
    "Sotto quella calma c'è qualcosa che non lascia indifferenti.",
    "La {Name} che pochi vedono è molto meno tranquilla di quanto sembri.",
    "Dietro la superficie {adj2} c'è un lato che ti fa cambiare idea su tutto.",
    "Chi l'ha scoperta dice sempre la stessa cosa: non se l'aspettava.",
]
HOOK_TEMPLATES = [
    "Quale lato scegli? 👀",
    "Tu da che parte stai? 🖤",
    "Pensavi davvero che fosse tutto qui? 🔥",
    "Il suo preferito? Forse quello che ancora non hai visto.",
    "Pubblico o Segreto? La scelta è tua. 👀",
    "Pubblico o Segreto… quale {Name} sceglieresti? 🔥",
    "Il lato pubblico lo conosci. L'altro ti aspetta. 🖤",
    "Basta un clic per scoprire quale {Name} è quella vera. 👀",
    "Due lati, una sola {Name}. Tu quale vuoi vedere prima? 🌙",
    "Fermarsi al primo lato sarebbe un peccato. ❤️‍🔥",
    "Il resto lo scopri solo dall'altra parte. 🔐",
    "Curioso di vedere cosa succede quando smette di trattenersi? 👀",
]
_DESCR = {"eleganti": ("elegante", "raffinata"), "more": ("intensa", "magnetica"), "bionde": ("luminosa", "solare"), "tatuate": ("decisa", "dark"), "sportive": ("energica", "dinamica"),
          "cosplay": ("giocosa", "creativa"), "latine": ("solare", "calda"), "rosse": ("magnetica", "ribelle"), "curvy": ("sensuale", "morbida"),
          "tattoo": ("dark", "decisa"), "sportiva": ("sportiva", "energica"), "dolce": ("dolce", "delicata"), "bordeaux": ("elegante", "intensa"), "boudoir": ("raffinata", "sensuale")}
_SAFE_TAGS = {"elegante", "raffinata", "alternativa", "dark", "dinamica", "dolce", "soft", "angelica", "chic", "creativa", "sensuale", "misteriosa", "ribelle", "magnetica", "solare", "intensa", "decisa", "luminosa", "energica", "giocosa"}


def _facts(m: dict) -> dict:
    tema = m.get("tema")
    style = (tema.get("preset") if isinstance(tema, dict) else tema) or ""
    return {"nome": (m.get("nome_artistico") or m.get("nome") or "").strip(), "frase": (m.get("frase") or "").strip(), "bio": (m.get("bio") or "").strip()[:400],
            "categorie": [c for c in (m.get("categorie") or []) if isinstance(c, str)], "tag": [t for t in (m.get("tag") or []) if isinstance(t, str)][:8], "stile": str(style)}


def _adjectives(f: dict) -> List[str]:
    """Only adjectives derived from the model's real categories/tags/style (never invented facts)."""
    out: List[str] = []
    for key in [*f["categorie"], f["stile"], *f["tag"]]:
        k = (key or "").lower()
        for a in _DESCR.get(k, ()) + ((k,) if k in _SAFE_TAGS else ()):
            if a and a not in out:
                out.append(a)
    return out or ["elegante", "intensa"]


def _pick(pool: List[str], slug: str, cycle: int, part: str) -> str:
    """Deterministic, different per model and per cycle: offset by cycle so consecutive cycles never repeat the same part."""
    h = int(hashlib.sha256(f"{slug}:{part}".encode()).hexdigest(), 16)
    return pool[(h + (cycle - 1) * (1 + h % 3)) % len(pool)]


def template_parts(m: dict, cycle: int) -> Dict[str, str]:
    f = _facts(m)
    name = f["nome"] or "Lei"
    first = name.split(" ")[0].capitalize()
    adjs = _adjectives(f)
    adj, adj2 = adjs[0], (adjs[1] if len(adjs) > 1 else "diversa")
    slug = m.get("slug") or name.lower()
    pub_pool = PUBLIC_TEMPLATES if (f["frase"] and len(f["frase"]) <= 70) else [t for t in PUBLIC_TEMPLATES if "{frase}" not in t]
    fmt = dict(Name=first, adj=adj, Adj=adj.capitalize(), adj2=adj2, frase=f["frase"].rstrip("."))
    return {"public": _pick(pub_pool, slug, cycle, "public").format(**fmt), "secret": _pick(SECRET_TEMPLATES, slug, cycle, "secret").format(**fmt) + " " + _pick(EMOJI_POOL[:5], slug, cycle, "emoji"),
            "hook": _pick(HOOK_TEMPLATES, slug, cycle, "hook").format(**fmt)}


def template_text(m: dict, cycle: int) -> str:
    return compose(_facts(m)["nome"] or "Lei", template_parts(m, cycle))


# ------------------------------------------------------------------------------------------------ composition (shared by LLM and fallback)
def compose(name: str, parts: Dict[str, str]) -> str:
    return f"{name.upper()}\n\n{H_PUBLIC}\n{parts['public'].strip()}\n\n{H_SECRET}\n{parts['secret'].strip()}\n\n{parts['hook'].strip()}"


def count_emoji(text: str) -> int:
    return len([c for c in text if ord(c) >= 0x2600 and c not in ("\ufe0f", "\u200d")])


def _clean_sentence(s: str, limit: int = SENTENCE_LIMIT) -> str:
    """Whole sentence rejected (empty) when it carries a URL / hashtag / @mention, is too short or too long."""
    s = re.sub(r"\s+", " ", str(s or "")).strip().strip('"').strip()
    if re.search(r"https?://|www\.|#\S+|@\S+", s) or len(s) < 12 or len(s) > limit:
        return ""
    return s


def _valid_parts(parts: Dict[str, str]) -> bool:
    blob = " ".join(parts.get(k, "") for k in ("public", "secret", "hook"))
    if not all(parts.get(k) for k in ("public", "secret", "hook")):
        return False
    if FORBIDDEN.search(blob) or len(ENGLISH_HINT.findall(blob)) >= 2 or "http" in blob or "@" in blob:
        return False
    if len({parts["public"], parts["secret"], parts["hook"]}) < 3 or count_emoji(blob) > 4:
        return False
    return True


# ------------------------------------------------------------------------------------------------ LLM
def _llm_available() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY")) and os.environ.get("OF_LLM_ENABLED", "true").lower() in ("1", "true", "yes")


async def llm_parts(m: dict, cycle: int) -> Optional[Dict[str, str]]:
    if not _llm_available():
        return None
    f = _facts(m)
    slug = m.get("slug") or f["nome"]
    emoji, hook_style = _pick(EMOJI_POOL[:5], slug, cycle, "emoji"), _pick(HOOK_STYLES, slug, cycle, "hookstyle")
    prompt = (f"Creator: {f['nome']}\nFrase breve: {f['frase'] or '-'}\nBio: {f['bio'] or '-'}\nCategorie: {', '.join(f['categorie']) or '-'}\nTag: {', '.join(f['tag']) or '-'}\n"
              f"Stile/atmosfera: {', '.join(_adjectives(f)[:3])}\nEmoji suggerita per chiudere il Lato Segreto: {emoji}\nStile della frase finale: {hook_style}\n"
              f"Ciclo n. {cycle}: frasi DIVERSE dai cicli precedenti (variante {cycle % 7 + 1}). Il post mostra due media: il primo del Lato Pubblico, il secondo del Lato Segreto. Rispondi solo con il JSON.")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"of-copy-v2-{m.get('slug')}-{cycle}", system_message=SYSTEM).with_model(*MODEL)
        raw = str(await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=TIMEOUT_S)).strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
    except Exception:                                   # noqa: BLE001 — any LLM/parse failure -> deterministic fallback
        return None
    parts = {k: _clean_sentence(data.get(k), SENTENCE_LIMIT if k != "hook" else 90) for k in ("public", "secret", "hook")}
    full, first = f["nome"], (f["nome"].split(" ")[0] if f["nome"] else "")
    if full and first and " " in full:                                                   # full name only in the header: sentences keep the first name
        parts = {k: re.sub(re.escape(full), first, v, flags=re.I) for k, v in parts.items()}
    if not _valid_parts(parts):
        return None
    if count_emoji(parts["secret"]) == 0:
        parts["secret"] += " " + _pick(EMOJI_POOL[:5], m.get("slug") or f["nome"], cycle, "emoji")
    return parts


async def llm_text(m: dict, cycle: int) -> Optional[str]:
    parts = await llm_parts(m, cycle)
    return compose(_facts(m)["nome"] or "Lei", parts) if parts else None


# ------------------------------------------------------------------------------------------------ public API (unchanged signature)
async def build_caption(m: dict, of_url: str, cycle: int, use_ai: bool = True) -> Dict[str, object]:
    """of_url MUST be the model's own validated onlyfans.com link (caller guarantees it). Link appended deterministically, never generated."""
    assert of_url and "onlyfans.com" in of_url
    body, source = None, "TEMPLATE"
    if use_ai:
        body = await llm_text(m, cycle)
        if body:
            source = "LLM"
    if not body:
        body = template_text(m, cycle)
    text = f"{body}\n\n{CTA}\n{of_url}"
    if len(text) > CAPTION_LIMIT:
        body = body[: CAPTION_LIMIT - len(CTA) - len(of_url) - 8].rstrip() + "…"
        text = f"{body}\n\n{CTA}\n{of_url}"
    assert text.count("http") == 1 and of_url in text and "@" not in body and H_PUBLIC in body and H_SECRET in body
    return {"text": text, "body": body, "cta": CTA, "of_url": of_url, "source": source, "language": "it"}


# ------------------------------------------------------------------------------------------------ MASS MESSAGE copy (more direct, ALWAYS different from the feed)
DM_SYSTEM_EXTRA = (" Questo testo è un MESSAGGIO DIRETTO ai fan (non un post): più diretto e confidenziale, come se parlassi a una persona sola, sempre elegante. "
                   "Le frasi devono essere DIVERSE da quelle del post feed che ti passo: non riusarle né parafrasarle da vicino.")


def compose_dm(name: str, parts: Dict[str, str]) -> str:
    """👀 Hai già scoperto NOME? / ✨ LATO PUBBLICO / 🔥 LATO SEGRETO  (no hook: the ❤️‍🔥 CTA closes the message)."""
    return f"{DM_OPENER.format(NAME=name.upper())}\n\n{H_PUBLIC}\n{parts['public'].strip()}\n\n{H_SECRET}\n{parts['secret'].strip()}"


def dm_template_parts(m: dict, cycle: int) -> Dict[str, str]:
    """Deterministic fallback for the DM: different pools offsets than the feed (part names differ -> different hashes)."""
    f = _facts(m)
    name = f["nome"] or "Lei"
    first = name.split(" ")[0].capitalize()
    adjs = _adjectives(f)
    adj, adj2 = adjs[0], (adjs[1] if len(adjs) > 1 else "diversa")
    slug = m.get("slug") or name.lower()
    pub_pool = PUBLIC_TEMPLATES if (f["frase"] and len(f["frase"]) <= 70) else [t for t in PUBLIC_TEMPLATES if "{frase}" not in t]
    fmt = dict(Name=first, adj=adj, Adj=adj.capitalize(), adj2=adj2, frase=f["frase"].rstrip("."))
    return {"public": _pick(pub_pool, slug, cycle, "dm_public").format(**fmt),
            "secret": _pick(SECRET_TEMPLATES, slug, cycle, "dm_secret").format(**fmt) + " " + _pick(EMOJI_POOL[:5], slug, cycle, "dm_emoji")}


async def llm_dm_parts(m: dict, cycle: int, feed_text: str) -> Optional[Dict[str, str]]:
    if not _llm_available():
        return None
    f = _facts(m)
    slug = m.get("slug") or f["nome"]
    emoji = _pick(EMOJI_POOL[:5], slug, cycle, "dm_emoji")
    prompt = (f"Creator: {f['nome']}\nFrase breve: {f['frase'] or '-'}\nBio: {f['bio'] or '-'}\nCategorie: {', '.join(f['categorie']) or '-'}\nTag: {', '.join(f['tag']) or '-'}\n"
              f"Stile/atmosfera: {', '.join(_adjectives(f)[:3])}\nEmoji suggerita per chiudere il Lato Segreto: {emoji}\n"
              f"Testo del post feed già pubblicato (NON riusare queste frasi):\n{feed_text}\n\nCiclo n. {cycle}. Rispondi solo con il JSON (hook può essere una stringa vuota).")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"of-dm-{slug}-{cycle}", system_message=SYSTEM + DM_SYSTEM_EXTRA).with_model(*MODEL)
        raw = str(await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=TIMEOUT_S)).strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
    except Exception:                                   # noqa: BLE001
        return None
    parts = {k: _clean_sentence(data.get(k)) for k in ("public", "secret")}
    parts["hook"] = "-"                                  # not used in the DM; keeps the shared validator happy
    full, first = f["nome"], (f["nome"].split(" ")[0] if f["nome"] else "")
    if full and first and " " in full:
        parts = {k: re.sub(re.escape(full), first, v, flags=re.I) for k, v in parts.items()}
    if not _valid_parts(parts):
        return None
    if count_emoji(parts["secret"]) == 0:
        parts["secret"] += " " + emoji
    return {"public": parts["public"], "secret": parts["secret"]}


def _sentences(text: str) -> set:
    return {l.strip().lower() for l in text.split("\n") if l.strip() and not l.startswith(("✨", "🔥", "💋", "❤️‍🔥", "👀", "http"))}


async def build_dm_caption(m: dict, of_url: str, cycle: int, feed_text: str = "", use_ai: bool = True) -> Dict[str, object]:
    """Mass message copy: opener + PUBLIC/SECRET sentences + ❤️‍🔥 CTA + the model's real OF link (from the DB, appended deterministically).
    Guarantees: text != feed text and no sentence shared with the feed (falls back to alternate template picks when needed)."""
    assert of_url and "onlyfans.com" in of_url
    name = _facts(m)["nome"] or "Lei"
    parts, source = (await llm_dm_parts(m, cycle, feed_text)) if use_ai else None, "LLM"
    feed_sent = _sentences(feed_text or "")
    if not parts or (_sentences(compose_dm(name, parts)) & feed_sent):
        source = "TEMPLATE"
        for bump in range(0, 6):                                                    # alternate deterministic picks until no sentence overlaps the feed
            parts = dm_template_parts(m, cycle + bump * 7)
            if not (_sentences(compose_dm(name, parts)) & feed_sent):
                break
    body = compose_dm(name, parts)
    text = f"{body}\n\n{DM_CTA}\n{of_url}"
    if len(text) > CAPTION_LIMIT:
        body = body[: CAPTION_LIMIT - len(DM_CTA) - len(of_url) - 8].rstrip() + "…"
        text = f"{body}\n\n{DM_CTA}\n{of_url}"
    assert text.count("http") == 1 and of_url in text and "@" not in body and H_PUBLIC in body and H_SECRET in body and text != (feed_text or "")
    return {"text": text, "body": body, "cta": DM_CTA, "of_url": of_url, "source": source, "language": "it", "different_from_feed": text != feed_text and not (_sentences(body) & feed_sent)}
