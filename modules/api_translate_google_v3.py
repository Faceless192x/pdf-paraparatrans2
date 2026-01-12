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

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
LOCATION = os.getenv("GOOGLE_LOCATION", "us-central1")
GLOSSARY_ID = os.getenv("GOOGLE_GLOSSARY_ID")
QUOTA_PROJECT_ID = os.getenv("GOOGLE_QUOTA_PROJECT_ID") or PROJECT_ID

DEBUG_TOKEN_PREFIX = os.getenv("DEBUG_TOKEN_PREFIX", "").lower() in ("1", "true", "yes", "on")

if not PROJECT_ID:
    raise RuntimeError("GOOGLE_PROJECT_ID is required.")
if not QUOTA_PROJECT_ID:
    raise RuntimeError("GOOGLE_QUOTA_PROJECT_ID (or GOOGLE_PROJECT_ID) is required.")

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

TRANSLATE_ENDPOINT = (
    f"https://translation.googleapis.com/v3/projects/{PROJECT_ID}/locations/{LOCATION}:translateText"
)


def _find_gcloud_exe() -> str | None:
    """
    gcloud 実行ファイルを探す。
    - PATH
    - Windows 既定インストール先
    """
    exe = shutil.which("gcloud")
    if exe:
        return exe

    # よくある既定パス（ユーザー/全体どっちも）
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Cloud SDK", "google-cloud-sdk", "bin", "gcloud.cmd"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Cloud SDK", "google-cloud-sdk", "bin", "gcloud.cmd"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Cloud SDK", "google-cloud-sdk", "bin", "gcloud.cmd"),
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

    # gcloud.cmd を直接叩く（shell=Falseのまま）
    subprocess.run([_GCLOUD, *args], check=True)


def _ensure_adc_login_interactive() -> None:
    """
    ADCが無い場合に、ブラウザログインを起動してADCを作る。
    Translate v3用に quota project も設定する。
    """
    _run_gcloud(["auth", "application-default", "login"])
    _run_gcloud(["auth", "application-default", "set-quota-project", QUOTA_PROJECT_ID])


def get_access_token() -> str:
    """
    ADCからアクセストークンを取得。
    ADCが無ければ gcloud でログインを起動して、成功したら続行する。
    """
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
    access_token = get_access_token()

    if DEBUG_TOKEN_PREFIX:
        print(f"Access Token Prefix: {access_token[:20]}...")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8",
        "x-goog-user-project": QUOTA_PROJECT_ID,
    }

    body = {
        "contents": [text],
        "mimeType": "text/html",
        "sourceLanguageCode": source,
        "targetLanguageCode": target,
    }

    if GLOSSARY_ID:
        glossary_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/glossaries/{GLOSSARY_ID}"
        body["glossaryConfig"] = {"glossary": glossary_name}

    resp = requests.post(TRANSLATE_ENDPOINT, headers=headers, data=json.dumps(body))
    if resp.status_code != 200:
        raise RuntimeError(f"Translate API error: {resp.status_code} {resp.text}")

    data = resp.json()
    if "glossaryTranslations" in data and data["glossaryTranslations"]:
        return data["glossaryTranslations"][0]["translatedText"]
    return data["translations"][0]["translatedText"]


if __name__ == "__main__":
    html_text = "google:<p>Hello <strong>ParaParaTrans</strong>!</p>"
    print(translate_text(html_text))
