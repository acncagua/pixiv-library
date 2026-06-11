from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from db import DB_PATH, connect_db, init_db
from pixiv_library.config import IMAGE_DIR, LIBRARY_DIR, THUMB_DIR, path_to_storage, resolve_storage_path
from pixiv_library.thumbnail import ensure_thumbnail


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

DOWNLOAD_JOB = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "message": "未実行",
    "log": [],
}
DOWNLOAD_LOCK = threading.Lock()

TOKEN_JOB = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "message": "未実行",
    "token": None,
    "log": [],
}
TOKEN_LOCK = threading.Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Pixiv Viewer.")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="stop an existing process that is already listening on the selected port before starting",
    )
    return parser.parse_args()


def listening_pids(port: int) -> set[int]:
    if os.name != "nt":
        return set()
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return set()

    pids = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "TCP" or parts[3] != "LISTENING":
            continue
        local_address = parts[1]
        if local_address.rsplit(":", 1)[-1] == str(port):
            try:
                pids.add(int(parts[-1]))
            except ValueError:
                pass
    return pids


def stop_existing_server(port: int) -> None:
    current_pid = os.getpid()
    for pid in listening_pids(port):
        if pid == current_pid:
            continue
        print(f"Stopping existing process on port {port}: PID {pid}")
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
        except OSError as exc:
            print(f"Failed to stop PID {pid}: {exc}")
    time.sleep(0.5)


def pages_for_image(conn: sqlite3.Connection, row: sqlite3.Row) -> list[dict]:
    pixiv_id = row["pixiv_id"]
    if pixiv_id:
        page_rows = conn.execute(
            """
            SELECT id, page_index
            FROM images
            WHERE pixiv_id = ? AND COALESCE(user_id, '') = COALESCE(?, '')
            ORDER BY COALESCE(page_index, 0) ASC, id ASC
            """,
            (pixiv_id, row["user_id"]),
        ).fetchall()
    else:
        page_rows = [row]
    return [
        {
            "id": page_row["id"],
            "page_index": page_row["page_index"],
            "image_url": f"/media/{page_row['id']}",
            "thumb_url": f"/thumb/{page_row['id']}",
        }
        for page_row in page_rows
    ]


def row_to_image(row: sqlite3.Row, conn: sqlite3.Connection | None = None) -> dict:
    tags = row["tags"].split("\x1f") if row["tags"] else []
    restrict_level = int(row["restrict_level"] or 0)
    is_r18 = bool(restrict_level) or any(tag.upper() == "R-18" for tag in tags)
    pages = pages_for_image(conn, row) if conn else [
        {
            "id": row["id"],
            "page_index": row["page_index"],
            "image_url": f"/media/{row['id']}",
            "thumb_url": f"/thumb/{row['id']}",
        }
    ]
    return {
        "id": row["id"],
        "pixiv_id": row["pixiv_id"],
        "page_index": row["page_index"],
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "title": row["title"],
        "source_url": row["source_url"],
        "posted_at": row["posted_at"],
        "restrict_level": restrict_level,
        "owner_type": row["owner_type"] if "owner_type" in row.keys() else "self",
        "source_user_id": row["source_user_id"] if "source_user_id" in row.keys() else row["user_id"],
        "is_r18": is_r18,
        "tags": tags,
        "image_url": f"/media/{row['id']}",
        "thumb_url": f"/thumb/{row['id']}",
        "pages": pages,
        "page_count": len(pages),
    }


def order_clause(sort: str) -> str:
    if sort == "posted_asc":
        return "ORDER BY i.posted_at ASC, i.id ASC"
    if sort == "title_asc":
        return "ORDER BY i.title COLLATE NOCASE ASC, i.id ASC"
    if sort == "title_desc":
        return "ORDER BY i.title COLLATE NOCASE DESC, i.id DESC"
    return "ORDER BY i.posted_at DESC, i.id DESC"


def query_images(
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "posted_desc",
    rating: str = "general",
    user_id: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict:
    limit = max(1, min(limit, 300))
    offset = max(0, offset)
    words = [word.strip() for word in search.replace("\u3000", " ").split() if word.strip()]
    filters = []
    filter_params = []
    if user_id:
        filters.append("i.user_id = ?")
        filter_params.append(user_id)
    if date_from:
        filters.append("i.posted_at >= ?")
        filter_params.append(date_from)
    if date_to:
        filters.append("i.posted_at < date(?, '+1 day')")
        filter_params.append(date_to)
    if rating == "r18":
        filters.append(
            """
            (
                COALESCE(i.restrict_level, 0) != 0
                OR EXISTS (
                    SELECT 1 FROM image_tags rit
                    JOIN tags rt ON rt.id = rit.tag_id
                    WHERE rit.image_id = i.id AND UPPER(rt.name) = 'R-18'
                )
            )
            """
        )
    elif rating == "general":
        filters.append(
            """
            COALESCE(i.restrict_level, 0) = 0
            AND NOT EXISTS (
                SELECT 1 FROM image_tags rit
                JOIN tags rt ON rt.id = rit.tag_id
                WHERE rit.image_id = i.id AND UPPER(rt.name) = 'R-18'
            )
            """
        )

    with connect_db() as conn:
        conn.row_factory = sqlite3.Row
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        work_key = """
            CASE
                WHEN COALESCE(i.pixiv_id, '') != '' THEN COALESCE(i.user_id, '') || ':' || i.pixiv_id
                ELSE 'image:' || i.id
            END
        """
        eligible_cte = f"""
            eligible AS (
                SELECT i.id, {work_key} AS work_key, COALESCE(i.page_index, 0) AS page_index
                FROM images i
                {where_clause}
            )
        """
        tag_params = [f"%{word}%" for word in words]
        if words:
            matched_cte = f"""
                matched AS (
                    SELECT e.id, e.work_key, e.page_index
                    FROM eligible e
                    JOIN image_tags it ON it.image_id = e.id
                    JOIN tags t ON t.id = it.tag_id
                    WHERE {" OR ".join("t.name LIKE ?" for _ in words)}
                    GROUP BY e.id
                    HAVING COUNT(DISTINCT CASE
                        {" ".join(f"WHEN t.name LIKE ? THEN {idx}" for idx, _ in enumerate(words))}
                    END) = ?
                )
            """
            matched_params = filter_params + tag_params + tag_params + [len(words)]
        else:
            matched_cte = """
                matched AS (
                    SELECT id, work_key, page_index
                    FROM eligible
                )
            """
            matched_params = filter_params
        representatives_cte = """
            representatives AS (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY work_key
                            ORDER BY page_index ASC, id ASC
                        ) AS row_number
                    FROM matched
                )
                WHERE row_number = 1
            )
        """
        search_cte = f"WITH {eligible_cte}, {matched_cte}, {representatives_cte}"
        total = conn.execute(
            f"""
            {search_cte}
            SELECT COUNT(*) FROM representatives
            """,
            matched_params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            {search_cte}
            SELECT i.*, GROUP_CONCAT(t.name, char(31)) AS tags
            FROM images i
            JOIN representatives r ON r.id = i.id
            LEFT JOIN image_tags it ON it.image_id = i.id
            LEFT JOIN tags t ON t.id = it.tag_id
            GROUP BY i.id
            {order_clause(sort)}
            LIMIT ? OFFSET ?
            """,
            matched_params + [limit, offset],
        ).fetchall()
        images = [row_to_image(row, conn) for row in rows]
        return {
            "images": images,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(images) < total,
        }


def popular_tags(
    date_from: str = "",
    date_to: str = "",
    rating: str = "general",
    user_id: str = "",
) -> list[dict]:
    filters = []
    params = []
    if user_id:
        filters.append("i.user_id = ?")
        params.append(user_id)
    if date_from:
        filters.append("i.posted_at >= ?")
        params.append(date_from)
    if date_to:
        filters.append("i.posted_at < date(?, '+1 day')")
        params.append(date_to)
    if rating == "r18":
        filters.append(
            """
            (
                COALESCE(i.restrict_level, 0) != 0
                OR EXISTS (
                    SELECT 1 FROM image_tags rit
                    JOIN tags rt ON rt.id = rit.tag_id
                    WHERE rit.image_id = i.id AND UPPER(rt.name) = 'R-18'
                )
            )
            """
        )
    elif rating == "general":
        filters.append(
            """
            COALESCE(i.restrict_level, 0) = 0
            AND NOT EXISTS (
                SELECT 1 FROM image_tags rit
                JOIN tags rt ON rt.id = rit.tag_id
                WHERE rit.image_id = i.id AND UPPER(rt.name) = 'R-18'
            )
            """
        )

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    with connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                t.name,
                COUNT(DISTINCT CASE
                    WHEN COALESCE(i.pixiv_id, '') != '' THEN COALESCE(i.user_id, '') || ':' || i.pixiv_id
                    ELSE 'image:' || i.id
                END) AS count
            FROM images i
            JOIN image_tags it ON it.image_id = i.id
            JOIN tags t ON t.id = it.tag_id
            {where_clause}
            GROUP BY t.id
            ORDER BY count DESC, t.name ASC
            LIMIT 80
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def int_param(params: dict, name: str, default: int) -> int:
    try:
        return int(params.get(name, [str(default)])[0])
    except (TypeError, ValueError):
        return default


def append_download_log(line: str) -> None:
    with DOWNLOAD_LOCK:
        DOWNLOAD_JOB["log"].append(line)
        DOWNLOAD_JOB["log"] = DOWNLOAD_JOB["log"][-500:]
        DOWNLOAD_JOB["message"] = line


def mark_download_started() -> None:
    with DOWNLOAD_LOCK:
        DOWNLOAD_JOB.update(
            {
                "running": True,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None,
                "returncode": None,
                "message": "取得を開始しました",
                "log": [],
            }
        )


def run_download_command(
    refresh_token: str,
    stop_at_existing: bool,
    include_restricted: bool,
) -> int:
    env = os.environ.copy()
    env["PIXIV_REFRESH_TOKEN"] = refresh_token
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-u", str(ROOT / "tools" / "download_pixiv_public.py")]
    if stop_at_existing:
        command.append("--stop-at-existing")
    if include_restricted:
        command.append("--include-restricted")

    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        append_download_log(line.rstrip())
    return process.wait()


def run_download_job(
    refresh_token: str,
    stop_at_existing: bool,
    include_restricted: bool,
) -> None:
    with DOWNLOAD_LOCK:
        DOWNLOAD_JOB.update(
            {
                "running": True,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None,
                "returncode": None,
                "message": "取得を開始しました",
                "log": [],
            }
        )

    try:
        returncode = run_download_command(refresh_token, stop_at_existing, include_restricted)
        with DOWNLOAD_LOCK:
            DOWNLOAD_JOB.update(
                {
                    "running": False,
                    "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "returncode": returncode,
                    "message": "取得が完了しました" if returncode == 0 else "取得に失敗しました",
                }
            )
    except Exception as exc:
        with DOWNLOAD_LOCK:
            DOWNLOAD_JOB.update(
                {
                    "running": False,
                    "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "returncode": -1,
                    "message": f"取得に失敗しました: {exc}",
                }
            )


def download_status() -> dict:
    with DOWNLOAD_LOCK:
        status = dict(DOWNLOAD_JOB)
        status["log"] = list(DOWNLOAD_JOB["log"])
        return status


def append_token_log(line: str) -> None:
    with TOKEN_LOCK:
        if line.startswith("$env:PIXIV_REFRESH_TOKEN="):
            return
        TOKEN_JOB["log"].append(line)
        TOKEN_JOB["log"] = TOKEN_JOB["log"][-80:]
        if line and line != "refresh_token:":
            TOKEN_JOB["message"] = line


def mark_token_started() -> None:
    TOKEN_JOB.update(
        {
            "running": True,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": None,
            "returncode": None,
            "message": "トークン取得を開始しました",
            "token": None,
            "log": [],
        }
    )


def run_token_job() -> None:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-u", str(ROOT / "tools" / "get_pixiv_token_browser.py")]
    with TOKEN_LOCK:
        TOKEN_JOB.update(
            {
                "running": True,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None,
                "returncode": None,
                "message": "ブラウザでPixivログインを開始しました",
                "token": None,
                "log": [],
            }
        )

    captured_token = None
    expect_token_line = False
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if expect_token_line and line:
                captured_token = line
                expect_token_line = False
                append_token_log("refresh_tokenを取得しました")
                continue
            if line == "refresh_token:":
                expect_token_line = True
                continue
            append_token_log(line)

        returncode = process.wait()
        with TOKEN_LOCK:
            TOKEN_JOB.update(
                {
                    "running": False,
                    "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "returncode": returncode,
                    "token": captured_token,
                    "message": "トークン取得が完了しました"
                    if returncode == 0 and captured_token
                    else "トークン取得に失敗しました",
                }
            )
    except Exception as exc:
        with TOKEN_LOCK:
            TOKEN_JOB.update(
                {
                    "running": False,
                    "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "returncode": -1,
                    "message": f"トークン取得に失敗しました: {exc}",
                }
            )


def token_status() -> dict:
    with TOKEN_LOCK:
        status = dict(TOKEN_JOB)
        status["log"] = list(TOKEN_JOB["log"])
        status["has_token"] = bool(TOKEN_JOB.get("token"))
        TOKEN_JOB["token"] = None
        return status


def lan_addresses() -> list[str]:
    addresses = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            address = info[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            self.handle_get()
        except Exception as exc:
            self.send_exception(exc)

    def handle_get(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            self.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8", cache_control="no-cache")
            return
        if path.startswith("/static/"):
            target = (STATIC_DIR / path.removeprefix("/static/")).resolve()
            if not target.is_relative_to(STATIC_DIR.resolve()):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            self.send_file(target)
            return
        if path == "/api/images":
            params = parse_qs(parsed.query)
            self.send_json(
                query_images(
                    params.get("tag", [""])[0],
                    params.get("from", [""])[0],
                    params.get("to", [""])[0],
                    params.get("sort", ["posted_desc"])[0],
                    params.get("rating", ["general"])[0],
                    "",
                    int_param(params, "limit", 100),
                    int_param(params, "offset", 0),
                )
            )
            return
        if path == "/api/tags":
            params = parse_qs(parsed.query)
            self.send_json(
                {
                    "tags": popular_tags(
                        params.get("from", [""])[0],
                        params.get("to", [""])[0],
                        params.get("rating", ["general"])[0],
                        "",
                    )
                }
            )
            return
        if path == "/api/download/status":
            self.send_json(download_status())
            return
        if path == "/api/token/status":
            self.send_json(token_status())
            return
        if path.startswith("/media/"):
            self.send_media(path.removeprefix("/media/"))
            return
        if path.startswith("/thumb/"):
            self.send_thumb(path.removeprefix("/thumb/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            self.handle_post()
        except Exception as exc:
            self.send_exception(exc)

    def handle_post(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/download/start":
            self.start_download()
            return
        if path == "/api/token/start":
            self.start_token()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body)

    def start_download(self) -> None:
        try:
            payload = self.read_json()
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "JSONの読み取りに失敗しました"}, HTTPStatus.BAD_REQUEST)
            return

        refresh_token = str(payload.get("refresh_token", "")).strip()
        stop_at_existing = bool(payload.get("stop_at_existing", True))
        include_restricted = bool(payload.get("include_restricted", False))
        if not refresh_token:
            self.send_json({"ok": False, "error": "refresh_tokenを入力してください"}, HTTPStatus.BAD_REQUEST)
            return

        with DOWNLOAD_LOCK:
            if DOWNLOAD_JOB["running"]:
                self.send_json({"ok": False, "error": "すでに取得処理が実行中です"}, HTTPStatus.CONFLICT)
                return

        thread = threading.Thread(
            target=run_download_job,
            args=(refresh_token, stop_at_existing, include_restricted),
            daemon=True,
        )
        mark_download_started()
        thread.start()
        self.send_json({"ok": True, "status": download_status()})

    def start_token(self) -> None:
        with TOKEN_LOCK:
            if TOKEN_JOB["running"]:
                self.send_json({"ok": False, "error": "すでにトークン取得が実行中です"}, HTTPStatus.CONFLICT)
                return
            mark_token_started()

        thread = threading.Thread(target=run_token_job, daemon=True)
        thread.start()
        self.send_json({"ok": True, "status": token_status()})

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(
        self,
        target: Path,
        content_type: str | None = None,
        cache_control: str = "public, max-age=3600",
    ) -> None:
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        guessed = content_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", guessed)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        with target.open("rb") as file:
            shutil.copyfileobj(file, self.wfile)

    def send_media(self, image_id: str) -> None:
        if not image_id.isdigit():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        with connect_db() as conn:
            row = conn.execute("SELECT file_path, thumb_path FROM images WHERE id = ?", (int(image_id),)).fetchone()
        if row is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        target = resolve_storage_path(row[0])
        if not target.is_relative_to(IMAGE_DIR.resolve()):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.send_file(target)

    def send_thumb(self, image_id: str) -> None:
        if not image_id.isdigit():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        with connect_db() as conn:
            row = conn.execute("SELECT file_path, thumb_path FROM images WHERE id = ?", (int(image_id),)).fetchone()
        if row is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        source = resolve_storage_path(row[0])
        if not source.is_relative_to(IMAGE_DIR.resolve()) or not source.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            target = ensure_thumbnail(int(image_id), source)
        except RuntimeError as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if not row[1] or resolve_storage_path(row[1]) != target.resolve():
            with connect_db() as conn:
                conn.execute(
                    "UPDATE images SET thumb_path = ? WHERE id = ?",
                    (path_to_storage(target), int(image_id)),
                )
        self.send_file(target)

    def send_exception(self, exc: Exception) -> None:
        print(f"Unhandled request error: {exc}")
        if not self.headers_sent():
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def headers_sent(self) -> bool:
        return getattr(self, "_headers_buffer", None) == []

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            status = HTTPStatus(code)
            self.send_json({"ok": False, "error": message or status.phrase}, status)
            return
        super().send_error(code, message, explain)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    args = parse_args()
    if args.replace_existing:
        stop_existing_server(args.port)

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Pixiv管理Viewer: http://127.0.0.1:{args.port}")
    for address in lan_addresses():
        print(f"LAN/iPad URL: http://{address}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
