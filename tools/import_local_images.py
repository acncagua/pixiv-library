from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import connect_db, extract_page_index, init_db, save_user_master, upsert_image
from pixiv_library.config import IMAGE_DIR, path_to_storage
from pixiv_library.storage import build_local_image_path, build_local_thumb_path, build_sidecar_path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def metadata_for(image_path: Path) -> dict:
    sidecar = image_path.with_suffix(image_path.suffix + ".json")
    if not sidecar.exists():
        return {"title": image_path.stem, "tags": []}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"Invalid metadata JSON: {sidecar}: {exc}")
        return {"title": image_path.stem, "tags": []}


def unique_target_path(source: Path) -> Path:
    target = build_local_image_path(source)
    if not target.exists() or source.resolve() == target.resolve():
        return target
    index = 1
    while True:
        candidate = target.parent / f"{target.stem}_{index}{target.suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def copy_sidecar(source_image: Path, target_image: Path) -> None:
    source_sidecar = source_image.with_suffix(source_image.suffix + ".json")
    if not source_sidecar.exists():
        return
    target_sidecar = target_image.with_suffix(target_image.suffix + ".json")
    if source_sidecar.resolve() == target_sidecar.resolve():
        return
    if target_sidecar.exists():
        return
    target_sidecar.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_sidecar, target_sidecar)


def add_image(conn: sqlite3.Connection, image_path: Path, metadata: dict) -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = unique_target_path(image_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if image_path.resolve() != target.resolve():
        shutil.copy2(image_path, target)
        copy_sidecar(image_path, target)

    stored_path = path_to_storage(target)
    sidecar_path = build_sidecar_path(target)
    thumb_path = build_local_thumb_path(target)
    title = metadata.get("title") or image_path.stem
    tags = [tag.strip() for tag in metadata.get("tags", []) if str(tag).strip()]
    posted_at = metadata.get("posted_at") or metadata.get("create_date")
    restrict_level = int(metadata.get("restrict_level") or metadata.get("x_restrict") or 0)
    page_index = int(metadata.get("page_index") or extract_page_index(image_path.name))
    user_id = str(metadata.get("user_id") or metadata.get("pixiv_user_id") or "").strip()
    user_name = str(metadata.get("user_name") or metadata.get("pixiv_user_name") or "").strip()
    owner_type = str(metadata.get("owner_type") or "self").strip()
    source_user_id = str(metadata.get("source_user_id") or user_id).strip()
    save_user_master(conn, user_id, user_name)
    upsert_image(
        conn,
        pixiv_id=metadata.get("pixiv_id"),
        user_id=user_id,
        user_name=user_name,
        title=title,
        file_path=stored_path,
        sidecar_path=path_to_storage(sidecar_path) if sidecar_path.exists() else None,
        thumb_path=path_to_storage(thumb_path),
        page_index=page_index,
        source_url=metadata.get("source_url"),
        posted_at=posted_at,
        restrict_level=restrict_level,
        tags=tags,
        owner_type=owner_type,
        source_user_id=source_user_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import local image files and optional sidecar JSON metadata."
    )
    parser.add_argument(
        "image_directory",
        type=Path,
        help="directory containing image files to import",
    )
    args = parser.parse_args()

    source = args.image_directory.resolve()
    if not source.exists():
        print(f"Directory not found: {source}")
        raise SystemExit(1)

    images = [path for path in source.rglob("*") if path.suffix.lower() in IMAGE_EXTENSIONS]
    with connect_db() as conn:
        init_db(conn)
        for image_path in images:
            add_image(conn, image_path, metadata_for(image_path))

    print(f"Imported {len(images)} image(s).")


if __name__ == "__main__":
    main()
