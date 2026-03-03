from __future__ import annotations

import datetime
import json
import os
import re
from typing import Dict, List, Optional, Tuple


_IGNORED_DIR_NAMES = {
    "backup",
    "structure",
    "doc_structure",
    "url_books",
    "__pycache__",
    "old",
}


class FileMgmtServiceError(Exception):
    """Service-level error with an associated HTTP status code."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class FileMgmtService:
    """File and folder management service.

    Encapsulates folder CRUD, PDF listing and directory-listing helpers
    previously scattered throughout pdf-paraparatrans.py.
    """

    def __init__(
        self,
        *,
        base_folder: str,
        data_folder: str,
        url_book_prefix: str,
        url_book_json_suffix: str,
        url_books_dirname: str,
    ) -> None:
        self.base_folder = os.path.abspath(base_folder)
        self.data_folder = os.path.abspath(data_folder)
        self.url_book_prefix = url_book_prefix
        self.url_book_json_suffix = url_book_json_suffix
        self.url_books_dirname = url_books_dirname

    # ------------------------------------------------------------------
    # Internal helpers (mirrors of private functions in main module)
    # ------------------------------------------------------------------

    def should_skip_dir(self, name: str) -> bool:
        if not name:
            return True
        if name.startswith("."):
            return True
        return name in _IGNORED_DIR_NAMES

    def normalize_rel_dir(self, dir_path: str) -> str:
        if not isinstance(dir_path, str):
            raise ValueError("dir must be a string")
        normalized = dir_path.replace("\\", "/").strip("/")
        if not normalized:
            return ""
        parts = [p for p in normalized.split("/") if p]
        if any(p in (".", "..") for p in parts):
            raise ValueError("invalid dir path")
        return "/".join(parts)

    def safe_join_data(self, *parts: str) -> str:
        base = self.base_folder
        path = os.path.abspath(os.path.join(base, *[str(p) for p in parts]))
        if os.path.commonpath([base, path]) != base:
            raise ValueError("path escapes data folder")
        return path

    def sanitize_folder_name(self, name) -> str:
        if not isinstance(name, str):
            return ""
        cleaned = name.strip()
        if not cleaned:
            return ""
        if "/" in cleaned or "\\" in cleaned:
            return ""
        cleaned = re.sub(r"[\\/:*?\"<>|]", "_", cleaned)
        cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)
        cleaned = cleaned.strip().strip(".")
        if len(cleaned) > 120:
            cleaned = cleaned[:120]
        return cleaned

    def normalize_pdf_name(self, pdf_name: str) -> str:
        if not isinstance(pdf_name, str):
            return ""
        normalized = pdf_name.replace("\\", "/").strip("/")
        if not normalized:
            return ""
        parts = [p for p in normalized.split("/") if p]
        if any(p in (".", "..") for p in parts):
            return ""
        return "/".join(parts)

    def is_url_book_name(self, pdf_name: str) -> bool:
        return isinstance(pdf_name, str) and pdf_name.startswith(self.url_book_prefix)

    def sanitize_pdf_basename(self, original_filename: str) -> str:
        """Return a safe pdf_name (no extension) from an uploaded filename."""
        name = os.path.basename(original_filename or "").strip()
        if name.lower().endswith(".pdf"):
            name = name[:-4]
        name = re.sub(r"[\\/:*?\"<>|]", "_", name)
        name = re.sub(r"[\x00-\x1f]", "", name)
        name = name.strip().strip(".")
        if len(name) > 180:
            name = name[:180]
        return name

    # ------------------------------------------------------------------
    # Folder operations
    # ------------------------------------------------------------------

    def create_folder(self, dir_param: str, name) -> str:
        """Create a subfolder.  Returns the new relative path.

        Raises:
            ValueError: *dir_param* is syntactically invalid.
            FileMgmtServiceError: business rule violated (bad name, conflict…).
        """
        current_dir = self.normalize_rel_dir(dir_param)
        cleaned_name = self.sanitize_folder_name(name)
        if not cleaned_name:
            raise FileMgmtServiceError("フォルダ名が不正です", 400)
        if cleaned_name in _IGNORED_DIR_NAMES:
            raise FileMgmtServiceError("予約済みのフォルダ名は使えません", 400)

        parts = current_dir.split("/") if current_dir else []
        target_dir = self.safe_join_data(*parts, cleaned_name)
        if os.path.exists(target_dir):
            raise FileMgmtServiceError("同名のフォルダが既に存在します", 409)

        os.makedirs(target_dir, exist_ok=False)
        return "/".join(parts + [cleaned_name]) if parts else cleaned_name

    def rename_folder(self, dir_param: str, new_name) -> str:
        """Rename a folder.  Returns the new relative path."""
        current_dir = self.normalize_rel_dir(dir_param)
        if not current_dir:
            raise FileMgmtServiceError("ルートフォルダは変更できません", 400)

        cleaned_name = self.sanitize_folder_name(new_name)
        if not cleaned_name:
            raise FileMgmtServiceError("フォルダ名が不正です", 400)
        if cleaned_name in _IGNORED_DIR_NAMES:
            raise FileMgmtServiceError("予約済みのフォルダ名は使えません", 400)

        parts = current_dir.split("/")
        parent_parts = parts[:-1]
        src_dir = self.safe_join_data(*parts)
        dst_dir = self.safe_join_data(*parent_parts, cleaned_name)

        if not os.path.isdir(src_dir):
            raise FileMgmtServiceError("対象フォルダが存在しません", 404)
        if os.path.exists(dst_dir):
            raise FileMgmtServiceError("同名のフォルダが既に存在します", 409)

        os.rename(src_dir, dst_dir)
        return "/".join(parent_parts + [cleaned_name]) if parent_parts else cleaned_name

    def delete_folder(self, dir_param: str) -> str:
        """Delete an empty folder.  Returns the parent directory path."""
        current_dir = self.normalize_rel_dir(dir_param)
        if not current_dir:
            raise FileMgmtServiceError("ルートフォルダは削除できません", 400)

        parts = current_dir.split("/")
        target_dir = self.safe_join_data(*parts)

        if not os.path.isdir(target_dir):
            raise FileMgmtServiceError("対象フォルダが存在しません", 404)

        if os.listdir(target_dir):
            raise FileMgmtServiceError("空のフォルダのみ削除できます", 409)

        os.rmdir(target_dir)
        return "/".join(parts[:-1]) if len(parts) > 1 else ""

    # ------------------------------------------------------------------
    # Directory / PDF listing
    # ------------------------------------------------------------------

    def get_directory_listing(self, rel_dir: str) -> Tuple[List[dict], dict]:
        """Return *(subdirs, file_dict)* for the given relative directory."""
        file_dict: dict = {}
        subdirs: List[dict] = []
        try:
            normalized_dir = self.normalize_rel_dir(rel_dir)
        except ValueError:
            return subdirs, file_dict

        if normalized_dir:
            parts = normalized_dir.split("/")
            dir_path = self.safe_join_data(*parts)
        else:
            dir_path = self.base_folder

        if not os.path.isdir(dir_path):
            return subdirs, file_dict

        for entry in os.listdir(dir_path):
            full_path = os.path.join(dir_path, entry)
            if os.path.isdir(full_path):
                if self.should_skip_dir(entry):
                    continue
                rel_path = f"{normalized_dir}/{entry}" if normalized_dir else entry
                subdirs.append({"name": entry, "rel_path": rel_path})
                continue

            if not entry.lower().endswith(".pdf"):
                continue

            pdf_name = os.path.splitext(entry)[0]
            pdf_key = f"{normalized_dir}/{pdf_name}" if normalized_dir else pdf_name
            pdf_path = full_path
            json_path = os.path.join(dir_path, pdf_name + ".json")
            updated_date = ""
            if os.path.exists(json_path):
                updated_date = datetime.datetime.fromtimestamp(
                    os.path.getmtime(json_path)
                ).strftime("%Y/%m/%d")
            else:
                json_path = ""
                updated_date = datetime.datetime.fromtimestamp(
                    os.path.getmtime(pdf_path)
                ).strftime("%Y/%m/%d")
            file_dict[pdf_key] = {
                "json_path": json_path,
                "pdf_name": pdf_key,
                "title": pdf_name,
                "updated": updated_date,
            }

        subdirs.sort(key=lambda x: x["name"].lower())
        file_dict = dict(
            sorted(file_dict.items(), key=lambda x: x[1]["updated"], reverse=True)
        )
        return subdirs, file_dict

    def get_url_books(self) -> dict:
        """Return a dict of all URL-book entries keyed by pdf_name."""
        books: dict = {}
        seen_keys: set = set()
        base_dir = self.base_folder

        if os.path.isdir(base_dir):
            for root, subdirs, files in os.walk(base_dir):
                subdirs[:] = [d for d in subdirs if not self.should_skip_dir(d)]
                for fname in files:
                    if not fname.lower().endswith(self.url_book_json_suffix):
                        continue
                    full_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(full_path, base_dir).replace(os.sep, "/")
                    book_key = rel_path[: -len(self.url_book_json_suffix)]
                    seen_keys.add(book_key)
                    pdf_name = f"{self.url_book_prefix}{book_key}"

                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            book_data = json.load(f)
                    except Exception:
                        book_data = {}

                    updated_date = ""
                    try:
                        updated_date = datetime.datetime.fromtimestamp(
                            os.path.getmtime(full_path)
                        ).strftime("%Y/%m/%d")
                    except Exception:
                        pass

                    trans_counts = (book_data or {}).get("trans_status_counts", {}) or {}
                    books[pdf_name] = {
                        "json_path": full_path,
                        "pdf_name": pdf_name,
                        "title": (book_data or {}).get("title") or pdf_name,
                        "updated": updated_date,
                        "last_open_page": (book_data or {}).get("last_open_page"),
                        "trans_status_counts": {
                            "none": trans_counts.get("none", 0),
                            "auto": trans_counts.get("auto", 0),
                            "draft": trans_counts.get("draft", 0),
                            "fixed": trans_counts.get("fixed", 0),
                        },
                        "book_type": (book_data or {}).get("source_type") or "url",
                    }

        try:
            legacy_dir = self.safe_join_data(self.url_books_dirname)
        except Exception:
            legacy_dir = None

        if legacy_dir and os.path.isdir(legacy_dir):
            for root, _dirs, files in os.walk(legacy_dir):
                for fname in files:
                    if not fname.lower().endswith(".json"):
                        continue
                    full_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(full_path, legacy_dir)
                    book_key = rel_path[:-5].replace(os.sep, "/")
                    if book_key in seen_keys:
                        continue
                    pdf_name = f"{self.url_book_prefix}{book_key}"

                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            book_data = json.load(f)
                    except Exception:
                        book_data = {}

                    updated_date = ""
                    try:
                        updated_date = datetime.datetime.fromtimestamp(
                            os.path.getmtime(full_path)
                        ).strftime("%Y/%m/%d")
                    except Exception:
                        pass

                    trans_counts = (book_data or {}).get("trans_status_counts", {}) or {}
                    books[pdf_name] = {
                        "json_path": full_path,
                        "pdf_name": pdf_name,
                        "title": (book_data or {}).get("title") or pdf_name,
                        "updated": updated_date,
                        "last_open_page": (book_data or {}).get("last_open_page"),
                        "trans_status_counts": {
                            "none": trans_counts.get("none", 0),
                            "auto": trans_counts.get("auto", 0),
                            "draft": trans_counts.get("draft", 0),
                            "fixed": trans_counts.get("fixed", 0),
                        },
                        "book_type": (book_data or {}).get("source_type") or "url",
                    }

        books = dict(
            sorted(books.items(), key=lambda x: x[1].get("updated", ""), reverse=True)
        )
        return books

    def get_all_dirs(self) -> List[str]:
        """Return a sorted list of all relative sub-directory paths."""
        dirs: List[str] = []
        for root, subdirs, _files in os.walk(self.base_folder):
            subdirs[:] = [d for d in subdirs if not self.should_skip_dir(d)]
            rel = os.path.relpath(root, self.base_folder)
            if rel == ".":
                continue
            dirs.append(rel.replace(os.sep, "/"))
        dirs.sort(key=lambda x: x.lower())
        return dirs

    def list_pdfs(self) -> List[str]:
        """Return a sorted list of all PDF names (without .pdf extension)."""
        pdf_files: List[str] = []
        if os.path.exists(self.data_folder):
            for root, subdirs, files in os.walk(self.data_folder):
                subdirs[:] = [d for d in subdirs if not self.should_skip_dir(d)]
                for item in files:
                    if not item.lower().endswith(".pdf"):
                        continue
                    full_path = os.path.join(root, item)
                    rel_path = os.path.relpath(full_path, self.data_folder).replace(
                        os.sep, "/"
                    )
                    pdf_files.append(rel_path[:-4])
        pdf_files.sort()
        return pdf_files

    # ------------------------------------------------------------------
    # Folder-tree / breadcrumb helpers (used by the index page)
    # ------------------------------------------------------------------

    def normalize_book_dir(self, book_name: str) -> str:
        if not isinstance(book_name, str):
            return ""
        rel = book_name
        if rel.startswith(self.url_book_prefix):
            rel = rel[len(self.url_book_prefix) :]
        rel = rel.replace("\\", "/").strip("/")
        if not rel:
            return ""
        return os.path.dirname(rel).replace("\\", "/").strip("/")

    def accumulate_folder_counts(self, book_names: List[str]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for name in book_names:
            current = self.normalize_book_dir(name)
            while True:
                counts[current] = counts.get(current, 0) + 1
                if not current:
                    break
                current = os.path.dirname(current).replace("\\", "/").strip("/")
        return counts

    def build_folder_tree(
        self, all_dirs: List[str], counts: Dict[str, int], current_dir: Optional[str]
    ) -> dict:
        root = {
            "name": "/ (ルート)",
            "path": "",
            "children": [],
            "count": counts.get("", 0),
            "open": True,
            "active": not current_dir,
        }
        nodes: Dict[str, dict] = {"": root}

        for dir_path in sorted(all_dirs, key=lambda x: (x.count("/"), x.lower())):
            parts = dir_path.split("/")
            acc: List[str] = []
            for part in parts:
                acc.append(part)
                key = "/".join(acc)
                if key in nodes:
                    continue
                parent_key = "/".join(acc[:-1])
                parent_node = nodes.get(parent_key, root)
                node: dict = {
                    "name": part,
                    "path": key,
                    "children": [],
                    "count": counts.get(key, 0),
                    "open": False,
                    "active": False,
                }
                parent_node["children"].append(node)
                nodes[key] = node

        for key, node in nodes.items():
            if key == "":
                continue
            node["count"] = counts.get(key, 0)
            if current_dir and (
                current_dir == key or current_dir.startswith(f"{key}/")
            ):
                node["open"] = True
            node["active"] = bool(current_dir) and current_dir == key

        return root

    def build_breadcrumbs(self, current_dir: str) -> List[dict]:
        crumbs: List[dict] = [{"name": "data", "path": ""}]
        if not current_dir:
            return crumbs
        parts = current_dir.split("/")
        acc: List[str] = []
        for part in parts:
            acc.append(part)
            crumbs.append({"name": part, "path": "/".join(acc)})
        return crumbs
