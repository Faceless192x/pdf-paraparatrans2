"""
parapara形式ファイルを指定ページ範囲内で翻訳する。

"""

import os
import html
import json
import re
import logging
from datetime import datetime
import tempfile

from api_translate import translate_text  # 翻訳関数は別ファイルで定義済み
import stream_logger


def _debug_pagetrans_enabled() -> bool:
    v = os.getenv("PARAPARA_DEBUG_PAGETRANS", "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _pagetrans_debug(msg: str):
    if _debug_pagetrans_enabled():
        # 既存の仕組みに載せるため print を使う（SSE/ログ出力に流れる）
        print(f"[PAGETRANS_DEBUG] {msg}")

def process_group(paragraphs_group):
    """
    1. 指定グループの各段落の src_replaced の先頭に【id】を付与して連結し、5000文字以内となる翻訳前テキストを作成
    2. 翻訳関数 translate_text を呼び出し、翻訳結果を取得
    3. 翻訳結果から各部の id と翻訳文を抽出し、該当するパラグラフに trans_auto をセットする
       - trans_status が "none" の場合、"auto" に変更
       - modified_at を現在時刻に更新
    4. 翻訳結果を反映した JSON データをファイルへ保存する
    """
    # 各段落のテキストを生成（src_replacedをHTMLエスケープ）
    texts = [f"【{para['id']}】{html.escape(para['src_replaced'])}" for para in paragraphs_group]
    concatenated_text = "".join(texts)
    # concatenated_textの最初の50文字をコンソールに出力
    print("FOR DEBUG(LEFT50/1TRANS):" + concatenated_text)
    # print("FOR DEBUG(LEFT50/1TRANS):" + concatenated_text[:50])

    try:
        translated_text = translate_text(concatenated_text, source="en", target="ja")
    except Exception as e:
        print(f"翻訳APIの呼び出しに失敗しました: {e}")
        raise Exception(f"翻訳APIの呼び出しに失敗しました: {e}")
    
    # 翻訳結果を【0_0】のパターンで分割
    parts = re.split(r'(?=【\d+_\d+】)', translated_text)
    # 空白を除去
    parts = [part.strip() for part in parts if part.strip()]

    stream_logger.init_logging()

    # 各段落を id をキーにした辞書にする
    para_by_id = { str(para['id']): para for para in paragraphs_group }
    
    # 翻訳結果をパターンマッチで抽出し、対応するパラグラフにセットする
    for part in parts:
        print(f"FOR DEBUG:{part}")
        m = re.match(r'【(\d+_\d+)】(.*)', part, re.DOTALL)
        if m:
            para_id, translated_content = m.group(1), m.group(2)
            # q_ と _q が前後に区切り文字（英数字以外、または行頭・行末）の場合にのみ除去する
            translated_content = re.sub(
                r'(?:(?<=^)|(?<=[^A-Za-z]))q_([A-Za-z]+)_q(?=$|[^A-Za-z])',
                r'\1',
                translated_content
            )
            if para_id in para_by_id:
                para = para_by_id[para_id]
                para['trans_auto'] = translated_content
                para['trans_text'] = translated_content
                para['trans_status'] = 'auto'
                para['modified_at'] = datetime.now().isoformat()
            else:
                print(f"Warning: 翻訳結果のid {para_id} に対応する段落が見つかりません。")
        else:
            print("Warning: 翻訳結果のマッチ数が0。")

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

    # start_pageからend_pageをループしてpagetransを実行
    for page in range(start_page, end_page + 1):
        pagetrans(json_path, book_data, page)

    # 翻訳ステータスの集計を更新
    recalc_trans_status_counts(book_data)
    atomicsave_json(json_path, book_data)
    
    return book_data

def count_alphabet_chars(text: str) -> int:
    """アルファベットの文字数をカウント"""
    return len(re.findall(r'[a-zA-Z]', text))


def pagetrans(filepath, book_data, page_number):
    """
    各グループは5000文字以内に収まるように連結して翻訳され、各グループ処理後に必ずファイルへ保存する。
    """
    print(f"ページ {page_number} の翻訳を開始します...")

    paragraphs_dict = book_data["pages"][str(page_number)].get("paragraphs", {}) # 辞書として取得
    print(f"FOR DEBUG:段落数: {len(paragraphs_dict)}")

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

    for para_id, paragraph in paragraphs_dict.items():
        if "src_joined" in paragraph and paragraph.get("src_joined") == "":
            continue

        src_replaced = paragraph.get("src_replaced", "")
        trans_status = paragraph.get("trans_status")

        # 未翻訳(none)の段落のみ、src_replaced が空なら trans_auto を空にする
        # （auto/draft/fixed の既存訳はここで壊さない）
        if trans_status == "none" and src_replaced == "":
            paragraph["trans_auto"] = ""

        # (要望2) 英字2文字以下なら src_replaced セットでよい（none/auto に適用）
        # statusがdraftとfixedは翻訳処理では触らない
        if trans_status in {"none", "auto"}:
            if src_replaced != "" and count_alphabet_chars(src_replaced) < 3:
                paragraph["trans_auto"] = src_replaced
                paragraph["trans_status"] = "auto"

    filtered_paragraphs = [
        p for p in paragraphs_dict.values() # 辞書の値 (パラグラフオブジェクト) をイテレート
        if p.get("trans_status") == "none" 
        and p.get("block_tag") not in ("header", "footer")
    ]
    # 段落ごとに翻訳するならソートは不要に思えるが、なるべく多くの段落を一度に翻訳したほうが
    # 自動翻訳が文意を理解しやすいので、ページ内での順序は保持する。
    filtered_paragraphs.sort(key=lambda p: (
        int(p['page_number']),
        int(p.get('order',0))
    ))

    print(f"翻訳対象段落数: {len(filtered_paragraphs)}")

    current_group = []
    current_length = 0
    # 4000文字を上限にグループ化して翻訳処理を実施
    for para in filtered_paragraphs:
        text_to_add = f"【{para['id']}】{para['src_replaced']}"
        print(f"FOR DEBUG:{text_to_add}")
        if current_length + len(text_to_add) > 4000:
            if current_group:
                process_group(current_group)
                current_group = []
                current_length = 0
        current_group.append(para)
        current_length += len(text_to_add)
    
    # 残ったグループがあれば処理
    if current_group:
        process_group(current_group)

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
                is_short_rule = (count_alphabet_chars(pre_src_replaced) < 3 and pre_src_replaced != "")
                if pre_trans_auto != post_trans_auto and (not is_joined_empty) and (not is_short_rule):
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
