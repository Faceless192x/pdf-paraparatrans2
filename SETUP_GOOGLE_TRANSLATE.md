# Google 翻訳 API のセットアップ

このドキュメントでは、PDF ParaParaTrans 2 で Google 翻訳 API を使うためのセットアップ手順（APIキー方式）をまとめます。
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

例:

```env
TRANSLATOR=google

GOOGLE_API_KEY=xxxxx_your_key_here_xxxxx
DEEPL_AUTH_KEY=YOUR_DEEPL_AUTH_KEY
```

### 5. 起動して動作確認

```bash
python pdf-paraparatrans.py
```

起動ログに出る `http://localhost:5077/` を開いて、翻訳が動けばOKです。



