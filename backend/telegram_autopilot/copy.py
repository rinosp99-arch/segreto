"""Italian promotional copy: LLM (existing Emergent key, same model family as the SEO layer) with deterministic templates as fallback.
Only real card data (name, frase, bio, categorie, tag, tema). Publishing never fails because of the LLM."""
import asyncio
import hashlib
import html
import os
import re
from typing import Dict, List, Optional

from .client import CAPTION_LIMIT

MODEL = ("openai", os.environ.get("TELEGRAM_LLM_MODEL", os.environ.get("SEO_AUTOPILOT_LLM_MODEL", "gpt-5.4-mini")))
TIMEOUT_S = 25
CTAS = ["⭐ SCOPRILA SU ONLYFANS", "🔥 GUARDA IL SUO PROFILO", "✨ ENTRA NEL SUO LATO SEGRETO", "👀 SCOPRI DI PIÙ SU ONLYFANS"]
FORBIDDEN = re.compile(r"\b(\d{2}\s*anni|anni\b|città|vive a|abita|di professione|lavora come|studentessa|infermiera|insegnante|cm\b|kg\b|taglia|seno|culo|sesso|scopa|porno|xxx|nuda|nude)\b", re.I)

SYSTEM = ("Sei il copywriter del canale Telegram LATO SEGRETO, una vetrina italiana elegante di creator OnlyFans. Scrivi caption brevi in italiano: "
          "2-3 righe, tono seducente ma elegante, mai volgare, mai spam, niente hashtag, niente keyword ripetute. "
          "Usa SOLO le informazioni fornite (nome, frase, bio, categorie, tag, tema). NON inventare età, città, professione, caratteristiche fisiche, attività, statistiche, disponibilità. "
          "Non inserire link né CTA: vengono aggiunti dopo. Rispondi SOLO con il testo della caption.")

_DESCR = {"eleganti": "elegante", "more": "intensa", "bionde": "luminosa", "tatuate": "decisa", "sportive": "energica", "cosplay": "giocosa", "latine": "solare", "rosse": "magnetica", "curvy": "sensuale"}
_OPENERS = ["{name} ✨", "{name} 🌙", "Ti presento {name} ✨", "{name} 🔥", "Oggi tocca a {name} ✨", "{name} 💫"]
_MIDDLES = ["{adj} e con un lato che non mostra proprio a tutti.", "{adj}, {adj2}: e quello che vedi qui è solo l'inizio.", "{adj} nel modo giusto. Il resto lo scopri solo tu.",
            "C'è la {name} di tutti i giorni. E poi c'è il suo lato segreto.", "{adj}, {adj2}, mai scontata.", "Uno sguardo basta per capire che c'è dell'altro."]
_CLOSERS = ["Scoprila qui 👇", "Il suo profilo ti aspetta 👇", "Entra nel suo lato segreto 👇", "Continua qui 👇", "Guarda tu stesso 👇"]


def _pick(seq: List[str], seed: str, salt: int = 0) -> str:
    h = int(hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest(), 16)
    return seq[h % len(seq)]


def _facts(m: dict) -> dict:
    return {"nome": m.get("nome_artistico") or m.get("nome") or "", "frase": (m.get("frase") or "").strip(), "bio": (m.get("bio") or "").strip()[:400],
            "categorie": [c for c in (m.get("categorie") or []) if isinstance(c, str)], "tag": [t for t in (m.get("tag") or []) if isinstance(t, str)][:8], "tema": m.get("tema") or ""}


def template_copy(m: dict, cycle: int) -> str:
    """Deterministic Italian copy, different per creator and per cycle."""
    f = _facts(m)
    name = f["nome"].split(" ")[0] if f["nome"] else "Lei"
    adjs = [_DESCR.get(c.lower()) for c in f["categorie"] if _DESCR.get(c.lower())] or [t for t in f["tag"] if len(t) < 14][:2] or ["elegante", "intensa"]
    adj = adjs[0].capitalize()
    adj2 = adjs[1] if len(adjs) > 1 else "autentica"
    seed = f"{m.get('slug')}:{cycle}"
    opener = _pick(_OPENERS, seed, 1).format(name=name)
    mid_t = _pick(_MIDDLES, seed, 2)
    middle = f["frase"] if (f["frase"] and cycle % 2 == 1 and len(f["frase"]) <= 90) else mid_t.format(adj=adj, adj2=adj2, name=name)
    closer = _pick(_CLOSERS, seed, 3)
    return f"{opener}\n{middle}\n{closer}"


def _llm_available() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY")) and os.environ.get("TELEGRAM_LLM_ENABLED", "true").lower() in ("1", "true", "yes")


async def llm_copy(m: dict, cycle: int) -> Optional[str]:
    """Returns the caption text or None (any failure -> None; the caller falls back to templates)."""
    if not _llm_available():
        return None
    f = _facts(m)
    prompt = (f"Creator: {f['nome']}\nFrase breve: {f['frase'] or '-'}\nBio: {f['bio'] or '-'}\nCategorie: {', '.join(f['categorie']) or '-'}\nTag: {', '.join(f['tag']) or '-'}\nTema: {f['tema'] or '-'}\n"
              f"Ciclo di pubblicazione n. {cycle}: scrivi una caption DIVERSA dalle precedenti (variante {cycle % 5 + 1}). Inizia con il nome, massimo 3 righe, massimo 220 caratteri.")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"tg-copy-{m.get('slug')}-{cycle}", system_message=SYSTEM).with_model(*MODEL)
        text = str(await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=TIMEOUT_S)).strip().strip('"')
    except Exception:
        return None
    text = re.sub(r"https?://\S+", "", text).strip()
    text = "\n".join(l.strip() for l in text.splitlines() if l.strip())[:300]
    if not text or FORBIDDEN.search(text) or f["nome"].split(" ")[0].lower() not in text.lower():
        return None            # invented / off-brand -> deterministic fallback
    return text


async def build_caption(m: dict, cycle: int, of_link: str, use_ai: bool = True) -> Dict[str, object]:
    text, source = None, "TEMPLATE"
    if use_ai:
        text = await llm_copy(m, cycle)
        if text:
            source = "LLM"
    if not text:
        text = template_copy(m, cycle)
    cta = _pick(CTAS, f"{m.get('slug')}:{cycle}", 9)
    safe_text = html.escape(text, quote=False)
    caption = f"{safe_text}\n\n<b>{cta}</b>\n{of_link}"
    if len(caption) > CAPTION_LIMIT:
        room = CAPTION_LIMIT - len(f"\n\n<b>{cta}</b>\n{of_link}") - 1
        caption = f"{safe_text[:max(0, room)].rstrip()}…\n\n<b>{cta}</b>\n{of_link}"
    return {"caption": caption, "text": text, "cta": cta, "source": source, "reply_markup": {"inline_keyboard": [[{"text": cta, "url": of_link}]]}}
