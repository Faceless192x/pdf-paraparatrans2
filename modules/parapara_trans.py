"""
parapara形式ファイルを指定ページ範囲内で翻訳する。

"""

import os
import html
import json
import re
import logging
import time
import unicodedata
from datetime import datetime
import tempfile
from dataclasses import dataclass, asdict
from typing import Callable, Dict, List, Optional

# 対訳辞書置換用
from modules.parapara_dict_replacer import load_dictionary, replace_with_dict
import sys

DICT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "dict.txt")

try:
    # パッケージとして読み込まれる（Flaskアプリなど）ケース
    from .api_translate import (  # type: ignore
        TranslationServerConnectionError,
        get_current_translator,
        translate_text,
        translate_texts,
    )
except Exception:
    # スクリプトとして直接実行されるケース（sys.path に modules が入っている前提）
    from api_translate import (  # type: ignore
        TranslationServerConnectionError,
        get_current_translator,
        translate_text,
        translate_texts,
    )


def _debug_pagetrans_enabled() -> bool:
    v = os.getenv("PARAPARA_DEBUG_PAGETRANS", "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _pagetrans_debug(msg: str):
    if _debug_pagetrans_enabled():
        # 既存の仕組みに載せるため print を使う（SSE/ログ出力に流れる）
        print(f"[PAGETRANS_DEBUG] {msg}")


DEFAULT_GROUP_MAX_CHARS = 4000
MIN_GROUP_MAX_CHARS = 400
MAX_GROUP_MAX_CHARS = 12000


def _normalize_group_max_chars(value: Optional[int]) -> int:
    if value is None:
        return DEFAULT_GROUP_MAX_CHARS
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_GROUP_MAX_CHARS
    if parsed < MIN_GROUP_MAX_CHARS:
        return MIN_GROUP_MAX_CHARS
    if parsed > MAX_GROUP_MAX_CHARS:
        return MAX_GROUP_MAX_CHARS
    return parsed


@dataclass
class TranslationStats:
    translation_engine: str = ""
    characters_used: int = 0
    group_max_chars: int = DEFAULT_GROUP_MAX_CHARS
    pages_processed: int = 0
    paragraphs_total_in_range: int = 0
    paragraphs_target: int = 0
    translated: int = 0
    translated_fallback: int = 0
    failed: int = 0
    skipped_header_footer: int = 0
    skipped_empty_src: int = 0
    skipped_already_translated: int = 0
    skipped_join_empty: int = 0
    missing_from_batch: int = 0
    groups: int = 0


def _record_used_chars(stats: Optional[TranslationStats], text: str) -> None:
    if stats is None:
        return
    stats.characters_used += len(str(text or ""))


def _record_used_chars_many(stats: Optional[TranslationStats], texts: List[str]) -> None:
    if stats is None:
        return
    stats.characters_used += sum(len(str(text or "")) for text in texts)


def _emit_progress(payload: Dict[str, object]) -> None:
    try:
        print("[PROGRESS] " + json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def _emit_translation_progress(
    progress_state: Optional[Dict[str, object]],
    phase: str,
    page_number: Optional[int] = None,
) -> None:
    if not progress_state:
        return

    done = int(progress_state.get("done") or 0)
    total = int(progress_state.get("total") or 0)
    payload: Dict[str, object] = {
        "kind": "translation",
        "phase": str(phase),
        "id": str(progress_state.get("id") or ""),
        "done": done,
        "total": total,
    }
    if page_number is not None:
        payload["page"] = int(page_number)
    _emit_progress(payload)


def _emit_translation_phase(
    progress_state: Optional[Dict[str, object]],
    phase: str,
    **extra_fields,
) -> None:
    if not progress_state:
        return

    payload: Dict[str, object] = {
        "kind": "translation_phase",
        "phase": str(phase),
        "id": str(progress_state.get("id") or ""),
        "done": int(progress_state.get("done") or 0),
        "total": int(progress_state.get("total") or 0),
    }
    payload.update(extra_fields)
    _emit_progress(payload)


def _mark_first_engine_access(
    progress_state: Optional[Dict[str, object]],
    page_number: int,
    route: str,
) -> None:
    if not progress_state:
        return
    if bool(progress_state.get("first_engine_access_emitted")):
        return

    started_at = progress_state.get("started_at_perf")
    if not isinstance(started_at, (int, float)):
        return

    elapsed_ms = round((time.perf_counter() - float(started_at)) * 1000, 1)
    progress_state["first_engine_access_emitted"] = True
    _emit_translation_phase(
        progress_state,
        phase="first_engine_access",
        page=int(page_number),
        route=str(route),
        elapsed_ms=elapsed_ms,
    )


def _advance_translation_progress(
    progress_state: Optional[Dict[str, object]],
    amount: int = 1,
    page_number: Optional[int] = None,
) -> None:
    if not progress_state:
        return

    done = int(progress_state.get("done") or 0)
    total = int(progress_state.get("total") or 0)
    done += max(0, int(amount))
    if done > total:
        total = done

    progress_state["done"] = done
    progress_state["total"] = total
    _emit_translation_progress(progress_state, phase="step", page_number=page_number)


def _estimate_translation_targets(book_data: dict, start_page: int, end_page: int) -> int:
    total = 0
    pages = (book_data or {}).get("pages", {}) or {}

    try:
        dict_cs, dict_ci = load_dictionary(DICT_PATH)
    except Exception:
        dict_cs, dict_ci = {}, {}

    for page in range(start_page, end_page + 1):
        page_data = pages.get(str(page), {}) or {}
        paragraphs = page_data.get("paragraphs", {}) or {}
        for paragraph in paragraphs.values():
            src_joined = paragraph.get("src_joined", "") or ""
            if src_joined == "":
                continue

            src_replaced = replace_with_dict(src_joined, dict_cs, dict_ci)
            if src_replaced == "":
                continue

            trans_status = paragraph.get("trans_status") or "none"
            if trans_status != "none":
                continue

            if paragraph.get("block_tag") in ("header", "footer"):
                continue

            if _should_auto_translate_as_draft(src_replaced):
                continue

            total += 1

    return total


_MARKER_RE = re.compile(r"【\s*([0-9]+[＿_][0-9]+)\s*】")


def _normalize_marker_id(raw: str) -> str:
    return raw.strip().replace("＿", "_")


def _extract_translations_by_marker(translated_text: str) -> Dict[str, str]:
    matches = list(_MARKER_RE.finditer(translated_text or ""))
    if not matches:
        return {}

    out: Dict[str, str] = {}
    for i, m in enumerate(matches):
        pid = _normalize_marker_id(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(translated_text)
        content = (translated_text[start:end] or "").strip()
        out[pid] = content
    return out


def _apply_translation_to_paragraph(para: dict, translated_content: str) -> None:
    # q_ と _q が前後に区切り文字（英数字以外、または行頭・行末）の場合にのみ除去する
    translated_content = re.sub(
        r'(?:(?<=^)|(?<=[^A-Za-z]))q_([A-Za-z]+)_q(?=$|[^A-Za-z])',
        r'\1',
        translated_content,
    )
    para['trans_auto'] = translated_content
    para['trans_text'] = translated_content
    para['trans_status'] = 'auto'
    para['modified_at'] = datetime.now().isoformat()


def _is_table_row(paragraph: dict) -> bool:
    return str(paragraph.get("block_tag") or "").lower() in {"th", "tr"}


def _split_markdown_row_cells(row_text: str) -> List[str]:
    if not row_text:
        return []
    parts = re.split(r"(?<!\\)\|", row_text)
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.replace(r"\|", "|").strip() for p in parts]


def _build_markdown_row_from_cells(cells: List[str]) -> str:
    escaped = [c.replace("|", r"\|").strip() for c in cells]
    return "| " + " | ".join(escaped) + " |"


def _translate_table_row_paragraph(para: dict, stats: Optional[TranslationStats] = None) -> bool:
    src_replaced = para.get("src_replaced", "") or ""
    cells = _split_markdown_row_cells(src_replaced)
    if not cells:
        return False

    used_fallback = False
    try:
        translated_cells = translate_texts(cells, source="en", target="ja")
        if not isinstance(translated_cells, list) or len(translated_cells) != len(cells):
            raise ValueError("Unexpected translate_texts result length")
        _record_used_chars_many(stats, cells)
    except Exception as e:
        if isinstance(e, TranslationServerConnectionError):
            raise
        print(f"Warning: テーブル行の一括翻訳に失敗。セルごとにフォールバックします: {e}")
        used_fallback = True
        translated_cells = []
        for cell in cells:
            try:
                translated = translate_text(cell, source="en", target="ja")
                translated_cells.append(translated)
                _record_used_chars(stats, cell)
            except Exception as ee:
                if isinstance(ee, TranslationServerConnectionError):
                    raise
                if stats is not None:
                    stats.failed += 1
                print(f"Warning: テーブル行のセル翻訳にも失敗しました: {ee}")
                translated_cells.append(cell)

    translated_row = _build_markdown_row_from_cells(translated_cells)
    _apply_translation_to_paragraph(para, translated_row)
    if stats is not None:
        stats.translated += 1
        if used_fallback:
            stats.translated_fallback += 1
    return True

def process_group(
    paragraphs_group: List[dict],
    stats: Optional[TranslationStats] = None,
    on_paragraph_done: Optional[Callable[[], None]] = None,
):
    """
    1. 指定グループの各段落の src_replaced の先頭に【id】を付与して連結し、グループ上限文字数以内の翻訳前テキストを作成
    2. 翻訳関数 translate_text を呼び出し、翻訳結果を取得
    3. 翻訳結果から各部の id と翻訳文を抽出し、該当するパラグラフに trans_auto をセットする
       - trans_status が "none" の場合、"auto" に変更
       - modified_at を現在時刻に更新
    4. 翻訳結果を反映した JSON データをファイルへ保存する
    """
    if stats is not None:
        stats.groups += 1

    def _mark_paragraph_done() -> None:
        if callable(on_paragraph_done):
            try:
                on_paragraph_done()
            except Exception:
                pass


    # --- 追加: 単体パラグラフ翻訳前にも対訳辞書置換を適用 ---
    try:
        dict_cs, dict_ci = load_dictionary(DICT_PATH)
    except Exception as e:
        print(f"[WARN] 対訳辞書の読み込みに失敗: {e}")
        dict_cs, dict_ci = {}, {}
    for para in paragraphs_group:
        src_joined = para.get("src_joined", "")
        para["src_replaced"] = replace_with_dict(src_joined, dict_cs, dict_ci)

    # 各段落のテキストを生成（src_replacedをHTMLエスケープ）
    texts = [
        f"\n【{para['id']}】\n{html.escape(para.get('src_replaced', ''))}\n" for para in paragraphs_group
    ]
    concatenated_text = "".join(texts)
    print("FOR DEBUG(LEFT200/1TRANS):" + concatenated_text[:200])

    para_by_id: Dict[str, dict] = {str(para['id']): para for para in paragraphs_group}

    try:
        translated_text = translate_text(concatenated_text, source="en", target="ja")
        _record_used_chars(stats, concatenated_text)
    except Exception as e:
        if isinstance(e, TranslationServerConnectionError):
            raise
        # グループ翻訳が落ちた場合は、段落単体へフォールバックする
        print(f"Warning: グループ翻訳に失敗。段落単体にフォールバックします: {e}")
        for pid, para in para_by_id.items():
            try:
                src_replaced = para.get("src_replaced", "") or ""
                t = translate_text(src_replaced, source="en", target="ja")
                _record_used_chars(stats, src_replaced)
                _apply_translation_to_paragraph(para, t)
                if stats is not None:
                    stats.translated += 1
                    stats.translated_fallback += 1
            except Exception as ee:
                if isinstance(ee, TranslationServerConnectionError):
                    raise
                if stats is not None:
                    stats.failed += 1
                print(f"Warning: 段落単体翻訳にも失敗しました id={pid}: {ee}")
            finally:
                _mark_paragraph_done()
        return

    extracted = _extract_translations_by_marker(translated_text)
    if not extracted:
        # マーカーが崩れて全く取れない場合は、全段落を単体翻訳へ
        print("Warning: 翻訳結果からマーカー抽出できません。段落単体にフォールバックします")
        for pid, para in para_by_id.items():
            try:
                src_replaced = para.get("src_replaced", "") or ""
                t = translate_text(src_replaced, source="en", target="ja")
                _record_used_chars(stats, src_replaced)
                _apply_translation_to_paragraph(para, t)
                if stats is not None:
                    stats.translated += 1
                    stats.translated_fallback += 1
                    stats.missing_from_batch += 1
            except Exception as ee:
                if isinstance(ee, TranslationServerConnectionError):
                    raise
                if stats is not None:
                    stats.failed += 1
                    stats.missing_from_batch += 1
                print(f"Warning: 段落単体翻訳にも失敗しました id={pid}: {ee}")
            finally:
                _mark_paragraph_done()
        return

    matched = 0
    for pid, content in extracted.items():
        if pid in para_by_id:
            _apply_translation_to_paragraph(para_by_id[pid], content)
            matched += 1
            _mark_paragraph_done()
        else:
            print(f"Warning: 翻訳結果のid {pid} に対応する段落が見つかりません。")

    if stats is not None:
        stats.translated += matched

    missing_ids = [pid for pid in para_by_id.keys() if pid not in extracted]
    if missing_ids:
        if stats is not None:
            stats.missing_from_batch += len(missing_ids)
        print(f"Warning: マーカー欠落により未反映の段落があります。フォールバックします count={len(missing_ids)}")
        for pid in missing_ids:
            para = para_by_id[pid]
            try:
                src_replaced = para.get("src_replaced", "") or ""
                t = translate_text(src_replaced, source="en", target="ja")
                _record_used_chars(stats, src_replaced)
                _apply_translation_to_paragraph(para, t)
                if stats is not None:
                    stats.translated += 1
                    stats.translated_fallback += 1
            except Exception as ee:
                if isinstance(ee, TranslationServerConnectionError):
                    raise
                if stats is not None:
                    stats.failed += 1
                print(f"Warning: 段落単体翻訳にも失敗しました id={pid}: {ee}")
            finally:
                _mark_paragraph_done()

def recalc_trans_status_counts(book_data):
    """
    段落の翻訳ステータスを集計し、trans_status_countsに書き込む。
    """
    counts = {"none": 0, "auto": 0, "draft": 0, "fixed": 0}
    for page in book_data["pages"].values(): # ページをイテレート
        for p in page.get("paragraphs", {}).values(): # ページ内の段落をイテレート
            status = p.get("trans_status", "none") # ステータスがない場合も考慮
            if status in counts:
                counts[status] += 1
            else:
                counts["none"] += 1 # 未定義のステータスは none としてカウント
                print(f"Warning: Unknown trans_status '{status}' found in paragraph ID {p.get('id', 'N/A')} during recalc. Counted as 'none'.")

    book_data["trans_status_counts"] = counts

def paraparatrans_json_file(
    json_path,
    start_page,
    end_page,
    group_max_chars: Optional[int] = None,
    progress_id: Optional[str] = None,
):
    """
    JSONファイルを読み込み、指定したページ範囲内の段落について翻訳処理を行い、結果をファイルへ保存する。
    ・filepath: JSONファイルのパス
    ・start_page, end_page: ページ範囲（両端を含む）
    各グループは group_max_chars 以内に収まるように連結して翻訳される。
    """
    print(f"翻訳処理を開始します: {json_path} ({start_page} 〜 {end_page} ページ)")

    # JSONファイル読み込み
    book_data = load_json(json_path)

    effective_group_max_chars = _normalize_group_max_chars(group_max_chars)
    stats = TranslationStats(
        translation_engine=get_current_translator(),
        group_max_chars=effective_group_max_chars,
    )

    translate_started_perf = time.perf_counter()
    progress_state: Dict[str, object] = {
        "id": str(progress_id or ""),
        "done": 0,
        "total": 0,
        "started_at_perf": translate_started_perf,
        "first_engine_access_emitted": False,
    }

    estimate_started_perf = time.perf_counter()
    estimated_total = _estimate_translation_targets(book_data, start_page, end_page)
    estimate_elapsed_ms = round((time.perf_counter() - estimate_started_perf) * 1000, 1)
    progress_state["total"] = max(0, int(estimated_total))

    _emit_translation_phase(
        progress_state,
        phase="estimate_done",
        start_page=int(start_page),
        end_page=int(end_page),
        estimate_total=int(progress_state["total"]),
        elapsed_ms=estimate_elapsed_ms,
    )
    _emit_translation_progress(progress_state, phase="start")

    # start_pageからend_pageをループしてpagetransを実行
    for page in range(start_page, end_page + 1):
        # 存在しないページはスキップ（end_page=9999などの運用を許容）
        if str(page) not in book_data.get("pages", {}):
            continue
        pagetrans(
            json_path,
            book_data,
            page,
            stats=stats,
            group_max_chars=effective_group_max_chars,
            progress_state=progress_state,
        )
        stats.pages_processed += 1

    # 翻訳ステータスの集計を更新
    recalc_trans_status_counts(book_data)
    atomicsave_json(json_path, book_data)

    progress_state["done"] = int(progress_state.get("total") or 0)
    _emit_translation_progress(progress_state, phase="done")
    _emit_translation_phase(
        progress_state,
        phase="completed",
        elapsed_ms=round((time.perf_counter() - translate_started_perf) * 1000, 1),
        pages_processed=int(stats.pages_processed),
        target=int(stats.paragraphs_target),
        translated=int(stats.translated),
        failed=int(stats.failed),
    )
    
    # 翻訳終了メッセージ（SSEログにも流れる）
    print(
        "翻訳完了: engine={engine} used_chars={used_chars} group_max_chars={group_max_chars} pages={pages} target={target} translated={translated} failed={failed} fallback={fallback} skipped_empty={skipped_empty} skipped_header_footer={skipped_hf}".format(
            engine=stats.translation_engine,
            used_chars=stats.characters_used,
            group_max_chars=stats.group_max_chars,
            pages=stats.pages_processed,
            target=stats.paragraphs_target,
            translated=stats.translated,
            failed=stats.failed,
            fallback=stats.translated_fallback,
            skipped_empty=stats.skipped_empty_src,
            skipped_hf=stats.skipped_header_footer,
        )
    )

    return book_data, asdict(stats)

def count_alphabet_chars(text: str) -> int:
    """アルファベットの文字数をカウント"""
    return len(re.findall(r'[a-zA-Z]', text))


def _is_digits_and_symbols_only(text: str) -> bool:
    """数字・記号のみ（空白は無視）の場合に True。

    - 数字: Unicode Decimal Digit
    - 記号/句読点: Unicode category が P* または S*
    """
    stripped = (text or "").strip()
    if stripped == "":
        return False

    has_content = False
    for ch in stripped:
        if ch.isspace():
            continue
        has_content = True
        if ch.isdigit():
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("S"):
            continue
        return False
    return has_content


def _should_auto_translate_as_draft(src_replaced: str) -> bool:
    """自動翻訳時に draft 扱いへ落とすべき段落か判定する。"""
    s = (src_replaced or "")
    if s.strip() == "":
        return True
    if _is_digits_and_symbols_only(s):
        return True
    alpha = count_alphabet_chars(s)
    # 「英字2文字以下」は 1〜2 文字を対象（0は数字/記号のみ等で別判定）
    if 1 <= alpha <= 2:
        return True
    return False


def _migrate_auto_to_draft_if_low_content(paragraph: dict) -> bool:
    """過去データ互換: 低情報量の段落が誤って auto になっている場合、draft に落とす。

    安全のため、既存の訳が src_replaced のコピー（または空）に見える場合のみ対象。
    """
    if (paragraph.get("trans_status") or "none") != "auto":
        return False

    src_replaced = paragraph.get("src_replaced", "") or ""
    if not _should_auto_translate_as_draft(src_replaced):
        return False

    trans_auto = paragraph.get("trans_auto", "") or ""
    trans_text = paragraph.get("trans_text", "") or ""

    # 実訳を壊さない: コピー/空 以外は触らない
    looks_like_copy = (
        trans_auto.strip() == src_replaced.strip()
        and (trans_text.strip() == src_replaced.strip() or trans_text.strip() == "")
    )
    looks_like_empty = (trans_auto.strip() == "" and trans_text.strip() == "" and src_replaced.strip() == "")
    if not (looks_like_copy or looks_like_empty):
        return False

    paragraph["trans_auto"] = src_replaced
    paragraph["trans_text"] = src_replaced
    paragraph["trans_status"] = "draft"
    paragraph["modified_at"] = datetime.now().isoformat()
    return True


def pagetrans(
    filepath,
    book_data,
    page_number,
    stats: Optional[TranslationStats] = None,
    group_max_chars: Optional[int] = None,
    progress_state: Optional[Dict[str, object]] = None,
):
    """
    各グループは group_max_chars 以内に収まるように連結して翻訳され、
    各グループ処理後に必ずファイルへ保存する。
    """
    print(f"ページ {page_number} の翻訳を開始します...")
    effective_group_max_chars = _normalize_group_max_chars(group_max_chars)

    paragraphs_dict = book_data["pages"][str(page_number)].get("paragraphs", {}) # 辞書として取得
    print(f"FOR DEBUG:段落数: {len(paragraphs_dict)}")
    if stats is not None:
        stats.paragraphs_total_in_range += len(paragraphs_dict)

    # デバッグ時は「既存訳が壊れていないか」を検知するため、事前スナップショットを取る
    before = {}
    if _debug_pagetrans_enabled():
        for pid, p in paragraphs_dict.items():
            before[str(pid)] = {
                "trans_status": p.get("trans_status"),
                "src_joined": p.get("src_joined"),
                "src_replaced": p.get("src_replaced"),
                "trans_auto": p.get("trans_auto"),
                "trans_text": p.get("trans_text"),
            }
        _pagetrans_debug(f"start page={page_number} paragraphs={len(before)}")


    # --- 追加: ページ翻訳前に全段落へ対訳辞書置換を適用 ---
    try:
        dict_cs, dict_ci = load_dictionary(DICT_PATH)
    except Exception as e:
        print(f"[WARN] 対訳辞書の読み込みに失敗: {e}")
        dict_cs, dict_ci = {}, {}
    for paragraph in paragraphs_dict.values():
        if "src_joined" in paragraph and paragraph.get("src_joined") == "":
            paragraph["src_replaced"] = ""
            paragraph["trans_auto"] = ""
            src_text = (paragraph.get("src_text") or "").strip()
            trans_text = (paragraph.get("trans_text") or "").strip()
            if src_text != "" and trans_text == src_text:
                paragraph["trans_text"] = ""
            if (paragraph.get("trans_status") or "none") == "none":
                paragraph["trans_status"] = "draft"
                paragraph["modified_at"] = datetime.now().isoformat()
            if stats is not None:
                stats.skipped_join_empty += 1
        else:
            src_joined = paragraph.get("src_joined", "")
            paragraph["src_replaced"] = replace_with_dict(src_joined, dict_cs, dict_ci)
        _migrate_auto_to_draft_if_low_content(paragraph)

    for para_id, paragraph in paragraphs_dict.items():
        if "src_joined" in paragraph and paragraph.get("src_joined") == "":
            continue

        src_replaced = paragraph.get("src_replaced", "")
        trans_status = paragraph.get("trans_status") or "none"

        # trans_status が欠けているデータを正規化（以降の条件分岐を安定させる）
        if paragraph.get("trans_status") != trans_status:
            paragraph["trans_status"] = trans_status

        # 要望: src_replaced が
        # - 数字と記号のみ
        # - 空
        # - 英字2文字以下
        # の段落は、自動翻訳で draft 扱いにする（翻訳APIへ投げない）
        # （draft/fixed の既存訳はここで壊さない）
        if trans_status == "none" and _should_auto_translate_as_draft(src_replaced):
            paragraph["trans_auto"] = src_replaced
            paragraph["trans_text"] = src_replaced
            paragraph["trans_status"] = "draft"
            paragraph["modified_at"] = datetime.now().isoformat()

    filtered_paragraphs = []
    for p in paragraphs_dict.values():
        st = p.get("trans_status") or "none"
        if st != "none":
            if stats is not None:
                stats.skipped_already_translated += 1
            continue
        if p.get("block_tag") in ("header", "footer"):
            if stats is not None:
                stats.skipped_header_footer += 1
            continue
        if (p.get("src_replaced") or "") == "":
            if stats is not None:
                stats.skipped_empty_src += 1
            continue
        filtered_paragraphs.append(p)
    # 段落ごとに翻訳するならソートは不要に思えるが、なるべく多くの段落を一度に翻訳したほうが
    # 自動翻訳が文意を理解しやすいので、ページ内での順序は保持する。
    filtered_paragraphs.sort(key=lambda p: (
        int(p['page_number']),
        int(p.get('order',0))
    ))

    print(f"翻訳対象段落数: {len(filtered_paragraphs)}")
    if stats is not None:
        stats.paragraphs_target += len(filtered_paragraphs)

    table_paragraphs = [p for p in filtered_paragraphs if _is_table_row(p)]
    normal_paragraphs = [p for p in filtered_paragraphs if not _is_table_row(p)]

    for para in table_paragraphs:
        _mark_first_engine_access(progress_state, page_number=page_number, route="table_row")
        ok = _translate_table_row_paragraph(para, stats=stats)
        if not ok and stats is not None:
            stats.failed += 1
        _advance_translation_progress(progress_state, amount=1, page_number=page_number)

    current_group = []
    current_length = 0
    # 上限文字数を超えないようにグループ化して翻訳処理を実施
    for para in normal_paragraphs:
        text_to_add = f"【{para['id']}】{para.get('src_replaced','')}"
        if current_length + len(text_to_add) > effective_group_max_chars:
            if current_group:
                _mark_first_engine_access(progress_state, page_number=page_number, route="group_batch")
                process_group(
                    current_group,
                    stats=stats,
                    on_paragraph_done=lambda: _advance_translation_progress(
                        progress_state,
                        amount=1,
                        page_number=page_number,
                    ),
                )
                current_group = []
                current_length = 0
        current_group.append(para)
        current_length += len(text_to_add)
    
    # 残ったグループがあれば処理
    if current_group:
        _mark_first_engine_access(progress_state, page_number=page_number, route="group_batch")
        process_group(
            current_group,
            stats=stats,
            on_paragraph_done=lambda: _advance_translation_progress(
                progress_state,
                amount=1,
                page_number=page_number,
            ),
        )

    atomicsave_json(filepath, book_data)  # 最後にアトミックセーブ
    print(f"ページ {page_number} の翻訳が完了しました。")

    # デバッグ: 既存(auto/draft/fixed)の段落で想定外の書き換えが発生していないか検知
    if _debug_pagetrans_enabled() and before:
        unexpected = []
        for pid, p in paragraphs_dict.items():
            pid = str(pid)
            b = before.get(pid)
            if not b:
                continue

            pre_status = b.get("trans_status")
            post_status = p.get("trans_status")
            pre_src_joined = b.get("src_joined")
            post_src_joined = p.get("src_joined")
            pre_src_replaced = b.get("src_replaced") or ""
            post_src_replaced = p.get("src_replaced") or ""
            pre_trans_auto = b.get("trans_auto")
            post_trans_auto = p.get("trans_auto")

            # 既存訳が存在する状態(未翻訳以外)で、join側でも短文規則でも説明できない trans_auto 変化を拾う
            if pre_status in {"auto", "draft", "fixed"}:
                is_joined_empty = (pre_src_joined == "") or (post_src_joined == "")
                is_expected_rule = _should_auto_translate_as_draft(pre_src_replaced)
                if pre_trans_auto != post_trans_auto and (not is_joined_empty) and (not is_expected_rule):
                    unexpected.append(
                        {
                            "id": pid,
                            "pre_status": pre_status,
                            "post_status": post_status,
                            "pre_src_replaced": pre_src_replaced,
                            "post_src_replaced": post_src_replaced,
                            "pre_trans_auto": pre_trans_auto,
                            "post_trans_auto": post_trans_auto,
                        }
                    )

        if unexpected:
            _pagetrans_debug(f"UNEXPECTED trans_auto changes: count={len(unexpected)}")
            for item in unexpected[:50]:
                _pagetrans_debug(
                    "id={id} status {pre_status}->{post_status} src_replaced '{pre_src_replaced}'->'{post_src_replaced}' trans_auto '{pre_trans_auto}'->'{post_trans_auto}'".format(
                        **item
                    )
                )
        else:
            _pagetrans_debug("no unexpected trans_auto changes")

# json を読み込んでobjectを戻す
def load_json(json_path: str):
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"{json_path} not found")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

# アトミックセーブ
def atomicsave_json(json_path, data):
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(json_path), suffix=".tmp", text=True)
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
        json.dump(data, tmp_file, ensure_ascii=False, indent=2)
    os.replace(tmp_path, json_path)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description="JSON の段落を指定ページ範囲内で翻訳し、結果を必ずファイルに保存するスクリプト"
    )
    parser.add_argument("json_file", help="JSONファイルのパス")
    parser.add_argument("start_page", type=int, help="開始ページ（含む）")
    parser.add_argument("end_page", type=int, help="終了ページ（含む）")
    parser.add_argument(
        "--group-max-chars",
        type=int,
        default=DEFAULT_GROUP_MAX_CHARS,
        help=f"1グループの最大文字数（{MIN_GROUP_MAX_CHARS}〜{MAX_GROUP_MAX_CHARS}、既定:{DEFAULT_GROUP_MAX_CHARS}）",
    )
    args = parser.parse_args()

    paraparatrans_json_file(
        args.json_file,
        args.start_page,
        args.end_page,
        group_max_chars=args.group_max_chars,
    )
