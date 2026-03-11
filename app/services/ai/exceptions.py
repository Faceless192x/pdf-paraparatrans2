"""AI統合レイヤーの例外クラス。

呼び出し側は `except AIError` で一括捕捉できる。
"""


class AIError(RuntimeError):
    """AI統合レイヤーの基底例外。"""


class AIProviderNotConfiguredError(AIError):
    """プロバイダが設定されていない、または利用不可能な場合。"""


class AIConnectionError(AIError):
    """プロバイダサーバーへの接続に失敗した場合。"""


class AIGenerationError(AIError):
    """プロバイダがAPIエラーを返した場合。"""
