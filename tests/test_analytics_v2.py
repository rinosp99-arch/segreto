"""Admin Analytics v2 — backend aggregation endpoints (routes_analytics_v2.py).

Guarantees the dashboard can never receive a shape that breaks it:
  * every endpoint is admin-only (401 without token)
  * empty period → zeros / None, never a division by zero or a 500
  * unknown event names, legacy events without optional fields (session_id, meta, model_slug) are tolerated
  * filters (model / mode / campagna / device / custom range) are applied and the model row matches the detail
  * raw log never leaks full session ids
Test events are inserted with a unique campagna marker and deleted at the end (real data untouched).

Run: cd /app && python -m pytest tests/test_analytics_v2.py -q
"""
import os, sys, uuid, requests, pytest
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
MARK = f"zztest-an2-{uuid.uuid4().hex[:8]}"          # campagna marker → isolates our fixtures from real events
SLUG = f"zztest-model-{uuid.uuid4().hex[:6]}"
SID_A, SID_B = f"zztest-sid-a-{uuid.uuid4().hex}", f"zztest-sid-b-{uuid.uuid4().hex}"


def H():
    tok = requests.post(f"{B}/api/admin/login", json=ADMIN, timeout=20).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _ts(minutes_ago=5):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


@pytest.fixture(scope="module", autouse=True)
async def fixtures():
    from database import events_col
    docs = [
        # sessione A: profilo → secret → cta → of (mobile, campagna MARK)
        {"tipo": "page_view", "model_slug": SLUG, "session_id": SID_A, "device": "mobile", "campagna": MARK, "source": "instagram", "meta": {"via": "swipe", "mode": "public"}},
        {"tipo": "secret_activate", "model_slug": SLUG, "session_id": SID_A, "device": "mobile", "campagna": MARK, "valore": 12},
        {"tipo": "secret_time", "model_slug": SLUG, "session_id": SID_A, "device": "mobile", "campagna": MARK, "valore": 40},
        {"tipo": "cta_click", "model_slug": SLUG, "session_id": SID_A, "device": "mobile", "campagna": MARK, "cta_source": "of_click_gallery"},
        {"tipo": "of_click", "model_slug": SLUG, "session_id": SID_A, "device": "mobile", "campagna": MARK, "cta_source": "of_click_gallery", "meta": {"swipes": 2, "profiles_seen": 3}},
        # sessione B: solo profilo (desktop) + evento sconosciuto + evento legacy senza campi opzionali
        {"tipo": "page_view", "model_slug": SLUG, "session_id": SID_B, "device": "desktop", "campagna": MARK},
        {"tipo": "evento_futuro_sconosciuto", "session_id": SID_B, "campagna": MARK},
        {"tipo": "visit", "campagna": MARK},                                     # no session_id, no model_slug, no meta
        {"tipo": "secret_time", "model_slug": SLUG, "session_id": SID_B, "campagna": MARK, "valore": "non-numerico"},   # valore sporco
        {"tipo": "of_global_marquee_profile_click", "model_slug": SLUG, "session_id": SID_B, "campagna": MARK, "meta": {"mode": "SECRET", "campagna": MARK}},
        {"tipo": "social_click_instagram", "model_slug": SLUG, "session_id": SID_B, "campagna": MARK, "cta_source": "instagram"},
        {"tipo": "profile_swipe_next", "model_slug": SLUG, "session_id": SID_B, "campagna": MARK, "meta": {"to": "altra-modella", "mode": "public", "swipes": 1}},
    ]
    for i, d in enumerate(docs):
        d.setdefault("id", str(uuid.uuid4()))
        d.setdefault("timestamp", _ts(30 - i))
    await events_col.insert_many(docs)
    yield
    await events_col.delete_many({"campagna": MARK})


F = {"range_key": "7g", "campagna": MARK}


def test_admin_only():
    for path in ("summary", "models", f"model/{SLUG}", "timeseries", "events", "filters", "export.csv"):
        r = requests.get(f"{V2}/{path}", params=F, timeout=20)
        assert r.status_code == 401, path


def test_summary_counts_and_funnel():
    s = requests.get(f"{V2}/summary", params=F, headers=H(), timeout=30).json()
    sc = s["scorecard"]
    assert sc["eventi"] == 12
    assert sc["sessioni"] == 2                      # 'visit' without session_id is not a session
    assert sc["profili_aperti"] == 2
    assert sc["secret_attivazioni"] == 1 and sc["secret_rate"] == 50.0
    assert sc["of_click_personali"] == 1 and sc["of_click_globale"] == 1 and sc["social_click"] == 1 and sc["swipe"] == 1
    assert sc["ctr_of"] == 50.0
    assert sc["tempo_medio_secret_s"] == 40.0        # dirty non-numeric valore ignored
    steps = {x["step"]: x for x in s["funnel"]}
    assert steps["Lato Segreto attivato (sessioni)"]["n"] == 1 and steps["Click OnlyFans (sessioni)"]["n"] == 1
    # unknown event is surfaced (not hidden) and flagged
    te = {x["evento"]: x for x in s["top_events"]}
    assert te["evento_futuro_sconosciuto"]["noto"] is False and te["page_view"]["noto"] is True
    assert s["onlyfans"]["personali"]["dopo_swipe"] == 1
    assert s["onlyfans"]["globale"]["per_modalita"][0]["key"] == "SECRET"
    assert isinstance(s["not_available"], list) and s["not_available"]


def test_empty_period_no_division_by_zero():
    r = requests.get(f"{V2}/summary", params={"range_key": "custom", "from": "2001-01-01", "to": "2001-01-02", "campagna": MARK}, headers=H(), timeout=30)
    assert r.status_code == 200
    s = r.json()
    assert s["eventi_totali"] == 0 and s["scorecard"]["sessioni"] == 0
    assert s["scorecard"]["ctr_of"] is None and s["scorecard"]["secret_rate"] is None
    assert all(x["n"] == 0 for x in s["funnel"])
    t = requests.get(f"{V2}/timeseries", params={"range_key": "custom", "from": "2001-01-01", "to": "2001-01-02", "campagna": MARK, "granularity": "hour"}, headers=H(), timeout=30).json()
    assert t["items"] == []


def test_models_table_row_and_filters():
    d = requests.get(f"{V2}/models", params=F, headers=H(), timeout=30).json()
    row = next(x for x in d["items"] if x["slug"] == SLUG)
    assert row["non_pubblicata"] is True           # test slug is not a published model but its history is kept
    assert row["visite"] == 2 and row["visitatori_unici"] == 2 and row["secret"] == 1 and row["of_click"] == 1
    assert row["ctr_of"] == 50.0 and row["social_click"] == 1 and row["swipe_out"] == 1 and row["marquee_click"] == 1
    assert row["tempo_medio_secret_s"] == 40.0
    # device filter: only mobile session has of_click
    dm = requests.get(f"{V2}/models", params={**F, "device": "desktop"}, headers=H(), timeout=30).json()
    rd = next(x for x in dm["items"] if x["slug"] == SLUG)
    assert rd["visite"] == 1 and rd["of_click"] == 0 and rd["ctr_of"] == 0.0
    # mode filter: public excludes secret-only events but keeps neutral page_view
    sp = requests.get(f"{V2}/summary", params={**F, "mode": "public"}, headers=H(), timeout=30).json()["scorecard"]
    assert sp["profili_aperti"] == 2 and sp["secret_attivazioni"] == 0 and sp["cta_click"] == 0


def test_model_detail_matches_table():
    d = requests.get(f"{V2}/model/{SLUG}", params=F, headers=H(), timeout=30).json()
    assert d["traffico"]["visite"] == 2 and d["traffico"]["visitatori_unici"] == 2
    assert d["secret"]["attivazioni"] == 1 and d["secret"]["public_to_secret_pct"] == 50.0 and d["secret"]["tempo_medio_s"] == 40.0
    assert d["onlyfans"]["of_click"] == 1 and d["onlyfans"]["dopo_swipe"] == 1 and d["onlyfans"]["marquee_globale_da_questo_profilo"] == 1
    assert d["social"] == {"instagram": 1}
    assert d["swipe"]["verso_quale_modella"][0]["slug"] == "altra-modella"
    assert d["traffico"]["per_device"] and d["ultimo_evento"]
    assert d["media"]["disponibile"] is False        # not tracked → not invented


def test_timeseries_and_compare():
    t = requests.get(f"{V2}/timeseries", params={**F, "granularity": "day"}, headers=H(), timeout=30).json()
    assert sum(x["profili"] for x in t["items"]) == 2 and sum(x["visite"] for x in t["items"]) >= 2
    for g in ("hour", "week", "month", "nonsense"):
        assert requests.get(f"{V2}/timeseries", params={**F, "granularity": g}, headers=H(), timeout=30).status_code == 200
    c = requests.get(f"{V2}/compare", params={**F, "slugs": f"{SLUG},non-esiste"}, headers=H(), timeout=30).json()
    assert c["items"][0]["visite"] == 2 and c["items"][1] == {"slug": "non-esiste", "modella": "non-esiste"}


def test_raw_events_privacy_and_pagination():
    e = requests.get(f"{V2}/events", params={**F, "limit": 5}, headers=H(), timeout=30).json()
    assert e["total"] == 12 and len(e["items"]) == 5
    for it in e["items"]:
        assert it["session"] is None or it["session"].endswith("…") and len(it["session"]) == 9   # truncated
        assert "ip" not in it and "geo" not in it and "token" not in str(it).lower()
    e2 = requests.get(f"{V2}/events", params={**F, "limit": 5, "skip": 10}, headers=H(), timeout=30).json()
    assert len(e2["items"]) == 2
    e3 = requests.get(f"{V2}/events", params={**F, "tipo": "evento_futuro_sconosciuto"}, headers=H(), timeout=30).json()
    assert e3["total"] == 1 and e3["items"][0]["evento"] == "evento_futuro_sconosciuto"
    assert requests.get(f"{V2}/events", params={**F, "limit": 99999}, headers=H(), timeout=30).json()["limit"] == 200


def test_filters_and_csv():
    o = requests.get(f"{V2}/filters", params=F, headers=H(), timeout=30).json()
    assert MARK in o["campagne"] and "evento_futuro_sconosciuto" in o["eventi"] and isinstance(o["modelle"], list)
    for kind in ("models", "summary", "of_clicks", "campaigns"):
        r = requests.get(f"{V2}/export.csv", params={**F, "kind": kind}, headers=H(), timeout=30)
        assert r.status_code == 200 and "text/csv" in r.headers["content-type"] and SLUG in r.text or kind in ("summary", "campaigns"), kind
    r = requests.get(f"{V2}/export.csv", params={**F, "kind": "model", "slug": SLUG}, headers=H(), timeout=30)
    assert r.status_code == 200 and "traffico;visite;2" in r.text
    assert "kind non valido" in requests.get(f"{V2}/export.csv", params={**F, "kind": "boh"}, headers=H(), timeout=30).text
