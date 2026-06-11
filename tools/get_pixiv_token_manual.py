from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser


USER_AGENT = "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)"
CALLBACK_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
LOGIN_URL = "https://app-api.pixiv.net/web/v1/login"
AUTH_TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"


def s256(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def extract_code(callback_text: str) -> str:
    parsed = urllib.parse.urlparse(callback_text.strip())
    query = urllib.parse.parse_qs(parsed.query)
    code = query.get("code", [""])[0]
    if not code:
        raise ValueError("URLに code=... が見つかりませんでした。")
    return code


def exchange_code(code: str, code_verifier: str) -> dict:
    data = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "include_policy": "true",
            "redirect_uri": CALLBACK_URI,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        AUTH_TOKEN_URL,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "App-OS-Version": "14.6",
            "App-OS": "ios",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    code_verifier = secrets.token_urlsafe(32)
    params = urllib.parse.urlencode(
        {
            "code_challenge": s256(code_verifier),
            "code_challenge_method": "S256",
            "client": "pixiv-android",
        }
    )
    login_url = f"{LOGIN_URL}?{params}"

    print("ブラウザでPixivログインページを開きます。")
    print("ログイン後、アドレスバーまたは遷移先のURL全体を貼り付けてください。")
    print("URLに code=... が含まれていればOKです。")
    print()
    print(login_url)
    webbrowser.open(login_url)

    callback_text = input("\nログイン後のURL: ").strip()
    code = extract_code(callback_text)
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
        main()
    except KeyboardInterrupt:
        sys.exit(130)

