"""Catalogue historique déclaratif.

Ces données servent uniquement à l'import Supabase de staging. Les produits sont
forcés en brouillon par le constructeur ``p`` et doivent être vérifiés avant
toute activation.
"""
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional


BRANDS = [
    {
        "slug": "bmw",
        "name": "BMW",
        "tagline": "La performance à l'état pur",
        "description": "Calandres sport, éléments aérodynamiques et améliorations intérieures conçus pour les passionnés BMW.",
        "image": "https://images.unsplash.com/photo-1617531653332-bd46c24f2068?q=80&w=1600&auto=format&fit=crop",
        "logo_text": "BMW",
        "order": 1,
    },
    {
        "slug": "mercedes-benz",
        "name": "Mercedes-Benz",
        "tagline": "L'élégance rencontre la puissance",
        "description": "Accessoires inspirés AMG, améliorations intérieures et transformations haut de gamme pour Mercedes-Benz.",
        "image": "https://images.unsplash.com/photo-1618843479313-40f8afb4b4d8?auto=format&fit=crop&w=1600&q=80",
        "logo_text": "Mercedes-Benz",
        "order": 2,
    },
    {
        "slug": "audi",
        "name": "Audi",
        "tagline": "L'esprit RS sans compromis",
        "description": "Calandres sport, accessoires intérieurs et améliorations esthétiques pour sublimer chaque Audi.",
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
        "name": "Extérieur",
        "tagline": "Style Sans Compromis.",
        "description": "Calandres, spoilers et kits carrosserie pour transformer votre véhicule.",
        "image": "https://images.unsplash.com/photo-1614200187524-dc4b892acf16?auto=format&fit=crop&w=1600&q=80",
        "subcategories": ["Calandres", "Spoilers", "Sorties d'échappement", "Silencieux", "Diffuseurs", "Extérieur"],
        "order": 1,
    },
    {
        "slug": "interior",
        "name": "Intérieur",
        "tagline": "Cockpit Modernisé.",
        "description": "Écrans CarPlay, tableaux de bord digitaux et accessoires premium.",
        "image": "https://images.unsplash.com/photo-1583121274602-3e2820c69888?auto=format&fit=crop&w=1600&q=80",
        "subcategories": ["Volants", "Tableaux de bord", "Projecteurs de portières", "Accessoires intérieurs"],
        "order": 2,
    },
    {
        "slug": "technology",
        "name": "Technologie",
        "tagline": "Visibilité Réinventée.",
        "description": "Écrans CarPlay, dashcams, caméras de recul et accessoires connectés.",
        "image": "https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?auto=format&fit=crop&w=1600&q=80",
        "subcategories": ["Écrans CarPlay", "Dashcams", "Caméras de recul", "Gonfleurs de pneus", "Accessoires connectés"],
        "order": 3,
    },
]

VEHICLE_MODELS = [
    # BMW
    {"brand_slug": "bmw", "name": "Série 3", "generations": ["F30 / F35"], "image": "https://images.unsplash.com/photo-1617531653332-bd46c16f4d68?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "bmw", "name": "Série 4", "generations": ["F32 / F36"], "image": "https://images.unsplash.com/photo-1741889838631-e8a1850854dc?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "bmw", "name": "Série 3", "generations": ["G20"], "image": "https://images.unsplash.com/photo-1750670951414-c71778b857f6?auto=format&fit=crop&w=2400&q=80"},
    # Audi
    {"brand_slug": "audi", "name": "A3", "generations": ["8V"], "image": "https://images.unsplash.com/photo-1546088626-8f9b425f61ca?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "audi", "name": "A4", "generations": ["B9"], "image": "https://images.unsplash.com/photo-1539119838978-ce22e2fd0212?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "audi", "name": "A5", "generations": [], "image": "https://images.unsplash.com/photo-1494976388531-d1058494cdd8?auto=format&fit=crop&w=2400&q=80"},
    # Mercedes-Benz
    {"brand_slug": "mercedes-benz", "name": "Classe C", "generations": ["W205"], "image": "https://images.unsplash.com/photo-1765446607390-aa61ae857a50?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "mercedes-benz", "name": "Classe A", "generations": ["W177"], "image": "https://images.unsplash.com/photo-1626668893632-6f3a4466d22f?auto=format&fit=crop&w=2400&q=80"},
    # Volkswagen
    {"brand_slug": "volkswagen", "name": "Golf 7", "generations": ["GTI / R"], "image": "https://images.unsplash.com/photo-1748466245947-bb2e22e758ed?auto=format&fit=crop&w=2400&q=80"},
    # Porsche
    {"brand_slug": "porsche", "name": "911", "generations": ["991 / 992"], "image": "https://images.unsplash.com/photo-1614244788272-f6dcdfd8df9f?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "porsche", "name": "Cayman", "generations": [], "image": "https://images.unsplash.com/photo-1699325413806-48286e94351c?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "porsche", "name": "Boxster", "generations": [], "image": "https://images.unsplash.com/photo-1750097296925-cbe35257d0f1?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "porsche", "name": "Cayenne", "generations": ["9YA"], "image": "https://images.unsplash.com/photo-1762120516501-bc1229824b4d?auto=format&fit=crop&w=2400&q=80"},
    # Toyota
    {"brand_slug": "toyota", "name": "GR Supra", "generations": ["A90"], "image": "https://images.unsplash.com/photo-1752560904748-390f9fa28bdb?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "toyota", "name": "GR Yaris", "generations": ["XP210"], "image": "https://images.unsplash.com/photo-1748939238043-403668614be9?auto=format&fit=crop&w=2400&q=80"},
    {"brand_slug": "toyota", "name": "GR86 / GT86", "generations": [], "image": "https://images.unsplash.com/photo-1541878117466-0e3000a65864?auto=format&fit=crop&w=2400&q=80"},
]

IMG = {
    "grille": [
        "https://images.unsplash.com/photo-1779263590536-5293d7e73c23?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1493238792000-8113da705763?auto=format&fit=crop&w=1200&q=80",
    ],
    "spoiler": [
        "https://images.unsplash.com/photo-1565043666747-69f6646db940?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?auto=format&fit=crop&w=1200&q=80",
    ],
    "exhaust": [
        "https://images.unsplash.com/photo-1639928197975-719885038475?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1614200187524-dc4b892acf16?auto=format&fit=crop&w=1200&q=80",
    ],
    "diffuser": [
        "https://images.unsplash.com/photo-1639928846190-9d342619118a?auto=format&fit=crop&w=1200&q=80",
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
        "https://images.unsplash.com/photo-1639928846767-2b900c357a30?auto=format&fit=crop&w=1200&q=80",
    ],
    "dashcam": [
        "https://images.unsplash.com/photo-1517524008697-84bbe3c3fd98?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1517524206127-48bbd363f3d7?auto=format&fit=crop&w=1200&q=80",
    ],
    "inflator": [
        "https://images.unsplash.com/photo-1639928848401-41650dc7238e?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1617814076367-b759c7d7e738?auto=format&fit=crop&w=1200&q=80",
    ],
    "reverse": [
        "https://images.unsplash.com/photo-1755039466898-026bb58cbefe?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1701012187548-03b07619ba48?auto=format&fit=crop&w=1200&q=80",
    ],
    "mirror": [
        "https://images.unsplash.com/photo-1614200187524-dc4b892acf16?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1542362567-b07e54358753?auto=format&fit=crop&w=1200&q=80",
    ],
    "projector": [
        "https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1583121274602-3e2820c69888?auto=format&fit=crop&w=1200&q=80",
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
        "compare_at_price": None,
        "currency": "EUR",
        "images": list(spec.images),
        "category_slug": spec.category_slug,
        "subcategory": spec.subcategory,
        "compatible_brands": list(spec.compatible_brands),
        "compatibilities": [],
        "badges": [],
        "sku": "TY-" + spec.slug.upper()[:14],
        "stock": 0,
        "rating": None,
        "review_count": 0,
        "featured": False,
        "specs": {},
        "package_contents": [],
        "tools_required": [],
        "status": "draft",
        "is_verified": False,
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
    # BMW
    p("bmw-f30-double-slat-grille", "Calandre Double Lame F30", "BMW Série 3 F30 / F35 2013-2019",
      "Inspirée des modèles BMW M Performance, cette calandre double lame apporte une présence plus affirmée à votre Série 3 F30. Sa finition noir brillant et son ajustement OEM garantissent une intégration propre tout en renforçant le caractère sportif du véhicule.",
      99.0, "Calandres", "performance", IMG["grille"], ["bmw"], ["Best Seller", "M Performance"], featured=True, compare_at=129.0),

    p("bmw-f30-m-performance-spoiler", "Spoiler Coffre F30 M Performance", "BMW Série 3 F30 2012-2019",
      "Conçu pour prolonger les lignes de la BMW F30, ce spoiler arrière style M Performance améliore l'esthétique du véhicule avec une finition haut de gamme et un design inspiré des versions les plus sportives de la gamme.",
      129.0, "Spoilers", "performance", IMG["spoiler"], ["bmw"], ["M Performance", "Top Vente"], featured=True, compare_at=159.0),

    p("bmw-f30-f32-mirror-caps", "Coques Rétroviseurs F30/F32", "BMW F30 / F32 / F36",
      "Remplacez les coques d'origine par cette version au design sportif. Leur finition noir brillant apporte une touche plus dynamique et moderne tout en conservant un ajustement précis conforme aux standards OEM.",
      69.0, "Rétroviseurs", "performance", IMG["mirror"], ["bmw"], ["Nouveau"], compare_at=89.0),

    p("bmw-f30-m-sport-rear-diffuser", "Diffuseur Arrière F30 M Sport", "BMW Série 3 F30 M Sport",
      "Ce diffuseur arrière transforme instantanément l'apparence de votre BMW F30 M Sport. Son design inspiré du sport automobile accentue la largeur visuelle du véhicule et renforce son caractère agressif.",
      199.0, "Diffuseurs", "performance", IMG["diffuser"], ["bmw"], ["M Performance"], compare_at=249.0),

    p("bmw-g20-gloss-black-grille", "Calandre G20", "BMW Série 3 G20",
      "Modernisez l'avant de votre BMW G20 avec cette calandre sport noir brillant. Son design épuré et sa finition premium offrent un look plus exclusif tout en respectant les lignes d'origine du véhicule.",
      149.0, "Calandres", "performance", IMG["grille"], ["bmw"], ["Nouveau"], compare_at=189.0),

    p("bmw-g20-m-performance-spoiler", "Spoiler G20", "BMW Série 3 G20",
      "Ce spoiler arrière apporte une finition plus sportive à la BMW G20 tout en conservant une intégration élégante. Idéal pour renforcer le style performance sans dénaturer le design d'origine.",
      149.0, "Spoilers", "performance", IMG["spoiler"], ["bmw"], ["M Performance"], compare_at=189.0),

    p("bmw-g20-mirror-caps", "Coques Rétroviseurs G20", "BMW Série 3 G20",
      "Ces coques de rétroviseurs noir brillant modernisent instantanément le profil de votre BMW G20. Une modification simple, propre et efficace pour obtenir un rendu plus sportif.",
      79.0, "Rétroviseurs", "performance", IMG["mirror"], ["bmw"], ["Nouveau"], compare_at=99.0),

    p("bmw-logo-door-projectors", "Projecteurs Logo BMW", "BMW",
      "Projetez le logo BMW au sol à chaque ouverture de porte grâce à cet éclairage LED discret et élégant. Une amélioration intérieure simple qui ajoute une finition premium au quotidien.",
      39.0, "Projecteurs de portières", "interior", IMG["projector"], ["bmw"], ["Installation Facile"], compare_at=59.0),

    # AUDI
    p("audi-a3-8v-rs3-grille", "Calandre RS3 A3 8V", "Audi A3 8V 2013-2020",
      "Inspirée de l'emblématique Audi RS3, cette calandre nid d'abeille apporte une identité plus sportive et distinctive à votre A3 8V. Sa finition haut de gamme assure une intégration propre et un rendu visuel remarquable.",
      149.0, "Calandres", "performance", IMG["grille"], ["audi"], ["Best Seller", "RS Style"], featured=True, compare_at=189.0),

    p("audi-a3-8v-rear-spoiler", "Spoiler Audi A3 8V", "Audi A3 8V",
      "Ce spoiler arrière renforce le profil sportif de l'Audi A3 8V avec une finition propre et discrète. Il apporte une ligne plus dynamique tout en conservant une esthétique proche de l'origine.",
      129.0, "Spoilers", "performance", IMG["spoiler"], ["audi"], ["RS Style"], featured=True, compare_at=159.0),

    p("audi-a4-b9-rs4-grille", "Calandre RS4 A4 B9", "Audi A4 B9",
      "Inspirée du design RS4, cette calandre nid d'abeille transforme l'avant de votre Audi A4 B9 avec une présence plus agressive. Sa finition noir brillant apporte un rendu premium et sportif.",
      179.0, "Calandres", "performance", IMG["grille"], ["audi"], ["RS Style"], compare_at=219.0),

    p("audi-a5-rear-spoiler", "Spoiler Audi A5", "Audi A5",
      "Pensé pour accompagner les lignes élégantes de l'Audi A5, ce spoiler arrière ajoute une touche sportive sans excès. Une modification sobre, premium et parfaitement adaptée à un style OEM+.",
      139.0, "Spoilers", "performance", IMG["spoiler"], ["audi"], ["Premium"], compare_at=179.0),

    p("audi-gloss-black-mirror-caps", "Coques Rétroviseurs Audi", "Audi A3 / A4 / A5",
      "Ces coques de rétroviseurs noir brillant ajoutent une signature plus sportive à votre Audi. Leur design discret permet de moderniser le véhicule tout en gardant une finition élégante.",
      79.0, "Rétroviseurs", "performance", IMG["mirror"], ["audi"], ["Nouveau"], compare_at=99.0),

    p("audi-logo-door-projectors", "Projecteurs Logo Audi", "Audi",
      "Ajoutez une finition lumineuse premium à votre Audi avec ces projecteurs LED de portières. Le logo projeté au sol apporte une touche élégante et moderne à chaque ouverture.",
      39.0, "Projecteurs de portières", "interior", IMG["projector"], ["audi"], ["Installation Facile"], compare_at=59.0),

    # MERCEDES
    p("mercedes-w205-amg-grille", "Calandre AMG W205", "Mercedes Classe C W205",
      "Apportez à votre Mercedes Classe C W205 l'élégance et l'agressivité des modèles AMG grâce à cette calandre premium. Son design moderne sublime l'avant du véhicule tout en conservant une parfaite harmonie avec les éléments d'origine.",
      169.0, "Calandres", "performance", IMG["grille"], ["mercedes-benz"], ["Best Seller", "AMG"], featured=True, compare_at=209.0),

    p("mercedes-w205-panamericana-grille", "Calandre Panamericana W205", "Mercedes Classe C W205",
      "Directement inspirée des modèles AMG les plus emblématiques, cette calandre Panamericana transforme l'apparence de votre W205 avec une présence visuelle plus affirmée et une finition irréprochable.",
      189.0, "Calandres", "performance", IMG["grille"], ["mercedes-benz"], ["AMG"], compare_at=239.0),

    p("mercedes-w205-rear-spoiler", "Spoiler W205", "Mercedes Classe C W205",
      "Ce spoiler arrière apporte une finition plus dynamique à la Mercedes W205. Son design sobre et sportif accompagne les lignes du véhicule sans casser son élégance d'origine.",
      139.0, "Spoilers", "performance", IMG["spoiler"], ["mercedes-benz"], ["Premium"], compare_at=179.0),

    p("mercedes-w177-amg-side-vents", "Side Vents W177", "Mercedes Classe A W177",
      "Ces side vents style AMG ajoutent une signature visuelle plus sportive à la Mercedes Classe A W177. Une finition extérieure discrète mais efficace pour renforcer le caractère du véhicule.",
      69.0, "Extérieur", "performance", IMG["diffuser"], ["mercedes-benz"], ["AMG"], compare_at=89.0),

    p("mercedes-w205-mirror-caps", "Coques Rétroviseurs W205", "Mercedes Classe C W205",
      "Modernisez le profil de votre Mercedes W205 avec ces coques de rétroviseurs noir brillant. Leur finition premium apporte un contraste élégant et une allure plus sportive.",
      79.0, "Rétroviseurs", "performance", IMG["mirror"], ["mercedes-benz"], ["Nouveau"], compare_at=99.0),

    p("mercedes-logo-door-projectors", "Projecteurs Logo Mercedes", "Mercedes-Benz",
      "Ces projecteurs LED de portières ajoutent une touche lumineuse haut de gamme à votre Mercedes. Le logo projeté au sol renforce l'expérience premium à chaque ouverture.",
      39.0, "Projecteurs de portières", "interior", IMG["projector"], ["mercedes-benz"], ["Installation Facile"], compare_at=59.0),

    # VOLKSWAGEN
    p("vw-golf7-gti-r-spoiler", "Spoiler Golf 7 GTI/R", "Volkswagen Golf 7 GTI / R",
      "Pensé pour les passionnés Volkswagen, ce spoiler arrière style GTI/R accentue le profil sportif de la Golf 7. Sa finition premium et son intégration propre en font une modification discrète mais particulièrement efficace.",
      129.0, "Spoilers", "performance", IMG["spoiler"], ["volkswagen"], ["Best Seller"], featured=True, compare_at=159.0),

    p("vw-golf7-gti-grille", "Calandre Golf 7 GTI", "Volkswagen Golf 7",
      "Cette calandre style GTI apporte une face avant plus sportive à la Golf 7. Son design noir brillant conserve l'esprit OEM tout en renforçant le look performance du véhicule.",
      129.0, "Calandres", "performance", IMG["grille"], ["volkswagen"], ["GTI"], compare_at=159.0),

    p("vw-golf7-mirror-caps", "Coques Rétroviseurs Golf 7", "Volkswagen Golf 7",
      "Ces coques de rétroviseurs noir brillant apportent une finition plus moderne et sportive à la Golf 7. Une modification simple pour améliorer l'apparence du véhicule sans transformation lourde.",
      69.0, "Rétroviseurs", "performance", IMG["mirror"], ["volkswagen"], ["Nouveau"], compare_at=89.0),

    p("vw-golf7-r-rear-diffuser", "Diffuseur Golf 7 R", "Volkswagen Golf 7 R",
      "Inspiré de la Golf R, ce diffuseur arrière renforce le caractère dynamique du véhicule grâce à un design plus agressif et une finition de qualité supérieure.",
      199.0, "Diffuseurs", "performance", IMG["diffuser"], ["volkswagen"], ["Performance"], compare_at=249.0),

    p("vw-logo-door-projectors", "Projecteurs Logo Volkswagen", "Volkswagen",
      "Projetez le logo VW au sol à chaque ouverture de porte. Une finition premium subtile qui modernise l'expérience intérieure de votre Volkswagen.",
      39.0, "Projecteurs de portières", "interior", IMG["projector"], ["volkswagen"], ["Installation Facile"], compare_at=59.0),

    # PORSCHE
    p("porsche-911-rear-spoiler", "Spoiler Arrière 911 GT Style", "Porsche 911 992 / 991",
      "Inspiré des modèles GT3, ce spoiler arrière en ABS apporte une présence visuelle plus affirmée à votre Porsche 911. Sa finition noir mat crée un rendu sportif.",
      389.0, "Spoilers", "performance", IMG["spoiler"], ["porsche"], [], featured=True, compare_at=449.0),

    p("porsche-cayenne-front-grille", "Calandre Sport Cayenne", "Porsche Cayenne 9YA",
      "Cette calandre sport transforme l'avant de votre Cayenne avec un design plus agressif et moderne. Finition noir brillant, montage direct sans modification.",
      249.0, "Calandres", "performance", IMG["grille"], ["porsche"], ["Nouveau"], compare_at=299.0),

    p("porsche-mirror-caps-black", "Coques Rétroviseurs Noires Porsche", "Porsche 911 / Cayman / Boxster",
      "Coques de rétroviseurs en ABS noir brillant pour Porsche. Une finition sportive qui modernise le profil du véhicule.",
      189.0, "Rétroviseurs", "performance", IMG["mirror"], ["porsche"], [], compare_at=229.0),

    p("porsche-logo-door-projectors", "Projecteurs Logo Porsche", "Porsche",
      "Projetez le logo Porsche au sol à chaque ouverture de porte. Un détail premium qui renforce l'expérience exclusive de votre véhicule.",
      39.0, "Projecteurs de portières", "interior", IMG["projector"], ["porsche"], ["Installation Facile"], compare_at=59.0),

    p("porsche-911-diffuser-black", "Diffuseur Arrière Noir 911", "Porsche 911 992",
      "Diffuseur arrière en ABS noir brillant pour Porsche 911 992. Design inspiré des versions GT, à confirmer selon le pare-chocs d'origine.",
      349.0, "Diffuseurs", "performance", IMG["diffuser"], ["porsche"], [], compare_at=399.0),

    # TOYOTA
    p("toyota-gr-supra-rear-spoiler", "Spoiler Arrière GR Supra", "Toyota GR Supra A90",
      "Ce spoiler arrière style GT en ABS noir renforce l'allure de la GR Supra A90. La compatibilité exacte doit être confirmée avant publication.",
      279.0, "Spoilers", "performance", IMG["spoiler"], ["toyota"], [], featured=True, compare_at=329.0),

    p("toyota-gr-yaris-grille", "Calandre Sport GR Yaris", "Toyota GR Yaris XP210",
      "Cette calandre sport remplace la calandre d'origine de la GR Yaris pour une apparence plus affirmée. Finition noir mat, ajustement OEM parfait.",
      149.0, "Calandres", "performance", IMG["grille"], ["toyota"], ["Nouveau"], compare_at=179.0),

    p("toyota-gr86-mirror-caps", "Coques Rétroviseurs GR86 / GT86", "Toyota GR86 / GT86",
      "Ces coques de rétroviseurs noir brillant modernisent le profil de votre GR86 ou GT86 avec une finition soignée et sportive.",
      69.0, "Rétroviseurs", "performance", IMG["mirror"], ["toyota"], ["Nouveau"], compare_at=89.0),

    p("toyota-logo-door-projectors", "Projecteurs Logo Toyota", "Toyota",
      "Projetez le logo Toyota au sol à chaque ouverture de porte. Une finition lumineuse premium simple à installer et compatible avec tous les modèles Toyota.",
      39.0, "Projecteurs de portières", "interior", IMG["projector"], ["toyota"], ["Installation Facile"], compare_at=59.0),

    p("toyota-supra-diffuser", "Diffuseur Arrière GR Supra", "Toyota GR Supra A90",
      "Diffuseur arrière sport pour GR Supra A90 en ABS haute résistance. Renforce l'esthétique arrière du véhicule avec un design inspiré du sport automobile.",
      199.0, "Diffuseurs", "performance", IMG["diffuser"], ["toyota"], ["Performance"], compare_at=239.0),

    # TECHNOLOGIE — Universel
    p("carplay-screen-12", "Écran CarPlay & Android Auto 12\" Sans Fil", "Montage Premium Universel",
      "Écran tactile QLED 12\" avec CarPlay sans fil, Android Auto, support caméra de recul AHD et mode écran partagé.",
      490.0, "Écrans CarPlay", "technology", IMG["carplay"], ["bmw", "mercedes-benz", "audi", "volkswagen", "toyota", "porsche"], ["Best Seller"], featured=True),

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
]
