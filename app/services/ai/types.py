"""AI統合レイヤーの共通リクエスト/レスポンス型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AIRequest:
    """プロバイダに渡す正規化されたリクエスト。

    Attributes:
        prompt: メインプロンプト文字列。
        images: マルチモーダル用画像バイト列のリスト（PNG推奨）。
        model: 使用モデル名。空文字ならプロバイダのデフォルト値を使う。
        temperature: 生成温度 (0.0〜1.0)。
        task: ルーティング用タスク識別子（例: "table_to_paragraph"）。
        extra: プロバイダ固有の追加パラメータ。
    """

    prompt: str
    images: list[bytes] = field(default_factory=list)
    model: str = ""
    temperature: float = 0.1
    task: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class AIResponse:
    """プロバイダから返される正規化されたレスポンス。

    Attributes:
        text: 生成されたテキスト。
        provider: プロバイダ識別子（例: "ollama"）。
        model: 実際に使われたモデル名。
        elapsed_ms: リクエスト〜レスポンスの経過時間（ミリ秒）。
        raw: プロバイダ固有のレスポンスデータ（デバッグ用）。
    """

    text: str
    provider: str
    model: str
    elapsed_ms: float
    raw: dict = field(default_factory=dict)
