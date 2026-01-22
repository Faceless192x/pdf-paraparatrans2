#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
parapara_join.py

JSON ファイル内の全段落を対象に、join フラグに基づいて src_joined を前の段落にマージします。
ターミナルと関数呼び出しの両方で利用可能。
Usage:
    python parapara_join.py path/to/data.json

Example as function:
    from parapara_join import join_paragraphs_in_file
    data = join_paragraphs_in_file("data.json")
"""
import os
import json
import tempfile
import argparse

def join_replaced_paragraphs(book_data):
    """
    ドキュメント全体の段落を page, order 順にソートし、
    join=1 の段落の src_text を直前の非結合段落にスペース付きで結合してsrc_joinedにセット。
    結合された段落のsrc_joinedは空文字にする。
    join フィールドが存在しない場合は結合しないものとみなす。
    """

    # page順にparagraphを取得して配列にする
    all_paragraphs = []
    for page in book_data["pages"].values():
        for para in page["paragraphs"].values():
            # block_tagがheaderかfooterは除外。それ以外はall_paragraphsに追加
            if para.get('block_tag') not in ['header', 'footer']:
                all_paragraphs.append(para)

    # 全段落を page_number, order , column_order , bbox[1] を数値化して順にソート
    all_paragraphs.sort(key=lambda p: (
        int(p['page_number']),
        int(p['order']),
        int(p['column_order']),
        float(p['bbox'][1])
    ))
    # block_tag ごとに join_target_paragraph を保持
    join_target_paragraphs = {}
    for p in all_paragraphs:
        tag = p.get('block_tag', '')
        curr_src_text = p.get('src_text', '')
        curr_src_joined = p.get('src_joined', '')
        curr_trans_status = p.get('trans_status', '')

        if p.get('join', 0) == 1 and join_target_paragraphs.get(tag):
            # 結合指定の段落(join=1)で同タグの開始段落があれば開始段落のsrc_joinedにsrc_textをに追加。
            target_src_joined = join_target_paragraphs[tag].get('src_joined', '')
            target_trans_status = join_target_paragraphs[tag].get('trans_status', '')
            merged = (target_src_joined + " " + curr_src_text).strip()
            join_target_paragraphs[tag]['src_joined'] = merged
            join_target_paragraphs[tag]['src_replaced'] = merged

            if target_trans_status in ['none', 'auto']:
                join_target_paragraphs[tag]['trans_text'] = merged
                join_target_paragraphs[tag]['trans_status'] = "none"

            # 違う場合はtrans_autoもクリア
            # 2個以上結合される場合どうしても変わってしまうのでクリアされるのは仕様上やむなし
            if target_src_joined != merged:
                join_target_paragraphs[tag]['trans_auto'] = merged

            # 現在の段落はクリア
            p['src_joined'] = ''
            p['src_replaced'] = ''
            p['trans_auto'] = ''
            # ステータスが none/auto の場合は 訳をクリアして fixed にする
            if p.get('trans_status', '') in ['none', 'auto']:
                p['trans_text'] = ''
                p['trans_status'] = "fixed"
        else:
            # 結合指定のない段落(join=0)に来たら
            p['src_joined'] = curr_src_text
            p['src_replaced'] = curr_src_text

            if curr_trans_status in ['none']:
                p['trans_auto'] = curr_src_text
                p['trans_text'] = curr_src_text

            # 自分を結合対象段落にセット
            join_target_paragraphs[tag] = p

    return book_data

def join_replaced_paragraphs_in_file(json_file):
    """
    JSON ファイルを読み込み、merge_join_paragraphs を実行して結果を保存。

    Returns:
        data (dict): 更新後の JSON データ
    """
    data = load_json(json_file)

    join_replaced_paragraphs(data)
    atomicsave_json(json_file, data)
    return data


# json を読み込んでobjectを戻す
def load_json(json_path: str):
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"{json_path} not found")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

# アトミックセーブ
def atomicsave_json(json_path, data):
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(json_path), suffix=".json", text=True)
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
        json.dump(data, tmp_file, ensure_ascii=False, indent=2)
    os.replace(tmp_path, json_path)

def main():
    parser = argparse.ArgumentParser(description='join フラグに基づいて src_joined をマージする')
    parser.add_argument('json_file', help='入力・出力共通の JSON ファイルパス')
    args = parser.parse_args()

    data = join_replaced_paragraphs_in_file(args.json_file)
    print(f"Joined src_joined for entire document in {args.json_file}")


if __name__ == '__main__':
    main()
