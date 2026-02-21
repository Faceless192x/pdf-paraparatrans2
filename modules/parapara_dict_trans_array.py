#!/usr/bin/env python3
import re
from typing import Iterable

try:
    from .api_translate import translate_texts  # type: ignore
except Exception:
    from api_translate import translate_texts  # type: ignore


def is_katakana(text: str) -> bool:
    if not str(text or "").strip():
        return False
    return re.fullmatch(r"[ァ-ンー\s　]+", str(text)) is not None


def _chunked(values: list[dict], chunk_size: int) -> Iterable[list[dict]]:
    for idx in range(0, len(values), chunk_size):
        yield values[idx:idx + chunk_size]


def translate_dict_entries(entries: list[dict], source: str = "EN", target: str = "JA", chunk_size: int = 50) -> list[dict]:
    if not isinstance(entries, list):
        raise ValueError("entries must be a list")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    normalized: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        original_word = str(entry.get("original_word") or "").strip()
        if not original_word:
            continue
        translated_word = str(entry.get("translated_word") or "")
        normalized.append(
            {
                "original_word": original_word,
                "translated_word": translated_word,
                "status": entry.get("status", 0),
                "count": entry.get("count", 0),
            }
        )

    if not normalized:
        return []

    translated_entries: list[dict] = []
    for batch in _chunked(normalized, chunk_size):
        src_words = [item["original_word"] for item in batch]
        translated_words = translate_texts(src_words, source=source, target=target)
        if len(translated_words) != len(batch):
            raise RuntimeError("翻訳結果の件数が入力件数と一致しません")

        for item, translated in zip(batch, translated_words):
            translated_value = str(translated or "")
            if translated_value == item["translated_word"]:
                new_status = 7
            elif is_katakana(translated_value):
                new_status = 6
            else:
                new_status = 8

            translated_entries.append(
                {
                    "original_word": item["original_word"],
                    "translated_word": translated_value,
                    "status": new_status,
                    "count": item["count"],
                }
            )

    return translated_entries
