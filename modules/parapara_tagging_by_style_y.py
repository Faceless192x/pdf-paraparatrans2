import argparse
import json
import os
import sys
import tempfile
from typing import Any, Dict, Tuple


_ALLOWED_ACTIONS = {"header", "footer", "remove"}

# bbox の微小差を吸収するための許容誤差（pt相当）
_Y_EPSILON = 1.0


def _normalize_action(action: str) -> str:
    a = (action or "").strip().lower()
    if a not in _ALLOWED_ACTIONS:
        raise ValueError(f"action must be one of {_ALLOWED_ACTIONS}, got: {action!r}")
    return a


def _extract_y0_y1_from_paragraph(paragraph: Dict[str, Any]) -> Tuple[float, float]:
    bbox = paragraph.get("bbox")
    if not (isinstance(bbox, (list, tuple)) and len(bbox) >= 4):
        raise ValueError("paragraph does not have a valid bbox")
    # bbox = [x0, y0, x1, y1]
    return float(bbox[1]), float(bbox[3])


def tag_paragraphs_by_style_y(
    book_data: Dict[str, Any],
    target_style: str,
    y0: float,
    y1: float,
    action: str,
) -> int:
    """指定スタイルかつY範囲内の段落に block_tag を設定する。

    Args:
        book_data: JSONをdictで読み込んだデータ。
        target_style: 対象の base_style。
        y0: 対象範囲の上端（bbox[1]）。
        y1: 対象範囲の下端（bbox[3]）。
        action: "header" | "footer" | "remove"。

    Returns:
        変更された段落数。

    Notes:
        - 判定は「段落bboxが指定範囲に完全に含まれる」(y0 <= para_y0 and para_y1 <= y1)
        - action=remove の場合は block_tag を "p" に戻す
    """
    if target_style is None or str(target_style).strip() == "":
        raise ValueError("target_style is required")

    action = _normalize_action(action)

    y0 = float(y0)
    y1 = float(y1)
    if y0 > y1:
        # 入力ミスの救済（上限/下限を逆に入れても動く）
        y0, y1 = y1, y0

    # remove は block_tag="remove" として保持する（UI上の意図を残す）
    new_tag = action

    y0_min = y0 - _Y_EPSILON
    y1_max = y1 + _Y_EPSILON

    changed = 0
    pages = book_data.get("pages") or {}
    for page_data in pages.values():
        paragraphs = (page_data or {}).get("paragraphs") or {}
        for paragraph in paragraphs.values():
            if paragraph.get("base_style") != target_style:
                continue

            try:
                para_y0, para_y1 = _extract_y0_y1_from_paragraph(paragraph)
            except Exception:
                # bboxが無い/壊れている段落は対象外
                continue

            # 同一範囲判定は、浮動小数点の微小差を許容する。
            if not (y0_min <= para_y0 and para_y1 <= y1_max):
                continue

            if paragraph.get("block_tag") != new_tag:
                paragraph["block_tag"] = new_tag
                changed += 1

    # header/footer/remove の場合は、ページ内の並び順も調整する。
    # - header は先頭、footer は末尾、remove は footer よりさらに後ろ(末尾) に寄せる
    if action in ("header", "footer", "remove"):
        for page_data in pages.values():
            _reorder_page_paragraphs_for_special_tags(page_data)

    return changed


def _reorder_page_paragraphs_for_special_tags(page_data: Dict[str, Any]) -> None:
    """ページ内で header/footer/remove を所定位置へ寄せ、order を振り直す。

    - header: 先頭へ（複数なら Y0 昇順）
    - footer: 末尾へ（複数なら Y1 昇順）
    - remove: footer よりさらに後ろの末尾へ（複数なら Y1 昇順）
    """
    if not isinstance(page_data, dict):
        return
    paragraphs_dict = page_data.get("paragraphs")
    if not isinstance(paragraphs_dict, dict) or not paragraphs_dict:
        return

    paragraphs = list(paragraphs_dict.values())

    def _safe_bbox(p: Dict[str, Any]):
        bbox = p.get("bbox") if isinstance(p.get("bbox"), (list, tuple)) else None
        if not (bbox and len(bbox) >= 4):
            return None
        return bbox

    def sort_key(p: Dict[str, Any]):
        bbox = _safe_bbox(p)
        y0 = float(bbox[1]) if bbox else 0.0
        return (
            int(p.get("order", 0) or 0),
            int(p.get("column_order", 0) or 0),
            y0,
        )

    def header_key(p: Dict[str, Any]):
        bbox = _safe_bbox(p)
        y0 = float(bbox[1]) if bbox else 0.0
        y1 = float(bbox[3]) if bbox else 0.0
        return (y0, y1, int(p.get("column_order", 0) or 0), int(p.get("order", 0) or 0))

    def footer_key(p: Dict[str, Any]):
        bbox = _safe_bbox(p)
        y0 = float(bbox[1]) if bbox else 0.0
        y1 = float(bbox[3]) if bbox else 0.0
        return (y1, y0, int(p.get("column_order", 0) or 0), int(p.get("order", 0) or 0))

    paragraphs.sort(key=sort_key)

    head = [p for p in paragraphs if p.get("block_tag") == "header"]
    tail = [p for p in paragraphs if p.get("block_tag") == "footer"]
    removed = [p for p in paragraphs if p.get("block_tag") == "remove"]
    middle = [p for p in paragraphs if p.get("block_tag") not in ("header", "footer", "remove")]

    head.sort(key=header_key)
    tail.sort(key=footer_key)
    removed.sort(key=footer_key)

    new_list = head + middle + tail + removed

    for i, p in enumerate(new_list, start=1):
        p["order"] = i


def load_json(json_path: str) -> Dict[str, Any]:
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"{json_path} not found")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def atomicsave_json(json_path: str, data: Dict[str, Any]) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(json_path), suffix=".json", text=True)
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
        json.dump(data, tmp_file, ensure_ascii=False, indent=2)
    os.replace(tmp_path, json_path)


def tag_paragraphs_by_style_y_in_file(
    json_file_path: str,
    target_style: str,
    y0: float,
    y1: float,
    action: str,
) -> int:
    book_data = load_json(json_file_path)
    changed = tag_paragraphs_by_style_y(book_data, target_style, y0, y1, action)

    # header/footer/remove は order の振り直しが発生しうるため、タグ変更0件でも保存する。
    if changed or str(action).strip().lower() in ("header", "footer", "remove"):
        atomicsave_json(json_file_path, book_data)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="指定スタイル + Y範囲で段落の block_tag を header/footer/p(remove) に一括設定します"
    )
    parser.add_argument("json_file_path")
    parser.add_argument("target_style")
    parser.add_argument("y0", type=float)
    parser.add_argument("y1", type=float)
    parser.add_argument("action", choices=sorted(_ALLOWED_ACTIONS))

    args = parser.parse_args(argv)

    changed = tag_paragraphs_by_style_y_in_file(
        args.json_file_path,
        args.target_style,
        args.y0,
        args.y1,
        args.action,
    )
    print(f"updated: {changed} paragraphs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
