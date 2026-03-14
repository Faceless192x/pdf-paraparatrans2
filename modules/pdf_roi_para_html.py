from __future__ import annotations

"""PDF ROI paragraph extractor for paraparatrans.

Strategy (adapted from pdf_roi_table_html.py):
1. Use PyMuPDF's lines-based table detection to find candidate cell rectangles.
2. Keep only cells inside or intersecting a user-provided ROI.
3. Cluster x/y borders from those cells to rebuild a clean grid.
4. Assign words to grid cells and emit pipe-separated paragraph rows.

Unlike pdf_roi_table_html which emits an HTML <table>, this module emits rows in
the "| Cell A | Cell B |" Markdown pipe-table format that paraparatrans uses.

The grid detection function (detect_roi_grid) is separated from paragraph
emission so it can be called independently to preview / draw grid lines on a
PDF page without running the full extraction.

Requirements:
    pip install pymupdf

Example::

    from modules.pdf_roi_para_html import extract_paragraphs_from_pdf

    result = extract_paragraphs_from_pdf(
        pdf_path="sample.pdf",
        page_number=0,
        roi=(90, 180, 760, 1220),
    )
    for row in result.rows:
        print(row.markdown)
"""

from dataclasses import dataclass
from typing import Iterable, Sequence

import fitz


BBox = tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# Options / result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoiGridOptions:
    """Options for grid detection.

    Attributes:
        cluster_tolerance: Tolerance for clustering cell border positions.
        include_partial: When True, include cells that partially intersect the
            ROI in addition to cells fully contained within it.
        expand_to_cells: When True (default), expand the ROI outward to the
            full bounding box of all selected cells before rebuilding the grid.
            This ensures that cells whose borders slightly protrude outside the
            user-drawn selection rectangle are captured correctly and that the
            resulting bboxes align with the actual PDF cell edges rather than
            the raw selection coordinates.
    """

    cluster_tolerance: float = 4.0
    include_partial: bool = True
    expand_to_cells: bool = True


@dataclass(frozen=True)
class RoiGridResult:
    """Result of lines-based grid detection in an ROI.

    ``clustered_x`` and ``clustered_y`` are the column/row border positions.
    They define a grid of (len(y)-1) rows × (len(x)-1) columns.
    """

    page_number: int
    roi: BBox
    clustered_x: tuple[float, ...]
    clustered_y: tuple[float, ...]

    @property
    def row_count(self) -> int:
        return max(0, len(self.clustered_y) - 1)

    @property
    def col_count(self) -> int:
        return max(0, len(self.clustered_x) - 1)

    def cell_rects(self) -> list[list[float]]:
        """Return all cell bounding boxes as ``[x0, y0, x1, y1]`` lists.

        Useful for drawing preview grid lines on the PDF viewer.
        """
        xs = self.clustered_x
        ys = self.clustered_y
        rects: list[list[float]] = []
        for r in range(len(ys) - 1):
            for c in range(len(xs) - 1):
                rects.append([xs[c], ys[r], xs[c + 1], ys[r + 1]])
        return rects


@dataclass
class ParaRow:
    """A single extracted paragraph row."""

    block_tag: str          # "th" for first row, "tr" for subsequent rows
    pipe_text: str          # e.g. "Cell A | Cell B | Cell C"
    markdown: str           # e.g. "| Cell A | Cell B | Cell C |"
    bbox: list[float]       # [x0, y0, x1, y1] in PDF points
    row_index: int          # 1-based row number


@dataclass(frozen=True)
class RoiParaExtractionResult:
    """Full extraction result: grid + paragraph rows."""

    grid: RoiGridResult
    rows: tuple[ParaRow, ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block_no: int
    line_no: int
    word_no: int

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2.0


@dataclass(frozen=True)
class _Cell:
    bbox: BBox


def _normalize_roi(roi: Sequence[float]) -> BBox:
    if len(roi) != 4:
        raise ValueError("roi must contain exactly 4 numbers: (x0, y0, x1, y1)")
    x0, y0, x1, y1 = map(float, roi)
    if x0 == x1 or y0 == y1:
        raise ValueError("roi must have non-zero width and height")
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _inside_roi(rect: BBox, roi: BBox, tol: float = 0.0) -> bool:
    rx0, ry0, rx1, ry1 = roi
    x0, y0, x1, y1 = rect
    return x0 >= rx0 - tol and y0 >= ry0 - tol and x1 <= rx1 + tol and y1 <= ry1 + tol


def _intersects_roi(rect: BBox, roi: BBox) -> bool:
    ax0, ay0, ax1, ay1 = rect
    bx0, by0, bx1, by1 = roi
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


def _cluster_positions(values: Iterable[float], tol: float) -> list[float]:
    vals = sorted(float(v) for v in values)
    if not vals:
        return []
    groups: list[list[float]] = [[vals[0]]]
    for v in vals[1:]:
        if abs(v - groups[-1][-1]) <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _find_line_cells(page: fitz.Page) -> list[_Cell]:
    tabs = page.find_tables(vertical_strategy="lines", horizontal_strategy="lines")
    cells: list[_Cell] = []
    for table in tabs.tables:
        for cell in table.cells:
            if cell:
                cells.append(_Cell(tuple(float(v) for v in cell)))
    return cells


def _select_cells(cells: Sequence[_Cell], roi: BBox, include_partial: bool) -> list[_Cell]:
    selected: list[_Cell] = []
    for cell in cells:
        ok = _intersects_roi(cell.bbox, roi) if include_partial else _inside_roi(cell.bbox, roi)
        if ok:
            selected.append(cell)
    return selected


def _rebuild_grid(cells: Sequence[_Cell], roi: BBox, cluster_tolerance: float) -> tuple[list[float], list[float]]:
    if not cells:
        raise ValueError(
            "ROI内に罫線ベースのセルが見つかりません。"
            "ROIを広げるか、別のページを試してください。"
        )

    xs: list[float] = []
    ys: list[float] = []
    for cell in cells:
        x0, y0, x1, y1 = cell.bbox
        xs.extend([x0, x1])
        ys.extend([y0, y1])

    rx0, ry0, rx1, ry1 = roi
    cx = _cluster_positions(xs + [rx0, rx1], cluster_tolerance)
    cy = _cluster_positions(ys + [ry0, ry1], cluster_tolerance)

    cx = sorted(x for x in cx if rx0 <= x <= rx1)
    cy = sorted(y for y in cy if ry0 <= y <= ry1)

    if len(cx) < 2 or len(cy) < 2:
        raise ValueError("グリッド再構築に失敗しました。クラスタリング後の境界が不足しています。")

    return cx, cy


def _extract_words(page: fitz.Page, roi: BBox) -> list[_Word]:
    raw = page.get_text("words", clip=fitz.Rect(roi))
    out: list[_Word] = []
    for item in raw:
        x0, y0, x1, y1, text, block_no, line_no, word_no = item
        text = str(text).strip()
        if not text:
            continue
        out.append(
            _Word(
                x0=float(x0),
                y0=float(y0),
                x1=float(x1),
                y1=float(y1),
                text=text,
                block_no=int(block_no),
                line_no=int(line_no),
                word_no=int(word_no),
            )
        )
    return out


def _assign_words_to_grid(
    words: Sequence[_Word],
    xs: Sequence[float],
    ys: Sequence[float],
) -> list[list[list[_Word]]]:
    rows = len(ys) - 1
    cols = len(xs) - 1
    buckets: list[list[list[_Word]]] = [[[] for _ in range(cols)] for _ in range(rows)]

    for word in words:
        col = None
        row = None
        for i in range(cols):
            if xs[i] <= word.xc < xs[i + 1] or (i == cols - 1 and xs[i] <= word.xc <= xs[i + 1]):
                col = i
                break
        for j in range(rows):
            if ys[j] <= word.yc < ys[j + 1] or (j == rows - 1 and ys[j] <= word.yc <= ys[j + 1]):
                row = j
                break
        if row is not None and col is not None:
            buckets[row][col].append(word)

    return buckets


def _words_to_text(words: Sequence[_Word]) -> str:
    """Join words in reading order (block→line→word→position)."""
    if not words:
        return ""
    ordered = sorted(words, key=lambda w: (w.block_no, w.line_no, w.word_no, w.x0))
    return " ".join(w.text for w in ordered)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_roi_grid(
    page: fitz.Page,
    roi: Sequence[float],
    *,
    options: RoiGridOptions | None = None,
) -> RoiGridResult:
    """Detect the row/column grid from PDF ruled lines within *roi*.

    This function is **independent of paragraph extraction** and can be called
    to obtain preview cell rectangles for drawing grid lines on the PDF viewer.

    Args:
        page: PyMuPDF page object.
        roi: Region of interest as ``(x0, y0, x1, y1)`` in PDF points.
        options: Grid detection options (cluster tolerance, inclusion mode).

    Returns:
        :class:`RoiGridResult` containing the clustered x/y border positions.

    Raises:
        ValueError: If no line-based cells are found in the ROI or if the
            grid cannot be reconstructed from the detected cells.
    """
    opts = options or RoiGridOptions()
    normalized_roi = _normalize_roi(roi)

    line_cells = _find_line_cells(page)
    selected_cells = _select_cells(line_cells, normalized_roi, opts.include_partial)

    # Optionally expand the ROI to fully enclose all selected cell bboxes.
    # This compensates for small user-selection inaccuracies and ensures the
    # grid boundaries align with the actual PDF ruled-line positions.
    if opts.expand_to_cells and selected_cells:
        cell_x0 = min(c.bbox[0] for c in selected_cells)
        cell_y0 = min(c.bbox[1] for c in selected_cells)
        cell_x1 = max(c.bbox[2] for c in selected_cells)
        cell_y1 = max(c.bbox[3] for c in selected_cells)
        rx0, ry0, rx1, ry1 = normalized_roi
        normalized_roi = (
            min(rx0, cell_x0),
            min(ry0, cell_y0),
            max(rx1, cell_x1),
            max(ry1, cell_y1),
        )

    xs, ys = _rebuild_grid(selected_cells, normalized_roi, opts.cluster_tolerance)

    return RoiGridResult(
        page_number=page.number,
        roi=normalized_roi,
        clustered_x=tuple(xs),
        clustered_y=tuple(ys),
    )


def extract_paragraphs(
    page: fitz.Page,
    roi: Sequence[float],
    *,
    options: RoiGridOptions | None = None,
) -> RoiParaExtractionResult:
    """Extract table rows as paraparatrans paragraphs from *roi*.

    Uses PDF ruled lines to detect the grid structure, then assigns words to
    grid cells and emits pipe-separated paragraph rows compatible with the
    paraparatrans Markdown pipe-table format.

    Args:
        page: PyMuPDF page object.
        roi: Region of interest as ``(x0, y0, x1, y1)`` in PDF points.
        options: Grid detection options.

    Returns:
        :class:`RoiParaExtractionResult` with the grid and extracted rows.

    Raises:
        ValueError: If grid detection fails (see :func:`detect_roi_grid`).
    """
    grid = detect_roi_grid(page, roi, options=options)
    xs = grid.clustered_x
    ys = grid.clustered_y
    roi_x0, roi_y0, roi_x1, roi_y1 = grid.roi

    words = _extract_words(page, grid.roi)
    buckets = _assign_words_to_grid(words, xs, ys)

    n_rows = len(buckets)
    para_rows: list[ParaRow] = []
    for row_idx, row_cells in enumerate(buckets):
        cell_texts = [_words_to_text(cell_words) for cell_words in row_cells]
        pipe_text = " | ".join(cell_texts)
        markdown = "| " + pipe_text + " |"

        # x0/x1: always use the specified ROI boundaries.
        # y0/y1: use the grid row boundaries, but snap the first row's y0 to
        # the ROI y0 and the last row's y1 to the ROI y1 so the full height
        # of the selection is covered exactly.
        row_y0 = ys[row_idx]
        row_y1 = ys[row_idx + 1]
        if row_idx == 0:
            row_y0 = roi_y0
        if row_idx == n_rows - 1:
            row_y1 = roi_y1

        para_rows.append(
            ParaRow(
                block_tag="th" if row_idx == 0 else "tr",
                pipe_text=pipe_text,
                markdown=markdown,
                bbox=[roi_x0, row_y0, roi_x1, row_y1],
                row_index=row_idx + 1,
            )
        )

    return RoiParaExtractionResult(
        grid=grid,
        rows=tuple(para_rows),
    )


def extract_paragraphs_from_pdf(
    pdf_path: str,
    page_number: int,
    roi: Sequence[float],
    *,
    options: RoiGridOptions | None = None,
) -> RoiParaExtractionResult:
    """Open a PDF file and extract paragraphs from *roi* on *page_number*.

    Args:
        pdf_path: Absolute path to the PDF file.
        page_number: **Zero-based** page number.
        roi: Region of interest as ``(x0, y0, x1, y1)`` in PDF points.
        options: Grid detection options.

    Returns:
        :class:`RoiParaExtractionResult` with the grid and extracted rows.

    Raises:
        IndexError: If *page_number* is out of range.
        ValueError: If grid detection fails.
    """
    doc = fitz.open(pdf_path)
    try:
        if not 0 <= page_number < len(doc):
            raise IndexError(
                f"page_number out of range: {page_number} (document has {len(doc)} pages)"
            )
        return extract_paragraphs(doc[page_number], roi, options=options)
    finally:
        doc.close()


__all__ = [
    "BBox",
    "ParaRow",
    "RoiGridOptions",
    "RoiGridResult",
    "RoiParaExtractionResult",
    "detect_roi_grid",
    "extract_paragraphs",
    "extract_paragraphs_from_pdf",
]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Extract ROI-based paragraphs from a PDF page as pipe-table rows."
    )
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("page_number", type=int, help="Zero-based page number")
    parser.add_argument("x0", type=float)
    parser.add_argument("y0", type=float)
    parser.add_argument("x1", type=float)
    parser.add_argument("y1", type=float)
    parser.add_argument("--cluster-tolerance", type=float, default=4.0)
    parser.add_argument("--inside-only", action="store_true")
    args = parser.parse_args()

    result = extract_paragraphs_from_pdf(
        args.pdf_path,
        args.page_number,
        (args.x0, args.y0, args.x1, args.y1),
        options=RoiGridOptions(
            cluster_tolerance=args.cluster_tolerance,
            include_partial=not args.inside_only,
        ),
    )
    print(f"Grid: {result.grid.row_count} rows × {result.grid.col_count} cols")
    for row in result.rows:
        sys.stdout.write(row.markdown + "\n")
