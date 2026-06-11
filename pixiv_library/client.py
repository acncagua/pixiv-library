from __future__ import annotations


def require_pixivpy():
    try:
        from pixivpy3 import AppPixivAPI  # type: ignore
    except ImportError:
        print("pixivpy3 is not installed. Run: pip install pixivpy3")
        raise SystemExit(1)
    return AppPixivAPI


class PixivClient:
    def __init__(self, refresh_token: str):
        AppPixivAPI = require_pixivpy()
        self.api = AppPixivAPI()
        self.api.auth(refresh_token=refresh_token)

    @property
    def user_id(self) -> str:
        return str(self.api.user_id)

    def user_detail(self, user_id: str):
        return self.api.user_detail(user_id)

    def my_illusts(self, next_qs: dict | None = None):
        if next_qs:
            return self.api.user_illusts(**next_qs)
        return self.api.user_illusts(self.user_id)

    def illust_detail(self, work_id: int | str):
        return self.api.illust_detail(work_id)

    def parse_qs(self, next_url: str | None):
        return self.api.parse_qs(next_url)

    def download(self, url: str, *, path: str, name: str) -> None:
        self.api.download(url, path=path, name=name)

