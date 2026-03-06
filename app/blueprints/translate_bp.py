from __future__ import annotations

import os
import re
from typing import Callable, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request

from app.services.translate_service import TranslateService


def create_translate_blueprint(
    translate_service: TranslateService,
    get_paths: Callable[[str], Tuple[str, str]],
    load_app_settings: Callable[[], dict],
    save_app_settings: Callable[[dict], None],
) -> Blueprint:
    """翻訳 API の Blueprint を生成して返す。

    依存オブジェクトはファクトリ引数で受け取り、クロージャ経由でルートハンドラに渡す。
    """

    bp = Blueprint("translate", __name__)

    def _parse_optional_group_max_chars() -> Optional[int]:
        raw = (request.values.get("group_max_chars") or "").strip()
        if not raw and request.is_json:
            payload = request.get_json(silent=True) or {}
            raw = str(payload.get("group_max_chars") or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValueError("group_max_chars は整数で指定してください")

    def _parse_optional_progress_id() -> Optional[str]:
        raw = (request.values.get("progress_id") or "").strip()
        if not raw and request.is_json:
            payload = request.get_json(silent=True) or {}
            raw = str(payload.get("progress_id") or "").strip()
        if not raw:
            return None
        normalized = re.sub(r"[^A-Za-z0-9._-]", "", raw)
        if not normalized:
            return None
        return normalized[:64]

    # ------------------------------------------------------------------
    # /api/translate_engine — 翻訳エンジンの取得・切替
    # ------------------------------------------------------------------

    @bp.route("/api/translate_engine", methods=["GET", "POST"])
    def translate_engine_api():
        if request.method == "GET":
            info = translate_service.get_engine()
            return jsonify({"status": "ok", **info}), 200

        data = request.get_json(silent=True) or {}
        requested = (data.get("engine") or "").strip().lower()
        if not requested:
            return jsonify({"status": "error", "message": "engineが指定されていません"}), 400

        try:
            active = translate_service.set_engine(requested)
        except Exception as e:
            return jsonify({"status": "error", "message": f"翻訳エンジン切替エラー: {str(e)}"}), 400

        settings = load_app_settings()
        settings["translator"] = active
        try:
            save_app_settings(settings)
        except Exception as e:
            current_app.logger.warning(f"translator setting save failed: {str(e)}")

        info = translate_service.get_engine()
        return jsonify({"status": "ok", **info}), 200

    # ------------------------------------------------------------------
    # /api/translate — 短文翻訳
    # ------------------------------------------------------------------

    @bp.route("/api/translate", methods=["POST"])
    def translate_api():
        data = request.get_json()
        if not data or "text" not in data:
            return jsonify({"status": "error", "message": "No text provided"}), 400

        text = data["text"]
        source = data.get("source", "EN")
        target = data.get("target", "JA")

        current_app.logger.debug(f"FOR DEBUG(LEFT50/1TRANS):{text[:50]}")

        try:
            translated_text = translate_service.translate(text, source, target)
            current_app.logger.debug(f"FOR DEBUG(LEFT50/1TRANS):{translated_text[:50]}")
            return jsonify({"status": "ok", "translated_text": translated_text}), 200
        except Exception as e:
            current_app.logger.error(f"Translation error: {str(e)}")
            return jsonify({"status": "error", "message": str(e)}), 500

    # ------------------------------------------------------------------
    # /api/translate_all/<path:pdf_name> — PDF 全体翻訳
    # ------------------------------------------------------------------

    @bp.route("/api/translate_all/<path:pdf_name>", methods=["POST"])
    def translate_all_api(pdf_name):
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 400
        try:
            group_max_chars = _parse_optional_group_max_chars()
            progress_id = _parse_optional_progress_id()
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        try:
            stats = translate_service.translate_all(
                pdf_name,
                json_path,
                group_max_chars=group_max_chars,
                progress_id=progress_id,
            )
            return jsonify({"status": "ok", "stats": stats}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"全翻訳エラー: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /api/paraparatrans/<path:pdf_name> — ページ範囲翻訳
    # ------------------------------------------------------------------

    @bp.route("/api/paraparatrans/<path:pdf_name>", methods=["POST"])
    def paraparatrans_api(pdf_name):
        start_page = request.form.get("start_page", type=int)
        end_page = request.form.get("end_page", type=int)
        try:
            group_max_chars = _parse_optional_group_max_chars()
            progress_id = _parse_optional_progress_id()
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        if not pdf_name or start_page is None or end_page is None:
            return jsonify({"status": "error", "message": "pdf_name, start_page, end_page は必須です"}), 400
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "対象のJSONファイルが存在しません"}), 404

        current_app.logger.debug("json_path:" + json_path + " start_page:" + str(start_page) + " end_page:" + str(end_page))
        try:
            delta, stats = translate_service.paraparatrans(
                pdf_name,
                json_path,
                start_page,
                end_page,
                group_max_chars=group_max_chars,
                progress_id=progress_id,
            )
            # 互換のため data も残す（旧クライアントは全体更新前提だったが、現状 data は未使用）
            return jsonify({"status": "ok", "delta": delta, "data": delta, "stats": stats}), 200
        except Exception as e:
            current_app.logger.error(f"翻訳処理中にエラーが発生しました: {str(e)}")
            return jsonify({"status": "error", "message": f"翻訳処理中にエラーが発生しました: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /api/align_trans_by_src_joined/<path:pdf_name> — src_joined 訳揃え
    # ------------------------------------------------------------------

    @bp.route("/api/align_trans_by_src_joined/<path:pdf_name>", methods=["POST"])
    def align_trans_by_src_joined_api(pdf_name):
        """同一 src_joined の訳を、より上位 trans_status の訳へ揃える。"""
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "対象のJSONファイルが存在しません"}), 404

        try:
            book_data, changed, delta = translate_service.align_trans_by_src_joined(json_path)
            return jsonify(
                {
                    "status": "ok",
                    "changed": changed,
                    "trans_status_counts": book_data.get("trans_status_counts"),
                    "delta": delta,
                }
            ), 200
        except Exception as e:
            current_app.logger.error(f"訳揃え処理中にエラーが発生しました: {str(e)}")
            return jsonify({"status": "error", "message": f"訳揃え処理中にエラーが発生しました: {str(e)}"}), 500

    return bp
