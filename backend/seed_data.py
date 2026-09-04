"""Demo seed data for LATO SEGRETO.
All content is placeholder / adult-safe (fashion public -> boudoir-soft secret).
No real persons are represented with authorization; images are stock placeholders.
"""
import os
import uuid
from database import (
    models_col, categories_col, articles_col, admins_col, settings_col, now_iso,
)
from auth import hash_password

UNSPLASH = [
    "photo-1524504388940-b1c1722653e1", "photo-1494790108377-be9c29b29330",
    "photo-1517841905240-472988babdf9", "photo-1534528741775-53994a69daeb",
    "photo-1524250502761-1ac6f2e30d43", "photo-1519699047748-de8e457a634e",
    "photo-1488426862026-3ee34a7d66df", "photo-1503104834685-7205e8607eb9",
    "photo-1531123897727-8f129e1688ce", "photo-1502823403499-6ccfcf4fb453",
    "photo-1500648767791-00dcc994a43e", "photo-1544005313-94ddf0286df2",
    "photo-1529626455594-4ff0802cfb7e", "photo-1524638431109-93d95c968f03",
    "photo-1506863530036-1efeddceb993", "photo-1508214751196-bcfd4ca60f91",
    "photo-1621784563330-caee0b138a00", "photo-1515202913167-d9a698095ebf",
    "photo-1512310604669-443f26c35f52",
]
PEXELS = [1631181, 1755385, 6311392, 6311617, 6935423, 7148383, 6976094,
          3757004, 2065195, 1382731, 8100784, 6976090, 7139962, 31507926, 19342940]

VID = ["pub1", "pub2", "pub3", "pub4"]
SVID = ["sec1", "sec2", "sec3", "sec4"]


def u(idx, w=900):
    pid = UNSPLASH[idx % len(UNSPLASH)]
    return f"https://images.unsplash.com/{pid}?w={w}&q=80&auto=format&fit=crop"


def p(idx, w=900):
    pid = PEXELS[idx % len(PEXELS)]
    return f"https://images.pexels.com/photos/{pid}/pexels-photo-{pid}.jpeg?auto=compress&cs=tinysrgb&w={w}"


PRESETS = {
    'bordeaux': ('40 55% 60%', '350 45% 30%'),
    'tattoo': ('35 25% 72%', '355 60% 36%'),
    'dolce': ('28 60% 68%', '338 45% 52%'),
    'sportiva': ('190 45% 55%', '220 40% 42%'),
    'cosplay': ('275 50% 62%', '320 55% 46%'),
}

REGIA_PRESETS = {
    'bordeaux': {"preset": "SENSUALE", "fumo": 35, "luci": 55, "glow": 40, "movimento": 25, "effetto_sonoro": "sensuale_01", "ambiente_sonoro": {"attivo": False, "preset": "warm_room", "volume": 12}},
    'tattoo': {"preset": "INTENSO", "fumo": 55, "luci": 45, "glow": 60, "movimento": 40, "effetto_sonoro": "cinematografico", "ambiente_sonoro": {"attivo": False, "preset": "dark_room", "volume": 12}},
    'dolce': {"preset": "DELICATO", "fumo": 20, "luci": 60, "glow": 30, "movimento": 15, "effetto_sonoro": "soft", "ambiente_sonoro": {"attivo": False, "preset": "warm_room", "volume": 10}},
    'sportiva': {"preset": "SENSUALE", "fumo": 25, "luci": 65, "glow": 35, "movimento": 45, "effetto_sonoro": "sensuale_02", "ambiente_sonoro": {"attivo": False, "preset": "warm_room", "volume": 10}},
    'cosplay': {"preset": "INTENSO", "fumo": 45, "luci": 50, "glow": 55, "movimento": 35, "effetto_sonoro": "cinematografico", "ambiente_sonoro": {"attivo": False, "preset": "dark_room", "volume": 12}},
}

DEFAULT_PELLICOLA = {
    "attiva": True,
    "titolo": "IN MOVIMENTO",
    "sottotitolo": "Una foto non racconta tutto.",
    "velocita": 6,               # seconds per tile (higher = slower)
    "max_video_attivi": 8,       # 6-10
    "seconda_fila": False,       # prepared but OFF by default
    "pausa_su_touch": True,
    "nomi_sempre_visibili": False,
    "inserisci_dopo_n": 10,      # insert strip after N cards (8-12)
}

# name, artistico, slug, frase, categorie, tag, badge, badge_tipo, preset, of_slug
SPECS = [
    ("Francesca", "Francesca Rossi", "francesca-rossi", "Dolce finch\u00e9 non premi.",
     ["eleganti", "more"], ["elegante", "boudoir", "raffinata"], "IN TENDENZA", "editoriale", "bordeaux", "francesca_demo"),
    ("Vanessa", "Vanessa Neri", "vanessa-neri", "Ogni tatuaggio \u00e8 un segreto.",
     ["tatuate", "more"], ["tattoo", "alternativa", "dark"], "NUOVA", "editoriale", "tattoo", "vanessa_demo"),
    ("Federica", "Federica Sole", "federica-sole", "Ti sfido a starmi dietro.",
     ["sportive", "bionde"], ["sportiva", "dinamica", "fit"], "SCELTA DEL GIORNO", "editoriale", "sportiva", "federica_demo"),
    ("Giulia", "Giulia Bianchi", "giulia-bianchi", "Sembro un angelo, lo so.",
     ["bionde", "eleganti"], ["dolce", "soft", "angelica"], None, "editoriale", "dolce", "giulia_demo"),
    ("Martina", "Martina Conte", "martina-conte", "L'eleganza \u00e8 solo l'inizio.",
     ["eleganti", "more"], ["elegante", "chic", "fashion"], "IN TENDENZA", "editoriale", "bordeaux", "martina_demo"),
    ("Sofia", "Sofia Marino", "sofia-marino", "Posso essere chiunque tu voglia.",
     ["cosplay"], ["cosplay", "fantasy", "creativa"], "NUOVA", "editoriale", "cosplay", "sofia_demo"),
    ("Chiara", "Chiara Greco", "chiara-greco", "Il caldo del sud, addosso.",
     ["latine", "more"], ["latina", "sensuale", "estate"], None, "editoriale", "bordeaux", "chiara_demo"),
    ("Alice", "Alice Ferrari", "alice-ferrari", "Non giudicarmi dalla copertina.",
     ["bionde", "eleganti"], ["elegante", "misteriosa"], None, "editoriale", "dolce", "alice_demo"),
    ("Elena", "Elena Costa", "elena-costa", "Sotto la pelle, un'altra storia.",
     ["tatuate"], ["tattoo", "ribelle", "notte"], None, "editoriale", "tattoo", "elena_demo"),
    ("Aurora", "Aurora Villa", "aurora-villa", "Il movimento \u00e8 la mia seduzione.",
     ["sportive", "more"], ["sportiva", "energia"], "NUOVA", "editoriale", "sportiva", "aurora_demo"),
]

CATEGORIES = [
    ("Eleganti", "eleganti", "Le creator dallo stile pi\u00f9 raffinato: fashion, luce morbida e classe senza tempo.", "Modelle Eleganti | LATO SEGRETO", "Scopri le creator pi\u00f9 eleganti e raffinate. Fashion, ritratti e un lato segreto tutto da svelare."),
    ("More", "more", "Fascino intenso e sguardi profondi: la nostra selezione di creator more.", "Modelle More | LATO SEGRETO", "Le creator more pi\u00f9 magnetiche del progetto. Entra e scopri il loro lato segreto."),
    ("Bionde", "bionde", "Luce, calore e dolcezza: le creator bionde da conoscere.", "Modelle Bionde | LATO SEGRETO", "Selezione delle creator bionde pi\u00f9 seguite. Un lato pubblico dolce e un lato segreto sorprendente."),
    ("Tatuate", "tatuate", "Ogni tatuaggio racconta un desiderio: le creator tatuate e alternative.", "Modelle Tatuate | LATO SEGRETO", "Le creator tatuate e alternative del progetto. Stile dark, carattere e un lato segreto intenso."),
    ("Sportive", "sportive", "Energia, corpo e disciplina: le creator sportive e dinamiche.", "Modelle Sportive | LATO SEGRETO", "Creator sportive e dinamiche. Un lato pubblico atletico e un lato segreto tutto da scoprire."),
    ("Cosplay", "cosplay", "Fantasia e trasformazione: le creator cosplay pi\u00f9 creative.", "Modelle Cosplay | LATO SEGRETO", "Le creator cosplay del progetto. Personaggi, fantasia e un lato segreto sorprendente."),
    ("Latine", "latine", "Il calore latino in ogni scatto: creator sensuali e solari.", "Modelle Latine | LATO SEGRETO", "Creator latine dal fascino caldo e solare. Scopri il loro lato segreto."),
]

ARTICLES = [
    ("Come nasce l'esperienza LATO SEGRETO", "come-nasce-esperienza-lato-segreto",
     "Dietro le quinte del concept che trasforma ogni profilo davanti ai tuoi occhi.",
     "<p>LATO SEGRETO nasce da un'idea semplice: la curiosit\u00e0 \u00e8 il motore del desiderio. Ogni creator ha due identit\u00e0 sulla stessa pagina, un lato pubblico elegante e un lato segreto pi\u00f9 intimo.</p><h2>Il momento della trasformazione</h2><p>Il cuore del progetto \u00e8 la transizione cinematografica: la pagina cambia luce, colori e contenuti in meno di un secondo.</p>",
     "esperienza premium creator", ["eleganti"], ["francesca-rossi", "martina-conte"]),
    ("Guida ai profili tatuati: stile e carattere", "guida-profili-tatuati-stile-carattere",
     "Perch\u00e9 le creator tatuate stanno conquistando il pubblico premium.",
     "<p>Il fascino alternativo ha un pubblico dedicato. Le creator tatuate uniscono estetica dark e forte personalit\u00e0.</p><h2>Chi seguire</h2><p>Nella nostra selezione trovi profili dallo stile deciso e riconoscibile.</p>",
     "modelle tatuate", ["tatuate"], ["vanessa-neri", "elena-costa"]),
    ("Fitness e sensualit\u00e0: le creator sportive", "fitness-e-sensualita-creator-sportive",
     "Energia e disciplina diventano seduzione: viaggio tra le creator sportive.",
     "<p>Il corpo allenato racconta impegno e cura. Le creator sportive portano dinamismo e freschezza al progetto.</p>",
     "modelle sportive", ["sportive"], ["federica-sole", "aurora-villa"]),
]


def build_model(i, spec, order):
    (nome, artistico, slug, frase, categorie, tag, badge, badge_tipo, preset, of_slug) = spec
    prim, sec = PRESETS[preset]
    base = i * 2
    # public media (3 photos)
    pub_imgs = [u(base), u(base + 1), u(base + 2)]
    sec_imgs = [p(base), p(base + 1), p(base + 2)]
    # videos (2)
    vpub = [VID[i % len(VID)], VID[(i + 1) % len(VID)]]
    vsec = [SVID[i % len(SVID)], SVID[(i + 1) % len(SVID)]]

    def mi(url, tipo='image', poster='', alt=''):
        return {"tipo": tipo, "url": url, "poster": poster, "alt": alt}

    # media pairs = 3 photo positions + 2 video positions (same grid slots)
    media_pairs = []
    for k in range(3):
        media_pairs.append({
            "id": str(uuid.uuid4()), "tipo": "image",
            "pubblico": mi(pub_imgs[k], 'image', '', f"{artistico} foto pubblica {k+1}"),
            "segreto": mi(sec_imgs[k], 'image', '', f"{artistico} foto segreta {k+1}"),
        })
    for k in range(2):
        media_pairs.append({
            "id": str(uuid.uuid4()), "tipo": "video",
            "pubblico": mi(f"/media/{vpub[k]}.mp4", 'video', f"/media/{vpub[k]}.jpg", f"{artistico} video pubblico {k+1}"),
            "segreto": mi(f"/media/{vsec[k]}.mp4", 'video', f"/media/{vsec[k]}.jpg", f"{artistico} video segreto {k+1}"),
        })

    hero_pub = pub_imgs[0]
    hero_sec = sec_imgs[0]
    gal_pub = pub_imgs

    bio = (f"{artistico} \u00e8 una creator dallo stile {tag[0]}. Nel suo lato pubblico trovi "
           f"ritratti curati, outfit ricercati e un'atmosfera raffinata. Una presenza magnetica "
           f"che unisce eleganza e naturalezza in ogni scatto.")
    bio_seg = (f"Ma c'\u00e8 un lato che {nome} mostra solo a chi sceglie di premere. "
               f"Luci pi\u00f9 intime, sguardi pi\u00f9 diretti, un'atmosfera che cambia completamente. "
               f"Il resto, per\u00f2, \u00e8 solo sul suo profilo.")

    return {
        "id": str(uuid.uuid4()),
        "nome": nome,
        "nome_artistico": artistico,
        "slug": slug,
        "frase": frase,
        "bio": bio,
        "bio_segreta": bio_seg,
        "foto_copertina": hero_pub,
        "foto_card": hero_pub,
        "foto_card_teaser": hero_sec,
        "foto_segreta_hero": hero_sec,
        "galleria_pubblica": [mi(g, 'image', '', f"{artistico} lifestyle") for g in gal_pub],
        "galleria_segreta": [mi(g, 'image', '', f"{artistico} boudoir") for g in sec_imgs],
        "media_pairs": media_pairs,
        "categorie": categorie,
        "tag": tag,
        "badge": badge,
        "badge_tipo": badge_tipo,
        "onlyfans_url": f"https://onlyfans.com/{of_slug}",
        "cta_testo": "CONTINUA CON ME",
        "tema": {
            "preset": preset,
            "colore_primario": prim,
            "colore_secondario": sec,
            "grain": 0.08,
            "glow": True,
            "sfondo_stile": "vignetta",
            "frase_attivazione": "NON DOVRESTI PREMERLO",
            "testo_dopo_click": "Te l'avevamo detto.",
            "effetti_touch": True,
        },
        "messaggio_35s": {
            "attivo": True,
            "timer": 35,
            "testo": f"Se sei ancora qui, forse {nome} vorrebbe mostrarti il resto\u2026",
            "foto": hero_sec,
            "video": "",
            "cta_testo": "CONTINUA CON ME",
        },
        "seo": {
            "title": f"{artistico} | LATO SEGRETO",
            "meta_description": f"Scopri {artistico}: ritratti, stile e un lato segreto tutto da svelare. Premi e lasciati sorprendere.",
            "alt_default": f"{artistico} - creator LATO SEGRETO",
            "og_image": hero_pub,
        },
        "teaser_copy": "Qui posso mostrarti solo fino a questo punto.",
        "regia": REGIA_PRESETS.get(preset, REGIA_PRESETS['bordeaux']),
        "cta_temporizzata": {
            "attivo": True, "ritardo": 10,
            "testo_intro": "Vuoi vedere dove continua?",
            "testo_pulsante": "CONTINUA CON ME",
        },
        "social": ({
            "instagram": f"https://instagram.com/{of_slug}",
            "tiktok": f"https://tiktok.com/@{of_slug}",
            "telegram": f"https://t.me/{of_slug}",
            "custom": [],
        } if i < 4 else {"instagram": f"https://instagram.com/{of_slug}", "custom": []}),
        "pellicola_home": {
            "attiva": True,
            "priorita": ((i * 3) % 10) + 1,
            "ordine": None,
            "pubblico": {
                "video_url": f"/media/{vpub[0]}.mp4",
                "poster_url": f"/media/{vpub[0]}.jpg",
            },
            "segreto": {
                "video_url": f"/media/{vsec[0]}.mp4",
                "poster_url": f"/media/{vsec[0]}.jpg",
            },
        },
        "stato": "pubblicata",
        "ordine": order,
        "conferma_maggiorenne": True,
        "data_pubblicazione": now_iso(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


async def seed_all(force=False):
    # Admin user
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@latosegreto.it')
    admin_pw = os.environ.get('ADMIN_PASSWORD', 'LatoSegreto2025!')
    existing_admin = await admins_col.find_one({"email": admin_email})
    if not existing_admin:
        await admins_col.insert_one({
            "id": str(uuid.uuid4()),
            "email": admin_email,
            "password_hash": hash_password(admin_pw),
            "ruolo": "amministratore",
            "created_at": now_iso(),
        })

    # Settings singleton
    if not await settings_col.find_one({"id": "global"}):
        await settings_col.insert_one({
            "id": "global",
            "brand_name": "LATO SEGRETO",
            "site_description": "Il lato che non hai ancora visto. Creator premium, un lato pubblico elegante e un lato segreto tutto da svelare.",
            "auto_publish_articles": False,
            "footer_contatti": "contatti@latosegreto.it",
            "global_switch_default": "public",
            "home_pellicola": DEFAULT_PELLICOLA,
            "created_at": now_iso(),
        })
    else:
        # backfill pellicola settings if missing (non-destructive)
        s = await settings_col.find_one({"id": "global"})
        if not s.get("home_pellicola"):
            await settings_col.update_one({"id": "global"}, {"$set": {"home_pellicola": DEFAULT_PELLICOLA}})

    # Categories
    if force:
        await categories_col.delete_many({})
    if await categories_col.count_documents({}) == 0:
        for i, (nome, slug, desc, st, md) in enumerate(CATEGORIES):
            await categories_col.insert_one({
                "id": str(uuid.uuid4()), "nome": nome, "slug": slug,
                "descrizione": desc, "seo_title": st, "meta_description": md,
                "immagine": u(i), "ordine": i, "indicizzabile": True,
                "stato": "pubblicata", "created_at": now_iso(),
            })

    # Models
    if force:
        await models_col.delete_many({})
    if await models_col.count_documents({}) == 0:
        for i, spec in enumerate(SPECS):
            await models_col.insert_one(build_model(i, spec, i))

    # Articles
    if force:
        await articles_col.delete_many({})
    if await articles_col.count_documents({}) == 0:
        for i, (titolo, slug, estratto, contenuto, kw, cats, related) in enumerate(ARTICLES):
            await articles_col.insert_one({
                "id": str(uuid.uuid4()), "titolo": titolo, "slug": slug,
                "estratto": estratto, "contenuto": contenuto,
                "immagine_principale": u(i + 5), "immagini_interne": [],
                "autore": "Redazione", "data_pubblicazione": now_iso(),
                "data_aggiornamento": now_iso(), "stato": "pubblicato",
                "categorie": cats, "tag": [kw], "keyword_principale": kw,
                "keyword_secondarie": [], "seo_title": f"{titolo} | LATO SEGRETO",
                "meta_description": estratto, "canonical": "", "alt_text": titolo,
                "og_image": u(i + 5), "internal_links": [], "cta": {},
                "indicizzabile": True, "modelle_correlate": related,
                "fonte": "manuale", "created_at": now_iso(),
            })
