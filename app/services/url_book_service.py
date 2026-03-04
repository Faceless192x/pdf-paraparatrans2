from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from typing import List, Optional, Tuple


def parse_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


class UrlBookService:
    """URL ブック管理サービス。

    カレントURLブック状態・インポートイベント・サイトプロファイル管理、
    および URLページナビゲーション操作を提供する。
    """

    def __init__(self, config_folder: str, url_book_prefix: str) -> None:
        self.config_folder = config_folder
        self.url_book_prefix = url_book_prefix
        self._current_url_book: dict = {"name": "", "updated_at": 0}
        self._current_url_book_lock = threading.Lock()
        self._url_import_events: dict = {}
        self._url_import_events_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Current URL book state
    # ------------------------------------------------------------------

    def get_current_url_book(self) -> str:
        with self._current_url_book_lock:
            return self._current_url_book.get("name") or ""

    def set_current_url_book(self, book_name: str) -> None:
        with self._current_url_book_lock:
            self._current_url_book["name"] = book_name
            self._current_url_book["updated_at"] = int(time.time())

    # ------------------------------------------------------------------
    # Import events
    # ------------------------------------------------------------------

    def get_import_event(self, book_name: str) -> dict:
        with self._url_import_events_lock:
            return self._url_import_events.get(book_name) or {}

    def set_import_event(self, book_name: str, event: dict) -> None:
        with self._url_import_events_lock:
            self._url_import_events[book_name] = event

    # ------------------------------------------------------------------
    # Site profiles
    # ------------------------------------------------------------------

    def save_site_profiles(self, profiles: dict) -> None:
        os.makedirs(self.config_folder, exist_ok=True)
        path = os.path.join(self.config_folder, "url_site_profiles.json")
        tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    @staticmethod
    def normalize_selector_list(values) -> list:
        if not isinstance(values, list):
            return []
        out = []
        for item in values:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out

    # ------------------------------------------------------------------
    # URL page navigation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _url_page_sort_key(page_key: str):
        text = str(page_key)
        if text.isdigit():
            return (0, int(text), text)
        return (1, text)

    @classmethod
    def _sorted_url_page_keys(cls, book_data: dict) -> List[str]:
        pages = (book_data or {}).get("pages") or {}
        if not isinstance(pages, dict):
            return []
        return sorted((str(k) for k in pages.keys()), key=cls._url_page_sort_key)

    @classmethod
    def _new_url_nav_node_id(cls, existing_ids: set, page_id: str) -> str:
        base = re.sub(r"[^a-zA-Z0-9_-]", "_", str(page_id)) or "page"
        candidate = f"n_{base}"
        if candidate not in existing_ids:
            return candidate
        index = 2
        while True:
            candidate = f"n_{base}_{index}"
            if candidate not in existing_ids:
                return candidate
            index += 1

    @classmethod
    def _build_default_url_page_nav(cls, book_data: dict) -> dict:
        page_keys = cls._sorted_url_page_keys(book_data)
        nodes: dict = {}
        root_children: list = []
        existing_ids: set = set()
        for page_id in page_keys:
            node_id = cls._new_url_nav_node_id(existing_ids, page_id)
            existing_ids.add(node_id)
            nodes[node_id] = {
                "id": node_id,
                "page_id": page_id,
                "parent_id": None,
                "children": [],
                "collapsed": False,
                "manual_title": None,
            }
            root_children.append(node_id)
        selected = root_children[0] if root_children else ""
        return {
            "root_children": root_children,
            "nodes": nodes,
            "selected_node_id": selected,
            "revision": 1,
        }

    @classmethod
    def _url_nav_parent_list(cls, page_nav: dict, node_id: str) -> Tuple[Optional[list], Optional[str], int]:
        nodes = page_nav.get("nodes") or {}
        node = nodes.get(node_id)
        if not node:
            return None, None, -1

        parent_id = node.get("parent_id")
        if parent_id:
            parent = nodes.get(parent_id)
            if not parent:
                return None, None, -1
            siblings = parent.get("children")
        else:
            siblings = page_nav.get("root_children")

        if not isinstance(siblings, list):
            return None, None, -1

        try:
            index = siblings.index(node_id)
        except ValueError:
            return None, None, -1
        return siblings, parent_id, index

    @classmethod
    def ensure_url_page_nav(cls, book_data: dict) -> bool:
        if not isinstance(book_data, dict):
            return False
        if (book_data.get("source_type") or "") != "url":
            return False

        changed = False
        page_keys = cls._sorted_url_page_keys(book_data)
        page_key_set = set(page_keys)

        nav = book_data.get("page_nav")
        if not isinstance(nav, dict):
            book_data["page_nav"] = cls._build_default_url_page_nav(book_data)
            nav = book_data["page_nav"]
            changed = True

        nodes_raw = nav.get("nodes")
        root_children_raw = nav.get("root_children")
        if not isinstance(nodes_raw, dict) or not isinstance(root_children_raw, list):
            book_data["page_nav"] = cls._build_default_url_page_nav(book_data)
            nav = book_data["page_nav"]
            changed = True
            nodes_raw = nav.get("nodes")
            root_children_raw = nav.get("root_children")

        nodes: dict = {}
        page_to_node: dict = {}

        for raw_node_id, raw_node in (nodes_raw or {}).items():
            if not isinstance(raw_node, dict):
                changed = True
                continue
            node_id = str(raw_node_id or "").strip()
            page_id = str(raw_node.get("page_id") or "").strip()
            if not node_id or page_id not in page_key_set:
                changed = True
                continue
            if page_id in page_to_node:
                changed = True
                continue

            children_raw = raw_node.get("children")
            if not isinstance(children_raw, list):
                children_raw = []
                changed = True

            manual_title = raw_node.get("manual_title")
            if manual_title is not None and not isinstance(manual_title, str):
                manual_title = str(manual_title)
                changed = True

            nodes[node_id] = {
                "id": node_id,
                "page_id": page_id,
                "parent_id": None,
                "children": [str(child) for child in children_raw],
                "collapsed": bool(raw_node.get("collapsed", False)),
                "manual_title": manual_title,
            }
            page_to_node[page_id] = node_id

        if not nodes and page_keys:
            book_data["page_nav"] = cls._build_default_url_page_nav(book_data)
            changed = True
            nav = book_data["page_nav"]
            nodes = nav.get("nodes") or {}
            root_children_raw = nav.get("root_children") or []

        parent_of: dict = {}
        for node_id, node in nodes.items():
            children: list = []
            for child_id in node.get("children") or []:
                if child_id == node_id or child_id not in nodes:
                    changed = True
                    continue
                if child_id in children:
                    changed = True
                    continue
                children.append(child_id)
            node["children"] = children

        for node_id, node in nodes.items():
            dedup_children = []
            for child_id in node.get("children") or []:
                existing_parent = parent_of.get(child_id)
                if existing_parent and existing_parent != node_id:
                    changed = True
                    continue
                parent_of[child_id] = node_id
                dedup_children.append(child_id)
            node["children"] = dedup_children

        root_children: list = []
        seen_root: set = set()
        for node_id in root_children_raw or []:
            if node_id not in nodes:
                changed = True
                continue
            if node_id in parent_of:
                changed = True
                continue
            if node_id in seen_root:
                changed = True
                continue
            root_children.append(node_id)
            seen_root.add(node_id)

        for page_id in page_keys:
            node_id = page_to_node.get(page_id)
            if node_id and node_id not in parent_of and node_id not in seen_root:
                root_children.append(node_id)
                seen_root.add(node_id)

        existing_ids = set(nodes.keys())
        for page_id in page_keys:
            if page_id in page_to_node:
                continue
            node_id = cls._new_url_nav_node_id(existing_ids, page_id)
            existing_ids.add(node_id)
            nodes[node_id] = {
                "id": node_id,
                "page_id": page_id,
                "parent_id": None,
                "children": [],
                "collapsed": False,
                "manual_title": None,
            }
            page_to_node[page_id] = node_id
            root_children.append(node_id)
            changed = True

        for node_id, node in nodes.items():
            parent_id = parent_of.get(node_id)
            if node.get("parent_id") != parent_id:
                changed = True
            node["parent_id"] = parent_id

        selected_node_id = str(nav.get("selected_node_id") or "")
        if selected_node_id and selected_node_id not in nodes:
            selected_node_id = ""
            changed = True
        if not selected_node_id:
            selected_node_id = root_children[0] if root_children else ""

        revision = parse_int(nav.get("revision"), 1)
        if revision < 1:
            revision = 1
            changed = True

        normalized_nav = {
            "root_children": root_children,
            "nodes": nodes,
            "selected_node_id": selected_node_id,
            "revision": revision,
        }
        book_data["page_nav"] = normalized_nav

        page_url_map = (book_data.get("page_url_map") or {}) if isinstance(book_data.get("page_url_map"), dict) else {}
        pages = (book_data.get("pages") or {}) if isinstance(book_data.get("pages"), dict) else {}
        url_to_page_id: dict = {}
        for page_id in page_keys:
            page_url = (pages.get(page_id) or {}).get("url")
            if not page_url:
                page_url = page_url_map.get(page_id)
            if isinstance(page_url, str) and page_url.strip():
                url_to_page_id[page_url.strip()] = page_id
        if book_data.get("url_to_page_id") != url_to_page_id:
            book_data["url_to_page_id"] = url_to_page_id
            changed = True

        return changed

    @classmethod
    def move_url_page_nav_node(cls, page_nav: dict, node_id: str, op: str) -> Tuple[bool, str]:
        nodes = page_nav.get("nodes") or {}
        if node_id not in nodes:
            return False, "node_idが不正です"

        siblings, parent_id, index = cls._url_nav_parent_list(page_nav, node_id)
        if siblings is None:
            return False, "ノードの配置が不正です"

        if op == "up":
            if index <= 0:
                return False, "先頭のため上へ移動できません"
            siblings[index - 1], siblings[index] = siblings[index], siblings[index - 1]
            return True, "ok"

        if op == "down":
            if index >= len(siblings) - 1:
                return False, "末尾のため下へ移動できません"
            siblings[index], siblings[index + 1] = siblings[index + 1], siblings[index]
            return True, "ok"

        if op == "indent":
            if index <= 0:
                return False, "直前の兄弟がないため階層下へ移動できません"
            new_parent_id = siblings[index - 1]
            new_parent = nodes.get(new_parent_id)
            if not new_parent:
                return False, "移動先が不正です"
            siblings.pop(index)
            new_parent_children = new_parent.get("children")
            if not isinstance(new_parent_children, list):
                new_parent_children = []
                new_parent["children"] = new_parent_children
            new_parent_children.append(node_id)
            nodes[node_id]["parent_id"] = new_parent_id
            return True, "ok"

        if op == "outdent":
            if not parent_id:
                return False, "ルートのため階層上へ移動できません"

            parent_node = nodes.get(parent_id)
            if not parent_node:
                return False, "親ノードが不正です"

            parent_siblings, grand_parent_id, parent_index = cls._url_nav_parent_list(page_nav, parent_id)
            if parent_siblings is None:
                return False, "親ノード配置が不正です"

            siblings.pop(index)
            insert_index = parent_index + 1
            parent_siblings.insert(insert_index, node_id)
            nodes[node_id]["parent_id"] = grand_parent_id
            return True, "ok"

        return False, "opが不正です"
