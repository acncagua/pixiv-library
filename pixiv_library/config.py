from __future__ import annotations

from pathlib import Path

from db_config import get_db_path, get_image_dir, get_library_dir, get_storage_layout, get_thumb_dir


ROOT = Path(__file__).resolve().parents[1]
LIBRARY_DIR = get_library_dir()
IMAGE_DIR = get_image_dir()
THUMB_DIR = get_thumb_dir()
DB_PATH = get_db_path()
STORAGE_LAYOUT = get_storage_layout()


def path_to_storage(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def resolve_storage_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (ROOT / path).resolve()
