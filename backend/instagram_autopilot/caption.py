"""Italian Instagram captions (ITALY_AUDIENCE_MODE): LLM (existing Emergent key) or deterministic templates; CTA = link in bio;
3-6 pertinent hashtags; no URLs; only real card data. Publishing never fails because of the LLM."""
import asyncio
import hashlib
import os
import re
from typing import Dict, List

from .adapter import CAPTION_LIMIT

MODEL = ("openai", os.environ.get("INSTAGRAM_LLM_MODEL", os.environ.get("TELEGRAM_LLM_MODEL", "gpt-5.4-mini")))
TIMEOUT_S = 25
CTAS = ["👀 Scopri di più dal link in bio.", "Guarda il suo Lato Segreto dal link in bio. ✨", "Trovi tutto nel link in bio.", "Il resto ti aspetta nel link in bio. 🔑", "Scoprila dal link in bio. ✨"]
BASE_TAGS = ["#latosegreto", "#creatoritaliana", "#creatoritaliane", "#modelleitaliane", "#italia"]
CATEGORY_TAGS = {"eleganti": "#eleganza", "more": "#brunette", "bionde": "#bionda", "tatuate": "#tatuaggi", "sportive": "#fitnessitalia", "cosplay": "#cosplayitalia", "latine": "#latina", "rosse": "#rossa", "curvy": "#curvy"}
FORBIDDEN = re.compile(r"\b(\d{2}\s*anni|anni\b|città|vive a|abita a|di professione|lavora come|studentessa|infermiera|insegnante|cm\b|kg\b|taglia|seno|culo|sesso|scopa|porno|xxx|nud[aoie]|nude|onlyfans)\b", re.I)
ENGLISH_HINT = re.compile(r"\b(the|and|with|her|discover|link in bio\b.*\bnow|more)\b", re.I)

SYSTEM = ("Sei il copywriter Instagram di LATO SEGRETO, vetrina italiana elegante di creator. Scrivi caption brevi in ITALIANO (pubblico italiano): "
          "2-3 righe, curiose, leggermente provocanti ma SFW, eleganti, mai volgari, mai spam. Usa SOLO le informazioni fornite (nome, frase, bio, categorie, tag, tema). "
          "NON inventare età, città/località, professione, caratteristiche fisiche, attività, statistiche, disponibilità. Niente URL, niente hashtag, niente CTA: vengono aggiunti dopo. "
          "Inizia con il nome in maiuscolo. Rispondi SOLO con il testo.")

_OPENERS = ["{NAME} ✨", "{NAME}", "{NAME} 🌙", "{NAME} 🔑"]
_MIDDLES = ["Quello che vedi è solo il lato pubblico.\nIl resto non lo trovi qui.", "{Adj}? Forse solo all'inizio.", "{Adj} e {adj2}, ma c'è un lato che non mostra a tutti.",
            "Uno sguardo basta per capire che c'è dell'altro.", "C'è la {Name} che vedi qui. E poi c'è il suo Lato Segreto.", "{Adj} nel modo giusto. Il resto è un'altra storia."]
_DESCR = {"eleganti": "elegante", "more": "intensa", "bionde": "luminosa", "tatuate": "decisa", "sportive": "energica", "cosplay": "giocosa", "latine": "solare", "rosse": "magnetica", "curvy": "sensuale"}


def italy_mode() -> bool:
    return os.environ.get("INSTAGRAM_ITALY_AUDIENCE_MODE", "true").lower() in ("1", "true", "yes")


def _pick(seq: List[str], seed: str, salt: int) -> str:
    return seq[int(hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest(), 16) % len(seq)]


def _facts(m: dict) -> dict:
    return {"nome": (m.get("nome_artistico") or m.get("nome") or "").strip(), "frase": (m.get("frase") or "").strip(), "bio": (m.get("bio") or "").strip()[:400],
            "categorie": [c for c in (m.get("categorie") or []) if isinstance(c, str)], "tag": [t for t in (m.get("tag") or []) if isinstance(t, str)][:8], "tema": m.get("tema") or ""}


def hashtags(m: dict, cycle: int) -> List[str]:
    """3-6 pertinent, mostly Italian hashtags; rotate so they are not always identical."""
    f = _facts(m)
    seed = f"{m.get('slug')}:{cycle}"
    base = ["#latosegreto"] + [t for i, t in enumerate(BASE_TAGS[1:]) if _pick(["y", "n"], seed, 20 + i) == "y"][:3]
    cats = [CATEGORY_TAGS[c.lower()] for c in f["categorie"] if c.lower() in CATEGORY_TAGS][:2]
    tags = list(dict.fromkeys(base + cats))
    if len(tags) < 3:
        tags += [t for t in BASE_TAGS if t not in tags][: 3 - len(tags)]
    return tags[:6]


def template_caption(m: dict, cycle: int) -> str:
    f = _facts(m)
    first = (f["nome"].split(" ")[0] or "Lei")
    adjs = [_DESCR[c.lower()] for c in f["categorie"] if c.lower() in _DESCR] or [t for t in f["tag"] if len(t) < 14][:2] or ["elegante", "intensa"]
    adj, adj2 = adjs[0], (adjs[1] if len(adjs) > 1 else "autentica")
    seed = f"{m.get('slug')}:{cycle}"
    opener = _pick(_OPENERS, seed, 1).format(NAME=first.upper())
    middle = f["frase"] if (f["frase"] and cycle % 3 == 2 and len(f["frase"]) <= 90) else _pick(_MIDDLES, seed, 2).format(Adj=adj.capitalize(), adj2=adj2, Name=first)
    return f"{opener}\n{middle}"


def _llm_available() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY")) and os.environ.get("INSTAGRAM_LLM_ENABLED", "true").lower() in ("1", "true", "yes")


async def llm_caption(m: dict, cycle: int):
    if not _llm_available():
        return None
    f = _facts(m)
    prompt = (f"Creator: {f['nome']}\nFrase breve: {f['frase'] or '-'}\nBio: {f['bio'] or '-'}\nCategorie: {', '.join(f['categorie']) or '-'}\nTag: {', '.join(f['tag']) or '-'}\nTema: {f['tema'] or '-'}\n"
              f"Ciclo n. {cycle}: caption DIVERSA dalle precedenti (variante {cycle % 5 + 1}). Massimo 3 righe, massimo 200 caratteri, deve creare curiosità verso il 'lato segreto' senza nominare piattaforme.")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"ig-copy-{m.get('slug')}-{cycle}", system_message=SYSTEM).with_model(*MODEL)
        text = str(await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=TIMEOUT_S)).strip().strip('"')
    except Exception:
        return None
    text = re.sub(r"https?://\S+|#\S+", "", text).strip()
    text = "\n".join(l.strip() for l in text.splitlines() if l.strip())[:300]
    first = f["nome"].split(" ")[0].lower()
    if not text or FORBIDDEN.search(text) or first not in text.lower() or (italy_mode() and len(ENGLISH_HINT.findall(text)) >= 3):
        return None
    return text


async def build_caption(m: dict, cycle: int, use_ai: bool = True) -> Dict[str, object]:
    text, source = None, "TEMPLATE"
    if use_ai:
        text = await llm_caption(m, cycle)
        if text:
            source = "LLM"
    if not text:
        text = template_caption(m, cycle)
    cta = _pick(CTAS, f"{m.get('slug')}:{cycle}", 9)
    tags = hashtags(m, cycle)
    caption = f"{text}\n\n{cta}\n\n{' '.join(tags)}"
    assert "http" not in caption.lower() and "onlyfans" not in caption.lower()
    if len(caption) > CAPTION_LIMIT:
        caption = caption[:CAPTION_LIMIT]
    return {"caption": caption, "text": text, "cta": cta, "hashtags": tags, "source": source, "language": "it"}
