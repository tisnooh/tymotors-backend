"""Seed script for TYMotors database.
Run: python /app/backend/seed_data.py
"""
import asyncio
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
db_name = os.environ['DB_NAME']
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]


BRANDS = [
    {
        "slug": "bmw",
        "name": "BMW",
        "tagline": "La performance à l'état pur",
        "description": "Calandres M Performance, pièces carbone, kits aérodynamiques et améliorations intérieures conçus pour les passionnés BMW.",
        "image": "https://images.unsplash.com/photo-1617531653332-bd46c24f2068?q=80&w=1600&auto=format&fit=crop",
        "logo_text": "BMW",
        "order": 1,
    },
    {
        "slug": "mercedes-benz",
        "name": "Mercedes-Benz",
        "tagline": "L'élégance rencontre la puissance",
        "description": "Accessoires inspirés AMG, éléments en carbone, améliorations intérieures et transformations haut de gamme pour Mercedes-Benz.",
        "image": "https://images.unsplash.com/photo-1618843479313-40f8afb4b4d8?auto=format&fit=crop&w=1600&q=80",
        "logo_text": "Mercedes-Benz",
        "order": 2,
    },
    {
        "slug": "audi",
        "name": "Audi",
        "tagline": "L'esprit RS sans compromis",
        "description": "Calandres sport, pièces carbone, éclairage moderne et améliorations esthétiques pour sublimer chaque Audi.",
        "image": "https://images.unsplash.com/photo-1655497520292-e445bffca81b?auto=format&fit=crop&w=1600&q=80",
        "logo_text": "Audi",
        "order": 3,
    },
    {
        "slug": "porsche",
        "name": "Porsche",
        "tagline": "Inspiré par le circuit",
        "description": "Éléments aérodynamiques, finitions premium et accessoires de performance conçus pour les passionnés Porsche.",
        "image": "https://images.unsplash.com/photo-1658863567312-fcaf9a15bc6f?auto=format&fit=crop&w=1600&q=80",
        "logo_text": "Porsche",
        "order": 4,
    },
    {
        "slug": "volkswagen",
        "name": "Volkswagen",
        "tagline": "Das Auto",
        "description": "Accessoires inspirés GTI et R, améliorations sportives et détails modernes pour personnaliser votre Volkswagen.",
        "image": "https://images.unsplash.com/photo-1680416825319-14f8091e5aeb?auto=format&fit=crop&w=1600&q=80",
        "logo_text": "Volkswagen",
        "order": 5,
    },
    {
        "slug": "toyota",
        "name": "Toyota",
        "tagline": "Conçue pour se démarquer",
        "description": "Améliorations esthétiques, accessoires modernes et pièces de personnalisation pour donner du caractère à votre Toyota.",
        "image": "https://images.unsplash.com/photo-1743308298784-ba0b26dbfac7?auto=format&fit=crop&w=1600&q=80",
        "logo_text": "Toyota",
        "order": 6,
    },
]

CATEGORIES = [
    {
        "slug": "performance",
        "name": "Performance",
        "tagline": "Aérodynamique sculpté, ADN motorsport.",
        "description": "Calandres avant, spoilers, diffuseurs, silencieux et sorties d'échappement fabriqués en fibre de carbone et alliages forgés.",
        "image": "https://images.unsplash.com/photo-1614200187524-dc4b892acf16?auto=format&fit=crop&w=1600&q=80",
        "subcategories": ["Calandres", "Spoilers", "Sorties d'échappement", "Silencieux", "Diffuseurs", "Extérieur"],
        "order": 1,
    },
    {
        "slug": "interior",
        "name": "Intérieur",
        "tagline": "Cockpit cinématique. Modernisé.",
        "description": "Volants, tableaux de bord numériques, éclairage ambiant, projecteurs de portières et finitions en fibre de carbone.",
        "image": "https://images.unsplash.com/photo-1583121274602-3e2820c69888?auto=format&fit=crop&w=1600&q=80",
        "subcategories": ["Volants", "Tableaux de bord", "Éclairage ambiant", "Projecteurs de portières", "Intérieur carbone"],
        "order": 2,
    },
    {
        "slug": "technology",
        "name": "Technologie",
        "tagline": "Matériel intelligent. Conduite connectée.",
        "description": "Écrans Apple CarPlay, dashcams, caméras de recul, gonfleurs de pneus et accessoires automobiles connectés.",
        "image": "https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?auto=format&fit=crop&w=1600&q=80",
        "subcategories": ["Écrans CarPlay", "Dashcams", "Caméras de recul", "Gonfleurs de pneus", "Accessoires connectés"],
        "order": 3,
    },
]

VEHICLE_MODELS = [
    # BMW
    {"brand_slug": "bmw", "name": "M3", "generations": ["G80 (2020+)", "F80 (2014-2018)", "E92 (2008-2013)"]},
    {"brand_slug": "bmw", "name": "M4", "generations": ["G82 (2021+)", "F82 (2014-2020)"]},
    {"brand_slug": "bmw", "name": "Série 3", "generations": ["G20 (2019+)", "F30 (2012-2018)"]},
    {"brand_slug": "bmw", "name": "Série 5", "generations": ["G30 (2017+)", "F10 (2010-2016)"]},
    {"brand_slug": "bmw", "name": "X5", "generations": ["G05 (2019+)", "F10 (2013-2018)"]},
    # Mercedes
    {"brand_slug": "mercedes-benz", "name": "Classe C", "generations": ["W206 (2021+)", "W205 (2014-2020)"]},
    {"brand_slug": "mercedes-benz", "name": "Classe E", "generations": ["W213 (2016+)", "W212 (2009-2016)"]},
    {"brand_slug": "mercedes-benz", "name": "Classe S", "generations": ["W223 (2020+)", "W222 (2013-2020)"]},
    {"brand_slug": "mercedes-benz", "name": "GLC", "generations": ["X254 (2022+)", "X253 (2015-2022)"]},
    {"brand_slug": "mercedes-benz", "name": "AMG GT", "generations": ["C190 (2014+)"]},
    # Audi
    {"brand_slug": "audi", "name": "RS3", "generations": ["8Y (2021+)", "8V (2015-2020)"]},
    {"brand_slug": "audi", "name": "RS6", "generations": ["C8 (2019+)", "C7 (2013-2018)"]},
    {"brand_slug": "audi", "name": "A4", "generations": ["B9 (2015+)", "B8 (2008-2015)"]},
    {"brand_slug": "audi", "name": "Q5", "generations": ["FY (2017+)", "8R (2008-2017)"]},
    {"brand_slug": "audi", "name": "e-tron GT", "generations": ["F8 (2021+)"]},
    # Porsche
    {"brand_slug": "porsche", "name": "911", "generations": ["992 (2019+)", "991 (2011-2019)", "997 (2004-2012)"]},
    {"brand_slug": "porsche", "name": "Cayenne", "generations": ["9YA (2017+)", "958 (2010-2017)"]},
    {"brand_slug": "porsche", "name": "Taycan", "generations": ["J1 (2019+)"]},
    {"brand_slug": "porsche", "name": "Macan", "generations": ["95B (2014+)"]},
    {"brand_slug": "porsche", "name": "Panamera", "generations": ["971 (2016+)"]},
    # VW
    {"brand_slug": "volkswagen", "name": "Golf GTI", "generations": ["Mk8 (2020+)", "Mk7 (2013-2020)"]},
    {"brand_slug": "volkswagen", "name": "Golf R", "generations": ["Mk8 (2021+)", "Mk7 (2014-2020)"]},
    {"brand_slug": "volkswagen", "name": "Tiguan", "generations": ["MQB (2016+)"]},
    {"brand_slug": "volkswagen", "name": "Passat", "generations": ["B8 (2014+)"]},
    # Toyota
    {"brand_slug": "toyota", "name": "GR Supra", "generations": ["A90 (2019+)"]},
    {"brand_slug": "toyota", "name": "GR Yaris", "generations": ["XP210 (2020+)"]},
    {"brand_slug": "toyota", "name": "Corolla", "generations": ["E210 (2018+)"]},
    {"brand_slug": "toyota", "name": "Camry", "generations": ["XV70 (2017+)"]},
    {"brand_slug": "toyota", "name": "Land Cruiser", "generations": ["J300 (2021+)"]},
]

IMG = {
    "grille": [
        "https://images.unsplash.com/photo-1605283176568-9b41fde3eba3?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1493238792000-8113da705763?auto=format&fit=crop&w=1200&q=80",
    ],
    "spoiler": [
        "https://images.unsplash.com/photo-1565043666747-69f6646db940?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?auto=format&fit=crop&w=1200&q=80",
    ],
    "exhaust": [
        "https://images.unsplash.com/photo-1611740801993-2c9c8c4b6e1b?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1614200187524-dc4b892acf16?auto=format&fit=crop&w=1200&q=80",
    ],
    "diffuser": [
        "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1542362567-b07e54358753?auto=format&fit=crop&w=1200&q=80",
    ],
    "steering": [
        "https://images.unsplash.com/photo-1583121274602-3e2820c69888?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1494976388531-d1058494cdd8?auto=format&fit=crop&w=1200&q=80",
    ],
    "dashboard": [
        "https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=1200&q=80",
    ],
    "ambient": [
        "https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1583121274602-3e2820c69888?auto=format&fit=crop&w=1200&q=80",
    ],
    "carplay": [
        "https://images.unsplash.com/photo-1606918801925-e2c914c4b503?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1592853625511-ad0b1f6a3411?auto=format&fit=crop&w=1200&q=80",
    ],
    "dashcam": [
        "https://images.unsplash.com/photo-1517524008697-84bbe3c3fd98?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1517524206127-48bbd363f3d7?auto=format&fit=crop&w=1200&q=80",
    ],
    "inflator": [
        "https://images.unsplash.com/photo-1607860108855-64acf2078ed9?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1617814076367-b759c7d7e738?auto=format&fit=crop&w=1200&q=80",
    ],
    "reverse": [
        "https://images.unsplash.com/photo-1581540222194-0def2dda95b8?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1605559424843-9e4d1c12b8ed?auto=format&fit=crop&w=1200&q=80",
    ],
    "carbon": [
        "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=1200&q=80",
    ],
}


@dataclass
class ProductSpec:
    slug: str
    name: str
    subtitle: str
    description: str
    price: float
    subcategory: str
    category_slug: str
    images: List[str]
    compatible_brands: List[str]
    badges: List[str] = field(default_factory=list)
    featured: bool = False
    compare_at_price: Optional[float] = None
    specs: Optional[dict] = None


def build_product(spec: ProductSpec) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "slug": spec.slug,
        "name": spec.name,
        "subtitle": spec.subtitle,
        "description": spec.description,
        "price": spec.price,
        "compare_at_price": spec.compare_at_price,
        "currency": "EUR",
        "images": list(spec.images),
        "category_slug": spec.category_slug,
        "subcategory": spec.subcategory,
        "compatible_brands": list(spec.compatible_brands),
        "badges": list(spec.badges),
        "sku": "TY-" + spec.slug.upper()[:14],
        "stock": 25,
        "rating": 4.8,
        "review_count": 42,
        "featured": spec.featured,
        "specs": spec.specs or {"Matériau": "Fibre de carbone", "Finition": "Brillant", "Garantie": "2 ans"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def p(slug, name, subtitle, description, price, subcategory, category_slug,
      images, compatible_brands, badges=None, featured=False, compare_at=None, specs=None):
    return build_product(ProductSpec(
        slug=slug, name=name, subtitle=subtitle, description=description,
        price=price, subcategory=subcategory, category_slug=category_slug,
        images=images, compatible_brands=compatible_brands,
        badges=badges or [], featured=featured, compare_at_price=compare_at, specs=specs,
    ))


PRODUCTS = [
    # PERFORMANCE
    p("m-performance-grille-g80", "Calandre Carbone M Performance", "BMW G80 / G82 – Montage OEM",
      "Calandre rein en fibre de carbone pré-imprégné pour BMW M3/M4 G80/G82. Vernis brillant protégé UV.",
      890.0, "Calandres", "performance", IMG["grille"], ["bmw"], ["Nouveau", "Carbone"], featured=True, compare_at=990.0),

    p("amg-night-package-grille", "Calandre Diamant AMG Night Package", "Mercedes-Benz Classe C/E/S",
      "Calandre noire à motif diamant avec accents chromés. Remplacement OEM direct pour les retrofits AMG Night Package.",
      720.0, "Calandres", "performance", IMG["grille"], ["mercedes-benz"], ["Best Seller"], featured=True),

    p("audi-rs-honeycomb-grille", "Calandre Aéro RS Nid d'abeille", "Audi A4 / A6 / RS-Line",
      "Grille honeycomb imprimée en 3D avec finition noire mat anodisée. Améliore le flux d'air de 14% vers les intercoolers.",
      640.0, "Calandres", "performance", IMG["grille"], ["audi"], ["Aéro+"]),

    p("porsche-gt3-front-splitter", "Splitter Avant GT3", "Porsche 911 992 / 991",
      "Splitter avant carbone issu de la compétition, usiné dans un seul bloc carbone, générant une appui mesurable sur l'essieu avant.",
      1490.0, "Extérieur", "performance", IMG["diffuser"], ["porsche"], ["Pro Series"], featured=True),

    p("vw-r-rear-spoiler", "Becquet Arrière R-Line", "VW Golf MK7 / MK8",
      "Spoiler en ABS qualité OEM avec finition noire brillante. Testé jusqu'à 250 km/h pour la stabilité à haute vitesse.",
      280.0, "Spoilers", "performance", IMG["spoiler"], ["volkswagen"], ["Best Seller"]),

    p("toyota-gr-aero-spoiler", "Aileron Aéro GR Performance", "Toyota GR Supra / GR Yaris",
      "Aileron arrière en fibre de carbone ajustable avec flasques motorsport. Jusqu'à 22% d'appui arrière supplémentaire.",
      820.0, "Spoilers", "performance", IMG["spoiler"], ["toyota"], ["Carbone"]),

    p("m4-quad-exhaust-tips", "Sorties d'échappement Quad Carbone M", "BMW M3 / M4 G80 / G82",
      "Âme en titane aérospatial avec manchons carbone finis à la main. Montage boulonné, sans soudure.",
      450.0, "Sorties d'échappement", "performance", IMG["exhaust"], ["bmw"], ["Titane"], featured=True),

    p("amg-quad-exhaust-tips", "Sorties d'échappement Quad AMG Sport", "Mercedes-AMG C63 / E63",
      "Sorties quad en inox poli avec signature AMG gravée au laser. Usinées CNC pour une symétrie parfaite.",
      380.0, "Sorties d'échappement", "performance", IMG["exhaust"], ["mercedes-benz"], []),

    p("porsche-titanium-silencieux", "Silencieux Titane Track", "Porsche 911 / Cayman",
      "Silencieux full titane conçu pour délivrer +18 ch et une sonorité race profonde. Homologué ECE.",
      2890.0, "Silencieux", "performance", IMG["exhaust"], ["porsche"], ["Pro Series", "Titane"]),

    p("rs6-carbon-diffuser", "Diffuseur Arrière Carbone RS6", "Audi RS6 C8",
      "Diffuseur carbone taillé pour la plateforme C8. Testé en aérodynamique pour la stabilité à vitesse autoroute.",
      1190.0, "Diffuseurs", "performance", IMG["diffuser"], ["audi"], ["Carbone"]),

    p("vw-golf-front-lip-splitter", "Lèvre Avant R-Line", "VW Golf MK7 / MK8",
      "Lèvre avant élégante en ABS renforcé. Agressivité subtile pour un raffinement quotidien.",
      210.0, "Extérieur", "performance", IMG["diffuser"], ["volkswagen"], []),

    p("supra-front-canards", "Canards Avant Aéro GR", "Toyota GR Supra A90",
      "Canards carbone posés à la main, conçus pour canaliser l'air vers les prises d'air avant. Installation boulonnée.",
      320.0, "Extérieur", "performance", IMG["diffuser"], ["toyota"], ["Carbone"]),

    # INTÉRIEUR
    p("m-performance-steering-wheel", "Volant Alcantara M Performance", "BMW Série M Performance",
      "Volant alcantara qualité course avec garniture carbone, témoins de changement de vitesse intégrés et surpiqûres tricolores.",
      1390.0, "Volants", "interior", IMG["steering"], ["bmw"], ["Best Seller", "Alcantara"], featured=True),

    p("amg-performance-steering-wheel", "Volant Alcantara AMG Performance", "Mercedes-AMG",
      "Volant alcantara AMG qualité OEM avec surpiqûres rouges et garniture carbone. Retrofit direct.",
      1290.0, "Volants", "interior", IMG["steering"], ["mercedes-benz"], ["Alcantara"]),

    p("rs-flat-bottom-wheel", "Volant Fond Plat RS", "Audi Série RS",
      "Volant fond plat RS avec insert carbone, surpiqûres contrastées et indicateur 12 heures. Plug-and-play.",
      1150.0, "Volants", "interior", IMG["steering"], ["audi"], []),

    p("gt3-rs-suede-wheel", "Volant Suède Performance GT3-RS", "Porsche 911 / Cayman / Panamera",
      "Volant suède cousu à la main avec garniture carbone et bande jaune 12 heures qualité motorsport.",
      1690.0, "Volants", "interior", IMG["steering"], ["porsche"], ["Pro Series"], featured=True),

    p("digital-cockpit-12-3", "Tableau de Bord Numérique 12,3\"", "Montage Premium Universel",
      "Cluster numérique 12,3\" 1920×720 anti-reflets avec firmware AMOLED personnalisé. Plug-and-play sur modèles VAG.",
      980.0, "Tableaux de bord", "interior", IMG["dashboard"], ["audi", "volkswagen", "porsche"], ["Nouveau"]),

    p("bmw-id8-dashboard", "Retrofit Écran Incurvé BMW iD8", "BMW Série 3 / Série 5 / X5",
      "Kit retrofit iD8 incurvé avec firmware iDrive 8.5, navigation et commandes gestuelles. Entièrement réversible.",
      1890.0, "Tableaux de bord", "interior", IMG["dashboard"], ["bmw"], ["Pro Series"]),

    p("ambient-led-pro-64", "Éclairage Ambiant LED Pro 64 Couleurs", "Montage Premium Universel",
      "Kit LED ambiant 64 couleurs avec contrôle via app, synchronisation musicale et animation pulse portières.",
      290.0, "Éclairage ambiant", "interior", IMG["ambient"], ["bmw", "mercedes-benz", "audi", "volkswagen"], ["Best Seller"], featured=True),

    p("welcome-door-projector", "Projecteur Logo Bienvenue Portière", "Montage HD Universel",
      "Projecteur LED de bienvenue HD 1080p avec logos de marques personnalisés. Boîtier aluminium usiné CNC.",
      89.0, "Projecteurs de portières", "interior", IMG["ambient"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], ["Best Seller"]),

    p("carbon-interior-trim-kit", "Kit Garnitures Intérieures Carbone", "Montage Premium Universel",
      "Kit de garnitures intérieures en fibre de carbone posé à la main. Vernis transparent résistant aux UV.",
      590.0, "Intérieur carbone", "interior", IMG["carbon"], ["bmw", "audi", "mercedes-benz", "porsche"], ["Carbone"]),

    # TECHNOLOGIE
    p("carplay-screen-12", "Écran CarPlay & Android Auto 12\" Sans Fil", "Montage Premium Universel",
      "Écran tactile QLED 12\" avec CarPlay sans fil, Android Auto, support caméra de recul AHD et mode écran partagé.",
      490.0, "Écrans CarPlay", "technology", IMG["carplay"], ["bmw", "mercedes-benz", "audi", "volkswagen", "toyota"], ["Best Seller"], featured=True),

    p("carplay-screen-10", "Écran Tactile CarPlay 10\" Sans Fil", "Montage Premium Universel",
      "Écran CarPlay IPS HD 10\" sans fil avec entrée dashcam intégrée et entrée caméra de recul. Plug-and-play.",
      350.0, "Écrans CarPlay", "technology", IMG["carplay"], ["bmw", "mercedes-benz", "audi", "volkswagen", "toyota", "porsche"], ["Nouveau"]),

    p("dashcam-4k-pro", "DashCam 4K Pro Double Objectif", "Montage Premium Universel",
      "Dashcam 4K avant + 1080p arrière avec vision nocturne, GPS, mode surveillance stationnement et support 256 Go.",
      280.0, "Dashcams", "technology", IMG["dashcam"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], ["Nouveau"], featured=True),

    p("reverse-cam-hd", "Kit Caméra de Recul AHD", "Montage Premium Universel",
      "Caméra de recul AHD 1080p avec lignes directrices dynamiques et indice IP68. Plug-and-play pour la plupart des écrans CarPlay.",
      120.0, "Caméras de recul", "technology", IMG["reverse"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], ["Best Seller"]),

    p("tire-inflator-pro", "Gonfleur de Pneus Intelligent Pro", "Montage Premium Universel",
      "Gonfleur de pneus sans fil avec arrêt automatique, jauge de pression numérique et écran OLED. 150 PSI max.",
      99.0, "Gonfleurs de pneus", "technology", IMG["inflator"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], ["Best Seller"]),

    p("smart-tpms-kit", "Kit Capteurs TPMS Sans Fil Intelligent", "Montage Premium Universel",
      "Kit TPMS 4 capteurs sans fil avec hub de charge solaire. Surveillance en temps réel de la pression et de la température.",
      149.0, "Accessoires connectés", "technology", IMG["inflator"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], []),
]


async def seed():
    print(f"Seeding database: {db_name}")
    await db.brands.delete_many({})
    for b in BRANDS:
        b = {**b, "id": str(uuid.uuid4())}
        await db.brands.insert_one(b)
    print(f"Inserted {len(BRANDS)} brands.")

    await db.categories.delete_many({})
    for c in CATEGORIES:
        c = {**c, "id": str(uuid.uuid4())}
        await db.categories.insert_one(c)
    print(f"Inserted {len(CATEGORIES)} categories.")

    await db.vehicle_models.delete_many({})
    for m in VEHICLE_MODELS:
        m = {**m, "id": str(uuid.uuid4())}
        await db.vehicle_models.insert_one(m)
    print(f"Inserted {len(VEHICLE_MODELS)} vehicle models.")

    await db.products.delete_many({})
    for p_doc in PRODUCTS:
        await db.products.insert_one(p_doc)
    print(f"Inserted {len(PRODUCTS)} products.")

    await db.products.create_index("slug", unique=True)
    await db.brands.create_index("slug", unique=True)
    await db.categories.create_index("slug", unique=True)
    await db.carts.create_index("session_id", unique=True)
    await db.wishlists.create_index("session_id", unique=True)

    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
