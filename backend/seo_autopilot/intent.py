"""Rule-based search-intent classification (rule 7). LLM opinion may be attached as advisory (intent_llm) but the
stored intent is the deterministic one unless rules are unsure (confidence < 0.6) and the LLM is confident (>= 0.75)."""
from typing import List, Tuple

from .textnorm import canon_tokens, fold, tokens, INFO_MARKERS, NAV_MARKERS, PEOPLE

CATEGORY_TOKENS = {"tatuate", "bionde", "more", "sportive", "eleganti", "latine", "cosplay", "rosse", "curvy", "milf", "mature", "giovani", "asiatiche", "gothic", "dark", "alternative"}


def classify(keyword: str, creator_names: List[str], categories: List[str], tags: List[str], brand: str) -> Tuple[str, float, str]:
    f = fold(keyword)
    toks = set(tokens(keyword))
    ct = canon_tokens(keyword)
    b = fold(brand).replace(" ", "")
    if b and (b in f.replace(" ", "")):
        return "BRANDED", 0.95, f"contiene il brand '{brand}'"
    for name in creator_names:
        fn = fold(name).strip()
        if fn and fn in f:
            return "CREATOR", 0.95, f"contiene il nome della creator '{name}'"
    # first name alone + onlyfans (e.g. 'vanessa onlyfans') -> CREATOR only if unique among creators
    firsts = {}
    for name in creator_names:
        first = fold(name).split()[0] if fold(name).split() else ""
        firsts.setdefault(first, []).append(name)
    for t in toks:
        if t in firsts and len(firsts[t]) == 1 and ("onlyfans" in ct or "lato" in toks):
            return "CREATOR", 0.7, f"nome proprio '{t}' (unica creator) + contesto"
    if toks & INFO_MARKERS:
        return "INFORMATIONAL", 0.85, f"marker informativo: {sorted(toks & INFO_MARKERS)}"
    if toks & NAV_MARKERS:
        return "NAVIGATIONAL", 0.8, f"marker navigazionale/commerciale: {sorted(toks & NAV_MARKERS)}"
    cat_tokens = CATEGORY_TOKENS | {c for cat in categories for c in canon_tokens(cat)} | {c for tg in tags for c in canon_tokens(tg)}
    hit = ct & cat_tokens
    if hit and (ct & PEOPLE or "onlyfans" in ct):
        return "CATEGORY", 0.85, f"attributo di categoria {sorted(hit)} + persone/onlyfans"
    if "onlyfans" in ct and (ct & PEOPLE or "italiane" in ct):
        return "DISCOVERY", 0.85, "onlyfans + persone/italiane: ricerca di scoperta"
    if ct & PEOPLE and "italiane" in ct:
        return "DISCOVERY", 0.6, "persone + italiane senza onlyfans esplicito"
    if "onlyfans" in ct:
        return "NAVIGATIONAL", 0.5, "solo onlyfans senza qualificatori (probabile navigazione verso la piattaforma)"
    if hit:
        return "CATEGORY", 0.5, f"solo attributo {sorted(hit)} (contesto debole)"
    return "OTHER", 0.3, "nessuna regola applicabile"


def merge_llm_opinion(rule_intent: str, rule_conf: float, llm_intent: str, llm_conf: float) -> Tuple[str, str]:
    """Returns (final_intent, source). Deterministic rule wins unless it is unsure and the LLM is confident."""
    if llm_intent and rule_conf < 0.6 and (llm_conf or 0) >= 0.75 and llm_intent != rule_intent:
        return llm_intent, "LLM_SUGGESTION"
    return rule_intent, "RULES"
