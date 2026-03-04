from __future__ import annotations

import datetime
import json
import os
import uuid
from typing import Callable, Optional, Tuple

import fitz

from modules.parapara_dict_replacer import atomicsave_json, load_json
from modules.parapara_join_incremental import (
    apply_all as join_apply_all,
    apply_join_change as join_apply_change,
    build_index as join_build_index,
    iter_paragraph_refs as join_iter_paragraph_refs,
)
from modules.parapara_symbolfont_rebuild import rebuild_src_text_in_file
from modules.parapara_table_reextract import (
    append_markdown_table_rows_from_selection,
    suggest_table_shape_for_selection,
)
from modules.parapara_tagging_by_structure import structure_tagging
from modules.parapara_tagging_by_style import tag_paragraphs_by_style
from modules.parapara_tagging_by_style_y import tag_paragraphs_by_style_y_in_file
from modules.parapara_trans import recalc_trans_status_counts
from modules.parapara_join_flags import join_flags_in_file


_TRANS_STATUS_KEYS = ("none", "auto", "draft", "fixed")


def _normalize_trans_status(status: str) -> str:
    if status in _TRANS_STATUS_KEYS:
        return status
    return "none"


def _ensure_trans_status_counts(book_data: dict) -> dict:
    """book_data["trans_status_counts"] を差分更新できる形に正規化する。"""
    counts = book_data.get("trans_status_counts")
    if not isinstance(counts, dict):
        counts = {}
    normalized = {}
    for k in _TRANS_STATUS_KEYS:
        v = counts.get(k, 0)
        try:
            normalized[k] = int(v)
        except Exception:
            normalized[k] = 0
    book_data["trans_status_counts"] = normalized
    return normalized


def _is_trans_status_counts_usable_for_delta(book_data: dict) -> bool:
    counts = book_data.get("trans_status_counts")
    if not isinstance(counts, dict):
        return False
    return all(k in counts for k in _TRANS_STATUS_KEYS)


def _apply_trans_status_delta(book_data: dict, old_status: str, new_status: str) -> None:
    """trans_status の変更分だけ trans_status_counts を更新する（全件再集計を避ける）。"""
    counts = _ensure_trans_status_counts(book_data)
    old_s = _normalize_trans_status(old_status)
    new_s = _normalize_trans_status(new_status)
    if old_s == new_s:
        return
    counts[old_s] = max(0, counts.get(old_s, 0) - 1)
    counts[new_s] = counts.get(new_s, 0) + 1


class ParagraphService:
    def __init__(
        self,
        data_folder: str,
        simble_dict_path: str,
        symbolfont_dict_path: str,
        is_url_book_name: Callable[[str], bool],
    ) -> None:
        self._data_folder = data_folder
        self._simble_dict_path = simble_dict_path
        self._symbolfont_dict_path = symbolfont_dict_path
        self._is_url_book_name = is_url_book_name

    # ------------------------------------------------------------------
    # /api/save_order
    # ------------------------------------------------------------------

    def save_order(self, json_path: str, order_json_str: str, title: Optional[str]) -> int:
        """段落の並び順・タグ・グループ・join フラグを保存する。

        Returns:
            変更されたフィールドの合計数。
        """
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        new_order = json.loads(order_json_str)

        changed_count = 0
        last_processed_item: dict = {}

        for item in new_order:
            page_number = str(item.get("page_number"))
            p_id_str = str(item.get("id"))
            new_order_val = item.get("order")
            new_block_tag = item.get("block_tag")
            new_group_id = item.get("group_id")
            new_join = item.get("join", 0)
            last_processed_item = item

            print(f"Processing ID: {p_id_str}, Order: {new_order_val}, Block Tag: {new_block_tag}, Group ID: {new_group_id}, Join: {new_join}")

            p = book_data["pages"][page_number]["paragraphs"][p_id_str]
            print(f"  Found ID: {p_id_str}, Current Order: {p.get('order')}, Block Tag: {p.get('block_tag')}, Group ID: {p.get('group_id')}, Join: {p.get('join')}")
            updated = False
            if p.get("order") != new_order_val:
                p["order"] = new_order_val
                updated = True
            if new_block_tag is not None and p.get("block_tag") != new_block_tag:
                p["block_tag"] = new_block_tag
                updated = True
            if new_group_id is not None and p.get("group_id") != new_group_id:
                p["group_id"] = new_group_id
                updated = True
            if new_join is not None and p.get("join") != new_join:
                p["join"] = new_join
                updated = True
            if updated:
                changed_count += 1
                print(f"  Updated ID: {p_id_str}")

        if title is not None and book_data.get("title") != title:
            book_data["title"] = title
            changed_count += 1
            print("Title updated.")

        if changed_count > 0:
            temp_file = f"{json_path}.{uuid.uuid4().hex}.tmp"
            try:
                log_p_id = str(last_processed_item.get("id", "N/A"))
                log_order = last_processed_item.get("order", "N/A")
                log_block_tag = last_processed_item.get("block_tag", "N/A")
                log_group_id = last_processed_item.get("group_id", "N/A")
                log_join = last_processed_item.get("join", "N/A")
                print(f"Writing changes to file. Last processed item for logging - ID: {log_p_id}, Order: {log_order}, Block Tag: {log_block_tag}, Group ID: {log_group_id}, Join: {log_join}")

                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(book_data, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, json_path)
            except Exception as e:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                raise

        return changed_count

    # ------------------------------------------------------------------
    # /api/auto_tagging
    # ------------------------------------------------------------------

    def auto_tagging(self, json_path: str, current_page: Optional[int]) -> Optional[dict]:
        """自動タグ付けを実行し、delta を返す。"""
        structure_tagging(json_path, self._simble_dict_path)
        join_flags_in_file(json_path, self._simble_dict_path)

        delta = None
        if current_page is not None:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
            page_key = str(current_page)
            page_obj = (book_data.get("pages", {}) or {}).get(page_key)
            if page_obj is not None:
                delta = {
                    "pages": {page_key: page_obj},
                    "trans_status_counts": book_data.get("trans_status_counts"),
                }

        return delta

    # ------------------------------------------------------------------
    # /api/rebuild_src_text
    # ------------------------------------------------------------------

    def rebuild_src_text(self, json_path: str, current_page: Optional[int]) -> Tuple[int, Optional[dict]]:
        """src_html から src_text を再生成しシンボル置換を適用する。

        Returns:
            (変更段落数, delta or None)
        """
        changed = rebuild_src_text_in_file(json_path, self._symbolfont_dict_path)

        delta = None
        if current_page is not None:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
            page_key = str(current_page)
            page_obj = (book_data.get("pages", {}) or {}).get(page_key)
            if page_obj is not None:
                delta = {
                    "pages": {page_key: page_obj},
                    "trans_status_counts": book_data.get("trans_status_counts"),
                }

        return changed, delta

    # ------------------------------------------------------------------
    # /api/update_block_tags_by_style
    # ------------------------------------------------------------------

    def update_block_tags_by_style(
        self,
        json_path: str,
        target_style: str,
        target_tag: str,
        current_page: Optional[int],
    ) -> Optional[dict]:
        """スタイルによる block_tag 一括更新。

        Returns:
            delta or None
        """
        tag_paragraphs_by_style(json_path, target_style, target_tag)

        delta = None
        if current_page is not None:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
            page_key = str(int(current_page))
            page_obj = (book_data.get("pages", {}) or {}).get(page_key)
            if page_obj is not None:
                delta = {
                    "pages": {page_key: page_obj},
                    "trans_status_counts": book_data.get("trans_status_counts"),
                }

        return delta

    # ------------------------------------------------------------------
    # /api/update_block_tags_by_style_y
    # ------------------------------------------------------------------

    def update_block_tags_by_style_y(
        self,
        json_path: str,
        target_style: str,
        y0: float,
        y1: float,
        action: str,
        current_page: Optional[int],
    ) -> Tuple[int, Optional[dict]]:
        """スタイル + Y 範囲による block_tag 更新（header/footer/remove）。

        Returns:
            (変更段落数, delta or None)
        """
        changed = tag_paragraphs_by_style_y_in_file(json_path, target_style, y0, y1, action)

        delta = None
        if current_page is not None:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
            page_key = str(int(current_page))
            page_obj = (book_data.get("pages", {}) or {}).get(page_key)
            if page_obj is not None:
                delta = {
                    "pages": {page_key: page_obj},
                    "trans_status_counts": book_data.get("trans_status_counts"),
                }

        return changed, delta

    # ------------------------------------------------------------------
    # /api/join_replaced_paragraphs
    # ------------------------------------------------------------------

    def join_replaced_paragraphs(
        self, json_path: str, current_page: Optional[int]
    ) -> Tuple[dict, Optional[dict]]:
        """置換文を結合して保存する。

        Returns:
            (book_data, delta or None)
        """
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        join_apply_all(book_data, sep="", normalize_head=True)
        recalc_trans_status_counts(book_data)
        atomicsave_json(json_path, book_data)

        delta = None
        if current_page is not None:
            page_key = str(current_page)
            page_obj = (book_data.get("pages", {}) or {}).get(page_key)
            if page_obj is not None:
                delta = {
                    "pages": {page_key: page_obj},
                    "trans_status_counts": book_data.get("trans_status_counts"),
                }

        return book_data, delta

    # ------------------------------------------------------------------
    # /api/reextract_table_from_selection
    # ------------------------------------------------------------------

    def reextract_table_from_selection(
        self,
        pdf_name: str,
        json_path: str,
        pdf_path: str,
        page_number: int,
        paragraph_ids: list,
        rows,
        cols,
        header_text,
    ) -> Tuple[int, dict]:
        """選択段落からテーブル行を再抽出して保存する。

        Returns:
            (追加行数, delta)
        Raises:
            ValueError: URLブックの場合、または入力が不正な場合。
        """
        if self._is_url_book_name(pdf_name):
            raise ValueError("URLブックは対象外です")

        page_key = str(page_number)
        book_data = load_json(json_path)
        page_obj = (book_data.get("pages", {}) or {}).get(page_key)
        if not isinstance(page_obj, dict):
            raise LookupError("対象ページが見つかりません")

        page_paragraphs = page_obj.get("paragraphs", {}) or {}
        available_ids = [pid for pid in paragraph_ids if pid in page_paragraphs]
        if len(available_ids) < 1:
            raise LookupError("選択段落が見つかりません")

        table_id = f"p{page_number}_{uuid.uuid4().hex[:8]}"

        with fitz.open(pdf_path) as doc:
            page_index = page_number - 1
            if page_index < 0 or page_index >= len(doc):
                raise ValueError("対象ページ番号が範囲外です")

            page = doc[page_index]
            added = append_markdown_table_rows_from_selection(
                page=page,
                page_number=page_number,
                page_paragraphs=page_paragraphs,
                paragraph_ids=available_ids,
                table_id=table_id,
                rows=rows,
                cols=cols,
                header_text=header_text,
            )

        recalc_trans_status_counts(book_data)
        atomicsave_json(json_path, book_data)

        delta = {
            "pages": {page_key: (book_data.get("pages", {}) or {}).get(page_key)},
            "trans_status_counts": book_data.get("trans_status_counts"),
        }
        return added, delta

    # ------------------------------------------------------------------
    # /api/table_grid_suggest
    # ------------------------------------------------------------------

    def table_grid_suggest(
        self,
        pdf_name: str,
        json_path: str,
        pdf_path: str,
        page_number: int,
        paragraph_ids: list,
        desired_rows,
        desired_cols,
        header_text,
    ) -> dict:
        """テーブルグリッドの推測結果を返す。

        Returns:
            suggest_table_shape_for_selection の戻り値 (dict)
        Raises:
            ValueError: URLブックの場合、または入力が不正な場合。
        """
        if self._is_url_book_name(pdf_name):
            raise ValueError("URLブックは対象外です")

        page_key = str(page_number)
        book_data = load_json(json_path)
        page_obj = (book_data.get("pages", {}) or {}).get(page_key)
        if not isinstance(page_obj, dict):
            raise LookupError("対象ページが見つかりません")

        page_paragraphs = page_obj.get("paragraphs", {}) or {}
        available_ids = [pid for pid in paragraph_ids if pid in page_paragraphs]
        if len(available_ids) < 1:
            raise LookupError("選択段落が見つかりません")

        with fitz.open(pdf_path) as doc:
            page_index = page_number - 1
            if page_index < 0 or page_index >= len(doc):
                raise ValueError("対象ページ番号が範囲外です")

            page = doc[page_index]
            suggestion = suggest_table_shape_for_selection(
                page=page,
                page_paragraphs=page_paragraphs,
                paragraph_ids=available_ids,
                desired_rows=desired_rows,
                desired_cols=desired_cols,
                header_text=str(header_text).strip() if header_text else None,
            )

        return suggestion

    # ------------------------------------------------------------------
    # /api/update_book_info
    # ------------------------------------------------------------------

    def update_book_info(
        self,
        pdf_name: str,
        title: str,
        page_count,
        trans_status_counts,
    ) -> None:
        """settings ファイルのブック情報を更新する。

        Raises:
            FileNotFoundError: settings ファイルが存在しない場合。
            LookupError: pdf_name が settings に存在しない場合。
        """
        settings_path = os.path.join(self._data_folder, "paraparatrans.settings.json")
        if not os.path.exists(settings_path):
            raise FileNotFoundError("settingsファイルが存在しません")

        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)

        if pdf_name not in settings["files"]:
            raise LookupError(f"{pdf_name}がsettingsに存在しません")

        settings["files"][pdf_name]["title"] = title

        if page_count is not None:
            settings["files"][pdf_name]["page_count"] = page_count

        if trans_status_counts is not None:
            settings["files"][pdf_name]["trans_status_counts"] = trans_status_counts

        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # /api/update_paragraph
    # ------------------------------------------------------------------

    def update_paragraph(
        self,
        json_path: str,
        page_number: str,
        paragraph_id: str,
        src_text,
        trans_auto,
        trans_text,
        comment,
        status: str,
        block_tag,
        new_join,
        markup,
    ) -> Tuple[dict, bool]:
        """単一段落の翻訳を保存する。

        Returns:
            (trans_status_counts, reload_book_data)
        """
        book_data = load_json(json_path)

        paragraph = book_data["pages"][page_number]["paragraphs"][paragraph_id]
        if not paragraph:
            raise LookupError("該当パラグラフが見つかりません")

        old_status = paragraph.get("trans_status", "none")
        old_status_norm = _normalize_trans_status(old_status)
        can_delta = _is_trans_status_counts_usable_for_delta(book_data)
        if can_delta:
            try:
                if int(book_data["trans_status_counts"].get(old_status_norm, 0)) <= 0:
                    can_delta = False
            except Exception:
                can_delta = False

        old_src_text = "" if paragraph.get("src_text") is None else str(paragraph.get("src_text"))
        new_src_text_norm = "" if src_text is None else str(src_text)

        paragraph["src_text"] = new_src_text_norm
        if old_src_text != new_src_text_norm:
            paragraph["src_joined"] = new_src_text_norm
            paragraph["src_replaced"] = new_src_text_norm
        paragraph["trans_auto"] = trans_auto
        paragraph["trans_text"] = trans_text
        if comment is not None:
            paragraph["comment"] = comment
        paragraph["trans_status"] = status
        paragraph["block_tag"] = block_tag
        if isinstance(markup, list):
            paragraph["markup"] = markup

        join_changed = False
        if new_join is not None:
            try:
                desired_join = 1 if int(new_join) == 1 else 0
            except Exception:
                desired_join = 0
            old_join = 1 if int(paragraph.get("join", 0)) == 1 else 0
            if old_join != desired_join:
                refs = join_iter_paragraph_refs(book_data)
                index = join_build_index(refs)
                join_apply_change(
                    book_data,
                    (page_number, paragraph_id),
                    desired_join,
                    refs=refs,
                    index=index,
                    sep="",
                    normalize_head=True,
                )
                join_changed = True

                if desired_join == 0:
                    try:
                        if "join" in paragraph:
                            del paragraph["join"]
                    except Exception:
                        pass

        paragraph["modified_at"] = datetime.datetime.now().isoformat()

        if join_changed:
            recalc_trans_status_counts(book_data)
            can_delta = False
        elif can_delta:
            _apply_trans_status_delta(book_data, old_status, status)
        else:
            recalc_trans_status_counts(book_data)

        atomicsave_json(json_path, book_data)
        return book_data.get("trans_status_counts"), bool(join_changed)

    # ------------------------------------------------------------------
    # /api/update_paragraphs
    # ------------------------------------------------------------------

    def update_paragraphs(
        self,
        json_path: str,
        title: Optional[str],
        paragraphs: list,
    ) -> Tuple[dict, bool]:
        """複数段落を一括更新する。

        Returns:
            (trans_status_counts, reload_book_data)
        """
        book_data = load_json(json_path)

        if title is not None:
            book_data["title"] = title

        def _apply_update(p: dict, upd_value: dict) -> None:
            p["modified_at"] = datetime.datetime.now().isoformat()
            p["src_text"] = upd_value.get("src_text", p.get("src_text"))
            p["trans_text"] = upd_value.get("trans_text", p.get("trans_text"))
            p["comment"] = upd_value.get("comment", p.get("comment", ""))
            p["trans_status"] = upd_value.get("trans_status", p.get("trans_status"))
            p["order"] = upd_value.get("order", p.get("order"))
            p["block_tag"] = upd_value.get("block_tag", p.get("block_tag"))

            group_id = upd_value.get("group_id", None)
            if group_id is not None:
                p["group_id"] = group_id
            elif "group_id" in p:
                del p["group_id"]

        join_updates = []

        can_delta = _is_trans_status_counts_usable_for_delta(book_data)
        if can_delta:
            _ensure_trans_status_counts(book_data)

        for request_paragraph in paragraphs:
            page_number = str(request_paragraph.get("page_number"))
            paragraph_id = str(request_paragraph.get("id"))
            paragraph_dict = book_data["pages"][page_number]["paragraphs"][paragraph_id]

            desired_join = 1 if request_paragraph.get("join") == 1 else 0
            old_join = 1 if int(paragraph_dict.get("join", 0)) == 1 else 0
            if old_join != desired_join:
                join_updates.append((page_number, paragraph_id, desired_join))

            old_status = paragraph_dict.get("trans_status", "none")
            if can_delta:
                old_status_norm = _normalize_trans_status(old_status)
                try:
                    if int(book_data["trans_status_counts"].get(old_status_norm, 0)) <= 0:
                        can_delta = False
                except Exception:
                    can_delta = False
            _apply_update(paragraph_dict, request_paragraph)
            new_status = paragraph_dict.get("trans_status", "none")
            if can_delta:
                _apply_trans_status_delta(book_data, old_status, new_status)

        join_changed = False
        if join_updates:
            refs = join_iter_paragraph_refs(book_data)
            index = join_build_index(refs)
            for page_number, paragraph_id, desired_join in join_updates:
                join_apply_change(
                    book_data,
                    (page_number, paragraph_id),
                    desired_join,
                    refs=refs,
                    index=index,
                    sep="",
                    normalize_head=True,
                )
                join_changed = True

                if desired_join == 0:
                    try:
                        p = book_data["pages"][page_number]["paragraphs"][paragraph_id]
                        if "join" in p:
                            del p["join"]
                    except Exception:
                        pass

        if join_changed:
            recalc_trans_status_counts(book_data)
            can_delta = False
        elif not can_delta:
            recalc_trans_status_counts(book_data)

        atomicsave_json(json_path, book_data)
        return book_data.get("trans_status_counts"), bool(join_changed)

    # ------------------------------------------------------------------
    # /api/delete_paragraphs
    # ------------------------------------------------------------------

    def delete_paragraphs(
        self,
        json_path: str,
        paragraphs: list,
    ) -> Tuple[int, dict]:
        """選択したパラグラフを削除する。

        Returns:
            (削除数, trans_status_counts)
        """
        book_data = load_json(json_path)

        deleted_count = 0
        for request_paragraph in paragraphs:
            page_number = str(request_paragraph.get("page_number"))
            paragraph_id = str(request_paragraph.get("id"))

            if page_number not in book_data["pages"]:
                continue

            page_paragraphs = book_data["pages"][page_number]["paragraphs"]
            if paragraph_id in page_paragraphs:
                del page_paragraphs[paragraph_id]
                deleted_count += 1

        recalc_trans_status_counts(book_data)

        affected_pages = set(str(p.get("page_number")) for p in paragraphs)
        for page_number in affected_pages:
            if page_number not in book_data["pages"]:
                continue
            page_paragraphs = book_data["pages"][page_number]["paragraphs"]
            sorted_paragraphs = sorted(
                page_paragraphs.values(),
                key=lambda x: x.get("order", 0),
            )
            for i, paragraph in enumerate(sorted_paragraphs, start=1):
                paragraph["order"] = i

        atomicsave_json(json_path, book_data)
        return deleted_count, book_data.get("trans_status_counts")
