# Google 翻訳 API v3（上級者向け / Glossary(Grossary) 対応）のセットアップ

このドキュメントでは、PDF ParaParaTrans 2 で **Google 翻訳 API v3** を使うためのセットアップ手順をまとめます。

> **注意（2026年1月時点）**
> - 本手順は 2026年1月時点の情報です。Google Cloud 側の画面構成/名称/手順は変更される可能性があります。
> - `gcloud` / ADC / 課金 / Glossary 周辺の要件は更新されることがあるため、うまくいかない場合は公式ドキュメントの案内も併せて確認してください。

- これは **上級者向け** です（GCPプロジェクト / 課金 / 認証設定などが必要）。
- **Glossary(Grossary) を使う予定がない場合は不要** です。
  - 通常は [SETUP_GOOGLE_TRANSLATE.md](SETUP_GOOGLE_TRANSLATE.md) の **APIキー方式**（`GOOGLE_API_KEY`）の方が簡単です。

## このツールで必要な環境変数

`TRANSLATOR=google_v3` の場合、コードは以下を参照します。

- `GOOGLE_PROJECT_ID`（必須）: GCPのプロジェクトID
- `GOOGLE_QUOTA_PROJECT_ID`（任意）: 課金/クォータ用プロジェクトID（未指定なら `GOOGLE_PROJECT_ID`）
- `GOOGLE_LOCATION`（任意）: 既定 `us-central1`
- `GOOGLE_GLOSSARY_ID`（任意）: Glossary(Grossary) を使う場合のみ指定

`.env` の例:

```env
TRANSLATOR=google_v3

GOOGLE_PROJECT_ID=your-gcp-project-id
GOOGLE_QUOTA_PROJECT_ID=your-gcp-project-id
GOOGLE_LOCATION=us-central1
GOOGLE_GLOSSARY_ID=your_glossary_id
```

## 1. GCP 側の準備

1. Google Cloud Console でプロジェクトを作成（既存でもOK）
2. **Cloud Translation API** を有効化
3. 課金（請求先）を設定

## 2. 認証（ADC: Application Default Credentials）の準備

このツールは、Google 翻訳 API v3 呼び出し用のアクセストークンを **ADC** から取得します。
ADC が無い場合は `gcloud` を使ってブラウザログインを起動します。

1. Google Cloud SDK（`gcloud`）をインストール
2. ターミナルで以下を実行:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_QUOTA_PROJECT_ID
```

- `YOUR_QUOTA_PROJECT_ID` には通常 `GOOGLE_PROJECT_ID` と同じ値を入れてOKです。
- Codespaces ではブラウザログインがやりにくい場合があるため、基本はローカル運用推奨です。

## 3. Glossary(Grossary) の作り方（必要な人だけ）

### 3.1 用語CSVを作る

Glossary は「用語の対訳表」です。まずCSVを作ります。

例（英→日）:

```csv
Bladesharp,ブレードシャープ
Ernalda,エルナルダ
```

- 文字コードはUTF-8推奨
- 1行=1用語（`,` 区切り）

### 3.2 Cloud Storage バケットを作る（重要）

Glossary 作成には、用語CSVを置く **Cloud Storage バケット** が必要です。

- **バケットのリージョンは `GOOGLE_LOCATION` と揃える必要があります。**
- このツールの既定の `GOOGLE_LOCATION` は `us-central1`（北米）です。
  - 迷ったら、Glossary とバケットを **`us-central1` に統一** してください。

### 3.3 CSVをバケットにアップロード

作成したCSV（例: `glossary_en_ja.csv`）を、上のバケットにアップロードします。

### 3.4 Translation の Glossary を作成

Google Cloud Console で以下の流れで作成します（UI名は変更されることがあります）。

1. Cloud Translation（Translation）を開く
2. Glossaries（用語集）を開く
3. Create（作成）
4. **Location を `GOOGLE_LOCATION`（例: `us-central1`）にする**
5. 入力として Cloud Storage 上のCSVを指定
6. Source language: `en` / Target language: `ja`
7. Glossary ID（名前）を設定して作成

作成した Glossary の ID（最後の名前部分）を `.env` の `GOOGLE_GLOSSARY_ID` に設定します。

## 4. 起動して動作確認

```bash
python pdf-paraparatrans.py
```

起動ログに出る `http://localhost:5077/` を開いて、翻訳が動けばOKです。

---

## トラブルシュート

- `gcloud が見つかりません` と出る
  - Google Cloud SDK を入れて `gcloud` にPATHを通してください。
- `GOOGLE_PROJECT_ID is required.` と出る
  - `.env` に `GOOGLE_PROJECT_ID` を設定してください。
- Glossary を指定したらエラーになる
  - `GOOGLE_LOCATION` と Glossary の Location と、CSVを置いたバケットの Location が揃っているか確認してください。
