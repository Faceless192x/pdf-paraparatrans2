"""AIルーター/ディスパッチャー。

`generate()` はリクエストを適切なプロバイダに振り分けて実行する。
プロバイダは環境変数 `AI_PROVIDER` で選択（デフォルト: ollama）。
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from app.services.ai import registry as _registry_module
from app.services.ai.exceptions import AIProviderNotConfiguredError
from app.services.ai.types import AIRequest, AIResponse

load_dotenv()

_DEFAULT_PROVIDER = os.getenv("AI_PROVIDER", "ollama")


def generate(request: AIRequest, provider_name: str | None = None) -> AIResponse:
    """リクエストをプロバイダに振り分けて実行する。

    Args:
        request: 送信するAIリクエスト。
        provider_name: 使用するプロバイダ名。None の場合は `AI_PROVIDER` 環境変数を使う。

    Returns:
        正規化されたAIレスポンス。

    Raises:
        AIProviderNotConfiguredError: プロバイダが未設定/未登録の場合。
        AIConnectionError: サーバーへの接続失敗。
        AIGenerationError: プロバイダがAPIエラーを返した場合。
    """
    _registry_module._ensure_defaults_registered()

    name = provider_name or _DEFAULT_PROVIDER
    if not name:
        raise AIProviderNotConfiguredError(
            "AIプロバイダが設定されていません。環境変数 AI_PROVIDER を設定してください。"
        )

    provider = _registry_module.get(name)
    return provider.generate(request)
