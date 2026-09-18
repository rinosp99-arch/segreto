"""SEO Autopilot Backend API Testing - Phase 14 READ_ONLY mode
Tests authentication, mode verification, read endpoints, write guards, and zero-mutation guarantee.
"""
import requests
import sys
import time
import re
from datetime import datetime

class SeoAutopilotTester:
    def __init__(self, base_url="https://secret-side.preview.emergentagent.com"):
        self.base_url = base_url.rstrip('/')
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.admin_email = "admin@latosegreto.it"
        self.admin_password = "LatoSegreto2025!"
        
    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None, auth_required=True):
        """Run a single API test"""
        url = f"{self.base_url}{endpoint}"
        req_headers = {'Content-Type': 'application/json'}
        if headers:
            req_headers.update(headers)
        if auth_required and self.token:
            req_headers['Authorization'] = f'Bearer {self.token}'
        
        self.tests_run += 1
        print(f"\n🔍 Test {self.tests_run}: {name}")
        print(f"   {method} {endpoint}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=req_headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=req_headers, timeout=30)
            
            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"   ✅ PASS - Status: {response.status_code}")
                try:
                    return True, response.json()
                except:
                    return True, response.text
            else:
                print(f"   ❌ FAIL - Expected {expected_status}, got {response.status_code}")
                try:
                    print(f"   Response: {response.json()}")
                except:
                    print(f"   Response: {response.text[:200]}")
                return False, {}
        
        except Exception as e:
            print(f"   ❌ FAIL - Error: {str(e)}")
            return False, {}
    
    def test_admin_login(self):
        """Test admin login and get JWT token"""
        print("\n" + "="*80)
        print("AUTHENTICATION TESTS")
        print("="*80)
        
        success, response = self.run_test(
            "Admin Login",
            "POST",
            "/api/admin/login",
            200,
            data={"email": self.admin_email, "password": self.admin_password},
            auth_required=False
        )
        
        if success and 'token' in response:
            self.token = response['token']
            print(f"   🔑 Token obtained: {self.token[:20]}...")
            return True
        return False
    
    def test_status_without_auth(self):
        """Test status endpoint without authentication - should fail"""
        # Temporarily remove token
        temp_token = self.token
        self.token = None
        
        success, _ = self.run_test(
            "Status without auth (should fail)",
            "GET",
            "/api/admin/seo-autopilot/status",
            401,
            auth_required=False
        )
        
        self.token = temp_token
        return success
    
    def test_status_with_auth(self):
        """Test status endpoint with authentication"""
        print("\n" + "="*80)
        print("MODE & STATUS VERIFICATION")
        print("="*80)
        
        success, response = self.run_test(
            "Status with admin auth",
            "GET",
            "/api/admin/seo-autopilot/status",
            200
        )
        
        if success:
            print(f"\n   📊 Status Response:")
            print(f"      Mode: {response.get('mode', {}).get('mode')}")
            print(f"      Full Locked: {response.get('mode', {}).get('full_locked')}")
            print(f"      Can Write Public: {response.get('mode', {}).get('can_write_public')}")
            print(f"      GSC Status: {response.get('GSC_STATUS')}")
            print(f"      LLM Source Label: {response.get('llm', {}).get('source_label')}")
            print(f"      Render Budget Daily: {response.get('render_budget', {}).get('daily')}")
            print(f"      Public Mutations Last: {response.get('PUBLIC_MUTATIONS_last')}")
            
            # Verify critical constraints
            mode_info = response.get('mode', {})
            if mode_info.get('mode') != 'READ_ONLY':
                print(f"   ⚠️  WARNING: Mode is {mode_info.get('mode')}, expected READ_ONLY")
            if not mode_info.get('full_locked'):
                print(f"   ⚠️  WARNING: FULL is not locked!")
            if mode_info.get('can_write_public'):
                print(f"   ⚠️  WARNING: can_write_public is True!")
            if response.get('llm', {}).get('source_label') != 'LLM_SUGGESTION':
                print(f"   ⚠️  WARNING: LLM source_label is not 'LLM_SUGGESTION'")
            
            # Check for credentials in response
            response_str = str(response)
            if 'EMERGENT_LLM_KEY' in response_str or 'sk-emergent' in response_str or 'private_key' in response_str:
                print(f"   ⚠️  WARNING: Response may contain credentials!")
        
        return success
    
    def test_read_endpoints(self):
        """Test all read endpoints return 200"""
        print("\n" + "="*80)
        print("READ ENDPOINTS TESTS")
        print("="*80)
        
        endpoints = [
            "/api/admin/seo-autopilot/opportunities",
            "/api/admin/seo-autopilot/clusters",
            "/api/admin/seo-autopilot/keywords",
            "/api/admin/seo-autopilot/page-map",
            "/api/admin/seo-autopilot/proposals",
            "/api/admin/seo-autopilot/cannibalization",
            "/api/admin/seo-autopilot/backlog",
            "/api/admin/seo-autopilot/tech",
            "/api/admin/seo-autopilot/render",
            "/api/admin/seo-autopilot/adult",
            "/api/admin/seo-autopilot/log",
            "/api/admin/seo-autopilot/runs",
            "/api/admin/seo-autopilot/matrix",
            "/api/admin/seo-autopilot/gsc/compare?by=query&days=7",
            "/api/admin/seo-autopilot/snapshot",
        ]
        
        all_passed = True
        for endpoint in endpoints:
            success, _ = self.run_test(
                f"GET {endpoint}",
                "GET",
                endpoint,
                200
            )
            if not success:
                all_passed = False
        
        return all_passed
    
    def test_write_guard(self):
        """Test that write operations are blocked (423)"""
        print("\n" + "="*80)
        print("WRITE GUARD TESTS (should all return 423)")
        print("="*80)
        
        # Test execute endpoint - should be blocked
        success, response = self.run_test(
            "POST /execute/test-proposal (should be blocked)",
            "POST",
            "/api/admin/seo-autopilot/execute/test-proposal",
            423
        )
        
        if success:
            print(f"   ✅ Write guard is active - execution blocked")
        
        # Test non-existent run endpoint
        success2, _ = self.run_test(
            "POST /run/inesistente (should 404)",
            "POST",
            "/api/admin/seo-autopilot/run/inesistente",
            404
        )
        
        return success and success2
    
    def capture_public_resources(self):
        """Capture public resources for mutation check"""
        print("\n   📸 Capturing public resources...")
        resources = {}
        
        try:
            # Capture sitemap (strip lastmod)
            r = requests.get(f"{self.base_url}/api/sitemap.xml", timeout=30)
            if r.status_code == 200:
                sitemap = re.sub(r'<lastmod>.*?</lastmod>', '', r.text)
                resources['sitemap'] = sitemap
                print(f"      ✓ Sitemap captured ({len(sitemap)} chars)")
        except Exception as e:
            print(f"      ✗ Sitemap error: {e}")
        
        try:
            # Capture robots.txt
            r = requests.get(f"{self.base_url}/robots.txt", timeout=30)
            if r.status_code == 200:
                resources['robots'] = r.text
                print(f"      ✓ robots.txt captured ({len(r.text)} chars)")
        except Exception as e:
            print(f"      ✗ robots.txt error: {e}")
        
        try:
            # Capture models
            r = requests.get(f"{self.base_url}/api/models", timeout=30)
            if r.status_code == 200:
                resources['models'] = r.json()
                print(f"      ✓ Models captured ({len(resources['models'])} items)")
        except Exception as e:
            print(f"      ✗ Models error: {e}")
        
        try:
            # Capture categories
            r = requests.get(f"{self.base_url}/api/categories", timeout=30)
            if r.status_code == 200:
                resources['categories'] = r.json()
                print(f"      ✓ Categories captured ({len(resources['categories'])} items)")
        except Exception as e:
            print(f"      ✗ Categories error: {e}")
        
        try:
            # Capture articles
            r = requests.get(f"{self.base_url}/api/articles", timeout=30)
            if r.status_code == 200:
                resources['articles'] = r.json()
                print(f"      ✓ Articles captured ({len(resources['articles'])} items)")
        except Exception as e:
            print(f"      ✗ Articles error: {e}")
        
        return resources
    
    def compare_resources(self, before, after):
        """Compare resources before and after"""
        print("\n   🔍 Comparing resources...")
        mutations = []
        
        for key in before.keys():
            if key not in after:
                mutations.append(f"{key} missing in after")
                continue
            
            if before[key] != after[key]:
                mutations.append(f"{key} changed")
                print(f"      ✗ {key} CHANGED")
            else:
                print(f"      ✓ {key} unchanged")
        
        return mutations
    
    def test_daily_analysis_run(self):
        """Test daily analysis run with zero-mutation check"""
        print("\n" + "="*80)
        print("DAILY ANALYSIS RUN TEST (with zero-mutation check)")
        print("="*80)
        
        # Capture BEFORE state
        print("\n📸 BEFORE RUN:")
        before = self.capture_public_resources()
        
        # Start daily analysis (without LLM to speed up)
        success, response = self.run_test(
            "POST /run/daily_analysis?llm=false",
            "POST",
            "/api/admin/seo-autopilot/run/daily_analysis?llm=false",
            200
        )
        
        if not success:
            print("   ❌ Failed to start daily analysis")
            return False
        
        if not response.get('started'):
            print(f"   ⚠️  Run not started: {response}")
            return False
        
        print(f"   ✅ Run started: {response}")
        
        # Poll status until complete (max 90 seconds)
        print("\n   ⏳ Polling status (max 90s)...")
        max_wait = 90
        start_time = time.time()
        running = True
        
        while running and (time.time() - start_time) < max_wait:
            time.sleep(5)
            try:
                r = requests.get(
                    f"{self.base_url}/api/admin/seo-autopilot/status",
                    headers={'Authorization': f'Bearer {self.token}'},
                    timeout=30
                )
                if r.status_code == 200:
                    status = r.json()
                    running = status.get('running', False)
                    elapsed = int(time.time() - start_time)
                    if running:
                        print(f"      ⏳ Still running... ({elapsed}s elapsed, kind: {status.get('running_kind')})")
                    else:
                        print(f"      ✅ Run completed ({elapsed}s)")
            except Exception as e:
                print(f"      ⚠️  Status check error: {e}")
                break
        
        if running:
            print(f"   ⚠️  Run still running after {max_wait}s timeout")
        
        # Get latest run
        success, runs_response = self.run_test(
            "GET /runs?limit=1 (latest run)",
            "GET",
            "/api/admin/seo-autopilot/runs?limit=1",
            200
        )
        
        if success and runs_response.get('items'):
            latest_run = runs_response['items'][0]
            print(f"\n   📊 Latest Run:")
            print(f"      Status: {latest_run.get('status')}")
            print(f"      Public Mutations: {latest_run.get('public_mutations')}")
            print(f"      PUBLIC_MUTATIONS_CHECK: {latest_run.get('PUBLIC_MUTATIONS_CHECK')}")
            print(f"      Steps: {len(latest_run.get('steps', []))}")
            
            # Verify steps
            steps = latest_run.get('steps', [])
            expected_steps = ['gsc_sync', 'models_matrix', 'keyword_universe', 'clustering', 
                            'opportunities', 'page_map', 'cannibalization', 'landing_planner', 'backlog']
            step_names = [s.get('step') for s in steps]
            print(f"      Step names: {step_names}")
            
            # Check public mutations
            if latest_run.get('public_mutations') != 0:
                print(f"   ❌ PUBLIC_MUTATIONS is {latest_run.get('public_mutations')}, expected 0")
            else:
                print(f"   ✅ PUBLIC_MUTATIONS = 0")
            
            if latest_run.get('PUBLIC_MUTATIONS_CHECK') != 'PASS':
                print(f"   ❌ PUBLIC_MUTATIONS_CHECK is {latest_run.get('PUBLIC_MUTATIONS_CHECK')}, expected PASS")
            else:
                print(f"   ✅ PUBLIC_MUTATIONS_CHECK = PASS")
        
        # Capture AFTER state
        print("\n📸 AFTER RUN:")
        after = self.capture_public_resources()
        
        # Compare
        mutations = self.compare_resources(before, after)
        
        if mutations:
            print(f"\n   ❌ MUTATIONS DETECTED: {mutations}")
            return False
        else:
            print(f"\n   ✅ ZERO MUTATIONS - All public resources unchanged")
            return True
    
    def test_data_structures(self):
        """Test data structure validation"""
        print("\n" + "="*80)
        print("DATA STRUCTURE VALIDATION")
        print("="*80)
        
        # Test keywords structure
        success, response = self.run_test(
            "GET /keywords (check structure)",
            "GET",
            "/api/admin/seo-autopilot/keywords?limit=10",
            200
        )
        
        if success and response.get('items'):
            kw = response['items'][0] if response['items'] else None
            if kw:
                print(f"\n   📊 Sample Keyword:")
                print(f"      search_volume: {kw.get('search_volume')}")
                print(f"      metrics.source: {kw.get('metrics', {}).get('source')}")
                print(f"      sources: {kw.get('sources')}")
                print(f"      intent_source: {kw.get('intent_source')}")
                
                # Verify search_volume is DATA_SOURCE_UNAVAILABLE
                if kw.get('search_volume') != 'DATA_SOURCE_UNAVAILABLE':
                    print(f"   ⚠️  search_volume is {kw.get('search_volume')}, expected DATA_SOURCE_UNAVAILABLE")
        
        # Test clusters structure
        success, response = self.run_test(
            "GET /clusters (check structure)",
            "GET",
            "/api/admin/seo-autopilot/clusters?limit=5",
            200
        )
        
        if success and response.get('items'):
            cluster = response['items'][0] if response['items'] else None
            if cluster:
                print(f"\n   📊 Sample Cluster:")
                print(f"      cluster_id: {cluster.get('cluster_id')}")
                print(f"      intent: {cluster.get('intent')}")
                print(f"      primary_keyword: {cluster.get('primary_keyword')}")
                print(f"      n_keywords: {len(cluster.get('secondary_keywords', []))}")
        
        # Test proposals structure
        success, response = self.run_test(
            "GET /proposals (check structure)",
            "GET",
            "/api/admin/seo-autopilot/proposals",
            200
        )
        
        if success and response.get('items'):
            proposal = response['items'][0] if response['items'] else None
            if proposal:
                print(f"\n   📊 Sample Proposal:")
                print(f"      status: {proposal.get('status')}")
                print(f"      public: {proposal.get('public')}")
                print(f"      executable: {proposal.get('executable')}")
                print(f"      proposed_slug: {proposal.get('proposed_slug')}")
                print(f"      quality_gate: {[g.get('check') for g in proposal.get('quality_gate', [])]}")
                
                # Verify proposal is not public
                if proposal.get('public'):
                    print(f"   ⚠️  Proposal is public! This should not happen in READ_ONLY")
                
                # Verify proposed_slug is not in sitemap
                slug = proposal.get('proposed_slug')
                if slug:
                    r = requests.get(f"{self.base_url}/api/sitemap.xml", timeout=30)
                    if r.status_code == 200 and slug in r.text:
                        print(f"   ⚠️  Proposed slug '{slug}' found in sitemap!")
        
        # Test log structure
        success, response = self.run_test(
            "GET /log (check structure)",
            "GET",
            "/api/admin/seo-autopilot/log?limit=10",
            200
        )
        
        if success and response.get('items'):
            # Look for PUBLIC_MUTATION_CHECK entry
            mutation_checks = [item for item in response['items'] if item.get('action') == 'PUBLIC_MUTATION_CHECK']
            if mutation_checks:
                check = mutation_checks[0]
                print(f"\n   📊 PUBLIC_MUTATION_CHECK Log Entry:")
                print(f"      action: {check.get('action')}")
                print(f"      result: {check.get('result')}")
                print(f"      timestamp: {check.get('timestamp')}")
                
                if check.get('result') != 'PASS':
                    print(f"   ⚠️  PUBLIC_MUTATION_CHECK result is {check.get('result')}, expected PASS")
        
        return True
    
    def test_public_endpoints(self):
        """Test existing public endpoints still work"""
        print("\n" + "="*80)
        print("PUBLIC ENDPOINTS REGRESSION TEST")
        print("="*80)
        
        endpoints = [
            ("/api/models", "Models"),
            ("/api/sitemap.xml", "Sitemap"),
            ("/api/categories", "Categories"),
        ]
        
        all_passed = True
        for endpoint, name in endpoints:
            try:
                r = requests.get(f"{self.base_url}{endpoint}", timeout=30)
                if r.status_code == 200:
                    print(f"   ✅ {name}: {r.status_code}")
                    self.tests_passed += 1
                else:
                    print(f"   ❌ {name}: {r.status_code}")
                    all_passed = False
                self.tests_run += 1
            except Exception as e:
                print(f"   ❌ {name}: {e}")
                all_passed = False
                self.tests_run += 1
        
        return all_passed

def main():
    print("\n" + "="*80)
    print("SEO AUTOPILOT BACKEND API TESTS - Phase 14 READ_ONLY")
    print("="*80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    tester = SeoAutopilotTester()
    
    # Run tests
    if not tester.test_admin_login():
        print("\n❌ Admin login failed, stopping tests")
        return 1
    
    tester.test_status_without_auth()
    tester.test_status_with_auth()
    tester.test_read_endpoints()
    tester.test_write_guard()
    tester.test_data_structures()
    tester.test_public_endpoints()
    tester.test_daily_analysis_run()
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Tests run: {tester.tests_run}")
    print(f"Tests passed: {tester.tests_passed}")
    print(f"Tests failed: {tester.tests_run - tester.tests_passed}")
    print(f"Success rate: {(tester.tests_passed / tester.tests_run * 100):.1f}%")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return 0 if tester.tests_passed == tester.tests_run else 1

if __name__ == "__main__":
    sys.exit(main())
