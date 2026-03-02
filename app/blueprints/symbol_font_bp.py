from __future__ import annotations

import os
from typing import Callable, Tuple

from flask import Blueprint, current_app, jsonify, render_template, request

from app.services.symbolfont_service import SymbolFontService


def create_symbol_font_blueprint(
    symbolfont_service: SymbolFontService,
    get_paths: Callable[[str], Tuple[str, str]],
) -> Blueprint:
    """シンボルフォント管理 API の Blueprint を生成して返す。

    依存オブジェクトはファクトリ引数で受け取り、クロージャ経由でルートハンドラに渡す。
    """

    bp = Blueprint("symbol_font", __name__)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    @bp.route("/symbol_fonts_maintenance")
    def symbol_fonts_maintenance_page():
        return render_template("symbol_fonts_maintenance.html")

    # ------------------------------------------------------------------
    # /api/*symbolfont* / /api/book_fonts/*
    # ------------------------------------------------------------------

    @bp.route("/api/register_symbolfont", methods=["POST"])
    def register_symbolfont_api():
        """Register a symbol font mapping in symbolfont_dict.txt."""
        payload = request.get_json(silent=True) or {}
        font_style = payload.get("font_style", "").strip()
        replacement = payload.get("replacement", "").strip()

        if not font_style:
            return jsonify({"status": "error", "message": "font_style is required"}), 400
        if not replacement:
            return jsonify({"status": "error", "message": "replacement is required"}), 400

        try:
            symbolfont_service.register(font_style, replacement)
            current_app.logger.info(f"Registered symbol font: {font_style} -> {replacement}")
            return jsonify({"status": "ok", "message": "シンボルフォントを登録しました"}), 200
        except Exception as e:
            current_app.logger.error(f"Error registering symbol font: {str(e)}")
            return jsonify({"status": "error", "message": f"登録エラー: {str(e)}"}), 500

    @bp.route("/api/get_registered_symbolfonts")
    def get_registered_symbolfonts_api():
        """Get all registered symbol font mappings."""
        try:
            symbols = symbolfont_service.get_registered()
            font_names = sorted({k.split(".")[0] for k in symbols.keys()})
            current_app.logger.info(
                f"Loaded {len(symbols)} mappings from {len(font_names)} fonts: {font_names}"
            )
            return jsonify({"status": "ok", "symbols": symbols}), 200
        except Exception as e:
            current_app.logger.error(f"Error getting registered symbol fonts: {str(e)}")
            return jsonify({"status": "error", "message": f"取得エラー: {str(e)}"}), 500

    @bp.route("/api/delete_symbolfont", methods=["POST"])
    def delete_symbolfont_api():
        """Delete a symbol font mapping from symbolfont_dict.txt."""
        payload = request.get_json(silent=True) or {}
        key = payload.get("key", "").strip()

        if not key:
            return jsonify({"status": "error", "message": "key is required"}), 400

        try:
            symbolfont_service.delete(key)
            current_app.logger.info(f"Deleted symbol font: {key}")
            return jsonify({"status": "ok", "message": "シンボルフォントを削除しました"}), 200
        except Exception as e:
            current_app.logger.error(f"Error deleting symbol font: {str(e)}")
            return jsonify({"status": "error", "message": f"削除エラー: {str(e)}"}), 500

    @bp.route("/api/book_fonts/<path:pdf_name>")
    def get_book_fonts_api(pdf_name):
        """Get unique font names from the book's styles (without size info)."""
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404

        try:
            fonts = symbolfont_service.get_book_fonts(json_path)
            return jsonify({"status": "ok", "fonts": fonts}), 200
        except Exception as e:
            current_app.logger.error(f"Error getting book fonts: {str(e)}")
            return jsonify({"status": "error", "message": f"フォント取得エラー: {str(e)}"}), 500

    @bp.route("/api/update_symbolfont_mappings", methods=["POST"])
    def update_symbolfont_mappings_api():
        """Update multiple symbol font mappings at once."""
        payload = request.get_json(silent=True) or {}
        font_name = payload.get("font_name", "").strip()
        mappings = payload.get("mappings", {}) or {}

        if not font_name:
            return jsonify({"status": "error", "message": "font_name is required"}), 400
        if not isinstance(mappings, dict):
            return jsonify({"status": "error", "message": "mappings must be a dict"}), 400

        try:
            symbolfont_service.update_mappings(font_name, mappings)
            current_app.logger.info(
                f"Updated symbol font mappings for: {font_name} ({len(mappings)} entries)"
            )
            return jsonify({"status": "ok", "message": "マッピングを更新しました"}), 200
        except Exception as e:
            current_app.logger.error(f"Error updating symbol font mappings: {str(e)}")
            return jsonify({"status": "error", "message": f"更新エラー: {str(e)}"}), 500

    return bp
