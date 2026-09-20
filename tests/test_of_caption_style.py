"""OF caption style v2 — brand format ✨ LATO PUBBLICO / 🔥 LATO SEGRETO + hook + 💋 CTA with the model's REAL OF link.
Checks: CAPTION_STRUCTURE_PUBLIC_SECRET · EMOJI_PRESENT · ITALIAN_ONLY · MODEL_PERSONALIZATION · CAPTION_NOT_TOO_LONG · QUESTION_OR_HOOK_PRESENT ·
REAL_OF_LINK · GLOBAL_OF_LINK_NOT_USED · NO_FAKE_DETAILS · LLM_FALLBACK_STYLE_UPDATED. Zero network, zero writes."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from of_autopilot import caption as ofcap, media as ofmedia  # noqa: E402

pytestmark = pytest.mark.anyio

MODELS = [
    {"id": "m1", "slug": "vanessa-bella", "nome_artistico": "Vanessa Bella", "frase": "Ogni tatuaggio è un segreto.", "bio": "Creator dallo stile tattoo, dark.", "categorie": ["tatuate", "more"], "tag": ["tattoo", "dark"], "tema": {"preset": "tattoo"}, "onlyfans_url": "https://onlyfans.com/vanessa_bellaaa/c9"},
    {"id": "m2", "slug": "federica-sole", "nome_artistico": "Federica Sole", "frase": "Ti sfido a starmi dietro.", "bio": "Creator sportiva.", "categorie": ["sportive"], "tag": ["sportiva", "fit"], "tema": {"preset": "sportiva"}, "onlyfans_url": "https://onlyfans.com/federicasole"},
    {"id": "m3", "slug": "giulia-chic", "nome_artistico": "Giulia Chic", "frase": "", "bio": "", "categorie": ["eleganti", "bionde"], "tag": ["chic"], "tema": {"preset": "bordeaux"}, "onlyfans_url": "https://onlyfans.com/giuliachic"},
    {"id": "m4", "slug": "mia-cos", "nome_artistico": "Mia Cos", "frase": "Un personaggio diverso ogni notte.", "bio": "Cosplay.", "categorie": ["cosplay"], "tag": ["cosplay", "fantasy"], "tema": {"preset": "cosplay"}, "onlyfans_url": "https://onlyfans.com/miacos"},
    {"id": "m5", "slug": "sara-dolce", "nome_artistico": "Sara Dolce", "frase": "Dolce finché non premi.", "bio": "", "categorie": [], "tag": [], "tema": None, "onlyfans_url": "https://onlyfans.com/saradolce"},
]


def _structure_ok(text: str, m: dict) -> bool:
    lines = [l for l in text.split("\n") if l.strip()]
    name = (m["nome_artistico"]).upper()
    i_pub, i_sec, i_cta = lines.index(ofcap.H_PUBLIC), lines.index(ofcap.H_SECRET), lines.index(ofcap.CTA)
    return lines[0] == name and 0 < i_pub < i_sec < i_cta and i_pub + 1 < i_sec and i_sec + 2 < i_cta and lines[-1] == m["onlyfans_url"] and lines[i_sec + 2] and text.count("http") == 1


async def test_structure_emoji_italian_length_hook_link_fallback(monkeypatch):
    monkeypatch.setattr(ofcap, "_llm_available", lambda: False)
    for m in MODELS:
        c = await ofcap.build_caption(m, m["onlyfans_url"], 1, use_ai=True)
        t = c["text"]
        assert c["source"] == "TEMPLATE" and c["language"] == "it"
        assert _structure_ok(t, m), t                                                                  # CAPTION_STRUCTURE_PUBLIC_SECRET
        assert ofcap.count_emoji(t) >= 3 and ofcap.count_emoji(t) <= ofcap.MAX_EMOJI, t                # EMOJI_PRESENT (moderate)
        assert not ofcap.ENGLISH_HINT.search(c["body"]), t                                             # ITALIAN_ONLY
        assert len(t) <= ofcap.CAPTION_LIMIT and len(t) < 600, len(t)                                  # CAPTION_NOT_TOO_LONG
        hook = [l for l in c["body"].split("\n") if l.strip()][-1]
        assert hook and (hook.endswith("?") or "?" in hook or ofcap.count_emoji(hook) or "lato" in hook.lower()), hook   # QUESTION_OR_HOOK_PRESENT
        assert t.rstrip().endswith(m["onlyfans_url"]) and "onlyfans.com/" in t and "@" not in c["body"]  # REAL_OF_LINK
        assert "onlyfans.com/latosegreto" not in t                                                     # GLOBAL_OF_LINK_NOT_USED
        assert not ofcap.FORBIDDEN.search(c["body"]), c["body"]                                         # NO_FAKE_DETAILS (no age/city/job/physical/platform words)
        assert "Due lati." not in c["body"] and ofcap.H_PUBLIC in c["body"] and ofcap.H_SECRET in c["body"]  # LLM_FALLBACK_STYLE_UPDATED (old flat copy gone)


async def test_personalization_and_variety(monkeypatch):
    monkeypatch.setattr(ofcap, "_llm_available", lambda: False)
    van = MODELS[0]
    parts = ofcap.template_parts(van, 1)
    blob = " ".join(parts.values()).lower()
    adjs = ofcap._adjectives(ofcap._facts(van))
    assert "dark" in adjs and "decisa" in adjs and "intensa" in adjs                                     # derived ONLY from real categorie/tag/stile
    assert any(a in blob for a in adjs) or "vanessa" in blob or "ogni tatuaggio" in blob                  # MODEL_PERSONALIZATION
    # different models -> different captions in the same cycle
    bodies = {(await ofcap.build_caption(m, m["onlyfans_url"], 1, use_ai=False))["body"] for m in MODELS}
    assert len(bodies) == len(MODELS)
    # same model -> different copy across cycles (fallback never flat/identical)
    cyc = [(await ofcap.build_caption(van, van["onlyfans_url"], i, use_ai=False))["body"] for i in range(1, 9)]
    assert len(set(cyc)) >= 6
    assert all(c.split("\n")[0] == "VANESSA BELLA" for c in cyc)
    assert len(ofcap.PUBLIC_TEMPLATES) >= 10 and len(ofcap.SECRET_TEMPLATES) >= 10 and len(ofcap.HOOK_TEMPLATES) >= 10


async def test_llm_json_path_validated(monkeypatch):
    m = MODELS[0]
    good = {"public": "Dark, magnetica e con quello sguardo che non passa inosservato.", "secret": "Ma quando lascia uscire il suo lato più audace, l'atmosfera cambia completamente.", "hook": "Pubblico o Segreto… quale Vanessa sceglieresti? 🔥"}
    monkeypatch.setattr(ofcap, "llm_parts", lambda m, c: asyncio.sleep(0, result=dict(good)))
    c = await ofcap.build_caption(m, m["onlyfans_url"], 1, use_ai=True)
    assert c["source"] == "LLM" and _structure_ok(c["text"], m) and good["public"] in c["text"] and good["hook"] in c["text"]
    assert c["text"].endswith(f"{ofcap.CTA}\n{m['onlyfans_url']}")                                      # link deterministic, outside creative part
    # invalid LLM output (fake details / english / url / platform) -> rejected -> template fallback
    for bad in ({"public": "Ha 24 anni e vive a Milano.", "secret": "x", "hook": "y"}, {"public": "Discover the secret side with her now", "secret": "s", "hook": "h"},
                {"public": "Vai su https://x.y", "secret": "s", "hook": "h"}, {"public": "Seguila su onlyfans", "secret": "s", "hook": "h"}, {"public": "", "secret": "s", "hook": "h"}):
        assert not ofcap._valid_parts({k: ofcap._clean_sentence(v) for k, v in bad.items()}), bad
    monkeypatch.setattr(ofcap, "llm_parts", lambda m, c: asyncio.sleep(0, result=None))
    assert (await ofcap.build_caption(m, m["onlyfans_url"], 2, use_ai=True))["source"] == "TEMPLATE"


async def test_link_guards():
    assert ofmedia.valid_of_link("https://onlyfans.com/latosegreto") is None                            # GLOBAL_OF_LINK_NOT_USED
    assert ofmedia.valid_of_link("https://latosegreto.it/vanessa") is None
    assert ofmedia.valid_of_link("onlyfans.com/vanessa_bellaaa/c9") == "https://onlyfans.com/vanessa_bellaaa/c9"
    with pytest.raises(AssertionError):
        await ofcap.build_caption(MODELS[0], "https://latosegreto.it/x", 1, use_ai=False)
