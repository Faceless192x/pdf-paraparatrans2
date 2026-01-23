#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""parapara_align_trans_by_src_joined.py

同一 `src_joined` を持つ段落の翻訳情報を揃える。

- 同じ `src_joined` の中で、より上位の `trans_status` を持つ段落を代表とする
- `trans_status` が同一で `trans_text` が異なる場合は先勝ち（先に見つかった段落を代表）
- 同グループ内の全段落の `trans_auto` / `trans_text` / `trans_status` を代表に合わせる

想定ステータス順: none < auto < draft < fixed

Usage:
    python modules/parapara_align_trans_by_src_joined.py path/to/book.json

Example as function:
    from parapara_align_trans_by_src_joined import align_translations_by_src_joined_in_file
    align_translations_by_src_joined_in_file("data.json")
"""

import os
import json
import tempfile
import argparse
from typing import Dict, Tuple, Any


_STATUS_RANK = {"none": 0, "auto": 1, "draft": 2, "fixed": 3}


def _rank(status: Any) -> int:
    return _STATUS_RANK.get(str(status or "none"), 0)


def load_json(json_path: str) -> dict:
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"{json_path} not found")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def atomicsave_json(json_path: str, data: dict) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(json_path), suffix=".json", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
        json.dump(data, tmp_file, ensure_ascii=False, indent=2)
    os.replace(tmp_path, json_path)


def align_translations_by_src_joined(book_data: dict) -> Tuple[dict, int]:
    """book_data を in-place 更新し、(book_data, 変更件数) を返す。"""

    best_by_src: Dict[str, Tuple[int, str, str]] = {}

    pages = book_data.get("pages", {}) or {}

    for page_key in pages:
        page = pages.get(page_key, {}) or {}
        paragraphs = (page.get("paragraphs", {}) or {}).values()
        for p in paragraphs:
            src = p.get("src_joined")
            if not src:
                continue

            status = p.get("trans_status", "none")
            r = _rank(status)
            trans_text = p.get("trans_text", "")
            trans_auto = p.get("trans_auto", "")

            if src not in best_by_src:
                best_by_src[src] = (r, trans_text, trans_auto)
                continue

            best_r, _, _ = best_by_src[src]
            if r > best_r:
                best_by_src[src] = (r, trans_text, trans_auto)

    changed = 0
    for page_key in pages:
        page = pages.get(page_key, {}) or {}
        paragraphs = (page.get("paragraphs", {}) or {}).values()
        for p in paragraphs:
            src = p.get("src_joined")
            if not src:
                continue
            best = best_by_src.get(src)
            if not best:
                continue

            best_r, best_text, best_auto = best
            best_status = next((k for k, v in _STATUS_RANK.items() if v == best_r), "none")

            before = (p.get("trans_status"), p.get("trans_text"), p.get("trans_auto"))
            p["trans_status"] = best_status
            p["trans_text"] = best_text
            p["trans_auto"] = best_auto
            after = (p.get("trans_status"), p.get("trans_text"), p.get("trans_auto"))

            if before != after:
                changed += 1

    return book_data, changed


def align_translations_by_src_joined_in_file(json_file: str) -> dict:
    data = load_json(json_file)
    align_translations_by_src_joined(data)
    atomicsave_json(json_file, data)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="同一 src_joined の翻訳情報を代表訳に揃える")
    parser.add_argument("json_file", help="入力・出力共通の JSON ファイルパス")
    args = parser.parse_args()

    data = load_json(args.json_file)
    _, changed = align_translations_by_src_joined(data)
    atomicsave_json(args.json_file, data)

    print(f"Aligned translations by src_joined: updated {changed} paragraphs")


if __name__ == "__main__":
    main()
