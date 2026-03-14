#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import bisect
from dataclasses import dataclass
from html import escape
from typing import Any, Dict, Iterable, List, Optional, Tuple

import fitz


@dataclass
class TableRangeSpec:
    start_id: str
    end_id: str
    table_id: str = ""


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_pos_int(value: Any, default: int = 1) -> int:
    try:
        iv = int(value)
        return iv if iv > 0 else default
    except Exception:
        return default


def _sorted_paragraph_items(page_paragraphs: Dict[str, Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    return sorted(
        page_paragraphs.items(),
        key=lambda kv: (
            _safe_int(kv[1].get("order"), 0),
            _safe_float((kv[1].get("bbox") or [0, 0, 0, 0])[1], 0.0),
            str(kv[0]),
        ),
    )


def _normalize_specs(specs: Iterable[Any]) -> List[TableRangeSpec]:
    normalized: List[TableRangeSpec] = []
    for i, raw in enumerate(specs):
        if not isinstance(raw, dict):
            continue

        start_id = str(raw.get("start_id") or raw.get("start") or "").strip()
        end_id = str(raw.get("end_id") or raw.get("end") or "").strip()
        if not start_id or not end_id:
            continue

        table_id = str(raw.get("table_id") or f"table_{i + 1}").strip()
        normalized.append(TableRangeSpec(start_id=start_id, end_id=end_id, table_id=table_id))
    return normalized


def _normalize_selected_ids(paragraph_ids: Iterable[Any]) -> List[str]:
    normalized = []
    for raw in paragraph_ids or []:
        text = str(raw or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _get_selected_paragraphs_in_order(
    page_paragraphs: Dict[str, Dict[str, Any]],
    paragraph_ids: Iterable[Any],
) -> List[Dict[str, Any]]:
    selected_ids = set(_normalize_selected_ids(paragraph_ids))
    if not selected_ids:
        return []

    ordered = _sorted_paragraph_items(page_paragraphs)
    selected = []
    for key, para in ordered:
        para_id = str(para.get("id") or key)
        if para_id in selected_ids:
            selected.append(para)
    return selected


def _union_rect_from_paragraphs(paragraphs: List[Dict[str, Any]]) -> Optional[fitz.Rect]:
    rect: Optional[fitz.Rect] = None
    for p in paragraphs:
        bbox = p.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        try:
            current = fitz.Rect(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except Exception:
            continue

        if rect is None:
            rect = current
        else:
            rect = fitz.Rect(
                min(rect.x0, current.x0),
                min(rect.y0, current.y0),
                max(rect.x1, current.x1),
                max(rect.y1, current.y1),
            )
    return rect


def build_selection_rect_from_paragraph_ids(
    page_paragraphs: Dict[str, Dict[str, Any]],
    paragraph_ids: Iterable[Any],
) -> Optional[fitz.Rect]:
    selected = _get_selected_paragraphs_in_order(page_paragraphs, paragraph_ids)
    return _union_rect_from_paragraphs(selected)


def _cluster_rows(words: List[Tuple[Any, ...]]) -> List[List[Tuple[Any, ...]]]:
    if not words:
        return []

    rows: List[List[Tuple[Any, ...]]] = []
    heights = [max(1.0, float(w[3]) - float(w[1])) for w in words]
    median_h = sorted(heights)[len(heights) // 2]
    y_tol = max(2.0, median_h * 0.55)

    words_sorted = sorted(words, key=lambda w: ((float(w[1]) + float(w[3])) / 2.0, float(w[0])))

    for w in words_sorted:
        yc = (float(w[1]) + float(w[3])) / 2.0
        if not rows:
            rows.append([w])
            continue

        last_row = rows[-1]
        last_y = sum((float(x[1]) + float(x[3])) / 2.0 for x in last_row) / len(last_row)
        if abs(yc - last_y) <= y_tol:
            last_row.append(w)
        else:
            rows.append([w])

    for row in rows:
        row.sort(key=lambda w: float(w[0]))
    return rows


def _split_row_to_cells(row_words: List[Tuple[Any, ...]]) -> List[Tuple[str, List[float]]]:
    if not row_words:
        return []

    gaps: List[float] = []
    for i in range(1, len(row_words)):
        prev = row_words[i - 1]
        curr = row_words[i]
        gaps.append(max(0.0, float(curr[0]) - float(prev[2])))

    gap_threshold = 18.0
    if gaps:
        sorted_gaps = sorted(gaps)
        q2 = sorted_gaps[len(sorted_gaps) // 2]
        q3 = sorted_gaps[(len(sorted_gaps) * 3) // 4]
        gap_threshold = max(18.0, q2 + (q3 - q2) * 1.5)

    cells: List[List[Tuple[Any, ...]]] = []
    current: List[Tuple[Any, ...]] = [row_words[0]]
    for i in range(1, len(row_words)):
        prev = row_words[i - 1]
        curr = row_words[i]
        gap = max(0.0, float(curr[0]) - float(prev[2]))
        if gap > gap_threshold:
            cells.append(current)
            current = [curr]
        else:
            current.append(curr)
    cells.append(current)

    result: List[Tuple[str, List[float]]] = []
    for cell in cells:
        text = " ".join(str(w[4]) for w in cell if str(w[4]).strip()).strip()
        if not text:
            continue
        x0 = min(float(w[0]) for w in cell)
        y0 = min(float(w[1]) for w in cell)
        x1 = max(float(w[2]) for w in cell)
        y1 = max(float(w[3]) for w in cell)
        result.append((text, [x0, y0, x1, y1]))
    return result


def _to_markdown_row(cells: List[str]) -> str:
    escaped = [c.replace("|", "\\|").strip() for c in cells]
    return "| " + " | ".join(escaped) + " |"


def _median(values: List[float], default: float = 0.0) -> float:
    if not values:
        return default
    arr = sorted(values)
    n = len(arr)
    m = n // 2
    if n % 2 == 1:
        return float(arr[m])
    return float((arr[m - 1] + arr[m]) / 2.0)


def _percentile(values: List[float], p: float, default: float = 0.0) -> float:
    if not values:
        return default
    arr = sorted(values)
    if len(arr) == 1:
        return float(arr[0])
    idx = max(0.0, min(1.0, p)) * (len(arr) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(arr) - 1)
    t = idx - lo
    return float(arr[lo] * (1.0 - t) + arr[hi] * t)


def _kmeans_1d(values: List[float], k: int, iterations: int = 20) -> List[float]:
    if not values:
        return []
    uniq = sorted(set(float(v) for v in values))
    if not uniq:
        return []
    k = max(1, min(int(k), len(uniq)))
    if k == 1:
        return [_median(uniq, 0.0)]

    centers = []
    for i in range(k):
        q = i / (k - 1)
        centers.append(_percentile(uniq, q, uniq[0]))

    for _ in range(max(1, iterations)):
        buckets: List[List[float]] = [[] for _ in range(k)]
        for v in values:
            dist = [abs(float(v) - c) for c in centers]
            idx = dist.index(min(dist))
            buckets[idx].append(float(v))

        new_centers = centers[:]
        for i in range(k):
            if buckets[i]:
                new_centers[i] = sum(buckets[i]) / len(buckets[i])

        if all(abs(new_centers[i] - centers[i]) <= 1e-6 for i in range(k)):
            centers = new_centers
            break
        centers = new_centers

    return sorted(float(c) for c in centers)


def _build_row_groups(words: List[Tuple[Any, ...]], desired_rows: Optional[int] = None) -> List[List[Tuple[Any, ...]]]:
    if not words:
        return []

    if desired_rows is None:
        return _cluster_rows(words)

    k = max(1, int(desired_rows))
    y_centers = [((float(w[1]) + float(w[3])) / 2.0) for w in words]
    centers = _kmeans_1d(y_centers, k)
    if not centers:
        return _cluster_rows(words)

    groups: List[List[Tuple[Any, ...]]] = [[] for _ in range(len(centers))]
    for w in words:
        yc = (float(w[1]) + float(w[3])) / 2.0
        idx = min(range(len(centers)), key=lambda i: abs(yc - centers[i]))
        groups[idx].append(w)

    indexed = []
    for i, g in enumerate(groups):
        if g:
            gy = sum((float(x[1]) + float(x[3])) / 2.0 for x in g) / len(g)
        else:
            gy = centers[i]
        indexed.append((gy, g))
    indexed.sort(key=lambda it: it[0])

    sorted_groups = [g for _, g in indexed]
    for g in sorted_groups:
        g.sort(key=lambda w: float(w[0]))
    return sorted_groups


def _cluster_1d_points(points: List[float], tolerance: float) -> List[float]:
    if not points:
        return []
    arr = sorted(float(p) for p in points)
    tolerance = max(1.0, float(tolerance))

    out: List[List[float]] = [[arr[0]]]
    for p in arr[1:]:
        cur = out[-1]
        if abs(p - (sum(cur) / len(cur))) <= tolerance:
            cur.append(p)
        else:
            out.append([p])
    return [sum(c) / len(c) for c in out]


def _extract_header_text_from_first_row(
    row_groups: List[List[Tuple[Any, ...]]],
    col_edges: Optional[List[float]] = None
) -> str:
    """最初の行の単語を列境界に基づいてカンマ区切りで結合"""
    if not row_groups or not row_groups[0]:
        return ""
    
    first_row = sorted(row_groups[0], key=lambda w: float(w[0]))
    
    # 列境界が指定されていない場合はスペース区切りで結合
    if not col_edges or len(col_edges) < 2:
        return " ".join(str(w[4]).strip() for w in first_row if str(w[4]).strip())
    
    # 列境界に基づいて単語をグループ化
    col_count = len(col_edges) - 1
    col_words: List[List[str]] = [[] for _ in range(col_count)]
    
    for word in first_row:
        xc = (float(word[0]) + float(word[2])) / 2.0
        col_idx = 0
        for i in range(len(col_edges) - 1):
            if col_edges[i] <= xc < col_edges[i + 1]:
                col_idx = i
                break
            elif xc >= col_edges[-1]:
                col_idx = len(col_edges) - 2
                break
        
        text = str(word[4]).strip()
        if text:
            col_words[col_idx].append(text)
    
    # 各列の単語をスペース区切りで結合し、列間をカンマで区切る
    col_texts = [" ".join(words) for words in col_words]
    return ",".join(col_texts)


def _estimate_columns_from_header_segments(
    header_text: str,
    words: List[Tuple[Any, ...]],
    clip_rect: fitz.Rect,
    row_groups: List[List[Tuple[Any, ...]]],
) -> List[float]:
    """カンマ区切りヘッダから列境界を推定"""
    if not header_text or not row_groups:
        return [float(clip_rect.x0), float(clip_rect.x1)]
    
    segments = [s.strip() for s in header_text.split(",") if s.strip()]
    if len(segments) < 2:
        return [float(clip_rect.x0), float(clip_rect.x1)]
    
    # 最初の行の単語を取得
    if not row_groups[0]:
        return [float(clip_rect.x0), float(clip_rect.x1)]
    first_row_words = sorted(row_groups[0], key=lambda w: float(w[0]))
    
    # 各セグメントに対応する単語のX範囲を算出
    segment_ranges: List[Tuple[float, float]] = []
    word_idx = 0
    
    for seg_text in segments:
        seg_words_in_segment = seg_text.split()
        if not seg_words_in_segment:
            continue
            
        # このセグメントの単語を探す
        seg_word_positions: List[Tuple[float, float]] = []
        for expected_word in seg_words_in_segment:
            # 次の単語を探す
            found = False
            while word_idx < len(first_row_words):
                word = first_row_words[word_idx]
                word_text = str(word[4]).strip()
                if expected_word.lower() in word_text.lower() or word_text.lower() in expected_word.lower():
                    seg_word_positions.append((float(word[0]), float(word[2])))
                    word_idx += 1
                    found = True
                    break
                word_idx += 1
            if not found:
                # 見つからない場合、次の単語を探す
                break
        
        if seg_word_positions:
            x_min = min(x0 for x0, x1 in seg_word_positions)
            x_max = max(x1 for x0, x1 in seg_word_positions)
            segment_ranges.append((x_min, x_max))
    
    if len(segment_ranges) < 2:
        # セグメントが見つからない場合は通常の推定に戻す
        return _estimate_column_edges(words, clip_rect, row_groups, desired_cols=len(segments))
    
    # セグメント間の境界を算出
    edges = [float(clip_rect.x0)]
    for i in range(1, len(segment_ranges)):
        prev_x_max = segment_ranges[i - 1][1]
        curr_x_min = segment_ranges[i][0]
        boundary = (prev_x_max + curr_x_min) / 2.0
        edges.append(boundary)
    edges.append(float(clip_rect.x1))
    
    return edges


def _estimate_column_edges(
    words: List[Tuple[Any, ...]],
    clip_rect: fitz.Rect,
    row_groups: List[List[Tuple[Any, ...]]],
    desired_cols: Optional[int] = None,
) -> List[float]:
    if not words:
        return [float(clip_rect.x0), float(clip_rect.x1)]

    x_centers = [((float(w[0]) + float(w[2])) / 2.0) for w in words]

    if desired_cols is not None:
        cols = max(1, int(desired_cols))
        centers = _kmeans_1d(x_centers, cols)
        if len(centers) <= 1:
            return [float(clip_rect.x0), float(clip_rect.x1)]
        edges = [float(clip_rect.x0)]
        for i in range(1, len(centers)):
            edges.append(float((centers[i - 1] + centers[i]) / 2.0))
        edges.append(float(clip_rect.x1))
        return sorted(edges)

    separators: List[float] = []
    word_widths = [max(1.0, float(w[2]) - float(w[0])) for w in words]
    base_tol = max(6.0, _median(word_widths, 8.0) * 0.6)

    for row_words in row_groups:
        if len(row_words) < 2:
            continue
        row = sorted(row_words, key=lambda w: float(w[0]))
        gaps = [max(0.0, float(row[i][0]) - float(row[i - 1][2])) for i in range(1, len(row))]
        if not gaps:
            continue
        q2 = _percentile(gaps, 0.5, 0.0)
        q3 = _percentile(gaps, 0.75, q2)
        iqr = max(0.0, q3 - q2)
        threshold = max(12.0, q2 + 1.2 * iqr)

        for i in range(1, len(row)):
            prev = row[i - 1]
            curr = row[i]
            gap = max(0.0, float(curr[0]) - float(prev[2]))
            if gap >= threshold:
                separators.append(float((float(prev[2]) + float(curr[0])) / 2.0))

    clustered_sep = _cluster_1d_points(separators, tolerance=base_tol)
    clustered_sep = [s for s in clustered_sep if clip_rect.x0 < s < clip_rect.x1]

    if not clustered_sep:
        return [float(clip_rect.x0), float(clip_rect.x1)]

    edges = [float(clip_rect.x0)] + sorted(clustered_sep) + [float(clip_rect.x1)]
    deduped = [edges[0]]
    for x in edges[1:]:
        if abs(x - deduped[-1]) >= 1.0:
            deduped.append(x)
    if len(deduped) < 2:
        return [float(clip_rect.x0), float(clip_rect.x1)]
    return deduped


def _build_uniform_edges(start: float, end: float, count: int) -> List[float]:
    count = max(1, int(count))
    span = max(1e-6, end - start)
    step = span / count
    return [start + i * step for i in range(count + 1)]


def _build_row_edges_from_groups(
    row_groups: List[List[Tuple[Any, ...]]],
    clip_rect: fitz.Rect,
) -> List[float]:
    if not row_groups:
        return [float(clip_rect.y0), float(clip_rect.y1)]

    centers: List[float] = []
    for group in row_groups:
        if group:
            centers.append(sum((float(w[1]) + float(w[3])) / 2.0 for w in group) / len(group))
        else:
            centers.append(float(clip_rect.y0))

    if len(centers) == 1:
        return [float(clip_rect.y0), float(clip_rect.y1)]

    centers = sorted(centers)
    edges = [float(clip_rect.y0)]
    for i in range(1, len(centers)):
        edges.append(float((centers[i - 1] + centers[i]) / 2.0))
    edges.append(float(clip_rect.y1))

    deduped = [edges[0]]
    for y in edges[1:]:
        if y - deduped[-1] < 1.0:
            y = deduped[-1] + 1.0
        deduped.append(y)
    return deduped


def _build_preview_cell_rects(row_edges: List[float], col_edges: List[float]) -> List[List[float]]:
    if len(row_edges) < 2 or len(col_edges) < 2:
        return []

    result: List[List[float]] = []
    for r in range(len(row_edges) - 1):
        for c in range(len(col_edges) - 1):
            result.append([
                float(col_edges[c]),
                float(row_edges[r]),
                float(col_edges[c + 1]),
                float(row_edges[r + 1]),
            ])
    return result


def suggest_table_shape_for_selection(
    page: fitz.Page,
    page_paragraphs: Dict[str, Dict[str, Any]],
    paragraph_ids: Iterable[Any],
    desired_rows: Optional[int] = None,
    desired_cols: Optional[int] = None,
    header_text: Optional[str] = None,
) -> Dict[str, Any]:
    rect = build_selection_rect_from_paragraph_ids(page_paragraphs, paragraph_ids)
    if rect is None:
        return {
            "ok": False,
            "message": "selection rect not found",
            "rows": 1,
            "cols": 1,
            "clip_rect": None,
            "preview_cell_rects": [],
            "header_text": "",
        }

    pad = 1.5
    clip = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
    words = page.get_text("words", clip=clip)

    row_groups = _build_row_groups(words, desired_rows=desired_rows)
    row_edges = _build_row_edges_from_groups(row_groups, clip)

    if header_text and "," in str(header_text):
        col_edges = _estimate_columns_from_header_segments(str(header_text), words, clip, row_groups)
    else:
        col_edges = _estimate_column_edges(words, clip, row_groups, desired_cols=desired_cols)

    rows = max(1, len(row_edges) - 1)
    cols = max(1, len(col_edges) - 1)
    preview_cell_rects = _build_preview_cell_rects(row_edges, col_edges)
    if header_text:
        resolved_header_text = str(header_text).strip()
    else:
        resolved_header_text = _extract_header_text_from_first_row(row_groups, col_edges)

    return {
        "ok": True,
        "rows": rows,
        "cols": cols,
        "clip_rect": [float(clip.x0), float(clip.y0), float(clip.x1), float(clip.y1)],
        "preview_cell_rects": preview_cell_rects,
        "header_text": resolved_header_text,
    }


def _extract_markdown_rows_by_grid(
    page: fitz.Page,
    clip_rect: fitz.Rect,
    rows: Optional[int],
    cols: Optional[int],
    header_text: Optional[str] = None,
) -> List[Dict[str, Any]]:
    words = page.get_text("words", clip=clip_rect)
    if not words:
        return []

    desired_rows = None if rows is None else max(1, int(rows))
    desired_cols = None if cols is None else max(1, int(cols))

    row_groups = _build_row_groups(words, desired_rows=desired_rows)
    if not row_groups:
        return []

    row_edges = _build_row_edges_from_groups(row_groups, clip_rect)
    
    # ヘッダテキストがある場合はそれを使って列境界を推定
    if header_text and "," in header_text:
        col_edges = _estimate_columns_from_header_segments(header_text, words, clip_rect, row_groups)
    else:
        col_edges = _estimate_column_edges(words, clip_rect, row_groups, desired_cols=desired_cols)
    
    col_count = max(1, len(col_edges) - 1)

    grid: List[List[List[Tuple[Any, ...]]]] = [
        [[] for _ in range(col_count)] for _ in range(len(row_groups))
    ]

    for r, group in enumerate(row_groups):
        for word in group:
            xc = (float(word[0]) + float(word[2])) / 2.0
            c = bisect.bisect_right(col_edges, xc) - 1
            c = min(max(0, c), col_count - 1)
            grid[r][c].append(word)

    result_rows: List[Dict[str, Any]] = []
    for r in range(len(row_groups)):
        cell_texts: List[str] = []
        cell_boxes: List[List[float]] = []

        for c in range(col_count):
            cell_words = sorted(grid[r][c], key=lambda wv: (float(wv[1]), float(wv[0])))
            text = " ".join(str(wv[4]) for wv in cell_words if str(wv[4]).strip()).strip()
            cell_texts.append(text)

            if cell_words:
                cell_boxes.append([
                    min(float(wv[0]) for wv in cell_words),
                    min(float(wv[1]) for wv in cell_words),
                    max(float(wv[2]) for wv in cell_words),
                    max(float(wv[3]) for wv in cell_words),
                ])
            else:
                cell_boxes.append([
                    float(col_edges[c]),
                    float(row_edges[r]),
                    float(col_edges[c + 1]),
                    float(row_edges[r + 1]),
                ])

        row_bbox = [
            min(cb[0] for cb in cell_boxes),
            min(cb[1] for cb in cell_boxes),
            max(cb[2] for cb in cell_boxes),
            max(cb[3] for cb in cell_boxes),
        ]
        result_rows.append({
            "cells": cell_texts,
            "bbox": row_bbox,
            "markdown": _to_markdown_row(cell_texts),
        })

    return result_rows


def append_markdown_table_rows_from_selection(
    page: fitz.Page,
    page_number: int,
    page_paragraphs: Dict[str, Dict[str, Any]],
    paragraph_ids: Iterable[Any],
    table_id: str,
    rows: Optional[int] = None,
    cols: Optional[int] = None,
    header_text: Optional[str] = None,
) -> int:
    selection = suggest_table_shape_for_selection(page, page_paragraphs, paragraph_ids)
    if not selection.get("ok"):
        return 0

    guessed_rows = _safe_pos_int(selection.get("rows"), 1)
    guessed_cols = _safe_pos_int(selection.get("cols"), 1)
    final_rows = _safe_pos_int(rows, guessed_rows)
    final_cols = _safe_pos_int(cols, guessed_cols)

    clip_arr = selection.get("clip_rect") or [0, 0, 0, 0]
    clip_rect = fitz.Rect(float(clip_arr[0]), float(clip_arr[1]), float(clip_arr[2]), float(clip_arr[3]))

    extracted_rows = _extract_markdown_rows_by_grid(page, clip_rect, final_rows, final_cols, header_text)
    if not extracted_rows:
        return 0

    current_max_order = 0
    for p in page_paragraphs.values():
        current_max_order = max(current_max_order, _safe_int(p.get("order"), 0))

    added_count = 0
    for row_index, row_data in enumerate(extracted_rows, start=1):
        md_row = str(row_data.get("markdown") or "").strip()
        if not md_row:
            continue

        current_max_order += 1
        para_id = f"tbl_{table_id}_r{row_index}"
        unique_key = para_id
        suffix = 2
        while unique_key in page_paragraphs:
            unique_key = f"{para_id}_{suffix}"
            suffix += 1

        block_tag_value = "th" if row_index == 1 else "tr"
        paragraph = {
            "id": unique_key,
            "src_text": md_row,
            "src_html": escape(md_row),
            "src_joined": md_row,
            "src_replaced": md_row,
            "trans_auto": md_row,
            "trans_text": md_row,
            "comment": "",
            "trans_status": "none",
            "block_tag": block_tag_value,
            "modified_at": "",
            "base_style": "",
            "bbox": row_data.get("bbox") or [clip_rect.x0, clip_rect.y0, clip_rect.x1, clip_rect.y1],
            "column_order": 999,
            "page_number": page_number,
            "order": current_max_order,
            "table_meta": {
                "table_id": table_id,
                "row": row_index,
                "source": "reextract_by_selection_grid",
                "markdown_row": True,
                "rows": final_rows,
                "cols": final_cols,
            },
        }
        page_paragraphs[unique_key] = paragraph
        added_count += 1

    return added_count


def append_markdown_table_rows_by_specs(
    page: fitz.Page,
    page_number: int,
    page_paragraphs: Dict[str, Dict[str, Any]],
    table_specs: Iterable[Any],
) -> int:
    """
    指定された paragraph 範囲(start_id/end_id)を元に座標を算出し、
    PDFから表を再抽出して「行単位Markdown」を段落としてページ末尾へ追記する。
    """
    specs = _normalize_specs(table_specs)
    if not specs:
        return 0

    added_count = 0
    for spec in specs:
        selected_ids = [spec.start_id, spec.end_id]
        added_count += append_markdown_table_rows_from_selection(
            page=page,
            page_number=page_number,
            page_paragraphs=page_paragraphs,
            paragraph_ids=selected_ids,
            table_id=spec.table_id,
        )

    return added_count


# ---------------------------------------------------------------------------
# AI 表再抽出ユーティリティ
# ---------------------------------------------------------------------------

def _distribute_row_bboxes(
    clip_rect: fitz.Rect,
    n_rows: int,
    source_bboxes: Optional[List[List[float]]] = None,
    row_fracs: Optional[List[float]] = None,
    sel_rect: Optional[fitz.Rect] = None,
) -> List[List[float]]:
    """N 行分の bbox を計算して返す。

    優先順位:

    1. *source_bboxes* の長さが *n_rows* と一致する場合 → そのまま使用
       （PyMuPDF が検出した実際の座標なので最も正確）。
    2. *row_fracs* の長さが *n_rows* と一致する場合 → 比率で分割
       （AI が ``data-height`` で返した推定割合）。
    3. いずれも使えない場合 → 分割対象矩形の高さを *n_rows* で等分。

    分割に使う矩形は *sel_rect*（指定時）、なければ *clip_rect* を使用する。
    *clip_rect* はレンダリング用に周囲にマージンを加えた矩形なので、
    実際の表領域を表す *sel_rect* を渡すと bbox のずれを防げる。

    Args:
        clip_rect: 周囲にマージンを含む全体領域矩形（PNG レンダリング用）。
            *sel_rect* が指定されない場合、こちらを分割基準として使用する。
        n_rows: 生成する行数。
        source_bboxes: 元の段落の bbox リスト（``[x0, y0, x1, y1]`` の並び、
            y0 でソート済みを期待）。行数が一致するときのみ使用される。
        row_fracs: 各行の高さ比率のリスト（合計 1.0 を期待、``n_rows`` と
            同じ長さのとき使用）。AI の ``data-height`` 属性から生成される。
        sel_rect: 実際に選択された表領域の矩形（マージンなし）。指定した場合、
            *row_fracs* および等分割の基準矩形としてこちらを優先する。

    Returns:
        *n_rows* 個の ``[x0, y0, x1, y1]`` リスト。
    """
    if n_rows <= 0:
        return []

    # 1. source_bboxes が行数と一致する場合はそのまま使用。
    #    ただし、すべての y0 が同一（前回の不正な抽出等で bbox が縮退している）
    #    場合は位置情報として無意味なので、後続の方法にフォールスルーする。
    #    丸め精度 2 桁 (0.01 pt) は表の行が重なる典型的な誤差より十分大きい。
    if source_bboxes and len(source_bboxes) == n_rows:
        y0_set = {round(bb[1], 2) for bb in source_bboxes}
        if len(y0_set) > 1:
            print(
                f"[_distribute_row_bboxes] path=source_bboxes n_rows={n_rows}"
                f" y0={source_bboxes[0][1]:.2f} y1={source_bboxes[-1][3]:.2f}"
            )
            return [list(bb) for bb in source_bboxes]

    # row_fracs および等分割には sel_rect（マージンなし実選択範囲）を優先使用。
    # sel_rect がない場合は clip_rect にフォールバックする。
    dist_rect = sel_rect if sel_rect is not None else clip_rect
    x0 = float(dist_rect.x0)
    y0 = float(dist_rect.y0)
    x1 = float(dist_rect.x1)
    y1 = float(dist_rect.y1)
    total_h = y1 - y0

    # 2. row_fracs による比率分割
    if row_fracs and len(row_fracs) == n_rows:
        result: List[List[float]] = []
        y_cursor = y0
        for frac in row_fracs:
            row_h = total_h * max(0.0, float(frac))
            result.append([x0, y_cursor, x1, y_cursor + row_h])
            y_cursor += row_h
        first_y0 = result[0][1] if result else float("nan")
        last_y1 = result[-1][3] if result else float("nan")
        print(
            f"[_distribute_row_bboxes] path=row_fracs n_rows={n_rows}"
            f" dist_rect=(y0={y0:.2f}, y1={y1:.2f}, h={total_h:.2f} pt)"
            f" result_first_y0={first_y0:.2f} result_last_y1={last_y1:.2f}"
        )
        return result

    # 3. dist_rect の y 範囲を n_rows 等分してストリップを生成
    strip_h = total_h / n_rows
    result = []
    for i in range(n_rows):
        y_top = y0 + i * strip_h
        y_bottom = y_top + strip_h
        result.append([x0, y_top, x1, y_bottom])
    first_y0 = result[0][1] if result else float("nan")
    last_y1 = result[-1][3] if result else float("nan")
    print(
        f"[_distribute_row_bboxes] path=equal_split n_rows={n_rows}"
        f" dist_rect=(y0={y0:.2f}, y1={y1:.2f}, h={total_h:.2f} pt)"
        f" strip_h={strip_h:.2f}"
        f" result_first_y0={first_y0:.2f} result_last_y1={last_y1:.2f}"
    )
    return result


def render_region_to_png(page: fitz.Page, rect: fitz.Rect, scale: float = 2.0) -> bytes:
    """PDF ページの指定領域を PNG バイト列としてレンダリングする。

    Args:
        page: PyMuPDF のページオブジェクト。
        rect: レンダリングする領域の矩形。
        scale: レンダリング倍率（デフォルト 2.0 = 144 DPI 相当）。

    Returns:
        PNG フォーマットのバイト列。
    """
    matrix = fitz.Matrix(float(scale), float(scale))
    pix = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
    return pix.tobytes("png")


def append_table_rows_from_pipe_texts(
    page_paragraphs: Dict[str, Dict[str, Any]],
    page_number: int,
    table_id: str,
    clip_rect: fitz.Rect,
    pipe_rows: List[Tuple[str, str]],
    source_bboxes: Optional[List[List[float]]] = None,
    row_fracs: Optional[List[float]] = None,
    sel_rect: Optional[fitz.Rect] = None,
) -> int:
    """縦パイプ形式の行テキストから段落を生成してページに追加する。

    AI が HTML テーブルとして返したデータを ``html_to_pipe_rows_with_dims()`` で
    変換した結果を受け取り、既存の
    ``append_markdown_table_rows_from_selection()`` と同じ段落フォーマット
    で *page_paragraphs* に追加する。

    各段落の bbox は ``_distribute_row_bboxes()`` によって行ごとに個別に割り当て
    られる。優先順位:

    1. *source_bboxes* が行数と一致 → PDF 実座標をそのまま使用（最高精度）。
    2. *row_fracs* が行数と一致 → AI が ``data-height`` で返した割合で分割。
    3. 等分割（フォールバック）。

    Args:
        page_paragraphs: ページの段落辞書（更新される）。
        page_number: ページ番号。
        table_id: テーブルID（段落 ID の生成に使用）。
        clip_rect: PNG レンダリングに使用した矩形（周囲にマージンを含む）。
            *sel_rect* が省略された場合、bbox 分割の基準としても使用される。
        pipe_rows: ``html_to_pipe_rows_with_dims()`` が返す
            ``[(block_tag, pipe_text), ...]`` リスト。
            *pipe_text* は ``"Cell A | Cell B | Cell C"`` 形式。
        source_bboxes: 選択段落の bbox リスト（``[x0, y0, x1, y1]`` の並び、
            y0 でソート済み）。省略可。行数が一致するとき各行の bbox として使用。
        row_fracs: AI の ``data-height`` から算出した各行の高さ比率リスト
            （合計 1.0）。省略可。行数が一致するとき使用。
        sel_rect: 実際に選択された表領域の矩形（マージンなし）。指定した場合、
            bbox 分割の基準矩形（y0/y1 の範囲）として *clip_rect* より優先する。
            フォールバック bbox にも使用される。

    Returns:
        追加した行数。
    """
    current_max_order = 0
    for p in page_paragraphs.values():
        current_max_order = max(current_max_order, _safe_int(p.get("order"), 0))

    # 空行を除いた有効な行リストを先に作成し、bbox を行数に応じて分配する。
    # pipe_rows は html_to_pipe_rows_with_dims() で事前フィルタ済みのため
    # 空テキストは通常含まれないが、念のためフィルタする。
    valid_rows = [
        (bt, str(pt or "").strip())
        for bt, pt in pipe_rows
        if str(pt or "").strip()
    ]
    row_bboxes = _distribute_row_bboxes(clip_rect, len(valid_rows), source_bboxes, row_fracs, sel_rect)

    # フォールバック bbox は sel_rect（あれば）、なければ clip_rect を使用する。
    fallback_rect = sel_rect if sel_rect is not None else clip_rect

    added_count = 0
    for row_index, (block_tag, pipe_text) in enumerate(valid_rows, start=1):
        # html_to_pipe_rows は "Cell A | Cell B | Cell C" 形式で返す。
        # 既存の _to_markdown_row と同じ "| Cell A | Cell B | Cell C |" 形式へ正規化する。
        md_row = "| " + pipe_text + " |"

        current_max_order += 1
        para_id = f"tbl_{table_id}_r{row_index}"
        unique_key = para_id
        suffix = 2
        while unique_key in page_paragraphs:
            unique_key = f"{para_id}_{suffix}"
            suffix += 1

        bbox = row_bboxes[row_index - 1] if row_index - 1 < len(row_bboxes) else [
            float(fallback_rect.x0), float(fallback_rect.y0),
            float(fallback_rect.x1), float(fallback_rect.y1),
        ]

        paragraph = {
            "id": unique_key,
            "src_text": md_row,
            "src_html": escape(md_row),
            "src_joined": md_row,
            "src_replaced": md_row,
            "trans_auto": md_row,
            "trans_text": md_row,
            "comment": "",
            "trans_status": "none",
            "block_tag": block_tag,
            "modified_at": "",
            "base_style": "",
            "bbox": bbox,
            "column_order": 999,
            "page_number": page_number,
            "order": current_max_order,
            "table_meta": {
                "table_id": table_id,
                "row": row_index,
                "source": "ai_reextract",
                "markdown_row": True,
            },
        }
        page_paragraphs[unique_key] = paragraph
        added_count += 1

    return added_count
