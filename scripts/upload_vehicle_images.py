"""Upload the audited configurator source/final pairs to Cloudinary.

This script never embeds credentials. Configure CLOUDINARY_URL or the standard
CLOUDINARY_* variables in the execution environment, then run it from backend/.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "vehicle_image_manifest.json"


def configure_cloudinary() -> None:
    import cloudinary

    if os.getenv("CLOUDINARY_URL"):
        cloudinary.config(secure=True)
        return
    required = {
        "cloud_name": os.getenv("CLOUDINARY_CLOUD_NAME"),
        "api_key": os.getenv("CLOUDINARY_API_KEY"),
        "api_secret": os.getenv("CLOUDINARY_API_SECRET"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit("Cloudinary credentials are missing: " + ", ".join(missing))
    cloudinary.config(**required, secure=True)


def upload(path: Path, public_id: str, *, context: dict[str, str]) -> dict[str, object]:
    import cloudinary.uploader

    result = cloudinary.uploader.upload(
        str(path),
        public_id=public_id,
        resource_type="image",
        overwrite=True,
        invalidate=True,
        unique_filename=False,
        use_filename=False,
        context=context,
    )
    return {
        "public_id": result["public_id"],
        "secure_url": result["secure_url"],
        "width": result["width"],
        "height": result["height"],
        "bytes": result["bytes"],
        "format": result["format"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not args.dry_run:
        configure_cloudinary()

    results: list[dict[str, object]] = []
    for item in manifest:
        base_id = item["cloudinary_public_id"].rsplit("/", 1)[0]
        source_path = ROOT / "assets" / "vehicle-sources" / item["source_file"]
        final_path = ROOT / "assets" / "vehicle-finals" / item["final_file"]
        if not source_path.is_file() or not final_path.is_file():
            raise SystemExit(f"Missing source/final pair for {item['generation_name']}")

        record: dict[str, object] = {
            "brand_slug": item["brand_slug"],
            "model_slug": item["model_slug"],
            "generation_slug": item["generation_slug"],
            "source": {"path": str(source_path), "public_id": f"{base_id}/source-original"},
            "final": {"path": str(final_path), "public_id": item["cloudinary_public_id"]},
        }
        if not args.dry_run:
            context = {
                "source_url": item["source_url"],
                "source_name": item["source_name"],
                "rights_status": item["rights_status"],
                "generation": item["generation_name"],
            }
            record["source"] = upload(source_path, f"{base_id}/source-original", context=context)
            record["final"] = upload(final_path, item["cloudinary_public_id"], context=context)
        results.append(record)

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
