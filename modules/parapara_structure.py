from __future__ import annotations

import datetime
import json
import os
import shutil
from typing import Any, Dict, Tuple


STRUCTURE_EXCLUDE_KEYS = {
    # 原文/派生原文（著作権配慮＆共同作業用に除外）
    "src_html",
    "src_text",  # ユーザー文言の src_trxt 想定
    "src_trxt",  # 念のため（typo互換）
    "src_joined",
    "src_replaced",
    # 翻訳
    "trans_auto",
    "trans_text",
}


def ensure_backup_copy(json_path: str, *, backup_dir: str) -> str:
    """更新前に backup_dir に原本を退避する。戻り値はバックアップ先パス。"""
    os.makedirs(backup_dir, exist_ok=True)

    base = os.path.basename(json_path)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(backup_dir, f"{base}.{ts}.bak.json")
    shutil.copy2(json_path, backup_path)
    return backup_path


def strip_structure(obj: Any, *, exclude_keys=STRUCTURE_EXCLUDE_KEYS) -> Any:
    """structure ファイル用に、指定キーを再帰的に除去したコピーを返す。"""
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if k in exclude_keys:
                continue
            out[k] = strip_structure(v, exclude_keys=exclude_keys)
        return out
    if isinstance(obj, list):
        return [strip_structure(v, exclude_keys=exclude_keys) for v in obj]
    return obj


def merge_structure_into_book(
    book_data: Dict[str, Any],
    imported: Dict[str, Any],
    *,
    exclude_keys=STRUCTURE_EXCLUDE_KEYS,
) -> Tuple[Dict[str, Any], Dict[str, int], bool]:
    """imported(structure) の内容で book_data を更新する。

    - exclude_keys は更新しない（存在しても無視）
    - pages/paragraphs は既存キーのみ更新（新規追加はしない）

    戻り値: (updated_book_data, stats_dict, join_changed_bool)
    """

    stats: Dict[str, int] = {
        "pages_ignored": 0,
        "paragraphs_ignored": 0,
        "paragraphs_updated": 0,
        "keys_updated": 0,
    }
    join_changed = False

    def merge(dst: Any, src: Any, *, path: str = "") -> None:
        nonlocal join_changed
        if not isinstance(dst, dict) or not isinstance(src, dict):
            return

        for k, sv in src.items():
            if k in exclude_keys:
                continue

            # pages/paragraphs は既存キーのみ更新
            if k == "pages" and isinstance(sv, dict) and isinstance(dst.get("pages"), dict):
                for page_key, s_page in sv.items():
                    if page_key not in dst["pages"]:
                        stats["pages_ignored"] += 1
                        continue
                    merge(dst["pages"][page_key], s_page, path=f"{path}/pages/{page_key}")
                continue

            if k == "paragraphs" and isinstance(sv, dict) and isinstance(dst.get("paragraphs"), dict):
                for para_key, s_para in sv.items():
                    if para_key not in dst["paragraphs"]:
                        stats["paragraphs_ignored"] += 1
                        continue
                    d_para = dst["paragraphs"][para_key]
                    if isinstance(d_para, dict) and isinstance(s_para, dict):
                        old_join = 1 if int(d_para.get("join", 0) or 0) == 1 else 0
                        merge(d_para, s_para, path=f"{path}/paragraphs/{para_key}")
                        new_join = 1 if int(d_para.get("join", 0) or 0) == 1 else 0
                        if old_join != new_join:
                            join_changed = True
                        stats["paragraphs_updated"] += 1
                    continue
                continue

            dv = dst.get(k)
            if isinstance(dv, dict) and isinstance(sv, dict):
                merge(dv, sv, path=f"{path}/{k}")
                continue

            # それ以外は上書き
            dst[k] = sv
            stats["keys_updated"] += 1

    merge(book_data, imported)
    return book_data, stats, join_changed


def load_json_from_upload(upload_file) -> Dict[str, Any]:
    """Flaskの upload file から JSON object を読む（例外は呼び出し側で処理）。"""
    return json.load(upload_file)
