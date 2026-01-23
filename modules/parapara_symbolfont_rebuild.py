#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""parapara_symbolfont_rebuild.py

目的
----
parapara JSON の各段落について、`src_html` を元に `src_text` を再生成し、
シンボルフォント由来の ASCII 文字をフォント別の置換文字列に置換します。

- 抽出時にしか補正できない問題を避けるため「後工程」で何度でも適用できます。
- 何がシンボルフォントかは `symbolfont_dict.txt` のフォント名群（キー）で判断します。

辞書ファイル形式
----------------
各行: `フォント名.キャラクター\t置換後文字列`
例:
  Wingdings.a\t■
  Wingdings.b\t▲

注意:
- `src_html` は `<span class="Font_Name_0100">text</span>` の連結であることを前提。
- フォント名は大小や空白/アンダースコア差を吸収して照合します。

使い方
------
  python modules/parapara_symbolfont_rebuild.py path/to/book.json [path/to/symbolfont_dict.txt]

動作
----
- `src_text` を更新。
- `src_joined` / `src_replaced` / `trans_auto` / `trans_text` は、値が旧 `src_text` と同一の場合のみ追従更新します。
"""

import argparse
import html
import json
import os
import re
import tempfile
from typing import Dict, Iterable, Iterator, Tuple


_SPAN_RE = re.compile(r'<span class="([^"]+)">(.*?)</span>', re.DOTALL)


def _normalize_font_name(font_name: str) -> str:
    # class は空白を '_' にしているので両方を吸収
    return re.sub(r"\s+", " ", font_name.replace("_", " ").strip()).casefold()


def _font_from_class(span_class: str) -> str:
    # create_paragraph の class は `${font_with_underscores}_${size_str}`
    # 末尾 `_<4桁数字>` を除去する
    m = re.match(r"^(.*)_\d{4}$", span_class)
    base = m.group(1) if m else span_class
    return base


def load_symbolfont_dict(dict_path: str) -> Dict[str, Dict[str, str]]:
    """symbolfont_dict.txt を読み込んで {norm_font: {char: replacement}} を返す。"""
    if not dict_path:
        raise ValueError("dict_path is required")
    if not os.path.exists(dict_path):
        raise FileNotFoundError(f"symbolfont_dict not found: {dict_path}")

    grouped: Dict[str, Dict[str, str]] = {}
    with open(dict_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" not in line:
                continue
            key, value = line.split("\t", 1)
            key = key.strip()
            value = value.rstrip("\r").strip()
            if not key:
                continue

            # key: FontName.char (char は1文字想定だが、最後の '.' で分割)
            if "." not in key:
                continue
            font_name, ch = key.rsplit(".", 1)
            font_name = font_name.strip()
            if not font_name or ch == "":
                continue

            norm_font = _normalize_font_name(font_name)
            grouped.setdefault(norm_font, {})[ch] = value

    return grouped


def iter_spans_from_src_html(src_html: str) -> Iterator[Tuple[str, str]]:
    """src_html から (span_class, text) を順に取り出す。"""
    if not src_html:
        return
    for m in _SPAN_RE.finditer(src_html):
        span_class = m.group(1)
        text = m.group(2)
        yield span_class, text


def rebuild_src_text_from_src_html(src_html: str, symbolfont_map: Dict[str, Dict[str, str]]) -> str:
    """src_html を元に src_text を再生成する（シンボルフォント置換込み）。"""
    if not src_html:
        return ""

    out_parts = []
    for span_class, raw_text in iter_spans_from_src_html(src_html):
        # HTML エスケープが入るケースにも一応対応（通常は入っていない想定）
        text = html.unescape(raw_text)

        font_from_class = _font_from_class(span_class)
        norm_font = _normalize_font_name(font_from_class)
        replace_table = symbolfont_map.get(norm_font)

        # 既存仕様に合わせてタブは '|' にする
        text = text.replace("\t", "|")

        if not replace_table:
            out_parts.append(text)
            continue

        # 文字単位で置換（見つからなければ原文のまま）
        replaced = "".join(replace_table.get(ch, ch) for ch in text)
        out_parts.append(replaced)

    return "".join(out_parts)


def rebuild_src_text_in_book_data(
    book_data: dict,
    symbolfont_map: Dict[str, Dict[str, str]],
    *,
    follow_fields: Tuple[str, ...] = ("src_joined", "src_replaced", "trans_auto", "trans_text"),
) -> int:
    """book_data を in-place 更新し、変更した段落数を返す。"""
    changed = 0

    for page in book_data.get("pages", {}).values():
        paragraphs = page.get("paragraphs", {})
        for para in paragraphs.values():
            src_html = para.get("src_html", "")
            if not src_html:
                continue

            old_src_text = para.get("src_text", "")
            new_src_text = rebuild_src_text_from_src_html(src_html, symbolfont_map)

            if new_src_text == old_src_text:
                continue

            para["src_text"] = new_src_text

            # 旧src_textと同じ値だった派生フィールドだけ追従更新
            for field in follow_fields:
                if para.get(field) == old_src_text:
                    para[field] = new_src_text

            changed += 1

    return changed


def load_json(json_path: str) -> dict:
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"{json_path} not found")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def atomicsave_json(json_path: str, data: dict) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(json_path), suffix=".json", text=True)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
            json.dump(data, tmp_file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, json_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def rebuild_src_text_in_file(json_path: str, symbolfont_dict_path: str) -> int:
    book_data = load_json(json_path)
    symbolfont_map = load_symbolfont_dict(symbolfont_dict_path)
    changed = rebuild_src_text_in_book_data(book_data, symbolfont_map)
    if changed:
        atomicsave_json(json_path, book_data)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="src_html から src_text を再生成し、シンボルフォント置換を適用")
    parser.add_argument("json_file", help="対象 JSON ファイル")
    parser.add_argument(
        "symbolfont_dict",
        nargs="?",
        default=os.path.join("config", "symbolfont_dict.txt"),
        help="symbolfont_dict.txt（省略時: config/symbolfont_dict.txt）",
    )
    args = parser.parse_args()

    changed = rebuild_src_text_in_file(args.json_file, args.symbolfont_dict)
    print(f"Updated paragraphs: {changed}")


if __name__ == "__main__":
    main()
