import os
from dotenv import load_dotenv

# .env ファイルの内容を読み込む
load_dotenv()
TRANSLATOR = os.getenv("TRANSLATOR", "google").lower()

if TRANSLATOR == "deepl":
    try:
        # パッケージ(import modules.api_translate)として読み込まれるケース
        from .api_translate_deepl import translate_text as translate_text_env  # type: ignore
    except Exception:
        # スクリプト/モジュール直下(import api_translate)として読み込まれるケース
        from api_translate_deepl import translate_text as translate_text_env  # type: ignore
    print("Using DeepL translator.")
elif TRANSLATOR == "google_v3":
    try:
        from .api_translate_google_v3 import translate_text as translate_text_env  # type: ignore
    except Exception:
        from api_translate_google_v3 import translate_text as translate_text_env  # type: ignore
    print("Using Google v3 translator.")
else:
    try:
        from .api_translate_google import translate_text as translate_text_env  # type: ignore
    except Exception:
        from api_translate_google import translate_text as translate_text_env  # type: ignore
    print("Using Google translator.")

def translate_text(text, source="EN", target="JA"):
    print(f"translate_text")
    """
    環境変数に基づいて翻訳サービスを選択し、テキストを翻訳する。
    """
    return translate_text_env(text, source, target)

if __name__ == "__main__":
    html_text = "<p>Hello <strong>ParaParaTrans</strong>!</p>"
    translated_text, status_code = translate_text(html_text)
    print(translated_text)
