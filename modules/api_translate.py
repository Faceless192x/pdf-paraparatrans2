import os
from dotenv import load_dotenv


_CONNECTION_EXCEPTION_CLASS_NAMES = {
    "ConnectionError",
    "ConnectTimeout",
    "ReadTimeout",
    "Timeout",
    "NewConnectionError",
    "MaxRetryError",
    "ConnectionException",
    "DeepLConnectionException",
    "ServerDisconnectedError",
    "ClientConnectorError",
    "EndpointConnectionError",
}

_CONNECTION_ERROR_KEYWORDS = (
    "connection refused",
    "failed to establish a new connection",
    "failed to connect",
    "network is unreachable",
    "name or service not known",
    "temporary failure in name resolution",
    "could not resolve host",
    "server disconnected",
    "connection reset",
    "read timed out",
    "connect timeout",
    "timed out",
    "i/o timeout",
    "service unavailable",
    "サーバーに接続できません",
    "接続できません",
    "接続に失敗",
    "タイムアウト",
    "名前解決",
    "通信エラー",
)


class TranslationServerConnectionError(RuntimeError):
    """翻訳サーバーへの接続失敗を表す例外。"""


def _iter_exception_chain(exc):
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _looks_like_connection_message(message):
    normalized = str(message or "").strip().lower()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in _CONNECTION_ERROR_KEYWORDS)


def _is_connection_related_error(exc):
    if isinstance(exc, TranslationServerConnectionError):
        return True

    for current in _iter_exception_chain(exc):
        if current.__class__.__name__ in _CONNECTION_EXCEPTION_CLASS_NAMES:
            return True
        if _looks_like_connection_message(str(current)):
            return True
    return False


def _build_connection_error_message(translator_name, original_error):
    label = _label_for_translator(translator_name)
    detail = str(original_error or "").strip()
    message = f"{label} の翻訳サーバーに接続できないため、翻訳を中止しました。"
    if detail:
        message += f"\n{detail}"
    return message

# .env ファイルの内容を読み込む
load_dotenv()
_SUPPORTED_TRANSLATORS = ("google", "deepl", "google_v3", "ollama")
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

    if translator_name == "ollama":
        try:
            from .api_translate_ollama import translate_text as translate_text_env  # type: ignore
        except Exception:
            from api_translate_ollama import translate_text as translate_text_env  # type: ignore
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
    if name == "ollama":
        return "Ollama"
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
    try:
        return translator_func(text, source, target)
    except Exception as e:
        if _is_connection_related_error(e):
            raise TranslationServerConnectionError(_build_connection_error_message(selected, e)) from e
        raise


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

    if translator_name == "ollama":
        try:
            from .api_translate_ollama import translate_texts as translate_texts_env  # type: ignore
        except Exception:
            from api_translate_ollama import translate_texts as translate_texts_env  # type: ignore
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
    try:
        return translate_texts_func(texts, source, target)
    except Exception as e:
        if _is_connection_related_error(e):
            raise TranslationServerConnectionError(_build_connection_error_message(selected, e)) from e
        raise

if __name__ == "__main__":
    html_text = "<p>Hello <strong>ParaParaTrans</strong>!</p>"
    translated_text, status_code = translate_text(html_text)
    print(translated_text)
