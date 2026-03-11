"""表→段落タスクビルダー。

選択した表領域の画像や抽出テキストを受け取り、AIRequest を構築する。
プロバイダを意識せず、プロンプト構築と入力正規化だけを担う。

使用例::

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
"""

from __future__ import annotations

from app.services.ai.types import AIRequest

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


def build_request(
    rows_text: list[str],
    image_png: bytes | None = None,
    table_title: str = "",
    instruction: str = "",
    temperature: float = 0.1,
    model: str = "",
) -> AIRequest:
    """表→段落生成用の AIRequest を構築する。

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
