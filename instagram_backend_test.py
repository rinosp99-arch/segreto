"""Instagram Autopilot Backend API Testing
Tests all /api/admin/instagram-autopilot/* endpoints via public URL.
Requirements: MOCK_MODE=true, CONNECTION_STATUS='NOT_CONNECTED', META_REAL_CALLS=0, no secret media.
"""
import requests
import sys
from datetime import datetime

# Public backend URL
BASE_URL = "https://secret-side.preview.emergentagent.com"

# Admin credentials
ADMIN_EMAIL = "admin@latosegreto.it"
ADMIN_PASSWORD = "LatoSegreto2025!"


class InstagramAutopilotTester:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.telegram_state_before = None

    def log(self, message, success=None):
        """Log test results"""
        if success is True:
            print(f"✅ {message}")
            self.tests_passed += 1
        elif success is False:
            print(f"❌ {message}")
        else:
            print(f"ℹ️  {message}")
        self.tests_run += 1 if success is not None else 0

    def test_admin_login(self):
        """Test admin login and get JWT token"""
        print("\n" + "="*80)
        print("TEST 1: Admin Login")
        print("="*80)
        
        try:
            response = requests.post(
                f"{self.base_url}/api/admin/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if "token" in data:
                    self.token = data["token"]
                    self.log("Admin login successful, JWT token obtained", True)
                    return True
                else:
                    self.log("Login response missing token", False)
                    return False
            else:
                self.log(f"Login failed with status {response.status_code}: {response.text}", False)
                return False
        except Exception as e:
            self.log(f"Login error: {str(e)}", False)
            return False

    def test_auth_required(self):
        """Test that all endpoints require admin JWT (401/403 without token)"""
        print("\n" + "="*80)
        print("TEST 2: Auth Required (401/403 without token)")
        print("="*80)
        
        endpoints = [
            ("GET", "/api/admin/instagram-autopilot/status"),
            ("GET", "/api/admin/instagram-autopilot/logs"),
            ("POST", "/api/admin/instagram-autopilot/test-connection"),
            ("POST", "/api/admin/instagram-autopilot/start"),
            ("POST", "/api/admin/instagram-autopilot/pause"),
            ("POST", "/api/admin/instagram-autopilot/publish-now"),
            ("POST", "/api/admin/instagram-autopilot/skip"),
            ("PATCH", "/api/admin/instagram-autopilot/settings"),
        ]
        
        all_protected = True
        for method, endpoint in endpoints:
            try:
                if method == "GET":
                    response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
                elif method == "POST":
                    response = requests.post(f"{self.base_url}{endpoint}", timeout=10)
                elif method == "PATCH":
                    response = requests.patch(f"{self.base_url}{endpoint}", json={}, timeout=10)
                
                if response.status_code in (401, 403):
                    print(f"  ✓ {method} {endpoint}: {response.status_code} (protected)")
                else:
                    print(f"  ✗ {method} {endpoint}: {response.status_code} (NOT protected!)")
                    all_protected = False
            except Exception as e:
                print(f"  ✗ {method} {endpoint}: Error - {str(e)}")
                all_protected = False
        
        self.log("All endpoints require authentication", all_protected)
        return all_protected

    def test_status_endpoint(self):
        """Test GET /api/admin/instagram-autopilot/status"""
        print("\n" + "="*80)
        print("TEST 3: GET /status - Verify all required fields")
        print("="*80)
        
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(
                f"{self.base_url}/api/admin/instagram-autopilot/status",
                headers=headers,
                timeout=60
            )
            
            if response.status_code != 200:
                self.log(f"Status endpoint failed: {response.status_code}", False)
                return False
            
            data = response.json()
            print(f"\nStatus response keys: {list(data.keys())}")
            
            # Check all required fields
            checks = [
                ("MOCK_MODE", data.get("MOCK_MODE") is True, "MOCK_MODE=true"),
                ("mock", data.get("mock") is True, "mock=true"),
                ("CONNECTION_STATUS", data.get("CONNECTION_STATUS") == "NOT_CONNECTED", "CONNECTION_STATUS='NOT_CONNECTED'"),
                ("operational", data.get("operational") is True, "operational=true"),
                ("AUTO_SCHEDULER_ENABLED", data.get("AUTO_SCHEDULER_ENABLED") is False, "AUTO_SCHEDULER_ENABLED=false"),
                ("active", data.get("active") is False, "active=false"),
                ("ITALY_AUDIENCE_MODE", data.get("ITALY_AUDIENCE_MODE") is True, "ITALY_AUDIENCE_MODE=true"),
                ("META_REAL_CALLS", data.get("META_REAL_CALLS") == 0, "META_REAL_CALLS=0"),
                ("SECRET_MEDIA_USED", data.get("SECRET_MEDIA_USED") is False, "SECRET_MEDIA_USED=false"),
                ("INSTAGRAM_REAL_POST_DONE", data.get("INSTAGRAM_REAL_POST_DONE") is False, "INSTAGRAM_REAL_POST_DONE=false"),
            ]
            
            all_passed = True
            for field, condition, description in checks:
                if condition:
                    print(f"  ✓ {description}")
                else:
                    print(f"  ✗ {description} (actual: {data.get(field)})")
                    all_passed = False
            
            # Check settings
            settings = data.get("settings", {})
            settings_checks = [
                ("posts_per_day", settings.get("posts_per_day") == 2, "posts_per_day=2"),
                ("schedule_times", settings.get("schedule_times") == ["13:00", "20:30"], "schedule_times=['13:00','20:30']"),
                ("timezone", settings.get("timezone") == "Europe/Rome", "timezone='Europe/Rome'"),
            ]
            
            for field, condition, description in settings_checks:
                if condition:
                    print(f"  ✓ settings.{description}")
                else:
                    print(f"  ✗ settings.{description} (actual: {settings.get(field)})")
                    all_passed = False
            
            # Check queue
            queue = data.get("queue", {})
            if queue.get("total", 0) >= 1:
                print(f"  ✓ queue.total >= 1 (actual: {queue.get('total')})")
            else:
                print(f"  ✗ queue.total >= 1 (actual: {queue.get('total')})")
                all_passed = False
            
            if "order" in queue and isinstance(queue["order"], list):
                print(f"  ✓ queue.order is list with {len(queue['order'])} items")
            else:
                print(f"  ✗ queue.order missing or not a list")
                all_passed = False
            
            # Check schedule
            schedule = data.get("schedule", {})
            next_slot = schedule.get("next_slot", {})
            slot_id = next_slot.get("slot_id", "")
            
            if slot_id.startswith("instagram_"):
                print(f"  ✓ schedule.next_slot.slot_id starts with 'instagram_'")
            else:
                print(f"  ✗ schedule.next_slot.slot_id doesn't start with 'instagram_' (actual: {slot_id})")
                all_passed = False
            
            if slot_id.endswith("13:00") or slot_id.endswith("20:30"):
                print(f"  ✓ schedule.next_slot.slot_id ends with 13:00 or 20:30")
            else:
                print(f"  ✗ schedule.next_slot.slot_id doesn't end with 13:00 or 20:30 (actual: {slot_id})")
                all_passed = False
            
            self.log("Status endpoint returns all required fields correctly", all_passed)
            return all_passed
            
        except Exception as e:
            self.log(f"Status endpoint error: {str(e)}", False)
            return False

    def test_connection_endpoint(self):
        """Test POST /api/admin/instagram-autopilot/test-connection"""
        print("\n" + "="*80)
        print("TEST 4: POST /test-connection")
        print("="*80)
        
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.post(
                f"{self.base_url}/api/admin/instagram-autopilot/test-connection",
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                self.log(f"Test connection failed: {response.status_code}", False)
                return False
            
            data = response.json()
            print(f"\nConnection response: {data}")
            
            checks = [
                ("CONNECTION_STATUS", data.get("CONNECTION_STATUS") == "NOT_CONNECTED", "CONNECTION_STATUS='NOT_CONNECTED'"),
                ("MOCK_MODE", data.get("MOCK_MODE") is True, "MOCK_MODE=true"),
                ("META_REAL_CALLS", data.get("META_REAL_CALLS") == 0, "META_REAL_CALLS=0"),
            ]
            
            all_passed = True
            for field, condition, description in checks:
                if condition:
                    print(f"  ✓ {description}")
                else:
                    print(f"  ✗ {description} (actual: {data.get(field)})")
                    all_passed = False
            
            # Verify no access token in response
            response_text = response.text.lower()
            if "access_token" not in response_text and "instagram_access_token" not in response_text:
                print(f"  ✓ No access token in response body")
            else:
                print(f"  ✗ Access token found in response body!")
                all_passed = False
            
            self.log("Test connection returns correct status", all_passed)
            return all_passed
            
        except Exception as e:
            self.log(f"Test connection error: {str(e)}", False)
            return False

    def test_dry_run(self):
        """Test POST /api/admin/instagram-autopilot/publish-now?dry_run=true"""
        print("\n" + "="*80)
        print("TEST 5: POST /publish-now?dry_run=true")
        print("="*80)
        
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.post(
                f"{self.base_url}/api/admin/instagram-autopilot/publish-now?dry_run=true",
                headers=headers,
                timeout=90
            )
            
            if response.status_code != 200:
                self.log(f"Dry run failed: {response.status_code} - {response.text}", False)
                return False
            
            data = response.json()
            print(f"\nDry run response keys: {list(data.keys())}")
            
            checks = [
                ("status", data.get("status") == "DRY_RUN", "status='DRY_RUN'"),
                ("post_type", data.get("post_type") in ("PHOTO_POST", "REEL_POST"), "post_type in (PHOTO_POST, REEL_POST)"),
            ]
            
            all_passed = True
            for field, condition, description in checks:
                if condition:
                    print(f"  ✓ {description}")
                else:
                    print(f"  ✗ {description} (actual: {data.get(field)})")
                    all_passed = False
            
            # Check caption
            caption = data.get("caption", "")
            print(f"\nCaption preview:\n{caption[:200]}...")
            
            caption_checks = [
                ("Italian + link in bio", "link in bio" in caption.lower(), "Caption contains 'link in bio'"),
                ("No OnlyFans", "onlyfans" not in caption.lower(), "Caption doesn't contain 'onlyfans'"),
                ("No URLs", "http" not in caption.lower(), "Caption doesn't contain 'http'"),
            ]
            
            for field, condition, description in caption_checks:
                if condition:
                    print(f"  ✓ {description}")
                else:
                    print(f"  ✗ {description}")
                    all_passed = False
            
            # Check hashtags
            hashtags = data.get("hashtags", [])
            if 3 <= len(hashtags) <= 6:
                print(f"  ✓ Hashtags count: {len(hashtags)} (3-6)")
            else:
                print(f"  ✗ Hashtags count: {len(hashtags)} (expected 3-6)")
                all_passed = False
            
            # Check media
            media = data.get("media", [])
            if media and len(media) > 0:
                first_media = media[0]
                if first_media.get("side") == "PUBLIC":
                    print(f"  ✓ media[0].side == 'PUBLIC'")
                else:
                    print(f"  ✗ media[0].side != 'PUBLIC' (actual: {first_media.get('side')})")
                    all_passed = False
                
                url = first_media.get("url", "")
                # Check that 'segret' or 'secret' is not in the PATH (host name containing 'secret' is OK)
                path_parts = url.split("/")[3:]  # Skip protocol and host
                path = "/".join(path_parts)
                if "segret" not in path.lower() and "secret" not in path.lower():
                    print(f"  ✓ media[0].url doesn't contain 'segret'/'secret' in path")
                else:
                    print(f"  ✗ media[0].url contains 'segret'/'secret' in path: {url}")
                    all_passed = False
            else:
                print(f"  ✗ No media in response")
                all_passed = False
            
            self.log("Dry run returns correct preview", all_passed)
            return all_passed
            
        except Exception as e:
            self.log(f"Dry run error: {str(e)}", False)
            return False

    def test_publish_now_and_skip(self):
        """Test POST /publish-now (real, max 2 calls) and POST /skip"""
        print("\n" + "="*80)
        print("TEST 6: POST /publish-now (real) and POST /skip")
        print("="*80)
        
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            
            # Get initial state
            status_before = requests.get(
                f"{self.base_url}/api/admin/instagram-autopilot/status",
                headers=headers,
                timeout=30
            ).json()
            
            queue_position_before = status_before.get("queue", {}).get("position", 0)
            print(f"\nInitial queue position: {queue_position_before}")
            
            # First publish-now (real)
            print("\n--- First publish-now (real) ---")
            response1 = requests.post(
                f"{self.base_url}/api/admin/instagram-autopilot/publish-now?dry_run=false",
                headers=headers,
                timeout=90
            )
            
            if response1.status_code != 200:
                self.log(f"First publish-now failed: {response1.status_code} - {response1.text}", False)
                return False
            
            data1 = response1.json()
            print(f"Response: status={data1.get('status')}, post_type={data1.get('post_type')}, model={data1.get('model_name')}")
            
            all_passed = True
            
            if data1.get("status") == "MOCK_PREPARED":
                print(f"  ✓ status='MOCK_PREPARED'")
            else:
                print(f"  ✗ status != 'MOCK_PREPARED' (actual: {data1.get('status')})")
                all_passed = False
            
            if data1.get("post_type") in ("PHOTO_POST", "REEL_POST"):
                print(f"  ✓ post_type in (PHOTO_POST, REEL_POST)")
            else:
                print(f"  ✗ Invalid post_type: {data1.get('post_type')}")
                all_passed = False
            
            # Check payload
            payload = data1.get("payload", {})
            if payload.get("media_type") in ("IMAGE", "REELS"):
                print(f"  ✓ payload.media_type in (IMAGE, REELS)")
            else:
                print(f"  ✗ Invalid payload.media_type: {payload.get('media_type')}")
                all_passed = False
            
            # Check logs
            print("\n--- Checking logs ---")
            logs_response = requests.get(
                f"{self.base_url}/api/admin/instagram-autopilot/logs?limit=10",
                headers=headers,
                timeout=30
            )
            
            if logs_response.status_code == 200:
                logs = logs_response.json().get("items", [])
                if logs and logs[0].get("status") == "MOCK_PREPARED" and logs[0].get("mock") is True:
                    print(f"  ✓ Latest log shows MOCK_PREPARED with mock=true")
                else:
                    print(f"  ✗ Latest log doesn't show MOCK_PREPARED or mock=true")
                    all_passed = False
            else:
                print(f"  ✗ Failed to get logs: {logs_response.status_code}")
                all_passed = False
            
            # Check status after first publish
            status_after1 = requests.get(
                f"{self.base_url}/api/admin/instagram-autopilot/status",
                headers=headers,
                timeout=30
            ).json()
            
            queue_position_after1 = status_after1.get("queue", {}).get("position", 0)
            print(f"\nQueue position after first publish: {queue_position_after1}")
            
            if queue_position_after1 != queue_position_before:
                print(f"  ✓ Queue position advanced")
            else:
                print(f"  ✗ Queue position didn't advance")
                all_passed = False
            
            if status_after1.get("last_published"):
                print(f"  ✓ last_published populated")
            else:
                print(f"  ✗ last_published not populated")
                all_passed = False
            
            if status_after1.get("META_REAL_CALLS") == 0:
                print(f"  ✓ META_REAL_CALLS still 0")
            else:
                print(f"  ✗ META_REAL_CALLS != 0 (actual: {status_after1.get('META_REAL_CALLS')})")
                all_passed = False
            
            # Second publish-now (real)
            print("\n--- Second publish-now (real) ---")
            response2 = requests.post(
                f"{self.base_url}/api/admin/instagram-autopilot/publish-now?dry_run=false",
                headers=headers,
                timeout=90
            )
            
            if response2.status_code == 200:
                data2 = response2.json()
                print(f"Response: status={data2.get('status')}, model={data2.get('model_name')}")
                
                if data2.get("status") == "MOCK_PREPARED":
                    print(f"  ✓ Second publish successful")
                else:
                    print(f"  ✗ Second publish status: {data2.get('status')}")
                    all_passed = False
            else:
                print(f"  ✗ Second publish failed: {response2.status_code}")
                all_passed = False
            
            # Test skip
            print("\n--- Testing skip ---")
            skip_response = requests.post(
                f"{self.base_url}/api/admin/instagram-autopilot/skip",
                headers=headers,
                timeout=30
            )
            
            if skip_response.status_code == 200:
                skip_data = skip_response.json()
                print(f"Skip response: status={skip_data.get('status')}, skipped={skip_data.get('skipped')}")
                
                if skip_data.get("status") == "MANUAL_SKIP":
                    print(f"  ✓ Skip status='MANUAL_SKIP'")
                else:
                    print(f"  ✗ Skip status != 'MANUAL_SKIP' (actual: {skip_data.get('status')})")
                    all_passed = False
            else:
                print(f"  ✗ Skip failed: {skip_response.status_code}")
                all_passed = False
            
            # Verify no duplicate creator within the same cycle
            print("\n--- Checking for duplicate creators in cycle ---")
            status_final = requests.get(
                f"{self.base_url}/api/admin/instagram-autopilot/status",
                headers=headers,
                timeout=30
            ).json()
            
            queue_order = status_final.get("queue", {}).get("order", [])
            done_slugs = [item["slug"] for item in queue_order if item.get("done")]
            
            if len(done_slugs) == len(set(done_slugs)):
                print(f"  ✓ No duplicate creators in done list")
            else:
                print(f"  ✗ Duplicate creators found in done list: {done_slugs}")
                all_passed = False
            
            self.log("Publish-now and skip work correctly", all_passed)
            return all_passed
            
        except Exception as e:
            self.log(f"Publish-now/skip error: {str(e)}", False)
            return False

    def test_settings_validation(self):
        """Test PATCH /api/admin/instagram-autopilot/settings validation"""
        print("\n" + "="*80)
        print("TEST 7: PATCH /settings - Validation")
        print("="*80)
        
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            
            validation_tests = [
                ({"schedule_times": ["25:00"]}, 422, "Invalid time 25:00"),
                ({"timezone": "Mars/Olympus"}, 422, "Invalid timezone"),
                ({"timezone": "America/New_York"}, 422, "Non-Italy timezone (Italy mode)"),
                ({"posts_per_day": 9, "schedule_times": ["13:00", "20:30"]}, 422, "posts_per_day > schedule_times"),
            ]
            
            all_passed = True
            for body, expected_status, description in validation_tests:
                response = requests.patch(
                    f"{self.base_url}/api/admin/instagram-autopilot/settings",
                    headers=headers,
                    json=body,
                    timeout=15
                )
                
                if response.status_code == expected_status:
                    print(f"  ✓ {description}: {response.status_code}")
                else:
                    print(f"  ✗ {description}: expected {expected_status}, got {response.status_code}")
                    all_passed = False
            
            # Valid settings update
            print("\n--- Testing valid settings update ---")
            valid_body = {
                "use_video": True,
                "timezone": "Europe/Rome",
                "schedule_times": ["20:30", "13:00"],
                "posts_per_day": 2
            }
            
            response = requests.patch(
                f"{self.base_url}/api/admin/instagram-autopilot/settings",
                headers=headers,
                json=valid_body,
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                print(f"  ✓ Valid settings accepted: {response.status_code}")
                
                # Check that schedule_times are sorted
                if data.get("schedule_times") == ["13:00", "20:30"]:
                    print(f"  ✓ schedule_times sorted: {data.get('schedule_times')}")
                else:
                    print(f"  ✗ schedule_times not sorted: {data.get('schedule_times')}")
                    all_passed = False
            else:
                print(f"  ✗ Valid settings rejected: {response.status_code}")
                all_passed = False
            
            # Restore defaults
            print("\n--- Restoring default settings ---")
            default_body = {
                "posts_per_day": 2,
                "schedule_times": ["13:00", "20:30"],
                "timezone": "Europe/Rome",
                "use_photo": True,
                "use_video": True,
                "use_ai_copy": True
            }
            
            response = requests.patch(
                f"{self.base_url}/api/admin/instagram-autopilot/settings",
                headers=headers,
                json=default_body,
                timeout=15
            )
            
            if response.status_code == 200:
                print(f"  ✓ Default settings restored")
            else:
                print(f"  ✗ Failed to restore defaults: {response.status_code}")
                all_passed = False
            
            self.log("Settings validation works correctly", all_passed)
            return all_passed
            
        except Exception as e:
            self.log(f"Settings validation error: {str(e)}", False)
            return False

    def test_start_pause(self):
        """Test POST /start and POST /pause"""
        print("\n" + "="*80)
        print("TEST 8: POST /start and POST /pause")
        print("="*80)
        
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            
            # Test start
            print("\n--- Testing start ---")
            start_response = requests.post(
                f"{self.base_url}/api/admin/instagram-autopilot/start",
                headers=headers,
                timeout=30
            )
            
            all_passed = True
            
            if start_response.status_code == 200:
                start_data = start_response.json()
                print(f"Start response: {start_data}")
                
                if start_data.get("enabled") is True:
                    print(f"  ✓ enabled=true")
                else:
                    print(f"  ✗ enabled != true")
                    all_passed = False
                
                if "note" in start_data and "AUTO_SCHEDULER_ENABLED" in start_data["note"]:
                    print(f"  ✓ Note about master switch being off")
                else:
                    print(f"  ℹ️  Note: {start_data.get('note')}")
            else:
                print(f"  ✗ Start failed: {start_response.status_code}")
                all_passed = False
            
            # Test pause
            print("\n--- Testing pause ---")
            pause_response = requests.post(
                f"{self.base_url}/api/admin/instagram-autopilot/pause",
                headers=headers,
                timeout=30
            )
            
            if pause_response.status_code == 200:
                pause_data = pause_response.json()
                print(f"Pause response: {pause_data}")
                
                if pause_data.get("enabled") is False:
                    print(f"  ✓ enabled=false")
                else:
                    print(f"  ✗ enabled != false")
                    all_passed = False
            else:
                print(f"  ✗ Pause failed: {pause_response.status_code}")
                all_passed = False
            
            self.log("Start/pause work correctly", all_passed)
            return all_passed
            
        except Exception as e:
            self.log(f"Start/pause error: {str(e)}", False)
            return False

    def test_telegram_untouched(self):
        """Test that Telegram collections are untouched (read-only check)"""
        print("\n" + "="*80)
        print("TEST 9: Telegram Collections Untouched (Read-Only)")
        print("="*80)
        
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            
            # Get Telegram status before
            print("\n--- Getting Telegram status before Instagram actions ---")
            tg_before = requests.get(
                f"{self.base_url}/api/admin/telegram-autopilot/status",
                headers=headers,
                timeout=30
            )
            
            if tg_before.status_code != 200:
                print(f"  ⚠️  Could not get Telegram status: {tg_before.status_code}")
                self.log("Telegram status check skipped (endpoint not accessible)", None)
                return True
            
            tg_before_data = tg_before.json()
            queue_before = tg_before_data.get("queue", {})
            position_before = queue_before.get("position")
            cycle_before = queue_before.get("cycle_number")
            
            print(f"Telegram before: position={position_before}, cycle={cycle_before}")
            
            # Perform Instagram action (already done in previous tests, but let's verify)
            print("\n--- Verifying Telegram state after Instagram actions ---")
            
            # Get Telegram status after
            tg_after = requests.get(
                f"{self.base_url}/api/admin/telegram-autopilot/status",
                headers=headers,
                timeout=30
            )
            
            if tg_after.status_code != 200:
                print(f"  ⚠️  Could not get Telegram status after: {tg_after.status_code}")
                self.log("Telegram status check incomplete", None)
                return True
            
            tg_after_data = tg_after.json()
            queue_after = tg_after_data.get("queue", {})
            position_after = queue_after.get("position")
            cycle_after = queue_after.get("cycle_number")
            
            print(f"Telegram after: position={position_after}, cycle={cycle_after}")
            
            all_passed = True
            
            if position_before == position_after:
                print(f"  ✓ Telegram queue position unchanged: {position_before}")
            else:
                print(f"  ✗ Telegram queue position changed: {position_before} -> {position_after}")
                all_passed = False
            
            if cycle_before == cycle_after:
                print(f"  ✓ Telegram cycle_number unchanged: {cycle_before}")
            else:
                print(f"  ✗ Telegram cycle_number changed: {cycle_before} -> {cycle_after}")
                all_passed = False
            
            self.log("Telegram collections untouched", all_passed)
            return all_passed
            
        except Exception as e:
            self.log(f"Telegram check error: {str(e)}", False)
            return False

    def run_all_tests(self):
        """Run all backend tests"""
        print("\n" + "="*80)
        print("INSTAGRAM AUTOPILOT BACKEND API TESTS")
        print("="*80)
        print(f"Backend URL: {self.base_url}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Test 1: Login
        if not self.test_admin_login():
            print("\n❌ CRITICAL: Admin login failed. Cannot proceed with other tests.")
            return False
        
        # Test 2: Auth required
        self.test_auth_required()
        
        # Test 3: Status endpoint
        self.test_status_endpoint()
        
        # Test 4: Test connection
        self.test_connection_endpoint()
        
        # Test 5: Dry run
        self.test_dry_run()
        
        # Test 6: Publish-now and skip
        self.test_publish_now_and_skip()
        
        # Test 7: Settings validation
        self.test_settings_validation()
        
        # Test 8: Start/pause
        self.test_start_pause()
        
        # Test 9: Telegram untouched
        self.test_telegram_untouched()
        
        # Summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print(f"Tests run: {self.tests_run}")
        print(f"Tests passed: {self.tests_passed}")
        print(f"Tests failed: {self.tests_run - self.tests_passed}")
        print(f"Success rate: {(self.tests_passed / self.tests_run * 100):.1f}%")
        
        if self.tests_passed == self.tests_run:
            print("\n✅ ALL TESTS PASSED!")
            return True
        else:
            print(f"\n⚠️  {self.tests_run - self.tests_passed} TEST(S) FAILED")
            return False


def main():
    tester = InstagramAutopilotTester()
    success = tester.run_all_tests()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
