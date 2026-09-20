"""Italian X copy — contrast LATO PUBBLICO vs LATO SEGRETO + CTA verso il link OnlyFans REALE della modella + 3-5 hashtag.
LLM (existing Emergent key) with deterministic Italian templates as fallback; never fails; weighted length <= 280 (URL = 23)."""
import asyncio
import hashlib
import os
import re
from typing import Dict, List

from .adapter import TEXT_LIMIT, x_len

MODEL = ("openai", os.environ.get("X_LLM_MODEL", os.environ.get("TELEGRAM_LLM_MODEL", "gpt-5.4-mini")))
TIMEOUT_S = 25
CTAS = ["🔗 Scoprila su OnlyFans:", "👇 Scoprila su OnlyFans", "Il suo Lato Segreto è qui 👇", "Tutto il resto, su OnlyFans 🔑", "Il Lato Segreto continua qui 👀"]
REPLIES = ["Lato Segreto 👀", "{NAME} — Lato Segreto 👀", "E questo è il suo Lato Segreto. 🔑", "Lato Segreto. Il resto lo trovi sopra 👆"]
BASE_TAGS = ["#LatoSegreto", "#CreatorItaliane", "#ModelleItaliane", "#Italia"]
CATEGORY_TAGS = {"eleganti": "#Eleganza", "more": "#Brunette", "bionde": "#Bionda", "tatuate": "#Tatuaggi", "sportive": "#Fitness", "cosplay": "#Cosplay", "latine": "#Latina", "rosse": "#Rossa", "curvy": "#Curvy"}
FORBIDDEN = re.compile(r"\b(\d{2}\s*anni|anni\b|città|vive a|abita a|di professione|lavora come|studentessa|infermiera|insegnante|cm\b|kg\b|taglia|seno|culo|sesso|scopa|porno|xxx|nud[aoie]|nude|onlyfans|instagram|telegram)\b", re.I)
ENGLISH_HINT = re.compile(r"\b(the|and|with|her|discover|you|now|this|what)\b", re.I)

SYSTEM = ("Sei il copywriter X (Twitter) di LATO SEGRETO, vetrina italiana elegante di creator. Scrivi in ITALIANO per un pubblico italiano un testo breve "
          "(2-4 righe, massimo 150 caratteri) che giochi sul contrasto tra il LATO PUBBLICO e il LATO SEGRETO della creator: curioso, elegante, provocante ma naturale, mai volgare. "
          "Usa SOLO le informazioni fornite (nome, frase, bio, categorie, tag, tema). NON inventare età, città/località, professione, caratteristiche fisiche, attività. "
          "Niente URL, niente hashtag, niente CTA, non nominare piattaforme: vengono aggiunti dopo. Inizia con il nome in MAIUSCOLO. Rispondi SOLO con il testo.")

_TEMPLATES = [
    "{NAME}\nLato Pubblico ✨\nLato Segreto 👀\nDue versioni, stessa {Name}.\nQuale scegli?",
    "Quello che tutti vedono.\nE quello che pochi scoprono.\n{NAME} — Lato Pubblico vs Lato Segreto 👀",
    "{NAME}\nLa prima foto la conoscono tutti.\nLa seconda, quasi nessuno.",
    "{NAME}: {adj} alla luce, {adj2} nel suo Lato Segreto. 🔑",
    "{NAME}\n«{frase}»\nLato Pubblico a sinistra. Lato Segreto a destra.",
    "Stessa {Name}, due lati.\nUno lo mostra a tutti.\nL'altro solo a chi lo cerca. 👀\n{NAME}",
]
_DESCR = {"eleganti": "elegante", "more": "intensa", "bionde": "luminosa", "tatuate": "decisa", "sportive": "energica", "cosplay": "giocosa", "latine": "solare", "rosse": "magnetica", "curvy": "sensuale"}


def italy_mode_env() -> bool:
    return os.environ.get("X_ITALY_AUDIENCE_MODE", "true").lower() in ("1", "true", "yes")


def _pick(seq: List[str], seed: str, salt: int) -> str:
    return seq[int(hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest(), 16) % len(seq)]


def _facts(m: dict) -> dict:
    return {"nome": (m.get("nome_artistico") or m.get("nome") or "").strip(), "frase": (m.get("frase") or "").strip(), "bio": (m.get("bio") or "").strip()[:400],
            "categorie": [c for c in (m.get("categorie") or []) if isinstance(c, str)], "tag": [t for t in (m.get("tag") or []) if isinstance(t, str)][:8], "tema": m.get("tema") or ""}


def hashtags(m: dict, cycle: int) -> List[str]:
    """3-5 pertinent Italian hashtags, rotating per cycle, never spam."""
    f = _facts(m)
    seed = f"{m.get('slug')}:{cycle}"
    tags = ["#LatoSegreto"] + [t for i, t in enumerate(BASE_TAGS[1:]) if _pick(["y", "n"], seed, 20 + i) == "y"][:2]
    tags += [CATEGORY_TAGS[c.lower()] for c in f["categorie"] if c.lower() in CATEGORY_TAGS][:2]
    tags = list(dict.fromkeys(tags))
    if len(tags) < 3:
        tags += [t for t in BASE_TAGS if t not in tags][: 3 - len(tags)]
    return tags[:5]


def template_text(m: dict, cycle: int) -> str:
    f = _facts(m)
    name = f["nome"] or "Lei"
    first = name.split(" ")[0]
    adjs = [_DESCR[c.lower()] for c in f["categorie"] if c.lower() in _DESCR] or [t for t in f["tag"] if len(t) < 14][:2] or ["elegante", "intensa"]
    adj, adj2 = adjs[0], (adjs[1] if len(adjs) > 1 else "diversa")
    seed = f"{m.get('slug')}:{cycle}"
    pool = _TEMPLATES if (f["frase"] and len(f["frase"]) <= 80) else [t for t in _TEMPLATES if "{frase}" not in t]
    idx = (cycle - 1) % len(pool)                              # a different template every cycle
    idx = (idx + int(hashlib.sha256(seed.encode()).hexdigest(), 16) % 2) % len(pool) if cycle > len(pool) else idx
    return pool[idx].format(NAME=name.upper(), Name=first, adj=adj, adj2=adj2, frase=f["frase"])


def reply_text(m: dict, cycle: int) -> str:
    return _pick(REPLIES, f"{m.get('slug')}:{cycle}", 7).format(NAME=(_facts(m)["nome"] or "").upper())


def _llm_available() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY")) and os.environ.get("X_LLM_ENABLED", "true").lower() in ("1", "true", "yes")


async def llm_text(m: dict, cycle: int, italy: bool = True):
    if not _llm_available():
        return None
    f = _facts(m)
    prompt = (f"Creator: {f['nome']}\nFrase breve: {f['frase'] or '-'}\nBio: {f['bio'] or '-'}\nCategorie: {', '.join(f['categorie']) or '-'}\nTag: {', '.join(f['tag']) or '-'}\nTema: {f['tema'] or '-'}\n"
              f"Ciclo n. {cycle}: testo DIVERSO dai precedenti (variante {cycle % 6 + 1}). Il post mostrer\u00e0 due media: il primo del Lato Pubblico, il secondo del Lato Segreto.")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"x-copy-{m.get('slug')}-{cycle}", system_message=SYSTEM).with_model(*MODEL)
        text = str(await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=TIMEOUT_S)).strip().strip('"')
    except Exception:
        return None
    text = re.sub(r"https?://\S+|#\S+|@\S+", "", text).strip()
    text = "\n".join(l.strip() for l in text.splitlines() if l.strip())[:170]
    first = (f["nome"].split(" ")[0] or "").lower()
    if not text or FORBIDDEN.search(text) or first not in text.lower() or (italy and len(ENGLISH_HINT.findall(text)) >= 3):
        return None
    return text


def compose(text: str, cta: str, of_url: str, tags: List[str]) -> str:
    body = f"{text}\n\n{cta}\n{of_url}\n\n{' '.join(tags)}"
    while x_len(body) > TEXT_LIMIT and len(tags) > 3:          # first drop optional hashtags
        tags = tags[:-1]
        body = f"{text}\n\n{cta}\n{of_url}\n\n{' '.join(tags)}"
    while x_len(body) > TEXT_LIMIT and len(text) > 40:         # then shorten the text
        text = text[:-8].rstrip() + "…"
        body = f"{text}\n\n{cta}\n{of_url}\n\n{' '.join(tags)}"
    return body


async def build_copy(m: dict, of_url: str, cycle: int, use_ai: bool = True, italy: bool = True) -> Dict[str, object]:
    """of_url MUST be the validated onlyfans.com link of THIS model (caller guarantees it)."""
    assert of_url and "onlyfans.com" in of_url
    text, source = None, "TEMPLATE"
    if use_ai:
        text = await llm_text(m, cycle, italy)
        if text:
            source = "LLM"
    if not text:
        text = template_text(m, cycle)
    cta = _pick(CTAS, f"{m.get('slug')}:{cycle}", 9)
    tags = hashtags(m, cycle)
    body = compose(text, cta, of_url, tags)
    assert body.count("http") == 1 and of_url in body and x_len(body) <= TEXT_LIMIT
    return {"text": body, "body": text, "cta": cta, "of_url": of_url, "hashtags": tags, "source": source, "language": "it", "reply_text": reply_text(m, cycle), "x_length": x_len(body)}
