from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import connect_db, init_db
from pixiv_library.config import ROOT as APP_ROOT
from pixiv_library.thumbnail import rebuild_thumbnails


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild local image thumbnails.")
    parser.add_argument("--limit", type=int, default=0, help="maximum number of images to process")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with connect_db() as conn:
        init_db(conn)
        conn.row_factory = sqlite3.Row
        sql = "SELECT id, file_path FROM images ORDER BY id"
        params = []
        if args.limit > 0:
            sql += " LIMIT ?"
            params.append(args.limit)
        rows = conn.execute(sql, params).fetchall()
    images = [(int(row["id"]), (APP_ROOT / row["file_path"]).resolve()) for row in rows]
    count = rebuild_thumbnails(images)
    print(f"Rebuilt {count} thumbnail(s).")


if __name__ == "__main__":
    main()
