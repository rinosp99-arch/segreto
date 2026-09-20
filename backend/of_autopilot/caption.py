"""Italian OnlyFans captions for the latosegreto account: concept LATO PUBBLICO vs LATO SEGRETO, personalised on the model,
different per cycle, LLM (existing Emergent key) with deterministic Italian templates as fallback.
Final format:  <caption>\n\nScoprila su OnlyFans:\n<REAL OF link of the model from the DB>   (no generated @mentions, no other links)."""
import asyncio
import hashlib
import os
import re
from typing import Dict, List

MODEL = ("openai", os.environ.get("OF_LLM_MODEL", os.environ.get("TELEGRAM_LLM_MODEL", "gpt-5.4-mini")))
TIMEOUT_S = 25
CAPTION_LIMIT = 900
CTA = "Scoprila su OnlyFans:"
FORBIDDEN = re.compile(r"\b(\d{2}\s*anni|anni\b|città|vive a|abita a|di professione|lavora come|studentessa|infermiera|insegnante|cm\b|kg\b|taglia|seno|culo|sesso|scopa|porno|xxx|nud[aoie]|nude|onlyfans|instagram|telegram|twitter)\b", re.I)
ENGLISH_HINT = re.compile(r"\b(the|and|with|her|discover|you|now|this|what)\b", re.I)

SYSTEM = ("Sei il copywriter OnlyFans di LATO SEGRETO, pagina italiana elegante che presenta creator. Scrivi in ITALIANO un testo breve (2-4 righe, massimo 220 caratteri) "
          "che giochi sul contrasto tra il LATO PUBBLICO e il LATO SEGRETO della creator: elegante, intrigante, provocante ma mai volgare, mai ripetitivo. "
          "Usa SOLO le informazioni fornite (nome, frase, bio, categorie, tag, tema). NON inventare età, città, professione, caratteristiche fisiche, attività. "
          "Niente URL, niente hashtag, niente @menzioni, niente CTA, non nominare piattaforme: la CTA con il link viene aggiunta dopo. Inizia con il nome in MAIUSCOLO. Rispondi SOLO con il testo.")

_TEMPLATES = [
    "{NAME}\nDue lati.\nQuello che tutti vedono e quello che pochi scoprono.",
    "Il suo Lato Pubblico lo conosci.\nAdesso guarda il suo Lato Segreto.\n{NAME}",
    "{NAME}\nLa prima immagine è per tutti.\nLa seconda è il suo Lato Segreto.",
    "{NAME}: {adj} alla luce, {adj2} nel suo Lato Segreto.",
    "{NAME}\n«{frase}»\nLato Pubblico prima. Lato Segreto dopo.",
    "Stessa {Name}, due versioni.\nUna la mostra a tutti, l'altra solo a chi la cerca.\n{NAME}",
]
_DESCR = {"eleganti": "elegante", "more": "intensa", "bionde": "luminosa", "tatuate": "decisa", "sportive": "energica", "cosplay": "giocosa", "latine": "solare", "rosse": "magnetica", "curvy": "sensuale"}


def _facts(m: dict) -> dict:
    return {"nome": (m.get("nome_artistico") or m.get("nome") or "").strip(), "frase": (m.get("frase") or "").strip(), "bio": (m.get("bio") or "").strip()[:400],
            "categorie": [c for c in (m.get("categorie") or []) if isinstance(c, str)], "tag": [t for t in (m.get("tag") or []) if isinstance(t, str)][:8], "tema": m.get("tema") or ""}


def template_text(m: dict, cycle: int) -> str:
    f = _facts(m)
    name = f["nome"] or "Lei"
    first = name.split(" ")[0]
    adjs = [_DESCR[c.lower()] for c in f["categorie"] if c.lower() in _DESCR] or [t for t in f["tag"] if len(t) < 14][:2] or ["elegante", "intensa"]
    adj, adj2 = adjs[0], (adjs[1] if len(adjs) > 1 else "diversa")
    pool = _TEMPLATES if (f["frase"] and len(f["frase"]) <= 80) else [t for t in _TEMPLATES if "{frase}" not in t]
    idx = (cycle - 1) % len(pool)
    if cycle > len(pool):
        idx = (idx + int(hashlib.sha256(f"{m.get('slug')}:{cycle}".encode()).hexdigest(), 16) % 2) % len(pool)
    return pool[idx].format(NAME=name.upper(), Name=first, adj=adj, adj2=adj2, frase=f["frase"])


def _llm_available() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY")) and os.environ.get("OF_LLM_ENABLED", "true").lower() in ("1", "true", "yes")


async def llm_text(m: dict, cycle: int):
    if not _llm_available():
        return None
    f = _facts(m)
    prompt = (f"Creator: {f['nome']}\nFrase breve: {f['frase'] or '-'}\nBio: {f['bio'] or '-'}\nCategorie: {', '.join(f['categorie']) or '-'}\nTag: {', '.join(f['tag']) or '-'}\nTema: {f['tema'] or '-'}\n"
              f"Ciclo n. {cycle}: testo DIVERSO dai precedenti (variante {cycle % 6 + 1}). Il post mostra due media: il primo del Lato Pubblico, il secondo del Lato Segreto.")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"of-copy-{m.get('slug')}-{cycle}", system_message=SYSTEM).with_model(*MODEL)
        text = str(await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=TIMEOUT_S)).strip().strip('"')
    except Exception:
        return None
    text = re.sub(r"https?://\S+|#\S+|@\S+", "", text).strip()
    text = "\n".join(l.strip() for l in text.splitlines() if l.strip())[:260]
    first = (f["nome"].split(" ")[0] or "").lower()
    if not text or FORBIDDEN.search(text) or first not in text.lower() or len(ENGLISH_HINT.findall(text)) >= 3:
        return None
    return text


async def build_caption(m: dict, of_url: str, cycle: int, use_ai: bool = True) -> Dict[str, object]:
    """of_url MUST be the model's own validated onlyfans.com link (caller guarantees it). Never generates @mentions."""
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
    assert text.count("http") == 1 and of_url in text and "@" not in body
    return {"text": text, "body": body, "cta": CTA, "of_url": of_url, "source": source, "language": "it"}
