import os
import json
import requests
from dotenv import load_dotenv

"""Ollama ローカル LLM 翻訳エンジン。

API キー不要でローカル LLM を使って翻訳する。
Ollama の REST API (http://localhost:11434) を利用。

.env 例:
  TRANSLATOR=ollama
  OLLAMA_MODEL=gemma3:12b        # 使用するモデル名（デフォルト: gemma3:12b）
  OLLAMA_BASE_URL=http://localhost:11434  # Ollama サーバーの URL（デフォルト: localhost）

前提:
  - Ollama がインストール・起動されていること
  - 翻訳に使うモデルが pull 済みであること（例: ollama pull gemma3:12b）
"""

load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:12b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# 言語コード → 言語名のマッピング
_LANG_NAMES = {
    "EN": "English",
    "JA": "Japanese",
    "ZH": "Chinese",
    "KO": "Korean",
    "FR": "French",
    "DE": "German",
    "ES": "Spanish",
    "PT": "Portuguese",
    "IT": "Italian",
    "RU": "Russian",
    "AR": "Arabic",
    "NL": "Dutch",
    "PL": "Polish",
    "SV": "Swedish",
    "DA": "Danish",
    "FI": "Finnish",
    "NO": "Norwegian",
}


def _lang_name(code: str) -> str:
    """言語コードを言語名に変換する。"""
    return _LANG_NAMES.get(code.upper(), code)


def _build_prompt(text: str, source: str, target: str) -> str:
    """翻訳プロンプトを生成する。"""
    src_name = _lang_name(source)
    tgt_name = _lang_name(target)
    return (
        f"Translate the following {src_name} text to {tgt_name}. "
        "Preserve all HTML tags exactly as they are. "
        "Output ONLY the translated text, nothing else. "
        "Do not add explanations, notes, or extra formatting.\n\n"
        f"{text}"
    )


def _call_ollama(prompt: str) -> str:
    """Ollama API を呼び出してレスポンスを取得する。"""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=120,
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Ollama サーバーに接続できません ({OLLAMA_BASE_URL})。\n"
            "Ollama が起動していることを確認してください。\n"
            "  - インストール: https://ollama.com\n"
            f"  - モデル取得: ollama pull {OLLAMA_MODEL}\n"
            "  - 起動確認: ollama list"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            "Ollama サーバーからの応答がタイムアウトしました。\n"
            "モデルの初回ロードには時間がかかることがあります。再度お試しください。"
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Ollama API error: {resp.status_code} {resp.text}")

    data = resp.json()
    return data.get("response", "").strip()


def translate_text(text: str, source: str = "EN", target: str = "JA") -> str:
    """Ollama を使って単一テキストを翻訳する。"""
    if not text or not text.strip():
        return text

    prompt = _build_prompt(text, source, target)
    return _call_ollama(prompt)


def translate_texts(texts: list[str], source: str = "EN", target: str = "JA") -> list[str]:
    """Ollama を使って複数テキストを一括翻訳する。"""
    if not texts:
        return []

    results = []
    for text in texts:
        if not text or not str(text).strip():
            results.append(text)
        else:
            result = translate_text(str(text), source, target)
            results.append(result)
    return results


if __name__ == "__main__":
    html_text = "ollama:<p>Hello <strong>ParaParaTrans</strong>!</p>"
    translated_text = translate_text(html_text)
    print(translated_text)
