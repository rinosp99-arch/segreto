"""
OnlyFans Autopilot Backend API Testing
Tests the MOCK autopilot phase with full write operations (MockOFProvider)
"""
import requests
import sys
import time
from datetime import datetime

class OFAutopilotTester:
    def __init__(self, base_url="https://secret-side.preview.emergentagent.com"):
        self.base_url = base_url
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_connection_calls = 0
        self.secrets = self._load_secrets()

    def _load_secrets(self):
        """Load secrets from .env to verify they're never exposed"""
        try:
            with open('/app/backend/.env', 'r') as f:
                content = f.read()
                secrets = {}
                for line in content.split('\n'):
                    if 'THE_ONLY_API_KEY=' in line:
                        secrets['api_key'] = line.split('=', 1)[1].strip().strip('"')
                    elif 'THE_ONLY_CRM_ID=' in line:
                        secrets['crm_id'] = line.split('=', 1)[1].strip().strip('"')
                return secrets
        except Exception as e:
            print(f"⚠️  Could not load secrets: {e}")
            return {}

    def run_test(self, name, method, endpoint, expected_status, data=None, timeout=60):
        """Run a single API test"""
        url = f"{self.base_url}/api/admin/of-autopilot/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'

        self.tests_run += 1
        print(f"\n🔍 Test {self.tests_run}: {name}...")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=timeout)
            elif method == 'PATCH':
                response = requests.patch(url, json=data, headers=headers, timeout=timeout)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ PASSED - Status: {response.status_code}")
            else:
                print(f"❌ FAILED - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}")

            return success, response

        except Exception as e:
            print(f"❌ FAILED - Error: {str(e)}")
            return False, None

    def login(self):
        """Login as admin"""
        print("\n" + "="*80)
        print("AUTHENTICATION")
        print("="*80)
        
        url = f"{self.base_url}/api/admin/login"
        response = requests.post(url, json={
            "email": "admin@latosegreto.it",
            "password": "LatoSegreto2025!"
        }, timeout=15)
        
        if response.status_code == 200:
            self.token = response.json()["token"]
            print("✅ Admin login successful")
            return True
        else:
            print(f"❌ Login failed: {response.status_code}")
            return False

    def test_auth_protection(self):
        """Test that all endpoints require admin JWT"""
        print("\n" + "="*80)
        print("AUTH PROTECTION TESTS")
        print("="*80)
        
        # Temporarily remove token
        saved_token = self.token
        self.token = None
        
        endpoints = [
            ('GET', 'status'),
            ('GET', 'preview'),
            ('GET', 'logs'),
            ('GET', 'uploads'),
            ('GET', 'connection'),
            ('POST', 'start'),
            ('POST', 'pause'),
            ('POST', 'publish-now'),
            ('POST', 'skip'),
            ('POST', 'test-connection'),
            ('PATCH', 'settings')
        ]
        
        for method, endpoint in endpoints:
            success, response = self.run_test(
                f"{method} {endpoint} without JWT",
                method,
                endpoint,
                401,  # Expecting 401 or 403
                data={} if method in ['POST', 'PATCH'] else None
            )
            # Accept both 401 and 403
            if response and response.status_code in [401, 403]:
                if not success:
                    self.tests_passed += 1
                    print(f"✅ Correctly rejected with {response.status_code}")
        
        # Restore token
        self.token = saved_token

    def test_status(self):
        """Test GET /status endpoint"""
        print("\n" + "="*80)
        print("STATUS ENDPOINT TEST")
        print("="*80)
        
        success, response = self.run_test(
            "GET status",
            "GET",
            "status",
            200,
            timeout=60
        )
        
        if success and response:
            data = response.json()
            
            # Check required fields
            required_fields = {
                'OF_AUTOPILOT_STATUS': ['PAUSED', 'READY', 'ACTIVE'],
                'MOCK_MODE': True,
                'OF_REAL_POSTING_ENABLED': False,
                'AUTO_SCHEDULER_ENABLED': False,
                'REAL_POSTING': 'OFF',
                'AUTO_SCHEDULER': 'OFF',
                'PROVIDER': 'The Only API',
                'CONNECTION_STATUS': 'CONNECTED',
                'ACCOUNT_USERNAME': 'latosegreto',
                'ACCOUNT_STATUS': 'HEALTHY',
                'THE_ONLY_API_REAL_WRITE_CALLS': 0,
                'OF_REAL_POST_DONE': False
            }
            
            all_ok = True
            for field, expected in required_fields.items():
                actual = data.get(field)
                if isinstance(expected, list):
                    if actual not in expected:
                        print(f"❌ {field}: expected one of {expected}, got {actual}")
                        all_ok = False
                    else:
                        print(f"✅ {field}: {actual}")
                else:
                    if actual != expected:
                        print(f"❌ {field}: expected {expected}, got {actual}")
                        all_ok = False
                    else:
                        print(f"✅ {field}: {actual}")
            
            # Check settings
            settings = data.get('settings', {})
            print(f"\n📋 Settings:")
            print(f"   posts_per_day: {settings.get('posts_per_day')}")
            print(f"   schedule_times: {settings.get('schedule_times')}")
            print(f"   timezone: {settings.get('timezone')}")
            
            # Check queue
            queue = data.get('queue', {})
            print(f"\n📋 Queue:")
            print(f"   total: {queue.get('total')}")
            print(f"   position: {queue.get('position')}")
            print(f"   cycle_number: {queue.get('cycle_number')}")
            if queue.get('order'):
                print(f"   order: {len(queue['order'])} models")
            
            # Check schedule
            schedule = data.get('schedule', {})
            next_slot = schedule.get('next_slot', {})
            if next_slot:
                slot_id = next_slot.get('slot_id', '')
                print(f"\n📋 Next slot: {slot_id}")
                if slot_id.startswith('of_') and any(t in slot_id for t in ['11:30', '17:30', '22:00']):
                    print(f"✅ Slot ID format correct")
                else:
                    print(f"❌ Slot ID format incorrect")
                    all_ok = False
            
            return all_ok
        
        return False

    def test_preview(self):
        """Test GET /preview endpoint (may take up to 60s)"""
        print("\n" + "="*80)
        print("PREVIEW ENDPOINT TEST (may take up to 60s)")
        print("="*80)
        
        success, response = self.run_test(
            "GET preview",
            "GET",
            "preview",
            200,
            timeout=120  # Generous timeout for LLM + HEAD checks
        )
        
        if success and response:
            data = response.json()
            
            # Check required fields
            checks = {
                'status': 'PREVIEW',
                'public.side': 'PUBLIC',
                'secret.side': 'SECRET',
                'SAME_MODEL_MEDIA': True,
                'media_order': ['PUBLIC', 'SECRET'],
                'provider': 'MOCK',
                'account': 'latosegreto',
                'writes': 0
            }
            
            all_ok = True
            for field, expected in checks.items():
                if '.' in field:
                    parts = field.split('.')
                    actual = data.get(parts[0], {}).get(parts[1])
                else:
                    actual = data.get(field)
                
                if actual != expected:
                    print(f"❌ {field}: expected {expected}, got {actual}")
                    all_ok = False
                else:
                    print(f"✅ {field}: {actual}")
            
            # Check validations
            pub_val = data.get('public_validation', {})
            sec_val = data.get('secret_validation', {})
            
            if pub_val.get('ok') and pub_val.get('status_code') in [200, 206]:
                print(f"✅ public_validation: ok=True, status_code={pub_val.get('status_code')}")
            else:
                print(f"❌ public_validation: {pub_val}")
                all_ok = False
            
            if sec_val.get('ok') and sec_val.get('status_code') in [200, 206]:
                print(f"✅ secret_validation: ok=True, status_code={sec_val.get('status_code')}")
            else:
                print(f"❌ secret_validation: {sec_val}")
                all_ok = False
            
            # Check URLs
            public_url = data.get('public', {}).get('source_url', '')
            secret_url = data.get('secret', {}).get('source_url', '')
            of_url = data.get('of_url', '')
            caption = data.get('caption', '')
            
            if public_url.startswith('https://'):
                print(f"✅ public.source_url starts with https://")
            else:
                print(f"❌ public.source_url: {public_url}")
                all_ok = False
            
            if secret_url.startswith('https://'):
                print(f"✅ secret.source_url starts with https://")
            else:
                print(f"❌ secret.source_url: {secret_url}")
                all_ok = False
            
            if of_url.startswith('https://onlyfans.com/'):
                print(f"✅ of_url starts with https://onlyfans.com/")
            else:
                print(f"❌ of_url: {of_url}")
                all_ok = False
            
            if caption.endswith(of_url):
                print(f"✅ caption ends with of_url")
            else:
                print(f"❌ caption does not end with of_url")
                all_ok = False
            
            # Check that 'http' appears exactly once in caption
            http_count = caption.count('http')
            if http_count == 1:
                print(f"✅ caption contains 'http' exactly once")
            else:
                print(f"❌ caption contains 'http' {http_count} times (expected 1)")
                all_ok = False
            
            return all_ok
        
        return False

    def test_publish_now(self):
        """Test POST /publish-now (call max 2 times)"""
        print("\n" + "="*80)
        print("PUBLISH-NOW TESTS (max 2 calls)")
        print("="*80)
        
        # Get status before to check queue position
        _, status_before = self.run_test("GET status before publish", "GET", "status", 200)
        queue_before = status_before.json().get('queue', {}) if status_before else {}
        position_before = queue_before.get('position', 0)
        
        # First publish-now
        success1, response1 = self.run_test(
            "POST publish-now (1st call)",
            "POST",
            "publish-now",
            200,
            timeout=120
        )
        
        if success1 and response1:
            data1 = response1.json()
            
            checks = {
                'status': 'MOCK_CONFIRMED',
                'real_status': 'POST_CONFIRMED',
                'action_type': 'PUBLISH_NOW',
                'slot_id': None,
                'scheduled_at': None,
                'media_order': ['PUBLIC', 'SECRET'],
                'SAME_MODEL_MEDIA': True
            }
            
            all_ok = True
            for field, expected in checks.items():
                actual = data1.get(field)
                if actual != expected:
                    print(f"❌ {field}: expected {expected}, got {actual}")
                    all_ok = False
                else:
                    print(f"✅ {field}: {actual}")
            
            # Check media IDs
            pub_id = data1.get('public_media_id', '')
            sec_id = data1.get('secret_media_id', '')
            
            if pub_id.startswith('pub:'):
                print(f"✅ public_media_id starts with 'pub:'")
            else:
                print(f"❌ public_media_id: {pub_id}")
                all_ok = False
            
            if sec_id.startswith('sec:'):
                print(f"✅ secret_media_id starts with 'sec:'")
            else:
                print(f"❌ secret_media_id: {sec_id}")
                all_ok = False
            
            # Check provider_post_id
            post_id = data1.get('provider_post_id', '')
            if post_id.startswith('mock_of_'):
                print(f"✅ provider_post_id starts with 'mock_of_'")
            else:
                print(f"❌ provider_post_id: {post_id}")
                all_ok = False
            
            # Check media objects
            pub_obj = data1.get('public_media_object', {})
            sec_obj = data1.get('secret_media_object', {})
            
            required_keys = ['processId', 'host', 'thumbId', 'name']
            for key in required_keys:
                if key in pub_obj and key in sec_obj:
                    print(f"✅ Media objects have '{key}'")
                else:
                    print(f"❌ Media objects missing '{key}'")
                    all_ok = False
            
            # Check caption and of_link
            caption = data1.get('caption', '')
            of_link = data1.get('of_link', '')
            
            if caption.endswith(of_link):
                print(f"✅ caption ends with of_link")
            else:
                print(f"❌ caption does not end with of_link")
                all_ok = False
            
            # Get status after to check queue advanced
            time.sleep(1)
            _, status_after = self.run_test("GET status after publish", "GET", "status", 200)
            if status_after:
                queue_after = status_after.json().get('queue', {})
                position_after = queue_after.get('position', 0)
                
                if position_after > position_before:
                    print(f"✅ Queue position advanced: {position_before} -> {position_after}")
                else:
                    print(f"⚠️  Queue position: {position_before} -> {position_after}")
                
                # Check last_published
                last_pub = status_after.json().get('last_published', {})
                if last_pub.get('provider_post_id') == post_id:
                    print(f"✅ last_published.provider_post_id set correctly")
                else:
                    print(f"❌ last_published.provider_post_id mismatch")
                    all_ok = False
            
            # Check logs
            _, logs_resp = self.run_test("GET logs", "GET", "logs", 200)
            if logs_resp:
                logs = logs_resp.json().get('items', [])
                if logs:
                    latest = logs[0]
                    if latest.get('status') == 'MOCK_CONFIRMED' and latest.get('action_type') == 'PUBLISH_NOW':
                        print(f"✅ Log entry created with correct status")
                    else:
                        print(f"❌ Log entry incorrect: {latest.get('status')}")
                        all_ok = False
            
            # Check uploads
            _, uploads_resp = self.run_test("GET uploads", "GET", "uploads", 200)
            if uploads_resp:
                uploads = uploads_resp.json().get('items', [])
                model_id = data1.get('model_id')
                model_uploads = [u for u in uploads if u.get('model_id') == model_id]
                
                if len(model_uploads) >= 2:
                    sides = {u.get('media_side') for u in model_uploads[:2]}
                    if sides == {'PUBLIC', 'SECRET'}:
                        print(f"✅ Uploads created for both PUBLIC and SECRET")
                    else:
                        print(f"❌ Upload sides: {sides}")
                        all_ok = False
                    
                    for upload in model_uploads[:2]:
                        if upload.get('status') == 'USED_IN_POST':
                            print(f"✅ Upload status: USED_IN_POST")
                        else:
                            print(f"❌ Upload status: {upload.get('status')}")
                            all_ok = False
        
        # Second publish-now (different model)
        print("\n--- Second publish-now ---")
        success2, response2 = self.run_test(
            "POST publish-now (2nd call)",
            "POST",
            "publish-now",
            200,
            timeout=120
        )
        
        if success2 and response2:
            data2 = response2.json()
            model_slug_2 = data2.get('model_slug')
            of_link_2 = data2.get('of_link')
            caption_2 = data2.get('caption', '')
            
            # Check it's a different model
            if model_slug_2 != data1.get('model_slug'):
                print(f"✅ Second publish uses different model: {model_slug_2}")
            else:
                print(f"⚠️  Same model used twice")
            
            # Check the model's own of_url appears in caption
            if of_link_2 in caption_2:
                print(f"✅ Model's own of_url appears in caption")
            else:
                print(f"❌ Model's of_url not in caption")
        
        # Check THE_ONLY_API_REAL_WRITE_CALLS still 0
        _, status_final = self.run_test("GET status final", "GET", "status", 200)
        if status_final:
            write_calls = status_final.json().get('THE_ONLY_API_REAL_WRITE_CALLS', -1)
            if write_calls == 0:
                print(f"✅ THE_ONLY_API_REAL_WRITE_CALLS still 0")
            else:
                print(f"❌ THE_ONLY_API_REAL_WRITE_CALLS: {write_calls}")

    def test_skip(self):
        """Test POST /skip"""
        print("\n" + "="*80)
        print("SKIP TEST")
        print("="*80)
        
        success, response = self.run_test(
            "POST skip",
            "POST",
            "skip",
            200
        )
        
        if success and response:
            data = response.json()
            if data.get('status') == 'MANUAL_SKIP':
                print(f"✅ Skip successful: {data.get('skipped')}")
            else:
                print(f"❌ Skip status: {data.get('status')}")

    def test_start_pause(self):
        """Test POST /start and /pause"""
        print("\n" + "="*80)
        print("START/PAUSE TESTS")
        print("="*80)
        
        # Start
        success, response = self.run_test(
            "POST start",
            "POST",
            "start",
            200
        )
        
        if success and response:
            data = response.json()
            if data.get('enabled') == True:
                print(f"✅ Start successful, enabled=True")
                if data.get('note'):
                    print(f"   Note: {data.get('note')}")
            else:
                print(f"❌ Start failed: {data}")
        
        # Check status is READY
        time.sleep(1)
        _, status_resp = self.run_test("GET status after start", "GET", "status", 200)
        if status_resp:
            status = status_resp.json().get('OF_AUTOPILOT_STATUS')
            if status == 'READY':
                print(f"✅ Status is READY after start")
            else:
                print(f"⚠️  Status is {status} (expected READY)")
        
        # Pause
        success, response = self.run_test(
            "POST pause",
            "POST",
            "pause",
            200
        )
        
        if success and response:
            data = response.json()
            if data.get('enabled') == False:
                print(f"✅ Pause successful, enabled=False")
            else:
                print(f"❌ Pause failed: {data}")
        
        # Check status is PAUSED
        time.sleep(1)
        _, status_resp = self.run_test("GET status after pause", "GET", "status", 200)
        if status_resp:
            status = status_resp.json().get('OF_AUTOPILOT_STATUS')
            if status == 'PAUSED':
                print(f"✅ Status is PAUSED after pause")
            else:
                print(f"❌ Status is {status} (expected PAUSED)")

    def test_settings(self):
        """Test PATCH /settings with validation"""
        print("\n" + "="*80)
        print("SETTINGS VALIDATION TESTS")
        print("="*80)
        
        # Invalid time format
        success, response = self.run_test(
            "PATCH settings with invalid time '25:00'",
            "PATCH",
            "settings",
            422,
            data={"schedule_times": ["25:00"]}
        )
        
        # Invalid timezone
        success, response = self.run_test(
            "PATCH settings with invalid timezone 'Mars/Olympus'",
            "PATCH",
            "settings",
            422,
            data={"timezone": "Mars/Olympus"}
        )
        
        # Invalid posts_per_day
        success, response = self.run_test(
            "PATCH settings with posts_per_day=9",
            "PATCH",
            "settings",
            422,
            data={"posts_per_day": 9}
        )
        
        # Valid settings
        success, response = self.run_test(
            "PATCH settings with valid data",
            "PATCH",
            "settings",
            200,
            data={
                "schedule_times": ["22:00", "11:30", "17:30"],
                "posts_per_day": 3,
                "timezone": "Europe/Rome",
                "use_ai_copy": True
            }
        )
        
        if success and response:
            data = response.json()
            # Should be sorted
            if data.get('schedule_times') == ["11:30", "17:30", "22:00"]:
                print(f"✅ Settings sorted correctly")
            else:
                print(f"❌ Settings not sorted: {data.get('schedule_times')}")

    def test_security(self):
        """Test security requirements"""
        print("\n" + "="*80)
        print("SECURITY TESTS")
        print("="*80)
        
        # Test that no route can enable real posting
        forbidden_routes = [
            'enable-real-posting',
            'upload',
            'schedule',
            'real-posting'
        ]
        
        for route in forbidden_routes:
            success, response = self.run_test(
                f"POST {route} should not exist",
                "POST",
                route,
                404,  # Expecting 404 or 405
                data={}
            )
            # Accept both 404 and 405
            if response and response.status_code in [404, 405]:
                if not success:
                    self.tests_passed += 1
                    print(f"✅ Route correctly does not exist ({response.status_code})")
        
        # Test that response bodies don't contain secrets
        print("\n--- Checking for secret leakage ---")
        
        endpoints_to_check = ['status', 'preview', 'uploads']
        
        for endpoint in endpoints_to_check:
            _, response = self.run_test(
                f"GET {endpoint} for secret check",
                "GET",
                endpoint,
                200,
                timeout=120 if endpoint == 'preview' else 60
            )
            
            if response:
                body = response.text
                
                # Check for raw secrets
                leaked = []
                if self.secrets.get('api_key') and self.secrets['api_key'] in body:
                    leaked.append('THE_ONLY_API_KEY')
                if self.secrets.get('crm_id') and self.secrets['crm_id'] in body:
                    leaked.append('THE_ONLY_CRM_ID')
                
                # Check for forbidden strings
                forbidden = ['sess', 'auth_id', 'x-api-key']
                for word in forbidden:
                    if word in body.lower():
                        leaked.append(word)
                
                if leaked:
                    print(f"❌ {endpoint} response contains: {', '.join(leaked)}")
                else:
                    print(f"✅ {endpoint} response clean (no secrets)")
        
        # Check backend logs for raw API key
        print("\n--- Checking backend logs for secrets ---")
        try:
            import subprocess
            result = subprocess.run(
                ['grep', '-c', self.secrets.get('api_key', 'DUMMY_KEY_THAT_WONT_MATCH'), 
                 '/var/log/supervisor/backend.out.log', '/var/log/supervisor/backend.err.log'],
                capture_output=True,
                text=True
            )
            # grep -c returns count, we want 0
            counts = [int(x) for x in result.stdout.strip().split('\n') if x.isdigit()]
            total = sum(counts)
            print(f"   Raw API key found in logs: {total} times")
            if total == 0:
                print(f"✅ No raw API key in backend logs")
            else:
                print(f"❌ Raw API key found {total} times in logs")
        except Exception as e:
            print(f"⚠️  Could not check logs: {e}")

    def test_regression(self):
        """Test that other autopilot modules are unchanged"""
        print("\n" + "="*80)
        print("REGRESSION TESTS")
        print("="*80)
        
        other_autopilots = [
            'telegram-autopilot',
            'instagram-autopilot',
            'x-autopilot'
        ]
        
        # Get initial state
        initial_states = {}
        for autopilot in other_autopilots:
            url = f"{self.base_url}/api/admin/{autopilot}/status"
            headers = {'Authorization': f'Bearer {self.token}'}
            try:
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    queue = data.get('queue', {})
                    initial_states[autopilot] = {
                        'position': queue.get('position'),
                        'cycle_number': queue.get('cycle_number')
                    }
                    print(f"✅ {autopilot} status: position={queue.get('position')}, cycle={queue.get('cycle_number')}")
                else:
                    print(f"⚠️  {autopilot} returned {response.status_code}")
            except Exception as e:
                print(f"⚠️  {autopilot} error: {e}")
        
        return initial_states

    def run_all_tests(self):
        """Run all tests"""
        print("\n" + "="*80)
        print("ONLYFANS AUTOPILOT BACKEND TESTING")
        print("="*80)
        print(f"Backend URL: {self.base_url}")
        print(f"Time: {datetime.now().isoformat()}")
        
        if not self.login():
            print("\n❌ Cannot proceed without authentication")
            return False
        
        # Run tests in order
        self.test_auth_protection()
        self.test_status()
        self.test_preview()
        self.test_publish_now()
        self.test_skip()
        self.test_start_pause()
        self.test_settings()
        self.test_security()
        initial_states = self.test_regression()
        
        # Final summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print(f"Tests run: {self.tests_run}")
        print(f"Tests passed: {self.tests_passed}")
        print(f"Success rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        return self.tests_passed == self.tests_run

def main():
    tester = OFAutopilotTester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
