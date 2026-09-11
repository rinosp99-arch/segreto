"""Env-only configuration. Credentials are never stored in Mongo nor returned by any API/GPT capability."""
import json
import os
from typing import Optional


def _bool(name: str, default: bool = False) -> bool:
    return str(os.environ.get(name, str(default))).strip().lower() in ("1", "true", "yes", "on")


class GoogleSearchConfig:
    @property
    def enabled(self) -> bool:
        return _bool("GOOGLE_SEARCH_ENABLED", False)

    @property
    def property_url(self) -> str:
        """Search Console property. URL-prefix property MUST end with '/'; Domain property uses 'sc-domain:example.com'."""
        p = (os.environ.get("GOOGLE_SEARCH_PROPERTY") or "https://secret-side.emergent.host/").strip()
        if p and not p.startswith("sc-domain:") and not p.endswith("/"):
            p += "/"
        return p

    @property
    def public_base(self) -> str:
        """Canonical public origin used to build sitemap/inspection URLs (no trailing slash)."""
        base = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if base:
            return base
        p = self.property_url
        return p.rstrip("/") if p.startswith("http") else ""

    @property
    def sync_enabled(self) -> bool:
        return _bool("GOOGLE_SEARCH_SYNC_ENABLED", True)

    @property
    def analytics_enabled(self) -> bool:
        return _bool("GOOGLE_SEARCH_ANALYTICS_ENABLED", True)

    @property
    def inspection_enabled(self) -> bool:
        return _bool("GOOGLE_SEARCH_INSPECTION_ENABLED", True)

    @property
    def mock(self) -> bool:
        """Deterministic adapter for tests (GOOGLE_SEARCH_MOCK=1). Never on in production."""
        return _bool("GOOGLE_SEARCH_MOCK", False)

    @property
    def inspection_cache_hours(self) -> int:
        return int(os.environ.get("GOOGLE_SEARCH_INSPECTION_CACHE_HOURS", "24"))

    @property
    def inspection_daily_budget(self) -> int:
        """Self-imposed daily budget (Google quota is 2000/day/property): keep a wide safety margin."""
        return int(os.environ.get("GOOGLE_SEARCH_INSPECTION_DAILY_BUDGET", "300"))

    @property
    def sitemap_debounce_hours(self) -> int:
        return int(os.environ.get("GOOGLE_SEARCH_SITEMAP_DEBOUNCE_HOURS", "6"))

    def credentials_info(self) -> Optional[dict]:
        """Service-account JSON from GOOGLE_SEARCH_CREDENTIALS_JSON (inline) or GOOGLE_SEARCH_CREDENTIALS_FILE (path).
        Returns the parsed dict or None. The dict is used only in-process by google-auth; never logged/returned."""
        raw = os.environ.get("GOOGLE_SEARCH_CREDENTIALS_JSON")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        path = os.environ.get("GOOGLE_SEARCH_CREDENTIALS_FILE") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def credentials_summary(self) -> dict:
        """Safe summary for status endpoints: presence + service-account email (public identifier), never keys."""
        info = self.credentials_info()
        if not info:
            return {"present": False, "type": None, "service_account_email": None}
        return {"present": True, "type": info.get("type"), "service_account_email": info.get("client_email"), "project_id": info.get("project_id")}


cfg = GoogleSearchConfig()
