from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Any, Dict


class LoginIn(BaseModel):
    email: str
    password: str


class MediaItem(BaseModel):
    model_config = ConfigDict(extra='ignore')
    tipo: str = 'image'  # image | video
    url: str = ''
    poster: Optional[str] = ''
    alt: Optional[str] = ''


class MediaPair(BaseModel):
    model_config = ConfigDict(extra='ignore')
    id: Optional[str] = None
    tipo: str = 'image'
    pubblico: MediaItem = Field(default_factory=MediaItem)
    segreto: MediaItem = Field(default_factory=MediaItem)


class TemaSegreto(BaseModel):
    model_config = ConfigDict(extra='ignore')
    preset: str = 'bordeaux'  # bordeaux | tattoo | dolce | sportiva | cosplay
    colore_primario: str = '40 55% 60%'
    colore_secondario: str = '350 45% 28%'
    grain: float = 0.08
    glow: bool = True
    sfondo_stile: str = 'vignetta'
    frase_attivazione: str = 'NON DOVRESTI PREMERLO'
    testo_dopo_click: str = "Te l'avevamo detto."
    effetti_touch: bool = True


class Messaggio35s(BaseModel):
    model_config = ConfigDict(extra='ignore')
    attivo: bool = True
    timer: int = 35
    testo: str = 'Se sei ancora qui, forse dovresti venire a vedere il resto…'
    foto: Optional[str] = ''
    video: Optional[str] = ''
    cta_testo: str = 'CONTINUA CON ME'


class SeoFields(BaseModel):
    """Full SEO field-set (per page). extra='allow' so future fields survive round-trips."""
    model_config = ConfigDict(extra='allow')
    title: str = ''
    meta_description: str = ''
    alt_default: str = ''
    og_image: str = ''
    # SUPER API additions
    canonical: str = ''
    robots: str = 'index,follow'
    og_title: str = ''
    og_description: str = ''
    structured_data_type: str = 'ProfilePage'
    keywords: List[str] = []
    topics: List[str] = []
    indexable: bool = True
    internal_links: List[Dict[str, Any]] = []


class PellicolaSide(BaseModel):
    model_config = ConfigDict(extra='ignore')
    video_url: str = ''
    poster_url: str = ''


class PellicolaHome(BaseModel):
    """Per-model configuration for the HOME 'IN MOVIMENTO' film strip."""
    model_config = ConfigDict(extra='ignore')
    attiva: bool = True
    priorita: int = 5  # 1-10
    ordine: Optional[int] = None  # manual override, null -> use priorita
    pubblico: PellicolaSide = Field(default_factory=PellicolaSide)
    segreto: PellicolaSide = Field(default_factory=PellicolaSide)


class ModelIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nome: str
    nome_artistico: Optional[str] = ''
    slug: Optional[str] = ''
    frase: str = ''
    bio: str = ''
    bio_segreta: str = ''
    foto_copertina: str = ''
    foto_card: str = ''
    foto_card_teaser: str = ''
    foto_segreta_hero: str = ''
    galleria_pubblica: List[MediaItem] = []
    galleria_segreta: List[MediaItem] = []
    media_pairs: List[MediaPair] = []
    categorie: List[str] = []
    tag: List[str] = []
    badge: Optional[str] = None
    badge_tipo: Optional[str] = 'editoriale'  # editoriale | dati
    onlyfans_url: str = ''
    cta_testo: str = 'CONTINUA CON ME'
    tema: TemaSegreto = Field(default_factory=TemaSegreto)
    messaggio_35s: Messaggio35s = Field(default_factory=Messaggio35s)
    seo: SeoFields = Field(default_factory=SeoFields)
    teaser_copy: str = 'Qui posso mostrarti solo fino a questo punto.'
    regia: Dict[str, Any] = {}
    cta_temporizzata: Dict[str, Any] = {}
    social: Dict[str, Any] = {}
    pellicola_home: PellicolaHome = Field(default_factory=PellicolaHome)
    content_overrides: Dict[str, str] = {}
    stato: str = 'bozza'  # bozza | pubblicata | disattivata | archiviata
    ordine: int = 0
    conferma_maggiorenne: bool = False
    data_pubblicazione: Optional[str] = None
    analytics: Dict[str, Any] = {}  # per-model tracking config (utm defaults, goals)
    is_deleted: bool = False


class CategoryIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nome: str
    slug: Optional[str] = ''
    descrizione: str = ''
    seo_title: str = ''
    meta_description: str = ''
    immagine: str = ''
    ordine: int = 0
    indicizzabile: bool = True
    stato: str = 'pubblicata'


class ArticleIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    titolo: str
    slug: Optional[str] = ''
    estratto: str = ''
    contenuto: str = ''
    immagine_principale: str = ''
    immagini_interne: List[str] = []
    autore: str = 'Redazione'
    data_pubblicazione: Optional[str] = None
    stato: str = 'bozza'
    categorie: List[str] = []
    tag: List[str] = []
    keyword_principale: str = ''
    keyword_secondarie: List[str] = []
    seo_title: str = ''
    meta_description: str = ''
    canonical: str = ''
    alt_text: str = ''
    og_image: str = ''
    internal_links: List[Dict[str, Any]] = []
    cta: Dict[str, Any] = {}
    indicizzabile: bool = True
    modelle_correlate: List[str] = []


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    brand_name: Optional[str] = None
    auto_publish_articles: Optional[bool] = None
    site_description: Optional[str] = None
    footer_contatti: Optional[str] = None
    global_switch_default: Optional[str] = None
    home_pellicola: Optional[Dict[str, Any]] = None


class TrackEventIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    tipo: str
    model_id: Optional[str] = None
    model_slug: Optional[str] = None
    article_id: Optional[str] = None
    session_id: str = ''
    cta_source: Optional[str] = None
    valore: Optional[float] = None
    referrer: Optional[str] = None
    ref: Optional[str] = None
    fonte: Optional[str] = None
    campagna: Optional[str] = None
    meta: Dict[str, Any] = {}


class WebhookArticleIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    titolo: str
    slug: Optional[str] = ''
    estratto: str = ''
    contenuto: str = ''
    immagine_principale: str = ''
    autore: Optional[str] = 'Soro SEO'
    categorie: List[str] = []
    tag: List[str] = []
    keyword_principale: str = ''
    keyword_secondarie: List[str] = []
    seo_title: str = ''
    meta_description: str = ''
    external_id: Optional[str] = None
