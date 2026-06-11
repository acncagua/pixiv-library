from __future__ import annotations

from pathlib import Path

from db_config import get_db_path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY_DIR = ROOT / "library"
IMAGE_DIR = LIBRARY_DIR / "images"
THUMB_DIR = LIBRARY_DIR / "thumbs"
DB_PATH = get_db_path()

