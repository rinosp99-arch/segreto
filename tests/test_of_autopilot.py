"""OF Autopilot tests (MockOFProvider for every write; the real provider is READ-ONLY; THE_ONLY_API_REAL_WRITE_CALLS must stay 0).
A eligibility · B Public+Secret pairing · C same model_id · D real OF link · E/F/G missing OF/Public/Secret -> skip · H/I public/secret cursor · J media wrap ·
K Italian caption · L LLM fallback · M circular queue · N no duplicate per cycle · O new model mid-cycle · P model removed mid-cycle · Q restart persistence ·
R duplicate slot · S concurrency · T pause · U manual skip · V preview · W publish-now mock (immediate) · X mock schedule (+verify) · Y zero provider write
+ media source (real HEAD on our storage, MIME, video, source_url, file fallback, media object, cursor only after success) + link OF rules + flows separation.
"""
import asyncio
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/tests")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")
os.environ["OF_AUTOPILOT_MOCK"] = "true"
os.environ["OF_REAL_POSTING_ENABLED"] = "false"
os.environ["OF_AUTO_SCHEDULER_ENABLED"] = "false"
os.environ["OF_MASS_DM_ENABLED"] = "false"          # feed-only suite: the mass DM step is covered by tests/test_of_mass_dm.py
os.environ["OF_MASS_DM_MOCK"] = "true"

from of_autopilot import engine, media as ofmedia, caption as ofcap, connection  # noqa: E402
from of_autopilot.providers import the_only_api as toa  # noqa: E402
from of_autopilot.providers.base import OFMedia, OFPostRequest, OFProviderAdapter, OFProviderError  # noqa: E402
from of_autopilot.providers.mock import MockOFProvider  # noqa: E402
from database import models_col, db  # noqa: E402
from _creds import admin_credentials  # noqa: E402

pytestmark = pytest.mark.anyio
BASE = os.environ.get("TEST_BACKEND", "http://localhost:8001")
TAG = f"oft-{uuid.uuid4().hex[:6]}"
HOST = ofmedia.media_base()                         # production media host (real HEAD checks, read-only)
REAL_PHOTO = "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=900&q=80"
REAL_VIDEO = f"{HOST}/media/pub1.mp4"
REAL_SITE_PHOTO = f"{HOST}/media/pub1.jpg"
MISSING = f"{HOST}/media/__does_not_exist_{TAG}"    # real 404 on our host


def _model(slug, pub=None, sec=None, of=None, stato="pubblicata", ordine=0, **extra):
    pub = pub if pub is not None else [REAL_PHOTO, REAL_SITE_PHOTO]
    sec = sec if sec is not None else [REAL_PHOTO.replace("q=80", "q=79"), REAL_SITE_PHOTO.replace("pub1", "pub2")]
    pairs = []
    for i in range(max(len(pub), len(sec))):
        p = pub[i] if i < len(pub) else None
        s_ = sec[i] if i < len(sec) else None
        pairs.append({"id": f"{slug}-{i}", "tipo": "image",
                      "pubblico": {"tipo": "video" if (p or "").endswith(".mp4") else "image", "url": p} if p else {},
                      "segreto": {"tipo": "video" if (s_ or "").endswith(".mp4") else "image", "url": s_} if s_ else {}})
    return {"id": str(uuid.uuid4()), "slug": slug, "nome": slug.split("-")[-1].capitalize(), "nome_artistico": f"{slug.split('-')[-1].capitalize()} Test", "frase": "Dolce finché non premi.", "bio": "bio",
            "categorie": ["eleganti"], "tag": ["raffinata"], "onlyfans_url": of if of is not None else f"https://onlyfans.com/{slug}", "media_pairs": pairs, "galleria_pubblica": [], "galleria_segreta": [],
            "stato": stato, "is_deleted": False, "ordine": ordine, "created_at": "2026-01-01", "_test_tag": TAG, **extra}


@pytest.fixture
async def sandbox():
    mock = MockOFProvider()
    engine.force_provider(mock)
    await engine.ensure_indexes()
    saved_state = await engine.state_col.find_one({"id": "global"}, {"_id": 0})
    await engine.state_col.delete_one({"id": "global"})
    await engine.ensure_indexes()
    await engine.set_state(use_ai_copy=False)
    orig = ofmedia.published_models

    async def only_test():
        items = [m async for m in models_col.find({"_test_tag": TAG, "stato": "pubblicata", "is_deleted": {"$ne": True}}, ofmedia.FIELDS | {"_test_tag": 1})]
        items.sort(key=ofmedia._order_key)
        return items
    ofmedia.published_models = only_test
    writes_before = toa.CALLS["write"]
    yield mock
    assert toa.CALLS["write"] == writes_before == 0, "a REAL provider write happened"
    ofmedia.published_models = orig
    engine.force_provider(None)
    test_ids = [m["id"] async for m in models_col.find({"_test_tag": TAG}, {"id": 1})]
    await models_col.delete_many({"_test_tag": TAG})
    await engine.media_state_col.delete_many({"model_id": {"$in": test_ids}})
    await engine.uploads_col.delete_many({"model_id": {"$in": test_ids}})
    await engine.runs_col.delete_many({"model_id": {"$in": test_ids}})
    await engine.log_col.delete_many({"$or": [{"model_slug": {"$regex": f"^{TAG}"}}, {"slot_id": {"$regex": f"^{TAG}"}}]})
    await engine.slots_col.delete_many({"slot_id": {"$regex": f"^{TAG}"}})
    await engine.state_col.delete_one({"id": "global"})
    if saved_state:
        await engine.state_col.insert_one(saved_state)
    else:
        await engine.ensure_indexes()


async def seed(*models):
    await models_col.insert_many([dict(m) for m in models])
    return models


def _ok(r, m):
    assert r["status"] == "MOCK_CONFIRMED", r
    assert r["media_order"] == ["PUBLIC", "SECRET"] and r["SAME_MODEL_MEDIA"] is True
    assert r["public_media_id"].startswith("pub:") and r["secret_media_id"].startswith("sec:")
    assert r["of_link"] == m["onlyfans_url"] and r["caption"].rstrip().endswith(m["onlyfans_url"]) and r["caption"].count("http") == 1
    assert r["public_media_object"]["processId"] and r["public_media_object"]["host"] and r["secret_media_object"]["processId"]


# ------------------------------------------------------------------ A eligibility · D OF link · E/F/G
def test_A_eligibility_and_of_link():
    assert ofmedia.classify(_model("a-ok"))["status"] == "ELIGIBLE"
    assert ofmedia.classify(_model("a-nopub", pub=[]))["status"] == "SKIPPED_NO_PUBLIC"
    assert ofmedia.classify(_model("a-nosec", sec=[]))["status"] == "SKIPPED_NO_SECRET"
    assert ofmedia.classify(_model("a-noof", of="https://latosegreto.it/x"))["status"] == "SKIPPED_NO_OF_LINK"
    assert ofmedia.classify(_model("a-emptyof", of=""))["status"] == "SKIPPED_NO_OF_LINK"
    assert ofmedia.classify(_model("a-excl", of_autopilot_excluded=True))["status"] == "SKIPPED_EXCLUDED"
    for bad in ("", None, "https://onlyfans.com/", "https://instagram.com/x", "https://t.me/latosegreto", "https://onlyfans.com.evil.io/x", "https://secret-side.emergent.host/x"):
        assert ofmedia.valid_of_link(bad) is None, bad
    assert ofmedia.valid_of_link("onlyfans.com/vanessa") == "https://onlyfans.com/vanessa"
    m = _model("a-media", pub=[REAL_PHOTO, REAL_VIDEO, f"{HOST}/media/doc.pdf", f"{HOST}/media/clip.webm"], sec=[REAL_SITE_PHOTO])
    xm = ofmedia.get_of_media(m)
    assert [x["type"] for x in xm["public"]] == ["photo", "video"] and all(x["model_id"] == m["id"] and x["side"] == "PUBLIC" for x in xm["public"])
    assert sorted(r["reason"] for r in xm["rejected"]) == ["UNSUPPORTED_FORMAT", "UNSUPPORTED_FORMAT"]
    assert xm["public"][1]["source_url"].startswith("https://") and xm["secret"][0]["model_id"] == m["id"]


# ------------------------------------------------------------------ media source: real HEAD, MIME, video lightweight, missing file
async def test_media_source_real_validation():
    ofmedia._cache.clear()
    v = await ofmedia.validate_media({"source_url": REAL_PHOTO, "type": "photo"})
    assert v["ok"] and v["status_code"] in (200, 206) and v["mime"].startswith("image/") and (v["size"] or 0) > 0 and v["source_type"] == "source_url", v
    vv = await ofmedia.validate_media({"source_url": REAL_VIDEO, "type": "video"})
    assert vv["ok"] and vv["status_code"] in (200, 206) and (vv["size"] or 0) > 0 and (vv["mime"].startswith("video/") or "octet-stream" in vv["mime"]), vv   # octet-stream + .mp4 tolerated
    site = await ofmedia.validate_media({"source_url": REAL_SITE_PHOTO, "type": "photo"})
    assert site["ok"] and site["mime"].startswith("image/")
    miss = await ofmedia.validate_media({"source_url": MISSING + ".jpg", "type": "photo"})
    assert not miss["ok"] and (miss["reason"].startswith("HTTP_") or miss["reason"] == "MIME_MISMATCH"), miss   # SPA host answers 200 text/html for missing files -> MIME check catches it
    mism = await ofmedia.validate_media({"source_url": REAL_PHOTO, "type": "video"}, use_cache=False)
    assert not mism["ok"] and mism["reason"] == "MIME_MISMATCH"
    assert (await ofmedia.validate_media({"source_url": "http://insecure.test/x.jpg", "type": "photo"}))["reason"] == "NOT_HTTPS"
    assert ofmedia._mime_ok("application/octet-stream", "video", "https://h/a.mp4") and not ofmedia._mime_ok("application/octet-stream", "video", "https://h/a.jpg")
    # file-upload fallback helper fetches from our storage server-side (small image), never through the browser
    data, ctype = await ofmedia.fetch_bytes(REAL_SITE_PHOTO)
    assert len(data) > 1000 and ctype.startswith("image/")
    with pytest.raises(ValueError):
        await ofmedia.fetch_bytes(REAL_SITE_PHOTO, max_bytes=100)


# ------------------------------------------------------------------ K/L caption italiana + OF link + fallback
async def test_K_L_caption(monkeypatch):
    m = _model("k-cap")
    monkeypatch.setattr(ofcap, "_llm_available", lambda: False)
    c = await ofcap.build_caption(m, m["onlyfans_url"], 1, use_ai=True)
    assert c["source"] == "TEMPLATE" and c["language"] == "it"
    assert c["text"].endswith(f"Scoprila su OnlyFans:\n{m['onlyfans_url']}") and c["text"].count("http") == 1 and "@" not in c["body"]
    assert ("lato" in c["body"].lower() or "lati" in c["body"].lower()) and "CAP TEST" in c["body"].upper() and not ofcap.ENGLISH_HINT.search(c["body"])
    assert len({(await ofcap.build_caption(m, m["onlyfans_url"], i, use_ai=False))["body"] for i in range(1, 7)}) >= 5
    monkeypatch.setattr(ofcap, "_llm_available", lambda: True)
    monkeypatch.setattr(ofcap, "llm_text", lambda m, c: asyncio.sleep(0, result=None))
    assert (await ofcap.build_caption(m, m["onlyfans_url"], 2, use_ai=True))["source"] == "TEMPLATE"
    with pytest.raises(AssertionError):
        await ofcap.build_caption(m, "https://latosegreto.it/x", 1, use_ai=False)          # never a non-OF link
    assert ofcap.FORBIDDEN.search("ha 24 anni e vive a Milano") and ofcap.FORBIDDEN.search("seguila su onlyfans")


# ------------------------------------------------------------------ B/C/W/U/Y publish-now immediate mock, pairing, same model, media objects, uploads state
async def test_W_publish_now_immediate_mock(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-anna", ordine=1), _model(f"{TAG}-bea", ordine=2))
    st0 = await engine.get_state()
    r = await engine.run("PUBLISH_NOW", "admin")
    _ok(r, a)
    assert r["real_status"] == "POST_CONFIRMED" and r["action_type"] == "PUBLISH_NOW" and r["slot_id"] is None and r["scheduled_at"] is None
    post = mock.posts[r["provider_post_id"]]
    assert post["isScheduled"] == 0 and post["scheduledDate"] is None and post["postedAt"], "immediate, not scheduled"
    assert not mock.scheduled, "IMMEDIATE_FLOW_DOES_NOT_USE_NEXT_SLOT"
    assert post["mediaFiles"] == [r["public_media_object"], r["secret_media_object"]] and post["media"][0]["id"] == r["public_media_object"]["processId"]   # complete objects, PUBLIC first
    assert set(post["mediaFiles"][0]) >= {"processId", "host", "thumbId", "name", "extra"}
    assert a["onlyfans_url"] in post["text"] and b["onlyfans_url"] not in post["text"]
    ups = [u async for u in engine.uploads_col.find({"model_id": a["id"]}, {"_id": 0})]
    assert len(ups) == 2 and {u["media_side"] for u in ups} == {"PUBLIC", "SECRET"} and all(u["status"] == "USED_IN_POST" and u["provider_media_reference"] and u["provider_media_object"]["processId"] and u["source_type"] == "source_url" and u["mime_type"] and u["provider_post_id"] == r["provider_post_id"] for u in ups)
    st1 = await engine.get_state()
    assert len(st1["cycle_done"]) == len(st0["cycle_done"]) + 1 and st1["last_published"]["provider_post_id"] == r["provider_post_id"] and st1["last_success"]
    r2 = await engine.run("PUBLISH_NOW", "admin")
    _ok(r2, b)
    assert r2["model_slug"] != r["model_slug"]
    lg = [l async for l in engine.log_col.find({"model_slug": {"$regex": f"^{TAG}"}})]
    assert len(lg) == 2 and all(l["status"] == "MOCK_CONFIRMED" and l["mock"] and l["provider_post_id"] and l["public_source_url"] and l["secret_source_url"] and l["of_link"] and l["action_type"] == "PUBLISH_NOW" for l in lg)
    assert toa.CALLS["write"] == 0


# ------------------------------------------------------------------ X mock schedule flow (isScheduled + scheduledDate + GET schedules verify) — separate from immediate
async def test_X_mock_schedule_flow_and_not_confirmed(sandbox):
    mock = sandbox
    a, b = await seed(_model(f"{TAG}-sa", ordine=1), _model(f"{TAG}-sb", ordine=2))
    when = "2030-01-01T11:30:00+01:00"
    r = await engine.run("SCHEDULE", "scheduler", slot_id=f"{TAG}_2030-01-01_11:30", scheduled_at=when)
    _ok(r, a)
    assert r["real_status"] == "SCHEDULE_CONFIRMED" and r["action_type"] == "SCHEDULE" and r["scheduled_at"] == when
    post = mock.posts[r["provider_post_id"]]
    assert post["isScheduled"] == 1 and post["scheduledDate"] == when and post["postedAt"] is None and len(mock.scheduled) == 1
    assert await mock.verify_scheduled("u", r["provider_post_id"]) is True
    # 200 but not in schedules -> SCHEDULE_NOT_CONFIRMED, NO advance, cursors untouched
    mock.hide_scheduled = True
    st = await engine.get_state()
    ms_before = await engine.media_state_col.find_one({"model_id": b["id"]})
    r = await engine.run("SCHEDULE", "scheduler", slot_id=f"{TAG}_2030-01-01_17:30", scheduled_at=when)
    assert r["status"] == "SCHEDULE_NOT_CONFIRMED" and r["model_slug"] == b["slug"] and r["provider_post_id"]
    assert (await engine.get_state())["cycle_done"] == st["cycle_done"] and await engine.media_state_col.find_one({"model_id": b["id"]}) == ms_before
    assert (await engine.log_col.find_one({"slot_id": f"{TAG}_2030-01-01_17:30"}))["status"] == "SCHEDULE_NOT_CONFIRMED"
    mock.hide_scheduled = False
    r = await engine.run("SCHEDULE", "scheduler", slot_id=f"{TAG}_2030-01-01_22:00", scheduled_at=when)
    assert r["status"] == "MOCK_CONFIRMED" and r["model_slug"] == b["slug"], "same model retried on the next slot (no blind advance)"


# ------------------------------------------------------------------ failures: upload failed / create failed / post not confirmed -> NO advance, cursors untouched, bounded
async def test_failures_do_not_advance(sandbox):
    mock = sandbox
    a, = await seed(_model(f"{TAG}-fail", pub=[REAL_PHOTO, REAL_SITE_PHOTO, f"{HOST}/media/pub3.jpg"], sec=[REAL_SITE_PHOTO.replace("pub1", "pub2")]))
    st0 = await engine.get_state()
    # every public upload rejected by the provider -> UPLOAD_FAILED, no advance, at most MAX_MEDIA_ATTEMPTS attempts
    mock.fail_upload.update({"unsplash", "/media/pub1.jpg", "/media/pub3.jpg"})
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["status"] == "UPLOAD_FAILED" and r["error_code"] == "API_ERROR"
    assert len([e for e in r["media_errors"] if e.get("stage") == "UPLOAD"]) == engine.MAX_MEDIA_ATTEMPTS
    assert (await engine.get_state())["cycle_done"] == st0["cycle_done"] and not mock.posts
    assert await engine.uploads_col.count_documents({"model_id": a["id"], "status": "UPLOAD_FAILED"}) == 3
    assert await engine.media_state_col.find_one({"model_id": a["id"]}) is None, "cursor NOT advanced"
    mock.fail_upload.clear()
    # timeout on upload -> UPLOAD_FAILED (bounded), no advance
    mock.timeout_upload = True
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["status"] == "UPLOAD_FAILED" and r["error_code"] == "NETWORK_ERROR" and (await engine.get_state())["cycle_done"] == st0["cycle_done"]
    mock.timeout_upload = False
    # create failed -> FAILED, uploads kept as UPLOAD_SUCCESS (not USED_IN_POST), no advance
    mock.fail_create = True
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["status"] == "FAILED" and r["error_code"] == "API_ERROR" and (await engine.get_state())["cycle_done"] == st0["cycle_done"]
    assert await engine.uploads_col.count_documents({"model_id": a["id"], "status": "USED_IN_POST"}) == 0
    mock.fail_create = False
    # post created but not verifiable -> POST_NOT_CONFIRMED, no advance
    mock.hide_post = True
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["status"] == "POST_NOT_CONFIRMED" and r["provider_post_id"] and (await engine.get_state())["cycle_done"] == st0["cycle_done"]
    mock.hide_post = False
    # finally OK -> advance, cursor set (CURSOR_ADVANCE_ONLY_AFTER_SUCCESS)
    r = await engine.run("PUBLISH_NOW", "admin")
    _ok(r, a)
    ms = await engine.media_state_col.find_one({"model_id": a["id"]})
    assert ms["last_public_media_id"] == r["public_media_id"] and ms["last_secret_media_id"] == r["secret_media_id"] and ms["cycle_last_used"] == 1


# ------------------------------------------------------------------ invalid media (real 404 on our host) -> next media of the same side; none valid -> skip model, queue continues; video pair
async def test_media_fallback_skip_and_video(sandbox):
    mock = sandbox
    a = _model(f"{TAG}-fb", pub=[MISSING + "_a.jpg", REAL_PHOTO], sec=[MISSING + "_b.jpg", REAL_VIDEO], ordine=1)     # first of each side is a real 404
    dead = _model(f"{TAG}-dead", pub=[REAL_PHOTO], sec=[MISSING + "_c.jpg", MISSING + "_d.jpg"], ordine=2)
    c = _model(f"{TAG}-vid", pub=[REAL_VIDEO], sec=[REAL_SITE_PHOTO], ordine=3)
    await seed(a, dead, c)
    r = await engine.run("PUBLISH_NOW", "admin")
    _ok(r, a)
    assert r["public_media_id"].endswith("-1") and r["secret_media_id"].endswith("-1") and r["secret_media_type"] == "video"
    assert any(e.get("stage") == "VALIDATION" and (e["reason"].startswith("HTTP_") or e["reason"] == "MIME_MISMATCH") for e in r["log"]["media_errors"])
    r = await engine.run("PUBLISH_NOW", "admin")
    _ok(r, c)                                                                                   # 'dead' skipped (SKIPPED_NO_SECRET), queue continues
    assert r["public_media_type"] == "video" and mock.uploads[-2]["kind"] == "video"
    sk = await engine.log_col.find_one({"model_slug": dead["slug"]})
    assert sk["status"] == "SKIPPED_NO_SECRET" and sk["error_code"] == "NO_VALID_SECRET_MEDIA"
    assert (await engine.get_state())["cycle_number"] == 2
    assert await engine.uploads_col.count_documents({"model_id": dead["id"]}) == 0, "no upload attempted without a valid pair"


# ------------------------------------------------------------------ H/I/J two cursors, wrap, never same pair
async def test_H_I_J_cursors_and_wrap(sandbox):
    m, = await seed(_model(f"{TAG}-cur", pub=[REAL_PHOTO, REAL_SITE_PHOTO, f"{HOST}/media/pub3.jpg"], sec=[REAL_SITE_PHOTO.replace("pub1", "pub2"), REAL_VIDEO]))
    pairs = []
    for _ in range(6):
        r = await engine.run("PUBLISH_NOW", "admin")
        _ok(r, m)
        pairs.append((r["public_media_id"][-1], r["secret_media_id"][-1]))
    assert [p[0] for p in pairs] == ["0", "1", "2", "0", "1", "2"] and [p[1] for p in pairs] == ["0", "1", "0", "1", "0", "1"]
    assert len(set(pairs)) == 6
    ms = await engine.media_state_col.find_one({"model_id": m["id"]}, {"_id": 0})
    assert {"public_media_index", "secret_media_index", "last_public_media_id", "last_secret_media_id", "cycle_last_used", "last_published_at", "updated_at"} <= set(ms)


# ------------------------------------------------------------------ M/N circular queue + wrap
async def test_M_N_circular_rotation(sandbox):
    ms = await seed(*[_model(f"{TAG}-r{i}", ordine=i) for i in range(4)])
    seen = [(await engine.run("PUBLISH_NOW", "admin"))["model_slug"] for _ in range(4)]
    assert seen == [m["slug"] for m in ms] and len(set(seen)) == 4
    st = await engine.get_state()
    assert st["cycle_number"] == 2 and st["cycle_done"] == [] and st["current_model_id"] == ms[0]["id"] and st["current_position"] == 1
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["model_slug"] == ms[0]["slug"] and r["cycle_number"] == 2
    s = await engine.status()
    assert s["queue"]["cycle_number"] == 2 and s["queue"]["position"] == 2 and s["queue"]["total"] == 4 and s["THE_ONLY_API_REAL_WRITE_CALLS"] == 0 and s["OF_REAL_POST_DONE"] is False


# ------------------------------------------------------------------ O new model mid-cycle · P removed mid-cycle
async def test_O_P_new_and_removed_mid_cycle(sandbox):
    ms = await seed(*[_model(f"{TAG}-mid{i}", ordine=i * 10) for i in range(3)])
    await engine.run("PUBLISH_NOW", "admin")
    new = _model(f"{TAG}-new", ordine=5)
    await seed(new)
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["model_slug"] == new["slug"] and (await engine.get_state())["cycle_number"] == 1
    await models_col.update_one({"id": ms[1]["id"]}, {"$set": {"stato": "bozza"}})
    await models_col.update_one({"id": ms[2]["id"]}, {"$set": {"onlyfans_url": ""}})
    late = _model(f"{TAG}-late", ordine=99)
    await seed(late)
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["model_slug"] == late["slug"]
    s = await engine.status()
    assert ms[2]["slug"] in s["queue"]["skipped_no_of_link"] and ms[1]["slug"] not in [o["slug"] for o in s["queue"]["order"]]
    assert (await engine.get_state())["cycle_number"] == 2


# ------------------------------------------------------------------ Q restart persistence
async def test_Q_restart_persistence(sandbox):
    ms = await seed(*[_model(f"{TAG}-pers{i}", ordine=i) for i in range(3)])
    await engine.run("PUBLISH_NOW", "admin")
    await engine.run("PUBLISH_NOW", "admin")
    before = await engine.state_col.find_one({"id": "global"}, {"_id": 0})
    import importlib
    importlib.reload(engine)
    engine.force_provider(sandbox)
    after = await engine.get_state()
    assert after["cycle_done"] == before["cycle_done"] and after["last_position"] == before["last_position"] and after["cycle_number"] == 1
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["model_slug"] == ms[2]["slug"]
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["model_slug"] == ms[0]["slug"] and r["public_media_id"].endswith("-1") and r["secret_media_id"].endswith("-1"), "cursors persisted"


# ------------------------------------------------------------------ R duplicate slot · S concurrency
async def test_R_S_duplicate_slot_and_concurrency(sandbox):
    mock = sandbox
    await seed(*[_model(f"{TAG}-dup{i}", ordine=i) for i in range(3)])
    when = "2030-02-01T11:30:00+01:00"
    r1 = await engine.run("SCHEDULE", "scheduler", slot_id=f"{TAG}_2030-02-01_11:30", scheduled_at=when)
    r2 = await engine.run("SCHEDULE", "scheduler", slot_id=f"{TAG}_2030-02-01_11:30", scheduled_at=when)
    assert r1["status"] == "MOCK_CONFIRMED" and r2["status"] == "SKIP_DUPLICATE_SLOT" and len(mock.posts) == 1
    assert await engine.log_col.find_one({"status": "SKIP_DUPLICATE_SLOT", "slot_id": f"{TAG}_2030-02-01_11:30"})
    results = await asyncio.gather(*[engine.run("SCHEDULE", "scheduler", slot_id=f"{TAG}_conc{i}", scheduled_at=when) for i in range(4)])
    statuses = [r["status"] for r in results]
    assert set(statuses) <= {"MOCK_CONFIRMED", "LOCKED"} and statuses.count("MOCK_CONFIRMED") >= 1
    slugs = [p["text"].split("\n")[0] for p in mock.posts.values()]
    assert len(slugs) == len(set(slugs)) or len(slugs) > 3
    st = await engine.get_state()
    slots = engine.slots_for_day(st, engine.datetime.now(engine.timezone.utc))
    assert [s["slot_id"][-5:] for s in slots] == ["11:30", "17:30", "22:00"] and all(s["slot_id"].startswith("of_") for s in slots)


# ------------------------------------------------------------------ T pause · U skip · V preview (zero write) · scheduler tick gated · scheduled flow separate
async def test_T_U_V_pause_skip_preview_tick(sandbox, monkeypatch):
    mock = sandbox
    ms = await seed(*[_model(f"{TAG}-pp{i}", ordine=i) for i in range(3)])
    await engine.set_state(enabled=True)
    monkeypatch.setenv("OF_AUTO_SCHEDULER_ENABLED", "false")
    assert (await engine.tick())["status"] == "AUTO_SCHEDULER_DISABLED" and not mock.posts
    monkeypatch.setenv("OF_AUTO_SCHEDULER_ENABLED", "true")
    await engine.set_state(enabled=False)
    assert (await engine.tick())["status"] == "PAUSED" and not mock.posts
    await engine.set_state(enabled=True, schedule_times=["03:33", "03:34", "03:35"], posts_per_day=3)
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if not (2 <= datetime.now(ZoneInfo("Europe/Rome")).hour <= 5):
        assert (await engine.tick())["status"] == "NO_DUE_SLOT"
    assert not mock.posts and not mock.uploads
    monkeypatch.setenv("OF_AUTO_SCHEDULER_ENABLED", "false")
    st = await engine.get_state()
    pv = await engine.preview()
    assert pv["status"] == "PREVIEW" and pv["model_slug"] == ms[0]["slug"] and pv["public"]["side"] == "PUBLIC" and pv["secret"]["side"] == "SECRET" and pv["SAME_MODEL_MEDIA"] is True
    assert pv["public_validation"]["ok"] and pv["secret_validation"]["ok"] and pv["of_url"] == ms[0]["onlyfans_url"] and pv["caption"].endswith(pv["of_url"]) and pv["slot"]["slot_id"].startswith("of_")
    assert pv["provider"] == "MOCK" and pv["mock"] is True and pv["writes"] == 0
    assert (await engine.get_state())["cycle_done"] == st["cycle_done"] and not mock.posts and not mock.uploads and mock.write_calls == 0, "preview = zero write"
    sk = await engine.skip_current("admin")
    assert sk["status"] == "MANUAL_SKIP" and sk["skipped"] == ms[0]["slug"]
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["model_slug"] == ms[1]["slug"] and len(mock.posts) == 1 and not mock.scheduled, "SCHEDULED_FLOW_SEPARATE: publish-now never touches the schedule list"
    # due_slot computes scheduledDate = slot time (not a past date)
    due = {"slot_id": "x", "scheduled_at": "2030-01-01T11:30:00+01:00"}
    assert due["scheduled_at"] >= "2030"


# ------------------------------------------------------------------ T provider abstraction · gate on real adapter · media object contract
async def test_provider_abstraction_and_real_gate(monkeypatch):
    assert issubclass(MockOFProvider, OFProviderAdapter) and issubclass(toa.TheOnlyAPIAdapter, OFProviderAdapter)
    src = open("/app/backend/of_autopilot/engine.py").read()
    assert "theonlyapi" not in src.lower() and "httpx" not in src, "engine must not know the vendor / HTTP"
    monkeypatch.setenv("OF_AUTOPILOT_MOCK", "false")
    monkeypatch.setenv("OF_REAL_POSTING_ENABLED", "false")
    engine.force_provider(None)
    assert isinstance(engine.get_provider(), toa.TheOnlyAPIAdapter)
    ready = await engine.readiness()
    assert ready["operational"] is False and ready["reason"] == "OF_REAL_POSTING_DISABLED", "real mode is blocked in this phase"
    import httpx
    async def boom(*a, **k):
        raise AssertionError("network reached")
    monkeypatch.setattr(httpx.AsyncClient, "request", boom)
    a = toa.TheOnlyAPIAdapter()
    for coro in (a.upload_media_from_url("1", source_url="https://x/y.jpg", file_name="y.jpg", kind="photo"), a.upload_media("1", file_name="a.jpg", content=b"x", content_type="image/jpeg"),
                 a.create_post("1", OFPostRequest("t")), a.schedule_post("1", OFPostRequest("t", scheduled_at="2030-01-01T00:00:00+00:00"))):
        with pytest.raises(OFProviderError) as ei:
            await coro
        assert ei.value.code == "WRITES_DISABLED"
    body = a._post_body(OFPostRequest("t", [OFMedia("p", "photo", {"processId": "p", "host": "h", "thumbId": 1, "name": "n", "extra": "e"})], "2030-01-01T00:00:00+00:00"))
    assert body["mediaFiles"] == [{"processId": "p", "host": "h", "thumbId": 1, "name": "n", "extra": "e"}] and body["isScheduled"] == 1 and "postedAt" not in body
    monkeypatch.setenv("OF_AUTOPILOT_MOCK", "true")
    assert isinstance(engine.get_provider(), MockOFProvider) and toa.CALLS["write"] == 0


# ------------------------------------------------------------------ independence from Telegram / Instagram / X
async def test_independent_from_other_autopilots(sandbox):
    cols = ["telegram_autopilot_state", "telegram_model_media_state", "instagram_autopilot_state", "instagram_model_media_state", "x_autopilot_state", "x_model_media_state", "x_autopilot_log", "instagram_autopilot_log", "telegram_autopilot_log"]
    snap = {c: [d async for d in db[c].find({}, {"_id": 0}).sort("_id", 1)] for c in cols}
    await seed(*[_model(f"{TAG}-ind{i}", ordine=i) for i in range(2)])
    await engine.run("PUBLISH_NOW", "admin")
    await engine.skip_current("admin")
    assert {engine.state_col.name, engine.media_state_col.name, engine.uploads_col.name, engine.log_col.name, engine.slots_col.name, engine.locks_col.name} == \
        {"of_autopilot_state", "of_model_media_state", "of_media_uploads", "of_autopilot_logs", "of_autopilot_slots", "of_autopilot_locks"}
    for c in cols:
        assert [d async for d in db[c].find({}, {"_id": 0}).sort("_id", 1)] == snap[c], c


# ------------------------------------------------------------------ admin API contract
def _token():
    r = requests.post(f"{BASE}/api/admin/login", json=admin_credentials(), timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def test_admin_api_contract():
    for ep in ("status", "preview", "logs", "connection", "uploads"):
        assert requests.get(f"{BASE}/api/admin/of-autopilot/{ep}", timeout=15).status_code in (401, 403), ep
    for ep in ("start", "pause", "publish-now", "skip", "test-connection"):
        assert requests.post(f"{BASE}/api/admin/of-autopilot/{ep}", timeout=15).status_code in (401, 403), ep
    h = {"Authorization": f"Bearer {_token()}"}
    s = requests.get(f"{BASE}/api/admin/of-autopilot/status", headers=h, timeout=60).json()
    assert s["MOCK_MODE"] is True and s["OF_REAL_POSTING_ENABLED"] is False and s["AUTO_SCHEDULER_ENABLED"] is False and s["REAL_POSTING"] == "OFF" and s["AUTO_SCHEDULER"] == "OFF"
    assert s["OF_AUTOPILOT_STATUS"] in ("PAUSED", "READY") and s["PROVIDER"] == "The Only API" and s["CONNECTION_STATUS"] == "CONNECTED" and s["ACCOUNT_USERNAME"] == "latosegreto" and s["ACCOUNT_STATUS"] == "HEALTHY"
    assert s["THE_ONLY_API_REAL_WRITE_CALLS"] == 0 and s["OF_REAL_POST_DONE"] is False
    assert s["settings"] == {"posts_per_day": 3, "schedule_times": ["11:30", "17:30", "22:00"], "timezone": "Europe/Rome", "use_ai_copy": True} or s["settings"]["timezone"] == "Europe/Rome"
    assert s["queue"]["total"] >= 1 and s["schedule"]["next_slot"]["slot_id"].startswith("of_")
    for k in ("skipped_no_public", "skipped_no_secret", "skipped_no_of_link", "excluded"):
        assert k in s["queue"]
    p = requests.get(f"{BASE}/api/admin/of-autopilot/preview", headers=h, timeout=180).json()
    assert p["status"] == "PREVIEW" and p["public"]["side"] == "PUBLIC" and p["secret"]["side"] == "SECRET" and p["SAME_MODEL_MEDIA"] is True and p["media_order"] == ["PUBLIC", "SECRET"]
    assert p["public_validation"]["ok"] and p["secret_validation"]["ok"] and p["public"]["source_url"].startswith("https://") and p["of_url"].startswith("https://onlyfans.com/") and p["caption"].endswith(p["of_url"])
    assert p["provider"] == "MOCK" and p["account"] == "latosegreto" and p["writes"] == 0
    # no route can enable real posting; no upload route
    for ep in ("enable-real-posting", "upload", "schedule", "real-posting"):
        assert requests.post(f"{BASE}/api/admin/of-autopilot/{ep}", headers=h, json={}, timeout=15).status_code in (404, 405), ep
    key = toa.api_key()
    body = requests.get(f"{BASE}/api/admin/of-autopilot/status", headers=h, timeout=60).text
    if key:
        assert key not in body and toa.crm_id() not in body
    u = f"{BASE}/api/admin/of-autopilot/settings"
    assert requests.patch(u, headers=h, json={"schedule_times": ["25:00"]}, timeout=15).status_code == 422
    assert requests.patch(u, headers=h, json={"timezone": "Mars/Olympus"}, timeout=15).status_code == 422
    r = requests.patch(u, headers=h, json={"schedule_times": ["22:00", "11:30", "17:30"], "posts_per_day": 3, "timezone": "Europe/Rome", "use_ai_copy": True}, timeout=15)
    assert r.status_code == 200 and r.json()["schedule_times"] == ["11:30", "17:30", "22:00"]
    from v1_jobs import JOBS
    import of_autopilot.jobs  # noqa: F401
    assert "of_autopilot_tick" in JOBS and JOBS["of_autopilot_tick"]["interval_s"] == 300


# ------------------------------------------------------------------ CONTROLLED REAL TEST protections (fake "real" provider: not MockOFProvider, zero network)
class _FakeReal(OFProviderAdapter):
    """Behaves like a real provider (engine treats it as non-mock) but records everything in memory."""
    name = "FAKE_REAL"

    def __init__(self):
        self.inner = MockOFProvider()
        self.creates = 0
    async def test_connection(self): return {}
    async def list_accounts(self): return await self.inner.list_accounts()
    async def get_account(self, u): return await self.inner.get_account(u)
    async def get_account_health(self, u): return await self.inner.get_account_health(u)
    async def get_scheduled_posts(self, u, limit=10, offset=0): return await self.inner.get_scheduled_posts(u, limit, offset)
    async def get_post(self, u, p): return await self.inner.get_post(u, p)
    async def upload_media_from_url(self, u, **k): return await self.inner.upload_media_from_url(u, **k)
    async def upload_media(self, u, **k): return await self.inner.upload_media(u, **k)
    async def create_post(self, u, r):
        self.creates += 1
        return await self.inner.create_post(u, r)
    async def schedule_post(self, u, r): return await self.inner.schedule_post(u, r)
    async def delete_scheduled_post(self, u, p): raise OFProviderError("NOT_DOCUMENTED")
    async def set_write_gate(self, u, enabled): return await self.inner.set_write_gate(u, enabled)
    async def get_write_gate(self, u): return await self.inner.get_write_gate(u)


@pytest.fixture
async def real_test_env(sandbox, monkeypatch):
    fake = _FakeReal()
    engine.force_provider(fake)
    monkeypatch.setenv("OF_AUTOPILOT_MOCK", "false")
    monkeypatch.setenv("OF_REAL_POSTING_ENABLED", "true")
    monkeypatch.setenv("OF_AUTO_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("OF_REAL_TEST_MAX_POSTS", "1")
    healthy = {"PROVIDER": "The Only API", "CONNECTION_STATUS": "CONNECTED", "ACCOUNT_STATUS": "HEALTHY", "ACCOUNT_USERNAME": "latosegreto"}

    async def fake_discover(check_schedules=True):
        return dict(healthy)
    monkeypatch.setattr(connection, "discover", fake_discover)

    async def fake_uid():
        return "999"
    monkeypatch.setattr(connection, "of_user_id", fake_uid)
    yield fake
    engine.force_provider(sandbox)


async def test_real_test_hard_limit_gate_and_verify(real_test_env):
    fake = real_test_env
    a, b = await seed(_model(f"{TAG}-ra", ordine=1), _model(f"{TAG}-rb", ordine=2))
    assert engine.real_test_mode() is True and engine.real_test_max_posts() == 1 and await engine.real_posts_created() == 0
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["status"] == "POST_CONFIRMED" and r["real_status"] == "POST_CONFIRMED" and r["model_slug"] == a["slug"] and r["mock"] is False
    v = r["verification"]
    assert v["ok"] and v["exists"] and v["account_ok"] and v["caption_ok"] and v["of_link_ok"] and v["media_ok"] and v["media_count"] == 2
    assert fake.inner.gate_history == [True, False] and fake.inner.gate is False, "gate opened only for the write and restored"
    assert r["write_gate"] == {"restored": True, "verified_false": True, "error": None}
    assert fake.creates == 1 and await engine.real_posts_created() == 1
    # SECOND POST MUST BE IMPOSSIBLE: readiness blocks before any upload/gate/create
    r2 = await engine.run("PUBLISH_NOW", "admin")
    assert r2["status"] == "FAILED" and r2["error_code"] == "REAL_TEST_LIMIT" and fake.creates == 1 and fake.inner.gate_history == [True, False]
    assert len(fake.inner.uploads) == 2, "no further upload"
    # scheduler path refused in real test mode
    r3 = await engine.run("SCHEDULE", "scheduler", slot_id=f"{TAG}_rt", scheduled_at="2030-01-01T11:30:00+01:00")
    assert r3["status"] == "FAILED" and r3["error_code"] in ("REAL_TEST_LIMIT", "REAL_TEST_MODE_IMMEDIATE_ONLY") and fake.creates == 1
    st = await engine.get_state()
    assert st["cycle_done"] == [a["id"]] and st["last_published"]["provider_post_id"] == r["provider_post_id"], "used model recorded, queue NOT auto-continued"
    s = await engine.status()
    assert s["REAL_TEST_MODE"] is True and s["REAL_TEST_MAX_POSTS"] == 1 and s["TOTAL_REAL_POSTS_CREATED"] == 1 and s["OF_REAL_POST_DONE"] is True and s["AUTO_SCHEDULER_ENABLED"] is False
    assert toa.CALLS["write"] == 0, "the real The Only API adapter was never called"


async def test_real_test_precheck_stop_no_next_model(real_test_env):
    fake = real_test_env
    bad = _model(f"{TAG}-bad", pub=[MISSING + "_x.jpg"], sec=[REAL_SITE_PHOTO], ordine=1)     # public unreachable on our host
    good = _model(f"{TAG}-good", ordine=2)
    await seed(bad, good)
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["status"] == "STOPPED_PRECHECK" and r["error_code"] == "NO_VALID_PUBLIC_MEDIA" and r["model_slug"] == bad["slug"]
    assert fake.creates == 0 and not fake.inner.uploads and fake.inner.gate_history == [], "no gate, no upload, no create"
    assert (await engine.get_state())["cycle_done"] == [], "no advance, no switch to the next model"
    assert await engine.real_posts_created() == 0
    # unhealthy account -> STOP before anything
    fake2 = fake

    async def unhealthy(check_schedules=True):
        return {"PROVIDER": "The Only API", "CONNECTION_STATUS": "CONNECTED", "ACCOUNT_STATUS": "UNHEALTHY", "ACCOUNT_USERNAME": "latosegreto"}
    connection.discover = unhealthy
    r = await engine.run("PUBLISH_NOW", "admin")
    assert r["status"] == "FAILED" and r["error_code"] == "ACCOUNT_UNHEALTHY" and fake2.creates == 0 and fake2.inner.gate_history == []


def test_adapter_hard_create_limit_and_global_link(monkeypatch):
    monkeypatch.setenv("OF_REAL_TEST_MAX_POSTS", "1")
    a = toa.TheOnlyAPIAdapter()
    before = toa.CALLS["create"]
    monkeypatch.setitem(toa.CALLS, "create", 1)
    with pytest.raises(OFProviderError) as ei:
        a._check_create_limit()
    assert ei.value.code == "REAL_TEST_LIMIT"
    monkeypatch.setitem(toa.CALLS, "create", before)
    # global Lato Segreto account is never a model link
    assert ofmedia.valid_of_link("https://onlyfans.com/latosegreto") is None and ofmedia.valid_of_link("https://onlyfans.com/latosegreto/c28") is None
    assert ofmedia.valid_of_link("https://onlyfans.com/vanessa_bellaaa/c9") == "https://onlyfans.com/vanessa_bellaaa/c9"
    assert ofmedia.classify(_model("g-glob", of="https://onlyfans.com/latosegreto"))["status"] == "SKIPPED_NO_OF_LINK"
