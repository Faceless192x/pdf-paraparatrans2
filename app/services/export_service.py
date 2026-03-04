from __future__ import annotations

import html
import io
import json
import os
import re
import zipfile
from typing import IO, Optional, Tuple

from modules.parapara_dict_replacer import atomicsave_json, load_json
from modules.parapara_json2html import json2html
from modules.parapara_join_incremental import apply_all as join_apply_all
from modules.parapara_structure import (
    ensure_backup_copy as structure_ensure_backup_copy,
    load_json_from_upload as structure_load_json_from_upload,
    merge_structure_into_book as structure_merge_into_book,
    strip_structure as structure_strip,
)
from modules.parapara_trans import recalc_trans_status_counts


_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"(?i)<br\s*/?>")
_P_CLOSE_RE = re.compile(r"(?i)</p>")
_P_OPEN_RE = re.compile(r"(?i)<p[^>]*>")


def _strip_html_text(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = _BR_RE.sub("\n", s)
    s = _P_CLOSE_RE.sub("\n", s)
    s = _P_OPEN_RE.sub("", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    s = s.replace("\u00a0", " ")
    return s


def _paragraph_sort_key(paragraph: dict) -> tuple:
    try:
        page_number = int(paragraph.get("page_number") or 0)
    except Exception:
        page_number = 0
    try:
        order = int(paragraph.get("order") or 0)
    except Exception:
        order = 0
    try:
        column_order = int(paragraph.get("column_order") or 0)
    except Exception:
        column_order = 0
    try:
        y0 = float((paragraph.get("bbox") or [0, 0])[1] or 0)
    except Exception:
        y0 = 0
    return (page_number, order, column_order, y0)


def _iter_sorted_paragraphs(book_data: dict) -> list[dict]:
    paragraphs_list = []
    pages = book_data.get("pages", {}) or {}
    for page in pages.values():
        paragraphs = (page or {}).get("paragraphs", {}) or {}
        for para in paragraphs.values():
            if isinstance(para, dict):
                paragraphs_list.append(para)
    paragraphs_list.sort(key=_paragraph_sort_key)
    return paragraphs_list


def _build_text_export_content(
    book_data: dict,
    fields: list[str],
    *,
    include_page_numbers: bool,
    include_header: bool,
    include_footer: bool,
    include_remove: bool,
    fmt: str,
) -> str:
    paragraphs_list = _iter_sorted_paragraphs(book_data)
    lines: list[str] = []
    current_page = None
    page_prefix = "## Page " if fmt == "md" else "Page "

    for paragraph in paragraphs_list:
        block_tag = str(paragraph.get("block_tag") or "").lower()
        if block_tag == "header" and not include_header:
            continue
        if block_tag == "footer" and not include_footer:
            continue
        if block_tag == "remove" and not include_remove:
            continue

        page_number = paragraph.get("page_number") or 0
        if include_page_numbers and page_number != current_page:
            current_page = page_number
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"{page_prefix}{page_number}")

        values = []
        for key in fields:
            raw = paragraph.get(key, "")
            text = _strip_html_text(raw).strip()
            values.append(text)

        if not any(values):
            continue

        for value in values:
            if value:
                lines.append(value)

        lines.append("")

    content = "\n".join(lines).strip()
    if content:
        content += "\n"
    return content


class ExportService:
    """エクスポート API に関するビジネスロジックを集約するサービス。"""

    def __init__(self, *, data_folder: str, app_dir: str) -> None:
        self.data_folder = os.path.abspath(data_folder)
        self.app_dir = os.path.abspath(app_dir)

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _structure_folder(self) -> str:
        folder = os.path.join(self.data_folder, "structure")
        os.makedirs(folder, exist_ok=True)
        return folder

    def _structure_path(self, pdf_name: str) -> str:
        return os.path.join(self._structure_folder(), f"{pdf_name}.structure.json")

    def _rel(self, path: str) -> str:
        """APP_DIR からの相対パスを返す。"""
        return os.path.relpath(path, self.app_dir)

    # ------------------------------------------------------------------
    # HTML エクスポート
    # ------------------------------------------------------------------

    def export_html(self, json_path: str, display_unit: str = "page") -> Tuple[str, str]:
        """対訳 HTML を生成して (out_path, rel_path) を返す。"""
        json2html(json_path, display_unit=display_unit)
        out_path = os.path.splitext(json_path)[0] + ".html"
        return out_path, self._rel(out_path)

    def ensure_html_exists(self, json_path: str, display_unit: str = "page") -> str:
        """HTML が存在しなければ生成してパスを返す。"""
        out_path = os.path.splitext(json_path)[0] + ".html"
        if not os.path.exists(out_path):
            json2html(json_path, display_unit=display_unit)
        return out_path

    # ------------------------------------------------------------------
    # 構造ファイル エクスポート
    # ------------------------------------------------------------------

    def export_structure(self, pdf_name: str, json_path: str) -> Tuple[str, str]:
        """文書構造ファイルを生成して (out_path, rel_path) を返す。"""
        book_data = load_json(json_path)
        structure_data = structure_strip(book_data)
        out_path = self._structure_path(pdf_name)
        atomicsave_json(out_path, structure_data)
        return out_path, self._rel(out_path)

    def ensure_structure_exists(self, pdf_name: str, json_path: str) -> str:
        """構造ファイルが存在しなければ生成してパスを返す。"""
        out_path = self._structure_path(pdf_name)
        if not os.path.exists(out_path):
            book_data = load_json(json_path)
            structure_data = structure_strip(book_data)
            atomicsave_json(out_path, structure_data)
        return out_path

    # ------------------------------------------------------------------
    # テキスト エクスポート
    # ------------------------------------------------------------------

    def export_text(
        self,
        json_path: str,
        fmt: str,
        fields: list[str],
        *,
        include_page_numbers: bool,
        include_header: bool,
        include_footer: bool,
        include_remove: bool,
    ) -> Tuple[str, str]:
        """テキストファイルを生成して (out_path, rel_path) を返す。"""
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        content = _build_text_export_content(
            book_data,
            fields,
            include_page_numbers=include_page_numbers,
            include_header=include_header,
            include_footer=include_footer,
            include_remove=include_remove,
            fmt=fmt,
        )
        out_path = os.path.splitext(json_path)[0] + f".{fmt}"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        return out_path, self._rel(out_path)

    def get_text_path(self, json_path: str, fmt: str) -> str:
        """テキストファイルのパスを返す（存在確認は呼び出し元で行う）。"""
        return os.path.splitext(json_path)[0] + f".{fmt}"

    # ------------------------------------------------------------------
    # 構造インポート
    # ------------------------------------------------------------------

    def import_structure(
        self,
        pdf_name: str,
        json_path: str,
        imported: dict,
    ) -> Tuple[str, dict, bool, Optional[dict]]:
        """構造データを取り込み、(backup_rel, stats, join_changed, trans_status_counts) を返す。"""
        book_data = load_json(json_path)
        backup_path = structure_ensure_backup_copy(
            json_path, backup_dir=os.path.join(self.data_folder, "backup")
        )
        book_data, stats, join_changed = structure_merge_into_book(book_data, imported)
        if join_changed:
            join_apply_all(book_data, sep="", normalize_head=True)
        recalc_trans_status_counts(book_data)
        atomicsave_json(json_path, book_data)
        return (
            self._rel(backup_path),
            stats,
            bool(join_changed),
            book_data.get("trans_status_counts"),
        )

    def load_structure_from_upload(self, upfile: IO) -> dict:
        """アップロードファイルから構造 JSON を読み込んで返す。"""
        return structure_load_json_from_upload(upfile)

    # ------------------------------------------------------------------
    # Chrome 拡張ダウンロード
    # ------------------------------------------------------------------

    def build_chrome_extension_zip(self) -> io.BytesIO:
        """Chrome/Edge 用ローカル拡張の ZIP を生成して BytesIO を返す。"""
        ext_dir = os.path.join(self.app_dir, "tools", "chrome_extension_paraparatrans")
        if not os.path.isdir(ext_dir):
            raise FileNotFoundError("拡張フォルダが見つかりません")

        zip_buffer = io.BytesIO()
        root_name = "chrome_extension_paraparatrans"

        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for folder, _, files in os.walk(ext_dir):
                rel_folder = os.path.relpath(folder, ext_dir)
                for file_name in files:
                    abs_path = os.path.join(folder, file_name)
                    rel_path = (
                        os.path.join(rel_folder, file_name)
                        if rel_folder != "."
                        else file_name
                    )
                    arcname = os.path.join(root_name, rel_path)
                    zf.write(abs_path, arcname)

        zip_buffer.seek(0)
        return zip_buffer
