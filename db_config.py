from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def get_db_path() -> Path:
    return ROOT / "pixiv_viewer.db"
