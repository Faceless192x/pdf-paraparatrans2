def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text)

import html
import json
import re
import unicodedata
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")

_KATAKANA_START = ord("ァ")
_KATAKANA_END = ord("ヶ")
_HIRAGANA_START = ord("ぁ")
_HIRAGANA_END = ord("ゖ")

def _to_hiragana(text: str) -> str:
    # カタカナ→ひらがな
    res = []
    for c in text:
        code = ord(c)
        if _KATAKANA_START <= code <= _KATAKANA_END:
            res.append(chr(code - 0x60))
        else:
            res.append(c)
    return ''.join(res)

def _to_katakana(text: str) -> str:
    # ひらがな→カタカナ
    res = []
    for c in text:
        code = ord(c)
        if _HIRAGANA_START <= code <= _HIRAGANA_END:
            res.append(chr(code + 0x60))
        else:
            res.append(c)
    return ''.join(res)

def _normalize(text: Any) -> str:
    s = "" if text is None else str(text)
    s = html.unescape(s)
    s = _strip_html(s)
    s = s.replace("\u00a0", " ")
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    return s

def _normalize_all(text: Any) -> set[str]:
    # ひらがな・カタカナ両方で正規化
    s = _normalize(text)
    return {
        s,
        _to_hiragana(s),
        _to_katakana(s),
    }

def _find_hit_field(paragraph: dict, terms: list[str]) -> tuple[str, str]:
    # どのフィールドでヒットしたか、スニペット用に返す
    for key in ("src_joined", "src_text", "trans_text", "trans_auto"):
        v = paragraph.get(key)
        if not v:
            continue
        normset = _normalize_all(v)
        if all(any(t in n for n in normset) for t in terms):
            return key, str(v)
    return "", ""


def search_paragraphs_in_book(json_path: str, query: str, *, limit: int = 200) -> list[dict]:
    """Search paragraphs in a book JSON.
        Targets: src_joined, src_text, trans_text, trans_auto.
    Returns list of dict:
      {page_number:int, id:str, snippet:str}
    """
    q = (query or "").strip()
    if not q:
        return []
    # split by whitespace, AND semantics
    terms = [_normalize(t) for t in re.split(r"\s+", q) if t]
    if not terms:
        return []
    limit = int(limit) if isinstance(limit, int) or str(limit).isdigit() else 200
    limit = max(1, min(limit, 2000))
    with open(json_path, "r", encoding="utf-8") as f:
        book_data = json.load(f)
    pages = book_data.get("pages", {}) or {}
    results: list[dict] = []
    for page_key, page in pages.items():
        paragraphs = (page or {}).get("paragraphs", {}) or {}
        for pid, p in paragraphs.items():
            if not isinstance(p, dict):
                continue
            # 各フィールドでヒット判定
            hit_field, hit_value = _find_hit_field(p, terms)
            if not hit_field:
                continue
            try:
                page_number = int(p.get("page_number") or page_key)
            except Exception:
                page_number = None
            para_id = p.get("id") or pid
            snippet = _strip_html(html.unescape(hit_value)).replace("\n", " ").strip()
            if len(snippet) > 90:
                snippet = snippet[:90] + "…"
            try:
                order = int(p.get("order") or 0)
            except Exception:
                order = 0
            try:
                column_order = int(p.get("column_order") or 0)
            except Exception:
                column_order = 0
            try:
                y0 = float((p.get("bbox") or [0, 0])[1] or 0)
            except Exception:
                y0 = 0.0
            results.append(
                {
                    "page_number": page_number,
                    "id": str(para_id),
                    "snippet": snippet,
                    "_sort": (page_number or 0, order, column_order, y0),
                }
            )
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    results.sort(key=lambda r: r.get("_sort") or (0, 0, 0, 0))
    for r in results:
        r.pop("_sort", None)
    return results
