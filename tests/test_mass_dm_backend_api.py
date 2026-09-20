#!/usr/bin/env python3
"""Test backend API for mass DM feature (read-only, authenticated admin only)."""
import requests
import sys

BASE_URL = "https://secret-side.preview.emergentagent.com"
ADMIN_EMAIL = "admin@latosegreto.it"
ADMIN_PASSWORD = "LatoSegreto2025!"

def get_admin_token():
    """Login as admin and get JWT token."""
    r = requests.post(f"{BASE_URL}/api/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    if r.status_code != 200:
        print(f"❌ Admin login failed: {r.status_code} {r.text}")
        sys.exit(1)
    token = r.json().get("token")
    if not token:
        print(f"❌ No token in login response: {r.json()}")
        sys.exit(1)
    print(f"✅ Admin login successful")
    return token

def test_unauthenticated_access():
    """Test that unauthenticated GET returns 401/403."""
    print("\n🔍 Testing unauthenticated access...")
    r = requests.get(f"{BASE_URL}/api/admin/of-autopilot/status", timeout=15)
    if r.status_code in (401, 403):
        print(f"✅ Unauthenticated GET blocked: {r.status_code}")
        return True
    else:
        print(f"❌ Unauthenticated GET should be 401/403, got {r.status_code}")
        return False

def test_authenticated_status(token):
    """Test authenticated GET /api/admin/of-autopilot/status."""
    print("\n🔍 Testing authenticated GET /api/admin/of-autopilot/status...")
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE_URL}/api/admin/of-autopilot/status", headers=headers, timeout=60)
    
    if r.status_code != 200:
        print(f"❌ Status endpoint failed: {r.status_code} {r.text}")
        return False
    
    data = r.json()
    print(f"✅ Status endpoint returned 200")
    
    # Check required fields
    required_fields = [
        "OF_MASS_DM_MOCK",
        "OF_MASS_DM_ENABLED",
        "OF_REAL_MASS_DM_SENT",
        "THE_ONLY_API_REAL_MASS_DM_CALLS",
        "current_run",
        "AUTO_SCHEDULER_ENABLED"
    ]
    
    missing = [f for f in required_fields if f not in data]
    if missing:
        print(f"❌ Missing required fields: {missing}")
        return False
    
    print(f"✅ All required fields present")
    
    # Check values
    checks = []
    
    # OF_MASS_DM_MOCK should be true
    if data["OF_MASS_DM_MOCK"] is True:
        print(f"✅ OF_MASS_DM_MOCK=true")
        checks.append(True)
    else:
        print(f"❌ OF_MASS_DM_MOCK={data['OF_MASS_DM_MOCK']}, expected true")
        checks.append(False)
    
    # OF_MASS_DM_ENABLED should be false
    if data["OF_MASS_DM_ENABLED"] is False:
        print(f"✅ OF_MASS_DM_ENABLED=false")
        checks.append(True)
    else:
        print(f"❌ OF_MASS_DM_ENABLED={data['OF_MASS_DM_ENABLED']}, expected false")
        checks.append(False)
    
    # OF_REAL_MASS_DM_SENT should be false
    if data["OF_REAL_MASS_DM_SENT"] is False:
        print(f"✅ OF_REAL_MASS_DM_SENT=false")
        checks.append(True)
    else:
        print(f"❌ OF_REAL_MASS_DM_SENT={data['OF_REAL_MASS_DM_SENT']}, expected false")
        checks.append(False)
    
    # THE_ONLY_API_REAL_MASS_DM_CALLS should be 0
    if data["THE_ONLY_API_REAL_MASS_DM_CALLS"] == 0:
        print(f"✅ THE_ONLY_API_REAL_MASS_DM_CALLS=0")
        checks.append(True)
    else:
        print(f"❌ THE_ONLY_API_REAL_MASS_DM_CALLS={data['THE_ONLY_API_REAL_MASS_DM_CALLS']}, expected 0")
        checks.append(False)
    
    # current_run should have FEED_STATUS and MASS_DM_STATUS
    current_run = data.get("current_run", {})
    if "FEED_STATUS" in current_run and "MASS_DM_STATUS" in current_run:
        print(f"✅ current_run has FEED_STATUS={current_run['FEED_STATUS']} and MASS_DM_STATUS={current_run['MASS_DM_STATUS']}")
        checks.append(True)
    else:
        print(f"❌ current_run missing FEED_STATUS or MASS_DM_STATUS: {current_run}")
        checks.append(False)
    
    # AUTO_SCHEDULER_ENABLED should be false
    if data["AUTO_SCHEDULER_ENABLED"] is False:
        print(f"✅ AUTO_SCHEDULER_ENABLED=false")
        checks.append(True)
    else:
        print(f"❌ AUTO_SCHEDULER_ENABLED={data['AUTO_SCHEDULER_ENABLED']}, expected false")
        checks.append(False)
    
    return all(checks)

def main():
    print("=" * 80)
    print("BACKEND API TEST: Mass DM Feature (Read-Only)")
    print("=" * 80)
    
    # Test unauthenticated access
    unauth_ok = test_unauthenticated_access()
    
    # Get admin token
    token = get_admin_token()
    
    # Test authenticated status
    status_ok = test_authenticated_status(token)
    
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Unauthenticated access blocked: {'✅ PASS' if unauth_ok else '❌ FAIL'}")
    print(f"Authenticated status endpoint: {'✅ PASS' if status_ok else '❌ FAIL'}")
    
    if unauth_ok and status_ok:
        print("\n✅ ALL BACKEND API TESTS PASSED")
        return 0
    else:
        print("\n❌ SOME BACKEND API TESTS FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
