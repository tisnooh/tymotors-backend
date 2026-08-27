"""Build catalogue replacements without redrawing product pixels.

The source products are cropped and composited on the TYMotors studio
background. White studio backgrounds are removed deterministically. Products
only available in an installed photo retain that real photographic context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter


ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT_DIR: Final = ROOT / "assets" / "ai-catalogue"

PRODUCTS: Final = {
    "bmw-f30-double-slat-grille": {
        "source": "assets/ai-sources/bmw-f30-double-slat-grille.jpg",
        "crop": (0, 430, 750, 750),
        "mode": "isolate",
    },
    "bmw-g20-m-performance-spoiler": {
        "source": "assets/ai-sources/bmw-g20-m-performance-spoiler.jpg",
        "crop": (0, 430, 750, 750),
        "mode": "isolate",
    },
    "carplay-screen-12": {
        "source": "assets/internet-products/carplay-screen-12.webp",
        "crop": (35, 60, 965, 910),
        "mode": "isolate",
    },
    "dashcam-4k-pro": {
        "source": "assets/internet-products/dashcam-4k-pro.jpg",
        "crop": (0, 0, 550, 550),
        "mode": "context",
    },
    "mercedes-w205-amg-grille": {
        "source": "assets/ai-sources/mercedes-w205-amg-grille.jpg",
        "crop": (0, 430, 750, 750),
        "mode": "isolate",
    },
    "porsche-911-rear-spoiler": {
        "source": "assets/internet-products/porsche-911-rear-spoiler.jpg",
        "crop": (85, 0, 915, 750),
        "mode": "context",
    },
    "reverse-cam-hd": {
        "source": "assets/internet-products/reverse-cam-hd.jpg",
        "crop": (35, 70, 720, 720),
        "mode": "isolate",
    },
    "vw-golf7-r-rear-diffuser": {
        "source": "assets/internet-products/vw-golf7-r-rear-diffuser.webp",
        "crop": (120, 0, 880, 667),
        "mode": "context",
    },
}


def studio_background(size: int = 1200) -> Image.Image:
    image = Image.new("RGB", (size, size), "#080a0e")
    pixels = image.load()
    center = size * 0.52
    for y in range(size):
        for x in range(size):
            radial = max(0.0, 1.0 - (((x - center) ** 2 + (y - center) ** 2) ** 0.5) / (size * 0.78))
            red_glow = max(0.0, 1.0 - (((x - center) ** 2 + (y - size * 0.68) ** 2) ** 0.5) / (size * 0.50))
            pixels[x, y] = (
                int(8 + 13 * radial + 16 * red_glow),
                int(10 + 13 * radial),
                int(14 + 15 * radial),
            )
    return image


def white_background_alpha(image: Image.Image) -> Image.Image:
    """Remove only near-white neutral pixels, preserving dark product detail."""
    rgb = image.convert("RGB")
    alpha = Image.new("L", rgb.size)
    src = rgb.load()
    dst = alpha.load()
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = src[x, y]
            minimum = min(r, g, b)
            maximum = max(r, g, b)
            whiteness = minimum - (maximum - minimum) * 1.8
            dst[x, y] = max(0, min(255, int((248 - whiteness) * 11)))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.65))
    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


def contain(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    result = image.copy()
    result.thumbnail(box, Image.Resampling.LANCZOS)
    return result


def build_isolated(source: Image.Image) -> Image.Image:
    product = white_background_alpha(source)
    product = contain(product, (1020, 790))
    canvas = studio_background().convert("RGBA")
    x = (canvas.width - product.width) // 2
    y = (canvas.height - product.height) // 2 - 20

    shadow_alpha = product.getchannel("A").filter(ImageFilter.GaussianBlur(28))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_piece = Image.new("RGBA", product.size, (0, 0, 0, 150))
    shadow_piece.putalpha(shadow_alpha.point(lambda value: int(value * 0.48)))
    shadow.alpha_composite(shadow_piece, (x + 15, y + 42))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.alpha_composite(product, (x, y))

    draw = ImageDraw.Draw(canvas)
    draw.line((170, 1010, 1030, 1010), fill=(238, 0, 0, 110), width=2)
    return canvas.convert("RGB")


def build_context(source: Image.Image) -> Image.Image:
    """Preserve a truthful installed-product photo when no standalone exists."""
    photo = ImageEnhance.Contrast(source.convert("RGB")).enhance(1.06)
    photo = ImageEnhance.Color(photo).enhance(0.92)
    scale = max(1200 / photo.width, 1200 / photo.height)
    photo = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.Resampling.LANCZOS)
    left = (photo.width - 1200) // 2
    top = (photo.height - 1200) // 2
    photo = photo.crop((left, top, left + 1200, top + 1200))

    overlay = Image.new("RGBA", photo.size, (0, 0, 0, 0))
    pixels = overlay.load()
    for y in range(1200):
        for x in range(1200):
            edge = max(abs(x - 600), abs(y - 600)) / 600
            pixels[x, y] = (3, 4, 7, int(25 + 100 * edge**1.8))
    composed = Image.alpha_composite(photo.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(composed)
    draw.line((170, 1010, 1030, 1010), fill=(238, 0, 0, 120), width=2)
    return composed.convert("RGB")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for slug, config in PRODUCTS.items():
        source = Image.open(ROOT / config["source"]).convert("RGB")
        source = source.crop(config["crop"])
        output = build_isolated(source) if config["mode"] == "isolate" else build_context(source)
        output.save(OUTPUT_DIR / f"{slug}.png", format="PNG", optimize=True)
        print(f"Built {slug}.png from exact source pixels ({config['mode']}).")


if __name__ == "__main__":
    main()
