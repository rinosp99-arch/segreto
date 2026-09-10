"""Version history + rollback for every important change.

Each version stores: entity, entity_id, before, after, changed_fields, actor,
source (manual|ai|api|system|autofix|rollback), reason, request_id, timestamp.
Rollback restores `before` and records a new version pointing to the original.
"""
import uuid
from typing import Optional, List
from fastapi import HTTPException

from database import (
    versions_col, models_col, categories_col, articles_col, landings_col, settings_col,
    config_col, experiments_col, files_col, redirects_col, audit_col, now_iso, serialize_doc,
)

ENTITY_COLLECTIONS = {
    "model": models_col,
    "category": categories_col,
    "article": articles_col,
    "landing": landings_col,
    "settings": settings_col,
    "config": config_col,
    "experiment": experiments_col,
    "file": files_col,
    "redirect": redirects_col,
}


def _clean(doc):
    if doc is None:
        return None
    return serialize_doc({k: v for k, v in doc.items() if k != "_id"})


def diff_fields(before: Optional[dict], after: Optional[dict]) -> List[str]:
    if before is None and after is None:
        return []
    if before is None:
        return sorted(list((after or {}).keys()))
    if after is None:
        return sorted(list(before.keys()))
    keys = set(before.keys()) | set(after.keys())
    return sorted([k for k in keys if before.get(k) != after.get(k) and k not in ("updated_at",)])


async def record_version(entity: str, entity_id: str, before: Optional[dict], after: Optional[dict],
                         actor: str, source: str = "manual", reason: str = "",
                         request_id: Optional[str] = None, meta: Optional[dict] = None) -> dict:
    b, a = _clean(before), _clean(after)
    changed = diff_fields(b, a)
    if before is not None and after is not None and not changed:
        return {"id": None, "changed_fields": []}
    v = {
        "id": str(uuid.uuid4()),
        "entity": entity,
        "entity_id": entity_id,
        "before": b,
        "after": a,
        "changed_fields": changed,
        "operation": "create" if before is None else ("delete" if after is None else "update"),
        "actor": actor,
        "source": source,  # manual | ai | api | system | autofix | rollback
        "reason": reason or "",
        "request_id": request_id or str(uuid.uuid4()),
        "timestamp": now_iso(),
        "rolled_back": False,
        "meta": meta or {},
    }
    await versions_col.insert_one(v)
    return {k: val for k, val in v.items() if k != "_id"}


async def audit_log(actor: str, action: str, entity: str, entity_id: str, meta=None, request_id=None, source="manual"):
    await audit_col.insert_one({
        "id": str(uuid.uuid4()), "actor": actor, "action": action,
        "entity": entity, "entity_id": entity_id, "meta": meta or {},
        "request_id": request_id, "source": source, "timestamp": now_iso(),
    })


async def list_versions(entity: Optional[str] = None, entity_id: Optional[str] = None, limit: int = 50, skip: int = 0):
    q = {}
    if entity:
        q["entity"] = entity
    if entity_id:
        q["entity_id"] = entity_id
    cur = versions_col.find(q, {"_id": 0, "before": 0, "after": 0}).sort("timestamp", -1).skip(skip).limit(limit)
    items = await cur.to_list(limit)
    total = await versions_col.count_documents(q)
    return {"items": items, "total": total}


async def get_version(version_id: str):
    v = await versions_col.find_one({"id": version_id}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Versione non trovata")
    return v


async def rollback_version(version_id: str, actor: str, request_id: Optional[str] = None, reason: str = "") -> dict:
    """Restore the `before` snapshot of a version. Never destructive: records a new version."""
    v = await get_version(version_id)
    col = ENTITY_COLLECTIONS.get(v["entity"])
    if col is None:
        raise HTTPException(status_code=400, detail=f"Rollback non supportato per entity '{v['entity']}'")
    entity_id = v["entity_id"]
    current = await col.find_one({"id": entity_id}, {"_id": 0})
    before = v.get("before")

    if before is None:
        # rollback of a create -> soft delete
        if current is None:
            raise HTTPException(status_code=409, detail="Entità già assente")
        new_doc = {**current, "is_deleted": True, "deleted_at": now_iso(), "updated_at": now_iso()}
        await col.update_one({"id": entity_id}, {"$set": {"is_deleted": True, "deleted_at": now_iso(), "updated_at": now_iso()}})
    else:
        # slug uniqueness guard for models/landings
        if v["entity"] in ("model", "landing", "category", "article") and before.get("slug"):
            clash = await col.find_one({"slug": before["slug"], "id": {"$ne": entity_id}}, {"_id": 0, "id": 1})
            if clash:
                before = {**before, "slug": f"{before['slug']}-r{uuid.uuid4().hex[:4]}"}
        new_doc = {**before, "updated_at": now_iso(), "is_deleted": False}
        new_doc.pop("deleted_at", None)
        await col.replace_one({"id": entity_id}, new_doc, upsert=True)

    rv = await record_version(v["entity"], entity_id, current, new_doc, actor, source="rollback",
                              reason=reason or f"Rollback della versione {version_id}", request_id=request_id,
                              meta={"rollback_of": version_id})
    await versions_col.update_one({"id": version_id}, {"$set": {"rolled_back": True, "rolled_back_at": now_iso(), "rolled_back_by": actor, "rollback_version_id": rv.get("id")}})
    await audit_log(actor, "rollback", v["entity"], entity_id, {"version_id": version_id, "new_version_id": rv.get("id")}, request_id, source="rollback")
    return {"ok": True, "entity": v["entity"], "entity_id": entity_id, "restored_version_id": version_id,
            "new_version_id": rv.get("id"), "operation": "soft_delete" if before is None else "restore"}
