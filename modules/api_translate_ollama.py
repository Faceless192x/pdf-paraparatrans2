import os
import json
import re
import time
import requests
from difflib import SequenceMatcher
from typing import Optional
from dotenv import load_dotenv

"""Ollama ローカル LLM 翻訳エンジン。

API キー不要でローカル LLM を使って翻訳する。
Ollama の REST API (http://localhost:11434) を利用。

.env 例:
  TRANSLATOR=ollama
  OLLAMA_MODEL=gemma3:12b        # 使用するモデル名（デフォルト: gemma3:12b）
  OLLAMA_BASE_URL=http://localhost:11434  # Ollama サーバーの URL（デフォルト: localhost）

前提:
  - Ollama がインストール・起動されていること
  - 翻訳に使うモデルが pull 済みであること（例: ollama pull gemma3:12b）
"""

load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:12b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

_PERF_BOOT_AT = time.perf_counter()
_PERF_STATE = {
    "calls": 0,
    "success": 0,
    "errors": 0,
    "elapsed_sum_ms": 0.0,
    "elapsed_max_ms": 0.0,
    "first_call_elapsed_ms": None,
    "first_request_since_boot_ms": None,
    "first_response_since_boot_ms": None,
    "first_success_since_boot_ms": None,
    "request_count": 0,
}

# 言語コード → 言語名のマッピング
_LANG_NAMES = {
    "EN": "English",
    "JA": "Japanese",
    "ZH": "Chinese",
    "KO": "Korean",
    "FR": "French",
    "DE": "German",
    "ES": "Spanish",
    "PT": "Portuguese",
    "IT": "Italian",
    "RU": "Russian",
    "AR": "Arabic",
    "NL": "Dutch",
    "PL": "Polish",
    "SV": "Swedish",
    "DA": "Danish",
    "FI": "Finnish",
    "NO": "Norwegian",
}


def _since_boot_ms() -> float:
    return round((time.perf_counter() - _PERF_BOOT_AT) * 1000, 1)


def _ns_to_ms(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return round(float(value) / 1_000_000, 1)
    except Exception:
        return None


def _perf_log(event: str, **fields) -> None:
    payload = {
        "event": event,
        "model": OLLAMA_MODEL,
        "since_boot_ms": _since_boot_ms(),
    }
    payload.update(fields)
    try:
        print("[OLLAMA_PERF] " + json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def _record_call_perf(elapsed_ms: float, success: bool) -> int:
    state = _PERF_STATE
    state["calls"] += 1
    call_index = int(state["calls"])
    if success:
        state["success"] += 1
        if state["first_success_since_boot_ms"] is None:
            state["first_success_since_boot_ms"] = _since_boot_ms()
    else:
        state["errors"] += 1

    state["elapsed_sum_ms"] += float(elapsed_ms)
    state["elapsed_max_ms"] = max(float(state["elapsed_max_ms"]), float(elapsed_ms))
    if state["first_call_elapsed_ms"] is None:
        state["first_call_elapsed_ms"] = float(elapsed_ms)

    should_log_summary = call_index <= 3 or (call_index % 20 == 0) or elapsed_ms >= 30000
    if should_log_summary:
        avg_ms = state["elapsed_sum_ms"] / max(1, call_index)
        _perf_log(
            "summary",
            calls=call_index,
            success=int(state["success"]),
            errors=int(state["errors"]),
            avg_elapsed_ms=round(avg_ms, 1),
            max_elapsed_ms=round(float(state["elapsed_max_ms"]), 1),
            first_call_elapsed_ms=round(float(state["first_call_elapsed_ms"] or 0.0), 1),
            first_request_since_boot_ms=state["first_request_since_boot_ms"],
            first_response_since_boot_ms=state["first_response_since_boot_ms"],
            first_success_since_boot_ms=state["first_success_since_boot_ms"],
        )

    return call_index


def _lang_name(code: str) -> str:
    """言語コードを言語名に変換する。"""
    return _LANG_NAMES.get(code.upper(), code)


def _build_prompt(text: str, source: str, target: str) -> str:
    """翻訳プロンプトを生成する。"""
    src_name = _lang_name(source)
    tgt_name = _lang_name(target)
    return (
        "You are a translation engine.\n"
        f"Translate the following {src_name} text to {tgt_name}.\n"
        "Rules:\n"
        "1) Translate ALL natural language sentences.\n"
        "2) Preserve HTML tags exactly.\n"
        "3) Preserve markers such as 【1_23】 exactly as-is.\n"
        "4) Keep numbers, IDs, URLs, and code-like tokens unchanged.\n"
        "5) Output ONLY translated text. No explanation, no notes.\n"
        "6) Do NOT return the source text unchanged unless it is already in the target language.\n\n"
        f"{text}"
    )


def _build_strict_retry_prompt(text: str, source: str, target: str) -> str:
    """未翻訳判定時の再試行用プロンプト。"""
    src_name = _lang_name(source)
    tgt_name = _lang_name(target)
    return (
        "STRICT TRANSLATION MODE\n"
        f"Translate from {src_name} to {tgt_name}.\n"
        "MANDATORY:\n"
        "- Translate every sentence that is not already in the target language.\n"
        "- Keep HTML tags unchanged.\n"
        "- Keep markers like 【1_1】 unchanged.\n"
        "- Return translated text only.\n\n"
        f"{text}"
    )


_EN_RE = re.compile(r"[A-Za-z]")
_JA_RE = re.compile(r"[ぁ-んァ-ン一-龥]")
_MARKER_RE = re.compile(r"【\s*[0-9]+[＿_][0-9]+\s*】")


def _normalize_for_similarity(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").strip().lower()
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _looks_untranslated(source_text: str, translated_text: str, source: str, target: str) -> bool:
    src = str(source_text or "").strip()
    out = str(translated_text or "").strip()
    if not src:
        return False
    if not out:
        return True
    if str(source or "").upper() == str(target or "").upper():
        return False

    if src == out:
        return True

    src_norm = _normalize_for_similarity(src)
    out_norm = _normalize_for_similarity(out)
    if not src_norm or not out_norm:
        return False

    sim = SequenceMatcher(None, src_norm, out_norm).ratio()
    src_en = len(_EN_RE.findall(src))
    out_ja = len(_JA_RE.findall(out))

    source_upper = str(source or "").upper()
    target_upper = str(target or "").upper()
    if source_upper == "EN" and target_upper == "JA":
        if src_en >= 8 and out_ja == 0 and sim >= 0.85:
            return True

    if src_en >= 8 and sim >= 0.97:
        return True

    return False


def _call_ollama(prompt: str, temperature: float = 0.1) -> str:
    """Ollama API を呼び出してレスポンスを取得する。"""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    request_started = time.perf_counter()
    prompt_len = len(str(prompt or ""))
    state = _PERF_STATE
    if state["first_request_since_boot_ms"] is None:
        state["first_request_since_boot_ms"] = _since_boot_ms()
        _perf_log(
            "first_request_start",
            base_url=OLLAMA_BASE_URL,
            prompt_len=prompt_len,
            temperature=temperature,
        )

    state["request_count"] += 1
    request_index = int(state["request_count"])
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
        },
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=120,
        )
    except requests.exceptions.ConnectionError:
        request_elapsed_ms = round((time.perf_counter() - request_started) * 1000, 1)
        _perf_log(
            "request_error",
            request_index=request_index,
            error="connection",
            elapsed_ms=request_elapsed_ms,
            prompt_len=prompt_len,
            temperature=temperature,
        )
        raise RuntimeError(
            f"Ollama サーバーに接続できません ({OLLAMA_BASE_URL})。\n"
            "Ollama が起動していることを確認してください。\n"
            "  - インストール: https://ollama.com\n"
            f"  - モデル取得: ollama pull {OLLAMA_MODEL}\n"
            "  - 起動確認: ollama list"
        )
    except requests.exceptions.Timeout:
        request_elapsed_ms = round((time.perf_counter() - request_started) * 1000, 1)
        _perf_log(
            "request_error",
            request_index=request_index,
            error="timeout",
            elapsed_ms=request_elapsed_ms,
            prompt_len=prompt_len,
            temperature=temperature,
        )
        raise RuntimeError(
            "Ollama サーバーからの応答がタイムアウトしました。\n"
            "モデルの初回ロードには時間がかかることがあります。再度お試しください。"
        )

    if resp.status_code != 200:
        request_elapsed_ms = round((time.perf_counter() - request_started) * 1000, 1)
        _perf_log(
            "request_error",
            request_index=request_index,
            error=f"status_{resp.status_code}",
            elapsed_ms=request_elapsed_ms,
            prompt_len=prompt_len,
            temperature=temperature,
        )
        raise RuntimeError(f"Ollama API error: {resp.status_code} {resp.text}")

    data = resp.json()
    response_text = data.get("response", "").strip()
    request_elapsed_ms = round((time.perf_counter() - request_started) * 1000, 1)
    load_ms = _ns_to_ms(data.get("load_duration"))
    prompt_eval_ms = _ns_to_ms(data.get("prompt_eval_duration"))
    eval_ms = _ns_to_ms(data.get("eval_duration"))
    total_ms = _ns_to_ms(data.get("total_duration"))
    prompt_eval_count = data.get("prompt_eval_count")
    eval_count = data.get("eval_count")

    if state["first_response_since_boot_ms"] is None:
        state["first_response_since_boot_ms"] = _since_boot_ms()
        _perf_log(
            "first_response",
            request_index=request_index,
            elapsed_ms=request_elapsed_ms,
            prompt_len=prompt_len,
            response_len=len(response_text),
            temperature=temperature,
            ollama_total_ms=total_ms,
            ollama_load_ms=load_ms,
            ollama_prompt_eval_ms=prompt_eval_ms,
            ollama_eval_ms=eval_ms,
            ollama_prompt_eval_count=prompt_eval_count,
            ollama_eval_count=eval_count,
        )
    elif request_index <= 3 or request_elapsed_ms >= 30000:
        _perf_log(
            "request_ok",
            request_index=request_index,
            elapsed_ms=request_elapsed_ms,
            prompt_len=prompt_len,
            response_len=len(response_text),
            temperature=temperature,
            ollama_total_ms=total_ms,
            ollama_load_ms=load_ms,
            ollama_prompt_eval_ms=prompt_eval_ms,
            ollama_eval_ms=eval_ms,
            ollama_prompt_eval_count=prompt_eval_count,
            ollama_eval_count=eval_count,
        )

    return response_text


def _debug_log_translation(source: str, target: str, before_text: str, after_text: Optional[str] = None, error: Optional[Exception] = None) -> None:
    print("[OLLAMA_DEBUG] --- translation start ---")
    print(f"[OLLAMA_DEBUG] model={OLLAMA_MODEL} source={source} target={target}")
    print(f"[OLLAMA_DEBUG] before(len={len(before_text or '')})")
    print(before_text)
    if error is not None:
        print(f"[OLLAMA_DEBUG] error={error}")
    else:
        print(f"[OLLAMA_DEBUG] after(len={len(after_text or '')})")
        print(after_text)
    print("[OLLAMA_DEBUG] --- translation end ---")


def _translate_segment_strict(text: str, source: str, target: str) -> str:
    """単一セグメントを厳格プロンプトで翻訳（失敗時は原文）。"""
    if not text or not text.strip():
        return text
    strict_prompt = _build_strict_retry_prompt(text, source, target)
    try:
        candidate = _call_ollama(strict_prompt, temperature=0.0)
    except Exception as e:
        print(f"[OLLAMA_DEBUG] strict segment translate failed: {e}")
        return text

    if _looks_untranslated(text, candidate, source, target):
        return text
    return candidate


def _translate_marker_blocks(text: str, source: str, target: str) -> str:
    """【id】ブロックを段落単位で翻訳し、マーカーを維持して再構築する。"""
    matches = list(_MARKER_RE.finditer(text or ""))
    if not matches:
        return text

    pieces = []
    head = text[: matches[0].start()]
    if head:
        pieces.append(head)

    for i, marker_match in enumerate(matches):
        marker = marker_match.group(0)
        body_start = marker_match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]

        leading_ws_len = len(body) - len(body.lstrip())
        trailing_ws_len = len(body) - len(body.rstrip())
        leading_ws = body[:leading_ws_len] if leading_ws_len > 0 else ""
        trailing_ws = body[len(body) - trailing_ws_len :] if trailing_ws_len > 0 else ""
        core = body.strip()

        translated_core = _translate_segment_strict(core, source, target) if core else core
        rebuilt_body = f"{leading_ws}{translated_core}{trailing_ws}"

        pieces.append(marker)
        pieces.append(rebuilt_body)

    rebuilt = "".join(pieces)
    return rebuilt if rebuilt.strip() else text


def translate_text(text: str, source: str = "EN", target: str = "JA") -> str:
    """Ollama を使って単一テキストを翻訳する。"""
    if not text or not text.strip():
        return text

    call_started = time.perf_counter()
    initial_untranslated = False
    strict_retry_used = False
    marker_fallback_used = False

    prompt = _build_prompt(text, source, target)
    try:
        translated = _call_ollama(prompt, temperature=0.1)
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - call_started) * 1000, 1)
        call_index = _record_call_perf(elapsed_ms, success=False)
        _perf_log(
            "translate_call_error",
            call_index=call_index,
            elapsed_ms=elapsed_ms,
            input_len=len(str(text or "")),
            source=str(source),
            target=str(target),
            strict_retry_used=strict_retry_used,
            marker_fallback_used=marker_fallback_used,
            error=str(e),
        )
        _debug_log_translation(source, target, text, error=e)
        raise

    if _looks_untranslated(text, translated, source, target):
        initial_untranslated = True
        print("[OLLAMA_DEBUG] output looks untranslated. retry with strict prompt.")
        strict_retry_used = True
        strict_prompt = _build_strict_retry_prompt(text, source, target)
        try:
            strict_retry = _call_ollama(strict_prompt, temperature=0.0)
            if not _looks_untranslated(text, strict_retry, source, target):
                translated = strict_retry
            else:
                print("[OLLAMA_DEBUG] strict retry also looks untranslated.")
        except Exception as retry_error:
            print(f"[OLLAMA_DEBUG] strict retry failed: {retry_error}")

    if _looks_untranslated(text, translated, source, target) and _MARKER_RE.search(text):
        print("[OLLAMA_DEBUG] fallback to marker-wise translation.")
        marker_fallback_used = True
        marker_translated = _translate_marker_blocks(text, source, target)
        if not _looks_untranslated(text, marker_translated, source, target):
            translated = marker_translated

    final_untranslated = _looks_untranslated(text, translated, source, target)
    elapsed_ms = round((time.perf_counter() - call_started) * 1000, 1)
    call_index = _record_call_perf(elapsed_ms, success=True)
    _perf_log(
        "translate_call",
        call_index=call_index,
        elapsed_ms=elapsed_ms,
        input_len=len(str(text or "")),
        output_len=len(str(translated or "")),
        source=str(source),
        target=str(target),
        initial_untranslated=bool(initial_untranslated),
        final_untranslated=bool(final_untranslated),
        strict_retry_used=bool(strict_retry_used),
        marker_fallback_used=bool(marker_fallback_used),
    )

    _debug_log_translation(source, target, text, after_text=translated)
    return translated


def translate_texts(texts: list[str], source: str = "EN", target: str = "JA") -> list[str]:
    """Ollama を使って複数テキストを一括翻訳する。"""
    if not texts:
        return []

    results = []
    for text in texts:
        if not text or not str(text).strip():
            results.append(text)
        else:
            result = translate_text(str(text), source, target)
            results.append(result)
    return results


if __name__ == "__main__":
    html_text = "ollama:<p>Hello <strong>ParaParaTrans</strong>!</p>"
    translated_text = translate_text(html_text)
    print(translated_text)
