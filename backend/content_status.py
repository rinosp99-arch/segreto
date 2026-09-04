"""DEMO/REALE detection (with manual per-media override) and publication readiness.

Two independent concepts:
- content_status: is the content DEMO (temporary) or REALE (real)?  -> respects manual overrides
- readiness: are all REQUIRED fields present so the model can be PUBLISHED?

Manual override: model.content_overrides is a dict { <key>: 'demo' | 'reale' } (or 'auto'/absent).
When set to 'reale' the media is treated as real even if the URL looks like demo, and vice versa.
This avoids false positives with CDNs / external URLs.
"""

DEMO_MEDIA_MARKERS = ("images.unsplash.com", "images.pexels.com")


def _auto_is_demo_media(url) -> bool:
    if not url:
        return False
    u = str(url)
    if u.startswith("/media/"):
        return True
    return any(m in u for m in DEMO_MEDIA_MARKERS)


def _auto_is_demo_link(url) -> bool:
    return bool(url) and "_demo" in str(url)


def _effective_demo(url, key, overrides, kind="media") -> bool:
    """Apply manual override if present, else auto-detect."""
    ov = (overrides or {}).get(key, "auto")
    if ov == "reale":
        return False
    if ov == "demo":
        return bool(url)  # only counts as demo if a value exists
    return _auto_is_demo_link(url) if kind == "link" else _auto_is_demo_media(url)


def _nz(v) -> bool:
    return bool(v and str(v).strip())


def compute_content_status(doc: dict) -> dict:
    ov = doc.get("content_overrides") or {}
    demo = []

    def add(label):
        if label not in demo:
            demo.append(label)

    if _effective_demo(doc.get("foto_card"), "foto_card", ov):
        add("Foto card Home")
    if _effective_demo(doc.get("foto_copertina"), "foto_copertina", ov):
        add("Foto Lato Pubblico")
    if _effective_demo(doc.get("foto_card_teaser"), "foto_card_teaser", ov):
        add("Foto teaser segreta")
    if _effective_demo(doc.get("foto_segreta_hero"), "foto_segreta_hero", ov):
        add("Foto Lato Segreto")
    if _effective_demo((doc.get("seo") or {}).get("og_image"), "seo_og", ov):
        add("Immagine OG (SEO)")

    # media pairs
    for pr in doc.get("media_pairs", []) or []:
        pid = pr.get("id") or ""
        tipo = pr.get("tipo")
        pub = pr.get("pubblico") or {}
        sec = pr.get("segreto") or {}
        if _effective_demo(pub.get("url"), f"pair:{pid}:pubblico", ov):
            add("Video Lato Pubblico" if tipo == "video" else "Foto Lato Pubblico (coppie)")
        if _effective_demo(sec.get("url"), f"pair:{pid}:segreto", ov):
            add("Video Lato Segreto" if tipo == "video" else "Foto Lato Segreto (coppie)")
        if tipo == "video":
            if _effective_demo(pub.get("poster"), f"pair:{pid}:poster_pub", ov) or \
               _effective_demo(sec.get("poster"), f"pair:{pid}:poster_sec", ov):
                add("Poster video")

    # pellicola
    ph = doc.get("pellicola_home") or {}
    pub = ph.get("pubblico") or {}
    sec = ph.get("segreto") or {}
    if _effective_demo(pub.get("video_url"), "pel_pub_video", ov) or _effective_demo(pub.get("poster_url"), "pel_pub_poster", ov):
        add("Video Pellicola Pubblico")
    if _effective_demo(sec.get("video_url"), "pel_sec_video", ov) or _effective_demo(sec.get("poster_url"), "pel_sec_poster", ov):
        add("Video Pellicola Segreto")

    # secret message media
    msg = doc.get("messaggio_35s") or {}
    if _effective_demo(msg.get("foto"), "msg_foto", ov) or _effective_demo(msg.get("video"), "msg_video", ov):
        add("Messaggio segreto (media)")

    # external links (auto only; overridable via onlyfans key)
    if _effective_demo(doc.get("onlyfans_url"), "onlyfans", ov, kind="link"):
        add("Link OnlyFans")
    social = doc.get("social") or {}
    social_demo = False
    for k, v in social.items():
        if k == "custom":
            for c in (v or []):
                if isinstance(c, dict) and _auto_is_demo_link(c.get("url")):
                    social_demo = True
        elif _auto_is_demo_link(v):
            social_demo = True
    if social_demo:
        add("Social")

    return {"is_demo": len(demo) > 0, "demo_fields": demo, "demo_count": len(demo)}


def _count_pairs(doc, tipo, side):
    n = 0
    for pr in doc.get("media_pairs", []) or []:
        if pr.get("tipo") == tipo and _nz((pr.get(side) or {}).get("url")):
            n += 1
    return n


def _pellicola_effective(ph, doc, side):
    """Resolve pellicola video for a side: explicit config or fallback to first video pair."""
    s = (ph.get(side) or {})
    if _nz(s.get("video_url")):
        return True
    for pr in doc.get("media_pairs", []) or []:
        if pr.get("tipo") == "video" and _nz((pr.get(side) or {}).get("url")):
            return True
    return False


def compute_readiness(doc: dict) -> dict:
    """REQUIRED-only checklist for publication. Optional items are warnings, never blocking."""
    pub_photos = _count_pairs(doc, "image", "pubblico")
    if pub_photos == 0:
        pub_photos = len([g for g in (doc.get("galleria_pubblica") or []) if _nz(g.get("url"))])
    sec_photos = _count_pairs(doc, "image", "segreto")
    if sec_photos == 0:
        sec_photos = len([g for g in (doc.get("galleria_segreta") or []) if _nz(g.get("url"))])
    pub_videos = _count_pairs(doc, "video", "pubblico")
    sec_videos = _count_pairs(doc, "video", "segreto")

    checklist = [
        {"label": "Creator maggiorenne confermata", "ok": bool(doc.get("conferma_maggiorenne")), "required": True},
        {"label": "Nome", "ok": _nz(doc.get("nome")), "required": True},
        {"label": "Slug (URL)", "ok": _nz(doc.get("slug")), "required": True},
        {"label": "Foto card Home", "ok": _nz(doc.get("foto_card")), "required": True},
        {"label": "3 foto Lato Pubblico", "ok": pub_photos >= 3, "required": True},
        {"label": "3 foto Lato Segreto", "ok": sec_photos >= 3, "required": True},
        {"label": "Video pubblico 1", "ok": pub_videos >= 1, "required": True},
        {"label": "Video segreto 1", "ok": sec_videos >= 1, "required": True},
        {"label": "Claim", "ok": _nz(doc.get("frase")), "required": True},
        {"label": "Descrizione pubblica", "ok": _nz(doc.get("bio")), "required": True},
        {"label": "Descrizione Lato Segreto", "ok": _nz(doc.get("bio_segreta")), "required": True},
        {"label": "Link OnlyFans", "ok": _nz(doc.get("onlyfans_url")), "required": True},
    ]

    ph = doc.get("pellicola_home") or {}
    if ph.get("attiva", False):
        checklist.append({"label": "Video Pellicola pubblico", "ok": _pellicola_effective(ph, doc, "pubblico"), "required": True})
        checklist.append({"label": "Video Pellicola segreto", "ok": _pellicola_effective(ph, doc, "segreto"), "required": True})

    # optional warnings
    social = doc.get("social") or {}
    checklist.append({"label": "Instagram (opzionale)", "ok": _nz(social.get("instagram")), "required": False})
    checklist.append({"label": "TikTok (opzionale)", "ok": _nz(social.get("tiktok")), "required": False})

    missing = [c["label"] for c in checklist if c["required"] and not c["ok"]]
    pellicola_labels = {"Video Pellicola pubblico", "Video Pellicola segreto"}
    profile_missing = [m for m in missing if m not in pellicola_labels]
    pellicola_missing = [m for m in missing if m in pellicola_labels]
    return {
        "checklist": checklist,
        "missing_required": missing,
        "missing_count": len(missing),
        "is_ready": len(missing) == 0,
        "profile_missing": profile_missing,
        "profile_ready": len(profile_missing) == 0,
        "pellicola_missing": pellicola_missing,
        "pellicola_ready": len(pellicola_missing) == 0,
    }


def compute_operational_state(doc: dict, readiness: dict) -> str:
    if doc.get("stato") == "pubblicata":
        return "pubblicata"
    return "pronta" if readiness.get("is_ready") else "incompleta"


def full_status(doc: dict) -> dict:
    cs = compute_content_status(doc)
    rd = compute_readiness(doc)
    return {
        "content_status": cs,
        "readiness": rd,
        "stato_operativo": compute_operational_state(doc, rd),
    }
