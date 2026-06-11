from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import connect_db, init_db, save_user_master, upsert_image
from pixiv_library.client import PixivClient
from pixiv_library.repository import is_work_downloaded


IMAGE_DIR = ROOT / "library" / "images"
DEFAULT_DOWNLOAD_INTERVAL = 0.8
DEFAULT_PAGE_INTERVAL = 1.2


def pixiv_status_code(error: BaseException) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    text = str(error)
    for code in (403, 429):
        if str(code) in text:
            return code
    return None


def save_record(
    conn: sqlite3.Connection,
    *,
    illust: object,
    file_path: Path,
    page_index: int,
    tags: list[str],
    user_id: str,
    user_name: str,
    owner_type: str,
    source_user_id: str,
) -> None:
    relative_path = file_path.relative_to(ROOT).as_posix()
    pixiv_id = str(illust.id)
    posted_at_value = getattr(illust, "create_date", None)
    posted_at = str(posted_at_value) if posted_at_value is not None else None
    restrict_level = int(getattr(illust, "x_restrict", 0) or 0)
    upsert_image(
        conn,
        pixiv_id=pixiv_id,
        user_id=user_id,
        user_name=user_name,
        title=illust.title,
        file_path=relative_path,
        page_index=page_index,
        source_url=f"https://www.pixiv.net/artworks/{pixiv_id}",
        posted_at=posted_at,
        restrict_level=restrict_level,
        tags=tags,
        owner_type=owner_type,
        source_user_id=source_user_id,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download public Pixiv works for the authenticated user.")
    parser.add_argument(
        "--stop-at-existing",
        action="store_true",
        help="stop when the newest-to-oldest listing reaches an already indexed pixiv_id",
    )
    parser.add_argument(
        "--include-restricted",
        action="store_true",
        help="include works whose x_restrict flag is set, such as R-18 works",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    refresh_token = os.environ.get("PIXIV_REFRESH_TOKEN")
    if not refresh_token:
        print("Set PIXIV_REFRESH_TOKEN before running this script.")
        raise SystemExit(2)

    client = PixivClient(refresh_token)
    api = client.api

    auth_user_id = str(api.user_id)
    user_id = auth_user_id
    owner_type = "self"
    source_user_id = user_id
    user_name = ""
    try:
        detail = api.user_detail(user_id)
        user_name = str(getattr(detail.user, "name", "") or "")
    except Exception:
        user_name = ""
    target_label = f"Authenticated user_id={user_id}"
    if user_name:
        target_label += f" user_name={user_name}"
    if user_id == auth_user_id:
        target_label += " (authenticated user)"
    print(target_label)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    with connect_db() as conn:
        init_db(conn)
        save_user_master(conn, user_id, user_name)
        conn.commit()
        next_qs = None
        total = 0
        failed_downloads = 0
        skipped_existing = 0
        refreshed_existing = 0
        skipped_indexed_general = 0

        while True:
            try:
                if next_qs:
                    payload = api.user_illusts(**next_qs)
                else:
                    payload = api.user_illusts(user_id)
            except Exception as exc:
                status_code = pixiv_status_code(exc)
                if status_code in {403, 429}:
                    print(f"Pixiv API stopped with status {status_code}.")
                    raise SystemExit(1) from exc
                raise

            illusts = getattr(payload, "illusts", None) if payload is not None else None
            if illusts is None:
                print(f"No illust list returned for user_id={user_id}. Stopping.")
                error = getattr(payload, "error", None) if payload is not None else None
                if error:
                    print(f"Pixiv API error: {error}")
                break
            if not illusts:
                print(f"No illusts found for user_id={user_id}.")
                break

            for illust in illusts:
                pixiv_id = str(illust.id)
                restrict_level = int(getattr(illust, "x_restrict", 0) or 0)
                pages = getattr(illust, "meta_pages", []) or []
                urls = [page.image_urls.original for page in pages] or [illust.meta_single_page.original_image_url]
                already_indexed = is_work_downloaded(conn, pixiv_id, user_id, len(urls))

                if restrict_level != 0 and not args.include_restricted:
                    print(f"Skipped restricted pixiv_id={pixiv_id}")
                    continue

                if args.stop_at_existing and already_indexed:
                    if args.include_restricted and restrict_level == 0:
                        skipped_indexed_general += 1
                        continue
                    if skipped_indexed_general:
                        print(
                            f"Skipped {skipped_indexed_general} already indexed general work(s) "
                            "while looking for restricted works."
                        )
                    print(f"Reached already indexed pixiv_id={pixiv_id}. Stopping.")
                    print(f"Processed {total} image file(s).")
                    return

                tags = [tag.name for tag in illust.tags]
                work_failed = False

                for index, url in enumerate(urls):
                    suffix = Path(url.split("?")[0]).suffix or ".jpg"
                    filename = f"{illust.id}_p{index}{suffix}"
                    target = IMAGE_DIR / filename
                    existed_before = target.exists()
                    if not existed_before:
                        print(f"Downloading {filename}")
                        try:
                            api.download(url, path=str(IMAGE_DIR), name=filename)
                        except Exception as exc:
                            status_code = pixiv_status_code(exc)
                            print(
                                f"Download failed pixiv_id={pixiv_id} page_index={index}: {exc}"
                            )
                            if status_code in {403, 429}:
                                print(f"Pixiv download stopped with status {status_code}.")
                                raise SystemExit(1) from exc
                            failed_downloads += 1
                            work_failed = True
                            break
                        time.sleep(DEFAULT_DOWNLOAD_INTERVAL)
                    else:
                        skipped_existing += 1
                        print(f"Already exists {filename}")

                    sidecar = target.with_suffix(target.suffix + ".json")
                    sidecar.write_text(
                        json.dumps(
                            {
                                "pixiv_id": str(illust.id),
                                "page_index": index,
                                "user_id": user_id,
                                "user_name": user_name,
                                "title": illust.title,
                                "source_url": f"https://www.pixiv.net/artworks/{illust.id}",
                                "posted_at": str(getattr(illust, "create_date", "")) or None,
                                "restrict_level": int(getattr(illust, "x_restrict", 0) or 0),
                                "owner_type": owner_type,
                                "source_user_id": source_user_id,
                                "tags": tags,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    save_record(
                        conn,
                        illust=illust,
                        file_path=target,
                        page_index=index,
                        tags=tags,
                        user_id=user_id,
                        user_name=user_name,
                        owner_type=owner_type,
                        source_user_id=source_user_id,
                    )
                    conn.commit()
                    if existed_before:
                        refreshed_existing += 1
                        print(f"Updated metadata {sidecar.name}")
                    total += 1
                if work_failed:
                    continue

            next_qs = api.parse_qs(getattr(payload, "next_url", None))
            if not next_qs:
                break
            time.sleep(DEFAULT_PAGE_INTERVAL)

    if skipped_indexed_general:
        print(
            f"Skipped {skipped_indexed_general} already indexed general work(s) "
            "while looking for restricted works."
        )
    print(f"Processed {total} image file(s).")
    if skipped_existing:
        print(f"Skipped downloading {skipped_existing} existing image file(s).")
    if refreshed_existing:
        print(f"Updated metadata for {refreshed_existing} image file(s).")
    if failed_downloads:
        print(f"Failed downloading {failed_downloads} image file(s).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
