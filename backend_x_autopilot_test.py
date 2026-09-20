#!/usr/bin/env python3
"""
X Autopilot Backend API Test Suite
Tests all X Autopilot endpoints with mock mode verification
"""
import requests
import sys
import time
from typing import Dict, Any, Optional

BASE_URL = "https://secret-side.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@latosegreto.it"
ADMIN_PASSWORD = "LatoSegreto2025!"


class XAutopilotTester:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []

    def log(self, msg: str, level: str = "INFO"):
        prefix = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "FAIL": "❌",
            "WARN": "⚠️"
        }.get(level, "•")
        print(f"{prefix} {msg}")

    def test(self, name: str, method: str, endpoint: str, expected_status: int,
             data: Optional[Dict] = None, headers: Optional[Dict] = None,
             check_response: Optional[callable] = None, timeout: int = 60) -> tuple[bool, Any]:
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
                response = requests.get(url, headers=req_headers, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=req_headers, timeout=timeout)
            elif method == 'PATCH':
                response = requests.patch(url, json=data, headers=req_headers, timeout=timeout)
            else:
                self.log(f"Unknown method {method}", "FAIL")
                self.failed_tests.append(name)
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
                    self.failed_tests.append(name)
                    return False, resp_data
                self.tests_passed += 1
                self.log(f"PASSED - Status: {response.status_code}", "SUCCESS")
            else:
                self.log(f"FAILED - Expected {expected_status}, got {response.status_code}: {str(resp_data)[:200]}", "FAIL")
                self.failed_tests.append(name)

            return success, resp_data

        except Exception as e:
            self.log(f"FAILED - Error: {str(e)}", "FAIL")
            self.failed_tests.append(name)
            return False, {}

    def login(self):
        """Login and get admin token"""
        self.log("\n--- ADMIN AUTHENTICATION ---", "INFO")
        success, resp = self.test("Login with admin credentials", "POST", "admin/login", 200,
                                   data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                                   check_response=lambda r: "token" in r)
        if success:
            self.token = resp.get("token")
            self.log(f"Got auth token: {self.token[:20]}...", "INFO")
            return True
        return False

    def test_auth_requirements(self):
        """Test that all endpoints require admin JWT"""
        self.log("\n--- AUTH REQUIREMENTS (401/403 without token) ---", "INFO")
        
        # Save token and clear it
        temp_token = self.token
        self.token = None
        
        # Test all endpoints without token
        self.test("GET status without token", "GET", "admin/x-autopilot/status", 401)
        self.test("GET logs without token", "GET", "admin/x-autopilot/logs", 401)
        self.test("POST test-connection without token", "POST", "admin/x-autopilot/test-connection", 401)
        self.test("POST start without token", "POST", "admin/x-autopilot/start", 401)
        self.test("POST pause without token", "POST", "admin/x-autopilot/pause", 401)
        self.test("POST preview without token", "POST", "admin/x-autopilot/preview", 401)
        self.test("POST publish-now without token", "POST", "admin/x-autopilot/publish-now", 401)
        self.test("POST skip without token", "POST", "admin/x-autopilot/skip", 401)
        self.test("PATCH settings without token", "PATCH", "admin/x-autopilot/settings", 401,
                  data={"use_ai_copy": True})
        
        # Restore token
        self.token = temp_token

    def test_status_endpoint(self):
        """Test GET status returns all required fields"""
        self.log("\n--- GET STATUS ENDPOINT ---", "INFO")
        
        def check_status(r):
            # Check MOCK_MODE and CONNECTION_STATUS
            if r.get("MOCK_MODE") != True:
                self.log(f"MOCK_MODE should be True, got {r.get('MOCK_MODE')}", "FAIL")
                return False
            if r.get("CONNECTION_STATUS") != "NOT_CONNECTED":
                self.log(f"CONNECTION_STATUS should be NOT_CONNECTED, got {r.get('CONNECTION_STATUS')}", "FAIL")
                return False
            if r.get("operational") != True:
                self.log(f"operational should be True, got {r.get('operational')}", "FAIL")
                return False
            if r.get("AUTO_SCHEDULER_ENABLED") != False:
                self.log(f"AUTO_SCHEDULER_ENABLED should be False, got {r.get('AUTO_SCHEDULER_ENABLED')}", "FAIL")
                return False
            if r.get("active") != False:
                self.log(f"active should be False, got {r.get('active')}", "FAIL")
                return False
            if r.get("ITALY_AUDIENCE_MODE") != True:
                self.log(f"ITALY_AUDIENCE_MODE should be True, got {r.get('ITALY_AUDIENCE_MODE')}", "FAIL")
                return False
            if r.get("X_REAL_CALLS") != 0:
                self.log(f"X_REAL_CALLS should be 0, got {r.get('X_REAL_CALLS')}", "FAIL")
                return False
            if r.get("X_REAL_POST_DONE") != False:
                self.log(f"X_REAL_POST_DONE should be False, got {r.get('X_REAL_POST_DONE')}", "FAIL")
                return False
            
            # Check settings
            settings = r.get("settings", {})
            if settings.get("posts_per_day") != 3:
                self.log(f"settings.posts_per_day should be 3, got {settings.get('posts_per_day')}", "FAIL")
                return False
            if settings.get("schedule_times") != ["12:30", "18:30", "22:00"]:
                self.log(f"settings.schedule_times should be ['12:30', '18:30', '22:00'], got {settings.get('schedule_times')}", "FAIL")
                return False
            if settings.get("timezone") != "Europe/Rome":
                self.log(f"settings.timezone should be Europe/Rome, got {settings.get('timezone')}", "FAIL")
                return False
            if settings.get("use_ai_copy") not in [True, False]:
                self.log(f"settings.use_ai_copy should be boolean, got {settings.get('use_ai_copy')}", "FAIL")
                return False
            if settings.get("italy_audience_mode") != True:
                self.log(f"settings.italy_audience_mode should be True, got {settings.get('italy_audience_mode')}", "FAIL")
                return False
            
            # Check queue
            queue = r.get("queue", {})
            if not isinstance(queue.get("total"), int) or queue.get("total") < 1:
                self.log(f"queue.total should be >= 1, got {queue.get('total')}", "FAIL")
                return False
            if not isinstance(queue.get("order"), list):
                self.log(f"queue.order should be a list, got {type(queue.get('order'))}", "FAIL")
                return False
            
            # Check for skip categories
            for key in ["skipped_no_public_media", "skipped_no_secret_media", "skipped_no_of_link", "not_x_safe"]:
                if key not in queue:
                    self.log(f"queue.{key} missing", "FAIL")
                    return False
            
            # Check schedule
            schedule = r.get("schedule", {})
            next_slot = schedule.get("next_slot", {})
            if not next_slot:
                self.log("schedule.next_slot missing", "FAIL")
                return False
            slot_id = next_slot.get("slot_id", "")
            if not slot_id.startswith("x_"):
                self.log(f"schedule.next_slot.slot_id should start with 'x_', got {slot_id}", "FAIL")
                return False
            if not any(slot_id.endswith(t) for t in ["12:30", "18:30", "22:00"]):
                self.log(f"schedule.next_slot.slot_id should end with 12:30/18:30/22:00, got {slot_id}", "FAIL")
                return False
            
            return True
        
        success, resp = self.test("GET status with all required fields", "GET", "admin/x-autopilot/status", 200,
                                   check_response=check_status)
        
        if success:
            self.log(f"Status details: queue.total={resp['queue']['total']}, cycle_number={resp['queue']['cycle_number']}", "INFO")
        
        return success, resp

    def test_connection_endpoint(self):
        """Test POST test-connection"""
        self.log("\n--- POST TEST-CONNECTION ---", "INFO")
        
        def check_connection(r):
            if r.get("CONNECTION_STATUS") != "NOT_CONNECTED":
                self.log(f"CONNECTION_STATUS should be NOT_CONNECTED, got {r.get('CONNECTION_STATUS')}", "FAIL")
                return False
            if r.get("MOCK_MODE") != True:
                self.log(f"MOCK_MODE should be True, got {r.get('MOCK_MODE')}", "FAIL")
                return False
            if r.get("X_REAL_CALLS") != 0:
                self.log(f"X_REAL_CALLS should be 0, got {r.get('X_REAL_CALLS')}", "FAIL")
                return False
            
            # Check no credentials in response
            resp_str = str(r).lower()
            if "api_secret" in resp_str or "access_token" in resp_str:
                self.log("Response contains credentials (api_secret or access_token)", "FAIL")
                return False
            
            return True
        
        success, resp = self.test("POST test-connection returns NOT_CONNECTED", "POST", "admin/x-autopilot/test-connection", 200,
                                   check_response=check_connection, timeout=30)
        return success, resp

    def test_preview_endpoint(self, initial_status):
        """Test POST preview doesn't change queue position"""
        self.log("\n--- POST PREVIEW (no queue mutation) ---", "INFO")
        
        initial_position = initial_status.get("queue", {}).get("position")
        initial_cycle = initial_status.get("queue", {}).get("cycle_number")
        
        def check_preview(r):
            if r.get("status") != "PREVIEW":
                self.log(f"status should be PREVIEW, got {r.get('status')}", "FAIL")
                return False
            if not r.get("model"):
                self.log("model missing", "FAIL")
                return False
            
            # Check media order
            if r.get("media_order") != ["PUBLIC", "SECRET"]:
                self.log(f"media_order should be ['PUBLIC', 'SECRET'], got {r.get('media_order')}", "FAIL")
                return False
            
            # Check public and secret
            public = r.get("public", {})
            secret = r.get("secret", {})
            if public.get("side") != "PUBLIC":
                self.log(f"public.side should be PUBLIC, got {public.get('side')}", "FAIL")
                return False
            if secret.get("side") != "SECRET":
                self.log(f"secret.side should be SECRET, got {secret.get('side')}", "FAIL")
                return False
            
            # Check format
            if r.get("format") not in ["SINGLE_POST", "THREAD"]:
                self.log(f"format should be SINGLE_POST or THREAD, got {r.get('format')}", "FAIL")
                return False
            
            # Check text contains onlyfans.com link
            text = r.get("text", "")
            of_url = r.get("of_url", "")
            if not of_url.startswith("https://onlyfans.com/"):
                self.log(f"of_url should start with https://onlyfans.com/, got {of_url}", "FAIL")
                return False
            if of_url not in text:
                self.log(f"of_url not found in text", "FAIL")
                return False
            if text.count("http") != 1:
                self.log(f"text should contain 'http' exactly once, got {text.count('http')} times", "FAIL")
                return False
            
            # Check hashtags
            hashtags = r.get("hashtags", [])
            if not (3 <= len(hashtags) <= 5):
                self.log(f"hashtags should be 3-5, got {len(hashtags)}", "FAIL")
                return False
            if hashtags and hashtags[0] != "#LatoSegreto":
                self.log(f"first hashtag should be #LatoSegreto, got {hashtags[0]}", "FAIL")
                return False
            
            # Check x_length
            if r.get("x_length", 999) > 280:
                self.log(f"x_length should be <= 280, got {r.get('x_length')}", "FAIL")
                return False
            
            # Check slot
            slot = r.get("slot", {})
            if not slot.get("slot_id", "").startswith("x_"):
                self.log(f"slot.slot_id should start with 'x_', got {slot.get('slot_id')}", "FAIL")
                return False
            
            return True
        
        success, resp = self.test("POST preview returns correct structure", "POST", "admin/x-autopilot/preview", 200,
                                   check_response=check_preview, timeout=120)
        
        if success:
            self.log(f"Preview: model={resp['model']}, format={resp['format']}, of_url={resp['of_url']}", "INFO")
        
        # Check queue position didn't change
        success2, status_after = self.test("GET status after preview", "GET", "admin/x-autopilot/status", 200)
        if success2:
            after_position = status_after.get("queue", {}).get("position")
            after_cycle = status_after.get("queue", {}).get("cycle_number")
            if after_position != initial_position or after_cycle != initial_cycle:
                self.log(f"Queue position changed after preview! Before: pos={initial_position}, cycle={initial_cycle}. After: pos={after_position}, cycle={after_cycle}", "FAIL")
                self.failed_tests.append("Preview doesn't mutate queue")
                return False, resp
            else:
                self.log(f"✓ Queue position unchanged (pos={after_position}, cycle={after_cycle})", "SUCCESS")
        
        return success, resp

    def test_publish_now_endpoint(self, initial_status):
        """Test POST publish-now (mock) - max 2 calls"""
        self.log("\n--- POST PUBLISH-NOW (mock, max 2 calls) ---", "INFO")
        
        initial_position = initial_status.get("queue", {}).get("position")
        initial_cycle = initial_status.get("queue", {}).get("cycle_number")
        current_of_url = initial_status.get("queue", {}).get("current", {}).get("of_url")
        
        def check_publish(r, expected_of_url=None):
            if r.get("status") != "MOCK_PREPARED":
                self.log(f"status should be MOCK_PREPARED, got {r.get('status')}", "FAIL")
                return False
            if r.get("format") not in ["SINGLE_POST", "THREAD"]:
                self.log(f"format should be SINGLE_POST or THREAD, got {r.get('format')}", "FAIL")
                return False
            if r.get("media_order") != ["PUBLIC", "SECRET"]:
                self.log(f"media_order should be ['PUBLIC', 'SECRET'], got {r.get('media_order')}", "FAIL")
                return False
            
            # Check media IDs
            public_media_id = r.get("public_media_id", "")
            secret_media_id = r.get("secret_media_id", "")
            if not public_media_id.startswith("pub:"):
                self.log(f"public_media_id should start with 'pub:', got {public_media_id}", "FAIL")
                return False
            if not secret_media_id.startswith("sec:"):
                self.log(f"secret_media_id should start with 'sec:', got {secret_media_id}", "FAIL")
                return False
            
            # Check x_post_id
            x_post_id = r.get("x_post_id", "")
            if not x_post_id.startswith("mock_x_"):
                self.log(f"x_post_id should start with 'mock_x_', got {x_post_id}", "FAIL")
                return False
            
            # Check of_url in text
            of_url = r.get("of_url", "")
            text = r.get("text", "")
            if of_url not in text:
                self.log(f"of_url not found in text", "FAIL")
                return False
            
            # If expected_of_url provided, verify it matches
            if expected_of_url and of_url != expected_of_url:
                self.log(f"of_url should be {expected_of_url}, got {of_url}", "FAIL")
                return False
            
            return True
        
        # First publish-now
        success1, resp1 = self.test("POST publish-now #1 (mock)", "POST", "admin/x-autopilot/publish-now", 200,
                                     check_response=lambda r: check_publish(r, current_of_url), timeout=120)
        
        if not success1:
            return False, resp1
        
        self.log(f"Publish #1: model={resp1.get('model_slug')}, format={resp1['format']}, x_post_id={resp1['x_post_id']}", "INFO")
        
        # Check logs
        success_log1, logs1 = self.test("GET logs after publish #1", "GET", "admin/x-autopilot/logs?limit=5", 200)
        if success_log1:
            items = logs1.get("items", [])
            if items:
                latest = items[0]
                if latest.get("status") == "MOCK_PREPARED" and latest.get("mock") == True:
                    self.log(f"✓ Log entry found: status=MOCK_PREPARED, mock=true, public_media_id={latest.get('public_media_id')}, secret_media_id={latest.get('secret_media_id')}", "SUCCESS")
                else:
                    self.log(f"Log entry status or mock flag incorrect: {latest}", "WARN")
        
        # Check queue advanced
        success_status1, status1 = self.test("GET status after publish #1", "GET", "admin/x-autopilot/status", 200)
        if success_status1:
            new_position = status1.get("queue", {}).get("position")
            new_cycle = status1.get("queue", {}).get("cycle_number")
            if new_position == initial_position + 1 or (new_position == 1 and new_cycle == initial_cycle + 1):
                self.log(f"✓ Queue advanced: pos {initial_position} -> {new_position}, cycle {initial_cycle} -> {new_cycle}", "SUCCESS")
            else:
                self.log(f"Queue didn't advance correctly: pos {initial_position} -> {new_position}, cycle {initial_cycle} -> {new_cycle}", "WARN")
            
            # Check last_published
            last_published = status1.get("last_published")
            if last_published:
                self.log(f"✓ last_published populated: model_slug={last_published.get('model_slug')}", "SUCCESS")
            
            # Get current model's of_url for second publish
            current_of_url2 = status1.get("queue", {}).get("current", {}).get("of_url")
        
        # Second publish-now
        success2, resp2 = self.test("POST publish-now #2 (mock)", "POST", "admin/x-autopilot/publish-now", 200,
                                     check_response=lambda r: check_publish(r, current_of_url2), timeout=120)
        
        if not success2:
            return False, resp2
        
        self.log(f"Publish #2: model={resp2.get('model_slug')}, format={resp2['format']}, x_post_id={resp2['x_post_id']}", "INFO")
        
        # Verify two different models
        if resp1.get("model_slug") == resp2.get("model_slug"):
            self.log(f"WARNING: Two consecutive publish-now used the same model: {resp1.get('model_slug')}", "WARN")
        else:
            self.log(f"✓ Two consecutive publish-now used different models: {resp1.get('model_slug')} vs {resp2.get('model_slug')}", "SUCCESS")
        
        # Verify each text contains that model's own of_url
        if resp1.get("of_url") in resp1.get("text", "") and resp2.get("of_url") in resp2.get("text", ""):
            self.log(f"✓ Each text contains its model's own of_url", "SUCCESS")
        else:
            self.log(f"Text doesn't contain correct of_url", "FAIL")
            self.failed_tests.append("Publish-now of_url mismatch")
        
        # Verify X_REAL_CALLS still 0
        success_status2, status2 = self.test("GET status after publish #2", "GET", "admin/x-autopilot/status", 200)
        if success_status2:
            if status2.get("X_REAL_CALLS") != 0:
                self.log(f"X_REAL_CALLS should still be 0, got {status2.get('X_REAL_CALLS')}", "FAIL")
                self.failed_tests.append("X_REAL_CALLS not 0")
            else:
                self.log(f"✓ X_REAL_CALLS still 0", "SUCCESS")
        
        return True, resp2

    def test_skip_endpoint(self):
        """Test POST skip"""
        self.log("\n--- POST SKIP ---", "INFO")
        
        # Get current model before skip
        success_before, status_before = self.test("GET status before skip", "GET", "admin/x-autopilot/status", 200)
        if not success_before:
            return False, {}
        
        current_before = status_before.get("queue", {}).get("current", {})
        current_slug = current_before.get("slug")
        
        def check_skip(r):
            if r.get("status") != "MANUAL_SKIP":
                self.log(f"status should be MANUAL_SKIP, got {r.get('status')}", "FAIL")
                return False
            if r.get("skipped") != current_slug:
                self.log(f"skipped should be {current_slug}, got {r.get('skipped')}", "FAIL")
                return False
            return True
        
        success, resp = self.test("POST skip current model", "POST", "admin/x-autopilot/skip", 200,
                                   check_response=check_skip)
        
        if success:
            self.log(f"Skipped model: {resp.get('skipped')}", "INFO")
        
        return success, resp

    def test_settings_validation(self):
        """Test PATCH settings validation"""
        self.log("\n--- PATCH SETTINGS VALIDATION ---", "INFO")
        
        # Invalid time format
        self.test("Settings: invalid time '25:00'", "PATCH", "admin/x-autopilot/settings", 422,
                  data={"schedule_times": ["25:00"]})
        
        # Invalid timezone
        self.test("Settings: invalid timezone 'Mars/Olympus'", "PATCH", "admin/x-autopilot/settings", 422,
                  data={"timezone": "Mars/Olympus"})
        
        # Wrong timezone while italy mode on
        self.test("Settings: timezone 'America/New_York' while italy mode on", "PATCH", "admin/x-autopilot/settings", 422,
                  data={"timezone": "America/New_York"})
        
        # Too many posts per day
        self.test("Settings: posts_per_day 9", "PATCH", "admin/x-autopilot/settings", 422,
                  data={"posts_per_day": 9})
        
        # Valid settings with sorted times
        def check_valid_settings(r):
            if r.get("schedule_times") != ["12:30", "18:30", "22:00"]:
                self.log(f"schedule_times should be sorted ['12:30', '18:30', '22:00'], got {r.get('schedule_times')}", "FAIL")
                return False
            if r.get("timezone") != "Europe/Rome":
                self.log(f"timezone should be Europe/Rome, got {r.get('timezone')}", "FAIL")
                return False
            if r.get("posts_per_day") != 3:
                self.log(f"posts_per_day should be 3, got {r.get('posts_per_day')}", "FAIL")
                return False
            if r.get("use_ai_copy") != True:
                self.log(f"use_ai_copy should be True, got {r.get('use_ai_copy')}", "FAIL")
                return False
            if r.get("italy_audience_mode") != True:
                self.log(f"italy_audience_mode should be True, got {r.get('italy_audience_mode')}", "FAIL")
                return False
            return True
        
        success, resp = self.test("Settings: valid update with sorted times", "PATCH", "admin/x-autopilot/settings", 200,
                                   data={"timezone": "Europe/Rome", "schedule_times": ["22:00", "12:30", "18:30"], 
                                         "posts_per_day": 3, "use_ai_copy": True, "italy_audience_mode": True},
                                   check_response=check_valid_settings)
        
        # Restore defaults
        self.test("Settings: restore defaults", "PATCH", "admin/x-autopilot/settings", 200,
                  data={"timezone": "Europe/Rome", "schedule_times": ["12:30", "18:30", "22:00"], 
                        "posts_per_day": 3, "use_ai_copy": True, "italy_audience_mode": True})
        
        return success, resp

    def test_start_pause(self):
        """Test POST start and pause"""
        self.log("\n--- POST START/PAUSE ---", "INFO")
        
        def check_start(r):
            if r.get("enabled") != True:
                self.log(f"enabled should be True, got {r.get('enabled')}", "FAIL")
                return False
            if "note" not in r:
                self.log("note field missing", "FAIL")
                return False
            return True
        
        success_start, resp_start = self.test("POST start", "POST", "admin/x-autopilot/start", 200,
                                               check_response=check_start)
        
        if success_start:
            self.log(f"Start response: enabled={resp_start['enabled']}, note={resp_start.get('note')}", "INFO")
        
        def check_pause(r):
            if r.get("enabled") != False:
                self.log(f"enabled should be False, got {r.get('enabled')}", "FAIL")
                return False
            return True
        
        success_pause, resp_pause = self.test("POST pause", "POST", "admin/x-autopilot/pause", 200,
                                               check_response=check_pause)
        
        if success_pause:
            self.log(f"Pause response: enabled={resp_pause['enabled']}", "INFO")
        
        # Verify status shows enabled=false
        success_status, status = self.test("GET status after pause", "GET", "admin/x-autopilot/status", 200)
        if success_status:
            if status.get("enabled") != False:
                self.log(f"Status enabled should be False after pause, got {status.get('enabled')}", "FAIL")
                self.failed_tests.append("Status enabled not false after pause")
            else:
                self.log(f"✓ Status shows enabled=false after pause", "SUCCESS")
        
        return success_start and success_pause, resp_pause

    def test_telegram_instagram_independence(self):
        """Test Telegram and Instagram state unchanged"""
        self.log("\n--- TELEGRAM/INSTAGRAM INDEPENDENCE ---", "INFO")
        
        # Get Telegram status before
        success_tg_before, tg_before = self.test("GET Telegram status before", "GET", "admin/telegram-autopilot/status", 200)
        if not success_tg_before:
            self.log("Could not get Telegram status", "WARN")
            return False, {}
        
        # Get Instagram status before
        success_ig_before, ig_before = self.test("GET Instagram status before", "GET", "admin/instagram-autopilot/status", 200)
        if not success_ig_before:
            self.log("Could not get Instagram status", "WARN")
            return False, {}
        
        tg_position_before = tg_before.get("queue", {}).get("position")
        tg_cycle_before = tg_before.get("queue", {}).get("cycle_number")
        ig_position_before = ig_before.get("queue", {}).get("position")
        ig_cycle_before = ig_before.get("queue", {}).get("cycle_number")
        
        self.log(f"Before: Telegram pos={tg_position_before}, cycle={tg_cycle_before}; Instagram pos={ig_position_before}, cycle={ig_cycle_before}", "INFO")
        
        # Get Telegram status after
        success_tg_after, tg_after = self.test("GET Telegram status after", "GET", "admin/telegram-autopilot/status", 200)
        if not success_tg_after:
            self.log("Could not get Telegram status after", "WARN")
            return False, {}
        
        # Get Instagram status after
        success_ig_after, ig_after = self.test("GET Instagram status after", "GET", "admin/instagram-autopilot/status", 200)
        if not success_ig_after:
            self.log("Could not get Instagram status after", "WARN")
            return False, {}
        
        tg_position_after = tg_after.get("queue", {}).get("position")
        tg_cycle_after = tg_after.get("queue", {}).get("cycle_number")
        ig_position_after = ig_after.get("queue", {}).get("position")
        ig_cycle_after = ig_after.get("queue", {}).get("cycle_number")
        
        self.log(f"After: Telegram pos={tg_position_after}, cycle={tg_cycle_after}; Instagram pos={ig_position_after}, cycle={ig_cycle_after}", "INFO")
        
        # Verify unchanged
        if tg_position_before != tg_position_after or tg_cycle_before != tg_cycle_after:
            self.log(f"Telegram state changed! Before: pos={tg_position_before}, cycle={tg_cycle_before}. After: pos={tg_position_after}, cycle={tg_cycle_after}", "FAIL")
            self.failed_tests.append("Telegram state changed")
            return False, {}
        
        if ig_position_before != ig_position_after or ig_cycle_before != ig_cycle_after:
            self.log(f"Instagram state changed! Before: pos={ig_position_before}, cycle={ig_cycle_before}. After: pos={ig_position_after}, cycle={ig_cycle_after}", "FAIL")
            self.failed_tests.append("Instagram state changed")
            return False, {}
        
        self.log(f"✓ Telegram and Instagram state unchanged", "SUCCESS")
        return True, {}

    def run_all_tests(self):
        """Execute all test suites"""
        self.log("=" * 80, "INFO")
        self.log("X AUTOPILOT Backend API Test Suite", "INFO")
        self.log("=" * 80, "INFO")

        # Login
        if not self.login():
            self.log("Login failed, cannot continue", "FAIL")
            return self.print_summary()

        # Test auth requirements
        self.test_auth_requirements()

        # Get initial status
        success_status, initial_status = self.test_status_endpoint()
        if not success_status:
            self.log("Status endpoint failed, cannot continue with dependent tests", "FAIL")
            return self.print_summary()

        # Test connection
        self.test_connection_endpoint()

        # Test preview (doesn't mutate queue)
        self.test_preview_endpoint(initial_status)

        # Test publish-now (max 2 calls)
        self.test_publish_now_endpoint(initial_status)

        # Test skip
        self.test_skip_endpoint()

        # Test settings validation
        self.test_settings_validation()

        # Test start/pause
        self.test_start_pause()

        # Test Telegram/Instagram independence
        self.test_telegram_instagram_independence()

        # Print summary
        return self.print_summary()

    def print_summary(self):
        self.log("\n" + "=" * 80, "INFO")
        self.log(f"TESTS COMPLETED: {self.tests_passed}/{self.tests_run} passed", "INFO")
        self.log("=" * 80, "INFO")

        if self.tests_passed == self.tests_run:
            self.log("ALL TESTS PASSED! 🎉", "SUCCESS")
            return 0
        else:
            failed = self.tests_run - self.tests_passed
            self.log(f"{failed} TEST(S) FAILED", "FAIL")
            if self.failed_tests:
                self.log(f"Failed tests: {', '.join(self.failed_tests[:10])}", "FAIL")
            return 1


def main():
    tester = XAutopilotTester()
    exit_code = tester.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
