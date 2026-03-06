from __future__ import annotations

import json
import os
import tempfile
from typing import Callable, Tuple

from flask import Blueprint, current_app, jsonify, render_template, request

from app.services.chunked_upload_service import ChunkedUploadService, ChunkedUploadServiceError
from app.services.file_mgmt_service import FileMgmtService, FileMgmtServiceError
from modules.parapara_dict_replacer import atomicsave_json, load_json
from modules.parapara_init import parapara_init
from modules.settings_sync import (
    lazy_sync_settings_from_json_files,
    save_settings,
    sync_one_pdf_settings_from_json,
)


def create_file_mgmt_blueprint(
    file_mgmt_service: FileMgmtService,
    get_paths: Callable[[str], Tuple[str, str]],
    chunked_upload_service: ChunkedUploadService,
    get_current_url_book: Callable[[], str],
    set_current_url_book: Callable[[str], None],
    chunk_upload_threshold_bytes: int,
    max_pdf_upload_bytes: int,
    max_pdf_upload_mb: int,
) -> Blueprint:
    """ファイル管理 API の Blueprint を生成して返す。

    依存オブジェクトはファクトリ引数で受け取り、クロージャ経由でルートハンドラに渡す。
    """

    bp = Blueprint("file_mgmt", __name__)

    data_folder = file_mgmt_service.data_folder
    base_folder = file_mgmt_service.base_folder

    def _pdf_size_limit_message() -> str:
        return f"PDFサイズ上限({max_pdf_upload_mb}MB)を超えています"

    # ------------------------------------------------------------------
    # Index page (一覧画面)
    # ------------------------------------------------------------------

    @bp.route("/", methods=["GET", "POST"])
    def index():
        settings_path = os.path.join(data_folder, "paraparatrans.settings.json")

        dir_param = request.args.get("dir", "").strip()
        try:
            current_dir = file_mgmt_service.normalize_rel_dir(dir_param)
        except ValueError:
            return jsonify({"status": "error", "message": "dirが不正です"}), 400

        parent_dir = ""
        if current_dir:
            parent_dir = "/".join(current_dir.split("/")[:-1])

        # POSTリクエストの場合はリストをリフレッシュ
        if request.method == "POST":
            try:
                parapara_init(base_folder, data_folder)
                current_app.logger.info("リストがリフレッシュされました")
            except Exception as e:
                current_app.logger.error(f"リストリフレッシュ中にエラーが発生しました: {str(e)}")
                return jsonify({"status": "error", "message": f"リストリフレッシュ中にエラーが発生しました: {str(e)}"}), 500

        # paraparatrans.settings.jsonが存在しない場合、parapara_initを実行
        if not os.path.exists(settings_path):
            parapara_init(base_folder, data_folder)

        # paraparatrans.settings.jsonを読み込む
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)

        # settingsのキャッシュが古い場合、各PDFのjson更新日時（PDFごとのjson_mtime）を基準に必要分だけ同期
        try:
            changed, _updated = lazy_sync_settings_from_json_files(
                settings=settings, base_folder=base_folder
            )
            if changed:
                save_settings(settings_path, settings, indent=4)
        except Exception as e:
            current_app.logger.warning(f"settingsのlazy同期に失敗しました: {str(e)}")

        # ファイルリストを取得
        files = settings.get("files", {})
        subdirs, pdf_dict = file_mgmt_service.get_directory_listing(current_dir)
        for pdf_name, file_data in files.items():
            if pdf_name not in pdf_dict:
                continue
            trans_counts = file_data.get("trans_status_counts", {})
            pdf_dict[pdf_name].update({
                "title": file_data.get("title", pdf_name),
                "last_open_page": file_data.get("last_open_page"),
                "trans_status_counts": {
                    "none": trans_counts.get("none", 0),
                    "auto": trans_counts.get("auto", 0),
                    "draft": trans_counts.get("draft", 0),
                    "fixed": trans_counts.get("fixed", 0),
                },
            })

        # URLブックを追加
        url_books = file_mgmt_service.get_url_books()
        url_book_prefix = file_mgmt_service.url_book_prefix
        for book_name, book_item in url_books.items():
            if current_dir:
                book_rel = (
                    book_name[len(url_book_prefix):]
                    if book_name.startswith(url_book_prefix)
                    else book_name
                )
                book_dir = os.path.dirname(book_rel).replace("\\", "/")
                if book_dir != current_dir:
                    continue
            else:
                book_rel = (
                    book_name[len(url_book_prefix):]
                    if book_name.startswith(url_book_prefix)
                    else book_name
                )
                if os.path.dirname(book_rel).strip():
                    continue
            if book_name in pdf_dict:
                continue
            pdf_dict[book_name] = book_item

        # フィルタ処理
        filter_text = request.args.get("filter", "").lower().strip()
        selected_types = set(request.args.getlist("type"))
        if not selected_types:
            selected_types = {"pdf", "url"}

        if filter_text:
            pdf_dict = {
                key: value
                for key, value in pdf_dict.items()
                if filter_text in value["title"].lower()
                or filter_text in value["pdf_name"].lower()
            }

        pdf_dict = {
            key: value
            for key, value in pdf_dict.items()
            if (value.get("book_type") or "pdf") in selected_types
        }

        pdf_dict = dict(
            sorted(pdf_dict.items(), key=lambda x: x[1].get("updated", ""), reverse=True)
        )

        all_dirs = file_mgmt_service.get_all_dirs()
        book_names = list((files or {}).keys()) + list(url_books.keys())
        folder_counts = file_mgmt_service.accumulate_folder_counts(book_names)
        folder_tree = file_mgmt_service.build_folder_tree(all_dirs, folder_counts, current_dir)

        return render_template(
            "index.html",
            pdf_dict=pdf_dict,
            filter_text=filter_text,
            selected_types=sorted(selected_types),
            current_dir=current_dir,
            parent_dir=parent_dir,
            subdirs=subdirs,
            breadcrumbs=file_mgmt_service.build_breadcrumbs(current_dir),
            all_dirs=all_dirs,
            folder_tree=folder_tree,
            chunk_upload_threshold_bytes=chunk_upload_threshold_bytes,
            max_pdf_upload_bytes=max_pdf_upload_bytes,
            max_pdf_upload_mb=max_pdf_upload_mb,
        )

    # ------------------------------------------------------------------
    # /api/folder/* — フォルダ CRUD
    # ------------------------------------------------------------------

    @bp.route("/api/folder/create", methods=["POST"])
    def create_folder_api():
        payload = request.get_json(silent=True) or {}
        dir_param = (payload.get("dir") or "").strip()
        name = payload.get("name")

        try:
            rel_path = file_mgmt_service.create_folder(dir_param, name)
        except ValueError:
            return jsonify({"status": "error", "message": "dirが不正です"}), 400
        except FileMgmtServiceError as e:
            return jsonify({"status": "error", "message": str(e)}), e.status
        except Exception as e:
            return jsonify({"status": "error", "message": f"フォルダ作成に失敗しました: {str(e)}"}), 500

        return jsonify({"status": "ok", "path": rel_path}), 201

    @bp.route("/api/folder/rename", methods=["POST"])
    def rename_folder_api():
        payload = request.get_json(silent=True) or {}
        dir_param = (payload.get("dir") or "").strip()
        new_name = payload.get("new_name")

        try:
            new_path = file_mgmt_service.rename_folder(dir_param, new_name)
        except ValueError:
            return jsonify({"status": "error", "message": "dirが不正です"}), 400
        except FileMgmtServiceError as e:
            return jsonify({"status": "error", "message": str(e)}), e.status
        except Exception as e:
            return jsonify({"status": "error", "message": f"フォルダ名の変更に失敗しました: {str(e)}"}), 500

        return jsonify({"status": "ok", "path": new_path}), 200

    @bp.route("/api/folder/delete", methods=["POST"])
    def delete_folder_api():
        payload = request.get_json(silent=True) or {}
        dir_param = (payload.get("dir") or "").strip()

        try:
            parent_dir = file_mgmt_service.delete_folder(dir_param)
        except ValueError:
            return jsonify({"status": "error", "message": "dirが不正です"}), 400
        except FileMgmtServiceError as e:
            return jsonify({"status": "error", "message": str(e)}), e.status
        except Exception as e:
            return jsonify({"status": "error", "message": f"フォルダ削除に失敗しました: {str(e)}"}), 500

        return jsonify({"status": "ok", "parent_dir": parent_dir}), 200

    # ------------------------------------------------------------------
    # /api/pdf/move — PDF / URLブックの移動
    # ------------------------------------------------------------------

    @bp.route("/api/pdf/move", methods=["POST"])
    def move_pdf_api():
        payload = request.get_json(silent=True) or {}
        pdf_name = (payload.get("pdf_name") or "").strip()
        dest_dir_param = (payload.get("dest_dir") or "").strip()

        normalized_pdf_name = file_mgmt_service.normalize_pdf_name(pdf_name)
        if not normalized_pdf_name:
            return jsonify({"status": "error", "message": "pdf_nameが不正です"}), 400

        try:
            normalized_dest_dir = file_mgmt_service.normalize_rel_dir(dest_dir_param)
        except ValueError:
            return jsonify({"status": "error", "message": "dest_dirが不正です"}), 400

        is_url_book = file_mgmt_service.is_url_book_name(normalized_pdf_name)
        src_pdf_path, src_json_path = get_paths(normalized_pdf_name)
        if is_url_book:
            if not os.path.exists(src_json_path):
                return jsonify({"status": "error", "message": "URLブックが存在しません"}), 404
        else:
            if not os.path.exists(src_pdf_path):
                return jsonify({"status": "error", "message": "PDFが存在しません"}), 404

        url_book_prefix = file_mgmt_service.url_book_prefix
        if is_url_book:
            src_dir = os.path.dirname(
                normalized_pdf_name[len(url_book_prefix):]
            ).replace("\\", "/")
        else:
            src_dir = os.path.dirname(normalized_pdf_name).replace("\\", "/")
        if normalized_dest_dir == src_dir:
            return jsonify({"status": "ok", "pdf_name": normalized_pdf_name, "moved": False}), 200

        dest_parts = normalized_dest_dir.split("/") if normalized_dest_dir else []
        if dest_parts and any(
            file_mgmt_service.should_skip_dir(part) for part in dest_parts
        ):
            return jsonify({"status": "error", "message": "移動先フォルダが不正です"}), 400

        dest_dir_path = (
            file_mgmt_service.safe_join_data(*dest_parts)
            if dest_parts
            else base_folder
        )
        if not os.path.isdir(dest_dir_path):
            return jsonify({"status": "error", "message": "移動先フォルダが存在しません"}), 404

        if is_url_book:
            base_name = os.path.basename(
                normalized_pdf_name[len(url_book_prefix):]
            )
            new_book_key = (
                f"{normalized_dest_dir}/{base_name}"
                if normalized_dest_dir
                else base_name
            )
            new_pdf_name = f"{url_book_prefix}{new_book_key}"
        else:
            base_name = os.path.basename(normalized_pdf_name)
            new_pdf_name = (
                f"{normalized_dest_dir}/{base_name}"
                if normalized_dest_dir
                else base_name
            )
        dest_pdf_path, dest_json_path = get_paths(new_pdf_name)

        if not is_url_book and os.path.exists(dest_pdf_path):
            return jsonify({"status": "error", "message": "移動先に同名PDFが存在します"}), 409
        if os.path.exists(dest_json_path):
            return jsonify({"status": "error", "message": "移動先に同名JSONが存在します"}), 409

        try:
            if is_url_book:
                os.replace(src_json_path, dest_json_path)
                if get_current_url_book() == normalized_pdf_name:
                    set_current_url_book(new_pdf_name)
                return jsonify({"status": "ok", "pdf_name": new_pdf_name, "moved": True}), 200

            os.replace(src_pdf_path, dest_pdf_path)
            if os.path.exists(src_json_path):
                os.replace(src_json_path, dest_json_path)

            if os.path.exists(dest_json_path):
                try:
                    book_data = load_json(dest_json_path)
                    if isinstance(book_data, dict):
                        book_data["src_filename"] = new_pdf_name
                        atomicsave_json(dest_json_path, book_data)
                except Exception as e:
                    current_app.logger.warning(f"JSONのsrc_filename更新に失敗しました: {str(e)}")

            settings_path = os.path.join(data_folder, "paraparatrans.settings.json")
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, "r", encoding="utf-8") as f:
                        settings = json.load(f)
                    if not isinstance(settings, dict):
                        settings = {"files": {}}
                    files = settings.get("files")
                    if not isinstance(files, dict):
                        files = {}
                        settings["files"] = files

                    moved_entry = files.pop(normalized_pdf_name, None)
                    if isinstance(moved_entry, dict):
                        moved_entry["src_filename"] = new_pdf_name
                        files[new_pdf_name] = moved_entry

                    save_settings(settings_path, settings, indent=4)
                except Exception as e:
                    current_app.logger.warning(f"settingsの更新に失敗しました: {str(e)}")

            if os.path.exists(dest_json_path):
                try:
                    sync_one_pdf_settings_from_json(
                        settings_path=settings_path,
                        base_folder=base_folder,
                        pdf_name=new_pdf_name,
                        indent=4,
                    )
                except Exception as e:
                    current_app.logger.warning(f"settingsの同期に失敗しました: {str(e)}")

            return jsonify({"status": "ok", "pdf_name": new_pdf_name, "moved": True}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"移動に失敗しました: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /api/upload_pdf — 単体アップロード
    # ------------------------------------------------------------------

    @bp.route("/api/upload_pdf", methods=["POST"])
    def upload_pdf_api():
        """PDFを data/ にアップロードする。

        同一PDFファイル名（拡張子を除いたpdf_name）が既に存在する場合はエラーとする。
        """
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "file が指定されていません"}), 400

        if os.path.exists(data_folder) and not os.path.isdir(data_folder):
            return jsonify({"status": "error", "message": f"dataフォルダが不正です: {data_folder}"}), 500
        os.makedirs(data_folder, exist_ok=True)
        if os.path.exists(base_folder) and not os.path.isdir(base_folder):
            return jsonify({"status": "error", "message": f"保存先フォルダが不正です: {base_folder}"}), 500
        os.makedirs(base_folder, exist_ok=True)

        file = request.files["file"]
        if not file or not getattr(file, "filename", ""):
            return jsonify({"status": "error", "message": "ファイル名が不正です"}), 400

        try:
            if int(request.content_length or 0) > max_pdf_upload_bytes:
                return jsonify({"status": "error", "message": _pdf_size_limit_message()}), 413
        except Exception:
            pass

        original_filename = file.filename
        if not original_filename.lower().endswith(".pdf"):
            return jsonify({"status": "error", "message": "PDFファイルのみアップロード可能です"}), 400

        pdf_name = file_mgmt_service.sanitize_pdf_basename(original_filename)
        if not pdf_name:
            return jsonify({"status": "error", "message": "ファイル名が空です"}), 400

        dest_pdf_path, _dest_json_path = get_paths(pdf_name)
        if os.path.exists(dest_pdf_path):
            return jsonify({"status": "error", "message": f"同名のPDFが既に存在します: {pdf_name}.pdf"}), 409

        last_modified_ms_raw = request.form.get("last_modified_ms", "")
        last_modified_sec = None
        if last_modified_ms_raw:
            try:
                last_modified_sec = int(last_modified_ms_raw) / 1000.0
            except Exception:
                last_modified_sec = None

        tmp_fd, tmp_path = tempfile.mkstemp(prefix="upload_", suffix=".pdf", dir=base_folder)
        os.close(tmp_fd)
        try:
            file.save(tmp_path)
            if os.path.getsize(tmp_path) > max_pdf_upload_bytes:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return jsonify({"status": "error", "message": _pdf_size_limit_message()}), 413
            if os.path.exists(dest_pdf_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return jsonify({"status": "error", "message": f"同名のPDFが既に存在します: {pdf_name}.pdf"}), 409

            os.replace(tmp_path, dest_pdf_path)

            if last_modified_sec is not None:
                try:
                    st = os.stat(dest_pdf_path)
                    os.utime(dest_pdf_path, (st.st_atime, last_modified_sec))
                except Exception:
                    pass

            current_app.logger.info(f"PDFアップロード: {original_filename} -> {dest_pdf_path}")
            return jsonify({"status": "ok", "pdf_name": pdf_name}), 201
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            return jsonify({"status": "error", "message": f"アップロードに失敗しました: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /api/upload_pdf_chunk/* — 分割アップロード
    # ------------------------------------------------------------------

    @bp.route("/api/upload_pdf_chunk/init", methods=["POST"])
    def upload_pdf_chunk_init_api():
        payload = request.get_json(silent=True) or {}

        original_filename = str(payload.get("filename") or "").strip()
        if not original_filename:
            return jsonify({"status": "error", "message": "filename が不正です"}), 400
        if not original_filename.lower().endswith(".pdf"):
            return jsonify({"status": "error", "message": "PDFファイルのみアップロード可能です"}), 400

        try:
            total_size = int(payload.get("size") or 0)
        except Exception:
            total_size = 0
        if total_size <= 0:
            return jsonify({"status": "error", "message": "size が不正です"}), 400
        if total_size > max_pdf_upload_bytes:
            return jsonify({"status": "error", "message": _pdf_size_limit_message()}), 413

        pdf_name = file_mgmt_service.sanitize_pdf_basename(original_filename)
        if not pdf_name:
            return jsonify({"status": "error", "message": "ファイル名が空です"}), 400

        if os.path.exists(data_folder) and not os.path.isdir(data_folder):
            return jsonify({"status": "error", "message": f"dataフォルダが不正です: {data_folder}"}), 500
        os.makedirs(data_folder, exist_ok=True)
        if os.path.exists(base_folder) and not os.path.isdir(base_folder):
            return jsonify({"status": "error", "message": f"保存先フォルダが不正です: {base_folder}"}), 500
        os.makedirs(base_folder, exist_ok=True)

        dest_pdf_path, _ = get_paths(pdf_name)
        if os.path.exists(dest_pdf_path):
            return jsonify({"status": "error", "message": f"同名のPDFが既に存在します: {pdf_name}.pdf"}), 409

        last_modified_sec = None
        last_modified_ms_raw = payload.get("last_modified_ms")
        if last_modified_ms_raw is not None and str(last_modified_ms_raw).strip():
            try:
                last_modified_sec = int(last_modified_ms_raw) / 1000.0
            except Exception:
                last_modified_sec = None

        chunk_size = int(chunked_upload_service.chunk_size_bytes)
        total_chunks = max(1, (total_size + chunk_size - 1) // chunk_size)

        try:
            session = chunked_upload_service.create_session(
                pdf_name=pdf_name,
                original_filename=original_filename,
                dest_pdf_path=dest_pdf_path,
                total_size=total_size,
                total_chunks=total_chunks,
                last_modified_sec=last_modified_sec,
            )
            return jsonify({"status": "ok", **session}), 201
        except ChunkedUploadServiceError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            current_app.logger.exception("分割アップロード初期化に失敗")
            return jsonify({"status": "error", "message": f"初期化に失敗しました: {str(e)}"}), 500

    @bp.route("/api/upload_pdf_chunk/part", methods=["POST"])
    def upload_pdf_chunk_part_api():
        upload_id = str(request.form.get("upload_id") or "").strip()
        if not upload_id:
            return jsonify({"status": "error", "message": "upload_id が不正です"}), 400

        chunk_index_raw = request.form.get("chunk_index")
        try:
            chunk_index = int(chunk_index_raw)
        except Exception:
            return jsonify({"status": "error", "message": "chunk_index が不正です"}), 400

        chunk_file = request.files.get("chunk")
        if not chunk_file:
            return jsonify({"status": "error", "message": "chunk が指定されていません"}), 400

        try:
            chunked_upload_service.save_chunk(
                upload_id=upload_id,
                chunk_index=chunk_index,
                file_obj=chunk_file.stream,
            )
            return jsonify({"status": "ok", "upload_id": upload_id, "chunk_index": chunk_index}), 200
        except ChunkedUploadServiceError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            current_app.logger.exception("分割アップロードチャンク保存に失敗")
            return jsonify({"status": "error", "message": f"チャンク保存に失敗しました: {str(e)}"}), 500

    @bp.route("/api/upload_pdf_chunk/complete", methods=["POST"])
    def upload_pdf_chunk_complete_api():
        payload = request.get_json(silent=True) or {}
        upload_id = str(payload.get("upload_id") or "").strip()
        if not upload_id:
            return jsonify({"status": "error", "message": "upload_id が不正です"}), 400

        try:
            completed = chunked_upload_service.complete_session(upload_id=upload_id)
            current_app.logger.info(
                f"PDF分割アップロード完了: {completed.get('pdf_name')} -> {completed.get('dest_pdf_path')}"
            )
            return jsonify({"status": "ok", "pdf_name": completed.get("pdf_name")}), 201
        except ChunkedUploadServiceError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            current_app.logger.exception("分割アップロード完了処理に失敗")
            return jsonify({"status": "error", "message": f"完了処理に失敗しました: {str(e)}"}), 500

    # ------------------------------------------------------------------
    # /api/pdf_list
    # ------------------------------------------------------------------

    @bp.route("/api/pdf_list")
    def pdf_list_api():
        """Get list of all available PDF files (without .pdf extension)."""
        try:
            pdf_files = file_mgmt_service.list_pdfs()
            return jsonify({"status": "ok", "pdf_files": pdf_files}), 200
        except Exception as e:
            current_app.logger.error(f"Error getting PDF list: {str(e)}")
            return jsonify({"status": "error", "message": f"取得エラー: {str(e)}"}), 500

    return bp
