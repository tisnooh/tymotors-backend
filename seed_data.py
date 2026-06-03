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
        "image": "https://images.unsplash.com/photo-1617531653332-bd46c24f2068?q=80&w?auto=format&fit=crop&w=1600&q=80",
        "logo_text": "BMW",
        "order": 1,
    },
    {
        "slug": "mercedes-benz",
        "name": "Mercedes-Benz",
        "tagline": "L'élégance rencontre la puissance",
        "description": "Accessoires inspirés AMG, éléments en carbone, améliorations intérieures et transformations haut de gamme pour Mercedes-Benz.",
        "image": "https://images.unsplash.com/photo-1618843479313-40f8afb4b4d8?auto=format&fit=crop&w=1600&q=80"",
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
        "tagline": "Sculpted aerodynamics, motorsport DNA.",
        "description": "Front grilles, spoilers, diffusers, silencieux and exhaust tips engineered with carbon fiber and forged alloys.",
        "image": "https://images.unsplash.com/photo-1614200187524-dc4b892acf16?auto=format&fit=crop&w=1600&q=80",
        "subcategories": ["Grilles", "Spoilers", "Exhaust Tips", "Silencieux", "Diffusers", "Exterior"],
        "order": 1,
    },
    {
        "slug": "interior",
        "name": "Interior",
        "tagline": "Cinematic cockpit. Modernized.",
        "description": "Steering wheels, digital dashboards, ambient lighting, door projectors and carbon fiber finishings.",
        "image": "https://images.unsplash.com/photo-1583121274602-3e2820c69888?auto=format&fit=crop&w=1600&q=80",
        "subcategories": ["Steering Wheels", "Digital Dashboards", "Ambient Lighting", "Door Projectors", "Carbon Interior"],
        "order": 2,
    },
    {
        "slug": "technology",
        "name": "Technology",
        "tagline": "Smart hardware. Intelligent drive.",
        "description": "Apple CarPlay screens, dashcams, reverse cameras, tire inflators and connected automotive accessories.",
        "image": "https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?auto=format&fit=crop&w=1600&q=80",
        "subcategories": ["CarPlay Screens", "Dashcams", "Reverse Cameras", "Tire Inflators", "Smart Accessories"],
        "order": 3,
    },
]

VEHICLE_MODELS = [
    # BMW
    {"brand_slug": "bmw", "name": "M3", "generations": ["G80 (2020+)", "F80 (2014-2018)", "E92 (2008-2013)"]},
    {"brand_slug": "bmw", "name": "M4", "generations": ["G82 (2021+)", "F82 (2014-2020)"]},
    {"brand_slug": "bmw", "name": "Serie 3", "generations": ["G20 (2019+)", "F30 (2012-2018)"]},
    {"brand_slug": "bmw", "name": "Serie 5", "generations": ["G30 (2017+)", "F10 (2010-2016)"]},
    {"brand_slug": "bmw", "name": "X5", "generations": ["G05 (2019+)", "F10 (2013-2018)"]},
    # Mercedes
    {"brand_slug": "mercedes-benz", "name": "C-Class", "generations": ["W206 (2021+)", "W205 (2014-2020)"]},
    {"brand_slug": "mercedes-benz", "name": "E-Class", "generations": ["W213 (2016+)", "W212 (2009-2016)"]},
    {"brand_slug": "mercedes-benz", "name": "S-Class", "generations": ["W223 (2020+)", "W222 (2013-2020)"]},
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

# Image pool for products (cinematic, dark automotive)
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


from dataclasses import dataclass, field
from typing import List, Optional


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
    """Construct a MongoDB product document from a ProductSpec."""
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
        "specs": spec.specs or {"Material": "Carbon Fiber", "Finish": "Gloss", "Warranty": "2 years"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def p(slug, name, subtitle, description, price, subcategory, category_slug,
      images, compatible_brands, badges=None, featured=False, compare_at=None, specs=None):
    """Backwards-compatible thin wrapper kept for readability of the PRODUCTS list."""
    return build_product(ProductSpec(
        slug=slug,
        name=name,
        subtitle=subtitle,
        description=description,
        price=price,
        subcategory=subcategory,
        category_slug=category_slug,
        images=images,
        compatible_brands=compatible_brands,
        badges=badges or [],
        featured=featured,
        compare_at_price=compare_at,
        specs=specs,
    ))


PRODUCTS = [
    # PERFORMANCE
    p("m-performance-grille-g80", "M Performance Carbon Grille", "BMW G80 / G82 \u2013 OEM Fit",
      "Hand-laid pre-preg carbon fiber kidney grille engineered for the BMW M3/M4 G80/G82. UV-protected gloss clear coat.",
      890.0, "Grilles", "performance", IMG["grille"], ["bmw"], ["New", "Carbon"], featured=True, compare_at=990.0),

    p("amg-night-package-grille", "AMG Night Package Diamond Grille", "Mercedes-Benz C/E/S Class",
      "Diamond-pattern blacked-out grille with chrome accents. Direct OEM replacement for AMG Night Package retrofits.",
      720.0, "Grilles", "performance", IMG["grille"], ["mercedes-benz"], ["Best Seller"], featured=True),

    p("audi-rs-honeycomb-grille", "RS Honeycomb Aero Grille", "Audi A4 / A6 / RS-Line",
      "3D-printed honeycomb mesh with anodized matte black finish. Improves airflow by 14% to front intercoolers.",
      640.0, "Grilles", "performance", IMG["grille"], ["audi"], ["Aero+"]),

    p("porsche-gt3-front-splitter", "GT3-Inspired Front Splitter", "Porsche 911 992 / 991",
      "Track-bred carbon front splitter machined from a single carbon block, generating measurable front-axle downforce.",
      1490.0, "Exterior", "performance", IMG["diffuser"], ["porsche"], ["Pro Series"], featured=True),

    p("vw-r-rear-spoiler", "R-Line Rear Ducktail Spoiler", "VW Golf MK7 / MK8",
      "OEM-grade ABS plastic spoiler with gloss black finish. Tested to 250 km/h for high-speed stability.",
      280.0, "Spoilers", "performance", IMG["spoiler"], ["volkswagen"], ["Best Seller"]),

    p("toyota-gr-aero-spoiler", "GR Performance Aero Wing", "Toyota GR Supra / GR Yaris",
      "Adjustable carbon fiber rear wing with motorsport endplates. Up to 22% increase in rear downforce.",
      820.0, "Spoilers", "performance", IMG["spoiler"], ["toyota"], ["Carbon"]),

    p("m4-quad-exhaust-tips", "M Quad Carbon Exhaust Tips", "BMW M3 / M4 G80 / G82",
      "Aerospace-grade titanium core with hand-finished carbon sleeves. Bolt-on, no welding required.",
      450.0, "Exhaust Tips", "performance", IMG["exhaust"], ["bmw"], ["Titanium"], featured=True),

    p("amg-quad-exhaust-tips", "AMG Quad Sport Exhaust Tips", "Mercedes-AMG C63 / E63",
      "Polished stainless quad outlets with laser-etched AMG signature. CNC machined for perfect symmetry.",
      380.0, "Exhaust Tips", "performance", IMG["exhaust"], ["mercedes-benz"], []),

    p("porsche-titanium-silencieux", "Track Titanium Silencieux", "Porsche 911 / Cayman",
      "Full titanium muffler engineered to deliver +18 hp and a deep race-bred soundtrack. ECE approved.",
      2890.0, "Silencieux", "performance", IMG["exhaust"], ["porsche"], ["Pro Series", "Titanium"]),

    p("rs6-carbon-diffuser", "RS6 Carbon Rear Diffuser", "Audi RS6 C8",
      "OEM-fit carbon diffuser sculpted for the C8 platform. Aero-tested for stability at autobahn speeds.",
      1190.0, "Diffusers", "performance", IMG["diffuser"], ["audi"], ["Carbon"]),

    p("vw-golf-front-lip-splitter", "R-Line Front Lip Splitter", "VW Golf MK7 / MK8",
      "Sleek front splitter with reinforced ABS construction. Subtle aggression for daily refinement.",
      210.0, "Exterior", "performance", IMG["diffuser"], ["volkswagen"], []),

    p("supra-front-canards", "GR Aero Front Canards", "Toyota GR Supra A90",
      "Hand-laid carbon canards designed to channel air to front intakes. Bolt-on installation.",
      320.0, "Exterior", "performance", IMG["diffuser"], ["toyota"], ["Carbon"]),

    # INTERIOR
    p("m-performance-steering-wheel", "M Performance Alcantara Steering Wheel", "BMW M Performance Series",
      "Race-grade alcantara wheel with carbon trim, integrated shift lights and tri-color stitching. Plug-and-play.",
      1390.0, "Steering Wheels", "interior", IMG["steering"], ["bmw"], ["Best Seller", "Alcantara"], featured=True),

    p("amg-performance-steering-wheel", "AMG Performance Alcantara Wheel", "Mercedes-AMG Lineup",
      "OEM-grade alcantara AMG performance wheel with red stitching and carbon trim. Direct retrofit.",
      1290.0, "Steering Wheels", "interior", IMG["steering"], ["mercedes-benz"], ["Alcantara"]),

    p("rs-flat-bottom-wheel", "RS Flat Bottom Steering Wheel", "Audi RS Series",
      "RS-spec flat bottom wheel with carbon insert, contrast stitching and 12 o\u2019clock indicator. Plug-and-play.",
      1150.0, "Steering Wheels", "interior", IMG["steering"], ["audi"], []),

    p("gt3-rs-suede-wheel", "GT3-RS Suede Performance Wheel", "Porsche 911 / Cayman / Panamera",
      "Hand-stitched suede wheel with carbon trim and motorsport-grade yellow 12 o\u2019clock band.",
      1690.0, "Steering Wheels", "interior", IMG["steering"], ["porsche"], ["Pro Series"], featured=True),

    p("digital-cockpit-12-3", "Digital Cockpit 12.3\" Display", "Universal Premium Fit",
      "12.3\" 1920\u00d7720 anti-glare digital cluster running custom AMOLED firmware. Plug-and-play with VAG models.",
      980.0, "Digital Dashboards", "interior", IMG["dashboard"], ["audi", "volkswagen", "porsche"], ["New"]),

    p("bmw-id8-dashboard", "BMW iD8 Curved Display Retrofit", "BMW Serie 3 / Serie 5 / X5",
      "Curved iD8 retrofit kit with iDrive 8.5 firmware, navigation and gesture controls. Fully reversible.",
      1890.0, "Digital Dashboards", "interior", IMG["dashboard"], ["bmw"], ["Pro Series"]),

    p("ambient-led-pro-64", "Ambient LED Pro 64-Color System", "Universal Premium Fit",
      "64-color ambient LED kit with app control, music sync and door pulse animation. Class-A wiring harness.",
      290.0, "Ambient Lighting", "interior", IMG["ambient"], ["bmw", "mercedes-benz", "audi", "volkswagen"], ["Best Seller"], featured=True),

    p("welcome-door-projector", "Welcome Door Logo Projector", "Universal HD Fit",
      "HD 1080p LED welcome projector with custom brand logos. CNC aluminum casing.",
      89.0, "Door Projectors", "interior", IMG["ambient"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], ["Best Seller"]),

    p("carbon-interior-trim-kit", "Carbon Fiber Interior Trim Kit", "Universal Premium Fit",
      "Hand-laid carbon fiber interior trim kit. UV-resistant clear coat finish.",
      590.0, "Carbon Interior", "interior", IMG["carbon"], ["bmw", "audi", "mercedes-benz", "porsche"], ["Carbon"]),

    # TECHNOLOGY
    p("carplay-screen-12", "12\" Wireless CarPlay & Android Auto Screen", "Universal Premium Fit",
      "12\" QLED touchscreen with wireless CarPlay, Android Auto, AHD reverse camera support and split-screen mode.",
      490.0, "CarPlay Screens", "technology", IMG["carplay"], ["bmw", "mercedes-benz", "audi", "volkswagen", "toyota"], ["Best Seller"], featured=True),

    p("carplay-screen-10", "10\" Wireless CarPlay Touchscreen", "Universal Premium Fit",
      "10\" IPS HD wireless CarPlay screen with built-in dashcam input and reverse cam input. Plug-and-play.",
      350.0, "CarPlay Screens", "technology", IMG["carplay"], ["bmw", "mercedes-benz", "audi", "volkswagen", "toyota", "porsche"], ["New"]),

    p("dashcam-4k-pro", "DashCam 4K Pro Dual-Lens", "Universal Premium Fit",
      "4K front + 1080p rear dashcam with night vision, GPS, parking guard mode and 256GB storage support.",
      280.0, "Dashcams", "technology", IMG["dashcam"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], ["New"], featured=True),

    p("reverse-cam-hd", "AHD Reverse Camera Kit", "Universal Premium Fit",
      "AHD 1080p reverse camera with dynamic guidelines and IP68 rating. Plug-and-play for most CarPlay screens.",
      120.0, "Reverse Cameras", "technology", IMG["reverse"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], ["Best Seller"]),

    p("tire-inflator-pro", "Smart Tire Inflator Pro", "Universal Premium Fit",
      "Cordless smart tire inflator with auto-stop, digital pressure gauge and OLED display. 150 PSI max.",
      99.0, "Tire Inflators", "technology", IMG["inflator"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], ["Best Seller"]),

    p("smart-tpms-kit", "Wireless TPMS Smart Sensor Kit", "Universal Premium Fit",
      "4-sensor wireless TPMS kit with solar charging hub. Real-time pressure and temperature monitoring.",
      149.0, "Smart Accessories", "technology", IMG["inflator"], ["bmw", "mercedes-benz", "audi", "porsche", "volkswagen", "toyota"], []),
]


async def seed():
    print(f"Seeding database: {db_name}")
    # Brands
    await db.brands.delete_many({})
    for b in BRANDS:
        b = {**b, "id": str(uuid.uuid4())}
        await db.brands.insert_one(b)
    print(f"Inserted {len(BRANDS)} brands.")

    # Categories
    await db.categories.delete_many({})
    for c in CATEGORIES:
        c = {**c, "id": str(uuid.uuid4())}
        await db.categories.insert_one(c)
    print(f"Inserted {len(CATEGORIES)} categories.")

    # Vehicle models
    await db.vehicle_models.delete_many({})
    for m in VEHICLE_MODELS:
        m = {**m, "id": str(uuid.uuid4())}
        await db.vehicle_models.insert_one(m)
    print(f"Inserted {len(VEHICLE_MODELS)} vehicle models.")

    # Products
    await db.products.delete_many({})
    for p_doc in PRODUCTS:
        await db.products.insert_one(p_doc)
    print(f"Inserted {len(PRODUCTS)} products.")

    # Indexes
    await db.products.create_index("slug", unique=True)
    await db.brands.create_index("slug", unique=True)
    await db.categories.create_index("slug", unique=True)
    await db.carts.create_index("session_id", unique=True)
    await db.wishlists.create_index("session_id", unique=True)

    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
