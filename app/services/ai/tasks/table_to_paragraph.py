"""表→段落タスクビルダー。

選択した表領域の画像や抽出テキストを受け取り、AIRequest を構築する。
プロバイダを意識せず、プロンプト構築と入力正規化だけを担う。

使用例（自然文段落生成）::

    from app.services.ai.tasks.table_to_paragraph import build_request
    from app.services.ai import router

    req = build_request(
        rows_text=["A 12.5 18.2", "B 10.1 17.8"],
        image_png=png_bytes,          # 任意
        table_title="Table 3.2",      # 任意
        instruction="傾向を中心に説明",  # 任意
    )
    resp = router.generate(req)
    paragraph_text = resp.text

使用例（HTML→縦パイプ形式）::

    from app.services.ai.tasks.table_to_paragraph import build_html_request, html_to_pipe_rows
    from app.services.ai import router

    req = build_html_request(rows_text=["A 12.5 18.2", "B 10.1 17.8"], image_png=png_bytes)
    resp = router.generate(req)
    rows = html_to_pipe_rows(resp.text)
    # rows = [("th", "項目 | 値1 | 値2"), ("tr", "A | 12.5 | 18.2"), ...]
"""

from __future__ import annotations

import re

from app.services.ai.types import AIRequest


def _normalize_cell_text(text: str) -> str:
    """セルテキストの余分な空白・改行を1スペースに正規化する。"""
    return " ".join(text.split())


_SYSTEM_PROMPT = (
    "あなたはPDF内の表を自然な説明文に変換するアシスタントです。\n"
    "入力された表の内容をもとに、日本語の1〜3段落で要約してください。\n"
    "要件:\n"
    "- 列や行の値をそのまま羅列しすぎず、意味のある比較や傾向を説明する\n"
    "- 表題、列見出し、単位、注記があれば反映する\n"
    "- 不明な値は推測しない\n"
    "- 読み取りに自信がない箇所は曖昧表現にする\n"
    "- Markdown表は出力せず、通常の文章で出力する\n"
)

_HTML_TABLE_PROMPT = (
    "以下の表の内容を読み取り、HTML の <table> タグで正確に出力してください。\n"
    "要件:\n"
    "- ヘッダ行は <tr><th>...</th></tr> で出力する\n"
    "- データ行は <tr><td>...</td></tr> で出力する\n"
    "- <table> タグ以外のテキスト（説明文、コードブロック記号など）は出力しない\n"
    "- セルの値はそのまま正確に出力する\n"
    "- 空欄のセルは空の <td></td> で出力する\n"
)


def build_request(
    rows_text: list[str],
    image_png: bytes | None = None,
    table_title: str = "",
    instruction: str = "",
    temperature: float = 0.1,
    model: str = "",
) -> AIRequest:
    """表→自然文段落生成用の AIRequest を構築する。

    Args:
        rows_text: 表の各行テキスト（抽出済み）。
        image_png: 表領域のPNGバイト列（任意、マルチモーダル対応モデル用）。
        table_title: 表のタイトルや番号（任意）。
        instruction: ユーザーの追加指示（任意）。
        temperature: 生成温度。
        model: 使用モデル名（空なら設定値を使う）。

    Returns:
        構築された AIRequest。
    """
    parts: list[str] = [_SYSTEM_PROMPT]

    if table_title:
        parts.append(f"表タイトル: {table_title}\n")

    if rows_text:
        parts.append("表のテキスト:\n" + "\n".join(rows_text))

    if instruction:
        parts.append(f"\n追加指示: {instruction}")

    if image_png:
        parts.append("\n（上記に加え、表の画像も添付しています）")

    prompt = "\n".join(parts)

    return AIRequest(
        prompt=prompt,
        images=[image_png] if image_png else [],
        model=model,
        temperature=temperature,
        task="table_to_paragraph",
    )


def build_html_request(
    rows_text: list[str],
    image_png: bytes | None = None,
    table_title: str = "",
    temperature: float = 0.0,
    model: str = "",
) -> AIRequest:
    """HTML テーブル形式で返す AIRequest を構築する。

    Gemini など HTML 出力が得意なモデルに表構造を再構成させ、
    `html_to_pipe_rows()` で縦パイプ形式に変換して利用する。

    Args:
        rows_text: 表の各行テキスト（抽出済み）。
        image_png: 表領域のPNGバイト列（任意）。
        table_title: 表のタイトルや番号（任意）。
        temperature: 生成温度。構造化出力のため低め (0.0) が望ましい。
        model: 使用モデル名（空なら設定値を使う）。

    Returns:
        構築された AIRequest。
    """
    parts: list[str] = [_HTML_TABLE_PROMPT]

    if table_title:
        parts.append(f"表タイトル: {table_title}\n")

    if rows_text:
        parts.append("表のテキスト:\n" + "\n".join(rows_text))

    if image_png:
        parts.append("\n（上記に加え、表の画像も添付しています）")

    return AIRequest(
        prompt="\n".join(parts),
        images=[image_png] if image_png else [],
        model=model,
        temperature=temperature,
        task="table_to_paragraph",
    )


def html_to_pipe_rows(html_text: str) -> list[tuple[str, str]]:
    """AI が返した HTML テーブルを縦パイプ形式の行リストに変換する。

    返却形式は既存の `src_text` フィールドと同じ縦パイプ形式。
    `split_markdown_row_cells()` で分割できる。

    Args:
        html_text: Gemini などが返した HTML 文字列。

    Returns:
        List of (block_tag, pipe_text) タプルのリスト。
        - block_tag: "th"（ヘッダ行）または "tr"（データ行）
        - pipe_text: "Cell A | Cell B | Cell C" 形式のテキスト
    """
    from bs4 import BeautifulSoup  # beautifulsoup4 は requirements.txt に含まれる

    soup = BeautifulSoup(html_text, "html.parser")
    rows: list[tuple[str, str]] = []

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        is_header = any(c.name == "th" for c in cells)
        block_tag = "th" if is_header else "tr"
        # セル内の複数行やスペースを1スペースに正規化してテキストを抽出
        cell_texts = [_normalize_cell_text(c.get_text(separator=" ", strip=True)) for c in cells]
        pipe_text = " | ".join(cell_texts)
        if pipe_text.strip():
            rows.append((block_tag, pipe_text))

    return rows


def html_to_plain_text(html_text: str) -> str:
    """HTML タグを除去してプレーンテキストを返す。

    自然文段落として生成された HTML レスポンスから
    テキストを取り出す際に使用する。

    Args:
        html_text: HTML 文字列。

    Returns:
        タグを除去したプレーンテキスト。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text(separator="\n", strip=True)
