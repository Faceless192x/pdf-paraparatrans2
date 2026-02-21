from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from app.repositories.dict_repo import (
    DEFAULT_DICT_HEADER,
    ensure_dict_file,
    load_dict,
    save_dict,
)
from app.repositories.settings_repo import load_settings, save_settings


@dataclass
class DictService:
    app_dir: str
    data_folder: str
    config_folder: str
    dict_path: str
    get_paths: Callable[[str], Tuple[str, str]]
    should_skip_dir: Callable[[str], bool]

    def _settings_path(self) -> str:
        return os.path.join(self.data_folder, "paraparatrans.settings.json")

    def _normalize_rel_path(self, path: str) -> str:
        if not isinstance(path, str):
            return ""
        normalized = path.replace("\\", "/").strip("/")
        if not normalized:
            return ""
        parts = [p for p in normalized.split("/") if p]
        if any(p in (".", "..") for p in parts):
            return ""
        return "/".join(parts)

    def _relpath_from_abs(self, path: str) -> str:
        rel = os.path.relpath(path, self.app_dir)
        return rel.replace("\\", "/")

    def _resolve_rel_path(self, rel_path: str) -> str:
        normalized = self._normalize_rel_path(rel_path)
        if not normalized:
            raise ValueError("invalid path")
        abs_path = os.path.abspath(os.path.join(self.app_dir, normalized))
        if os.path.commonpath([self.app_dir, abs_path]) != self.app_dir:
            raise ValueError("path escapes app dir")
        return abs_path

    def _get_book_dict_paths(self, pdf_name: str) -> Tuple[str, str]:
        pdf_path, _ = self.get_paths(pdf_name)
        book_dict_path = os.path.splitext(pdf_path)[0] + ".dict.txt"
        return book_dict_path, self._relpath_from_abs(book_dict_path)

    def _list_config_dicts(self) -> List[Dict[str, str]]:
        dicts: List[Dict[str, str]] = []
        try:
            entries = os.listdir(self.config_folder)
        except OSError:
            return dicts

        for name in entries:
            lower = name.lower()
            if lower in ("symbolfont_dict.txt", "symbolfonts.txt"):
                continue
            if not (lower == "dict.txt" or lower.endswith(".dict.txt")):
                continue
            abs_path = os.path.join(self.config_folder, name)
            if not os.path.isfile(abs_path):
                continue
            rel_path = self._relpath_from_abs(abs_path)
            dicts.append({"path": rel_path, "label": name})

        dicts.sort(key=lambda d: d["label"].lower())
        return dicts

    def _list_book_dicts(self) -> List[Dict[str, str]]:
        dicts: List[Dict[str, str]] = []
        for root, dirs, files in os.walk(self.data_folder):
            dirs[:] = [d for d in dirs if not self.should_skip_dir(d)]
            for name in files:
                if not name.lower().endswith(".dict.txt"):
                    continue
                abs_path = os.path.join(root, name)
                if not os.path.isfile(abs_path):
                    continue
                rel_path = self._relpath_from_abs(abs_path)
                dicts.append({"path": rel_path, "label": rel_path})
        dicts.sort(key=lambda d: d["label"].lower())
        return dicts

    def _default_dict_selection(self) -> List[str]:
        if os.path.exists(self.dict_path):
            return [self._relpath_from_abs(self.dict_path)]
        return []

    def _load_dict_selection(self, pdf_name: str) -> List[str]:
        settings = load_settings(self._settings_path())
        entry = settings.get("files", {}).get(pdf_name, {})
        selected = entry.get("dict_paths")
        if not isinstance(selected, list):
            return self._default_dict_selection()
        normalized = []
        seen = set()
        for item in selected:
            norm = self._normalize_rel_path(str(item))
            if not norm or norm in seen:
                continue
            normalized.append(norm)
            seen.add(norm)
        return normalized or self._default_dict_selection()

    def _save_dict_selection(self, pdf_name: str, dict_paths: List[str]) -> None:
        settings_path = self._settings_path()
        settings = load_settings(settings_path)
        files = settings.setdefault("files", {})
        entry = files.get(pdf_name)
        if not isinstance(entry, dict):
            entry = {}
            files[pdf_name] = entry
        entry["dict_paths"] = dict_paths
        save_settings(settings_path, settings, indent=4)

    def ensure_dict_file(self, path: str) -> None:
        ensure_dict_file(path, header=DEFAULT_DICT_HEADER)

    def merged_dict_file(self, dict_paths: List[str]) -> str:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.config_folder, suffix=".dict.txt", text=True)
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as out:
            out.write(DEFAULT_DICT_HEADER)
            for path in dict_paths:
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip() or line.lstrip().startswith("#"):
                            continue
                        out.write(line)
        return tmp_path

    def _find_dict_entry(self, dict_data: List[List], word: str) -> Optional[List]:
        if not word:
            return None
        for entry in dict_data:
            if entry[2] == 0 and entry[0] == word:
                return entry
        for entry in dict_data:
            if entry[2] == 1 and entry[0].lower() == word.lower():
                return entry
        for entry in dict_data:
            if entry[2] not in [0, 1] and entry[0].lower() == word.lower():
                return entry
        return None

    def get_active_dict_paths(self, pdf_name: str) -> List[str]:
        selected_rel = self._load_dict_selection(pdf_name)
        abs_paths: List[str] = []
        for rel in selected_rel:
            try:
                abs_paths.append(self._resolve_rel_path(rel))
            except ValueError:
                continue
        if not abs_paths:
            abs_paths = [self.dict_path]
        return abs_paths

    def get_primary_dict_path(self, pdf_name: str) -> str:
        selected = self.get_active_dict_paths(pdf_name)
        return selected[-1] if selected else self.dict_path

    def list_entries(self, dict_path: Optional[str]) -> Tuple[List[Dict[str, object]], str]:
        if dict_path:
            dict_path = self._resolve_rel_path(dict_path)
        else:
            dict_path = self.dict_path

        dict_data = load_dict(dict_path)
        entries = []
        for entry in dict_data:
            count = entry[3] if len(entry) > 3 else 0
            entries.append(
                {
                    "original_word": entry[0],
                    "translated_word": entry[1],
                    "status": entry[2],
                    "count": count,
                }
            )
        return entries, self._relpath_from_abs(dict_path)

    def bulk_update(self, entries: List[Dict[str, object]], dict_path: Optional[str]) -> int:
        if dict_path:
            dict_path = self._resolve_rel_path(dict_path)
        else:
            dict_path = self.dict_path

        new_data = []
        for idx, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise ValueError(f"{idx} 行目の形式が不正です")
            original_word = str(entry.get("original_word") or "").strip()
            if not original_word:
                raise ValueError(f"{idx} 行目の原語が空です")
            translated_word = str(entry.get("translated_word") or "").strip()
            try:
                status = int(entry.get("status", 0))
            except (TypeError, ValueError):
                raise ValueError(f"{idx} 行目の状態が不正です")
            try:
                count = int(entry.get("count", 0))
            except (TypeError, ValueError):
                count = 0
            if count < 0:
                count = 0
            new_data.append([original_word, translated_word, status, count])

        os.makedirs(os.path.dirname(dict_path), exist_ok=True)
        save_dict(dict_path, new_data)
        return len(new_data)

    def catalog(self) -> Tuple[List[Dict[str, str]], str]:
        config_dicts = self._list_config_dicts()
        book_dicts = self._list_book_dicts()
        config_set = {d["path"] for d in config_dicts}
        all_dicts = config_dicts + [d for d in book_dicts if d["path"] not in config_set]
        if os.path.exists(self.dict_path):
            default_path = self._relpath_from_abs(self.dict_path)
        else:
            default_path = all_dicts[0]["path"] if all_dicts else ""
        return all_dicts, default_path

    def compare(self, dict_path: str) -> Tuple[Dict[str, Dict[str, object]], str]:
        dict_abs = self._resolve_rel_path(dict_path)
        dict_data = load_dict(dict_abs)
        entries: Dict[str, Dict[str, object]] = {}
        for entry in dict_data:
            key = entry[0]
            status = entry[2]
            entries[key] = {
                "translated_word": entry[1],
                "status": status,
            }
        return entries, self._relpath_from_abs(dict_abs)

    def auto_translate_selected(
        self,
        dict_path: Optional[str],
        entries: List[Dict[str, object]],
        translate_entries_fn: Callable[[List[Dict[str, object]]], List[Dict[str, object]]],
    ) -> Tuple[str, int]:
        if dict_path:
            dict_abs = self._resolve_rel_path(dict_path)
        else:
            dict_abs = self.dict_path

        self.ensure_dict_file(dict_abs)
        if not isinstance(entries, list) or not entries:
            raise ValueError("entries が空です")

        translated_entries = translate_entries_fn(entries)
        if not translated_entries:
            raise ValueError("翻訳対象の entries がありません")

        dict_data = load_dict(dict_abs)
        dict_map = {item[0]: item for item in dict_data}

        for entry in translated_entries:
            key = str(entry.get("original_word") or "").strip()
            if not key:
                continue
            translated_word = str(entry.get("translated_word") or "")
            try:
                status = int(entry.get("status", 8))
            except (TypeError, ValueError):
                status = 8
            count = 0
            if key in dict_map and len(dict_map[key]) > 3:
                count = dict_map[key][3]
            else:
                try:
                    count = int(entry.get("count", 0))
                except (TypeError, ValueError):
                    count = 0

            dict_map[key] = [key, translated_word, status, max(0, count)]

        save_dict(dict_abs, list(dict_map.values()))
        return self._relpath_from_abs(dict_abs), len(translated_entries)

    def create_book_dict(
        self,
        pdf_name: str,
        json_path: str,
        common_words_path: str,
        dict_create_fn: Callable[[str, str, str], None],
    ) -> str:
        book_abs, book_rel = self._get_book_dict_paths(pdf_name)
        self.ensure_dict_file(book_abs)
        dict_create_fn(json_path, book_abs, common_words_path)
        return book_rel

    def transfer(
        self,
        action: str,
        source_path: str,
        target_path: str,
        entries: List[Dict[str, object]],
    ) -> None:
        if action not in {"move", "copy", "delete"}:
            raise ValueError("action が不正です")
        if not isinstance(entries, list) or not entries:
            raise ValueError("entries が空です")

        source_abs = self._resolve_rel_path(source_path) if source_path else self.dict_path

        target_abs = None
        if action in {"move", "copy"}:
            target_abs = self._resolve_rel_path(target_path) if target_path else None
            if not target_abs:
                raise ValueError("target_path が必要です")

        self.ensure_dict_file(source_abs)
        source_data = load_dict(source_abs)
        target_data = load_dict(target_abs) if target_abs else []

        source_map = {entry[0]: entry for entry in source_data}
        target_map = {entry[0]: entry for entry in target_data}

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("original_word") or "").strip()
            if not key:
                continue
            value = str(entry.get("translated_word") or "")
            try:
                status = int(entry.get("status", 0))
            except (TypeError, ValueError):
                status = 0
            try:
                count = int(entry.get("count", 0))
            except (TypeError, ValueError):
                count = 0

            if action in {"move", "copy"} and target_abs:
                target_map[key] = [key, value, status, count]
            if action in {"move", "delete"}:
                source_map.pop(key, None)

        save_dict(source_abs, list(source_map.values()))
        if target_abs:
            save_dict(target_abs, list(target_map.values()))

    def selection_get(self, pdf_name: str) -> Tuple[List[Dict[str, str]], Dict[str, object], List[str]]:
        config_dicts = self._list_config_dicts()
        book_abs, book_rel = self._get_book_dict_paths(pdf_name)
        selected = self._load_dict_selection(pdf_name)
        return (
            config_dicts,
            {
                "path": book_rel,
                "label": os.path.basename(book_rel),
                "exists": os.path.exists(book_abs),
            },
            selected,
        )

    def selection_save(self, pdf_name: str, dict_paths: List[str]) -> List[str]:
        config_dicts = self._list_config_dicts()
        book_abs, book_rel = self._get_book_dict_paths(pdf_name)
        allowed = {d["path"].lower(): d["path"] for d in config_dicts}
        allowed[book_rel.lower()] = book_rel

        selected = []
        seen = set()
        for item in dict_paths:
            norm = self._normalize_rel_path(str(item))
            if not norm:
                continue
            key = norm.lower()
            if key not in allowed or key in seen:
                continue
            selected.append(allowed[key])
            seen.add(key)

        if not selected:
            selected = self._default_dict_selection()

        if book_rel.lower() in {p.lower() for p in selected}:
            self.ensure_dict_file(book_abs)

        self._save_dict_selection(pdf_name, selected)
        return selected

    def search(self, word: str, pdf_name: Optional[str]) -> Optional[List]:
        dict_paths = self.get_active_dict_paths(pdf_name) if pdf_name else [self.dict_path]
        for path in reversed(dict_paths):
            dict_data = load_dict(path)
            found_entry = self._find_dict_entry(dict_data, word)
            if found_entry:
                return found_entry
        return None

    def update(
        self,
        original_word: str,
        translated_word: str,
        status: int,
        pdf_name: Optional[str],
        dict_path: Optional[str] = None,
    ) -> bool:
        if dict_path:
            if not pdf_name:
                raise ValueError("pdf_name が必要です")
            normalized = self._normalize_rel_path(dict_path)
            if not normalized:
                raise ValueError("dict_path が不正です")
            active_abs = self.get_active_dict_paths(pdf_name)
            active_map = {self._relpath_from_abs(path).lower(): path for path in active_abs}
            target_path = active_map.get(normalized.lower())
            if not target_path:
                raise ValueError("dict_path が適用辞書に含まれていません")
        else:
            dict_paths = self.get_active_dict_paths(pdf_name) if pdf_name else [self.dict_path]
            target_path = None
            for path in reversed(dict_paths):
                if self._find_dict_entry(load_dict(path), original_word):
                    target_path = path
                    break
            if target_path is None:
                target_path = dict_paths[-1] if dict_paths else self.dict_path

        self.ensure_dict_file(target_path)
        dict_data = load_dict(target_path)
        found_index = -1

        for i, entry in enumerate(dict_data):
            if entry[2] == 0 and entry[0] == original_word:
                found_index = i
                break
        if found_index == -1:
            for i, entry in enumerate(dict_data):
                if entry[2] == 1 and entry[0].lower() == original_word.lower():
                    found_index = i
                    break
        if found_index == -1:
            for i, entry in enumerate(dict_data):
                if entry[2] not in [0, 1] and entry[0].lower() == original_word.lower():
                    found_index = i
                    break

        if found_index != -1:
            dict_data[found_index][1] = translated_word
            dict_data[found_index][2] = status
        else:
            dict_data.append([original_word, translated_word, status, 0])

        save_dict(target_path, dict_data)
        return True
