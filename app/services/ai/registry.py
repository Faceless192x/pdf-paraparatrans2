"""プロバイダレジストリ。

名前とプロバイダインスタンスを管理し、遅延ロードをサポートする。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.ai.exceptions import AIProviderNotConfiguredError

if TYPE_CHECKING:
    from app.services.ai.providers.base import BaseProvider

_registry: dict[str, "BaseProvider"] = {}


def register(provider: "BaseProvider") -> None:
    """プロバイダをレジストリに登録する。"""
    _registry[provider.name] = provider


def get(name: str) -> "BaseProvider":
    """名前でプロバイダを取得する。未登録なら例外を送出。"""
    if name not in _registry:
        raise AIProviderNotConfiguredError(
            f"AIプロバイダ '{name}' が登録されていません。"
        )
    return _registry[name]


def registered_names() -> list[str]:
    """登録済みプロバイダ名の一覧を返す。"""
    return list(_registry.keys())


def ensure_defaults_registered() -> None:
    """デフォルトプロバイダ（Ollama / Gemini）を遅延登録する。"""
    if "ollama" not in _registry:
        from app.services.ai.providers.ollama_provider import OllamaProvider

        register(OllamaProvider())

    if "gemini" not in _registry:
        import os

        if os.getenv("GEMINI_API_KEY"):
            from app.services.ai.providers.gemini_provider import GeminiProvider

            register(GeminiProvider())


# Backwards-compatible private alias
_ensure_defaults_registered = ensure_defaults_registered
