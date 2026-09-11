"""Google Search Console integration layer (Phase 13 - GOOGLE SEO CORE).

Structure (no Google call outside this package):
  config.py     env-only configuration (never exposed through the API)
  auth.py       service-account access token (google-auth), cached
  client.py     httpx client with timeout, retry/backoff, quota handling, structured request log (never secrets)
  mock.py       deterministic adapter used when not configured / in tests
  service.py    business-level functions: status, sitemap sync (debounced), URL inspection (cached), analytics
"""
