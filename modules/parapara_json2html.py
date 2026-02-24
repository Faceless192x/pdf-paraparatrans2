import json
import sys
import os
import re

def json2html(json_file_path: str, display_unit: str = "page"):
    # JSONファイルの読み込み
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    display_unit = (display_unit or "page").strip().lower()
    if display_unit not in {"all", "page", "h1", "h2"}:
        display_unit = "page"

    title = data.get("title", "PDF 翻訳")
    # 目次と本文のエントリを保持する変数
    toc_entries = []
    content_by_chunk = []
    current_chunk_content = ""
    anchor_page_map = {}
    anchor_chunk_map = {}
    current_chunk_index = 0
    current_chunk_label = ""
    current_chunk_first_page = None
    # グループ化用変数
    open_group = None
    # 現在のページ番号を覚えておく
    current_page_number = None

    paragraphs_list = []
    for page in data["pages"].values():
        for para in page["paragraphs"].values():
            paragraphs_list.append(para)

    # 全段落を page_number, order , column_order , bbox[1] を数値化して順にソート
    paragraphs_list.sort(key=lambda p: (
        int(p['page_number']),
        int(p.get('order',0)),
        int(p['column_order']),
        float(p['bbox'][1])
    ))

    # 目次データを階層化する関数
    def build_toc_tree(paragraphs):
        toc_tree = []
        level_stack = [toc_tree] # 現在のレベルのリストを保持
        last_level = 0

        for paragraph in paragraphs:
            try:
                join_flag = int(paragraph.get("join") or 0)
            except (TypeError, ValueError):
                join_flag = 0

            block_tag = paragraph.get("block_tag", "div").lower()
            if block_tag not in [f'h{i}' for i in range(1, 7)]:
                continue

            # join=1 の段落は、前段落へ結合される側なので目次対象外
            if join_flag == 1:
                continue

            level = int(block_tag[1])
            text = paragraph.get("trans_text", paragraph.get("src_joined", "無題"))
            # 一意な段落IDを生成
            unique_paragraph_id = f"{paragraph.get('page_number', '0')}_{paragraph.get('id', '0')}"

            # 新しいレベルの項目を作成
            new_item = {
                "text": text,
                "id": unique_paragraph_id,
                "level": level,
                "children": []
            }

            if level > last_level:
                # レベルが深くなった場合、新しいリストを現在のレベルに追加し、スタックにプッシュ
                if level_stack[-1] and isinstance(level_stack[-1][-1], dict):
                     level_stack[-1][-1]["children"].append(new_item)
                     level_stack.append(level_stack[-1][-1]["children"])
                else:
                     # エラーケースまたは最初の項目
                     level_stack[-1].append(new_item)
                     level_stack.append(new_item["children"])

            elif level < last_level:
                # レベルが浅くなった場合、スタックからポップ
                # スタックが空にならないように、ポップする回数を制限
                pop_count = min(last_level - level, len(level_stack) - 1)
                for _ in range(pop_count):
                    level_stack.pop()
                # ポップ後にスタックが空でなければ追加
                if level_stack:
                    level_stack[-1].append(new_item)
                else:
                    # エラーケース: スタックが空になった場合は、toc_treeのルートに追加
                    toc_tree.append(new_item)


            else:
                # 同じレベルの場合、現在のレベルのリストに追加
                # スタックが空でないことを確認してから追加
                if level_stack:
                    level_stack[-1].append(new_item)
                else:
                     # エラーケース: スタックが空の場合は、toc_treeのルートに追加
                    toc_tree.append(new_item)

            last_level = level

        return toc_tree

    # 階層化された目次データを生成
    toc_tree_data = build_toc_tree(paragraphs_list)

    # 階層化された目次データをHTMLリストに変換する関数
    def render_toc_html(toc_items):
        html = '<ul>'
        for item in toc_items:
            has_children = bool(item["children"])
            # 子要素がある場合のみマーカーを付与
            indicator = f'<span class="toggle-indicator">{"▼" if has_children else ""}</span>'
            html += f'<li class="toc-item level-{item["level"]}">'
            html += f'<a href="#{item["id"]}">{indicator}{item["text"]}</a>'
            if has_children:
                html += render_toc_html(item["children"])
            html += '</li>'
        html += '</ul>'
        return html

    # 目次HTMLを生成
    toc_html_content = render_toc_html(toc_tree_data)

    def split_markdown_row_cells(row_text: str):
        if not row_text:
            return []
        parts = re.split(r"(?<!\\)\|", row_text)
        if parts and parts[0].strip() == "":
            parts = parts[1:]
        if parts and parts[-1].strip() == "":
            parts = parts[:-1]
        return [p.replace(r"\|", "|").strip() for p in parts]

    def build_table_row_html(cells, cell_tag: str):
        if not cells:
            return ""
        inner = "".join([f"<{cell_tag}>{c}</{cell_tag}>" for c in cells])
        return f"<tr>{inner}</tr>"

    table_rows_trans = []
    table_rows_src = []
    table_anchor_id = None
    table_open = False

    def flush_chunk_if_needed():
        nonlocal content_by_chunk, current_chunk_content
        nonlocal current_chunk_index, current_chunk_label, current_chunk_first_page
        if current_chunk_index == 0:
            return
        if not current_chunk_content.strip():
            return
        content_by_chunk.append(
            {
                "chunk_index": current_chunk_index,
                "label": current_chunk_label,
                "html": current_chunk_content,
                "page": current_chunk_first_page,
            }
        )
        current_chunk_content = ""

    def start_new_chunk(label: str, first_page: int):
        nonlocal current_chunk_index, current_chunk_label, current_chunk_first_page
        if current_chunk_index != 0:
            flush_chunk_if_needed()
        current_chunk_index += 1
        current_chunk_label = label
        current_chunk_first_page = first_page

    def flush_table_if_needed():
        nonlocal current_chunk_content, table_rows_trans, table_rows_src, table_anchor_id, table_open
        if not table_open:
            return
        trans_table = "<table class=\"para-table\"><tbody>" + "".join(table_rows_trans) + "</tbody></table>"
        src_table = "<table class=\"para-table\"><tbody>" + "".join(table_rows_src) + "</tbody></table>"
        anchor_html = ""
        id_html = ""
        if table_anchor_id:
            anchor_html = f'<div class="paragraph-anchor" id="{table_anchor_id}"></div>'
            id_html = f'<div class="paragraph-id hidden-text">{table_anchor_id}</div>'
        current_chunk_content += f'''
        <div class="paragraph-container">
            {anchor_html}
            {id_html}
            <div class="trans-text">{trans_table}</div>
            <div class="src-joined">{src_table}</div>
        </div>
        '''
        table_rows_trans = []
        table_rows_src = []
        table_anchor_id = None
        table_open = False


    for paragraph in paragraphs_list:  # ソートされたリストをイテレート
        # --- ページ番号が変わったら改ページを挿入 ---
        page_number = int(paragraph.get("page_number", 0))
        if page_number != current_page_number:
            flush_table_if_needed()
            if open_group is not None:
                current_chunk_content += '</div></div>'
                open_group = None
            if display_unit == "page":
                start_new_chunk(f"Page {page_number}", page_number)
            elif current_chunk_index == 0:
                label = "All" if display_unit == "all" else f"{display_unit.upper()} 1"
                start_new_chunk(label, page_number)
            current_page_number = page_number
            current_chunk_content += f'<div class="page-break"></div>Page {page_number}'

        # --- 追加: 空文字のみの段落をスキップ ---
        trans_text = paragraph.get("trans_text", "")
        src_joined = paragraph.get("src_joined", "")
        if not trans_text.strip() and not src_joined.strip():
            continue

        # グループIDで記事を囲む
        group_id = paragraph.get("group_id")
        if group_id != open_group:
            flush_table_if_needed()
            # 既存のグループを閉じる
            if open_group is not None:
                current_chunk_content += '</div></div>'
            # 新しいグループを開始
            if group_id:
                current_chunk_content += f'<div class="article-group" data-group="{group_id}"><div class="paragraph-group">'
            open_group = group_id

        unique_paragraph_id = f"{paragraph.get('page_number','0')}_{paragraph.get('id','0')}"
        anchor_page_map[unique_paragraph_id] = page_number
        if current_chunk_index == 0:
            label = "All" if display_unit == "all" else f"{display_unit.upper()} 1"
            start_new_chunk(label, page_number)
        anchor_chunk_map[unique_paragraph_id] = current_chunk_index

        original_block_tag = str(paragraph.get("block_tag", "div"))
        block_tag = original_block_tag.lower()
        if block_tag in ("header", "footer"):
            flush_table_if_needed()
            continue

        if display_unit in {"h1", "h2"} and (block_tag == display_unit or (display_unit == "h2" and block_tag == "h1")):
            flush_table_if_needed()
            if open_group is not None:
                current_chunk_content += '</div></div>'
                open_group = None
            heading_text = (trans_text or src_joined or "").strip()
            label_prefix = "H1" if block_tag == "h1" else display_unit.upper()
            heading_text = heading_text if heading_text else f"{label_prefix} {current_chunk_index + 1}"
            start_new_chunk(f"{label_prefix}: {heading_text}", page_number)

        if block_tag in ("th", "tr"):
            if not table_open:
                table_open = True
                table_anchor_id = unique_paragraph_id

            trans_cells = split_markdown_row_cells(trans_text)
            if not trans_cells and trans_text.strip():
                trans_cells = [trans_text.strip()]

            src_cells = split_markdown_row_cells(src_joined)
            if not src_cells and src_joined.strip():
                src_cells = [src_joined.strip()]

            cell_tag = "th" if block_tag == "th" else "td"
            trans_row_html = build_table_row_html(trans_cells, cell_tag)
            src_row_html = build_table_row_html(src_cells, cell_tag)
            if trans_row_html or src_row_html:
                table_rows_trans.append(trans_row_html)
                table_rows_src.append(src_row_html)
            continue

        flush_table_if_needed()

        safe_flow_tags = {"p", "div"} | {f"h{i}" for i in range(1, 7)}
        render_tag = block_tag if block_tag in safe_flow_tags else "div"

        # 段落を追加
        current_chunk_content += f'''
        <div class="paragraph-container">
            <div class="paragraph-anchor" id="{unique_paragraph_id}"></div>
            <div class="paragraph-id hidden-text">{unique_paragraph_id}</div>
            <div class="trans-text"><{render_tag} data-block-tag="{block_tag}">{trans_text}</{render_tag}></div>
            <div class="src-joined"><{render_tag} data-block-tag="{block_tag}">{src_joined}</{render_tag}></div>
        </div>
        '''

    # 最後のグループを閉じる
    flush_table_if_needed()
    if open_group is not None:
        current_chunk_content += '</div></div>'
        open_group = None
    flush_chunk_if_needed()

    pages_payload = [
        {
            "chunk_index": chunk["chunk_index"],
            "label": chunk["label"],
            "html": chunk["html"],
            "page": chunk.get("page"),
        }
        for chunk in content_by_chunk
    ]
    pages_json = json.dumps(pages_payload, ensure_ascii=False).replace("</", "<\\/")
    anchor_map_json = json.dumps(anchor_page_map, ensure_ascii=False).replace("</", "<\\/")
    anchor_chunk_map_json = json.dumps(anchor_chunk_map, ensure_ascii=False).replace("</", "<\\/")

    # HTML全体の構造
    html_content = '''
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <title>''' + title + '''</title>
        <style>
            body {
                margin: 0;
                padding: 0;
                font-family: Arial, sans-serif;
                display: flex;
                flex-direction: column;
                background-color: #fff;
                color: #000;
            }
            .header {
                position: fixed;
                top: 0; left: 0; right: 0;
                display: flex;
                align-items: center;
                background-color: #2e3b4e;
                color: #fff;
                z-index: 1000;
            }
            .header .buttons {
                margin-right: auto;
            }
            .header button {
                background: #3f4e62;
                color: white;
                border: none;
                padding: 5px 10px;
                font-size: 12px;
                cursor: pointer;
                margin-right: 4px;
            }
            .header .title {
                font-size: 18px;
                font-weight: bold;
            }
            .header .powered {
                font-size: 12px;
                margin-left: 20px;
            }
            .header .page-controls {
                margin-left: 20px;
                display: inline-flex;
                align-items: center;
                gap: 6px;
            }
            .header .page-controls .page-status {
                font-size: 12px;
                padding: 2px 6px;
                background: #1f2a3a;
                border-radius: 4px;
            }

            .container {
                display: flex;
                margin-top: 40px;
                height: calc(100vh - 50px);
            }
            .toc {
                background-color: #f8f8f8;
                color: #333;
                padding: 2px;
                border-right: 1px solid #ccc;
                overflow-y: auto;
                max-width: 25%;
                height: 100%;
            }
            .content {
                flex: 1;
                padding: 8px;
                overflow-y: auto;
                background-color: #ffffff;
            }

            .paragraph-container {
                display: flex;
                gap: 10px;
                margin-bottom: 2px;
            }
            .paragraph-anchor {
                display: inline-block;
                width: 0;
                height: 0;
                overflow: hidden;
            }
            .paragraph-id {
                display: inline-block;
                width: 8ch;
                text-align: right;
                font-family: monospace;
                font-size: 80%;
            }

            .src-joined {
                background-color: #fff8dc;
                flex: 1;
                padding: 5px 10px;
            }
            .trans-text {
                background-color: #e1f5e8;
                flex: 1;
                padding: 5px 10px;
            }

            .hidden-text {
                display: none;
            }
            .paragraph-container p,
            .paragraph-container div {
                margin: 0;
                line-height: 1.5;
                font-family: Arial, sans-serif;
            }

            .para-table {
                width: 100%;
                border-collapse: collapse;
                table-layout: fixed;
            }
            .para-table th,
            .para-table td {
                border: 1px solid #888;
                padding: 4px 6px;
                vertical-align: top;
                word-break: break-word;
            }

            .paragraph-container h1,
            .paragraph-container h2,
            .paragraph-container h3,
            .paragraph-container h4,
            .paragraph-container h5,
            .paragraph-container h6 {
                margin: 0;
                padding: 0.5em;
                line-height: 1.5;
                font-family: Arial, sans-serif;
            }

            h2 {
                font-size: 180%;
                color: #222;
                border-left: 6px solid #a2a;
                padding-left: 10px;
                background-color: #f2e8f7;
            }
            h3 {
                font-size: 150%;
                color: #114488;
                border-left: 4px solid #88a;
                padding-left: 8px;
                background-color: #e5f0ff;
            }
            h4 {
                font-size: 120%;
                color: #333;
                border-left: 3px solid #6a6;
                padding-left: 6px;
                background-color: #f2fff2;
            }
            h5 {
                font-size: 110%;
                font-weight: bold;
                color: #444;
            }
            h6 {
                font-weight: bold;
                color: #555;
            }

            .paragraph-group {
                padding: 6px;
                border: 4px solid #c33;
                background-color: #fff5f5;
            }

            ul {
                margin: 4px;
                padding: 4px;
                line-height: 1.2;
                list-style: none;
            }

            .toc-item {
                cursor: pointer;
                margin-bottom: 2px;
            }
            .toc-item a {
                text-decoration: none;
                color: #333;
                display: block;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                padding: 2px 0;
            }
            .toc-item a:hover {
                text-decoration: underline;
            }
            .toc-item ul {
                margin-left: 10px;
                border-left: 1px dotted #ccc;
                padding-left: 5px;
            }
            .toc-item ul.collapsed {
                display: none;
            }
            .toc-item.level-1 > a { font-weight: bold; margin-top: 5px; }
            .toc-item.level-2 > a { margin-left: 5px; }
            .toc-item.level-3 > a { margin-left: 10px; }
            .toc-item.level-4 > a { margin-left: 15px; }
            .toc-item.level-5 > a { margin-left: 20px; }
            .toc-item.level-6 > a { margin-left: 25px; }

            .toggle-indicator {
                display: inline-block;
                width: 1em;
                text-align: center;
                cursor: pointer;
                margin-right: 4px;
            }

            .page-break {
                page-break-before: always;
                margin: 20px 0;
            }

            .toc-item.active-page > a {
                color: #007bff;
                background-color: #e0f7fa;
            }

            /* ダークモード */
            @media (prefers-color-scheme: dark) {
                body {
                    background-color: #1e1e1e;
                    color: #e0e0e0;
                }
                .header {
                    background-color: #2c2c2c;
                    color: #fff;
                }
                .header button {
                    background: #444;
                    color: #fff;
                }
                .toc {
                    background-color: #2b2b2b;
                    color: #ccc;
                    border-right-color: #444;
                }
                .toc-item a {
                    color: #ccc;
                }
                .toc-item a:hover {
                    color: #fff;
                }
                .content {
                    background-color: #1e1e1e;
                }
                .src-joined {
                    background-color: #3a3a2e;
                }
                .trans-text {
                    background-color: #2f4f3a;
                }
                h2 {
                    color: #ddd;
                    background-color: #3e2f45;
                    border-left-color: #cc99cc;
                }
                h3 {
                    color: #aaccee;
                    background-color: #2a3540;
                    border-left-color: #6688aa;
                }
                h4 {
                    color: #cfc;
                    background-color: #2f3f2f;
                    border-left-color: #6a6;
                }
                h5, h6 {
                    color: #ccc;
                }
                .paragraph-group {
                    background-color: #3f2a2a;
                    border-color: #c66;
                }
                .toc-item.active-page > a {
                    background-color: #35566a;
                    color: #90caff;
                }
            }
        </style>

    </head>
    <body>
        <div class="header">
            <div class="buttons">
                <button onclick="toggleToc()">目次</button>
                <button onclick="toggleId()">ID</button>
                <button onclick="toggleTrans()">訳文</button>
                <button onclick="toggleSrc()">原文</button>
            </div>
            <span class="title">''' + title + '''</span>
            <span class="page-controls">
                <button onclick="prevPage()">Prev</button>
                <button onclick="nextPage()">Next</button>
                <span class="page-status" id="pageStatus">Page</span>
            </span>
            <span class="powered">Powered by PDF-ParaParaTrans</span>
        </div>
        <div class="container">
            <div class="toc" id="toc">
    ''' + toc_html_content + '''
            </div>
            <div class="content" id="content"></div>
        </div>
        <script>
            document.addEventListener('DOMContentLoaded', function() {
                const PAGES = ''' + pages_json + ''';
                const ANCHOR_PAGE = ''' + anchor_map_json + ''';
                const ANCHOR_CHUNK = ''' + anchor_chunk_map_json + ''';
                const content = document.getElementById('content');
                const pageStatus = document.getElementById('pageStatus');
                let currentIndex = 0;

                function renderPage(index, anchorId) {
                    if (!PAGES.length) {
                        content.innerHTML = '';
                        if (pageStatus) pageStatus.textContent = 'Page -';
                        return;
                    }
                    currentIndex = Math.min(Math.max(index, 0), PAGES.length - 1);
                    const page = PAGES[currentIndex];
                    content.innerHTML = page.html;
                    if (pageStatus) {
                        const label = page.label || `Unit ${currentIndex + 1}`;
                        pageStatus.textContent = `${label} (${currentIndex + 1}/${PAGES.length})`;
                    }
                    highlightTocForPage(page.page);
                    if (anchorId) {
                        const target = document.getElementById(anchorId);
                        if (target) target.scrollIntoView({ behavior: 'smooth' });
                    } else {
                        content.scrollTop = 0;
                    }
                }

                function highlightTocForPage(pageNum) {
                    document.querySelectorAll('.toc-item').forEach(item =>
                        item.classList.remove('active-page')
                    );
                    document.querySelectorAll(`.toc-item a[href^="#${pageNum}_"]`)
                        .forEach(link => link.parentElement.classList.add('active-page'));
                }

                window.prevPage = function() {
                    renderPage(currentIndex - 1);
                };
                window.nextPage = function() {
                    renderPage(currentIndex + 1);
                };

                const tocItems = document.querySelectorAll('.toc-item');
                tocItems.forEach(item => {
                    const indicator = item.querySelector('.toggle-indicator');
                    const childList = item.querySelector('ul');

                    // マーカークリック → 折りたたみ／展開 のみ
                    if (indicator && childList) {
                        indicator.addEventListener('click', function(event) {
                            event.stopPropagation();
                            childList.classList.toggle('collapsed');
                            this.textContent = childList.classList.contains('collapsed') ? '▶' : '▼';
                        });
                    }

                    // 見出しリンククリック → スクロールのみ
                    const link = item.querySelector('a');
                    if (link) {
                        link.addEventListener('click', function(event) {
                            event.preventDefault();
                            const targetId = this.getAttribute('href').substring(1);
                            const chunkId = ANCHOR_CHUNK[targetId];
                            if (chunkId) {
                                const pageIndex = PAGES.findIndex(p => p.chunk_index === chunkId);
                                renderPage(pageIndex, targetId);
                            }
                        });
                    }
                });

                // 初期状態でh2以降を折りたたむ
                document.querySelectorAll('.toc-item:not(.level-1) > ul')
                        .forEach(ul => ul.classList.add('collapsed'));

                renderPage(0);
            });

            function toggleToc() {
                let toc = document.getElementById('toc');
                toc.classList.toggle('hidden');
                // flex レイアウトによりコンテンツ幅は自動調整される
            }

            function toggleSrc() {
                let srcTexts = document.getElementsByClassName('src-joined');
                for (let i = 0; i < srcTexts.length; i++) {
                    srcTexts[i].classList.toggle('hidden-text');
                }
            }

            function toggleTrans() {
                let transTexts = document.getElementsByClassName('trans-text');
                for (let i = 0; i < transTexts.length; i++) {
                    transTexts[i].classList.toggle('hidden-text');
                }
            }

            // 追加：段落ID表示の ON/OFF
            function toggleId() {
                let idElems = document.getElementsByClassName('paragraph-id');
                for (let i = 0; i < idElems.length; i++) {
                    idElems[i].classList.toggle('hidden-text');
                }
            }
        </script>
    </body>
    </html>
    '''

    # 出力ファイル名の生成
    output_file_path = os.path.splitext(json_file_path)[0] + '.html'

    # HTMLファイルの保存
    with open(output_file_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"HTMLファイルが生成されました: {output_file_path}")

def main():
    if len(sys.argv) != 2:
        print("使い方: python parapara_json2html.py 翻訳データ.json")
        return
    
    json_file_path = sys.argv[1]
    json2html(json_file_path)

if __name__ == "__main__":
    main()
