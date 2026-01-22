# README用スクリーンショット作成メモ

このリポジトリでは、READMEの冒頭に **自作SVG（docs/hero.svg）** を置いています。
実画面スクリーンショットやGIFを追加する場合は、以下の手順が最短です。

## 1) スクショ（静止画）

- 推奨: Windows の「切り取り領域とスケッチ」
  - `Win + Shift + S` → 範囲選択 → 保存
- 画像は `docs/screenshots/` に置く（例: `docs/screenshots/main.png`）

撮ると映えるポイント:
- 左: 目次パネル（表示）
- 中: PDFパネル（段落ハイライトが見える状態）
- 右: 段落パネル（編集UIが開いている状態）

## 2) GIF（短い操作動画）

- 推奨: Windows 11 の「Snipping Tool（録画）」または OBS
- 10〜15秒、以下のいずれかに絞ると伝わりやすいです
  - 目次クリック → 該当段落へスクロール
  - 段落クリック → PDF側がハイライト
  - (自動タグ付け) → 目次が生える

## 3) READMEへの貼り方（例）

- 静止画: `![メイン画面](docs/screenshots/main.png)`
- GIF: `![段落→PDFハイライト](docs/screenshots/highlight.gif)`
