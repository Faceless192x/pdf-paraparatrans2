from __future__ import annotations

import os
from typing import Callable, Tuple

from flask import Blueprint, current_app, jsonify, render_template, request

from app.services.dict_service import DictService


def create_dict_blueprint(
    dict_service: DictService,
    get_paths: Callable[[str], Tuple[str, str]],
    get_resource_path: Callable[[str], str],
    translate_dict_entries: Callable,
    dict_create: Callable,
) -> Blueprint:
    """辞書管理 API の Blueprint を生成して返す。

    依存オブジェクトはファクトリ引数で受け取り、クロージャ経由でルートハンドラに渡す。
    """

    bp = Blueprint("dict", __name__)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    @bp.route("/dict_maintenance")
    def dict_maintenance_page():
        return render_template("dict_maintenance.html")

    # ------------------------------------------------------------------
    # /api/dict/* — 辞書 CRUD / 選択 / 翻訳
    # ------------------------------------------------------------------

    @bp.route("/api/dict/list", methods=["GET"])
    def dict_list_api():
        dict_path = request.args.get("dict_path") or ""
        try:
            entries, dict_rel = dict_service.list_entries(dict_path or None)
        except ValueError:
            return jsonify({"status": "error", "message": "dict_path が不正です"}), 400
        return jsonify({"status": "ok", "entries": entries, "dict_path": dict_rel}), 200

    @bp.route("/api/dict/bulk_update", methods=["POST"])
    def dict_bulk_update_api():
        payload = request.get_json(silent=True) or {}
        entries = payload.get("entries")
        dict_path = payload.get("dict_path") or ""
        if not isinstance(entries, list):
            return jsonify({"status": "error", "message": "entries が配列ではありません"}), 400
        try:
            count = dict_service.bulk_update(entries, dict_path or None)
            return jsonify({"status": "ok", "count": count}), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            current_app.logger.error(f"辞書ファイル書き込みエラー: {str(e)}")
            return jsonify({"status": "error", "message": f"辞書ファイル書き込みエラー: {str(e)}"}), 500

    @bp.route("/api/dict/catalog", methods=["GET"])
    def dict_catalog_api():
        all_dicts, default_path = dict_service.catalog()
        return jsonify({"status": "ok", "dicts": all_dicts, "default_path": default_path}), 200

    @bp.route("/api/dict/compare", methods=["GET"])
    def dict_compare_api():
        dict_path = request.args.get("dict_path") or ""
        if not dict_path:
            return jsonify({"status": "error", "message": "dict_path が必要です"}), 400
        try:
            entries, dict_rel = dict_service.compare(dict_path)
        except ValueError:
            return jsonify({"status": "error", "message": "dict_path が不正です"}), 400
        return jsonify({"status": "ok", "entries": entries, "dict_path": dict_rel}), 200

    @bp.route("/api/dict/auto_translate", methods=["POST"])
    def dict_auto_translate_api():
        payload = request.get_json(silent=True) or {}
        dict_path = payload.get("dict_path") or ""
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return jsonify({"status": "error", "message": "entries が配列ではありません"}), 400
        try:
            dict_rel, count = dict_service.auto_translate_selected(
                dict_path or None,
                entries,
                translate_dict_entries,
            )
        except ValueError:
            return jsonify({"status": "error", "message": "dict_path または entries が不正です"}), 400
        except Exception as e:
            current_app.logger.error(f"辞書自動翻訳エラー: {str(e)}")
            return jsonify({"status": "error", "message": f"辞書自動翻訳エラー: {str(e)}"}), 500
        return jsonify({"status": "ok", "message": f"自動翻訳を実行しました ({count} 件)", "dict_path": dict_rel, "count": count}), 200

    @bp.route("/api/dict/create_book/<path:pdf_name>", methods=["POST"])
    def dict_create_book_api(pdf_name):
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404
        common_words_path = get_resource_path(os.path.join("modules", "english_common_words.txt"))
        try:
            book_rel = dict_service.create_book_dict(pdf_name, json_path, common_words_path, dict_create)
        except Exception as e:
            return jsonify({"status": "error", "message": f"辞書生成エラー: {str(e)}"}), 500
        return jsonify({"status": "ok", "dict_path": book_rel}), 200

    @bp.route("/api/dict/transfer", methods=["POST"])
    def dict_transfer_api():
        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "").lower()
        source_path = payload.get("source_path") or ""
        target_path = payload.get("target_path") or ""
        entries = payload.get("entries")
        try:
            dict_service.transfer(action, source_path, target_path, entries)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            current_app.logger.error(f"辞書ファイル書き込みエラー: {str(e)}")
            return jsonify({"status": "error", "message": f"辞書ファイル書き込みエラー: {str(e)}"}), 500
        return jsonify({"status": "ok", "message": "更新しました"}), 200

    @bp.route("/api/dict/selection/<path:pdf_name>", methods=["GET"])
    def dict_selection_get_api(pdf_name):
        config_dicts, book_dict, selected = dict_service.selection_get(pdf_name)
        return jsonify(
            {
                "status": "ok",
                "config_dicts": config_dicts,
                "book_dict": book_dict,
                "selected_paths": selected,
            }
        ), 200

    @bp.route("/api/dict/selection/<path:pdf_name>", methods=["POST"])
    def dict_selection_save_api(pdf_name):
        payload = request.get_json(silent=True) or {}
        dict_paths = payload.get("dict_paths")
        if not isinstance(dict_paths, list):
            return jsonify({"status": "error", "message": "dict_paths が配列ではありません"}), 400
        selected = dict_service.selection_save(pdf_name, dict_paths)
        return jsonify({"status": "ok", "selected_paths": selected}), 200

    @bp.route("/api/dict/search", methods=["POST"])
    def dict_search_api():
        data = request.get_json() or {}
        word = data.get("word")
        pdf_name = data.get("pdf_name")
        if not word:
            return jsonify({"status": "error", "message": "単語が指定されていません"}), 400
        found_entry = dict_service.search(word, pdf_name)
        if found_entry:
            return jsonify({
                "status": "ok",
                "found": True,
                "original_word": found_entry[0],
                "translated_word": found_entry[1],
                "entry_status": found_entry[2],
            }), 200
        return jsonify({
            "status": "ok",
            "found": False,
            "original_word": word,
            "translated_word": "",
            "entry_status": 0,
        }), 200

    @bp.route("/api/dict/update", methods=["POST"])
    def dict_update_api():
        data = request.get_json() or {}
        original_word = data.get("original_word")
        translated_word = data.get("translated_word")
        status = data.get("status", 0)
        pdf_name = data.get("pdf_name")
        dict_path = data.get("dict_path")
        if not original_word:
            return jsonify({"status": "error", "message": "原語が指定されていません"}), 400
        if dict_path and not pdf_name:
            return jsonify({"status": "error", "message": "dict_path 指定時は pdf_name が必要です"}), 400
        try:
            dict_service.update(original_word, translated_word, status, pdf_name, dict_path=dict_path)
            current_app.logger.info(f"辞書更新: '{original_word}' -> '{translated_word}' (状態: {status})")
            return jsonify({"status": "ok", "message": "辞書が更新されました"}), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            current_app.logger.error(f"辞書ファイル書き込みエラー: {str(e)}")
            return jsonify({"status": "error", "message": f"辞書ファイル書き込みエラー: {str(e)}"}), 500

    return bp
