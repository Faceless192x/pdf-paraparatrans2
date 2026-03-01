# URLブックガイド

このページは、Webページを翻訳対象にする **URLブック** の使い方をまとめたものです。

## 1. URLブックとは

URLブックは、PDFの代わりにWebページをページ単位で取り込み、段落抽出・辞書置換・翻訳・推敲まで行うための機能です。

## 2. 最短手順

1. 一覧画面で **「URLを追加」** を押す
2. 取り込み開始URLを入力してURLブックを作成
3. 詳細画面のURLプレビューで対象ページを表示
4. **「取込」** で現在ページを取り込む
5. 必要に応じて **「クロール」** で同一サイト内のページを追加

## 3. 取り込み方法

- 1ページ追加: URLを指定してページを追加
- URL取込: URLを指定して本文HTMLを取得し取り込み
- HTML直接取込: 取得済みHTMLを直接取り込み
- クロール: 開始URLから同一サイト内リンクをたどって追加

## 4. サイトルール（抽出の安定化）

詳細画面の **「ルール」** から、ドメイン単位で抽出ルールを保存できます。

- 対象範囲（include）
- 追加要素（add）
- 除外要素（exclude）

保存先は `config/url_site_profiles.json` です。

## 5. ブラウザ拡張（Chrome / Edge）

ParaParaTrans のプロジェクトURL:
- https://github.com/runequest77/pdf-paraparatrans2

ParaParaTrans は、PDF/URL文書を段落単位で管理し、辞書置換・翻訳・推敲を同じ画面で進めるためのローカルアプリです。
このブラウザ拡張は、表示中ページのHTMLを ParaParaTrans に渡して URLブックへ取り込むための連携コンポーネントです。

URLパネルの **「取込」** は、ブラウザ拡張と連携して現在表示中ページのHTMLを取り込みます。

### 拡張の場所

- `tools/chrome_extension_paraparatrans`

### インストール

事前に、アプリの **データ入出力** ダイアログにある **「ブラウザ拡張をダウンロード」** から、
`chrome_extension_paraparatrans.zip` を取得して展開しておくとスムーズです。

1. `chrome://extensions`（または `edge://extensions`）を開く
2. **デベロッパーモード** をON
3. **パッケージ化されていない拡張機能を読み込む** を押す
4. `tools/chrome_extension_paraparatrans` フォルダを選択

### 使い方

1. アプリを起動（`python pdf-paraparatrans.py`）
2. URLブックの詳細画面を開く
3. （初回）拡張ポップアップで `ParaParaTrans URL` を設定（例: `http://localhost:5077`）
4. URLプレビューで対象ページを開く
5. 詳細画面の **「取込」** を押す

右クリックメニューからの取込や、ルール登録（この階層以下/要素追加/要素除外）にも対応しています。

### 補足

- 同じURLが既にある場合は、再取込（上書き）として扱われます。
- `Book name` 未設定時は、現在開いているURLブックが対象になります。
- 「ブラウザ拡張が利用できないか、応答がありません」と表示された場合は、拡張の有効化状態を確認してください。

## 6. 関連資料

- 拡張機能の詳細README: [tools/chrome_extension_paraparatrans/README.md](../tools/chrome_extension_paraparatrans/README.md)
