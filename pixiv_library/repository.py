from __future__ import annotations

import sqlite3
from pathlib import Path

from db import connect_db, init_db, save_user_master, upsert_image

from .config import path_to_storage, resolve_storage_path
from .models import PixivWork
from .storage import build_sidecar_path, build_thumb_path


def initialize(conn: sqlite3.Connection | None = None) -> None:
    init_db(conn)


def is_work_downloaded(conn: sqlite3.Connection, work_id: int | str, user_id: str, page_count: int) -> bool:
    rows = conn.execute(
        """
        SELECT page_index, file_path
        FROM images
        WHERE pixiv_id = ? AND user_id = ?
        """,
        (str(work_id), str(user_id)),
    ).fetchall()
    found_pages = set()
    for page_index, file_path in rows:
        target = resolve_storage_path(str(file_path))
        if target.exists():
            found_pages.add(int(page_index or 0))
    return set(range(page_count)).issubset(found_pages)


def upsert_work_image(
    conn: sqlite3.Connection,
    *,
    work: PixivWork,
    file_path: Path,
    page_index: int,
    sidecar_path: Path | None = None,
    thumb_path: Path | None = None,
    owner_type: str = "self",
    source_user_id: str | None = None,
) -> int:
    save_user_master(conn, work.user_id, work.user_name)
    sidecar_path = sidecar_path or build_sidecar_path(file_path)
    thumb_path = thumb_path or build_thumb_path(file_path)
    return upsert_image(
        conn,
        pixiv_id=work.pixiv_id,
        user_id=work.user_id,
        user_name=work.user_name,
        title=work.title,
        file_path=path_to_storage(file_path),
        sidecar_path=path_to_storage(sidecar_path),
        thumb_path=path_to_storage(thumb_path),
        page_index=page_index,
        source_url=work.source_url,
        posted_at=work.posted_at,
        restrict_level=work.restrict_level,
        tags=work.tags,
        owner_type=owner_type,
        source_user_id=source_user_id or work.user_id,
    )
