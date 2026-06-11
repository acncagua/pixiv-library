from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import sys
import urllib.parse

import requests
from playwright.async_api import async_playwright


USER_AGENT = "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)"
CALLBACK_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
LOGIN_URL = "https://app-api.pixiv.net/web/v1/login"
AUTH_TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"


def s256(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def exchange_code(code: str, code_verifier: str) -> dict:
    response = requests.post(
        AUTH_TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "include_policy": "true",
            "redirect_uri": CALLBACK_URI,
        },
        headers={
            "User-Agent": USER_AGENT,
            "App-OS-Version": "14.6",
            "App-OS": "ios",
        },
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        print(f"Token exchange failed: HTTP {response.status_code}", file=sys.stderr)
        print(response.text[:1000], file=sys.stderr)
        raise exc
    return response.json()


async def main() -> None:
    code_verifier = secrets.token_urlsafe(32)
    login_url = f"{LOGIN_URL}?{urllib.parse.urlencode({
        'code_challenge': s256(code_verifier),
        'code_challenge_method': 'S256',
        'client': 'pixiv-android',
    })}"

    code_future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[f"--user-agent={USER_AGENT}", "--disable-extensions"],
        )
        context = await browser.new_context()
        page = await context.new_page()

        def capture_url(url: str) -> None:
            if code_future.done():
                return
            match = re.search(r"code=([^&]+)", url)
            if url.startswith("pixiv://") and match:
                code_future.set_result(match.group(1))

        page.on("request", lambda request: capture_url(request.url))
        page.on("framenavigated", lambda frame: capture_url(frame.url))

        print("ブラウザでPixivにログインしてください。")
        print("メール認証やCaptchaが出た場合も、そのまま最後まで進めてください。")
        print("認可コードを検出するまで最大5分待ちます。")
        await page.goto(login_url, wait_until="domcontentloaded")

        try:
            code = await asyncio.wait_for(code_future, timeout=300)
        finally:
            await browser.close()

    token = exchange_code(code, code_verifier)
    if "refresh_token" not in token:
        print(json.dumps(token, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    print("\nrefresh_token:")
    print(token["refresh_token"])
    print("\nPowerShellで使う場合:")
    print(f'$env:PIXIV_REFRESH_TOKEN="{token["refresh_token"]}"')


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
