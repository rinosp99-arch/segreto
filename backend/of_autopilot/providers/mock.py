"""MockOFProvider — simulates the full provider contract (upload -> complete media object -> immediate post / scheduled post ->
GET schedules / GET post -> verification) with ZERO network. Test knobs: fail_upload (url substrings), timeout_upload, fail_create,
hide_scheduled (create returns 200 but the post is not in the schedule list -> SCHEDULE_NOT_CONFIRMED), hide_post (POST_NOT_CONFIRMED),
fail_mass_dm (send rejected), hide_mass_dm (send 200 but not in the mass message list -> MASS_DM_NOT_CONFIRMED), fans (audience size)."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from .base import OFAccount, OFAccountHealth, OFMassMessageRequest, OFMassMessageResult, OFMedia, OFPostRequest, OFPostResult, OFProviderAdapter, OFProviderError

MOCK_OF_USER_ID = "mock_latosegreto"


class MockOFProvider(OFProviderAdapter):
    name = "MOCK"

    def __init__(self):
        self.uploads: List[dict] = []
        self.posts: Dict[str, dict] = {}
        self.scheduled: List[dict] = []
        self.fail_upload: set = set()
        self.timeout_upload: bool = False
        self.fail_create: bool = False
        self.hide_scheduled: bool = False
        self.hide_post: bool = False
        self.write_calls = 0                  # mock-internal counter (never a real write)
        self.gate: bool = False
        self.gate_history: List[bool] = []
        self.mass_messages: List[dict] = []   # sent mass DMs (mock queue list)
        self.fail_mass_dm: bool = False
        self.hide_mass_dm: bool = False
        self.fans: int = 418                  # mock audience size (ALL subscribers)

    # ---------------- READ
    async def test_connection(self) -> Dict[str, Any]:
        return {"key_valid": True, "crm_scope": True, "accounts_count": 1, "accounts": [{"username": "latosegreto", "platform": "onlyfans"}], "mock": True}

    async def list_accounts(self) -> List[OFAccount]:
        return [OFAccount(MOCK_OF_USER_ID, "latosegreto", "onlyfans", {"mock": True})]

    async def get_account(self, of_user_id: str) -> OFAccount:
        return (await self.list_accounts())[0]

    async def get_account_health(self, of_user_id: str) -> OFAccountHealth:
        return OFAccountHealth("HEALTHY", "latosegreto", False, False, "mock")

    async def get_scheduled_posts(self, of_user_id: str, limit: int = 10, offset: int = 0) -> Dict[str, Any]:
        page = self.scheduled[offset: offset + limit]
        return {"list": [dict(p) for p in page], "hasMore": offset + limit < len(self.scheduled)}

    async def get_post(self, of_user_id: str, post_id: str) -> Dict[str, Any]:
        p = self.posts.get(str(post_id))
        if not p or self.hide_post:
            raise OFProviderError("NOT_FOUND", "mock: post non trovato", 404)
        return dict(p)

    async def set_write_gate(self, of_user_id: str, enabled: bool) -> Dict[str, Any]:
        self.gate = bool(enabled)
        self.gate_history.append(self.gate)
        return {"polling": {"allow_of_write_actions": self.gate}}

    async def get_write_gate(self, of_user_id: str):
        return self.gate

    # ---------------- WRITE (mock only)
    def _media_obj(self, name: str, kind: str, source: str) -> OFMedia:
        raw = {"processId": f"mock_{uuid.uuid4().hex[:12]}", "host": "convert4.onlyfans.com", "thumbId": 1, "name": name, "extra": "mock-extra", "mock": True, "source": source}
        self.uploads.append({**raw, "kind": kind})
        return OFMedia(provider_ref=raw["processId"], kind=kind, raw=raw)

    async def upload_media_from_url(self, of_user_id: str, *, source_url: str, file_name: str, kind: str) -> OFMedia:
        self.write_calls += 1
        if self.timeout_upload:
            raise OFProviderError("NETWORK_ERROR", "mock: timeout upload")
        if any(f in source_url for f in self.fail_upload):
            raise OFProviderError("API_ERROR", "mock: upload rifiutato", 422)
        return self._media_obj(file_name, kind, "source_url")

    async def upload_media(self, of_user_id: str, *, file_name: str, content: bytes, content_type: str) -> OFMedia:
        self.write_calls += 1
        if not content:
            raise OFProviderError("API_ERROR", "mock: file vuoto", 422)
        kind = "video" if content_type.startswith("video/") else "photo"
        return self._media_obj(file_name, kind, "file")

    def _create(self, req: OFPostRequest, scheduled: bool) -> dict:
        self.write_calls += 1
        if self.fail_create:
            raise OFProviderError("API_ERROR", "mock: creazione post rifiutata", 500)
        pid = f"mock_of_{uuid.uuid4().hex[:10]}"
        post = {"id": pid, "author": {"id": MOCK_OF_USER_ID, "username": "latosegreto"}, "text": req.text, "media": [{"id": m.provider_ref, "type": m.kind} for m in req.media], "mediaFiles": [dict(m.raw) for m in req.media],
                "isScheduled": 1 if scheduled else 0, "scheduledDate": req.scheduled_at if scheduled else None, "postedAt": None if scheduled else datetime.now(timezone.utc).isoformat()}
        self.posts[pid] = post
        if scheduled and not self.hide_scheduled:
            self.scheduled.append(post)
        return post

    async def create_post(self, of_user_id: str, req: OFPostRequest) -> OFPostResult:
        post = self._create(req, scheduled=False)
        return OFPostResult(post["id"], False, "PUBLISHED", post)

    async def schedule_post(self, of_user_id: str, req: OFPostRequest) -> OFPostResult:
        if not req.scheduled_at:
            raise OFProviderError("API_ERROR", "schedule_post richiede scheduled_at")
        post = self._create(req, scheduled=True)
        confirmed = await self.verify_scheduled(of_user_id, post["id"])
        return OFPostResult(post["id"], True, "SCHEDULE_CONFIRMED" if confirmed else "SCHEDULE_NOT_CONFIRMED", post)

    async def delete_scheduled_post(self, of_user_id: str, post_id: str) -> Dict[str, Any]:
        raise OFProviderError("NOT_DOCUMENTED", "mock: non documentato")

    # ---------------- MASS MESSAGE (mock only, zero network)
    async def mass_message_audience_size(self, of_user_id: str):
        return self.fans

    async def subscribers_count(self, of_user_id: str):
        return self.fans

    async def get_mass_messages(self, of_user_id: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        page = self.mass_messages[offset: offset + limit]
        return {"list": [dict(x) for x in page], "hasMore": offset + limit < len(self.mass_messages)}

    async def send_mass_message(self, of_user_id: str, req: OFMassMessageRequest) -> OFMassMessageResult:
        self.write_calls += 1
        if self.fail_mass_dm:
            raise OFProviderError("API_ERROR", "mock: mass message rifiutato", 500)
        if not req.text and not req.media_ids:
            raise OFProviderError("API_ERROR", "mock: message requires text or mediaFiles", 400)
        mid = f"mock_dm_{uuid.uuid4().hex[:10]}"
        msg = {"id": mid, "text": req.text, "mediaFiles": list(req.media_ids), "price": req.price or 0, "queueBuyers": [] if req.audience == "ALL" else [req.audience],
               "audience": "ALL_SUBSCRIBERS" if req.audience == "ALL" else req.audience, "recipients": self.fans, "createdAt": datetime.now(timezone.utc).isoformat(), "mock": True}
        if not self.hide_mass_dm:
            self.mass_messages.append(msg)
        confirmed = await self.verify_mass_message(of_user_id, mid)
        return OFMassMessageResult(mid, "MASS_DM_CONFIRMED" if confirmed else "MASS_DM_NOT_CONFIRMED", self.fans, dict(msg))
