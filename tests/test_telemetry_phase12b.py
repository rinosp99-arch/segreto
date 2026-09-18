"""Phase 12b Telemetry Testing — privacy-safe product analytics.

Tests:
1. Backend /api/track/batch: accepts 2 events, rejects 60, scrubs password from meta
2. Public site regression: age gate, cards, filmstrip, profile, secret, CTA, swipe, marquee
3. Telemetry: visit_id consistency, monotonic seq, entry_source values, batch sizes
4. Admin analytics: all widgets render, no errors, model detail, visit journey, timeseries
5. Admin robustness: 500 error handling and retry

Run: cd /app && python -m pytest tests/test_telemetry_phase12b.py -v
"""
import os
import sys
import uuid
import requests
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

# Use public endpoint from .env
BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://secret-side.preview.emergentagent.com")
ADMIN_EMAIL = "admin@latosegreto.it"
ADMIN_PASSWORD = "LatoSegreto2025!"

def get_admin_token():
    """Get admin JWT token"""
    r = requests.post(f"{BACKEND_URL}/api/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    if r.status_code != 200:
        raise Exception(f"Admin login failed: {r.status_code} {r.text}")
    return r.json()["token"]

def test_backend_track_batch_2_events():
    """POST /api/track/batch with 2 valid events returns {ok:true, accepted:2}"""
    print("\n🔍 Testing /api/track/batch with 2 events...")
    
    visitor_id = f"test-visitor-{uuid.uuid4().hex[:8]}"
    visit_id = f"test-visit-{uuid.uuid4().hex[:8]}"
    
    events = [
        {
            "tipo": "zz_test_event_1",
            "visitor_id": visitor_id,
            "visit_id": visit_id,
            "session_id": visitor_id,
            "seq": 1,
            "ts_client": int(datetime.now(timezone.utc).timestamp() * 1000),
            "path": "/test",
            "mode": "public",
            "device_type": "desktop"
        },
        {
            "tipo": "zz_test_event_2",
            "visitor_id": visitor_id,
            "visit_id": visit_id,
            "session_id": visitor_id,
            "seq": 2,
            "ts_client": int(datetime.now(timezone.utc).timestamp() * 1000),
            "path": "/test",
            "mode": "public",
            "device_type": "desktop"
        }
    ]
    
    payload = {
        "events": events,
        "sent_at": int(datetime.now(timezone.utc).timestamp() * 1000)
    }
    
    r = requests.post(f"{BACKEND_URL}/api/track/batch", json=payload, timeout=20)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    
    data = r.json()
    assert data.get("ok") is True, f"Expected ok=true, got {data}"
    assert data.get("accepted") == 2, f"Expected accepted=2, got {data.get('accepted')}"
    
    print(f"✅ Passed - Status: {r.status_code}, Response: {data}")

def test_backend_track_batch_60_events():
    """POST /api/track/batch with 60 events returns 422 (max 50)"""
    print("\n🔍 Testing /api/track/batch with 60 events (should reject)...")
    
    visitor_id = f"test-visitor-{uuid.uuid4().hex[:8]}"
    visit_id = f"test-visit-{uuid.uuid4().hex[:8]}"
    
    events = []
    for i in range(60):
        events.append({
            "tipo": f"zz_test_event_{i}",
            "visitor_id": visitor_id,
            "visit_id": visit_id,
            "session_id": visitor_id,
            "seq": i + 1,
            "ts_client": int(datetime.now(timezone.utc).timestamp() * 1000),
            "path": "/test",
            "mode": "public",
            "device_type": "desktop"
        })
    
    payload = {
        "events": events,
        "sent_at": int(datetime.now(timezone.utc).timestamp() * 1000)
    }
    
    r = requests.post(f"{BACKEND_URL}/api/track/batch", json=payload, timeout=20)
    
    # Schema validation rejects with 422 (Pydantic max_length=50)
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    data = r.json()
    assert "detail" in data, f"Expected validation error detail, got {data}"
    
    print(f"✅ Passed - Status: {r.status_code}, correctly rejected 60 events (max 50)")

def test_backend_track_batch_password_scrubbing():
    """Verify meta containing 'password' is scrubbed from stored doc"""
    print("\n🔍 Testing password scrubbing in meta field...")
    
    visitor_id = f"test-visitor-{uuid.uuid4().hex[:8]}"
    visit_id = f"test-visit-{uuid.uuid4().hex[:8]}"
    unique_tipo = f"zz_password_test_{uuid.uuid4().hex[:8]}"
    
    events = [
        {
            "tipo": unique_tipo,
            "visitor_id": visitor_id,
            "visit_id": visit_id,
            "session_id": visitor_id,
            "seq": 1,
            "ts_client": int(datetime.now(timezone.utc).timestamp() * 1000),
            "path": "/test",
            "mode": "public",
            "device_type": "desktop",
            "meta": {
                "password": "secret123",
                "token": "abc123",
                "email": "test@test.com",
                "safe_field": "this_should_remain",
                "another_safe": "also_safe"
            }
        }
    ]
    
    payload = {
        "events": events,
        "sent_at": int(datetime.now(timezone.utc).timestamp() * 1000)
    }
    
    r = requests.post(f"{BACKEND_URL}/api/track/batch", json=payload, timeout=20)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    
    # Verify directly in database (more reliable than admin API which may filter)
    import sys
    sys.path.insert(0, "/app/backend")
    import asyncio
    from database import events_col
    
    async def check_db():
        doc = await events_col.find_one({"tipo": unique_tipo}, {"_id": 0})
        return doc
    
    doc = asyncio.run(check_db())
    assert doc is not None, f"Event not found in database"
    
    meta = doc.get("meta", {})
    print(f"Stored meta: {meta}")
    
    # Verify sensitive fields were scrubbed
    assert "password" not in meta, f"Password should be scrubbed from meta, but found: {meta}"
    assert "token" not in meta, f"Token should be scrubbed from meta, but found: {meta}"
    assert "email" not in meta, f"Email should be scrubbed from meta, but found: {meta}"
    
    # Verify safe fields were preserved
    assert meta.get("safe_field") == "this_should_remain", f"Safe field should be preserved: {meta}"
    assert meta.get("another_safe") == "also_safe", f"Another safe field should be preserved: {meta}"
    
    print(f"✅ Passed - Sensitive fields scrubbed, safe fields preserved: {meta}")

def test_admin_analytics_summary():
    """Test admin analytics summary endpoint renders without errors"""
    print("\n🔍 Testing admin analytics summary...")
    
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    r = requests.get(
        f"{BACKEND_URL}/api/admin/analytics/v2/summary",
        params={"range_key": "oggi"},
        headers=headers,
        timeout=30
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    
    data = r.json()
    
    # Verify key sections exist
    assert "scorecard" in data, "Missing scorecard"
    assert "funnel" in data, "Missing funnel"
    assert "entry_sources" in data, "Missing entry_sources"
    assert "device_compare" in data, "Missing device_compare"
    assert "percorsi" in data, "Missing percorsi"
    assert "onlyfans" in data, "Missing onlyfans"
    assert "swipe" in data, "Missing swipe"
    assert "secret" in data, "Missing secret"
    assert "home" in data, "Missing home"
    
    scorecard = data["scorecard"]
    print(f"✅ Passed - Scorecard: {scorecard.get('visite')} visite, {scorecard.get('profili_aperti')} profili")

def test_admin_analytics_models():
    """Test admin analytics models table endpoint"""
    print("\n🔍 Testing admin analytics models table...")
    
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    r = requests.get(
        f"{BACKEND_URL}/api/admin/analytics/v2/models",
        params={"range_key": "30g"},
        headers=headers,
        timeout=30
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    
    data = r.json()
    assert "items" in data, "Missing items"
    
    print(f"✅ Passed - Found {len(data['items'])} models")

def test_admin_analytics_timeseries():
    """Test admin analytics timeseries endpoint"""
    print("\n🔍 Testing admin analytics timeseries...")
    
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    r = requests.get(
        f"{BACKEND_URL}/api/admin/analytics/v2/timeseries",
        params={"range_key": "7g", "granularity": "day"},
        headers=headers,
        timeout=30
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    
    data = r.json()
    assert "items" in data, "Missing items"
    assert "granularity" in data, "Missing granularity"
    
    print(f"✅ Passed - Timeseries with {len(data['items'])} data points")

def test_admin_analytics_events():
    """Test admin analytics raw events endpoint"""
    print("\n🔍 Testing admin analytics raw events...")
    
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    r = requests.get(
        f"{BACKEND_URL}/api/admin/analytics/v2/events",
        params={"range_key": "oggi", "limit": 10},
        headers=headers,
        timeout=30
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    
    data = r.json()
    assert "items" in data, "Missing items"
    assert "total" in data, "Missing total"
    
    print(f"✅ Passed - Found {data['total']} total events, showing {len(data['items'])}")

if __name__ == "__main__":
    print("=" * 80)
    print("PHASE 12B TELEMETRY BACKEND TESTS")
    print("=" * 80)
    
    try:
        test_backend_track_batch_2_events()
        test_backend_track_batch_60_events()
        test_backend_track_batch_password_scrubbing()
        test_admin_analytics_summary()
        test_admin_analytics_models()
        test_admin_analytics_timeseries()
        test_admin_analytics_events()
        
        print("\n" + "=" * 80)
        print("✅ ALL BACKEND TESTS PASSED")
        print("=" * 80)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
