# DeepL API のセットアップ

このドキュメントでは、PDF ParaParaTrans 2 で DeepL API を使うためのセットアップ手順（`DEEPL_AUTH_KEY` の取得と設定）をまとめます。

> **注意（2026年1月時点）**
> - 本手順は 2026年1月時点の情報です。DeepL 側の画面構成/名称/手順は変更される可能性があります。
> - APIキーの取得方法や無料枠/課金条件が変わることがあるため、うまくいかない場合は DeepL の公式案内も併せて確認してください。

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

リポジトリ直下の `.env.example` を `.env` にコピーして、以下を設定します。

- `TRANSLATOR=deepl`
- `DEEPL_AUTH_KEY=...`

例:

```env
# TRANSLATOR=google
TRANSLATOR=deepl

GOOGLE_API_KEY=
DEEPL_AUTH_KEY=xxxxx_your_key_here_xxxxx
```

注意:
- `.env` は秘密情報を含むので、Gitにコミットしないでください。
- Codespaces を使う場合は、Codespaces Secrets に `DEEPL_AUTH_KEY`（必要なら `TRANSLATOR=deepl`）を登録してもOKです。

### （Codespacesの場合）GitHub UIから Secrets を登録する

Codespaces を使う場合は、`.env` を作らず **Codespaces Secrets** を登録する運用が安全でおすすめです。

#### リポジトリ単位（このリポジトリだけで使う）

1. GitHub のリポジトリ画面を開く
2. **Settings** → **Secrets and variables** → **Codespaces**
3. **New repository secret** を押す
4. 以下を登録
   - Name: `DEEPL_AUTH_KEY`
   - Value: DeepL の Authentication Key
   - （任意）Name: `TRANSLATOR` / Value: `deepl`

#### 組織（Organization）単位（複数リポジトリで共通利用）

1. Organization の **Settings** → **Secrets and variables** → **Codespaces**
2. **New organization secret** を押す
3. 適用するリポジトリを選択して登録

#### 反映について

- 既に起動中の Codespace がある場合、Secrets 追加後は **Codespace を再起動**すると確実です。
  - 反映しない場合は **Rebuild container** が必要なことがあります。

補足:
- Actions の Secrets（`Settings → Secrets and variables → Actions`）とは別物です。Codespaces で使う場合は **Codespaces** 側に登録してください。

### 3. 起動して動作確認

```bash
python pdf-paraparatrans.py
```

起動ログに出る `http://localhost:5077/` を開いて、翻訳が動けばOKです。
