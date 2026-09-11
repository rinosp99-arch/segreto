"""Shared test-residue purge (preview DB only). Removes ONLY harness-generated records that are already non-business:
revoked test API keys, soft-deleted test models/landings (+ their versions / SEO issues / soft-deleted files).
Live business data and the audit trail of real sessions (ai_actions) are never touched."""
import asyncio
import os
import re
import sys

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

TEST_MODEL_RX = re.compile(r"^(Zeta Testuale|Idem Test|Francesca \(copia\)|Test |TEST GIULIA|Cov |Audit Test|Test Giulia|OF Test|Vanessa Test)", re.I)
TEST_KEY_RX = re.compile(r"^(test-|sim-|smoke-|cov12a-|chatgpt-test$|dbg$|seo-only$|ChatGPT Production READ_ONLY \(simulazione\)$)")
TEST_LANDING_RX = re.compile(r"^(test-|e2e-|landing-cov-|landing-test)")


async def _purge():
    from database import models_col, files_col, landings_col, seo_issues_col, versions_col, api_keys_col
    out = {}
    mids = [m["id"] async for m in models_col.find({"is_deleted": True}, {"_id": 0, "id": 1, "nome": 1}) if TEST_MODEL_RX.match(m.get("nome") or "")]
    out["models"] = (await models_col.delete_many({"id": {"$in": mids}})).deleted_count
    out["seo_issues"] = (await seo_issues_col.delete_many({"entity_id": {"$in": mids}})).deleted_count
    fids = [f["id"] async for f in files_col.find({"is_deleted": True, "model_id": {"$in": mids}}, {"_id": 0, "id": 1})]
    out["files"] = (await files_col.delete_many({"$or": [{"id": {"$in": fids}}, {"parent_id": {"$in": fids}}]})).deleted_count
    lids = [x["id"] async for x in landings_col.find({"is_deleted": True}, {"_id": 0, "id": 1, "slug": 1}) if TEST_LANDING_RX.match(x.get("slug") or "")]
    out["landings"] = (await landings_col.delete_many({"id": {"$in": lids}})).deleted_count
    out["versions"] = (await versions_col.delete_many({"entity_id": {"$in": mids + lids + fids}})).deleted_count
    kids = [k["id"] async for k in api_keys_col.find({"active": False}, {"_id": 0, "id": 1, "name": 1}) if TEST_KEY_RX.match(k.get("name") or "")]
    out["api_keys"] = (await api_keys_col.delete_many({"id": {"$in": kids}})).deleted_count
    return out


def purge_test_residue():
    """Sync entry point for standalone scripts (fresh loop, safe after other loops closed)."""
    if os.environ.get("KEEP_TEST_RESIDUE"):
        return {}
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_purge())
    finally:
        loop.close()


async def purge_test_residue_async():
    return await _purge()


if __name__ == "__main__":
    print(purge_test_residue())
