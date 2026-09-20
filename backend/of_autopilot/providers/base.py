"""Provider abstraction for the future OF Autopilot. The engine will depend ONLY on `OFProviderAdapter`, never on a vendor API.

Contract (vendor-neutral):
  READ  : test_connection, get_account, get_account_health, get_scheduled_posts, get_post
  WRITE : upload_media, create_post, schedule_post, delete_scheduled_post  (guarded by OF_REAL_POSTING_ENABLED; blocked in this phase)
A scheduled post is SUCCESS only when `verify_scheduled(post_id)` finds it in the provider's schedule list (SCHEDULE_CONFIRMED),
otherwise SCHEDULE_NOT_CONFIRMED and the caller must NOT advance blindly."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CONNECTION_STATUSES = ("CONNECTED", "NOT_CONNECTED", "ERROR")
ACCOUNT_STATUSES = ("HEALTHY", "UNHEALTHY", "UNKNOWN")


class OFProviderError(Exception):
    """code: NOT_CONFIGURED | UNAUTHORIZED | FORBIDDEN | NOT_FOUND | RATE_LIMITED | API_ERROR | NETWORK_ERROR | WRITES_DISABLED |
    NOT_DOCUMENTED | ACCOUNT_MISMATCH | AMBIGUOUS_ACCOUNTS. `description` is always secret-scrubbed by the adapter."""

    def __init__(self, code: str, description: str = "", status: Optional[int] = None):
        super().__init__(f"{code}: {description}")
        self.code, self.description, self.status = code, description, status


@dataclass
class OFAccount:
    of_user_id: str
    username: str
    platform: str                       # "onlyfans" expected
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OFAccountHealth:
    status: str                         # HEALTHY | UNHEALTHY | UNKNOWN
    username: Optional[str] = None      # username as seen by the live platform session
    write_actions_allowed: Optional[bool] = None
    polling_enabled: Optional[bool] = None
    detail: Optional[str] = None        # scrubbed, non-sensitive


@dataclass
class OFMedia:
    """Complete media object exactly as returned by the provider. `raw` MUST be passed through whole to the post (`mediaFiles`)."""
    provider_ref: str
    kind: str                           # photo | video | audio | gif
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OFPostRequest:
    text: str
    media: List[OFMedia] = field(default_factory=list)
    scheduled_at: Optional[str] = None  # ISO-8601 with offset -> isScheduled + scheduledDate (never postedAt)


@dataclass
class OFPostResult:
    post_id: Optional[str]
    scheduled: bool
    schedule_state: str                 # PUBLISHED | SCHEDULE_CONFIRMED | SCHEDULE_NOT_CONFIRMED | UNKNOWN
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OFMassMessageRequest:
    """Mass DM to ALL fans/subscribers of the account. `media_ids` = vault media ids of media ALREADY consumed by the confirmed feed post
    (read back from GET post -> media[].id), PUBLIC first then SECRET. price None/0 = free message."""
    text: str
    media_ids: List[Any] = field(default_factory=list)
    price: Optional[float] = None
    audience: str = "ALL"               # ALL = every subscriber (empty queueBuyers); nothing else is supported by this engine


@dataclass
class OFMassMessageResult:
    message_id: Optional[str]
    state: str                          # MASS_DM_CONFIRMED | MASS_DM_NOT_CONFIRMED | UNKNOWN
    audience_size: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class OFProviderAdapter(ABC):
    name: str = "abstract"

    # ---------------- READ ----------------
    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]: ...

    @abstractmethod
    async def list_accounts(self) -> List[OFAccount]: ...

    @abstractmethod
    async def get_account(self, of_user_id: str) -> OFAccount: ...

    @abstractmethod
    async def get_account_health(self, of_user_id: str) -> OFAccountHealth: ...

    @abstractmethod
    async def get_scheduled_posts(self, of_user_id: str, limit: int = 10, offset: int = 0) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_post(self, of_user_id: str, post_id: str) -> Dict[str, Any]: ...

    # ---------------- WRITE (guarded) ----------------
    @abstractmethod
    async def upload_media(self, of_user_id: str, *, file_name: str, content: bytes, content_type: str) -> OFMedia: ...

    @abstractmethod
    async def create_post(self, of_user_id: str, req: OFPostRequest) -> OFPostResult: ...

    @abstractmethod
    async def schedule_post(self, of_user_id: str, req: OFPostRequest) -> OFPostResult: ...

    @abstractmethod
    async def delete_scheduled_post(self, of_user_id: str, post_id: str) -> Dict[str, Any]: ...

    async def upload_media_from_url(self, of_user_id: str, *, source_url: str, file_name: str, kind: str) -> OFMedia:
        """Preferred path: the provider fetches the media from OUR storage (https source_url). Providers may override."""
        raise OFProviderError("NOT_SUPPORTED", "upload da source_url non supportato da questo provider")

    # ---------------- fail-safe verification ----------------
    async def verify_post(self, of_user_id: str, post_id: str) -> bool:
        """Immediate post: CREATE -> post id -> GET post -> exists ? POST_CONFIRMED : POST_NOT_CONFIRMED (read-only)."""
        try:
            data = await self.get_post(of_user_id, post_id)
        except OFProviderError:
            return False
        return bool(data) and str((data or {}).get("id")) == str(post_id)

    async def verify_scheduled(self, of_user_id: str, post_id: str, pages: int = 5, page_size: int = 50) -> bool:
        """CREATE -> post id -> GET schedules -> id present ? SCHEDULE_CONFIRMED : SCHEDULE_NOT_CONFIRMED (read-only)."""
        for p in range(pages):
            page = await self.get_scheduled_posts(of_user_id, limit=page_size, offset=p * page_size)
            items = page.get("list") or []
            if any(str(it.get("id")) == str(post_id) for it in items):
                return True
            if not page.get("hasMore") or not items:
                break
        return False

    # ---------------- MASS MESSAGE (optional capability; guarded like every write) ----------------
    async def mass_message_audience_size(self, of_user_id: str) -> Optional[int]:
        """Recipients of an ALL-subscribers mass message (exact preview for the send body). None when the provider cannot tell.
        NOTE: on The Only API this is a POST behind the account write gate -> only meaningful once the gate is open."""
        return None

    async def subscribers_count(self, of_user_id: str) -> Optional[int]:
        """READ-ONLY audience proxy for ALL subscribers (usable while the write gate is closed). None when unavailable."""
        return None

    async def get_mass_messages(self, of_user_id: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """{"list": [...], "hasMore": bool} of the account's mass messages (queued/sent), read-only."""
        raise OFProviderError("NOT_SUPPORTED", "mass message non supportato da questo provider")

    async def send_mass_message(self, of_user_id: str, req: OFMassMessageRequest) -> OFMassMessageResult:
        raise OFProviderError("NOT_SUPPORTED", "mass message non supportato da questo provider")

    async def verify_mass_message(self, of_user_id: str, message_id: str, pages: int = 3, page_size: int = 50) -> bool:
        """SEND -> id -> GET mass messages -> id present ? MASS_DM_CONFIRMED : MASS_DM_NOT_CONFIRMED (read-only)."""
        for p in range(pages):
            try:
                page = await self.get_mass_messages(of_user_id, limit=page_size, offset=p * page_size)
            except OFProviderError:
                return False
            items = page.get("list") or []
            if any(str(it.get("id")) == str(message_id) for it in items):
                return True
            if not page.get("hasMore") or not items:
                break
        return False
