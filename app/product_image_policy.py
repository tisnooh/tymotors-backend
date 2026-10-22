"""Pure output/validation guard. Keeps source evidence in storage, never serves it as a photo."""
from urllib.parse import unquote, urlsplit
import hashlib
import json
from pathlib import Path

DENIED_IMAGE_HASHES = frozenset(json.loads((Path(__file__).parent / 'data/denied_image_sha256.json').read_text(encoding='utf-8'))['sha256'])


def image_bytes_usage_denied(content: bytes) -> bool:
    return hashlib.sha256(content).hexdigest() in DENIED_IMAGE_HASHES

SCP_PUBLIC_IDS = frozenset({
    'tymotors/products/hvtqoa2mfv40mn2gy1ww',
    'tymotors/products/ckvfckn89wcdd9fzaegj',
    'tymotors/products/o5ylil1cryn4uertnc89',
})
SCP_HOSTS = frozenset({'scpautomotive.co.uk', 'www.scpautomotive.co.uk'})
SCP_FILE_MARKERS = ('BMW-LED-Door-Projector-_Pair_-BMW-Logo-SCP-Automotive-90141840',)


def image_usage_denied(source: str | None) -> bool:
    if not source:
        return False
    try:
        url = urlsplit(source)
        path = unquote(url.path)
        if url.hostname in SCP_HOSTS and path.startswith('/cdn/'):
            return True
        if any(marker in path for marker in SCP_FILE_MARKERS):
            return True
        if url.hostname != 'res.cloudinary.com' or not path.startswith('/dwsyixjux/'):
            return False
        without_extension = path.rsplit('.', 1)[0]
        return any(path.endswith('/' + key) or without_extension.endswith('/' + key)
                   for key in SCP_PUBLIC_IDS)
    except (ValueError, TypeError):
        return False


def permitted_image(source: str | None) -> str | None:
    return None if image_usage_denied(source) else source
