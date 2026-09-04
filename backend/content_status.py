"""Detect whether a model still uses DEMO placeholder content or REAL content.

Demo markers (temporary test content shipped with the app):
- images from stock hosts: images.unsplash.com / images.pexels.com
- locally generated demo teaser clips/posters under /media/
- demo external links containing the "_demo" suffix (seed uses e.g. francesca_demo)

Real content will point either to uploaded object-storage URLs (/api/uploads/...)
or to the owner's own absolute URLs, and real links won't contain "_demo".
"""

DEMO_MEDIA_MARKERS = ("images.unsplash.com", "images.pexels.com")


def _is_demo_media(url) -> bool:
    if not url:
        return False
    u = str(url)
    if u.startswith("/media/"):
        return True
    return any(m in u for m in DEMO_MEDIA_MARKERS)


def _is_demo_link(url) -> bool:
    if not url:
        return False
    return "_demo" in str(url)


def _any_demo_in_list(items, keys):
    for it in items or []:
        if not isinstance(it, dict):
            continue
        for k in keys:
            if _is_demo_media(it.get(k)):
                return True
    return False


def compute_content_status(doc: dict) -> dict:
    """Return {is_demo, demo_fields, total_checked} for a model document."""
    demo = []

    def check(label, url, kind="media"):
        is_demo = _is_demo_link(url) if kind == "link" else _is_demo_media(url)
        if is_demo and label not in demo:
            demo.append(label)

    # Home / hero photos
    check("Foto card Home", doc.get("foto_card"))
    check("Foto Lato Pubblico", doc.get("foto_copertina"))
    check("Foto teaser segreta", doc.get("foto_card_teaser"))
    check("Foto Lato Segreto", doc.get("foto_segreta_hero"))
    check("Immagine OG (SEO)", (doc.get("seo") or {}).get("og_image"))

    # galleries
    if _any_demo_in_list(doc.get("galleria_pubblica"), ["url"]):
        demo.append("Galleria pubblica")
    if _any_demo_in_list(doc.get("galleria_segreta"), ["url"]):
        demo.append("Galleria segreta")

    # media pairs (foto + video, pubblico + segreto + poster)
    foto_pub = foto_sec = vid_pub = vid_sec = poster = False
    for pr in doc.get("media_pairs", []) or []:
        tipo = pr.get("tipo")
        pub = pr.get("pubblico") or {}
        sec = pr.get("segreto") or {}
        if tipo == "video":
            vid_pub = vid_pub or _is_demo_media(pub.get("url"))
            vid_sec = vid_sec or _is_demo_media(sec.get("url"))
            poster = poster or _is_demo_media(pub.get("poster")) or _is_demo_media(sec.get("poster"))
        else:
            foto_pub = foto_pub or _is_demo_media(pub.get("url"))
            foto_sec = foto_sec or _is_demo_media(sec.get("url"))
    if foto_pub:
        demo.append("Foto Lato Pubblico (coppie)")
    if foto_sec:
        demo.append("Foto Lato Segreto (coppie)")
    if vid_pub:
        demo.append("Video Lato Pubblico")
    if vid_sec:
        demo.append("Video Lato Segreto")
    if poster:
        demo.append("Poster video")

    # pellicola home
    ph = doc.get("pellicola_home") or {}
    pub = ph.get("pubblico") or {}
    sec = ph.get("segreto") or {}
    if _is_demo_media(pub.get("video_url")) or _is_demo_media(pub.get("poster_url")):
        demo.append("Video Pellicola Pubblico")
    if _is_demo_media(sec.get("video_url")) or _is_demo_media(sec.get("poster_url")):
        demo.append("Video Pellicola Segreto")

    # secret message media
    msg = doc.get("messaggio_35s") or {}
    if _is_demo_media(msg.get("foto")) or _is_demo_media(msg.get("video")):
        demo.append("Messaggio segreto (media)")

    # external links
    check("Link OnlyFans", doc.get("onlyfans_url"), kind="link")
    social = doc.get("social") or {}
    social_demo = False
    for k, v in social.items():
        if k == "custom":
            for c in (v or []):
                if isinstance(c, dict) and _is_demo_link(c.get("url")):
                    social_demo = True
        elif _is_demo_link(v):
            social_demo = True
    if social_demo:
        demo.append("Social")

    return {
        "is_demo": len(demo) > 0,
        "demo_fields": demo,
        "demo_count": len(demo),
    }
