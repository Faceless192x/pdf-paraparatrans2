from __future__ import annotations

import io
import json
import os
import re
import threading
import time
import uuid
from typing import Callable, Optional, Tuple

from PyPDF2 import PdfReader, PdfWriter

from modules.parapara_pdf2json import extract_paragraphs, reextract_page
from modules.parapara_search import search_paragraphs_in_book


class BookService:
    """ブック閲覧 API のビジネスロジックを提供するサービス。"""

    def __init__(
        self,
        get_paths: Callable[[str], Tuple[str, str]],
        is_url_book_name: Callable[[str], bool],
        ensure_url_page_nav: Callable[[dict], bool],
        build_url_page_preview_map: Callable[[dict], dict],
        load_app_settings: Callable[[], dict],
        save_app_settings: Callable[[dict], None],
    ) -> None:
        self._get_paths = get_paths
        self._is_url_book_name = is_url_book_name
        self._ensure_url_page_nav = ensure_url_page_nav
        self._build_url_page_preview_map = build_url_page_preview_map
        self._load_app_settings = load_app_settings
        self._save_app_settings = save_app_settings
        # book_toc キャッシュ（JSONのmtimeが変わらない限り再計算しない）
        self._toc_cache: dict = {}
        self._toc_cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # /api/book_data — 全 book_data 取得
    # ------------------------------------------------------------------

    def get_book_data(self, pdf_name: str) -> Optional[dict]:
        """book_data を返す。JSONが存在しない場合は None を返す。"""
        _, json_path = self._get_paths(pdf_name)
        if not os.path.exists(json_path):
            return None
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        if self._is_url_book_name(pdf_name):
            self._ensure_url_page_nav(book_data)
        return book_data

    # ------------------------------------------------------------------
    # /api/book_meta — メタ情報のみ取得（初期ロード高速化用）
    # ------------------------------------------------------------------

    def get_book_meta(self, pdf_name: str) -> Tuple[Optional[dict], Optional[float]]:
        """(meta, json_mtime) を返す。JSONが存在しない場合は (None, None) を返す。"""
        _, json_path = self._get_paths(pdf_name)
        if not os.path.exists(json_path):
            return None, None

        try:
            json_mtime = os.path.getmtime(json_path)
        except OSError:
            json_mtime = None

        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        if self._is_url_book_name(pdf_name):
            self._ensure_url_page_nav(book_data)

        last_open_page = book_data.get("last_open_page")
        if not self._is_url_book_name(pdf_name):
            try:
                settings = self._load_app_settings()
                files = (settings or {}).get("files", {}) or {}
                settings_page = (files.get(pdf_name) or {}).get("last_open_page")
                if settings_page is not None:
                    last_open_page = settings_page
            except Exception:
                pass

        meta = {
            "version": book_data.get("version"),
            "src_filename": book_data.get("src_filename"),
            "title": book_data.get("title"),
            "page_count": book_data.get("page_count"),
            "last_open_page": last_open_page,
            "styles": book_data.get("styles") or {},
            "trans_status_counts": book_data.get("trans_status_counts") or {},
            "json_mtime": json_mtime,
            "source_type": book_data.get("source_type") or "pdf",
            "source_root_url": book_data.get("source_root_url"),
            "source_host": book_data.get("source_host"),
            "page_url_map": book_data.get("page_url_map") or {},
            "url_to_page_id": book_data.get("url_to_page_id") or {},
            "page_nav": book_data.get("page_nav") or {},
            "page_preview_map": (
                self._build_url_page_preview_map(book_data)
                if self._is_url_book_name(pdf_name)
                else {}
            ),
        }
        return meta, json_mtime

    # ------------------------------------------------------------------
    # /api/update_last_page — 最終ページ番号を保存
    # ------------------------------------------------------------------

    def update_last_page(self, pdf_name: str, json_path: str, page_number: int) -> dict:
        """最終ページ番号を保存する。

        Returns:
            {"changed": int, "last_open_page": int, "stored_in": str}
        """
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        try:
            page_count = int(book_data.get("page_count") or 0)
        except Exception:
            page_count = 0
        if page_count > 0:
            page_number = max(1, min(page_number, page_count))

        if self._is_url_book_name(pdf_name):
            if book_data.get("last_open_page") == page_number:
                return {"changed": 0, "stored_in": "book_data"}

            book_data["last_open_page"] = page_number

            temp_file = f"{json_path}.{uuid.uuid4().hex}.tmp"
            try:
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(book_data, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, json_path)
            except Exception:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                raise

            return {"changed": 1, "last_open_page": page_number, "stored_in": "book_data"}

        settings = self._load_app_settings()
        files = settings.get("files") or {}
        file_entry = files.get(pdf_name)
        if not isinstance(file_entry, dict):
            file_entry = {}
            files[pdf_name] = file_entry
            settings["files"] = files

        try:
            prev_page = int(file_entry.get("last_open_page")) if file_entry.get("last_open_page") is not None else None
        except Exception:
            prev_page = None
        if prev_page == page_number:
            return {"changed": 0, "stored_in": "settings"}

        file_entry["last_open_page"] = page_number
        self._save_app_settings(settings)

        return {"changed": 1, "last_open_page": page_number, "stored_in": "settings"}

    # ------------------------------------------------------------------
    # /api/book_toc — 目次（見出し）取得（キャッシュ付き）
    # ------------------------------------------------------------------

    def get_book_toc(self, pdf_name: str, json_path: str) -> Tuple[list, bool]:
        """TOC を返す。

        Returns:
            (headlines, cached) — cached=True はキャッシュから取得された場合
        """
        try:
            mtime = os.path.getmtime(json_path)
        except OSError:
            mtime = None

        if mtime is not None:
            with self._toc_cache_lock:
                cached = self._toc_cache.get(pdf_name)
                if cached and cached.get("mtime") == mtime and isinstance(cached.get("toc"), list):
                    return cached["toc"], True

        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        headlines = []
        pages = book_data.get("pages", {}) or {}
        for page_key, page in pages.items():
            paragraphs = (page or {}).get("paragraphs", {}) or {}
            for _pid, p in paragraphs.items():
                block_tag = (p or {}).get("block_tag")
                join_flag = int((p or {}).get("join", 0) or 0)
                if join_flag == 1:
                    continue
                if not isinstance(block_tag, str):
                    continue
                if not re.match(r"^h[1-6]$", block_tag):
                    continue

                page_number = (p or {}).get("page_number")
                para_id = (p or {}).get("id")
                try:
                    y0 = (p or {}).get("bbox")[1]
                except Exception:
                    y0 = 0.0

                headlines.append(
                    {
                        "rowId": f"{page_number}_{para_id}",
                        "page_number": page_number,
                        "id": para_id,
                        "order": (p or {}).get("order", 0) or 0,
                        "column_order": (p or {}).get("column_order", 0) or 0,
                        "y0": y0,
                        "block_tag": block_tag,
                        "src_joined": (p or {}).get("src_joined"),
                        "trans_text": (p or {}).get("trans_text"),
                        "join": join_flag,
                    }
                )

        def _toc_sort_key(item: dict):
            try:
                pn = int(item.get("page_number") or 0)
            except Exception:
                pn = 0
            try:
                order = int(item.get("order") or 0)
            except Exception:
                order = 0
            try:
                col = int(item.get("column_order") or 0)
            except Exception:
                col = 0
            try:
                y0 = float(item.get("y0") or 0)
            except Exception:
                y0 = 0.0
            return (pn, order, col, y0)

        headlines.sort(key=_toc_sort_key)

        if mtime is not None:
            with self._toc_cache_lock:
                self._toc_cache[pdf_name] = {"mtime": mtime, "toc": headlines}

        return headlines, False

    # ------------------------------------------------------------------
    # /api/book_page — 指定ページのみ取得（差分更新用）
    # ------------------------------------------------------------------

    def get_book_page(self, json_path: str, page_number: int) -> Tuple[dict, Optional[dict]]:
        """指定ページを返す。

        Returns:
            (book_data, page or None)
        """
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        page_key = str(page_number)
        page = (book_data.get("pages", {}) or {}).get(page_key)
        return book_data, page

    # ------------------------------------------------------------------
    # /api/search — 全文検索
    # ------------------------------------------------------------------

    def search(self, json_path: str, query: str, limit: int) -> list:
        """全文検索を実行して結果を返す。"""
        return search_paragraphs_in_book(json_path, query, limit=limit)

    # ------------------------------------------------------------------
    # /api/extract_paragraphs — PDF からパラグラフ抽出
    # ------------------------------------------------------------------

    def extract_paragraphs(self, pdf_name: str, pdf_path: str, json_path: str, current_page: Optional[int]) -> str:
        """パラグラフ抽出（または再抽出）を実行する。

        Returns:
            完了メッセージ文字列
        Raises:
            ValueError: URLブックに対して呼び出された場合、または current_page が不正な場合。
        """
        if self._is_url_book_name(pdf_name):
            raise ValueError("URLブックはパラグラフ抽出不要です")

        if os.path.exists(json_path):
            if not current_page:
                raise ValueError("current_page が指定されていません")
            try:
                page_number = int(current_page)
            except (ValueError, TypeError):
                raise ValueError("current_page が不正です")
            reextract_page(pdf_path, json_path, page_number)
            return f"ページ {page_number} を再抽出しました"
        else:
            extract_paragraphs(pdf_path, json_path)
            return "パラグラフ抽出完了"

    # ------------------------------------------------------------------
    # /api/reload_book_data — book_data 再取得
    # ------------------------------------------------------------------

    def reload_book_data(self, json_path: str) -> dict:
        """JSON から book_data を読み込んで返す。"""
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # /pdf_view — PDF ファイルを返す
    # ------------------------------------------------------------------

    def get_pdf_path(self, pdf_name: str) -> str:
        """PDF ファイルのパスを返す。存在しない場合は FileNotFoundError。"""
        pdf_path, _ = self._get_paths(pdf_name)
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        return pdf_path

    # ------------------------------------------------------------------
    # /pdf_view/<page> — 指定ページを PDF として返す
    # ------------------------------------------------------------------

    def get_pdf_page_bytes(self, pdf_name: str, page_number: int) -> Tuple[io.BytesIO, str]:
        """指定ページを PDF バイト列として返す。

        Returns:
            (BytesIO, safe_filename_prefix)
        Raises:
            FileNotFoundError: PDF が存在しない場合
            ValueError: ページが範囲外の場合
        """
        pdf_path, _ = self._get_paths(pdf_name)
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            if page_number < 1 or page_number > len(reader.pages):
                raise ValueError("ページが存在しません")
            writer = PdfWriter()
            writer.add_page(reader.pages[page_number - 1])
            output = io.BytesIO()
            writer.write(output)
            output.seek(0)

        safe_name = os.path.splitext(os.path.basename(pdf_path))[0]
        return output, safe_name

    # ------------------------------------------------------------------
    # /api/book_styles — スタイル一覧取得
    # ------------------------------------------------------------------

    def get_book_styles(self, json_path: str) -> dict:
        """書籍の styles を返す。"""
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        return book_data.get("styles", {}) or {}
