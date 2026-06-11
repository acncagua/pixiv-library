from __future__ import annotations

from pathlib import Path

from .storage import build_thumb_path


THUMB_MAX_SIZE = (360, 360)


def thumbnail_path(image_id: int, source_path: Path) -> Path:
    return build_thumb_path(source_path, image_id=image_id)


def generate_thumbnail(source_path: Path, target_path: Path) -> Path:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate thumbnails. Run setup.bat again.") from exc

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail(THUMB_MAX_SIZE)
        if target_path.suffix.lower() in {".jpg", ".jpeg"} and image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        image.save(target_path, quality=85, optimize=True)
    return target_path


def ensure_thumbnail(image_id: int, source_path: Path) -> Path:
    target = thumbnail_path(image_id, source_path)
    if target.exists() and target.stat().st_mtime >= source_path.stat().st_mtime:
        return target
    return generate_thumbnail(source_path, target)


def rebuild_thumbnails(images: list[tuple[int, Path]]) -> int:
    count = 0
    for image_id, source_path in images:
        if source_path.exists():
            ensure_thumbnail(image_id, source_path)
            count += 1
    return count
