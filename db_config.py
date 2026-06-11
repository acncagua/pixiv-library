from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOCAL_CONFIG_PATH = ROOT / "local_config.json"


def _load_local_config() -> dict:
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _configured_path(env_name: str, config_key: str, default: Path) -> Path:
    value = os.environ.get(env_name)
    if not value:
        value = str(_load_local_config().get(config_key) or "").strip()
    if not value:
        return default
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def get_db_path() -> Path:
    return _configured_path("PIXIV_VIEWER_DB_PATH", "db_path", ROOT / "pixiv_viewer.db")


def get_library_dir() -> Path:
    return _configured_path("PIXIV_VIEWER_LIBRARY_DIR", "library_dir", ROOT / "library")


def get_image_dir() -> Path:
    return _configured_path("PIXIV_VIEWER_IMAGE_DIR", "image_dir", get_library_dir() / "images")


def get_thumb_dir() -> Path:
    return _configured_path("PIXIV_VIEWER_THUMB_DIR", "thumb_dir", get_library_dir() / "thumbs")


def get_storage_layout() -> str:
    value = os.environ.get("PIXIV_VIEWER_STORAGE_LAYOUT")
    if not value:
        value = str(_load_local_config().get("storage_layout") or "").strip()
    value = (value or "flat").lower()
    if value not in {"flat", "by_user"}:
        return "flat"
    return value
