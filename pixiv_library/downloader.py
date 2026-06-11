from __future__ import annotations

import json
from pathlib import Path

from .config import IMAGE_DIR, ROOT
from .models import PixivWork, WorkImage


def work_from_illust(illust: object, *, user_id: str, user_name: str) -> PixivWork:
    pages = getattr(illust, "meta_pages", []) or []
    urls = [page.image_urls.original for page in pages] or [illust.meta_single_page.original_image_url]
    images = []
    for index, url in enumerate(urls):
        suffix = Path(url.split("?")[0]).suffix or ".jpg"
        images.append(WorkImage(page_index=index, url=url, file_name=f"{illust.id}_p{index}{suffix}"))
    posted_at_value = getattr(illust, "create_date", None)
    return PixivWork(
        pixiv_id=str(illust.id),
        user_id=str(user_id),
        user_name=str(user_name or ""),
        title=str(getattr(illust, "title", "")),
        source_url=f"https://www.pixiv.net/artworks/{illust.id}",
        posted_at=str(posted_at_value) if posted_at_value is not None else None,
        restrict_level=int(getattr(illust, "x_restrict", 0) or 0),
        tags=[tag.name for tag in getattr(illust, "tags", [])],
        images=images,
    )


def fetch_work(client: object, work_id: int | str, *, user_id: str, user_name: str) -> PixivWork:
    detail = client.illust_detail(work_id)
    return work_from_illust(detail.illust, user_id=user_id, user_name=user_name)


def save_work_sidecar(
    work: PixivWork,
    image_path: Path,
    page_index: int,
    *,
    owner_type: str = "self",
    source_user_id: str | None = None,
) -> None:
    image_path.with_suffix(image_path.suffix + ".json").write_text(
        json.dumps(
            {
                "pixiv_id": work.pixiv_id,
                "page_index": page_index,
                "user_id": work.user_id,
                "user_name": work.user_name,
                "title": work.title,
                "source_url": work.source_url,
                "posted_at": work.posted_at,
                "restrict_level": work.restrict_level,
                "owner_type": owner_type,
                "source_user_id": source_user_id or work.user_id,
                "tags": work.tags,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def download_work_asset(
    client: object,
    work: PixivWork,
    image: WorkImage,
    *,
    owner_type: str = "self",
    source_user_id: str | None = None,
) -> tuple[Path, WorkImage, bool]:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = IMAGE_DIR / image.file_name
    existed_before = target.exists()
    if not existed_before:
        client.download(image.url, path=str(IMAGE_DIR), name=image.file_name)
    save_work_sidecar(
        work,
        target,
        image.page_index,
        owner_type=owner_type,
        source_user_id=source_user_id,
    )
    return target, image, existed_before


def download_work_assets(
    client: object,
    work: PixivWork,
    *,
    owner_type: str = "self",
    source_user_id: str | None = None,
) -> list[tuple[Path, WorkImage, bool]]:
    results = []
    for image in work.images:
        results.append(
            download_work_asset(
                client,
                work,
                image,
                owner_type=owner_type,
                source_user_id=source_user_id,
            )
        )
    return results
