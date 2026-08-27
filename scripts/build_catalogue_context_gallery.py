"""Create a realistic second gallery image for every catalogue product.

The source photograph is never regenerated. It is only resized and mounted in
the shared TYMotors studio frame, preserving the real product, installation
context, supplier markings and included accessories.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = ROOT / "assets" / "catalogue-style" / "studio-background-v2.png"
OUTPUT_DIR = ROOT / "assets" / "catalogue-gallery"
UPLOAD_MANIFEST = ROOT / "data" / "product_ai_catalogue_uploads.json"
SOURCE_DIRS = (ROOT / "assets" / "ai-sources", ROOT / "assets" / "internet-products")


def source_for(slug: str) -> Path:
    matches = [path for directory in SOURCE_DIRS for path in directory.glob(f"{slug}.*")]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one source for {slug}, found {len(matches)}")
    return matches[0]


def framed_source(source: Image.Image) -> Image.Image:
    background = Image.open(BACKGROUND).convert("RGB").resize((1200, 1200), Image.Resampling.LANCZOS)
    photo = source.convert("RGB")
    photo.thumbnail((1060, 900), Image.Resampling.LANCZOS)

    frame = Image.new("RGB", (photo.width + 18, photo.height + 18), "#151920")
    frame.paste(photo, (9, 9))
    shadow = Image.new("RGBA", background.size, (0, 0, 0, 0))
    shadow_box = Image.new("RGBA", frame.size, (0, 0, 0, 185)).filter(ImageFilter.GaussianBlur(18))
    x = (1200 - frame.width) // 2
    y = (1200 - frame.height) // 2 - 20
    shadow.alpha_composite(shadow_box, (x + 15, y + 26))

    result = Image.alpha_composite(background.convert("RGBA"), shadow)
    result.alpha_composite(frame.convert("RGBA"), (x, y))
    draw = ImageDraw.Draw(result)
    draw.rectangle((x, y, x + frame.width - 1, y + frame.height - 1), outline=(70, 76, 88, 190), width=2)
    return result.convert("RGB")


def main() -> None:
    manifest = json.loads(UPLOAD_MANIFEST.read_text(encoding="utf-8-sig"))
    slugs = sorted(image["product_slug"] for image in manifest["images"])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for slug in slugs:
        output_path = OUTPUT_DIR / f"{slug}-context.png"
        if output_path.exists():
            print(f"Skipping {output_path.name} (already built)")
            continue
        source_path = source_for(slug)
        output = framed_source(Image.open(source_path))
        output.save(output_path, format="PNG", optimize=True)
        print(f"Built {output_path.name} from {source_path.name}")


if __name__ == "__main__":
    main()
