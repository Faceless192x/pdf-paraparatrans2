# アプリケーションリファクタリング戦略

## 概要

`pdf-paraparatrans.py` は現在 4,700 行超の単一ファイルに 60 以上のルート定義が集中しており、
コードの見通しが悪く、テスト・保守が困難になっています。
このドキュメントは段階的なリファクタリングの進め方をガイドします。

---

## 現在のアーキテクチャ

```
pdf-paraparatrans.py   ← 全ルート + ヘルパー関数 + 初期化コード (約 4,700 行)
app/
  repositories/        ← データアクセス層（一部実装済み）
    dict_repo.py
    json_repo.py
    settings_repo.py
  services/            ← サービス層（一部実装済み）
    dict_service.py
    chunked_upload_service.py
modules/               ← ビジネスロジック（PDF解析・翻訳など）
```

## 目標アーキテクチャ

```
pdf-paraparatrans.py   ← アプリ起動・Blueprints 登録のみ（数十行）
app/
  blueprints/          ← ルートハンドラを機能単位に分割
    dict_bp.py         ← 辞書 API (/api/dict/*)
    book_bp.py         ← ブック閲覧 API (/api/book_data/*, /detail/*)
    paragraph_bp.py    ← 段落編集 API (/api/update_paragraph/*, etc.)
    translate_bp.py    ← 翻訳 API (/api/translate*, /api/paraparatrans/*)
    export_bp.py       ← エクスポート API (/api/export_*, /api/download_*)
    file_mgmt_bp.py    ← ファイル管理 API (/, /api/folder/*, /api/upload_*)
    url_book_bp.py     ← URL ブック API (/api/url_book/*)
    symbol_font_bp.py  ← シンボルフォント API (/api/*symbolfont*)
  repositories/        ← データアクセス層（現状維持）
  services/            ← サービス層（拡張）
modules/               ← ビジネスロジック（現状維持）
```

---

## 推奨する進め方（フェーズ分割）

### フェーズ 1: Blueprint 基盤の構築 ✅（本PRで実施）

**作業内容**
- `app/blueprints/` ディレクトリを作成
- 最もサービス層が整備されている **辞書 API** を Blueprint に移行
  - 対象ルート: `/api/dict/*`（11 本）
  - 依存: `DictService`（既に `app/services/dict_service.py` に存在）
- Blueprint のファクトリ関数パターンを確立し、後続フェーズの雛形にする

**効果**
- 本体ファイルから約 160 行削減
- 依存注入パターンの確立
- テスト容易性の向上

---

### フェーズ 2: シンボルフォント Blueprint の分離 ✅（本PRで実施）

**作業内容**
- `app/services/symbolfont_service.py` を新規作成し、シンボルフォント読み書きロジックを集約
- `app/blueprints/symbol_font_bp.py` を作成し以下を移行
  - `/api/register_symbolfont`
  - `/api/get_registered_symbolfonts`
  - `/api/delete_symbolfont`
  - `/api/update_symbolfont_mappings`
  - `/symbol_fonts_maintenance`
  - `/api/book_fonts/<path:pdf_name>`

**参考**: `modules/parapara_symbolfont_rebuild.py` の再利用を検討

---

### フェーズ 3: ファイル管理 Blueprint の分離

**作業内容**
- `app/services/file_mgmt_service.py` を作成し、フォルダ/PDF 管理ロジックを集約
- `app/blueprints/file_mgmt_bp.py` を作成し以下を移行
  - `/`（一覧画面）
  - `/api/folder/create`, `/api/folder/rename`, `/api/folder/delete`
  - `/api/pdf/move`
  - `/api/upload_pdf`, `/api/upload_pdf_chunk/*`（ChunkedUploadService を活用）
  - `/api/pdf_list`

---

### フェーズ 4: URL ブック Blueprint の分離

**作業内容**
- `app/services/url_book_service.py` を作成し、URL ブックのクロール・インポートロジックを集約
- `app/blueprints/url_book_bp.py` を作成し、`/api/url_book/*` 系 10 本を移行

---

### フェーズ 5: 翻訳 Blueprint の分離

**作業内容**
- `app/blueprints/translate_bp.py` を作成し以下を移行
  - `/api/translate_engine`
  - `/api/translate`
  - `/api/translate_all/<path:pdf_name>`
  - `/api/paraparatrans/<path:pdf_name>`
  - `/api/align_trans_by_src_joined/<path:pdf_name>`

---

### フェーズ 6: エクスポート Blueprint の分離

**作業内容**
- `app/blueprints/export_bp.py` を作成し以下を移行
  - `/api/export_html/*`, `/api/download_html/*`
  - `/api/export_structure/*`, `/api/download_structure/*`
  - `/api/export_text/*`, `/api/download_text/*`
  - `/api/import_structure/*`
  - `/api/download_extension/chrome`

---

### フェーズ 7: 段落管理・タグ付け Blueprint の分離

**作業内容**
- `app/blueprints/paragraph_bp.py` を作成し以下を移行
  - `/api/save_order/*`
  - `/api/update_paragraph/*`, `/api/update_paragraphs/*`, `/api/delete_paragraphs/*`
  - `/api/update_book_info/*`
  - `/api/auto_tagging/*`, `/api/rebuild_src_text/*`
  - `/api/update_block_tags_by_style/*`, `/api/update_block_tags_by_style_y/*`
  - `/api/join_replaced_paragraphs/*`
  - `/api/reextract_table_from_selection/*`, `/api/table_grid_suggest/*`

---

### フェーズ 8: ブック閲覧 Blueprint の分離

**作業内容**
- `app/blueprints/book_bp.py` を作成し以下を移行
  - `/detail/*`, `/pdf_view/*`
  - `/api/book_data/*`, `/api/book_meta/*`, `/api/book_toc/*`, `/api/book_page/*`
  - `/api/book_styles/*`, `/api/book_fonts/*`
  - `/api/update_last_page/*`, `/api/reload_book_data/*`
  - `/api/search/*`
  - `/api/extract_paragraphs/*`

---

### フェーズ 9: アプリケーションファクトリへの移行（任意）

フェーズ 1〜8 が完了した後、さらに進める場合:

- `app/factory.py` に `create_app()` ファクトリ関数を作成
- `pdf-paraparatrans.py` をエントリポイントのみに簡素化
- テストで `create_app(config=TestConfig)` を使った完全分離テストを可能にする

---

## 各フェーズの実施手順（共通）

1. **サービス層の整備**: ロジックが `pdf-paraparatrans.py` に残っている場合は `app/services/` に移動
2. **Blueprint ファイルを作成**: ファクトリ関数パターンで依存を注入
3. **本体に Blueprint を登録**: `app.register_blueprint(...)` を追加
4. **本体から旧ルートを削除**: Blueprint に移行したルート定義を削除
5. **動作確認**: UIスモークテストを実行（`tools/ui_smoke_test.py`）
6. **コミット**: `report_progress` で進捗をコミット

---

## Blueprint ファクトリ関数パターン（依存注入）

各 Blueprint はファクトリ関数で生成し、依存オブジェクトをクロージャ経由で受け取ります。

```python
# app/blueprints/example_bp.py
from flask import Blueprint, jsonify, request

def create_example_blueprint(some_service):
    bp = Blueprint("example", __name__)

    @bp.route("/api/example")
    def example_api():
        result = some_service.do_something()
        return jsonify({"status": "ok", "result": result})

    return bp
```

```python
# pdf-paraparatrans.py（登録側）
from app.blueprints.example_bp import create_example_blueprint

bp_example = create_example_blueprint(some_service)
app.register_blueprint(bp_example)
```

このパターンの利点:
- グローバル変数への依存がなく、テストで差し替えが容易
- Blueprint 同士が疎結合のまま維持される
- `current_app` の乱用を防ぐ

---

## 注意事項

- **既存の動作を壊さない**: 各フェーズで必ずスモークテストを実行してから PR を出す
- **段階的に進める**: 1 フェーズずつ独立した PR にする（レビューしやすさ向上）
- **ヘルパー関数の整理**: `_normalize_pdf_name`, `get_paths` などの共有ヘルパーは
  最終的に `app/utils.py` などに集約する（ただし他フェーズに先行しないこと）
- **modules/ は現状維持**: `modules/` 内のビジネスロジックは今回の対象外
