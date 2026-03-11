"""Ollama プロバイダ実装。

設定 (.env):
    OLLAMA_MODEL=gemma3:12b          # 使用モデル（既存変数を流用）
    OLLAMA_BASE_URL=http://localhost:11434
"""

from __future__ import annotations

import base64
import os
import time

import requests
from dotenv import load_dotenv

from app.services.ai.exceptions import AIConnectionError, AIGenerationError
from app.services.ai.providers.base import BaseProvider
from app.services.ai.types import AIRequest, AIResponse

load_dotenv()

_DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:12b")
_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_TIMEOUT = 120


class OllamaProvider(BaseProvider):
    """Ollama ローカルLLMプロバイダ。APIキー不要。"""

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        base_url: str = _BASE_URL,
        timeout: int = _TIMEOUT,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "ollama"

    def generate(self, request: AIRequest) -> AIResponse:
        """Ollama `/api/generate` を呼び出してレスポンスを返す。"""
        model = request.model or self._model
        payload: dict = {
            "model": model,
            "prompt": request.prompt,
            "stream": False,
            "options": {"temperature": request.temperature},
        }

        # マルチモーダル: 画像をBase64エンコードして添付
        if request.images:
            payload["images"] = [
                base64.b64encode(img).decode("ascii") for img in request.images
            ]

        url = f"{self._base_url}/api/generate"
        started = time.perf_counter()
        try:
            resp = requests.post(url, json=payload, timeout=self._timeout)
        except requests.exceptions.ConnectionError as exc:
            raise AIConnectionError(
                f"Ollama サーバーに接続できません ({self._base_url})。\n"
                "Ollama が起動していることを確認してください。"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise AIConnectionError(
                "Ollama サーバーからの応答がタイムアウトしました。"
            ) from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        if resp.status_code != 200:
            raise AIGenerationError(
                f"Ollama API エラー: {resp.status_code} {resp.text}"
            )

        data = resp.json()
        text = data.get("response", "").strip()

        return AIResponse(
            text=text,
            provider=self.name,
            model=model,
            elapsed_ms=elapsed_ms,
            raw=data,
        )
