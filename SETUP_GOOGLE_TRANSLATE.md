# Google 翻訳 API のセットアップ

このドキュメントでは、PDF ParaParaTrans 2 で Google 翻訳 API を使うためのセットアップ手順（APIキー方式）をまとめます。

> **注意（2026年1月時点）**
> - 本手順は 2026年1月時点の情報です。Google Cloud 側の画面構成/名称/手順は変更される可能性があります。
> - APIキーの作成・制限・課金設定まわりも更新されることがあるため、うまくいかない場合は公式ドキュメントの案内も併せて確認してください。

※筆者環境で手順を毎回検証できていないため、Google Cloud 側のUI名称等が変わっている可能性があります。

## 前提条件

- Google Cloud Platform (GCP) アカウント
- GCP プロジェクト
	- 通常は「お支払い（請求先）アカウント」の設定も必要です（無料枠/無料試用の有無は時期やアカウント条件で変わります）。

## 手順

### 1. Google Cloud プロジェクトの作成

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセスし、Google アカウントでログインします。
2. プロジェクトを作成します。既存のプロジェクトを使用することもできます。

### 2. 翻訳 API の有効化

1. Google Cloud Console で、左側のメニューから「API とサービス」 > 「ライブラリ」を選択します。
2. 「Cloud Translation API」を検索し、選択します。
3. 「有効にする」ボタンをクリックして、API を有効にします。

### 3. Google API キーの取得（`GOOGLE_API_KEY`）

1. Google Cloud Console で「API とサービス」 > 「認証情報」を開きます。
2. 「認証情報を作成」から「API キー」を作成します。
3. 発行された API キーを控えます（これが `GOOGLE_API_KEY` です）。

#### 推奨: APIキーの制限（漏洩対策）

APIキーが漏れると第三者に使われる可能性があります。可能な範囲で制限をかけてください。

- **アプリケーションの制限**
	- サーバー用途ではないため、IP制限/HTTPリファラ制限が合わないケースがあります。
	- まずは「制限なし」で動作確認 → 可能なら制限を追加、がおすすめです。
- **APIの制限**
	- 「キーを制限」して、Translation API（Cloud Translation API）だけに絞ります。

### 4. `.env` に設定する

リポジトリ直下の `.env_sample` を `.env` にコピーし、キーを貼り付けます。

Codespaces の場合は `.env` を作らず、Codespaces Secrets に `GOOGLE_API_KEY` を登録する運用でもOKです。

例:

```env
TRANSLATOR=google

GOOGLE_API_KEY=xxxxx_your_key_here_xxxxx
DEEPL_AUTH_KEY=
```

### （Codespacesの場合）GitHub UIから Secrets を登録する

Codespaces を使う場合は、`.env` を作らず **Codespaces Secrets** を登録する運用が安全でおすすめです。
登録した値は Codespace 起動時に **環境変数**として渡されます。

#### リポジトリ単位（このリポジトリだけで使う）

1. GitHub のリポジトリ画面を開く
2. **Settings** → **Secrets and variables** → **Codespaces**
3. **New repository secret** を押す
4. 以下を登録
	 - Name: `GOOGLE_API_KEY`
	 - Value: 発行した API キー
	 - （任意）Name: `TRANSLATOR` / Value: `google`

#### 組織（Organization）単位（複数リポジトリで共通利用）

1. Organization の **Settings** → **Secrets and variables** → **Codespaces**
2. **New organization secret** を押す
3. 適用するリポジトリを選択して登録

#### 反映について

- 既に起動中の Codespace がある場合、Secrets 追加後は **Codespace を再起動**すると確実です。
	- 反映しない場合は **Rebuild container** が必要なことがあります。

補足:
- Actions の Secrets（`Settings → Secrets and variables → Actions`）とは別物です。Codespaces で使う場合は **Codespaces** 側に登録してください。

### 5. 起動して動作確認

```bash
python pdf-paraparatrans.py
```

起動ログに出る `http://localhost:5077/` を開いて、翻訳が動けばOKです。



