"""抽象プロバイダ基底クラス。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.ai.types import AIRequest, AIResponse


class BaseProvider(ABC):
    """すべてのAIプロバイダが実装すべきインターフェース。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """プロバイダ識別子（例: "ollama"）。"""

    @abstractmethod
    def generate(self, request: AIRequest) -> AIResponse:
        """リクエストを送信してレスポンスを返す。

        Args:
            request: 正規化されたAIリクエスト。

        Returns:
            正規化されたAIレスポンス。

        Raises:
            AIConnectionError: サーバーへの接続失敗。
            AIGenerationError: プロバイダがAPIエラーを返した場合。
        """
