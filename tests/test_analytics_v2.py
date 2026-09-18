"""Admin Analytics v2 — backend aggregation endpoints (routes_analytics_v2.py) + batched ingestion (/api/track/batch).

Guarantees:
  * every admin endpoint is admin-only (401 without token)
  * empty period -> zeros / None, never a division by zero or a 500
  * unknown event names, legacy events without optional fields (session_id, visit_id, meta, model_slug) are tolerated
  * common schema fields (visit_id, entry_source, mode, cta_type, slot, to_model, input) drive the new metrics
  * closed funnel per visit with exact drop-off; paths; device compare; video per slot; engaged/scroll
  * raw log never leaks full ids; batch ingestion strips sensitive meta keys and preserves client order
Test events use a unique campagna marker and are deleted at the end (real data untouched).

Run: cd /app && python -m pytest tests/test_analytics_v2.py -q
"""
import os, sys, uuid, time, requests, pytest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

B = os.environ.get("TEST_BACKEND", "http://localhost:8001")
V2 = f"{B}/api/admin/analytics/v2"
ADMIN = {}
for _line in open("/app/memory/test_credentials.md"):          # never hard-code credentials in tests
    if "email" in _line.lower() and "@" in _line and "email" not in ADMIN:
        ADMIN["email"] = _line.split(":")[-1].strip().strip("`* ")
    if "password" in _line.lower() and "password" not in ADMIN and ":" in _line:
        ADMIN["password"] = _line.split(":", 1)[-1].strip().strip("`* ")

pytestmark = pytest.mark.anyio
MARK = f"zztest-an2-{uuid.uuid4().hex[:8]}"
SLUG = f"zztest-model-{uuid.uuid4().hex[:6]}"
OTHER = f"zztest-other-{uuid.uuid4().hex[:6]}"
VIS_A, VIS_B, VIS_C = (f"zztest-visitor-{uuid.uuid4().hex}" for _ in range(3))
VA, VB, VC = (f"zztest-visit-{uuid.uuid4().hex}" for _ in range(3))


def H():
    tok = requests.post(f"{B}/api/admin/login", json=ADMIN, timeout=20).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _ts(minutes_ago=5):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def ev(tipo, visit, visitor, i, **kw):
    d = {"tipo": tipo, "visit_id": visit, "visitor_id": visitor, "session_id": visitor, "campagna": MARK, "device": "mobile", "seq": i, "timestamp": _ts(60 - i), "id": str(uuid.uuid4())}
    d.update(kw)
    return d


@pytest.fixture(scope="module", autouse=True)
async def fixtures():
    from database import events_col
    A = lambda t, i, **kw: ev(t, VA, VIS_A, i, **kw)  # noqa: E731
    Bv = lambda t, i, **kw: ev(t, VB, VIS_B, i, device="desktop", **kw)  # noqa: E731
    docs = [
        # VISIT A (mobile): home -> card -> profile (home_card) -> video -> secret -> cta imp -> cta click -> of ; swipe by button to OTHER
        A("home_view", 1, mode="public"),
        A("home_model_card_impression", 2, model_slug=SLUG, placement="home", mode="public"),
        A("home_model_card_click", 3, model_slug=SLUG, placement="home", mode="public"),
        A("page_view", 4, model_slug=SLUG, entry_source="home_card", profile_pos=1, mode="public", source="instagram"),
        A("video_impression", 5, model_slug=SLUG, slot=2, mode="secret", entry_source="home_card"),
        A("video_start", 6, model_slug=SLUG, slot=2, mode="secret", entry_source="home_card"),
        A("video_50", 7, model_slug=SLUG, slot=2, mode="secret", entry_source="home_card"),
        A("secret_activate", 8, model_slug=SLUG, mode="secret", valore=12, entry_source="home_card"),
        A("cta_impression", 9, model_slug=SLUG, mode="secret", cta_type="gallery", cta_source="of_click_gallery", entry_source="home_card"),
        A("cta_click", 10, model_slug=SLUG, mode="secret", cta_type="gallery", cta_source="of_click_gallery", entry_source="home_card", valore=40),
        A("of_click", 11, model_slug=SLUG, mode="secret", cta_type="gallery", cta_source="of_click_gallery", entry_source="home_card", meta={"swipes": 0, "profiles_seen": 1, "last_nav_input": None}),
        A("profile_nav_next_click", 12, model_slug=SLUG, from_model=SLUG, to_model=OTHER, input="button", mode="secret", entry_source="home_card"),
        A("page_view", 13, model_slug=OTHER, entry_source="swipe_button", profile_pos=2, mode="secret"),
        A("profile_engaged", 14, model_slug=SLUG, valore=45, meta={"public_s": 10, "secret_s": 35, "max_scroll": 75}),
        A("profile_scroll_50", 15, model_slug=SLUG, valore=50, mode="secret"),
        # VISIT B (desktop): direct profile, secret, no CTA seen, OF click anyway (open funnel != closed funnel)
        Bv("page_view", 1, model_slug=SLUG, entry_source="direct_profile", profile_pos=1, mode="public"),
        Bv("secret_activate", 2, model_slug=SLUG, mode="secret", valore=5),
        Bv("of_click", 3, model_slug=SLUG, mode="secret", cta_type="timed", cta_source="of_click_timed", meta={"swipes": 2, "profiles_seen": 3, "last_nav_input": "gesture"}),
        Bv("of_global_marquee_impression", 4, model_slug=SLUG, placement="profile", mode="secret"),
        Bv("of_global_marquee_profile_click", 5, model_slug=SLUG, placement="profile", mode="secret", meta={"mode": "SECRET"}),
        Bv("social_click_instagram", 6, model_slug=SLUG, platform="instagram", cta_source="instagram", mode="secret"),
        Bv("profile_swipe_next", 7, model_slug=OTHER, from_model=OTHER, to_model=SLUG, input="gesture", mode="public"),
        # legacy / dirty: unknown event, no ids, non numeric valore, legacy meta.to swipe
        {"tipo": "evento_futuro_sconosciuto", "campagna": MARK, "timestamp": _ts(3), "id": str(uuid.uuid4())},
        {"tipo": "visit", "campagna": MARK, "timestamp": _ts(2), "id": str(uuid.uuid4())},
        {"tipo": "secret_time", "model_slug": SLUG, "session_id": VIS_C, "campagna": MARK, "valore": "x", "timestamp": _ts(2), "id": str(uuid.uuid4())},
        {"tipo": "profile_swipe_previous", "model_slug": OTHER, "session_id": VIS_C, "campagna": MARK, "meta": {"to": SLUG}, "timestamp": _ts(1), "id": str(uuid.uuid4())},
    ]
    await events_col.insert_many(docs)
    yield
    await events_col.delete_many({"campagna": MARK})
    await events_col.delete_many({"tipo": {"$regex": "^zz_"}})


F = {"range_key": "7g", "campagna": MARK}


def test_admin_only():
    for path in ("summary", "models", f"model/{SLUG}", "timeseries", "events", "filters", "export.csv", "compare?slugs=a", f"visit/{VA}"):
        r = requests.get(f"{V2}/{path}", params=F, timeout=20)
        assert r.status_code == 401, path


def test_summary_visits_visitors_and_funnel():
    s = requests.get(f"{V2}/summary", params=F, headers=H(), timeout=30).json()
    sc = s["scorecard"]
    assert sc["eventi"] == 26
    assert sc["visite"] == 3            # VA, VB + legacy VIS_C session (no visit_id)
    assert sc["visitatori"] == 3
    assert sc["profili_aperti"] == 3 and sc["visite_con_profilo"] == 2
    assert sc["secret_attivazioni"] == 2 and sc["secret_rate"] == 100.0
    assert sc["cta_impressions"] == 1 and sc["cta_click"] == 1 and sc["ctr_cta"] == 100.0
    assert sc["of_click_personali"] == 2 and sc["of_global_impressions"] == 1 and sc["of_click_globale"] == 1 and sc["ctr_of_globale"] == 100.0
    assert sc["social_click"] == 1 and sc["swipe"] == 3 and sc["video_start"] == 1
    assert sc["engaged_medio_s"] == 45.0 and sc["secret_engaged_medio_s"] == 35.0 and sc["scroll_medio_pct"] == 75.0
    # closed funnel: B has OF without CTA impression -> counted raw, not closed
    f = {x["key"]: x for x in s["funnel"]}
    assert f["view"]["n"] == 2 and f["engaged"]["n"] == 2 and f["secret"]["n"] == 2
    assert f["cta_imp"]["n"] == 1 and f["cta_click"]["n"] == 1 and f["of"]["n"] == 1 and f["of"]["n_raw"] == 2
    assert f["cta_imp"]["prosegue_pct"] == 50.0 and f["cta_imp"]["abbandona_pct"] == 50.0
    # unknown events are surfaced and flagged
    te = {x["evento"]: x for x in s["top_events"]}
    assert te["evento_futuro_sconosciuto"]["noto"] is False and te["page_view"]["noto"] is True
    # OF attribution
    assert s["onlyfans"]["personali"]["dopo_swipe"] == 1 and s["onlyfans"]["personali"]["dopo_gesture"] == 1 and s["onlyfans"]["personali"]["profili_medi_prima_del_click"] == 2.0
    assert s["onlyfans"]["globale"]["per_modalita"][0]["key"] == "SECRET"
    assert isinstance(s["not_available"], list) and s["not_available"]


def test_entry_sources_paths_devices_video_cta():
    s = requests.get(f"{V2}/summary", params=F, headers=H(), timeout=30).json()
    es = {r["entry_source"]: r for r in s["entry_sources"]}
    assert es["home_card"]["profili"] == 1 and es["home_card"]["of_click"] == 1 and es["home_card"]["ctr_of"] == 100.0
    assert es["direct_profile"]["profili"] == 1 and es["swipe_button"]["profili"] == 1
    paths = {p["percorso"]: p for p in s["percorsi"]["items"]}
    assert f"HOME → CARD → {SLUG.upper()} → SECRET → OF → SWIPE ‹› → {OTHER.upper()}" in paths
    assert paths[f"HOME → CARD → {SLUG.upper()} → SECRET → OF → SWIPE ‹› → {OTHER.upper()}"]["of"] == 1
    dc = {d["device"]: d for d in s["device_compare"]}
    assert dc["mobile"]["of_click"] == 1 and dc["desktop"]["of_click"] == 1 and dc["desktop"]["of_global_click"] == 1 and dc["mobile"]["engaged_medio_s"] == 45.0
    vs = {(v["slot"], v["mode"]): v for v in s["video"]["per_slot"]}
    assert vs[(2, "secret")]["video_impression"] == 1 and vs[(2, "secret")]["video_50"] == 1 and vs[(2, "secret")]["start_pct"] == 100.0 and vs[(2, "secret")]["complete_pct"] == 0.0
    ct = {c["cta_type"]: c for c in s["cta"]["per_tipo"]}
    assert ct["gallery"]["impressions"] == 1 and ct["gallery"]["click"] == 1 and ct["gallery"]["ctr"] == 100.0 and ct["gallery"]["secondi_medi_al_click"] == 40.0
    assert ct["timed"]["of_click"] == 1 and ct["timed"]["impressions"] == 0
    assert s["scroll"]["scroll_50"]["n"] == 1 and s["engaged"]["oltre_30s"]["n"] == 1
    assert s["home"]["card_impressions"] == 1 and s["home"]["card_click"] == 1 and s["home"]["card_ctr"] == 100.0


def test_empty_period_no_division_by_zero():
    p = {"range_key": "custom", "from": "2001-01-01", "to": "2001-01-02", "campagna": MARK}
    r = requests.get(f"{V2}/summary", params=p, headers=H(), timeout=30)
    assert r.status_code == 200
    s = r.json()
    assert s["eventi_totali"] == 0 and s["scorecard"]["visite"] == 0
    assert s["scorecard"]["ctr_of"] is None and s["scorecard"]["secret_rate"] is None and s["scorecard"]["engaged_medio_s"] is None
    assert all(x["n"] == 0 for x in s["funnel"]) and s["percorsi"]["items"] == [] and s["device_compare"] == [] and s["entry_sources"] == []
    t = requests.get(f"{V2}/timeseries", params={**p, "granularity": "hour"}, headers=H(), timeout=30).json()
    assert t["items"] == []
    d = requests.get(f"{V2}/model/{SLUG}", params=p, headers=H(), timeout=30).json()
    assert d["traffico"]["visite"] == 0 and d["media"]["disponibile"] is False and d["engaged"]["engaged_medio_s"] is None


def test_models_table_row_and_filters():
    d = requests.get(f"{V2}/models", params=F, headers=H(), timeout=30).json()
    row = next(x for x in d["items"] if x["slug"] == SLUG)
    assert row["non_pubblicata"] is True
    assert row["visite"] == 2 and row["visite_uniche"] == 2 and row["visitatori_unici"] == 2 and row["engaged"] == 2
    assert row["secret"] == 2 and row["cta_impressions"] == 1 and row["cta_click"] == 1 and row["of_click"] == 2 and row["ctr_of"] == 100.0
    assert row["social_click"] == 1 and row["swipe_out"] == 1 and row["swipe_in"] == 2      # to_model + legacy meta.to
    assert row["video_start"] == 1 and row["scroll_50_pct"] == 50.0 and row["engaged_medio_s"] == 45.0 and row["secret_engaged_medio_s"] == 35.0
    assert row["marquee_click"] == 1 and row["marquee_impressions"] == 1
    assert row["via_home"] == 1 and row["via_direct"] == 1 and row["via_swipe"] == 0
    other = next(x for x in d["items"] if x["slug"] == OTHER)
    assert other["via_swipe"] == 1 and other["swipe_in"] == 1 and other["swipe_out"] == 2
    # device filter
    dm = requests.get(f"{V2}/models", params={**F, "device": "desktop"}, headers=H(), timeout=30).json()
    rd = next(x for x in dm["items"] if x["slug"] == SLUG)
    assert rd["visite"] == 1 and rd["of_click"] == 1 and rd["cta_impressions"] == 0
    # entry filter
    de = requests.get(f"{V2}/summary", params={**F, "entry": "home_card"}, headers=H(), timeout=30).json()["scorecard"]
    assert de["profili_aperti"] == 1 and de["of_click_personali"] == 1
    # mode filter: public keeps neutral page_view, drops secret-only
    sp = requests.get(f"{V2}/summary", params={**F, "mode": "public"}, headers=H(), timeout=30).json()["scorecard"]
    assert sp["profili_aperti"] == 2 and sp["secret_attivazioni"] == 0 and sp["of_click_personali"] == 0


def test_model_detail_matches_table():
    d = requests.get(f"{V2}/model/{SLUG}", params=F, headers=H(), timeout=30).json()
    assert d["traffico"]["visite"] == 2 and d["traffico"]["visite_uniche"] == 2
    assert d["secret"]["attivazioni"] == 2 and d["secret"]["public_to_secret_pct"] == 100.0
    assert d["onlyfans"]["of_click"] == 2 and d["onlyfans"]["dopo_swipe"] == 1 and d["onlyfans"]["dopo_gesture"] == 1 and d["onlyfans"]["marquee_globale_da_questo_profilo"] == 1 and d["onlyfans"]["marquee_ctr"] == 100.0
    assert d["social"] == {"instagram": 1}
    assert d["swipe"]["arrivi"] == 2 and d["swipe"]["arrivi_gesture"] == 2 and d["swipe"]["uscite_pulsante"] == 1 and d["swipe"]["verso_quale_modella"][0]["slug"] == OTHER
    f = {x["key"]: x for x in d["funnel"]}
    assert f["view"]["n"] == 2 and f["of"]["n"] == 1 and f["of"]["n_raw"] == 2
    assert d["media"]["disponibile"] is True and d["media"]["per_slot"][0]["slot"] == 2
    assert {r["entry_source"] for r in d["entry_sources"]} == {"home_card", "direct_profile"}
    assert d["engaged"]["engaged_medio_s"] == 45.0 and d["scroll"]["scroll_50"]["n"] == 1 and d["ultimo_evento"]
    assert {c["cta_type"] for c in d["cta"]["per_tipo"]} == {"gallery", "timed"}


def test_timeseries_compare_visit():
    t = requests.get(f"{V2}/timeseries", params={**F, "granularity": "day"}, headers=H(), timeout=30).json()
    assert sum(x["profili"] for x in t["items"]) == 3 and sum(x["visite"] for x in t["items"]) >= 3 and sum(x["cta_imp"] for x in t["items"]) == 1
    for g in ("hour", "week", "month", "nonsense"):
        assert requests.get(f"{V2}/timeseries", params={**F, "granularity": g}, headers=H(), timeout=30).status_code == 200
    c = requests.get(f"{V2}/compare", params={**F, "slugs": f"{SLUG},non-esiste"}, headers=H(), timeout=30).json()
    assert c["items"][0]["visite"] == 2 and c["items"][1] == {"slug": "non-esiste", "modella": "non-esiste"}
    v = requests.get(f"{V2}/visit/{VA}", headers=H(), timeout=30).json()
    assert v["n"] == 15 and v["percorso"].startswith("HOME → CARD → ") and v["items"][0]["evento"] == "home_view" and v["items"][-1]["seq"] == 15


def test_raw_events_privacy_and_pagination():
    e = requests.get(f"{V2}/events", params={**F, "limit": 5}, headers=H(), timeout=30).json()
    assert e["total"] == 26 and len(e["items"]) == 5
    for it in e["items"]:
        assert it["session"] is None or (it["session"].endswith("…") and len(it["session"]) == 9)
        assert it["visit"] is None or it["visit"].endswith("…")
        assert "ip" not in it and "geo" not in it and "token" not in str(it).lower()
    e2 = requests.get(f"{V2}/events", params={**F, "limit": 5, "skip": 25}, headers=H(), timeout=30).json()
    assert len(e2["items"]) == 1
    e3 = requests.get(f"{V2}/events", params={**F, "tipo": "evento_futuro_sconosciuto"}, headers=H(), timeout=30).json()
    assert e3["total"] == 1 and e3["items"][0]["evento"] == "evento_futuro_sconosciuto"
    assert requests.get(f"{V2}/events", params={**F, "limit": 99999}, headers=H(), timeout=30).json()["limit"] == 200


def test_filters_and_csv():
    o = requests.get(f"{V2}/filters", params=F, headers=H(), timeout=30).json()
    assert MARK in o["campagne"] and "evento_futuro_sconosciuto" in o["eventi"] and "home_card" in o["entry_sources"] and isinstance(o["modelle"], list)
    for kind in ("models", "summary", "of_clicks", "campaigns"):
        r = requests.get(f"{V2}/export.csv", params={**F, "kind": kind}, headers=H(), timeout=30)
        assert r.status_code == 200 and "text/csv" in r.headers["content-type"], kind
    r = requests.get(f"{V2}/export.csv", params={**F, "kind": "models"}, headers=H(), timeout=30)
    assert SLUG in r.text and "via_home" in r.text
    r = requests.get(f"{V2}/export.csv", params={**F, "kind": "model", "slug": SLUG}, headers=H(), timeout=30)
    assert r.status_code == 200 and "traffico;visite;2" in r.text and "funnel_step" in r.text
    assert "kind non valido" in requests.get(f"{V2}/export.csv", params={**F, "kind": "boh"}, headers=H(), timeout=30).text


# ---------------------------------------------------------------------------------------------- ingestion
def test_track_batch_ingestion_order_privacy_and_limits():
    from pymongo import MongoClient
    col = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]["analytics_events"]
    now = int(time.time() * 1000)
    tag = f"zz_batch_{uuid.uuid4().hex[:6]}"
    events = [
        {"tipo": tag, "visitor_id": "zz-v", "visit_id": "zz-visit", "seq": 1, "ts_client": now - 5000, "path": "/modelle/x", "mode": "SECRET", "entry_source": "home_card", "meta": {"password": "nope", "token": "nope", "ok": 1}},
        {"tipo": tag, "visitor_id": "zz-v", "visit_id": "zz-visit", "seq": 2, "ts_client": now, "referrer": "https://l.instagram.com/"},
        {"tipo": tag, "visit_id": "zz-visit", "seq": 3, "ts_client": now - 10 * 3600 * 1000},   # absurd skew -> server time
    ]
    r = requests.post(f"{B}/api/track/batch", json={"events": events, "sent_at": now}, headers={"Referer": "https://example.test/modelle/x"}, timeout=20)
    assert r.status_code == 200 and r.json()["accepted"] == 3
    docs = list(col.find({"tipo": tag}, {"_id": 0}).sort("seq", 1))
    assert len(docs) == 3
    assert docs[0]["mode"] == "secret" and docs[0]["path"] == "/modelle/x" and docs[0]["entry_source"] == "home_card"
    assert docs[0]["meta"] == {"ok": 1}                                   # sensitive keys stripped
    assert docs[0]["session_id"] == "zz-v" and docs[0]["visitor_id"] == "zz-v"
    assert docs[1]["source"] == "instagram"                               # derived from referrer host
    t0 = datetime.fromisoformat(docs[0]["timestamp"]); t1 = datetime.fromisoformat(docs[1]["timestamp"])
    assert 4 <= (t1 - t0).total_seconds() <= 6                            # client offsets preserved
    assert docs[2].get("visitor_id") in (None, "")
    assert "ip" not in docs[0]
    # limits: >50 events truncated, empty batch ok, invalid payload 422
    big = [{"tipo": tag + "_big", "ts_client": now} for _ in range(60)]
    assert requests.post(f"{B}/api/track/batch", json={"events": big, "sent_at": now}, timeout=20).status_code == 422
    assert requests.post(f"{B}/api/track/batch", json={"events": [], "sent_at": now}, timeout=20).json()["accepted"] == 0
    assert requests.post(f"{B}/api/track/batch", json={"events": [{"nope": 1}]}, timeout=20).status_code == 422
    col.delete_many({"tipo": {"$regex": f"^{tag}"}})
