from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Optional, Tuple

from modules.api_translate import (
    get_current_translator,
    get_supported_translators,
    set_current_translator,
    translate_text,
)
from modules.parapara_align_trans_by_src_joined import (
    align_translations_by_src_joined_collect_pages,
)
from modules.parapara_dict_replacer import atomicsave_json, file_replace_with_dict
from modules.parapara_trans import paraparatrans_json_file, recalc_trans_status_counts
from modules.settings_sync import sync_one_pdf_settings_from_json

if TYPE_CHECKING:
    from app.services.dict_service import DictService


class TranslateService:
    """翻訳 API に関するビジネスロジックを集約するサービス。"""

    def __init__(
        self,
        dict_service: DictService,
        data_folder: str,
        base_folder: str,
    ) -> None:
        self.dict_service = dict_service
        self.data_folder = data_folder
        self.base_folder = base_folder

    # ------------------------------------------------------------------
    # 翻訳エンジン管理
    # ------------------------------------------------------------------

    def get_engine(self) -> dict:
        """現在の翻訳エンジンとサポートエンジン一覧を返す。"""
        return {
            "engine": get_current_translator(),
            "supported": get_supported_translators(),
        }

    def set_engine(self, engine: str) -> str:
        """翻訳エンジンを切り替えて、アクティブなエンジン名を返す。"""
        return set_current_translator(engine)

    # ------------------------------------------------------------------
    # 短文翻訳
    # ------------------------------------------------------------------

    def translate(self, text: str, source: str, target: str) -> str:
        """単一テキストを翻訳して結果を返す。"""
        return translate_text(text, source, target)

    # ------------------------------------------------------------------
    # 辞書置換ヘルパー
    # ------------------------------------------------------------------

    def apply_dict_replace_for_range(
        self,
        pdf_name: str,
        json_path: str,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
    ) -> None:
        """対訳辞書を使って JSON の指定ページ範囲に置換を適用する。"""
        dict_paths = self.dict_service.get_active_dict_paths(pdf_name)
        merged_path = self.dict_service.merged_dict_file(dict_paths)
        try:
            if start_page is None or end_page is None:
                file_replace_with_dict(json_path, merged_path)
            else:
                file_replace_with_dict(json_path, merged_path, start_page, end_page)
        finally:
            try:
                os.remove(merged_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # 全翻訳
    # ------------------------------------------------------------------

    def translate_all(
        self,
        pdf_name: str,
        json_path: str,
        group_max_chars: Optional[int] = None,
        progress_id: Optional[str] = None,
    ) -> dict:
        """PDF 全体を翻訳し、stats を返す。"""
        self.apply_dict_replace_for_range(pdf_name, json_path)
        _, stats = paraparatrans_json_file(
            json_path,
            1,
            9999,
            group_max_chars=group_max_chars,
            progress_id=progress_id,
        )
        settings_path = os.path.join(self.data_folder, "paraparatrans.settings.json")
        sync_one_pdf_settings_from_json(
            settings_path=settings_path,
            base_folder=self.base_folder,
            pdf_name=pdf_name,
            indent=4,
        )
        return stats

    # ------------------------------------------------------------------
    # ページ範囲翻訳
    # ------------------------------------------------------------------

    def paraparatrans(
        self,
        pdf_name: str,
        json_path: str,
        start_page: int,
        end_page: int,
        group_max_chars: Optional[int] = None,
        progress_id: Optional[str] = None,
    ) -> Tuple[dict, dict]:
        """指定ページ範囲を翻訳し、(delta, stats) を返す。"""
        self.apply_dict_replace_for_range(pdf_name, json_path, start_page, end_page)
        updated_data, stats = paraparatrans_json_file(
            json_path,
            start_page,
            end_page,
            group_max_chars=group_max_chars,
            progress_id=progress_id,
        )

        pages_delta: dict = {}
        pages = updated_data.get("pages", {})
        for page in range(start_page, end_page + 1):
            key = str(page)
            if key in pages:
                pages_delta[key] = pages[key]

        delta = {
            "pages": pages_delta,
            "trans_status_counts": updated_data.get("trans_status_counts"),
        }

        settings_path = os.path.join(self.data_folder, "paraparatrans.settings.json")
        sync_one_pdf_settings_from_json(
            settings_path=settings_path,
            base_folder=self.base_folder,
            pdf_name=pdf_name,
            indent=4,
        )
        return delta, stats

    # ------------------------------------------------------------------
    # src_joined 訳揃え
    # ------------------------------------------------------------------

    def align_trans_by_src_joined(self, json_path: str) -> Tuple[dict, int, dict]:
        """同一 src_joined の訳を上位 trans_status の訳に揃え、(book_data, changed, delta) を返す。"""
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        _, changed, pages_changed = align_translations_by_src_joined_collect_pages(book_data)
        recalc_trans_status_counts(book_data)
        atomicsave_json(json_path, book_data)

        pages_delta: dict = {}
        pages = book_data.get("pages", {}) or {}
        for key in pages_changed:
            if key in pages:
                pages_delta[key] = pages[key]

        delta = {
            "pages": pages_delta,
            "trans_status_counts": book_data.get("trans_status_counts"),
        }

        return book_data, changed, delta
