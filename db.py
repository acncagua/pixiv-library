from __future__ import annotations

import sqlite3
import re

from db_config import get_db_path


DB_PATH = get_db_path()
PAGE_INDEX_PATTERN = re.compile(r"_p(\d+)(?:\.[^.]+)?$", re.IGNORECASE)


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    if conn is None:
        with connect_db() as owned_conn:
            init_db(owned_conn)
        return

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pixiv_id TEXT,
            user_id TEXT,
            user_name TEXT,
            title TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            page_index INTEGER DEFAULT 0,
            source_url TEXT,
            posted_at TEXT,
            restrict_level INTEGER DEFAULT 0,
            owner_type TEXT DEFAULT 'self',
            source_user_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_masters (
            user_id TEXT PRIMARY KEY,
            user_name TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS image_tags (
            image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (image_id, tag_id)
        )
        """
    )

    columns = [row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()]
    if "posted_at" not in columns:
        conn.execute("ALTER TABLE images ADD COLUMN posted_at TEXT")
    if "restrict_level" not in columns:
        conn.execute("ALTER TABLE images ADD COLUMN restrict_level INTEGER DEFAULT 0")
    if "user_id" not in columns:
        conn.execute("ALTER TABLE images ADD COLUMN user_id TEXT")
    if "user_name" not in columns:
        conn.execute("ALTER TABLE images ADD COLUMN user_name TEXT")
    if "page_index" not in columns:
        conn.execute("ALTER TABLE images ADD COLUMN page_index INTEGER DEFAULT 0")
    if "owner_type" not in columns:
        conn.execute("ALTER TABLE images ADD COLUMN owner_type TEXT DEFAULT 'self'")
    if "source_user_id" not in columns:
        conn.execute("ALTER TABLE images ADD COLUMN source_user_id TEXT")
    conn.execute("UPDATE images SET owner_type = 'self' WHERE owner_type IS NULL OR owner_type = ''")
    backfill_page_index(conn)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_pixiv_id ON images(pixiv_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_user_id ON images(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_posted_at ON images(posted_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_restrict_level ON images(restrict_level)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_owner_type ON images(owner_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_source_user_id ON images(source_user_id)")
    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_images_user_pixiv_page
            ON images(user_id, pixiv_id, page_index)
            WHERE user_id IS NOT NULL AND user_id != ''
              AND pixiv_id IS NOT NULL AND pixiv_id != ''
            """
        )
    except sqlite3.IntegrityError:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_user_pixiv_page_lookup ON images(user_id, pixiv_id, page_index)"
        )
    conn.execute("DROP VIEW IF EXISTS public_images")
    conn.execute(
        """
        CREATE VIEW public_images AS
        SELECT *
        FROM images
        WHERE COALESCE(owner_type, 'self') = 'self'
        """
    )


def extract_page_index(file_path: str) -> int:
    match = PAGE_INDEX_PATTERN.search(str(file_path))
    if not match:
        return 0
    return int(match.group(1))


def backfill_page_index(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, file_path, COALESCE(page_index, 0) FROM images").fetchall()
    for image_id, file_path, current_page_index in rows:
        page_index = extract_page_index(file_path)
        if page_index != int(current_page_index or 0):
            conn.execute("UPDATE images SET page_index = ? WHERE id = ?", (page_index, image_id))


def save_user_master(conn: sqlite3.Connection, user_id: str, user_name: str) -> None:
    if not user_id:
        return
    conn.execute(
        """
        INSERT INTO user_masters (user_id, user_name, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            user_name = CASE
                WHEN excluded.user_name != '' THEN excluded.user_name
                ELSE user_masters.user_name
            END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, user_name),
    )


def upsert_image(
    conn: sqlite3.Connection,
    *,
    pixiv_id: str | None,
    user_id: str,
    user_name: str,
    title: str,
    file_path: str,
    page_index: int,
    source_url: str | None,
    posted_at: str | None,
    restrict_level: int,
    tags: list[str],
    owner_type: str = "self",
    source_user_id: str | None = None,
) -> int:
    owner_type = owner_type if owner_type in {"self", "external"} else "self"
    cursor = conn.execute(
        """
        INSERT INTO images (
            pixiv_id, user_id, user_name, title, file_path, page_index, source_url,
            posted_at, restrict_level, owner_type, source_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            pixiv_id = excluded.pixiv_id,
            user_id = excluded.user_id,
            user_name = excluded.user_name,
            title = excluded.title,
            page_index = excluded.page_index,
            source_url = excluded.source_url,
            posted_at = excluded.posted_at,
            restrict_level = excluded.restrict_level,
            owner_type = excluded.owner_type,
            source_user_id = excluded.source_user_id
        RETURNING id
        """,
        (
            pixiv_id,
            user_id,
            user_name,
            title,
            file_path,
            page_index,
            source_url,
            posted_at,
            restrict_level,
            owner_type,
            source_user_id,
        ),
    )
    image_id = int(cursor.fetchone()[0])
    replace_image_tags(conn, image_id, tags)
    return image_id


def replace_image_tags(conn: sqlite3.Connection, image_id: int, tags: list[str]) -> None:
    conn.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))
    for tag in tags:
        name = str(tag).strip()
        if not name:
            continue
        cursor = conn.execute(
            "INSERT INTO tags (name) VALUES (?) ON CONFLICT(name) DO UPDATE SET name = excluded.name RETURNING id",
            (name,),
        )
        tag_id = int(cursor.fetchone()[0])
        conn.execute(
            "INSERT OR IGNORE INTO image_tags (image_id, tag_id) VALUES (?, ?)",
            (image_id, tag_id),
        )
