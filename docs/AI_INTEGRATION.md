# AI Integration Foundation — 設計書

## なぜ共通AI統合レイヤーが必要か

翻訳エンジン（`modules/api_translate_*.py`）はすでにOllamaなどのLLMを使っているが、
今後は **翻訳以外の生成AIワークフロー**（表→段落化、画像生成、文書変換など）を追加する想定がある。
そのたびに個別実装を増やすと、プロバイダ切り替えや設定管理が分散してしまう。

共通レイヤーを設けることで：

- プロバイダ（Ollama, OpenAI など）の差異を1ヶ所で吸収できる
- タスク実装者はHTTPやモデルの差異を気にせずプロンプトに集中できる
- 設定は環境変数に一本化され、未設定でも安全に動作する

---

## ファイルレイアウト

```
app/services/ai/
├── __init__.py          # 公開API (generate / get_router)
├── types.py             # 共通リクエスト/レスポンス型
├── exceptions.py        # 例外クラス
├── providers/
│   ├── __init__.py
│   ├── base.py          # 抽象プロバイダ
│   └── ollama_provider.py  # Ollama実装
├── registry.py          # プロバイダ登録・取得
├── router.py            # タスク→プロバイダ振り分け
└── tasks/
    ├── __init__.py
    └── table_to_paragraph.py  # 表→段落タスクビルダー
```

---

## コアコンセプト

### 1. リクエスト/レスポンス正規化

`types.py` に `AIRequest` と `AIResponse` の dataclass を定義する。
すべてのプロバイダ実装はこの型を入出力として使い、プロバイダ固有の差異を内部で吸収する。

```python
@dataclass
class AIRequest:
    prompt: str
    images: list[bytes] = field(default_factory=list)   # 画像（マルチモーダル用）
    model: str = ""          # 空なら設定値を使う
    temperature: float = 0.1
    task: str = ""           # ルーティング用タスク識別子
    extra: dict = field(default_factory=dict)

@dataclass
class AIResponse:
    text: str
    provider: str
    model: str
    elapsed_ms: float
    raw: dict = field(default_factory=dict)  # プロバイダ固有のレスポンス
```

### 2. プロバイダ抽象化

`providers/base.py` に `BaseProvider` 抽象クラスを定義する。
各プロバイダは `generate(request: AIRequest) -> AIResponse` を実装するだけでよい。

### 3. レジストリとルーター

- `registry.py`: プロバイダ名 → インスタンスの辞書を管理する
- `router.py`: `AIRequest.task` またはデフォルト設定に基づいてプロバイダを選択し `generate()` を呼ぶ

### 4. タスクビルダー

`tasks/` 以下に、特定ユースケース向けのリクエスト生成ヘルパーを置く。
例: `table_to_paragraph.build_request(...)` → `AIRequest` を返す。
タスクビルダーはプロバイダを意識せず、プロンプト構築と入力の正規化だけを担う。

---

## 初期サポートプロバイダ/タスク

| 種別 | 名前 | 備考 |
|------|------|------|
| Provider | `ollama` | ローカルLLM。APIキー不要。既存 `OLLAMA_MODEL` / `OLLAMA_BASE_URL` 変数を流用 |
| Task | `table_to_paragraph` | 表領域画像＋テキストから説明段落を生成 |
| Task | `text_generate` | 汎用テキスト生成（プロンプト直渡し） |

OpenAIなど追加プロバイダは `providers/openai_provider.py` を追加してレジストリに登録するだけで拡張できる。

---

## 将来ワークフローとの接続

| ワークフロー | 対応方法 |
|---|---|
| 表→段落化 | `tasks/table_to_paragraph.py` → `router.generate()` |
| 汎用テキスト生成 | プロンプトを直接 `AIRequest` に渡して `router.generate()` |
| 画像生成 | `AIRequest.task="image_generate"` で画像生成対応プロバイダにルーティング |
| 文書変換 | 新たな `tasks/document_transform.py` を追加 |

---

## 設定（環境変数）

```dotenv
# 生成AIプロバイダ選択（デフォルト: ollama）
AI_PROVIDER=ollama

# Ollamaプロバイダ設定（既存変数を流用）
OLLAMA_MODEL=gemma3:12b
OLLAMA_BASE_URL=http://localhost:11434

# OpenAIプロバイダ設定（将来用）
# AI_PROVIDER=openai
# OPENAI_API_KEY=
# OPENAI_MODEL=gpt-4o-mini
```

未設定の場合はプロバイダを `None` として扱い、呼び出し時に `AIProviderNotConfiguredError` を送出する。
アプリ全体はクラッシュせず、UI側でエラーを表示するだけで済む。

---

## エラーハンドリング方針

- `AIProviderNotConfiguredError`: プロバイダ未設定時
- `AIConnectionError`: ネットワーク到達不可
- `AIGenerationError`: プロバイダが返したAPIエラー

すべて `AIError` 基底クラスを継承するため、呼び出し側は `except AIError` で一括捕捉できる。
