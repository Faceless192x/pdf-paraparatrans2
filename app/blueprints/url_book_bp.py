from __future__ import annotations

import json
import os
import time
import uuid
from typing import Callable, Tuple

from flask import Blueprint, current_app, jsonify, request

from app.services.url_book_service import UrlBookService, parse_int
from modules.parapara_url2json import (
    build_url_book_data,
    crawl_site,
    ensure_url_page_in_book,
    ensure_url_page_in_book_from_html,
    fetch_html,
    get_site_profile,
    load_site_profiles,
    normalize_host,
    normalize_url,
    save_url_book,
)


def create_url_book_blueprint(
    url_book_service: UrlBookService,
    get_paths: Callable[[str], Tuple[str, str]],
    normalize_pdf_name: Callable[[str], str],
    is_url_book_name: Callable[[str], bool],
    sanitize_folder_name: Callable[[str], str],
    corsify_response: Callable,
    config_folder: str,
    url_book_prefix: str,
) -> Blueprint:
    """URL ブック API の Blueprint を生成して返す。

    依存オブジェクトはファクトリ引数で受け取り、クロージャ経由でルートハンドラに渡す。
    """

    bp = Blueprint("url_book", __name__)

    # ------------------------------------------------------------------
    # /api/url_book/create
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/create", methods=["POST"])
    def create_url_book_api():
        payload = request.get_json(silent=True) or {}
        raw_url = (payload.get("url") or "").strip()
        normalized = normalize_url(raw_url)
        if not normalized:
            return jsonify({"status": "error", "message": "URLが不正です"}), 400

        host = normalize_host(normalized)
        if not host:
            return jsonify({"status": "error", "message": "URLのホスト名が不正です"}), 400

        book_name = (payload.get("book_name") or "").strip()
        if book_name:
            book_name = normalize_pdf_name(book_name)
            if not book_name:
                return jsonify({"status": "error", "message": "book_nameが不正です"}), 400
            if not book_name.startswith(url_book_prefix):
                book_name = f"{url_book_prefix}{book_name}"
        else:
            slug = sanitize_folder_name(host.replace(":", "_")) or host.replace(":", "_")
            book_name = f"{url_book_prefix}{slug}"

        _, json_path = get_paths(book_name)
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    book_data = json.load(f)
                url_book_service.ensure_url_page_nav(book_data)
            except Exception:
                book_data = {}
            return jsonify({
                "status": "ok",
                "book_name": book_name,
                "exists": True,
                "title": (book_data or {}).get("title"),
                "page_count": (book_data or {}).get("page_count"),
                "page_nav": (book_data or {}).get("page_nav") or {},
            })

        profiles = load_site_profiles(config_folder)
        profile = get_site_profile(profiles, host)
        title = (payload.get("title") or "").strip() or None

        try:
            book_data = build_url_book_data(normalized, title=title, site_profile=profile)
            url_book_service.ensure_url_page_nav(book_data)
            save_url_book(json_path, book_data)
        except Exception as e:
            current_app.logger.exception("URL book create failed")
            return jsonify({"status": "error", "message": f"URL取得に失敗しました: {str(e)}"}), 500

        return jsonify({
            "status": "ok",
            "book_name": book_name,
            "exists": False,
            "title": book_data.get("title"),
            "page_count": book_data.get("page_count"),
            "page_nav": book_data.get("page_nav") or {},
        })

    # ------------------------------------------------------------------
    # /api/url_book/navigate
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/navigate", methods=["POST"])
    def navigate_url_book_api():
        payload = request.get_json(silent=True) or {}
        book_name = normalize_pdf_name(payload.get("book_name") or "")
        if not book_name or not is_url_book_name(book_name):
            return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

        raw_url = (payload.get("url") or "").strip()
        normalized = normalize_url(raw_url)
        if not normalized:
            return jsonify({"status": "error", "message": "URLが不正です"}), 400

        _, json_path = get_paths(book_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "URLブックが存在しません"}), 404

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
        except Exception as e:
            return jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"}), 500

        root_host = (book_data or {}).get("source_host") or normalize_host((book_data or {}).get("source_root_url") or "")
        target_host = normalize_host(normalized)
        if root_host and target_host and root_host != target_host:
            return jsonify({"status": "error", "message": "別ドメインのURLはこのブックに追加できません"}), 400

        profiles = load_site_profiles(config_folder)
        profile = get_site_profile(profiles, root_host)

        try:
            page_number, page_data, added = ensure_url_page_in_book(book_data, normalized, site_profile=profile)
            nav_changed = url_book_service.ensure_url_page_nav(book_data)
            if added or nav_changed:
                save_url_book(json_path, book_data)
        except Exception as e:
            current_app.logger.exception("URL book navigate failed")
            return jsonify({"status": "error", "message": f"URL取得に失敗しました: {str(e)}"}), 500

        return jsonify({
            "status": "ok",
            "page_number": page_number,
            "page": page_data,
            "page_count": book_data.get("page_count"),
            "trans_status_counts": book_data.get("trans_status_counts"),
            "title": book_data.get("title"),
            "page_url_map": book_data.get("page_url_map") or {},
            "url_to_page_id": book_data.get("url_to_page_id") or {},
            "page_nav": book_data.get("page_nav") or {},
        })

    # ------------------------------------------------------------------
    # /api/url_book/import_html
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/import_html", methods=["POST", "OPTIONS"])
    def import_url_book_html_api():
        if request.method == "OPTIONS":
            resp = current_app.make_response("")
            resp.status_code = 204
            return corsify_response(resp)

        payload = request.get_json(silent=True) or {}
        book_name = normalize_pdf_name(payload.get("book_name") or "")
        if not book_name:
            book_name = url_book_service.get_current_url_book()
        if not book_name or not is_url_book_name(book_name):
            resp = jsonify({"status": "error", "message": "book_nameが不正です"})
            resp.status_code = 400
            return corsify_response(resp)

        raw_url = (payload.get("url") or "").strip()
        normalized = normalize_url(raw_url)
        if not normalized:
            resp = jsonify({"status": "error", "message": "URLが不正です"})
            resp.status_code = 400
            return corsify_response(resp)

        html_text = payload.get("html") or ""
        force = bool(payload.get("force", False))

        _, json_path = get_paths(book_name)
        if not os.path.exists(json_path):
            resp = jsonify({"status": "error", "message": "URLブックが存在しません"})
            resp.status_code = 404
            return corsify_response(resp)

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
        except Exception as e:
            resp = jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"})
            resp.status_code = 500
            return corsify_response(resp)

        root_host = (book_data or {}).get("source_host") or normalize_host((book_data or {}).get("source_root_url") or "")
        target_host = normalize_host(normalized)
        if root_host and target_host and root_host != target_host:
            resp = jsonify({"status": "error", "message": "別ドメインのURLはこのブックに追加できません"})
            resp.status_code = 400
            return corsify_response(resp)

        profiles = load_site_profiles(config_folder)
        profile = get_site_profile(profiles, root_host)

        try:
            page_number, page_data, added, updated = ensure_url_page_in_book_from_html(
                book_data,
                normalized,
                html_text,
                site_profile=profile,
                force=force,
            )
            nav_changed = url_book_service.ensure_url_page_nav(book_data)
            if added or updated or nav_changed:
                save_url_book(json_path, book_data)
        except Exception as e:
            current_app.logger.exception("URL book import_html failed")
            resp = jsonify({"status": "error", "message": f"HTML取り込みに失敗しました: {str(e)}"})
            resp.status_code = 500
            return corsify_response(resp)

        exists = (not added and not updated)
        event = {
            "id": uuid.uuid4().hex,
            "book_name": book_name,
            "kind": "import",
            "page_number": page_number,
            "page_count": book_data.get("page_count"),
            "url": normalized,
            "added": bool(added),
            "updated": bool(updated),
            "exists": bool(exists),
            "created_at": int(time.time()),
        }
        url_book_service.set_import_event(book_name, event)

        resp = jsonify({
            "status": "ok",
            "page_number": page_number,
            "page": page_data,
            "page_count": book_data.get("page_count"),
            "trans_status_counts": book_data.get("trans_status_counts"),
            "title": book_data.get("title"),
            "page_url_map": book_data.get("page_url_map") or {},
            "url_to_page_id": book_data.get("url_to_page_id") or {},
            "page_nav": book_data.get("page_nav") or {},
            "added": bool(added),
            "updated": bool(updated),
            "exists": bool(exists),
        })
        return corsify_response(resp)

    # ------------------------------------------------------------------
    # /api/url_book/import_url
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/import_url", methods=["POST"])
    def import_url_book_url_api():
        payload = request.get_json(silent=True) or {}
        book_name = normalize_pdf_name(payload.get("book_name") or "")
        if not book_name:
            book_name = url_book_service.get_current_url_book()
        if not book_name or not is_url_book_name(book_name):
            return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

        raw_url = (payload.get("url") or "").strip()
        normalized = normalize_url(raw_url)
        if not normalized:
            return jsonify({"status": "error", "message": "URLが不正です"}), 400

        force = bool(payload.get("force", True))

        _, json_path = get_paths(book_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "URLブックが存在しません"}), 404

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
        except Exception as e:
            return jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"}), 500

        root_host = (book_data or {}).get("source_host") or normalize_host((book_data or {}).get("source_root_url") or "")
        target_host = normalize_host(normalized)
        if root_host and target_host and root_host != target_host:
            return jsonify({"status": "error", "message": "別ドメインのURLはこのブックに追加できません"}), 400

        profiles = load_site_profiles(config_folder)
        profile = get_site_profile(profiles, root_host)

        try:
            html_text = fetch_html(normalized)
            page_number, page_data, added, updated = ensure_url_page_in_book_from_html(
                book_data,
                normalized,
                html_text,
                site_profile=profile,
                force=force,
            )
            nav_changed = url_book_service.ensure_url_page_nav(book_data)
            if added or updated or nav_changed:
                save_url_book(json_path, book_data)
        except Exception as e:
            current_app.logger.exception("URL book import_url failed")
            return jsonify({"status": "error", "message": f"URL取込に失敗しました: {str(e)}"}), 500

        exists = (not added and not updated)
        event = {
            "id": uuid.uuid4().hex,
            "book_name": book_name,
            "kind": "import",
            "page_number": page_number,
            "page_count": book_data.get("page_count"),
            "url": normalized,
            "added": bool(added),
            "updated": bool(updated),
            "exists": bool(exists),
            "created_at": int(time.time()),
        }
        url_book_service.set_import_event(book_name, event)

        return jsonify({
            "status": "ok",
            "page_number": page_number,
            "page": page_data,
            "page_count": book_data.get("page_count"),
            "trans_status_counts": book_data.get("trans_status_counts"),
            "title": book_data.get("title"),
            "page_url_map": book_data.get("page_url_map") or {},
            "url_to_page_id": book_data.get("url_to_page_id") or {},
            "page_nav": book_data.get("page_nav") or {},
            "added": bool(added),
            "updated": bool(updated),
            "exists": bool(exists),
        }), 200

    # ------------------------------------------------------------------
    # /api/url_book/import_event/<book_name>
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/import_event/<path:book_name>", methods=["GET"])
    def url_book_import_event_api(book_name: str):
        normalized = normalize_pdf_name(book_name or "")
        if not normalized or not is_url_book_name(normalized):
            return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

        event = url_book_service.get_import_event(normalized)
        if not event:
            return jsonify({"status": "ok", "event": None}), 200

        return jsonify({"status": "ok", "event": event}), 200

    # ------------------------------------------------------------------
    # /api/url_book/site_rules/<book_name>
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/site_rules/<path:book_name>", methods=["GET", "POST"])
    def url_book_site_rules_api(book_name: str):
        normalized = normalize_pdf_name(book_name or "")
        if not normalized or not is_url_book_name(normalized):
            return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

        _, json_path = get_paths(normalized)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "URLブックが存在しません"}), 404

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
        except Exception as e:
            return jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"}), 500

        host = (book_data or {}).get("source_host") or normalize_host((book_data or {}).get("source_root_url") or "")
        if not host:
            return jsonify({"status": "error", "message": "hostが不正です"}), 400

        profiles = load_site_profiles(config_folder)
        profile = get_site_profile(profiles, host) or {}

        if request.method == "GET":
            return jsonify({
                "status": "ok",
                "host": host,
                "site_rules": {
                    "include_selectors": profile.get("include_selectors") or [],
                    "add_selectors": profile.get("add_selectors") or [],
                    "exclude_selectors": profile.get("exclude_selectors") or [],
                },
            }), 200

        payload = request.get_json(silent=True) or {}
        include_selectors = url_book_service.normalize_selector_list(payload.get("include_selectors"))
        add_selectors = url_book_service.normalize_selector_list(payload.get("add_selectors"))
        exclude_selectors = url_book_service.normalize_selector_list(payload.get("exclude_selectors"))

        profiles[host] = {
            "include_selectors": include_selectors,
            "add_selectors": add_selectors,
            "exclude_selectors": exclude_selectors,
        }
        try:
            url_book_service.save_site_profiles(profiles)
        except Exception as e:
            return jsonify({"status": "error", "message": f"ルールの保存に失敗しました: {str(e)}"}), 500

        rule_event = {
            "id": uuid.uuid4().hex,
            "book_name": normalized,
            "kind": "rule_update",
            "created_at": int(time.time()),
        }
        url_book_service.set_import_event(normalized, rule_event)

        return jsonify({
            "status": "ok",
            "host": host,
            "site_rules": profiles[host],
        }), 200

    # ------------------------------------------------------------------
    # /api/url_book/current
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/current", methods=["GET", "POST", "OPTIONS"])
    def current_url_book_api():
        if request.method == "OPTIONS":
            resp = current_app.make_response("")
            resp.status_code = 204
            return corsify_response(resp)

        if request.method == "GET":
            resp = jsonify({"status": "ok", "book_name": url_book_service.get_current_url_book()})
            return corsify_response(resp)

        payload = request.get_json(silent=True) or {}
        book_name = normalize_pdf_name(payload.get("book_name") or "")
        if not book_name or not is_url_book_name(book_name):
            resp = jsonify({"status": "error", "message": "book_nameが不正です"})
            resp.status_code = 400
            return corsify_response(resp)

        url_book_service.set_current_url_book(book_name)
        resp = jsonify({"status": "ok", "book_name": book_name})
        return corsify_response(resp)

    # ------------------------------------------------------------------
    # /api/url_book/page_nav/<book_name>
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/page_nav/<path:book_name>", methods=["GET", "PUT"])
    def url_book_page_nav_api(book_name: str):
        normalized = normalize_pdf_name(book_name or "")
        if not normalized or not is_url_book_name(normalized):
            return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

        _, json_path = get_paths(normalized)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "URLブックが存在しません"}), 404

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
        except Exception as e:
            return jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"}), 500

        if request.method == "GET":
            changed = url_book_service.ensure_url_page_nav(book_data)
            if changed:
                save_url_book(json_path, book_data)
            return jsonify({
                "status": "ok",
                "page_nav": book_data.get("page_nav") or {},
                "revision": parse_int((book_data.get("page_nav") or {}).get("revision"), 1),
            }), 200

        payload = request.get_json(silent=True) or {}
        expected_revision = parse_int(payload.get("revision"), 0)
        changed = url_book_service.ensure_url_page_nav(book_data)
        current_revision = parse_int((book_data.get("page_nav") or {}).get("revision"), 1)
        if changed:
            save_url_book(json_path, book_data)

        if expected_revision != current_revision:
            return jsonify({
                "status": "error",
                "message": "ページリストが更新されています。再読み込みしてください",
                "revision": current_revision,
                "page_nav": book_data.get("page_nav") or {},
            }), 409

        incoming = payload.get("page_nav")
        if not isinstance(incoming, dict):
            return jsonify({"status": "error", "message": "page_navが不正です"}), 400

        book_data["page_nav"] = incoming
        url_book_service.ensure_url_page_nav(book_data)
        next_revision = current_revision + 1
        book_data["page_nav"]["revision"] = next_revision
        save_url_book(json_path, book_data)

        return jsonify({
            "status": "ok",
            "page_nav": book_data.get("page_nav") or {},
            "revision": next_revision,
        }), 200

    # ------------------------------------------------------------------
    # /api/url_book/page_nav/move
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/page_nav/move", methods=["POST"])
    def move_url_book_page_nav_api():
        payload = request.get_json(silent=True) or {}
        book_name = normalize_pdf_name(payload.get("book_name") or "")
        if not book_name or not is_url_book_name(book_name):
            return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

        node_id = str(payload.get("node_id") or "").strip()
        op = str(payload.get("op") or "").strip().lower()
        expected_revision = parse_int(payload.get("revision"), 0)
        if not node_id:
            return jsonify({"status": "error", "message": "node_idが不正です"}), 400

        _, json_path = get_paths(book_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "URLブックが存在しません"}), 404

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
        except Exception as e:
            return jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"}), 500

        changed = url_book_service.ensure_url_page_nav(book_data)
        page_nav = book_data.get("page_nav") or {}
        current_revision = parse_int(page_nav.get("revision"), 1)
        if changed:
            save_url_book(json_path, book_data)

        if expected_revision != current_revision:
            return jsonify({
                "status": "error",
                "message": "ページリストが更新されています。再読み込みしてください",
                "revision": current_revision,
                "page_nav": page_nav,
            }), 409

        ok, message = url_book_service.move_url_page_nav_node(page_nav, node_id, op)
        if not ok:
            return jsonify({
                "status": "error",
                "message": message,
                "revision": current_revision,
                "page_nav": page_nav,
            }), 400

        page_nav["selected_node_id"] = node_id
        page_nav["revision"] = current_revision + 1
        save_url_book(json_path, book_data)

        return jsonify({
            "status": "ok",
            "page_nav": page_nav,
            "revision": page_nav.get("revision"),
        }), 200

    # ------------------------------------------------------------------
    # /api/url_book/page_nav/rebuild
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/page_nav/rebuild", methods=["POST"])
    def rebuild_url_book_page_nav_api():
        payload = request.get_json(silent=True) or {}
        book_name = normalize_pdf_name(payload.get("book_name") or "")
        if not book_name or not is_url_book_name(book_name):
            return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

        _, json_path = get_paths(book_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "URLブックが存在しません"}), 404

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
        except Exception as e:
            return jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"}), 500

        before_revision = parse_int((book_data.get("page_nav") or {}).get("revision"), 1)
        changed = url_book_service.ensure_url_page_nav(book_data)

        page_nav = (book_data.get("page_nav") or {}) if isinstance(book_data.get("page_nav"), dict) else {}
        if changed:
            page_nav["revision"] = max(1, before_revision) + 1
            book_data["page_nav"] = page_nav
            save_url_book(json_path, book_data)

        return jsonify({
            "status": "ok",
            "page_nav": page_nav,
            "revision": page_nav.get("revision"),
        }), 200

    # ------------------------------------------------------------------
    # /api/url_book/crawl
    # ------------------------------------------------------------------

    @bp.route("/api/url_book/crawl", methods=["POST"])
    def crawl_url_book_api():
        payload = request.get_json(silent=True) or {}
        book_name = normalize_pdf_name(payload.get("book_name") or "")
        if not book_name or not is_url_book_name(book_name):
            return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

        _, json_path = get_paths(book_name)
        if not os.path.exists(json_path):
            return jsonify({"status": "error", "message": "URLブックが存在しません"}), 404

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
        except Exception as e:
            return jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"}), 500

        root_url = (book_data or {}).get("source_root_url")
        if not root_url:
            return jsonify({"status": "error", "message": "source_root_urlが不正です"}), 400

        root_host = (book_data or {}).get("source_host") or normalize_host(root_url)
        profiles = load_site_profiles(config_folder)
        profile = get_site_profile(profiles, root_host)

        path_prefix = payload.get("path_prefix") or None
        max_pages = int(payload.get("max_pages") or 100)
        if max_pages < 1:
            max_pages = 100
        if max_pages > 500:
            max_pages = 500

        try:
            discovered = crawl_site(
                root_url,
                path_prefix=path_prefix,
                max_pages=max_pages,
                respect_robots=True,
                site_profile=profile,
                delay_sec=0.5,
            )
        except Exception as e:
            current_app.logger.exception("URL book crawl failed")
            return jsonify({"status": "error", "message": f"クロール失敗: {str(e)}"}), 500

        added_count = 0
        for url in discovered:
            try:
                _, _, added = ensure_url_page_in_book(book_data, url, site_profile=profile)
                if added:
                    added_count += 1
            except Exception as e:
                current_app.logger.warning(f"Failed to add URL {url}: {e}")
                continue

        nav_changed = url_book_service.ensure_url_page_nav(book_data)
        if added_count > 0 or nav_changed:
            save_url_book(json_path, book_data)

        return jsonify({
            "status": "ok",
            "discovered": len(discovered),
            "added": added_count,
            "page_count": book_data.get("page_count"),
            "trans_status_counts": book_data.get("trans_status_counts"),
            "page_nav": book_data.get("page_nav") or {},
        })

    return bp
