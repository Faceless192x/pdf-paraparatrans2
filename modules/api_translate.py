import os
from dotenv import load_dotenv

# .env ファイルの内容を読み込む
load_dotenv()
_SUPPORTED_TRANSLATORS = ("google", "deepl", "google_v3")
_TRANSLATOR_FUNCS = {}
_CURRENT_TRANSLATOR = "google"


def _normalize_translator(name):
    value = str(name or "").strip().lower()
    if not value:
        value = "google"
    if value not in _SUPPORTED_TRANSLATORS:
        raise ValueError(f"Unsupported translator: {value}")
    return value


def _load_translator_func(translator_name):
    if translator_name == "deepl":
        try:
            from .api_translate_deepl import translate_text as translate_text_env  # type: ignore
        except Exception:
            from api_translate_deepl import translate_text as translate_text_env  # type: ignore
        return translate_text_env

    if translator_name == "google_v3":
        try:
            from .api_translate_google_v3 import translate_text as translate_text_env  # type: ignore
        except Exception:
            from api_translate_google_v3 import translate_text as translate_text_env  # type: ignore
        return translate_text_env

    try:
        from .api_translate_google import translate_text as translate_text_env  # type: ignore
    except Exception:
        from api_translate_google import translate_text as translate_text_env  # type: ignore
    return translate_text_env


def _resolve_translator_func(translator_name):
    if translator_name in _TRANSLATOR_FUNCS:
        return _TRANSLATOR_FUNCS[translator_name]
    fn = _load_translator_func(translator_name)
    _TRANSLATOR_FUNCS[translator_name] = fn
    return fn


def get_supported_translators():
    return list(_SUPPORTED_TRANSLATORS)


def get_current_translator():
    return _CURRENT_TRANSLATOR


def set_current_translator(translator_name):
    global _CURRENT_TRANSLATOR
    normalized = _normalize_translator(translator_name)
    _resolve_translator_func(normalized)
    _CURRENT_TRANSLATOR = normalized
    os.environ["TRANSLATOR"] = normalized
    return _CURRENT_TRANSLATOR


def _label_for_translator(name):
    if name == "deepl":
        return "DeepL"
    if name == "google_v3":
        return "Google v3"
    return "Google"


try:
    _initial = _normalize_translator(os.getenv("TRANSLATOR", "google"))
    set_current_translator(_initial)
except Exception as e:
    print(f"Translator initialization failed ({e}). fallback to Google.")
    set_current_translator("google")

print(f"Using {_label_for_translator(get_current_translator())} translator.")


def translate_text(text, source="EN", target="JA", translator=None):
    print(f"translate_text")
    """
    環境変数に基づいて翻訳サービスを選択し、テキストを翻訳する。
    """
    selected = get_current_translator() if translator is None else _normalize_translator(translator)
    translator_func = _resolve_translator_func(selected)
    return translator_func(text, source, target)


def _resolve_translate_texts_func(translator_name):
    if translator_name == "deepl":
        try:
            from .api_translate_deepl import translate_texts as translate_texts_env  # type: ignore
        except Exception:
            from api_translate_deepl import translate_texts as translate_texts_env  # type: ignore
        return translate_texts_env

    if translator_name == "google_v3":
        try:
            from .api_translate_google_v3 import translate_texts as translate_texts_env  # type: ignore
        except Exception:
            from api_translate_google_v3 import translate_texts as translate_texts_env  # type: ignore
        return translate_texts_env

    try:
        from .api_translate_google import translate_texts as translate_texts_env  # type: ignore
    except Exception:
        from api_translate_google import translate_texts as translate_texts_env  # type: ignore
    return translate_texts_env


def translate_texts(texts, source="EN", target="JA", translator=None):
    selected = get_current_translator() if translator is None else _normalize_translator(translator)
    if not isinstance(texts, list):
        raise ValueError("texts must be a list")
    if not texts:
        return []

    translate_texts_func = _resolve_translate_texts_func(selected)
    return translate_texts_func(texts, source, target)

if __name__ == "__main__":
    html_text = "<p>Hello <strong>ParaParaTrans</strong>!</p>"
    translated_text, status_code = translate_text(html_text)
    print(translated_text)
