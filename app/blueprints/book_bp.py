from __future__ import annotations

import datetime
import json
import os
import time
from typing import Callable, Tuple

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from app.services.book_service import BookService


def create_book_blueprint(
    book_service: BookService,
    get_paths: Callable[[str], Tuple[str, str]],
    normalize_pdf_name: Callable[[str], str],
    is_url_book_name: Callable[[str], bool],
    url_book_prefix: str,
    perf_api_enabled: Callable[[], bool],
    perf_log: Callable[[str], None],
) -> Blueprint:
    """ブック閲覧 API の Blueprint を生成して返す。

    依存オブジェクトはファクトリ引数で受け取り、クロージャ経由でルートハンドラに渡す。
    """

    bp = Blueprint("book", __name__)

    # ------------------------------------------------------------------
    # /detail/<path:pdf_name> — 詳細ビュー
    # ------------------------------------------------------------------

    @bp.route("/detail/<path:pdf_name>")
    @bp.route("/detail/<path:pdf_name>/<int:page_number>")
    def detail(pdf_name, page_number=1):
        normalized_pdf_name = normalize_pdf_name(pdf_name)
        if not normalized_pdf_name:
            return "pdf_name が不正です", 400

        pdf_name = normalized_pdf_name
        is_url_book = is_url_book_name(pdf_name)
        book_type = "url" if is_url_book else "pdf"
        if is_url_book:
            book_rel = pdf_name.removeprefix(url_book_prefix)
            current_dir = os.path.dirname(book_rel).replace("\\", "/")
        else:
            current_dir = os.path.dirname(pdf_name).replace("\\", "/")
        index_dir = current_dir if current_dir else None
        pdf_path, json_path = get_paths(pdf_name)

        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
            if isinstance(book_data, dict) and book_type == "url":
                book_data.setdefault("source_type", "url")
        else:
            if is_url_book:
                return "URLブックが存在しません", 404
            book_data = {
                "src_filename": pdf_name,
                "title": pdf_name,
                "styles": {},
                "trans_status_counts": {"pending": 0, "auto": 0, "manual": 0, "fixed": 0},
                "pages": []
            }

        updated_date = ""
        if os.path.exists(json_path):
            updated_date = datetime.datetime.fromtimestamp(os.path.getmtime(json_path)).strftime("%Y/%m/%d")
        elif os.path.exists(pdf_path):
            updated_date = datetime.datetime.fromtimestamp(os.path.getmtime(pdf_path)).strftime("%Y/%m/%d")

        return render_template(
            "detail.html",
            pdf_name=pdf_name,
            page_number=page_number,
            book_data=book_data,
            updated_date=updated_date,
            index_dir=index_dir,
            book_type=book_type,
        )

    # ------------------------------------------------------------------
    # /api/book_data/<path:pdf_name> — book_data 全体取得
    # ------------------------------------------------------------------

    @bp.route("/api/book_data/<path:pdf_name>")
    def get_book_data(pdf_name):
        book_data = book_service.get_book_data(pdf_name)
        if book_data is None:
            return jsonify({"status": "ok", "message": "JSONが存在しません"}), 206
        return jsonify(book_data)

    # ------------------------------------------------------------------
    # /api/book_meta/<path:pdf_name> — メタ情報のみ取得
    # ------------------------------------------------------------------

    @bp.route("/api/book_meta/<path:pdf_name>")
    def get_book_meta(pdf_name):
        meta, _ = book_service.get_book_meta(pdf_name)
        if meta is None:
            return jsonify({"status": "ok", "message": "JSONが存在しません"}), 206
        return jsonify({"status": "ok", "meta": meta})

    # ------------------------------------------------------------------
    # /api/update_last_page/<path:pdf_name> — 最終ページ番号保存
    # ------------------------------------------------------------------

    @bp.route("/api/update_last_page/<path:pdf_name>", methods=["POST"])
    def update_last_page_api(pdf_name):
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

        data = request.get_json(silent=True) or {}
        page_number = data.get("page_number")
        try:
            page_number = int(page_number)
        except Exception:
            return jsonify({"status": "error", "message": "page_number が不正です"}), 400

        if page_number < 1:
            return jsonify({"status": "error", "message": "page_number は1以上で指定してください"}), 400

        try:
            result = book_service.update_last_page(pdf_name, json_path, page_number)
            return jsonify({"status": "ok", **result}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"最終ページ保存中にエラーが発生しました: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /api/book_toc/<path:pdf_name> — 目次（見出し）取得
    # ------------------------------------------------------------------

    @bp.route("/api/book_toc/<path:pdf_name>")
    def get_book_toc(pdf_name):
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

        try:
            toc, cached = book_service.get_book_toc(pdf_name, json_path)
        except Exception as e:
            current_app.logger.exception("book_toc failed")
            return jsonify({"status": "error", "message": f"目次取得エラー: {str(e)}"}), 500

        return jsonify({"status": "ok", "toc": toc, "cached": cached})

    # ------------------------------------------------------------------
    # /api/book_page/<path:pdf_name>/<int:page_number> — 指定ページ取得
    # ------------------------------------------------------------------

    @bp.route("/api/book_page/<path:pdf_name>/<int:page_number>")
    def get_book_page(pdf_name, page_number: int):
        t0 = time.perf_counter()
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

        json_size = None
        try:
            json_size = os.path.getsize(json_path)
        except Exception:
            pass

        t_load_start = time.perf_counter()
        book_data, page = book_service.get_book_page(json_path, page_number)
        t_load_end = time.perf_counter()

        if page is None:
            return jsonify({"status": "error", "message": f"ページが存在しません: {page_number}"}), 404

        t1 = time.perf_counter()
        if perf_api_enabled():
            size_kb = (json_size / 1024.0) if isinstance(json_size, (int, float)) else None
            size_note = f", json_kb={size_kb:.1f}" if size_kb is not None else ""
            perf_log(
                f"[perf] book_page page={page_number} load_json={(t_load_end - t_load_start)*1000:.1f} ms "
                f"total={(t1 - t0)*1000:.1f} ms"
                f"{size_note}"
            )

        response = jsonify(
            {
                "status": "ok",
                "page_key": str(page_number),
                "page": page,
                "trans_status_counts": book_data.get("trans_status_counts"),
                "page_count": book_data.get("page_count"),
                "title": book_data.get("title"),
            }
        )

        if perf_api_enabled():
            load_ms = (t_load_end - t_load_start) * 1000.0
            total_ms = (t1 - t0) * 1000.0
            response.headers["Server-Timing"] = (
                f"load_json;dur={load_ms:.1f}, "
                f"total;dur={total_ms:.1f}"
            )

        return response

    # ------------------------------------------------------------------
    # /api/search/<path:pdf_name> — 全文検索
    # ------------------------------------------------------------------

    @bp.route("/api/search/<path:pdf_name>")
    def search_api(pdf_name: str):
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

        query = (request.args.get("q") or "").strip()
        try:
            limit = int(request.args.get("limit") or 200)
        except Exception:
            limit = 200
        limit = max(1, min(limit, 2000))

        try:
            results = book_service.search(json_path, query, limit=limit)
        except Exception as e:
            current_app.logger.exception("search failed")
            return jsonify({"status": "error", "message": f"検索エラー: {str(e)}"}), 500

        return jsonify({"status": "ok", "query": query, "count": len(results), "results": results})

    # ------------------------------------------------------------------
    # /api/extract_paragraphs/<path:pdf_name> — パラグラフ抽出
    # ------------------------------------------------------------------

    @bp.route("/api/extract_paragraphs/<path:pdf_name>", methods=["POST"])
    def create_book_data_api(pdf_name):
        pdf_path, json_path = get_paths(pdf_name)
        data = request.get_json(silent=True) or {}
        current_page = data.get("current_page")

        try:
            message = book_service.extract_paragraphs(pdf_name, pdf_path, json_path, current_page)
            return jsonify({"status": "ok", "message": message}), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            current_app.logger.error(f"extract_paragraphs error: {str(e)}")
            return jsonify({"status": "error", "message": f"パラグラフ抽出エラー: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /api/reload_book_data/<path:pdf_name> — book_data 再取得
    # ------------------------------------------------------------------

    @bp.route("/api/reload_book_data/<path:pdf_name>", methods=["GET"])
    def reload_book_data_api(pdf_name):
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404
        book_data = book_service.reload_book_data(json_path)
        return jsonify(book_data), 200

    # ------------------------------------------------------------------
    # /pdf_view/<path:pdf_name> — PDF ファイル配信
    # ------------------------------------------------------------------

    @bp.route("/pdf_view/<path:pdf_name>")
    def pdf_view(pdf_name):
        try:
            pdf_path = book_service.get_pdf_path(pdf_name)
        except FileNotFoundError:
            current_app.logger.error(f"File not found: {pdf_name}")
            return "PDFファイルが見つかりません", 404

        resp = send_file(pdf_path, as_attachment=False, conditional=True)
        try:
            resp.cache_control.public = True
            resp.cache_control.max_age = 3600
        except Exception:
            pass
        return resp

    # ------------------------------------------------------------------
    # /pdf_view/<path:pdf_name>/<int:page_number> — 指定ページを PDF として配信
    # ------------------------------------------------------------------

    @bp.route("/pdf_view/<path:pdf_name>/<int:page_number>")
    def pdf_view_page(pdf_name, page_number):
        try:
            output, safe_name = book_service.get_pdf_page_bytes(pdf_name, page_number)
        except FileNotFoundError:
            current_app.logger.error(f"File not found: {pdf_name}")
            return "PDFファイルが見つかりません", 404
        except ValueError as e:
            return str(e), 404
        return send_file(output, download_name=f"{safe_name}_page_{page_number}.pdf", as_attachment=False)

    # ------------------------------------------------------------------
    # /api/book_styles/<path:pdf_name> — スタイル一覧取得
    # ------------------------------------------------------------------

    @bp.route("/api/book_styles/<path:pdf_name>")
    def get_book_styles_api(pdf_name):
        """Get all styles from the book's JSON file."""
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404

        try:
            styles = book_service.get_book_styles(json_path)
            return jsonify({"status": "ok", "styles": styles}), 200
        except Exception as e:
            current_app.logger.error(f"Error getting book styles: {str(e)}")
            return jsonify({"status": "error", "message": f"スタイル取得エラー: {str(e)}"}), 500

    return bp
