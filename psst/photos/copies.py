"""Our own copies of a photo: a full-size and a thumbnail JPEG, with every camera and location record removed,
each named by the hash of its bytes so a file never changes once published."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

MAX_SOURCE_BYTES = 60_000_000


@dataclass(frozen=True)
class Rendition:
    file: str
    width: int
    height: int
    data: bytes


def render(source: bytes, longest: int) -> Rendition:
    with Image.open(io.BytesIO(source)) as opened:
        picture = ImageOps.exif_transpose(opened).convert("RGB")
        picture.thumbnail((longest, longest), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        # No exif, no icc, no comments: a new image with only pixels.
        clean = Image.new("RGB", picture.size)
        clean.paste(picture)
        clean.save(out, "JPEG", quality=84, optimize=True, progressive=True)
    data = out.getvalue()
    return Rendition(hashlib.sha256(data).hexdigest()[:24] + ".jpg", clean.width, clean.height, data)


def store(rendition: Rendition, directory: Path) -> None:
    target = directory / rendition.file
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(rendition.data)
        temporary.chmod(0o644)
        temporary.rename(target)
