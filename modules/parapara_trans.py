"""
parapara形式ファイルを指定ページ範囲内で翻訳する。

"""

import os
import html
import json
import re
import logging
import unicodedata
from datetime import datetime
import tempfile
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

try:
    # パッケージとして読み込まれる（Flaskアプリなど）ケース
    from .api_translate import translate_text  # type: ignore
except Exception:
    # スクリプトとして直接実行されるケース（sys.path に modules が入っている前提）
    from api_translate import translate_text  # type: ignore


def _debug_pagetrans_enabled() -> bool:
    v = os.getenv("PARAPARA_DEBUG_PAGETRANS", "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _pagetrans_debug(msg: str):
    if _debug_pagetrans_enabled():
        # 既存の仕組みに載せるため print を使う（SSE/ログ出力に流れる）
        print(f"[PAGETRANS_DEBUG] {msg}")


@dataclass
class TranslationStats:
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

def process_group(paragraphs_group: List[dict], stats: Optional[TranslationStats] = None):
    """
    1. 指定グループの各段落の src_replaced の先頭に【id】を付与して連結し、5000文字以内となる翻訳前テキストを作成
    2. 翻訳関数 translate_text を呼び出し、翻訳結果を取得
    3. 翻訳結果から各部の id と翻訳文を抽出し、該当するパラグラフに trans_auto をセットする
       - trans_status が "none" の場合、"auto" に変更
       - modified_at を現在時刻に更新
    4. 翻訳結果を反映した JSON データをファイルへ保存する
    """
    if stats is not None:
        stats.groups += 1

    # 各段落のテキストを生成（src_replacedをHTMLエスケープ）
    # マーカー周りは翻訳で崩れやすいので、前後に改行を入れて境界を安定させる
    texts = [
        f"\n【{para['id']}】\n{html.escape(para.get('src_replaced', ''))}\n" for para in paragraphs_group
    ]
    concatenated_text = "".join(texts)
    # デバッグログは長すぎるとノイズになるので先頭だけ
    print("FOR DEBUG(LEFT200/1TRANS):" + concatenated_text[:200])

    # 各段落を id をキーにした辞書にする
    para_by_id: Dict[str, dict] = {str(para['id']): para for para in paragraphs_group}

    try:
        translated_text = translate_text(concatenated_text, source="en", target="ja")
    except Exception as e:
        # グループ翻訳が落ちた場合は、段落単体へフォールバックする
        print(f"Warning: グループ翻訳に失敗。段落単体にフォールバックします: {e}")
        for pid, para in para_by_id.items():
            try:
                t = translate_text(para.get("src_replaced", ""), source="en", target="ja")
                _apply_translation_to_paragraph(para, t)
                if stats is not None:
                    stats.translated += 1
                    stats.translated_fallback += 1
            except Exception as ee:
                if stats is not None:
                    stats.failed += 1
                print(f"Warning: 段落単体翻訳にも失敗しました id={pid}: {ee}")
        return

    extracted = _extract_translations_by_marker(translated_text)
    if not extracted:
        # マーカーが崩れて全く取れない場合は、全段落を単体翻訳へ
        print("Warning: 翻訳結果からマーカー抽出できません。段落単体にフォールバックします")
        for pid, para in para_by_id.items():
            try:
                t = translate_text(para.get("src_replaced", ""), source="en", target="ja")
                _apply_translation_to_paragraph(para, t)
                if stats is not None:
                    stats.translated += 1
                    stats.translated_fallback += 1
                    stats.missing_from_batch += 1
            except Exception as ee:
                if stats is not None:
                    stats.failed += 1
                    stats.missing_from_batch += 1
                print(f"Warning: 段落単体翻訳にも失敗しました id={pid}: {ee}")
        return

    matched = 0
    for pid, content in extracted.items():
        if pid in para_by_id:
            _apply_translation_to_paragraph(para_by_id[pid], content)
            matched += 1
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
                t = translate_text(para.get("src_replaced", ""), source="en", target="ja")
                _apply_translation_to_paragraph(para, t)
                if stats is not None:
                    stats.translated += 1
                    stats.translated_fallback += 1
            except Exception as ee:
                if stats is not None:
                    stats.failed += 1
                print(f"Warning: 段落単体翻訳にも失敗しました id={pid}: {ee}")

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

def paraparatrans_json_file(json_path, start_page, end_page):
    """
    JSONファイルを読み込み、指定したページ範囲内の段落について翻訳処理を行い、結果をファイルへ保存する。
    ・filepath: JSONファイルのパス
    ・start_page, end_page: ページ範囲（両端を含む）
    各グループは5000文字以内に収まるように連結して翻訳される。
    """
    print(f"翻訳処理を開始します: {json_path} ({start_page} 〜 {end_page} ページ)")

    # JSONファイル読み込み
    book_data = load_json(json_path)

    stats = TranslationStats()

    # start_pageからend_pageをループしてpagetransを実行
    for page in range(start_page, end_page + 1):
        # 存在しないページはスキップ（end_page=9999などの運用を許容）
        if str(page) not in book_data.get("pages", {}):
            continue
        pagetrans(json_path, book_data, page, stats=stats)
        stats.pages_processed += 1

    # 翻訳ステータスの集計を更新
    recalc_trans_status_counts(book_data)
    atomicsave_json(json_path, book_data)
    
    # 翻訳終了メッセージ（SSEログにも流れる）
    print(
        "翻訳完了: pages={pages} target={target} translated={translated} failed={failed} fallback={fallback} skipped_empty={skipped_empty} skipped_header_footer={skipped_hf}".format(
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


def pagetrans(filepath, book_data, page_number, stats: Optional[TranslationStats] = None):
    """
    各グループは5000文字以内に収まるように連結して翻訳され、各グループ処理後に必ずファイルへ保存する。
    """
    print(f"ページ {page_number} の翻訳を開始します...")

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

    # src_joined が明示的に空の段落（joinで結合された側など）は翻訳対象外。
    # 期待値: src_replacedは空、trans_autoも空、trans_textは触らない。
    for paragraph in paragraphs_dict.values():
        if "src_joined" in paragraph and paragraph.get("src_joined") == "":
            paragraph["src_replaced"] = ""
            paragraph["trans_auto"] = ""
            if stats is not None:
                stats.skipped_join_empty += 1

        # 過去データの自動補正: 誤って auto になっている低情報量段落を draft に落とす
        _migrate_auto_to_draft_if_low_content(paragraph)

    for para_id, paragraph in paragraphs_dict.items():
        if "src_joined" in paragraph and paragraph.get("src_joined") == "":
            continue

        src_replaced = paragraph.get("src_replaced", "")
        trans_status = paragraph.get("trans_status")

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
        st = p.get("trans_status")
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

    current_group = []
    current_length = 0
    # 4000文字を上限にグループ化して翻訳処理を実施
    for para in filtered_paragraphs:
        text_to_add = f"【{para['id']}】{para.get('src_replaced','')}"
        if current_length + len(text_to_add) > 4000:
            if current_group:
                process_group(current_group, stats=stats)
                current_group = []
                current_length = 0
        current_group.append(para)
        current_length += len(text_to_add)
    
    # 残ったグループがあれば処理
    if current_group:
        process_group(current_group, stats=stats)

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
    args = parser.parse_args()

    paraparatrans_json_file(args.json_file, args.start_page, args.end_page)
