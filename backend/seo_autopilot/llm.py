"""LLM suggestion layer (decision 1b). Advisory ONLY:
- every output is tagged source=LLM_SUGGESTION and cached (key = model + prompt hash);
- it can propose Italian synonyms/variants, long-tail ideas, an intent opinion, cluster-merge suggestions;
- it can NEVER produce metrics: any numeric "volume/impression/ctr/position" returned is discarded;
- final decisions are taken by deterministic rules (clustering.py / opportunities.py / planner.py).
Fails soft: no key, no budget, timeout -> returns {"available": False} and the engine continues.
"""
import asyncio
import hashlib
import json
import os
import re
from typing import Any, List, Optional

from dotenv import load_dotenv

from .store import llm_cache_col, state_col, now_iso

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

MODEL = ("openai", os.environ.get("SEO_AUTOPILOT_LLM_MODEL", "gpt-5.4-mini"))
DAILY_CALL_BUDGET = int(os.environ.get("SEO_AUTOPILOT_LLM_DAILY_CALLS", "40"))
TIMEOUT_S = 60
SOURCE = "LLM_SUGGESTION"
FORBIDDEN_NUMERIC = re.compile(r"(volume|impression|impressions|clicks|ctr|position|ranking|traffic|search_volume)", re.I)

SYSTEM = ("Sei un SEO specialist italiano per un sito che presenta creator/modelle italiane con profili OnlyFans (contenuti non espliciti). "
          "Rispondi SOLO con JSON valido, in italiano, senza testo extra. Non stimare MAI volumi di ricerca, impression, CTR, posizioni o trend: "
          "non hai accesso a questi dati. Non inventare nomi di creator: usa solo quelli forniti. Evita keyword stuffing e combinazioni meccaniche senza intento reale.")


def _key() -> Optional[str]:
    return os.environ.get("EMERGENT_LLM_KEY") or None


def available() -> bool:
    return bool(_key()) and os.environ.get("SEO_AUTOPILOT_LLM_ENABLED", "true").lower() in ("1", "true", "yes")


async def _calls_today() -> int:
    st = await state_col.find_one({"id": "global"}, {"_id": 0, "llm_calls": 1}) or {}
    return int(((st.get("llm_calls") or {}).get(now_iso()[:10])) or 0)


async def _count_call():
    await state_col.update_one({"id": "global"}, {"$inc": {f"llm_calls.{now_iso()[:10]}": 1}}, upsert=True)


def _strip_numbers(obj: Any) -> Any:
    """Remove any metric-like numeric fields the model may have produced (rule 24/25)."""
    if isinstance(obj, dict):
        return {k: _strip_numbers(v) for k, v in obj.items() if not (FORBIDDEN_NUMERIC.search(str(k)) and isinstance(v, (int, float)))}
    if isinstance(obj, list):
        return [_strip_numbers(x) for x in obj]
    return obj


async def ask_json(task: str, payload: dict, cache_ttl_days: int = 14) -> dict:
    """One JSON-in/JSON-out call. Returns {available, cached, data, source}. Never raises."""
    if not available():
        return {"available": False, "reason": "LLM non configurato (EMERGENT_LLM_KEY assente o SEO_AUTOPILOT_LLM_ENABLED=false)", "source": SOURCE}
    prompt = json.dumps({"task": task, **payload}, ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256((MODEL[1] + prompt).encode()).hexdigest()[:32]
    cached = await llm_cache_col.find_one({"key": key}, {"_id": 0})
    if cached:
        return {"available": True, "cached": True, "data": cached["data"], "source": SOURCE, "model": MODEL[1]}
    if await _calls_today() >= DAILY_CALL_BUDGET:
        return {"available": False, "reason": f"budget LLM giornaliero esaurito ({DAILY_CALL_BUDGET} chiamate)", "source": SOURCE}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(api_key=_key(), session_id=f"seo-autopilot-{key[:12]}", system_message=SYSTEM).with_model(*MODEL)
        await _count_call()
        text = await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=TIMEOUT_S)
        raw = str(text).strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1] if "{" in raw else raw
        data = _strip_numbers(json.loads(raw))
        await llm_cache_col.update_one({"key": key}, {"$set": {"key": key, "task": task, "data": data, "model": MODEL[1], "created_at": now_iso()}}, upsert=True)
        return {"available": True, "cached": False, "data": data, "source": SOURCE, "model": MODEL[1]}
    except Exception as e:
        return {"available": False, "reason": f"{type(e).__name__}: {str(e)[:160]}", "source": SOURCE}


# ------------------------------------------------------------------------------------------------ tasks
async def suggest_variants(seeds: List[str], creators: List[str], categories: List[str], tags: List[str]) -> dict:
    """Italian synonyms / variants / long-tail with a REAL intent for the given seeds. Metrics are never requested."""
    return await ask_json("keyword_variants", {
        "istruzioni": "Per ogni seed proponi al massimo 6 varianti italiane realistiche che una persona digiterebbe davvero su Google (sinonimi, plurali, ordine parole, long-tail con intento chiaro). "
                      "Escludi combinazioni meccaniche (città, colori, numeri) senza intento reale. Per ogni variante indica intent tra DISCOVERY, CATEGORY, CREATOR, INFORMATIONAL, BRANDED, NAVIGATIONAL. "
                      "Formato: {\"variants\":[{\"seed\":\"…\",\"keyword\":\"…\",\"intent\":\"…\",\"motivo\":\"…\"}]}",
        "seeds": seeds[:20], "creator_reali": creators[:40], "categorie_reali": categories[:20], "tag_reali": tags[:40]})


async def classify_intents(keywords: List[str], creators: List[str], categories: List[str], brand: str) -> dict:
    return await ask_json("intent_classification", {
        "istruzioni": "Classifica ogni keyword con intent (DISCOVERY, CATEGORY, CREATOR, INFORMATIONAL, BRANDED, NAVIGATIONAL, COMMERCIAL, OTHER) e confidence 0-1. "
                      "Formato: {\"items\":[{\"keyword\":\"…\",\"intent\":\"…\",\"confidence\":0.0,\"motivo\":\"…\"}]}",
        "brand": brand, "creator_reali": creators[:40], "categorie_reali": categories[:20], "keywords": keywords[:80]})


async def suggest_merges(clusters: List[dict]) -> dict:
    """Given cluster labels + members, suggest which clusters express the SAME search intent (candidates only; rules decide)."""
    return await ask_json("cluster_merge", {
        "istruzioni": "Indica coppie di cluster che esprimono sostanzialmente lo stesso intento di ricerca (stessa pagina ideale). Sii conservativo: unisci solo se un utente si aspetterebbe la stessa pagina. "
                      "Formato: {\"merges\":[{\"a\":\"cluster_id\",\"b\":\"cluster_id\",\"confidence\":0.0,\"motivo\":\"…\"}]}",
        "clusters": [{"cluster_id": c["cluster_id"], "primary": c["primary_keyword"], "members": c.get("keywords", [])[:8], "intent": c.get("intent")} for c in clusters[:60]]})
