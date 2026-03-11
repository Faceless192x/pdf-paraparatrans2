"""Gemini プロバイダ実装 (Google AI Studio)。

設定 (.env):
    GEMINI_API_KEY=...             # Google AI Studio のAPIキー
    GEMINI_MODEL=gemini-2.0-flash  # 使用モデル（デフォルト）

無料枠:
    - Google AI Studio の無料APIキーで利用可能
    - https://aistudio.google.com/ からキーを取得
    - gemini-2.0-flash / gemini-1.5-flash がおすすめ

マルチモーダル:
    AIRequest.images に PNG バイト列を渡すと画像も送信される。
"""

from __future__ import annotations

import base64
import os
import time

import requests
from dotenv import load_dotenv

from app.services.ai.exceptions import (
    AIConnectionError,
    AIGenerationError,
    AIProviderNotConfiguredError,
)
from app.services.ai.providers.base import BaseProvider
from app.services.ai.types import AIRequest, AIResponse

load_dotenv()

_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
_API_KEY = os.getenv("GEMINI_API_KEY", "")
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_TIMEOUT = 60


class GeminiProvider(BaseProvider):
    """Google Gemini プロバイダ（AI Studio REST API）。"""

    def __init__(
        self,
        api_key: str = _API_KEY,
        model: str = _DEFAULT_MODEL,
        timeout: int = _TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "gemini"

    def generate(self, request: AIRequest) -> AIResponse:
        """Gemini generateContent API を呼び出してレスポンスを返す。"""
        if not self._api_key:
            raise AIProviderNotConfiguredError(
                "GEMINI_API_KEY が設定されていません。\n"
                "https://aistudio.google.com/ からAPIキーを取得して .env に設定してください。"
            )

        model = request.model or self._model
        url = f"{_BASE_URL}/{model}:generateContent?key={self._api_key}"

        # パーツ構築: 画像を先に配置してからテキストプロンプトを追加
        parts: list[dict] = []
        for image_bytes in request.images:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    }
                }
            )
        parts.append({"text": request.prompt})

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": request.temperature},
        }

        started = time.perf_counter()
        try:
            resp = requests.post(url, json=payload, timeout=self._timeout)
        except requests.exceptions.ConnectionError as exc:
            raise AIConnectionError(
                "Gemini API に接続できません。ネットワーク接続を確認してください。"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise AIConnectionError(
                "Gemini API からの応答がタイムアウトしました。"
            ) from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        if resp.status_code != 200:
            raise AIGenerationError(
                f"Gemini API エラー: {resp.status_code}\n{resp.text}"
            )

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as exc:
            raise AIGenerationError(
                f"Gemini API レスポンスの解析に失敗しました: {data}"
            ) from exc

        return AIResponse(
            text=text,
            provider=self.name,
            model=model,
            elapsed_ms=elapsed_ms,
            raw=data,
        )
