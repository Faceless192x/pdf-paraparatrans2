#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
parapara_join_incremental.py

段落 join のトグル(0→1, 1→0)が発生したとき、影響範囲だけ src_joined を更新するためのモジュール。
加えて、同一ロジックをファイル全体に一括適用する apply_all() を提供する。

前提(現段階):
- src_joined は「join=0 の段落(base)」だけが保持する。
- join=1 の段落は常に src_joined=""。
- 結合は基本「同一 block_tag の範囲内」。
- ただしページ境界をまたいだ結合は block_tag='p' のときだけ許可する。
- ただし block_tag が 'p' の段落に限り:
    - base 探索は他 block_tag を無視して直近の 'p' まで遡る。
    - run 構築も他 block_tag を無視し、右側に現れる 'p' の join=1 を連結する。
      (次に現れた 'p' が join=0 なら打ち切り)
- src_replaced/trans_* は src_joined 変更時のみ更新する:
    - src_joined が変化したら src_replaced に同じ値をセットし、trans_status を "none" にする
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


ParagraphKey = Tuple[str, str]  # (page_key, para_key)


@dataclass
class ParaRef:
    key: ParagraphKey
    p: Dict[str, Any]


def iter_paragraph_refs(book_data: Dict[str, Any]) -> List[ParaRef]:
    """段落を走査し、ソート済み ParaRef の配列を返す。"""
    refs: List[ParaRef] = []
    pages = book_data.get("pages", {})
    for page_key, page in pages.items():
        paras = page.get("paragraphs", {})
        for para_key, p in paras.items():
            refs.append(ParaRef(key=(str(page_key), str(para_key)), p=p))

    def sort_key(r: ParaRef):
        p = r.p
        return (
            int(p.get("page_number", 0)),
            int(p.get("order", 0)),
            int(p.get("column_order", 0)),
            float((p.get("bbox") or [0, 0, 0, 0])[1]),
        )

    refs.sort(key=sort_key)
    return refs


def build_index(refs: List[ParaRef]) -> Dict[ParagraphKey, int]:
    """ParaRef.key -> index"""
    return {r.key: i for i, r in enumerate(refs)}


def _join_flag(p: Dict[str, Any]) -> int:
    try:
        return 1 if int(p.get("join", 0)) == 1 else 0
    except Exception:
        return 0


def _block_tag(p: Dict[str, Any]) -> str:
    return str(p.get("block_tag", ""))


def _is_p_tag(tag: str) -> bool:
    return tag == "p"


def _src_text(p: Dict[str, Any]) -> str:
    v = p.get("src_text", "")
    return "" if v is None else str(v)


def _page_number(p: Dict[str, Any]) -> int:
    try:
        return int(p.get("page_number", 0))
    except Exception:
        return 0


def _set_src_joined(p: Dict[str, Any], value: str) -> None:
    """
    src_joined が変化したら:
      - src_replaced に同じ値をセット
      - trans_status を "none" にする
    """
    old = p.get("src_joined", "")
    old = "" if old is None else str(old)
    value = "" if value is None else str(value)

    if old != value:
        p["src_joined"] = value
        p["src_replaced"] = value
        p["trans_status"] = "none"
    else:
        p["src_joined"] = value


def find_base_index(refs: List[ParaRef], i: int, *, normalize_head: bool = True) -> Optional[int]:
    """
    i を含む結合チェーンの base(join=0) を左に遡って探す。

        - 基本: 遡り中に block_tag が変わったら None
            (ただし block_tag!='p' の場合はページ境界をまたがない)
    - ただし i の block_tag が 'p' のときは:
        他 block_tag を無視して直近の 'p' まで遡る(join=0 を見つけたらそれ、無ければ先頭まで)
    - 見つからなければ normalize_head=True のとき i 自身を base として扱う(=i を返す)
      (先頭が join=1 などの不整合でも情報欠落を避けるため)
    """
    if i < 0 or i >= len(refs):
        return None

    tag = _block_tag(refs[i].p)

    if not _is_p_tag(tag):
        page_no = _page_number(refs[i].p)
        j = i
        while j >= 0:
            pj = refs[j].p
            if _page_number(pj) != page_no:
                break
            if _block_tag(pj) != tag:
                return None
            if _join_flag(pj) == 0:
                return j
            j -= 1
        return i if normalize_head else None

    # tag == 'p': 他タグ無視で p だけを見る
    j = i
    while j >= 0:
        pj = refs[j].p
        if not _is_p_tag(_block_tag(pj)):
            j -= 1
            continue
        if _join_flag(pj) == 0:
            return j
        j -= 1

    return i if normalize_head else None


def find_run_end_index(refs: List[ParaRef], base_i: int) -> int:
    """
    base_i から右方向に run の終端を返す。

    - base の block_tag が 'p' 以外:
        ページ境界をまたがず、(同一block_tag かつ join=1) が連続する間だけ伸ばす(隣接前提)。
    - base の block_tag が 'p':
        右方向に走査し、block_tag が 'p' の段落だけを対象に join=1 が続く限り伸ばす。
        途中に他 block_tag が挟まっても無視して継続する。
        ただし次に現れた 'p' が join=0 の時点で打ち切る。
    """
    if base_i < 0 or base_i >= len(refs):
        return base_i

    tag = _block_tag(refs[base_i].p)
    end = base_i

    if not _is_p_tag(tag):
        page_no = _page_number(refs[base_i].p)
        k = base_i + 1
        while k < len(refs):
            pk = refs[k].p
            if _page_number(pk) != page_no:
                break
            if _block_tag(pk) != tag:
                break
            if _join_flag(pk) != 1:
                break
            end = k
            k += 1
        return end

    # tag == 'p'
    k = base_i + 1
    while k < len(refs):
        pk = refs[k].p
        t = _block_tag(pk)
        if not _is_p_tag(t):
            k += 1
            continue
        if _join_flag(pk) != 1:
            break
        end = k
        k += 1
    return end


def rebuild_run(refs: List[ParaRef], base_i: int, *, sep: str = "") -> List[int]:
    """
    base_i を起点に run を再構築して src_joined を書き換える。

    - base: src_joined = src_text(base)+sep+src_text(join=1...).
    - join=1側: src_joined = "".

    戻り値: run に含めた段落の index リスト(ベース含む)。
    """
    if base_i is None or base_i < 0 or base_i >= len(refs):
        return []

    base_p = refs[base_i].p
    tag = _block_tag(base_p)

    members: List[int] = [base_i]

    if not _is_p_tag(tag):
        end = find_run_end_index(refs, base_i)
        for k in range(base_i + 1, end + 1):
            members.append(k)
    else:
        end = find_run_end_index(refs, base_i)
        for k in range(base_i + 1, end + 1):
            pk = refs[k].p
            if _is_p_tag(_block_tag(pk)) and _join_flag(pk) == 1:
                members.append(k)

    parts: List[str] = [_src_text(refs[k].p) for k in members]
    joined = sep.join(parts) if sep != "" else "".join(parts)

    _set_src_joined(base_p, joined)
    for k in members[1:]:
        _set_src_joined(refs[k].p, "")

    return members


def apply_join_change(
    book_data: Dict[str, Any],
    current_key: ParagraphKey,
    new_join: int,
    *,
    refs: Optional[List[ParaRef]] = None,
    index: Optional[Dict[ParagraphKey, int]] = None,
    sep: str = "",
    normalize_head: bool = True,
) -> Dict[str, Any]:
    """
    UI で段落の join を書き換えたとき、影響範囲だけ src_joined を更新する。

    Args:
        book_data: JSON object
        current_key: (page_key, para_key)
        new_join: 0 or 1
        refs/index: 事前構築して渡すと高速。Noneなら内部で構築。
        sep: 連結の区切り。あなたのルールが「単純連結」なのでデフォルト ""。
        normalize_head: 左に base が存在しない join=1 を base 扱いして情報欠落を避ける。

    Returns:
        book_data (in-place update して返す)
    """
    if refs is None:
        refs = iter_paragraph_refs(book_data)
    if index is None:
        index = build_index(refs)

    if current_key not in index:
        raise KeyError(f"paragraph not found: {current_key}")

    i = index[current_key]
    p = refs[i].p

    old_join = _join_flag(p)
    new_join = 1 if int(new_join) == 1 else 0

    if old_join == new_join:
        return book_data

    affected_bases: List[int] = []

    if old_join == 0 and new_join == 1:
        # いったん join=1 として扱い「吸収先(base)」を探す。
        # normalize_head=False にして、左に base が無い場合は None 扱いにする。
        p["join"] = 1
        left_base = find_base_index(refs, i, normalize_head=False)
        if left_base is None:
            # 吸収先が無いなら base に戻して rebuild
            p["join"] = 0
            rebuild_run(refs, i, sep=sep)
            return book_data

        # 自分は join 側になる
        _set_src_joined(p, "")
        affected_bases.append(left_base)

    elif old_join == 1 and new_join == 0:
        # まず旧状態(join=1)のまま「元のbase」を特定しておく。
        prev_base = find_base_index(refs, i, normalize_head=False)
        p["join"] = 0
        if prev_base is not None:
            affected_bases.append(prev_base)
        affected_bases.append(i)

    for b in sorted(set(affected_bases)):
        rebuild_run(refs, b, sep=sep)

    return book_data


def apply_all(
    book_data: Dict[str, Any],
    *,
    sep: str = "",
    normalize_head: bool = True,
) -> Dict[str, Any]:
    """
    このモジュールのロジックをファイル全体に一括適用して src_joined を再構築する。

    - join ルールに従い、base(join=0) に連結結果を格納
    - join=1 側の src_joined は常に空
    - block_tag が 'p' のときだけ、遡り探索/右方向の連結で他 block_tag を無視
    - ページ境界をまたいだ結合は block_tag='p' のときだけ許可
    - src_joined が変化した段落は src_replaced を同値にし、trans_status='none'

    normalize_head=True の場合:
      左に有効な base が存在しない join=1 を join=0 に正規化して base として扱う
      (src_joined が空になって情報が落ちるのを避けるため)
    """
    refs = iter_paragraph_refs(book_data)

    visited: set[int] = set()

    for i in range(len(refs)):
        if i in visited:
            continue

        pi = refs[i].p
        join_i = _join_flag(pi)

        if join_i == 0:
            members = rebuild_run(refs, i, sep=sep)
            visited.update(members)
            continue

        base_i = find_base_index(refs, i, normalize_head=normalize_head)
        if base_i is None or base_i == i:
            if normalize_head:
                pi["join"] = 0
            members = rebuild_run(refs, i, sep=sep)
            visited.update(members)
            continue

        # base は左にあるはず。未処理ならここで処理しても良い。
        if base_i not in visited:
            members = rebuild_run(refs, base_i, sep=sep)
            visited.update(members)

    return book_data
