#!/usr/bin/env python3
"""
OnlyFans Autopilot Backend API Test
Tests the specific contract requirements for the READ-ONLY OnlyFans integration
"""
import requests
import sys

BASE_URL = "https://secret-side.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@latosegreto.it"
ADMIN_PASSWORD = "LatoSegreto2025!"

class OFAutopilotTester:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_connection_calls = 0  # Track test-connection calls (max 3 total)

    def log(self, msg: str, level: str = "INFO"):
        prefix = {"INFO": "ℹ️", "SUCCESS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(level, "•")
        print(f"{prefix} {msg}")

    def test(self, name: str, method: str, endpoint: str, expected_status: int,
             data=None, headers=None, check_response=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        req_headers = {'Content-Type': 'application/json'}
        if self.token:
            req_headers['Authorization'] = f'Bearer {self.token}'
        if headers:
            req_headers.update(headers)

        self.tests_run += 1
        self.log(f"Testing {name}...", "INFO")

        try:
            if method == 'GET':
                response = requests.get(url, headers=req_headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=req_headers, timeout=30)
            else:
                self.log(f"Unknown method {method}", "FAIL")
                return False, {}

            success = response.status_code == expected_status
            resp_data = {}
            try:
                resp_data = response.json()
            except:
                resp_data = {"text": response.text[:200]}

            if success:
                if check_response and not check_response(resp_data):
                    self.log(f"FAILED - Status OK but response validation failed", "FAIL")
                    return False, resp_data
                self.tests_passed += 1
                self.log(f"PASSED - Status: {response.status_code}", "SUCCESS")
            else:
                self.log(f"FAILED - Expected {expected_status}, got {response.status_code}", "FAIL")

            return success, resp_data

        except Exception as e:
            self.log(f"FAILED - Error: {str(e)}", "FAIL")
            return False, {}

    def run_all_tests(self):
        """Execute all OnlyFans Autopilot tests"""
        self.log("=" * 70, "INFO")
        self.log("OnlyFans Autopilot Backend API Test (READ-ONLY Phase)", "INFO")
        self.log("=" * 70, "INFO")

        # 1. Test auth protection
        self.test_auth_protection()

        # 2. Admin login
        self.test_admin_login()

        # 3. Test connection endpoint with JWT
        if self.token:
            self.test_connection_endpoint()
            self.test_test_connection_endpoint()
            self.test_no_write_routes()
            self.test_security_requirements()
            self.test_regression_other_autopilots()
        else:
            self.log("Skipping authenticated tests - no token", "WARN")

        # Print summary
        self.print_summary()

    def test_auth_protection(self):
        self.log("\n--- AUTH PROTECTION (401/403 without JWT) ---", "INFO")
        
        # Test without token
        success, _ = self.test(
            "GET connection without JWT",
            "GET",
            "admin/of-autopilot/connection",
            401
        )
        
        success, _ = self.test(
            "POST test-connection without JWT",
            "POST",
            "admin/of-autopilot/test-connection",
            401
        )

    def test_admin_login(self):
        self.log("\n--- ADMIN LOGIN ---", "INFO")
        
        success, resp = self.test(
            "Admin login",
            "POST",
            "admin/login",
            200,
            data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            check_response=lambda r: "token" in r
        )
        
        if success:
            self.token = resp.get("token")
            self.log(f"Got auth token", "INFO")

    def test_connection_endpoint(self):
        self.log("\n--- GET /api/admin/of-autopilot/connection (with JWT) ---", "INFO")
        
        def check_connection_contract(r):
            """Verify the exact contract from requirements"""
            required_fields = [
                "PROVIDER", "CONNECTION_STATUS", "ACCOUNT_STATUS", "ACCOUNT_USERNAME",
                "PLATFORM", "OF_USER_ID_DISCOVERED", "of_user_id_masked",
                "key_valid", "crm_scope", "schedules_read",
                "REAL_POSTING", "AUTO_SCHEDULER",
                "OF_REAL_POSTING_ENABLED", "OF_AUTO_SCHEDULER_ENABLED",
                "OF_REAL_WRITE_CALLS", "error"
            ]
            
            for field in required_fields:
                if field not in r:
                    self.log(f"Missing required field: {field}", "FAIL")
                    return False
            
            # Verify specific values for READ-ONLY phase
            if r.get("PROVIDER") != "The Only API":
                self.log(f"PROVIDER should be 'The Only API', got: {r.get('PROVIDER')}", "FAIL")
                return False
            
            if r.get("CONNECTION_STATUS") != "CONNECTED":
                self.log(f"CONNECTION_STATUS should be 'CONNECTED', got: {r.get('CONNECTION_STATUS')}", "FAIL")
                return False
            
            if r.get("ACCOUNT_STATUS") != "HEALTHY":
                self.log(f"ACCOUNT_STATUS should be 'HEALTHY', got: {r.get('ACCOUNT_STATUS')}", "FAIL")
                return False
            
            if r.get("ACCOUNT_USERNAME") != "latosegreto":
                self.log(f"ACCOUNT_USERNAME should be 'latosegreto', got: {r.get('ACCOUNT_USERNAME')}", "FAIL")
                return False
            
            if r.get("PLATFORM") != "onlyfans":
                self.log(f"PLATFORM should be 'onlyfans', got: {r.get('PLATFORM')}", "FAIL")
                return False
            
            if r.get("OF_USER_ID_DISCOVERED") != True:
                self.log(f"OF_USER_ID_DISCOVERED should be True", "FAIL")
                return False
            
            # Verify of_user_id_masked starts with '*'
            masked = r.get("of_user_id_masked")
            if not masked or not masked.startswith("*"):
                self.log(f"of_user_id_masked should start with '*', got: {masked}", "FAIL")
                return False
            
            if r.get("key_valid") != True:
                self.log(f"key_valid should be True", "FAIL")
                return False
            
            if r.get("crm_scope") != True:
                self.log(f"crm_scope should be True", "FAIL")
                return False
            
            if r.get("schedules_read") != True:
                self.log(f"schedules_read should be True", "FAIL")
                return False
            
            if r.get("REAL_POSTING") != "OFF":
                self.log(f"REAL_POSTING should be 'OFF', got: {r.get('REAL_POSTING')}", "FAIL")
                return False
            
            if r.get("AUTO_SCHEDULER") != "OFF":
                self.log(f"AUTO_SCHEDULER should be 'OFF', got: {r.get('AUTO_SCHEDULER')}", "FAIL")
                return False
            
            if r.get("OF_REAL_POSTING_ENABLED") != False:
                self.log(f"OF_REAL_POSTING_ENABLED should be False", "FAIL")
                return False
            
            if r.get("OF_AUTO_SCHEDULER_ENABLED") != False:
                self.log(f"OF_AUTO_SCHEDULER_ENABLED should be False", "FAIL")
                return False
            
            if r.get("OF_REAL_WRITE_CALLS") != 0:
                self.log(f"OF_REAL_WRITE_CALLS should be 0, got: {r.get('OF_REAL_WRITE_CALLS')}", "FAIL")
                return False
            
            if r.get("error") is not None:
                self.log(f"error should be null, got: {r.get('error')}", "FAIL")
                return False
            
            self.log("✓ All contract fields verified", "SUCCESS")
            return True
        
        success, resp = self.test(
            "GET connection with JWT",
            "GET",
            "admin/of-autopilot/connection",
            200,
            check_response=check_connection_contract
        )

    def test_test_connection_endpoint(self):
        self.log("\n--- POST /api/admin/of-autopilot/test-connection (with JWT, ONCE) ---", "INFO")
        
        if self.test_connection_calls >= 1:
            self.log("⚠️ Skipping test-connection call (already called once, rate limit protection)", "WARN")
            return
        
        self.test_connection_calls += 1
        
        def check_test_connection_contract(r):
            """Same contract as GET connection"""
            # Should have same fields and values
            if r.get("CONNECTION_STATUS") != "CONNECTED":
                self.log(f"CONNECTION_STATUS should be 'CONNECTED'", "FAIL")
                return False
            
            if r.get("OF_REAL_WRITE_CALLS") != 0:
                self.log(f"OF_REAL_WRITE_CALLS should stay 0, got: {r.get('OF_REAL_WRITE_CALLS')}", "FAIL")
                return False
            
            self.log("✓ test-connection contract verified", "SUCCESS")
            return True
        
        success, resp = self.test(
            "POST test-connection with JWT (ONCE)",
            "POST",
            "admin/of-autopilot/test-connection",
            200,
            check_response=check_test_connection_contract
        )

    def test_no_write_routes(self):
        self.log("\n--- NO WRITE ROUTES (404/405) ---", "INFO")
        
        write_endpoints = [
            "publish-now",
            "start",
            "skip",
            "upload",
            "schedule"
        ]
        
        for endpoint in write_endpoints:
            # Try POST (should be 404 or 405)
            url = f"{self.base_url}/admin/of-autopilot/{endpoint}"
            headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
            
            try:
                response = requests.post(url, headers=headers, timeout=10)
                if response.status_code in (404, 405):
                    self.tests_passed += 1
                    self.log(f"✓ POST {endpoint} correctly returns {response.status_code}", "SUCCESS")
                else:
                    self.log(f"✗ POST {endpoint} should return 404/405, got {response.status_code}", "FAIL")
                self.tests_run += 1
            except Exception as e:
                self.log(f"✗ Error testing {endpoint}: {e}", "FAIL")
                self.tests_run += 1

    def test_security_requirements(self):
        self.log("\n--- SECURITY: No sensitive data in responses ---", "INFO")
        
        # Get connection response
        url = f"{self.base_url}/admin/of-autopilot/connection"
        headers = {'Authorization': f'Bearer {self.token}'}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            body = response.text.lower()
            
            forbidden_strings = ["sess", "auth_id", "proxy", "api_key", "x-api-key"]
            
            all_clean = True
            for forbidden in forbidden_strings:
                if forbidden in body:
                    self.log(f"✗ Found forbidden string '{forbidden}' in response", "FAIL")
                    all_clean = False
            
            if all_clean:
                self.tests_passed += 1
                self.log("✓ No forbidden strings in response", "SUCCESS")
            
            self.tests_run += 1
            
        except Exception as e:
            self.log(f"✗ Error checking security: {e}", "FAIL")
            self.tests_run += 1

    def test_regression_other_autopilots(self):
        self.log("\n--- REGRESSION: Other autopilot modules unchanged ---", "INFO")
        
        other_autopilots = [
            ("Telegram", "admin/telegram-autopilot/status"),
            ("Instagram", "admin/instagram-autopilot/status"),
            ("X", "admin/x-autopilot/status")
        ]
        
        for name, endpoint in other_autopilots:
            success, resp = self.test(
                f"{name} autopilot status",
                "GET",
                endpoint,
                200,
                check_response=lambda r: "queue" in r or "CONNECTION_STATUS" in r
            )

    def print_summary(self):
        self.log("\n" + "=" * 70, "INFO")
        self.log(f"TESTS COMPLETED: {self.tests_passed}/{self.tests_run} passed", "INFO")
        self.log(f"test-connection calls made: {self.test_connection_calls}/3 allowed", "INFO")
        self.log("=" * 70, "INFO")

        if self.tests_passed == self.tests_run:
            self.log("ALL TESTS PASSED! 🎉", "SUCCESS")
            return 0
        else:
            failed = self.tests_run - self.tests_passed
            self.log(f"{failed} TEST(S) FAILED", "FAIL")
            return 1


def main():
    tester = OFAutopilotTester()
    exit_code = tester.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
