from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .config import IMAGE_DIR, STORAGE_LAYOUT, THUMB_DIR
from .models import PixivWork, WorkImage


SAFE_SEGMENT_PATTERN = re.compile(r"[^0-9A-Za-z._-]+")
IMAGE_THUMB_SUFFIX = ".webp"


def safe_segment(value: str | int | None, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = SAFE_SEGMENT_PATTERN.sub("_", text)
    text = text.strip("._")
    return text or fallback


def image_extension(path_or_name: str | Path, fallback: str = ".jpg") -> str:
    suffix = Path(path_or_name).suffix.lower()
    return suffix if suffix else fallback


def pixiv_file_name(work: PixivWork, image: WorkImage, ext: str | None = None) -> str:
    suffix = ext or image_extension(image.file_name or image.url)
    return f"{safe_segment(work.pixiv_id)}_p{int(image.page_index or 0)}{suffix}"


def build_image_path(work: PixivWork, image: WorkImage, ext: str | None = None, *, layout: str | None = None) -> Path:
    file_name = pixiv_file_name(work, image, ext)
    if (layout or STORAGE_LAYOUT) == "by_user":
        return IMAGE_DIR / "users" / safe_segment(work.user_id) / file_name
    return IMAGE_DIR / (image.file_name or file_name)


def build_sidecar_path(image_path: Path) -> Path:
    return image_path.with_suffix(image_path.suffix + ".json")


def build_thumb_path(image_path: Path, *, image_id: int | None = None, layout: str | None = None) -> Path:
    if (layout or STORAGE_LAYOUT) == "by_user":
        try:
            relative = image_path.resolve().relative_to(IMAGE_DIR.resolve())
        except ValueError:
            relative = Path(safe_segment(image_path.stem) + image_path.suffix)
        return (THUMB_DIR / relative).with_suffix(IMAGE_THUMB_SUFFIX)

    if image_id is not None:
        suffix = image_extension(image_path)
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        return THUMB_DIR / f"{image_id}{suffix}"
    return THUMB_DIR / f"{safe_segment(image_path.stem)}{IMAGE_THUMB_SUFFIX}"


def local_hash(source_path: Path) -> str:
    digest = hashlib.sha256()
    with source_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_local_image_path(source_path: Path, *, layout: str | None = None) -> Path:
    if (layout or STORAGE_LAYOUT) == "by_user":
        return IMAGE_DIR / "local" / f"{local_hash(source_path)}{image_extension(source_path)}"
    return IMAGE_DIR / source_path.name


def build_local_thumb_path(image_path: Path, *, image_id: int | None = None, layout: str | None = None) -> Path:
    return build_thumb_path(image_path, image_id=image_id, layout=layout)
