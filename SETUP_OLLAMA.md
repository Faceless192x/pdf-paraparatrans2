# Ollama（ローカル LLM）のセットアップ

このドキュメントでは、PDF ParaParaTrans 2 で Ollama（ローカル LLM）を翻訳エンジンとして使うためのセットアップ手順をまとめます。

## Ollama とは

[Ollama](https://ollama.com) はローカル環境で大規模言語モデル（LLM）を実行するためのオープンソースツールです。

**メリット**:
- **API キー不要** — アカウント登録やクレジットカードは一切不要
- **完全オフライン** — モデルダウンロード後はインターネット接続不要
- **完全無料** — API 課金なし、何度でも翻訳可能
- **プライバシー** — テキストデータが外部に一切送信されない

**注意点**:
- 翻訳品質は Google Translate や DeepL と比較すると、モデルやテキストの種類によって差があります
- ハードウェアリソース（メモリ・CPU/GPU）を使用します
- 初回のモデルロードには時間がかかることがあります

## 前提条件

- **メモリ**: 8GB 以上（16GB 推奨）
- **ディスク**: モデルサイズ分の空き容量（数GB〜数十GB）
- **GPU（任意）**: NVIDIA/AMD GPU があれば高速に動作。CPU のみでも利用可能

## 手順

### 1. Ollama のインストール

[ollama.com](https://ollama.com) からお使いの OS 用のインストーラーをダウンロードしてインストールします。

- **Windows**: インストーラーを実行（バックグラウンドサービスとして起動）
- **macOS**: `.dmg` をダウンロードしてインストール
- **Linux**: `curl -fsSL https://ollama.com/install.sh | sh`

### 2. 翻訳用モデルの取得

ターミナル（コマンドプロンプト）で以下を実行します:

```bash
ollama pull gemma3:12b
```

> **モデルの選択について**
>
> - `gemma3:12b` — Google の Gemma 3（12B パラメータ）。多言語翻訳で高い品質。推奨
> - `gemma3:4b` — 軽量版。メモリが限られる環境向け
> - `llama3.1:8b` — Meta の Llama 3.1。英日翻訳で良好な品質
> - `mistral` — Mistral AI のモデル。欧州言語に強い
>
> モデル名は [Ollama Library](https://ollama.com/library) で確認できます。

### 3. Ollama の起動確認

```bash
ollama list
```

取得済みモデルの一覧が表示されれば OK です。

### 4. `.env` の設定

`.env.example` を `.env` にコピー（または既存の `.env` を編集）して、以下を設定します:

```env
TRANSLATOR=ollama

# （任意）使用するモデルを変更する場合
# OLLAMA_MODEL=gemma3:12b

# （任意）Ollama サーバーが別のアドレスで動いている場合
# OLLAMA_BASE_URL=http://localhost:11434
```

### 5. 起動して動作確認

```bash
python pdf-paraparatrans.py
```

起動ログに `Using Ollama translator.` と表示されれば設定完了です。

`http://localhost:5077/` を開いて翻訳をお試しください。

## トラブルシューティング

### 「Ollama サーバーに接続できません」と表示される

- Ollama が起動しているか確認: `ollama list`
- Windows の場合、タスクトレイに Ollama アイコンがあるか確認
- `OLLAMA_BASE_URL` が正しいか確認（デフォルト: `http://localhost:11434`）

### 翻訳が遅い

- GPU が利用されているか確認（NVIDIA: `nvidia-smi` コマンド）
- より軽量なモデル（`gemma3:4b` 等）に変更
- `OLLAMA_MODEL` を `.env` で変更可能

### モデルを変更したい

`.env` の `OLLAMA_MODEL` を変更して、アプリを再起動してください:

```env
OLLAMA_MODEL=llama3.1:8b
```

事前に `ollama pull llama3.1:8b` でモデルを取得しておく必要があります。

## Docker での利用

Docker Compose で ParaParaTrans と Ollama を同時に起動できます:

```yaml
services:
  paraparatrans:
    build: .
    ports:
      - "5077:5077"
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    environment:
      - TRANSLATOR=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
volumes:
  ollama_data:
```

## 他の翻訳エンジンとの比較

| 項目 | Ollama | Google Translate | DeepL |
|------|--------|-----------------|-------|
| API キー | **不要** | 要（GCP） | 要（DeepL） |
| 料金 | **無料** | 従量課金 | 従量課金/月額 |
| オフライン | **対応** | 不可 | 不可 |
| プライバシー | **完全ローカル** | クラウド送信 | クラウド送信 |
| 翻訳品質 | モデル依存 | 高品質 | 高品質 |
| 速度 | ハードウェア依存 | 高速 | 高速 |
| セットアップ | Ollama インストール | GCP 設定 | アカウント作成 |
