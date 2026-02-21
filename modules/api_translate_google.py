import os
import json
import subprocess
import shutil
from pathlib import Path

from dotenv import load_dotenv
import requests

import google.auth
from google.auth.transport.requests import Request
from google.auth.exceptions import DefaultCredentialsError

"""Google Translate API (v2).

- APIキー（GOOGLE_API_KEY）があれば APIキー方式で呼び出す（PROJECT_ID不要）
- 無ければ ADC (Application Default Credentials) で OAuth2 アクセストークンを取得して呼び出す
- ADC が見つからない場合は、gcloud を使って browser login を起動して作成する

.env 例:
  GOOGLE_PROJECT_ID=your-gcp-project-id   # (推奨) 課金/請求先
  GOOGLE_QUOTA_PROJECT_ID=your-billing-project-id  # 任意。未指定なら PROJECT_ID を使う
  DEBUG_TOKEN_PREFIX=1                   # 任意。token 先頭を表示

前提:
  pip install google-auth requests python-dotenv
"""

# 環境変数/.env を読み込み
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
QUOTA_PROJECT_ID = os.getenv("GOOGLE_QUOTA_PROJECT_ID") or PROJECT_ID
DEBUG_TOKEN_PREFIX = os.getenv("DEBUG_TOKEN_PREFIX", "").lower() in ("1", "true", "yes", "on")

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

TRANSLATE_ENDPOINT_V2 = "https://translation.googleapis.com/language/translate/v2"



def _find_gcloud_exe() -> str | None:
    """gcloud 実行ファイルを探す。

    - PATH
    - Windows 既定インストール先
    """
    exe = shutil.which("gcloud")
    if exe:
        return exe

    candidates = [
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Google",
            "Cloud SDK",
            "google-cloud-sdk",
            "bin",
            "gcloud.cmd",
        ),
        os.path.join(
            os.environ.get("ProgramFiles", ""),
            "Google",
            "Cloud SDK",
            "google-cloud-sdk",
            "bin",
            "gcloud.cmd",
        ),
        os.path.join(
            os.environ.get("ProgramFiles(x86)", ""),
            "Google",
            "Cloud SDK",
            "google-cloud-sdk",
            "bin",
            "gcloud.cmd",
        ),
    ]

    for p in candidates:
        if p and Path(p).exists():
            return p

    return None


_GCLOUD = _find_gcloud_exe()


def _run_gcloud(args: list[str]) -> None:
    if not _GCLOUD:
        raise RuntimeError(
            "gcloud が見つかりません。\n"
            "ADC を自動でブラウザログインさせるには Google Cloud SDK (gcloud) が必要です。\n"
            "対処:\n"
            "  1) Google Cloud SDK をインストール\n"
            "  2) その後、次を実行してADCを作成\n"
            "     gcloud auth application-default login\n"
            f"     gcloud auth application-default set-quota-project {QUOTA_PROJECT_ID}\n"
            "または gcloud を PATH に通してください。"
        )

    subprocess.run([_GCLOUD, *args], check=True)


def _ensure_adc_login_interactive() -> None:
    """ADCが無い場合に、ブラウザログインを起動してADCを作る。"""
    if not QUOTA_PROJECT_ID:
        raise RuntimeError(
            "ADC (OAuth) を使う場合は GOOGLE_QUOTA_PROJECT_ID または GOOGLE_PROJECT_ID が必要です。\n"
            "APIキー方式を使う場合は GOOGLE_API_KEY を設定してください。"
        )
    _run_gcloud(["auth", "application-default", "login"])
    _run_gcloud(["auth", "application-default", "set-quota-project", QUOTA_PROJECT_ID])


def get_access_token() -> str:
    """ADCからアクセストークンを取得。

    ADCが無ければ gcloud でログインを起動して、成功したら続行する。
    """
    if not QUOTA_PROJECT_ID:
        raise RuntimeError(
            "ADC (OAuth) を使う場合は GOOGLE_QUOTA_PROJECT_ID または GOOGLE_PROJECT_ID が必要です。\n"
            "APIキー方式を使う場合は GOOGLE_API_KEY を設定してください。"
        )
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
    except DefaultCredentialsError:
        _ensure_adc_login_interactive()
        creds, _ = google.auth.default(scopes=SCOPES)

    if hasattr(creds, "with_quota_project"):
        creds = creds.with_quota_project(QUOTA_PROJECT_ID)

    req = Request()
    creds.refresh(req)

    token = getattr(creds, "token", None)
    if not token:
        raise RuntimeError("Failed to obtain access token from ADC.")
    return token


def translate_text(text: str, source: str = "en", target: str = "ja") -> str:
    """Google Translate v2 を APIキー優先で呼び出す。
    - GOOGLE_API_KEY があれば APIキー
    - 無ければ ADC(OAuth)
    """

    body = {
        "q": [text],
        "source": source,
        "target": target,
        "format": "html",
    }

    # ===== APIキー優先 =====
    if GOOGLE_API_KEY:
        params = {
            "key": GOOGLE_API_KEY,
        }
        resp = requests.post(
            TRANSLATE_ENDPOINT_V2,
            params=params,
            data=json.dumps(body),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
    else:
        # ===== ADC (OAuth) =====
        access_token = get_access_token()

        if DEBUG_TOKEN_PREFIX:
            print(f"Access Token Prefix: {access_token[:20]}...")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        if QUOTA_PROJECT_ID:
            headers["x-goog-user-project"] = QUOTA_PROJECT_ID

        resp = requests.post(
            TRANSLATE_ENDPOINT_V2,
            headers=headers,
            data=json.dumps(body),
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Translate API error: {resp.status_code} {resp.text}")

    data = resp.json()
    return data["data"]["translations"][0]["translatedText"]


def translate_texts(texts: list[str], source: str = "en", target: str = "ja") -> list[str]:
    if not texts:
        return []

    body = {
        "q": list(texts),
        "source": source,
        "target": target,
        "format": "html",
    }

    if GOOGLE_API_KEY:
        params = {
            "key": GOOGLE_API_KEY,
        }
        resp = requests.post(
            TRANSLATE_ENDPOINT_V2,
            params=params,
            data=json.dumps(body),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
    else:
        access_token = get_access_token()

        if DEBUG_TOKEN_PREFIX:
            print(f"Access Token Prefix: {access_token[:20]}...")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        if QUOTA_PROJECT_ID:
            headers["x-goog-user-project"] = QUOTA_PROJECT_ID

        resp = requests.post(
            TRANSLATE_ENDPOINT_V2,
            headers=headers,
            data=json.dumps(body),
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Translate API error: {resp.status_code} {resp.text}")

    data = resp.json()
    translations = data.get("data", {}).get("translations", [])
    return [item.get("translatedText", "") for item in translations]

if __name__ == "__main__":
    html_text = "google:<p>Hello <strong>ParaParaTrans</strong>!</p>"
    print(translate_text(html_text))
