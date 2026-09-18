"""Sitemap dirty marker — dependency-free leaf module.
Imported by the model/landing mutation paths (v1_models, v1_landings, v1_versioning) so that they never import the
Search Console service layer (which in turn reads v1_seo -> v1_models): no import cycle, lazy or otherwise."""
from database import google_search_state_col, now_iso


async def mark_sitemap_dirty(reason: str):
    """Called by publish/unpublish/slug/canonical changes: the sitemap itself is always live (computed on request);
    this only schedules a (debounced) Search Console re-submit."""
    try:
        await google_search_state_col.update_one(
            {"id": "global"},
            {"$set": {"sitemap_dirty": True, "sitemap_dirty_reason": (reason or "")[:120], "sitemap_dirty_at": now_iso()}},
            upsert=True,
        )
    except Exception:
        pass
