"""Phase 12A micro-step: static + non-mutating verification of the corrected bindings. NO writes to the DB."""
import asyncio, inspect, sys
sys.path.insert(0, "/app/backend")
from unittest.mock import MagicMock

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))

import v1_capabilities as C
import v1_media, v1_seo, v1_config, schemas
from database import files_col, backups_col, models_col

# ---- A. fetch_url_bytes: 1 arg, sync; call sites use run_in_executor
sig = inspect.signature(v1_media.fetch_url_bytes)
check("fetch_url_bytes: 1 argomento", len(sig.parameters) == 1, str(sig))
check("fetch_url_bytes: sincrona (no await diretto)", not inspect.iscoroutinefunction(v1_media.fetch_url_bytes))
src = inspect.getsource(C)
check("fetch_url_bytes: nessuna chiamata a 2 argomenti / await diretto", "await fetch_url_bytes(" not in src and "run_in_executor(None, fetch_url_bytes," in src)
sm = inspect.signature(v1_media.store_media).parameters
check("store_media: nessun kwarg 'source' passato", "source" not in sm and "request_id=request_id_of(ctx.request), source=" not in src.split("store_media(")[1].split(")")[0])

# ---- B. run_audit / apply_safe_fixes: entity_id
check("run_audit: parametro reale entity_id", "entity_id" in inspect.signature(v1_seo.run_audit).parameters and "model_id" not in inspect.signature(v1_seo.run_audit).parameters)
check("apply_safe_fixes: parametro reale entity_id", "entity_id" in inspect.signature(v1_seo.apply_safe_fixes).parameters)
check("bozza: nessun run_audit/apply_safe_fixes(model_id=)", "run_audit(scope=\"models\", model_id" not in src and "apply_safe_fixes(model_id" not in src)
dry_shape = {"dry_run": True, "would_fix": 2, "items": [{"id": "x", "code": "A"}, {"id": "y", "code": "B"}]}
apply_shape = {"applied": 1, "skipped": 1, "results": [{"applied": True, "version_id": "v1", "code": "A"}, {"applied": False, "code": "B"}]}
check("_safe_fix_view dry", C._safe_fix_view(dry_shape) == (2, [], dry_shape["items"]))
check("_safe_fix_view apply", C._safe_fix_view(apply_shape)[:2] == (1, ["v1"]))

# ---- C. variants: dict structure via public_file
fake_img = {"id": "f1", "tipo": "image", "storage_path": "img/a.jpg", "variants": {"original": {"url": "/api/uploads/img/a.jpg"}, "web": {"url": "/api/uploads/img/a_web.webp"}}}
fake_vid = {"id": "f2", "tipo": "video", "storage_path": "vid/b.mp4", "variants": {"original": {"url": "/api/uploads/vid/b.mp4"}, "poster": {"url": "/api/uploads/vid/b_poster.jpg"}}}
check("media_urls image -> variants.web.url", C.media_urls(fake_img) == ("/api/uploads/img/a_web.webp", ""))
check("media_urls video -> original + poster", C.media_urls(fake_vid) == ("/api/uploads/vid/b.mp4", "/api/uploads/vid/b_poster.jpg"))
check("media_summary.url corretto", C.media_summary(fake_img)["url"] == "/api/uploads/img/a_web.webp")
check("bozza: nessun (variants).get('web') come stringa", '.get("web") or' not in src and '.get("poster") or ""' not in src)

# ---- D. pellicola_home: real schema PellicolaHome.pubblico/segreto.{video_url,poster_url}
doc = {"id": "m1", "slug": "test", "pellicola_home": {"attiva": True, "priorita": 5, "pubblico": {"video_url": "", "poster_url": ""}, "segreto": {"video_url": "", "poster_url": ""}}, "media_pairs": []}
ch = v1_media.slot_changes(doc, url="/v.mp4", slot="pellicola", side="segreto", tipo="video", poster="/p.jpg")
ph = schemas.PellicolaHome(**ch["pellicola_home"])
check("slot_changes pellicola -> PellicolaHome valido", ph.segreto.video_url == "/v.mp4" and ph.segreto.poster_url == "/p.jpg" and ph.pubblico.video_url == "")
check("parse_slot filmstrip_secret -> (pellicola, segreto, video)", C.parse_slot("filmstrip_secret")[:3] == ("pellicola", "segreto", "video"))
check("parse_slot secret_photo_2 -> pair", C.parse_slot("secret_photo_2") == ("pair", "segreto", "image", 2))
check("bozza: nessuna chiave video_pubblico/poster_segreto scritta", 'f"video_{side}"' not in src and 'f"poster_{side}"' not in src)
check("apply_media_to_slot usa slot_changes (preview==execute)", "slot_changes(doc, url=url, slot=tech" in inspect.getsource(C.apply_media_to_slot) and "attach_to_model" not in inspect.getsource(C.apply_media_to_slot))

# ---- E. categorie: CategoryIn
cat_fields = set(schemas.CategoryIn.model_fields.keys())
check("CATEGORY_FIELDS ⊆ CategoryIn", C.CATEGORY_FIELDS <= cat_fields, str(C.CATEGORY_FIELDS - cat_fields))
check("nessun campo fantasma (attiva/hero_text/icona/colore)", not ({"attiva", "hero_text", "icona", "colore", "seo"} & C.CATEGORY_FIELDS))
c_in = schemas.CategoryIn(nome="Estate", descrizione="x", ordine=3).model_dump()
check("CategoryIn payload valido -> stato default pubblicata", c_in["stato"] == "pubblicata" and c_in["slug"] == "")

# ---- F. backup: counts/inline/_load_backup/restore_backup(dry_run)
check("create_backup firma (actor, include_events, reason)", list(inspect.signature(v1_config.create_backup).parameters) == ["actor", "include_events", "reason"])
check("restore_backup + RestoreBody(dry_run) esistono", hasattr(v1_config, "restore_backup") and "dry_run" in v1_config.RestoreBody.model_fields)
check("bozza: nessun accesso a b['snapshot']/b['data']", 'b.get("snapshot")' not in src and '"snapshot": 0' not in src)

async def live_readonly():
    # read-only calls against the preview DB (no writes): apply_safe_fixes dry, find_media, backup verify/plan
    m = await models_col.find_one({"is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "slug": 1})
    if m:
        r = await v1_seo.apply_safe_fixes("verify", None, scope="models", entity_id=m["id"], dry_run=True)
        check("apply_safe_fixes(dry_run) live: forma {dry_run, would_fix, items}", r.get("dry_run") is True and isinstance(r.get("would_fix"), int) and isinstance(r.get("items"), list))
    f = await files_col.find_one({"is_deleted": {"$ne": True}, "parent_id": {"$exists": False}}, {"_id": 0})
    if f:
        found = await C.find_media(f["id"])
        u, _ = C.media_urls(found)
        check("find_media(id) + media_urls live", found["id"] == f["id"] and u.startswith("/") or u.startswith("http"), u)
        by_url = await C.find_media(u)
        check("find_media(url) live via variants.*.url/storage_path", by_url["id"] == f["id"])
    b = await backups_col.find_one({}, {"_id": 0, "id": 1}, sort=[("created_at", -1)])
    if b:
        req = MagicMock(); req.headers = {}; req.state = MagicMock(); req.state.request_id = "verify"
        principal = {"type": "user", "id": "verify", "email": "verify@local", "role": "admin", "scopes": ["*"]}
        ctx = C.Ctx(principal=principal, request=req, params={"backup_id": b["id"]}, dry=True)
        n_before = await backups_col.count_documents({})
        rv = await C._backup_verify(ctx)
        rp = await C._backup_plan(ctx)
        check("backup.verify live (collections/integrity)", isinstance(rv["data"].get("collections"), dict) and "integrity_ok" in rv["data"])
        check("backup.restore_plan live via restore_backup(dry_run)", rp["data"].get("dry_run") is True and isinstance(rp["data"].get("plan"), list))
        check("backup: nessuna mutation (count invariato)", await backups_col.count_documents({}) == n_before)
    else:
        check("backup live: nessun backup presente -> skip (verifica statica sola)", True)

asyncio.run(live_readonly())
ok = all(r[1] for r in results)
for n, p, d in results:
    print(("PASS " if p else "FAIL ") + n + (f"  [{d}]" if d and not p else ""))
print(f"\nTOTALE: {sum(1 for r in results if r[1])}/{len(results)}  -> {'PASS' if ok else 'FAIL'}; capability nel registry: {len(C.REGISTRY)}")
sys.exit(0 if ok else 1)
