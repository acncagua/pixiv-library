from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkImage:
    page_index: int
    url: str
    file_name: str = ""


@dataclass(frozen=True)
class PixivWork:
    pixiv_id: str
    user_id: str
    user_name: str
    title: str
    source_url: str
    posted_at: str | None
    restrict_level: int
    tags: list[str] = field(default_factory=list)
    images: list[WorkImage] = field(default_factory=list)

