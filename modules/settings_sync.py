import json
import os
import uuid
from typing import Any, Dict, Tuple


_TRANS_STATUS_KEYS = ("none", "auto", "draft", "fixed")


def _normalize_trans_status_counts(counts: Any) -> Dict[str, int]:
    if not isinstance(counts, dict):
        counts = {}

    normalized: Dict[str, int] = {}
    for k in _TRANS_STATUS_KEYS:
        v = counts.get(k, 0)
        try:
            normalized[k] = int(v)
        except Exception:
            normalized[k] = 0
    return normalized


def _atomic_write_json(path: str, data: Dict[str, Any], *, indent: int = 4) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def load_settings(settings_path: str) -> Dict[str, Any]:
    if not os.path.exists(settings_path):
        return {"files": {}}
    with open(settings_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"files": {}}
    if not isinstance(data.get("files"), dict):
        data["files"] = {}
    return data


def save_settings(settings_path: str, settings: Dict[str, Any], *, indent: int = 4) -> None:
    if not isinstance(settings, dict):
        settings = {"files": {}}
    if not isinstance(settings.get("files"), dict):
        settings["files"] = {}
    _atomic_write_json(settings_path, settings, indent=indent)


def extract_book_info_from_json(json_path: str) -> Dict[str, Any]:
    with open(json_path, "r", encoding="utf-8") as f:
        book_data = json.load(f)

    if not isinstance(book_data, dict):
        return {}

    info: Dict[str, Any] = {
        "version": book_data.get("version", ""),
        "src_filename": book_data.get("src_filename", ""),
        "title": book_data.get("title", ""),
        "page_count": book_data.get("page_count", 0),
        "trans_status_counts": _normalize_trans_status_counts(book_data.get("trans_status_counts")),
    }
    return info


def sync_one_pdf_settings_from_json(
    *,
    settings_path: str,
    base_folder: str,
    pdf_name: str,
    indent: int = 4,
) -> bool:
    """指定PDFの <pdf>.json を読み、settingsの該当エントリを更新して保存する。"""

    json_path = os.path.join(base_folder, f"{pdf_name}.json")
    if not os.path.exists(json_path):
        return False

    settings = load_settings(settings_path)
    files = settings.setdefault("files", {})
    file_entry = files.get(pdf_name)
    if not isinstance(file_entry, dict):
        file_entry = {}
        files[pdf_name] = file_entry

    book_info = extract_book_info_from_json(json_path)
    json_mtime = os.path.getmtime(json_path)

    changed = False
    for k, v in book_info.items():
        if file_entry.get(k) != v:
            file_entry[k] = v
            changed = True

    # mtimeは浮動小数点のまま保持（Windowsでも比較に使える）
    if file_entry.get("json_mtime") != json_mtime:
        file_entry["json_mtime"] = json_mtime
        changed = True

    if changed:
        _atomic_write_json(settings_path, settings, indent=indent)

    return changed


def lazy_sync_settings_from_json_files(
    *,
    settings: Dict[str, Any],
    base_folder: str,
) -> Tuple[bool, int]:
    """settings内の各PDFについて、jsonが新しければ trans_status_counts 等を settings に反映する。

    返り値: (changed, updated_pdf_count)
    - changed: settingsを書き戻す必要があるか
    - updated_pdf_count: 同期したPDF数
    """

    files = settings.get("files")
    if not isinstance(files, dict):
        return False, 0

    changed = False
    updated = 0

    for pdf_name, entry in list(files.items()):
        if not isinstance(entry, dict):
            entry = {}
            files[pdf_name] = entry
            changed = True

        json_path = os.path.join(base_folder, f"{pdf_name}.json")
        if not os.path.exists(json_path):
            continue

        try:
            json_mtime = os.path.getmtime(json_path)
        except Exception:
            continue

        prev_mtime = entry.get("json_mtime")
        try:
            prev_mtime_f = float(prev_mtime) if prev_mtime is not None else 0.0
        except Exception:
            prev_mtime_f = 0.0

        if json_mtime <= prev_mtime_f:
            continue

        book_info = extract_book_info_from_json(json_path)
        for k, v in book_info.items():
            if entry.get(k) != v:
                entry[k] = v
                changed = True

        entry["json_mtime"] = json_mtime
        changed = True
        updated += 1

    return changed, updated
