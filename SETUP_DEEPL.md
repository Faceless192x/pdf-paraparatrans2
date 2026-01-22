# DeepL API のセットアップ

このドキュメントでは、PDF ParaParaTrans 2 で DeepL API を使うためのセットアップ手順（`DEEPL_AUTH_KEY` の取得と設定）をまとめます。

## 前提条件

- DeepL アカウント
- DeepL API（Free / Pro いずれでも可）
  - 料金や無料枠はプラン/時期で変わります。

## 手順

### 1. DeepL API キー（`DEEPL_AUTH_KEY`）の取得

1. DeepL の「DeepL API」ページからアカウントを作成/ログインします。
2. DeepL API の管理画面（アカウント）で **Authentication Key（認証キー）** を発行/確認します。
3. 表示されたキー文字列を控えます（これが `DEEPL_AUTH_KEY` です）。

補足:
- Free 用/Pro 用でキー種別やエンドポイントが異なる場合がありますが、本ツールは `deepl` Python ライブラリを使っており、通常はキーを設定すれば動作します。

### 2. `.env` に設定する

リポジトリ直下の `.env_sample` を `.env` にコピーして、以下を設定します。

- `TRANSLATOR=deepl`
- `DEEPL_AUTH_KEY=...`

例:

```env
# TRANSLATOR=google
TRANSLATOR=deepl

GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY
DEEPL_AUTH_KEY=xxxxx_your_key_here_xxxxx
```

注意:
- `.env` は秘密情報を含むので、Gitにコミットしないでください。
- Codespaces を使う場合は、Secrets に `DEEPL_AUTH_KEY` を登録してもOKです。

### 3. 起動して動作確認

```bash
python pdf-paraparatrans.py
```

起動ログに出る `http://localhost:5077/` を開いて、翻訳が動けばOKです。
