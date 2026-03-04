from __future__ import annotations

import os
from typing import Callable, Tuple

from flask import Blueprint, jsonify, render_template, request, send_file

from app.services.export_service import ExportService


def create_export_blueprint(
    export_service: ExportService,
    get_paths: Callable[[str], Tuple[str, str]],
) -> Blueprint:
    """エクスポート API の Blueprint を生成して返す。

    依存オブジェクトはファクトリ引数で受け取り、クロージャ経由でルートハンドラに渡す。
    """

    bp = Blueprint("export", __name__)

    # ------------------------------------------------------------------
    # /api/export_html/<path:pdf_name> — 対訳 HTML 生成
    # ------------------------------------------------------------------

    @bp.route("/api/export_html/<path:pdf_name>", methods=["POST"])
    def export_html_api(pdf_name):
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 400
        try:
            display_unit = request.form.get("display_unit") or "page"
            _, rel = export_service.export_html(json_path, display_unit=display_unit)
        except Exception as e:
            return jsonify({"status": "error", "message": f"HTML生成エラー: {str(e)}"}), 500
        return jsonify({"status": "ok", "path": rel}), 200

    # ------------------------------------------------------------------
    # /api/download_html/<path:pdf_name> — 対訳 HTML ダウンロード
    # ------------------------------------------------------------------

    @bp.route("/api/download_html/<path:pdf_name>")
    def download_html_api(pdf_name):
        """対訳HTMLをダウンロードする（無ければ生成して返す）。"""
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

        try:
            display_unit = request.args.get("display_unit") or "page"
            out_path = export_service.ensure_html_exists(json_path, display_unit=display_unit)
        except Exception as e:
            return jsonify({"status": "error", "message": f"HTML生成エラー: {str(e)}"}), 500

        try:
            return send_file(out_path, as_attachment=True, download_name=os.path.basename(out_path))
        except TypeError:
            # Flask の古い版互換 (download_name 未対応)
            return send_file(out_path, as_attachment=True)

    # ------------------------------------------------------------------
    # /api/export_structure/<path:pdf_name> — 文書構造ファイル生成
    # ------------------------------------------------------------------

    @bp.route("/api/export_structure/<path:pdf_name>", methods=["POST"])
    def export_structure_api(pdf_name):
        """著作権配慮用の '文書構造ファイル' を出力する。

        - src_html/src_text/src_joined/src_replaced/trans_auto/trans_text を除去
        - data/structure/<pdf_name>.structure.json に保存
        """
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 400

        try:
            _, rel = export_service.export_structure(pdf_name, json_path)
            return jsonify({"status": "ok", "path": rel}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"構造ファイル出力エラー: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /api/export_text/<path:pdf_name> — テキストファイル生成
    # ------------------------------------------------------------------

    @bp.route("/api/export_text/<path:pdf_name>", methods=["POST"])
    def export_text_api(pdf_name):
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 400

        payload = request.get_json(silent=True) or {}
        fmt = (payload.get("format") or "txt").lower().strip()
        fields = payload.get("fields") or []
        include_page_numbers = bool(payload.get("include_page_numbers", True))
        include_header = bool(payload.get("include_header", False))
        include_footer = bool(payload.get("include_footer", False))
        include_remove = bool(payload.get("include_remove", False))

        if fmt not in {"txt", "md"}:
            return jsonify({"status": "error", "message": "format は txt か md を指定してください"}), 400
        if not isinstance(fields, list):
            return jsonify({"status": "error", "message": "fields は配列で指定してください"}), 400

        allowed_fields = {"src_text", "src_joined", "src_replaced", "trans_auto", "trans_text"}
        fields = [f for f in fields if f in allowed_fields]
        if not fields or len(fields) > 2:
            return jsonify({"status": "error", "message": "fields は1〜2件で指定してください"}), 400

        try:
            _, rel = export_service.export_text(
                json_path,
                fmt,
                fields,
                include_page_numbers=include_page_numbers,
                include_header=include_header,
                include_footer=include_footer,
                include_remove=include_remove,
            )
            return jsonify({"status": "ok", "path": rel}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"テキスト出力エラー: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /api/download_text/<path:pdf_name>/<string:fmt> — テキストファイルダウンロード
    # ------------------------------------------------------------------

    @bp.route("/api/download_text/<path:pdf_name>/<string:fmt>")
    def download_text_api(pdf_name, fmt: str):
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

        fmt = (fmt or "txt").lower().strip()
        if fmt not in {"txt", "md"}:
            return jsonify({"status": "error", "message": "format は txt か md を指定してください"}), 400

        out_path = export_service.get_text_path(json_path, fmt)
        if not os.path.exists(out_path):
            return jsonify({"status": "error", "message": "出力ファイルが存在しません"}), 404

        try:
            return send_file(out_path, as_attachment=True, download_name=os.path.basename(out_path))
        except TypeError:
            return send_file(out_path, as_attachment=True)

    # ------------------------------------------------------------------
    # /api/download_structure/<path:pdf_name> — 構造ファイルダウンロード
    # ------------------------------------------------------------------

    @bp.route("/api/download_structure/<path:pdf_name>")
    def download_structure_api(pdf_name):
        """既存の文書構造ファイルをダウンロードする（無ければ生成して返す）。"""
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

        try:
            out_path = export_service.ensure_structure_exists(pdf_name, json_path)
        except Exception as e:
            return jsonify({"status": "error", "message": f"構造ファイル生成エラー: {str(e)}"}), 500

        try:
            return send_file(out_path, as_attachment=True, download_name=os.path.basename(out_path))
        except TypeError:
            # Flask の古い版互換 (download_name 未対応)
            return send_file(out_path, as_attachment=True)

    # ------------------------------------------------------------------
    # /api/download_extension/chrome — Chrome 拡張ダウンロード
    # ------------------------------------------------------------------

    @bp.route("/api/download_extension/chrome")
    def download_chrome_extension_api():
        """Chrome/Edge用ローカル拡張をZIPでダウンロードする。"""
        try:
            zip_buffer = export_service.build_chrome_extension_zip()
        except FileNotFoundError as e:
            return jsonify({"status": "error", "message": str(e)}), 404
        except Exception as e:
            return jsonify({"status": "error", "message": f"ZIP生成エラー: {str(e)}"}), 500

        try:
            return send_file(
                zip_buffer,
                as_attachment=True,
                download_name="chrome_extension_paraparatrans.zip",
                mimetype="application/zip",
            )
        except TypeError:
            zip_buffer.seek(0)
            return send_file(
                zip_buffer,
                as_attachment=True,
                attachment_filename="chrome_extension_paraparatrans.zip",
                mimetype="application/zip",
            )

    # ------------------------------------------------------------------
    # /api/import_structure/<path:pdf_name> — 構造ファイル取り込み
    # ------------------------------------------------------------------

    @bp.route("/api/import_structure/<path:pdf_name>", methods=["POST"])
    def import_structure_api(pdf_name):
        """文書構造ファイルを取り込み、既存JSONの構造情報のみ更新する。

        - 更新前に data/backup に元JSONを複写
        - src_html/src_text/src_joined/src_replaced/trans_auto/trans_text は更新しない
        - join が変化した場合は src_joined/src_replaced を再構築する
        """
        _, json_path = get_paths(pdf_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "JSONが存在しません"}), 400

        imported = None

        upfile = request.files.get("file")
        if upfile and getattr(upfile, "filename", ""):
            try:
                imported = export_service.load_structure_from_upload(upfile)
            except Exception as e:
                return jsonify({"status": "error", "message": f"アップロードJSONの読み取りに失敗: {str(e)}"}), 400
        else:
            imported = request.get_json(silent=True)

        if not isinstance(imported, dict):
            return jsonify({"status": "error", "message": "取り込みデータが不正です（JSON object ではありません）"}), 400

        try:
            backup_rel, stats, join_changed, trans_status_counts = export_service.import_structure(
                pdf_name, json_path, imported
            )
            return jsonify(
                {
                    "status": "ok",
                    "backup": backup_rel,
                    "stats": stats,
                    "join_changed": join_changed,
                    "trans_status_counts": trans_status_counts,
                }
            ), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"構造ファイル取り込みエラー: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /partials/data_export_dialog — データエクスポートダイアログ部分テンプレート
    # ------------------------------------------------------------------

    @bp.route("/partials/data_export_dialog")
    def data_export_dialog_partial():
        return render_template("_data_export_dialog.html")

    return bp
