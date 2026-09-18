"""Deterministic Italian text normalisation for keywords: lowercase, accent folding, stopword removal, light stemming,
sector synonym canonicalisation (OF == OnlyFans, ragazze ~ modelle ~ creator when used as 'people' head nouns).
The canonical token set is what clustering compares — fully auditable, no ML."""
import re
import unicodedata
from typing import List, Set

STOP = {"di", "del", "della", "dei", "delle", "dello", "degli", "il", "lo", "la", "i", "gli", "le", "un", "una", "uno", "e", "ed", "o", "con", "per", "su", "sul", "sulla", "sui", "sulle",
        "in", "a", "al", "alla", "ai", "alle", "da", "dal", "dalla", "che", "chi", "cui", "the", "on", "nel", "nella", "nei", "nelle", "più", "piu"}   # NB: "of" is NOT a stopword here (OF = OnlyFans)
# sector synonyms -> canonical token (used ONLY for clustering equivalence, never rewrites user text)
SYN = {
    "of": "onlyfans", "only": "onlyfans", "onlyfan": "onlyfans", "onlyfans": "onlyfans", "onlyfance": "onlyfans",
    "ragazza": "ragazze", "ragazze": "ragazze", "modella": "modelle", "modelle": "modelle", "modelli": "modelle", "creator": "creator", "creators": "creator", "creatrici": "creator", "creatrice": "creator",
    "profilo": "profili", "profili": "profili", "account": "profili", "pagine": "profili", "pagina": "profili",
    "italiana": "italiane", "italiane": "italiane", "italiani": "italiane", "italiano": "italiane", "italia": "italiane", "ita": "italiane",
    "migliore": "migliori", "migliori": "migliori", "top": "migliori", "best": "migliori",
    "gratis": "gratis", "free": "gratis", "gratuito": "gratis", "gratuiti": "gratis",
    "tatuata": "tatuate", "tatuate": "tatuate", "tattoo": "tatuate", "tatuaggi": "tatuate",
    "bionda": "bionde", "bionde": "bionde", "mora": "more", "more": "more", "brune": "more", "bruna": "more",
    "sportiva": "sportive", "sportive": "sportive", "fitness": "sportive", "fit": "sportive",
    "elegante": "eleganti", "eleganti": "eleganti", "raffinata": "eleganti", "raffinate": "eleganti", "chic": "eleganti",
    "latina": "latine", "latine": "latine", "latino": "latine", "latinoamericane": "latine", "sudamericane": "latine",
    "cosplayer": "cosplay", "cosplay": "cosplay",
}
# 'people' head nouns are equivalent for DISCOVERY intent (ragazze onlyfans ~ modelle onlyfans ~ creator onlyfans)
PEOPLE = {"ragazze", "modelle", "creator", "profili"}
STEM_SUFFIXES = ("issime", "issimi", "mente", "zione", "zioni", "ate", "ati", "ata", "ato", "are", "ere", "ire", "ine", "ini", "ina", "ino", "e", "i", "a", "o")
INFO_MARKERS = {"come", "cosa", "perche", "perché", "quanto", "quanti", "quale", "quali", "dove", "guida", "consigli", "trovare", "cercare", "funziona", "significa", "cos'e", "cos", "differenza", "recensione", "recensioni", "opinioni", "classifica"}
NAV_MARKERS = {"login", "accedi", "app", "sito", "ufficiale", "iscriversi", "iscrizione", "registrarsi", "abbonamento", "prezzo", "prezzi", "costo", "costa"}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("'", " ").replace("’", " ")
    return re.sub(r"[^a-z0-9\s]", " ", s)


def tokens(s: str) -> List[str]:
    return [t for t in fold(s).split() if t and t not in STOP]


def stem(t: str) -> str:
    if t in SYN:
        return SYN[t]
    if len(t) <= 4:
        return t
    for suf in STEM_SUFFIXES:
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            return t[: -len(suf)]
    return t


def canon_tokens(s: str) -> Set[str]:
    """Canonical token set: synonyms folded, light stem, stopwords removed."""
    return {SYN.get(t, stem(t)) for t in tokens(s)}


def norm_key(s: str) -> str:
    """Stable identity of a keyword (dedup): folded tokens sorted."""
    return " ".join(sorted(tokens(s)))


def cluster_key(s: str) -> str:
    """Identity used for deterministic clustering: canonical tokens, people-nouns collapsed to one class."""
    toks = canon_tokens(s)
    if toks & PEOPLE:
        toks = (toks - PEOPLE) | {"<persone>"}
    return " ".join(sorted(toks))


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a: str, b: str) -> float:
    """Token-set similarity of two strings (titles/H1), 0..1."""
    return jaccard(canon_tokens(a), canon_tokens(b))
