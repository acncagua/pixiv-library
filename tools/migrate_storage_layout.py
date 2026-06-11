from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import DB_PATH, connect_db, init_db
from pixiv_library.config import IMAGE_DIR, THUMB_DIR, path_to_storage, resolve_storage_path
from pixiv_library.storage import build_sidecar_path, build_thumb_path, image_extension, local_hash, safe_segment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate local media files to another storage layout.")
    parser.add_argument("--to", choices=["by_user"], required=True, help="target storage layout")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="show planned moves without changing files")
    mode.add_argument("--apply", action="store_true", help="move files and update the database")
    return parser.parse_args()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def row_sidecar_path(row: sqlite3.Row, image_path: Path) -> Path:
    value = row["sidecar_path"] if "sidecar_path" in row.keys() else None
    if value:
        return resolve_storage_path(value)
    return build_sidecar_path(image_path)


def row_thumb_path(row: sqlite3.Row, image_path: Path) -> Path:
    value = row["thumb_path"] if "thumb_path" in row.keys() else None
    if value:
        return resolve_storage_path(value)
    return build_thumb_path(image_path, image_id=int(row["id"]), layout="flat")


def user_id_for(row: sqlite3.Row, sidecar_path: Path) -> tuple[str, bool]:
    for key in ("user_id", "source_user_id"):
        value = str(row[key] or "").strip()
        if value:
            return value, False
    metadata = read_json(sidecar_path) if sidecar_path.exists() else {}
    for key in ("user_id", "source_user_id", "pixiv_user_id"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value, False
    user = metadata.get("user")
    if isinstance(user, dict):
        value = str(user.get("id") or "").strip()
        if value:
            return value, False
    return "unknown", True


def target_image_path(row: sqlite3.Row, source_path: Path, sidecar_path: Path) -> tuple[Path, bool, str]:
    pixiv_id = str(row["pixiv_id"] or "").strip()
    if pixiv_id:
        user_id, unknown = user_id_for(row, sidecar_path)
        page_index = int(row["page_index"] or 0)
        target = (
            IMAGE_DIR
            / "users"
            / safe_segment(user_id)
            / f"{safe_segment(pixiv_id)}_p{page_index}{image_extension(source_path)}"
        )
        return target, unknown, "pixiv"

    if not source_path.exists():
        target = IMAGE_DIR / "local" / f"{safe_segment(source_path.stem)}{image_extension(source_path)}"
    else:
        target = IMAGE_DIR / "local" / f"{local_hash(source_path)}{image_extension(source_path)}"
    return target, False, "local"


def same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def plan_move(moves: list[dict], source: Path, target: Path, kind: str, image_id: int) -> None:
    if same_path(source, target):
        return
    moves.append(
        {
            "image_id": image_id,
            "kind": kind,
            "source": str(source),
            "target": str(target),
        }
    )


def collect_orphans(known_paths: set[Path]) -> list[str]:
    roots = [IMAGE_DIR, THUMB_DIR]
    orphans = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.resolve() not in known_paths:
                orphans.append(str(path))
    return orphans


def build_plan(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM images ORDER BY id").fetchall()
    moves: list[dict] = []
    updates: list[dict] = []
    missing: list[dict] = []
    unknown_users: list[dict] = []
    known_paths: set[Path] = set()

    for row in rows:
        image_id = int(row["id"])
        source_image = resolve_storage_path(row["file_path"])
        source_sidecar = row_sidecar_path(row, source_image)
        source_thumb = row_thumb_path(row, source_image)
        for path in (source_image, source_sidecar, source_thumb):
            known_paths.add(path.resolve())

        target_image, unknown_user, category = target_image_path(row, source_image, source_sidecar)
        target_sidecar = build_sidecar_path(target_image)
        target_thumb = build_thumb_path(target_image, image_id=image_id, layout="by_user")
        if unknown_user:
            unknown_users.append({"image_id": image_id, "file_path": str(source_image)})

        if source_image.exists():
            plan_move(moves, source_image, target_image, "image", image_id)
        else:
            missing.append({"image_id": image_id, "kind": "image", "path": str(source_image)})

        if source_sidecar.exists():
            plan_move(moves, source_sidecar, target_sidecar, "sidecar", image_id)
        elif row["sidecar_path"]:
            missing.append({"image_id": image_id, "kind": "sidecar", "path": str(source_sidecar)})

        if source_thumb.exists():
            plan_move(moves, source_thumb, target_thumb, "thumb", image_id)
        elif row["thumb_path"]:
            missing.append({"image_id": image_id, "kind": "thumb", "path": str(source_thumb)})

        updates.append(
            {
                "image_id": image_id,
                "category": category,
                "file_path": path_to_storage(target_image),
                "sidecar_path": path_to_storage(target_sidecar) if source_sidecar.exists() else None,
                "thumb_path": path_to_storage(target_thumb),
            }
        )

    collisions = []
    targets: dict[str, dict] = {}
    for move in moves:
        target = Path(move["target"]).resolve()
        source = Path(move["source"]).resolve()
        key = str(target)
        if key in targets and Path(targets[key]["source"]).resolve() != source:
            collisions.append({"target": key, "sources": [targets[key]["source"], move["source"]]})
        elif target.exists() and target.resolve() != source:
            collisions.append({"target": key, "sources": [move["source"], key]})
        else:
            targets[key] = move

    return {
        "rows": len(rows),
        "moves": moves,
        "updates": updates,
        "missing": missing,
        "unknown_users": unknown_users,
        "orphans": collect_orphans(known_paths),
        "collisions": collisions,
    }


def write_manifest(plan: dict, *, applied: bool) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = ROOT / f"storage_migration_{timestamp}.json"
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "applied": applied,
        "db_path": str(DB_PATH),
        "image_dir": str(IMAGE_DIR),
        "thumb_dir": str(THUMB_DIR),
        "plan": plan,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def backup_db() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = DB_PATH.with_name(f"{DB_PATH.stem}.backup_{timestamp}{DB_PATH.suffix}")
    shutil.copy2(DB_PATH, target)
    return target


def apply_plan(conn: sqlite3.Connection, plan: dict) -> None:
    for move in plan["moves"]:
        source = Path(move["source"])
        target = Path(move["target"])
        if same_path(source, target):
            continue
        if not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))

    for update in plan["updates"]:
        conn.execute(
            """
            UPDATE images
            SET file_path = ?, sidecar_path = ?, thumb_path = ?
            WHERE id = ?
            """,
            (
                update["file_path"],
                update["sidecar_path"],
                update["thumb_path"],
                int(update["image_id"]),
            ),
        )
    conn.commit()


def print_summary(plan: dict) -> None:
    print(f"Rows: {plan['rows']}")
    print(f"Moves: {len(plan['moves'])}")
    print(f"Missing DB files: {len(plan['missing'])}")
    print(f"Unmanaged files: {len(plan['orphans'])}")
    print(f"Unknown Pixiv user IDs: {len(plan['unknown_users'])}")
    print(f"Collisions: {len(plan['collisions'])}")
    for collision in plan["collisions"][:20]:
        print(f"Collision: {collision['target']}")
    for item in plan["missing"][:20]:
        print(f"Missing {item['kind']}: image_id={item['image_id']} {item['path']}")


def main() -> None:
    args = parse_args()
    with connect_db() as conn:
        init_db(conn)
        plan = build_plan(conn)
        print_summary(plan)
        manifest = write_manifest(plan, applied=False)
        print(f"Manifest: {manifest}")
        if args.dry_run:
            print("Dry-run only. No files were moved.")
            return
        if plan["collisions"]:
            print("Collisions were found. Resolve them before applying.")
            raise SystemExit(1)
        backup = backup_db()
        print(f"DB backup: {backup}")
        apply_plan(conn, plan)
        applied_manifest = write_manifest(plan, applied=True)
        print(f"Applied manifest: {applied_manifest}")


if __name__ == "__main__":
    main()
