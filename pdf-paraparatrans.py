from flask import Flask, request, render_template, redirect, url_for, send_from_directory, jsonify, send_file
import os
import json
import datetime
import io
import sys
import threading
import shutil
import time
import gzip
import fitz
# /api/book_toc 用の簡易キャッシュ（JSONのmtimeが変わらない限り再計算しない）
from PyPDF2 import PdfReader, PdfWriter
import uuid  # ファイル名の一意性を確保するために追加
import tempfile
import re
from urllib.parse import urlsplit
from werkzeug.exceptions import RequestEntityTooLarge

# modulesディレクトリをPythonのモジュール検索パスに追加
sys.path.append(os.path.join(os.path.dirname(__file__), 'modules'))

from dotenv import load_dotenv

# .envが存在しない場合に .env.example から作成
ENV_PATH = ".env"
ENV_EXAMPLE_PATH = ".env.example"
if not os.path.exists(ENV_PATH):
    if os.path.exists(ENV_EXAMPLE_PATH):
        print(f".env が存在しません。{ENV_EXAMPLE_PATH} から作成します: {ENV_PATH}")
        shutil.copyfile(ENV_EXAMPLE_PATH, ENV_PATH)
    else:
        print(f"Warning: {ENV_PATH} も {ENV_EXAMPLE_PATH} も存在しません。環境変数が未設定の可能性があります。")

load_dotenv(ENV_PATH)

# ログ設定
import logging
from modules.stream_logger import init_logging 
from modules.sse_endpoint import create_log_stream_endpoint
# ログ初期化（ログファイル＋SSEキューへの出力）
init_logging("pdf-paraparatrans.log")
# Flaskの静的ファイルアクセスログを抑制
# ログレベルはenvファイルの設定に従う。未指定の場合はWARNING
log_level = os.getenv("LOG_LEVEL", "WARNING").upper()
if log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
    raise ValueError(f"Invalid LOG_LEVEL: {log_level}")
logging.getLogger('werkzeug').setLevel(log_level)

# PDFからパラグラフJSON生成(header/footerは自動判定でセット)
from modules.parapara_pdf2json import extract_paragraphs, reextract_page
# block_tagをセット
from modules.parapara_tagging_by_structure import structure_tagging
# 先頭小文字にjoinをセット
from modules.parapara_join_flags import join_flags_in_file
# 対訳辞書に単語を抽出
from modules.parapara_dict_create import dict_create
# 対訳辞書の単語を翻訳
from modules.parapara_dict_trans import dict_trans
from modules.parapara_dict_trans_array import translate_dict_entries
# 対訳辞書で置換
from modules.parapara_dict_replacer import (
    atomicsave_json,
    file_replace_with_dict,
    load_dictionary,
    load_json,
    replace_with_dict,
)

# joinフラグに従って src_joined/src_replaced を再構築（UIトグル対応）
from modules.parapara_join_incremental import (
    apply_all as join_apply_all,
    apply_join_change as join_apply_change,
    build_index as join_build_index,
    iter_paragraph_refs as join_iter_paragraph_refs,
)

from modules.parapara_symbolfont_rebuild import rebuild_src_text_in_file
from modules.parapara_table_reextract import (
    append_markdown_table_rows_from_selection,
    suggest_table_shape_for_selection,
)

from modules.api_translate import (
    set_current_translator,
)
from modules.parapara_trans import recalc_trans_status_counts
from modules.parapara_init import parapara_init  # parapara_initをインポート
# スタイルによるblock_tag一括更新
from modules.parapara_tagging_by_style import tag_paragraphs_by_style # 追加
# スタイル + Y範囲による header/footer タグ付け
from modules.parapara_tagging_by_style_y import tag_paragraphs_by_style_y_in_file
from modules.settings_sync import (
    load_settings,
    lazy_sync_settings_from_json_files,
    save_settings,
)
from modules.parapara_search import search_paragraphs_in_book
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
from app.services.dict_service import DictService
from app.services.chunked_upload_service import ChunkedUploadService, ChunkedUploadServiceError
from app.services.symbolfont_service import SymbolFontService
from app.services.file_mgmt_service import FileMgmtService
from app.services.url_book_service import UrlBookService
from app.services.translate_service import TranslateService
from app.blueprints.dict_bp import create_dict_blueprint
from app.blueprints.symbol_font_bp import create_symbol_font_blueprint
from app.blueprints.file_mgmt_bp import create_file_mgmt_blueprint
from app.blueprints.url_book_bp import create_url_book_blueprint
from app.blueprints.translate_bp import create_translate_blueprint
from app.blueprints.export_bp import create_export_blueprint
from app.services.export_service import ExportService
from app.blueprints.paragraph_bp import create_paragraph_blueprint
from app.services.paragraph_service import ParagraphService
from app.blueprints.book_bp import create_book_blueprint
from app.services.book_service import BookService


app = Flask(__name__, template_folder="templates", static_folder="static")
# /api/book_toc 用の簡易キャッシュ（JSONのmtimeが変わらない限り再計算しない）
_BOOK_TOC_CACHE = {}
_BOOK_TOC_CACHE_LOCK = threading.Lock()
# mjsがtext/plain解釈されPDFビューアーが読み込めないケースへの対策。
# 一度キャッシュされると壊れたままになるので、F12→ハードキャッシュクリアを推奨。
import mimetypes
mimetypes.add_type('application/javascript', '.mjs')


def _get_env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    return value


def _get_env_csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


_EXTENSION_ORIGIN_PREFIXES = (
    "chrome-extension://",
    "moz-extension://",
    "edge-extension://",
)
_EXTRA_CORS_ALLOWED_ORIGINS = tuple(_get_env_csv("PARAPARATRANS_CORS_ALLOWED_ORIGINS"))


def _origin_is_loopback_http(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    return host in ("localhost", "127.0.0.1", "::1")


def _is_allowed_cors_origin(origin: str) -> bool:
    if not origin:
        return False
    if _origin_is_loopback_http(origin):
        return True
    # ブラウザ拡張（同梱 Chrome/Edge 拡張）からの import_html/current API を許可する。
    # 任意の Web origin ではなく、拡張 origin のみを許可対象に残す意図。
    if origin.startswith(_EXTENSION_ORIGIN_PREFIXES):
        return True
    for allowed in _EXTRA_CORS_ALLOWED_ORIGINS:
        if allowed.endswith("*"):
            if origin.startswith(allowed[:-1]):
                return True
        elif origin == allowed:
            return True
    return False


def _corsify_response(resp):
    origin = str(request.headers.get("Origin") or "").strip()
    if not _is_allowed_cors_origin(origin):
        return resp
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Max-Age"] = "600"
    resp.headers.add("Vary", "Origin")
    return resp


_BOOK_FONT_FAMILY_PATTERN = re.compile(r"font-family\s*:\s*([^;\n]+)", re.IGNORECASE)


def _extract_book_font_name(style_value: str) -> str:
    if not style_value:
        return ""

    match = _BOOK_FONT_FAMILY_PATTERN.search(style_value)
    if not match:
        return ""

    family_expr = match.group(1).strip()
    if not family_expr:
        return ""

    primary = family_expr.split(",", 1)[0].strip().strip("'\"")
    if not primary:
        return ""

    # PDF由来の `FontName-BoldItalic` 形式はハイフン以降を落としてフォント名だけ採用
    primary = primary.split("-", 1)[0].strip()
    if not primary:
        return ""

    return re.sub(r"\s+", " ", primary).strip()


def _perf_api_enabled() -> bool:
    flag = os.getenv("PERF_API", "").strip().lower()
    return flag not in ("", "0", "false", "off")


def _perf_log(message: str) -> None:
    if _perf_api_enabled():
        app.logger.info(message)

def _get_app_dir():
    """アプリの基準ディレクトリを返す（起動CWDに依存しない）。"""
    if getattr(sys, "frozen", False):
        # PyInstaller等でEXE化されている場合: exeのある場所を基準
        return os.path.dirname(sys.executable)
    # 通常の実行: このファイルの場所を基準
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _get_app_dir()

# data/ は入出力（pdf/json/html）、config/ はユーザー設定（辞書・settings）
DATA_FOLDER = os.path.abspath(os.getenv("PARAPARATRANS_DATA_DIR", os.path.join(APP_DIR, "data")))
CONFIG_FOLDER = os.path.abspath(os.getenv("PARAPARATRANS_CONFIG_DIR", os.path.join(APP_DIR, "config")))

URL_BOOKS_DIRNAME = "url_books"
URL_BOOK_PREFIX = "url/"
URL_BOOK_JSON_SUFFIX = ".url.json"

# 既存コード互換のため BASE_FOLDER は data/ を指す
BASE_FOLDER = DATA_FOLDER
SETTINGS_PATH = os.path.join(DATA_FOLDER, "paraparatrans.settings.json")

CHUNK_UPLOAD_THRESHOLD_MB = _get_env_int("CHUNK_UPLOAD_THRESHOLD_MB", 15, minimum=1)
CHUNK_UPLOAD_THRESHOLD_BYTES = CHUNK_UPLOAD_THRESHOLD_MB * 1024 * 1024
MAX_PDF_UPLOAD_MB = _get_env_int("MAX_PDF_UPLOAD_MB", 300, minimum=1)
MAX_PDF_UPLOAD_BYTES = MAX_PDF_UPLOAD_MB * 1024 * 1024
# multipart/form-data の boundary / ヘッダぶんだけ少し余裕を持たせる。
MAX_PDF_REQUEST_OVERHEAD_BYTES = 2 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_PDF_UPLOAD_BYTES + MAX_PDF_REQUEST_OVERHEAD_BYTES

DICT_PATH = os.path.join(CONFIG_FOLDER, "dict.txt")
SIMBLE_DICT_PATH = os.path.join(CONFIG_FOLDER, "symbolfonts.txt")
SYMBOLFONT_DICT_PATH = os.path.join(CONFIG_FOLDER, "symbolfont_dict.txt")



def _load_app_settings() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        return {"files": {}}
    try:
        return load_settings(SETTINGS_PATH)
    except Exception:
        return {"files": {}}


def _save_app_settings(settings: dict) -> None:
    save_settings(SETTINGS_PATH, settings, indent=2)


def _sync_runtime_translator_from_settings() -> None:
    settings = _load_app_settings()
    desired = settings.get("translator")
    if not desired:
        return
    try:
        set_current_translator(desired)
    except Exception as e:
        app.logger.warning(f"translator setting ignored ({desired}): {str(e)}")


def _migrate_user_file(filename: str) -> None:
    """旧 data/ 配下のユーザーファイルを config/ に移行（存在する場合のみ）。"""
    old_path = os.path.join(DATA_FOLDER, filename)
    new_path = os.path.join(CONFIG_FOLDER, filename)

    if os.path.exists(new_path):
        return
    if not os.path.exists(old_path):
        return

    os.makedirs(CONFIG_FOLDER, exist_ok=True)
    try:
        shutil.move(old_path, new_path)
        print(f"{filename} を data/ から config/ に移行しました: {new_path}")
    except Exception:
        shutil.copy2(old_path, new_path)
        print(f"{filename} を data/ から config/ にコピーしました: {new_path}")


os.makedirs(DATA_FOLDER, exist_ok=True)
os.makedirs(CONFIG_FOLDER, exist_ok=True)


def _startup_cleanup_tmp_files(folder: str, min_age_seconds: int = 600) -> int:
    """起動時に残った tmp ファイルを掃除する。

    - mkstemp 由来の tmpXXXXXX.* が異常終了等で残ることがある
    - ユーザー操作不要にするため、起動時に「十分古いもの」だけ削除する
    """
    try:
        entries = os.listdir(folder)
    except OSError:
        return 0

    now = time.time()
    removed = 0
    for name in entries:
        # tempfile.mkstemp() の典型: tmp + ランダム
        if not name.startswith("tmp"):
            continue
        if not (name.endswith(".tmp") or name.endswith(".json") or name.endswith(".txt")):
            continue

        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue

        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if age < min_age_seconds:
            continue

        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass

    return removed


removed_tmp = 0
removed_tmp += _startup_cleanup_tmp_files(DATA_FOLDER)
removed_tmp += _startup_cleanup_tmp_files(CONFIG_FOLDER)
if removed_tmp:
    print(f"起動時クリーンアップ: tmpファイルを{removed_tmp}件削除しました")

_migrate_user_file("dict.txt")
_migrate_user_file("symbolfonts.txt")
_migrate_user_file("symbolfont_dict.txt")


def _migrate_settings_to_data() -> None:
    """旧 config/ 配下の settings を data/ に移行（存在する場合のみ）。"""
    filename = "paraparatrans.settings.json"
    old_path = os.path.join(CONFIG_FOLDER, filename)
    new_path = os.path.join(DATA_FOLDER, filename)

    if os.path.exists(new_path):
        return
    if not os.path.exists(old_path):
        return

    os.makedirs(DATA_FOLDER, exist_ok=True)
    try:
        shutil.move(old_path, new_path)
        print(f"{filename} を config/ から data/ に移行しました: {new_path}")
    except Exception:
        shutil.copy2(old_path, new_path)
        print(f"{filename} を config/ から data/ にコピーしました: {new_path}")


_migrate_settings_to_data()
_sync_runtime_translator_from_settings()

# dict.txtのひな形
DICT_TEMPLATE = """#英語\t#日本語\t#状態\t#出現回数
Rune Quest\tルーンクエスト\t0\t0
Runequest\tルーンクエスト\t0\t0
Glorantha\tグローランサ\t0\t0
Detect Magic\t《魔力検知》\t1\t0
"""

# dict.txtが存在しない場合にひな形を出力
if not os.path.exists(DICT_PATH):
    print(f"dict.txt が存在しません。ひな形を作成します: {DICT_PATH}")
    os.makedirs(os.path.dirname(DICT_PATH), exist_ok=True)
    with open(DICT_PATH, "w", encoding="utf-8") as f:
        f.write(DICT_TEMPLATE)

# symbolfont_dict.txt のひな形（存在しない場合だけ作成）
SYMBOLFONT_DICT_TEMPLATE = """# symbolfont_dict.txt\n#\n# 形式: フォント名.キャラクター\t置換後文字列\n# 例:\n#   Wingdings.a\t■\n#   Wingdings.b\t▲\n#\n# メモ:\n# - フォント名は大小/空白/アンダースコア差を吸収して照合されます。\n# - 置換後文字列には翻訳拒否タグ等を含めてもOK（翻訳側で扱う想定）。\n\nWingdings.a\t■\nWingdings.b\t▲\n"""
if not os.path.exists(SYMBOLFONT_DICT_PATH):
    print(f"symbolfont_dict.txt が存在しません。ひな形を作成します: {SYMBOLFONT_DICT_PATH}")
    os.makedirs(os.path.dirname(SYMBOLFONT_DICT_PATH), exist_ok=True)
    with open(SYMBOLFONT_DICT_PATH, "w", encoding="utf-8") as f:
        f.write(SYMBOLFONT_DICT_TEMPLATE)

app.add_url_rule('/logstream', 'logstream', create_log_stream_endpoint())

def get_resource_path(relative_path):
    """PyInstaller で EXE 化された時のパスを取得する"""
    if getattr(sys, "frozen", False):
        # PyInstallerで実行されている場合
        base_path = sys._MEIPASS
    else:
        # 通常の実行（起動CWDに依存しない）
        base_path = APP_DIR

    return os.path.join(base_path, relative_path)


_IGNORED_DIR_NAMES = {
    "backup",
    "structure",
    "doc_structure",
    "url_books",
    "__pycache__",
    "old",
}


def _should_skip_dir(name: str) -> bool:
    if not name:
        return True
    if name.startswith("."):
        return True
    return name in _IGNORED_DIR_NAMES


def _normalize_pdf_name(pdf_name: str) -> str:
    if not isinstance(pdf_name, str):
        return ""
    normalized = pdf_name.replace("\\", "/").strip("/")
    if not normalized:
        return ""
    parts = [p for p in normalized.split("/") if p]
    if any(p in (".", "..") for p in parts):
        return ""
    return "/".join(parts)


def _is_url_book_name(pdf_name: str) -> bool:
    return isinstance(pdf_name, str) and pdf_name.startswith(URL_BOOK_PREFIX)


def _parse_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _url_page_sort_key(page_key: str):
    text = str(page_key)
    if text.isdigit():
        return (0, int(text), text)
    return (1, text)


def _sorted_url_page_keys(book_data: dict) -> list[str]:
    pages = (book_data or {}).get("pages") or {}
    if not isinstance(pages, dict):
        return []
    return sorted((str(k) for k in pages.keys()), key=_url_page_sort_key)


def _url_page_first_paragraph_summary(page_id: str, page: dict) -> dict:
    page_obj = page if isinstance(page, dict) else {}
    paragraphs = page_obj.get("paragraphs") or {}

    best = None
    if isinstance(paragraphs, dict):
        for para in paragraphs.values():
            if not isinstance(para, dict):
                continue
            order = _parse_int(para.get("order"), 10**9)
            column_order = _parse_int(para.get("column_order"), 10**9)
            bbox = para.get("bbox") or [0, 0]
            try:
                y0 = float(bbox[1]) if isinstance(bbox, list) and len(bbox) > 1 else 0.0
            except Exception:
                y0 = 0.0
            pid = str(para.get("id") or "")
            key = (order, column_order, y0, pid)
            if best is None or key < best[0]:
                best = (key, para)

    selected = best[1] if best else {}
    src_text = str(selected.get("src_text") or selected.get("src_joined") or page_obj.get("title") or page_obj.get("url") or f"Page {page_id}")
    trans_text = str(selected.get("trans_text") or selected.get("trans_auto") or "")
    return {
        "paragraph_id": str(selected.get("id") or ""),
        "src_text": src_text,
        "trans_text": trans_text,
    }


def _build_url_page_preview_map(book_data: dict) -> dict:
    result: dict[str, dict] = {}
    pages = (book_data or {}).get("pages") or {}
    if not isinstance(pages, dict):
        return result
    for page_id in _sorted_url_page_keys(book_data):
        result[str(page_id)] = _url_page_first_paragraph_summary(str(page_id), pages.get(str(page_id)) or {})
    return result


def _new_url_nav_node_id(existing_ids: set[str], page_id: str) -> str:
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


def _build_default_url_page_nav(book_data: dict) -> dict:
    page_keys = _sorted_url_page_keys(book_data)
    nodes: dict[str, dict] = {}
    root_children: list[str] = []
    existing_ids: set[str] = set()
    for page_id in page_keys:
        node_id = _new_url_nav_node_id(existing_ids, page_id)
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


def _ensure_url_page_nav(book_data: dict) -> bool:
    if not isinstance(book_data, dict):
        return False
    if (book_data.get("source_type") or "") != "url":
        return False

    changed = False
    page_keys = _sorted_url_page_keys(book_data)
    page_key_set = set(page_keys)

    nav = book_data.get("page_nav")
    if not isinstance(nav, dict):
        book_data["page_nav"] = _build_default_url_page_nav(book_data)
        nav = book_data["page_nav"]
        changed = True

    nodes_raw = nav.get("nodes")
    root_children_raw = nav.get("root_children")
    if not isinstance(nodes_raw, dict) or not isinstance(root_children_raw, list):
        book_data["page_nav"] = _build_default_url_page_nav(book_data)
        nav = book_data["page_nav"]
        changed = True
        nodes_raw = nav.get("nodes")
        root_children_raw = nav.get("root_children")

    nodes: dict[str, dict] = {}
    page_to_node: dict[str, str] = {}

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
        book_data["page_nav"] = _build_default_url_page_nav(book_data)
        changed = True
        nav = book_data["page_nav"]
        nodes = nav.get("nodes") or {}
        root_children_raw = nav.get("root_children") or []

    parent_of: dict[str, str] = {}
    for node_id, node in nodes.items():
        children: list[str] = []
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

    root_children: list[str] = []
    seen_root: set[str] = set()
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
        node_id = _new_url_nav_node_id(existing_ids, page_id)
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

    revision = _parse_int(nav.get("revision"), 1)
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
    url_to_page_id: dict[str, str] = {}
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


def _sanitize_folder_name(name: str) -> str:
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


def _safe_join_data(*parts: str) -> str:
    base = os.path.abspath(BASE_FOLDER)
    path = os.path.abspath(os.path.join(base, *parts))
    if os.path.commonpath([base, path]) != base:
        raise ValueError("path escapes data folder")
    return path

def get_paths(pdf_name):
    normalized = _normalize_pdf_name(pdf_name)
    if not normalized:
        normalized = "_invalid"
    if normalized.startswith(URL_BOOK_PREFIX):
        rel = normalized[len(URL_BOOK_PREFIX):]
        parts = [p for p in rel.split("/") if p] or ["_invalid"]
        base_path = _safe_join_data(*parts)
    else:
        parts = normalized.split("/")
        base_path = _safe_join_data(*parts)
    pdf_path = base_path + ".pdf"
    if normalized.startswith(URL_BOOK_PREFIX):
        json_path = base_path + URL_BOOK_JSON_SUFFIX
        legacy_json_path = _safe_join_data(URL_BOOKS_DIRNAME, *parts) + ".json"
        if not os.path.exists(json_path) and os.path.exists(legacy_json_path):
            json_path = legacy_json_path
    else:
        json_path = base_path + ".json"
    return pdf_path, json_path


dict_service = DictService(
    app_dir=APP_DIR,
    data_folder=DATA_FOLDER,
    config_folder=CONFIG_FOLDER,
    dict_path=DICT_PATH,
    get_paths=get_paths,
    should_skip_dir=_should_skip_dir,
)

chunked_upload_service = ChunkedUploadService(
    base_folder=BASE_FOLDER,
    max_total_size_bytes=MAX_PDF_UPLOAD_BYTES,
)
try:
    chunked_upload_service.cleanup_expired_sessions()
except Exception as e:
    app.logger.warning(f"古い分割アップロードセッションのクリーンアップに失敗しました: {str(e)}")

# 辞書管理 Blueprint を登録（app/blueprints/dict_bp.py）
_bp_dict = create_dict_blueprint(
    dict_service=dict_service,
    get_paths=get_paths,
    get_resource_path=get_resource_path,
    translate_dict_entries=translate_dict_entries,
    dict_create=dict_create,
)
app.register_blueprint(_bp_dict)

# シンボルフォント Blueprint を登録（app/blueprints/symbol_font_bp.py）
_symbolfont_service = SymbolFontService(
    symbolfont_dict_path=SYMBOLFONT_DICT_PATH,
    symbolfonts_path=SIMBLE_DICT_PATH,
)
_bp_symbol_font = create_symbol_font_blueprint(
    symbolfont_service=_symbolfont_service,
    get_paths=get_paths,
)
app.register_blueprint(_bp_symbol_font)

# ファイル管理 Blueprint を登録（app/blueprints/file_mgmt_bp.py）
_file_mgmt_service = FileMgmtService(
    base_folder=BASE_FOLDER,
    data_folder=DATA_FOLDER,
    url_book_prefix=URL_BOOK_PREFIX,
    url_book_json_suffix=URL_BOOK_JSON_SUFFIX,
    url_books_dirname=URL_BOOKS_DIRNAME,
)

# URL ブック Blueprint を登録（app/blueprints/url_book_bp.py）
_url_book_service = UrlBookService(
    config_folder=CONFIG_FOLDER,
    url_book_prefix=URL_BOOK_PREFIX,
)

_bp_file_mgmt = create_file_mgmt_blueprint(
    file_mgmt_service=_file_mgmt_service,
    get_paths=get_paths,
    chunked_upload_service=chunked_upload_service,
    get_current_url_book=_url_book_service.get_current_url_book,
    set_current_url_book=_url_book_service.set_current_url_book,
    chunk_upload_threshold_bytes=CHUNK_UPLOAD_THRESHOLD_BYTES,
    max_pdf_upload_bytes=MAX_PDF_UPLOAD_BYTES,
    max_pdf_upload_mb=MAX_PDF_UPLOAD_MB,
)
app.register_blueprint(_bp_file_mgmt)

_bp_url_book = create_url_book_blueprint(
    url_book_service=_url_book_service,
    get_paths=get_paths,
    normalize_pdf_name=_normalize_pdf_name,
    is_url_book_name=_is_url_book_name,
    sanitize_folder_name=_sanitize_folder_name,
    corsify_response=_corsify_response,
    config_folder=CONFIG_FOLDER,
    url_book_prefix=URL_BOOK_PREFIX,
)
app.register_blueprint(_bp_url_book)

# 翻訳 Blueprint を登録（app/blueprints/translate_bp.py）
_translate_service = TranslateService(
    dict_service=dict_service,
    data_folder=DATA_FOLDER,
    base_folder=BASE_FOLDER,
)
_bp_translate = create_translate_blueprint(
    translate_service=_translate_service,
    get_paths=get_paths,
    load_app_settings=_load_app_settings,
    save_app_settings=_save_app_settings,
)
app.register_blueprint(_bp_translate)

# エクスポート Blueprint を登録（app/blueprints/export_bp.py）
_export_service = ExportService(
    data_folder=DATA_FOLDER,
    app_dir=APP_DIR,
)
_bp_export = create_export_blueprint(
    export_service=_export_service,
    get_paths=get_paths,
)
app.register_blueprint(_bp_export)

# 段落管理 Blueprint を登録（app/blueprints/paragraph_bp.py）
_paragraph_service = ParagraphService(
    data_folder=DATA_FOLDER,
    simble_dict_path=SIMBLE_DICT_PATH,
    symbolfont_dict_path=SYMBOLFONT_DICT_PATH,
    is_url_book_name=_is_url_book_name,
)
_bp_paragraph = create_paragraph_blueprint(
    paragraph_service=_paragraph_service,
    get_paths=get_paths,
)
app.register_blueprint(_bp_paragraph)

# ブック閲覧 Blueprint を登録（app/blueprints/book_bp.py）
_book_service = BookService(
    get_paths=get_paths,
    is_url_book_name=_is_url_book_name,
    ensure_url_page_nav=_ensure_url_page_nav,
    build_url_page_preview_map=_build_url_page_preview_map,
    load_app_settings=_load_app_settings,
    save_app_settings=_save_app_settings,
)
_bp_book = create_book_blueprint(
    book_service=_book_service,
    get_paths=get_paths,
    normalize_pdf_name=_normalize_pdf_name,
    is_url_book_name=_is_url_book_name,
    url_book_prefix=URL_BOOK_PREFIX,
    perf_api_enabled=_perf_api_enabled,
    perf_log=_perf_log,
)
app.register_blueprint(_bp_book)


# Flaskテンプレートでループのインデックスを取得するためのフィルタ
@app.context_processor
def utility_processor():
    def enumerate_filter(iterable):
        return enumerate(iterable)
    return dict(enumerate=enumerate_filter)


# # API:ファイルへの辞書全置換
# @app.route("/api/dict_replace_all/<pdf_name>", methods=["POST"])
# def dict_replace_all_api(pdf_name):
#     if not os.path.exists(DICT_PATH):
#         return jsonify({"status": "error", "message": "dict.txtが存在しません2"}), 404
#     pdf_path, json_path = get_paths(pdf_name)
#     if not os.path.exists(json_path):
#         return jsonify({"status": "error", "message": "対象のJSONファイルが存在しません"}), 404
#     try:
#         file_replace_with_dict(json_path, DICT_PATH)
#     except Exception as e:
#         return jsonify({"status": "error", "message": f"辞書適用中のエラー: {str(e)}"}), 500
#     return jsonify({"status": "ok"}), 200


# API:ファイルの指定ページに辞書置換
@app.route("/api/dict_replace_pages/<path:pdf_name>", methods=["POST"])
def dict_replace_page_api(pdf_name):
    start_page = request.form.get("start_page", type=int)
    end_page = request.form.get("end_page", type=int)
    if not pdf_name or start_page is None or end_page is None:
        return jsonify({"status": "error", "message": "pdf_name, start_page, end_page は必須です"}), 400
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "対象のJSONファイルが存在しません"}), 404
    try:
        dict_paths = dict_service.get_active_dict_paths(pdf_name)
        merged_path = dict_service.merged_dict_file(dict_paths)
        try:
            book_data = file_replace_with_dict(json_path, merged_path, start_page, end_page)
        finally:
            try:
                os.remove(merged_path)
            except OSError:
                pass

        pages_delta = {}
        pages = (book_data or {}).get("pages", {}) or {}
        for page in range(start_page, end_page + 1):
            key = str(page)
            if key in pages:
                pages_delta[key] = pages[key]

        delta = {
            "pages": pages_delta,
            "trans_status_counts": (book_data or {}).get("trans_status_counts"),
        }
    except Exception as e:
        return jsonify({"status": "error", "message": f"辞書適用中のエラー: {str(e)}"}), 500
    return jsonify({"status": "ok", "delta": delta}), 200


@app.route("/api/dict_replace_paragraph/<path:pdf_name>", methods=["POST"])
def dict_replace_paragraph_api(pdf_name):
    data = request.get_json(silent=True) or {}
    page_number = data.get("page_number", None)
    paragraph_id = data.get("paragraph_id", None)

    try:
        page_number = int(page_number)
    except Exception:
        page_number = None

    if not pdf_name or page_number is None or paragraph_id in (None, ""):
        return jsonify({"status": "error", "message": "pdf_name, page_number, paragraph_id は必須です"}), 400

    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "対象のJSONファイルが存在しません"}), 404

    page_key = str(page_number)
    paragraph_key = str(paragraph_id)

    try:
        dict_paths = dict_service.get_active_dict_paths(pdf_name)
        merged_path = dict_service.merged_dict_file(dict_paths)
        try:
            dict_cs, dict_ci = load_dictionary(merged_path)
        finally:
            try:
                os.remove(merged_path)
            except OSError:
                pass

        book_data = load_json(json_path)
        pages = (book_data or {}).get("pages", {}) or {}
        page = pages.get(page_key)
        if not isinstance(page, dict):
            return jsonify({"status": "error", "message": f"ページが見つかりません: {page_number}"}), 404

        paragraphs = (page or {}).get("paragraphs", {}) or {}
        paragraph = paragraphs.get(paragraph_key)
        if not isinstance(paragraph, dict):
            for para in paragraphs.values():
                if isinstance(para, dict) and str(para.get("id")) == paragraph_key:
                    paragraph = para
                    break

        if not isinstance(paragraph, dict):
            return jsonify({"status": "error", "message": f"段落が見つかりません: {paragraph_key}"}), 404

        src_joined = paragraph.get("src_joined", "")
        paragraph["src_replaced"] = replace_with_dict(src_joined, dict_cs, dict_ci)

        atomicsave_json(json_path, book_data)

        delta = {
            "pages": {
                page_key: page,
            },
            "trans_status_counts": (book_data or {}).get("trans_status_counts"),
        }
        return jsonify({"status": "ok", "delta": delta}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"段落辞書適用中のエラー: {str(e)}"}), 500



@app.route("/api/dict_create/<path:pdf_name>", methods=["POST"])
def dict_create_api(pdf_name):
    pdf_path, json_path = get_paths(pdf_name)
    COMMON_WORDS_PATH = get_resource_path(os.path.join("modules", "english_common_words.txt"))
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404
    try:
        dict_path = dict_service.get_primary_dict_path(pdf_name)
        dict_service.ensure_dict_file(dict_path)
        dict_create(json_path, dict_path, COMMON_WORDS_PATH)
    except Exception as e:
        return jsonify({"status": "error", "message": f"辞書生成エラー: {str(e)}"}), 500
    return jsonify({"status": "ok", "message": "辞書生成完了"}), 200

@app.route("/api/dict_trans/<path:pdf_name>", methods=["POST"])
def dict_trans_api(pdf_name):
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404
    try:
        dict_paths = dict_service.get_active_dict_paths(pdf_name)
        if not dict_paths:
            dict_paths = [DICT_PATH]
        for path in dict_paths:
            if not os.path.exists(path):
                continue
            dict_trans(path)
    except Exception as e:
        return jsonify({"status": "error", "message": f"辞書翻訳エラー: {str(e)}"}), 500
    return jsonify({"status": "ok", "message": "辞書翻訳完了"}), 200



# PDFビューアーがChromeで読み込めなかったときに対策として入れてみた。
# キャッシュクリアで治ったのでコメントアウト化。
# @app.after_request
# def add_header(response):
#     if request.path.endswith('.mjs'):
#         response.headers['Content-Type'] = 'application/javascript'
#     return response


@app.after_request
def gzip_compress_response(response):
    try:
        accept = request.headers.get("Accept-Encoding", "")
        if "gzip" not in accept.lower():
            return response
        if response.direct_passthrough or response.is_streamed:
            return response
        if response.headers.get("Content-Encoding"):
            return response
        if response.mimetype == "text/event-stream":
            return response

        data = response.get_data()
        if not data or len(data) < 512:
            return response

        compressible_types = (
            "text/",
            "application/javascript",
            "application/json",
            "application/xml",
            "image/svg+xml",
        )
        if not any(response.mimetype.startswith(t) for t in compressible_types):
            return response

        compressed = gzip.compress(data, compresslevel=6)
        response.set_data(compressed)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(compressed))
        response.headers.add("Vary", "Accept-Encoding")
        return response
    except Exception:
        return response


@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(_error):
    message = f"PDFサイズ上限({MAX_PDF_UPLOAD_MB}MB)を超えています"
    if request.path.startswith("/api/"):
        response = jsonify({"status": "error", "message": message})
        response.status_code = 413
        return response
    return message, 413

if __name__ == "__main__":
    # portはenvファイルの設定に従う。未指定の場合は5077
    port_str = os.getenv("PORT", "5077")
    if not port_str.isdigit():
        raise ValueError(f"Invalid PORT: {port_str}")
    port = int(port_str)

    # debug/reloader は起動直後のプロセス二重起動でリクエストが落ちる原因になるため、
    # 明示的に環境変数でのみ有効化し、reloaderは常に無効化する。
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes", "on")
    # ターミナルにリンクを出力
    print(f"Flask server is running at: http://localhost:{port}/")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True, use_reloader=False)
