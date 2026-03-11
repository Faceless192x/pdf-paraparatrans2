"""AI統合レイヤー。

基本的な使い方::

    from app.services.ai import generate
    from app.services.ai.types import AIRequest

    req = AIRequest(prompt="こんにちは、世界！")
    resp = generate(req)
    print(resp.text)

表→段落生成::

    from app.services.ai.tasks.table_to_paragraph import build_request
    from app.services.ai import generate

    req = build_request(rows_text=["A 12.5", "B 10.1"], table_title="Table 1")
    resp = generate(req)
"""

from app.services.ai.router import generate
from app.services.ai.types import AIRequest, AIResponse

__all__ = ["generate", "AIRequest", "AIResponse"]
