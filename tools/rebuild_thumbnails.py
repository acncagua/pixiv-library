from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import connect_db, init_db
from pixiv_library.config import path_to_storage, resolve_storage_path
from pixiv_library.thumbnail import ensure_thumbnail


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild local image thumbnails.")
    parser.add_argument("--limit", type=int, default=0, help="maximum number of images to process")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    count = 0
    with connect_db() as conn:
        init_db(conn)
        conn.row_factory = sqlite3.Row
        sql = "SELECT id, file_path FROM images ORDER BY id"
        params = []
        if args.limit > 0:
            sql += " LIMIT ?"
            params.append(args.limit)
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            image_id = int(row["id"])
            source_path = resolve_storage_path(row["file_path"])
            if not source_path.exists():
                continue
            thumb_path = ensure_thumbnail(image_id, source_path)
            conn.execute(
                "UPDATE images SET thumb_path = ? WHERE id = ?",
                (path_to_storage(thumb_path), image_id),
            )
            count += 1
    print(f"Rebuilt {count} thumbnail(s).")


if __name__ == "__main__":
    main()
