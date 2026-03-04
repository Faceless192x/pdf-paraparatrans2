from flask import Flask, request, render_template, redirect, url_for, send_from_directory, jsonify, send_file
import os
import json
import datetime
import io
import zipfile
import sys
import threading
import shutil
import time
import html
import gzip
import fitz
# /api/book_toc 用の簡易キャッシュ（JSONのmtimeが変わらない限り再計算しない）
from PyPDF2 import PdfReader, PdfWriter
import uuid  # ファイル名の一意性を確保するために追加
import tempfile
import re

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
    get_current_translator,
    get_supported_translators,
    set_current_translator,
    translate_text,
)
from modules.parapara_trans import paraparatrans_json_file, recalc_trans_status_counts
from modules.parapara_init import parapara_init  # parapara_initをインポート
# スタイルによるblock_tag一括更新
from modules.parapara_tagging_by_style import tag_paragraphs_by_style # 追加
# スタイル + Y範囲による header/footer タグ付け
from modules.parapara_tagging_by_style_y import tag_paragraphs_by_style_y_in_file
# 対訳HTMLの出力
from modules.parapara_json2html import json2html
from modules.parapara_align_trans_by_src_joined import (
    align_translations_by_src_joined,
    align_translations_by_src_joined_collect_pages,
)
from modules.settings_sync import (
    load_settings,
    lazy_sync_settings_from_json_files,
    save_settings,
    sync_one_pdf_settings_from_json,
)
from modules.parapara_structure import (
    ensure_backup_copy as structure_ensure_backup_copy,
    load_json_from_upload as structure_load_json_from_upload,
    merge_structure_into_book as structure_merge_into_book,
    strip_structure as structure_strip,
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
from app.blueprints.dict_bp import create_dict_blueprint
from app.blueprints.symbol_font_bp import create_symbol_font_blueprint
from app.blueprints.file_mgmt_bp import create_file_mgmt_blueprint


app = Flask(__name__, template_folder="templates", static_folder="static")
# /api/book_toc 用の簡易キャッシュ（JSONのmtimeが変わらない限り再計算しない）
_BOOK_TOC_CACHE = {}
_BOOK_TOC_CACHE_LOCK = threading.Lock()
_CURRENT_URL_BOOK = {"name": "", "updated_at": 0}
_CURRENT_URL_BOOK_LOCK = threading.Lock()
_URL_IMPORT_EVENTS = {}
_URL_IMPORT_EVENTS_LOCK = threading.Lock()
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


def _corsify_response(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Max-Age"] = "600"
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


def _set_current_url_book(book_name: str) -> None:
    with _CURRENT_URL_BOOK_LOCK:
        _CURRENT_URL_BOOK["name"] = book_name
        _CURRENT_URL_BOOK["updated_at"] = int(time.time())


def _get_current_url_book() -> str:
    with _CURRENT_URL_BOOK_LOCK:
        return _CURRENT_URL_BOOK.get("name") or ""


def _save_site_profiles(config_folder: str, profiles: dict) -> None:
    os.makedirs(config_folder, exist_ok=True)
    path = os.path.join(config_folder, "url_site_profiles.json")
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


def _normalize_selector_list(values) -> list:
    if not isinstance(values, list):
        return []
    out = []
    for item in values:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def _set_url_import_event(book_name: str, event: dict) -> None:
    with _URL_IMPORT_EVENTS_LOCK:
        _URL_IMPORT_EVENTS[book_name] = event


def _get_url_import_event(book_name: str) -> dict:
    with _URL_IMPORT_EVENTS_LOCK:
        return _URL_IMPORT_EVENTS.get(book_name) or {}


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

DICT_PATH = os.path.join(CONFIG_FOLDER, "dict.txt")
SIMBLE_DICT_PATH = os.path.join(CONFIG_FOLDER, "symbolfonts.txt")
SYMBOLFONT_DICT_PATH = os.path.join(CONFIG_FOLDER, "symbolfont_dict.txt")

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"(?i)<br\s*/?>")
_P_CLOSE_RE = re.compile(r"(?i)</p>")
_P_OPEN_RE = re.compile(r"(?i)<p[^>]*>")


def _strip_html_text(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = _BR_RE.sub("\n", s)
    s = _P_CLOSE_RE.sub("\n", s)
    s = _P_OPEN_RE.sub("", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    s = s.replace("\u00a0", " ")
    return s


def _paragraph_sort_key(paragraph: dict) -> tuple:
    try:
        page_number = int(paragraph.get("page_number") or 0)
    except Exception:
        page_number = 0
    try:
        order = int(paragraph.get("order") or 0)
    except Exception:
        order = 0
    try:
        column_order = int(paragraph.get("column_order") or 0)
    except Exception:
        column_order = 0
    try:
        y0 = float((paragraph.get("bbox") or [0, 0])[1] or 0)
    except Exception:
        y0 = 0
    return (page_number, order, column_order, y0)


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


def _iter_sorted_paragraphs(book_data: dict) -> list[dict]:
    paragraphs_list = []
    pages = book_data.get("pages", {}) or {}
    for page in pages.values():
        paragraphs = (page or {}).get("paragraphs", {}) or {}
        for para in paragraphs.values():
            if isinstance(para, dict):
                paragraphs_list.append(para)
    paragraphs_list.sort(key=_paragraph_sort_key)
    return paragraphs_list


def _build_text_export_content(
    book_data: dict,
    fields: list[str],
    *,
    include_page_numbers: bool,
    include_header: bool,
    include_footer: bool,
    include_remove: bool,
    fmt: str,
) -> str:
    paragraphs_list = _iter_sorted_paragraphs(book_data)
    lines: list[str] = []
    current_page = None
    page_prefix = "## Page " if fmt == "md" else "Page "

    for paragraph in paragraphs_list:
        block_tag = str(paragraph.get("block_tag") or "").lower()
        if block_tag == "header" and not include_header:
            continue
        if block_tag == "footer" and not include_footer:
            continue
        if block_tag == "remove" and not include_remove:
            continue

        page_number = paragraph.get("page_number") or 0
        if include_page_numbers and page_number != current_page:
            current_page = page_number
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"{page_prefix}{page_number}")

        values = []
        for key in fields:
            raw = paragraph.get(key, "")
            text = _strip_html_text(raw).strip()
            values.append(text)

        if not any(values):
            continue

        for value in values:
            if value:
                lines.append(value)

        lines.append("")

    content = "\n".join(lines).strip()
    if content:
        content += "\n"
    return content


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


def _url_nav_parent_list(page_nav: dict, node_id: str):
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


def _move_url_page_nav_node(page_nav: dict, node_id: str, op: str) -> tuple[bool, str]:
    nodes = page_nav.get("nodes") or {}
    if node_id not in nodes:
        return False, "node_idが不正です"

    siblings, parent_id, index = _url_nav_parent_list(page_nav, node_id)
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

        parent_siblings, grand_parent_id, parent_index = _url_nav_parent_list(page_nav, parent_id)
        if parent_siblings is None:
            return False, "親ノード配置が不正です"

        siblings.pop(index)
        insert_index = parent_index + 1
        parent_siblings.insert(insert_index, node_id)
        nodes[node_id]["parent_id"] = grand_parent_id
        return True, "ok"

    return False, "opが不正です"


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

chunked_upload_service = ChunkedUploadService(base_folder=BASE_FOLDER)
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
_bp_file_mgmt = create_file_mgmt_blueprint(
    file_mgmt_service=_file_mgmt_service,
    get_paths=get_paths,
    chunked_upload_service=chunked_upload_service,
    get_current_url_book=_get_current_url_book,
    set_current_url_book=_set_current_url_book,
    chunk_upload_threshold_bytes=CHUNK_UPLOAD_THRESHOLD_BYTES,
)
app.register_blueprint(_bp_file_mgmt)


# Flaskテンプレートでループのインデックスを取得するためのフィルタ
@app.context_processor
def utility_processor():
    def enumerate_filter(iterable):
        return enumerate(iterable)
    return dict(enumerate=enumerate_filter)

@app.route("/detail/<path:pdf_name>")
@app.route("/detail/<path:pdf_name>/<int:page_number>")  # page_number をオプションに
def detail(pdf_name, page_number=1):
    normalized_pdf_name = _normalize_pdf_name(pdf_name)
    if not normalized_pdf_name:
        return "pdf_name が不正です", 400

    pdf_name = normalized_pdf_name
    is_url_book = _is_url_book_name(pdf_name)
    book_type = "url" if is_url_book else "pdf"
    if is_url_book:
        book_rel = pdf_name[len(URL_BOOK_PREFIX):]
        current_dir = os.path.dirname(book_rel).replace("\\", "/")
    else:
        current_dir = os.path.dirname(pdf_name).replace("\\", "/")
    index_dir = current_dir if current_dir else None
    pdf_path, json_path = get_paths(pdf_name)

    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        if isinstance(book_data, dict) and book_type == "url":
            book_data.setdefault("source_type", "url")
    else:
        if is_url_book:
            return "URLブックが存在しません", 404
        book_data = {
            "src_filename": pdf_name,
            "title": pdf_name,
            "styles": {},
            "trans_status_counts": {"pending": 0, "auto": 0, "manual": 0, "fixed": 0},
            "pages": []
        }

    updated_date = ""
    if os.path.exists(json_path):
        updated_date = datetime.datetime.fromtimestamp(os.path.getmtime(json_path)).strftime("%Y/%m/%d")
    elif os.path.exists(pdf_path):
        updated_date = datetime.datetime.fromtimestamp(os.path.getmtime(pdf_path)).strftime("%Y/%m/%d")

    return render_template(
        "detail.html",
        pdf_name=pdf_name,
        page_number=page_number,
        book_data=book_data,
        updated_date=updated_date,
        index_dir=index_dir,
        book_type=book_type,
    )


# API:book_dataデータ取得
@app.route("/api/book_data/<path:pdf_name>")
def get_book_data(pdf_name):
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "ok", "message": "JSONが存在しません"}), 206
    with open(json_path, "r", encoding="utf-8") as f:
        book_data = json.load(f)
    if _is_url_book_name(pdf_name):
        _ensure_url_page_nav(book_data)
    return jsonify(book_data)


# API: book_data のメタ情報のみ取得（初期ロード高速化用）
@app.route("/api/book_meta/<path:pdf_name>")
def get_book_meta(pdf_name):
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "ok", "message": "JSONが存在しません"}), 206

    try:
        json_mtime = os.path.getmtime(json_path)
    except OSError:
        json_mtime = None

    with open(json_path, "r", encoding="utf-8") as f:
        book_data = json.load(f)

    if _is_url_book_name(pdf_name):
        _ensure_url_page_nav(book_data)

    last_open_page = book_data.get("last_open_page")
    if not _is_url_book_name(pdf_name):
        try:
            settings = _load_app_settings()
            files = (settings or {}).get("files", {}) or {}
            settings_page = (files.get(pdf_name) or {}).get("last_open_page")
            if settings_page is not None:
                last_open_page = settings_page
        except Exception:
            pass

    meta = {
        "version": book_data.get("version"),
        "src_filename": book_data.get("src_filename"),
        "title": book_data.get("title"),
        "page_count": book_data.get("page_count"),
        "last_open_page": last_open_page,
        "styles": book_data.get("styles") or {},
        "trans_status_counts": book_data.get("trans_status_counts") or {},
        "json_mtime": json_mtime,
        "source_type": book_data.get("source_type") or "pdf",
        "source_root_url": book_data.get("source_root_url"),
        "source_host": book_data.get("source_host"),
        "page_url_map": book_data.get("page_url_map") or {},
        "url_to_page_id": book_data.get("url_to_page_id") or {},
        "page_nav": book_data.get("page_nav") or {},
        "page_preview_map": _build_url_page_preview_map(book_data) if _is_url_book_name(pdf_name) else {},
    }
    return jsonify({"status": "ok", "meta": meta})


@app.route("/api/update_last_page/<path:pdf_name>", methods=["POST"])
def update_last_page_api(pdf_name):
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

    data = request.get_json(silent=True) or {}
    page_number = data.get("page_number")
    try:
        page_number = int(page_number)
    except Exception:
        return jsonify({"status": "error", "message": "page_number が不正です"}), 400

    if page_number < 1:
        return jsonify({"status": "error", "message": "page_number は1以上で指定してください"}), 400

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        try:
            page_count = int(book_data.get("page_count") or 0)
        except Exception:
            page_count = 0
        if page_count > 0:
            page_number = max(1, min(page_number, page_count))

        if _is_url_book_name(pdf_name):
            if book_data.get("last_open_page") == page_number:
                return jsonify({"status": "ok", "changed": 0, "stored_in": "book_data"}), 200

            book_data["last_open_page"] = page_number

            temp_file = f"{json_path}.{uuid.uuid4().hex}.tmp"
            try:
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(book_data, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, json_path)
            except Exception:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                raise

            return jsonify({"status": "ok", "changed": 1, "last_open_page": page_number, "stored_in": "book_data"}), 200

        settings = _load_app_settings()
        files = settings.get("files") or {}
        file_entry = files.get(pdf_name)
        if not isinstance(file_entry, dict):
            file_entry = {}
            files[pdf_name] = file_entry
            settings["files"] = files

        try:
            prev_page = int(file_entry.get("last_open_page")) if file_entry.get("last_open_page") is not None else None
        except Exception:
            prev_page = None
        if prev_page == page_number:
            return jsonify({"status": "ok", "changed": 0, "stored_in": "settings"}), 200

        file_entry["last_open_page"] = page_number
        _save_app_settings(settings)

        return jsonify({"status": "ok", "changed": 1, "last_open_page": page_number, "stored_in": "settings"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"最終ページ保存中にエラーが発生しました: {str(e)}"}), 500


# API: 目次（見出し）情報のみ取得（初期ロード高速化用）
@app.route("/api/book_toc/<path:pdf_name>")
def get_book_toc(pdf_name):
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

    try:
        mtime = os.path.getmtime(json_path)
    except OSError:
        mtime = None

    if mtime is not None:
        with _BOOK_TOC_CACHE_LOCK:
            cached = _BOOK_TOC_CACHE.get(pdf_name)
            if cached and cached.get("mtime") == mtime and isinstance(cached.get("toc"), list):
                return jsonify({"status": "ok", "toc": cached["toc"], "cached": True})

    with open(json_path, "r", encoding="utf-8") as f:
        book_data = json.load(f)

    headlines = []
    pages = book_data.get("pages", {}) or {}
    for page_key, page in pages.items():
        paragraphs = (page or {}).get("paragraphs", {}) or {}
        for _pid, p in paragraphs.items():
            block_tag = (p or {}).get("block_tag")
            join_flag = int((p or {}).get("join", 0) or 0)
            if join_flag == 1:
                continue
            if not isinstance(block_tag, str):
                continue
            if not re.match(r"^h[1-6]$", block_tag):
                continue

            page_number = (p or {}).get("page_number")
            para_id = (p or {}).get("id")
            try:
                y0 = (p or {}).get("bbox")[1]
            except Exception:
                y0 = 0

            headlines.append(
                {
                    "rowId": f"{page_number}_{para_id}",
                    "page_number": page_number,
                    "id": para_id,
                    "order": (p or {}).get("order", 0) or 0,
                    "column_order": (p or {}).get("column_order", 0) or 0,
                    "y0": y0,
                    "block_tag": block_tag,
                    "src_joined": (p or {}).get("src_joined"),
                    "trans_text": (p or {}).get("trans_text"),
                    "join": join_flag,
                }
            )

    def _toc_sort_key(item: dict):
        try:
            pn = int(item.get("page_number") or 0)
        except Exception:
            pn = 0
        try:
            order = int(item.get("order") or 0)
        except Exception:
            order = 0
        try:
            col = int(item.get("column_order") or 0)
        except Exception:
            col = 0
        try:
            y0 = float(item.get("y0") or 0)
        except Exception:
            y0 = 0
        return (pn, order, col, y0)

    headlines.sort(key=_toc_sort_key)

    if mtime is not None:
        with _BOOK_TOC_CACHE_LOCK:
            _BOOK_TOC_CACHE[pdf_name] = {"mtime": mtime, "toc": headlines}

    return jsonify({"status": "ok", "toc": headlines, "cached": False})


# API: 指定ページだけ取得（差分更新用）
@app.route("/api/book_page/<path:pdf_name>/<int:page_number>")
def get_book_page(pdf_name, page_number: int):
    t0 = time.perf_counter()
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 404
    json_size = None
    try:
        json_size = os.path.getsize(json_path)
    except Exception:
        json_size = None

    t_load_start = time.perf_counter()
    with open(json_path, "r", encoding="utf-8") as f:
        book_data = json.load(f)
    t_load_end = time.perf_counter()

    t_page_start = time.perf_counter()
    page_key = str(page_number)
    page = (book_data.get("pages", {}) or {}).get(page_key)
    t_page_end = time.perf_counter()
    if page is None:
        return jsonify({"status": "error", "message": f"ページが存在しません: {page_number}"}), 404

    t1 = time.perf_counter()
    if _perf_api_enabled():
        size_kb = (json_size / 1024.0) if isinstance(json_size, (int, float)) else None
        size_note = f", json_kb={size_kb:.1f}" if size_kb is not None else ""
        _perf_log(
            f"[perf] book_page page={page_number} load_json={(t_load_end - t_load_start)*1000:.1f} ms "
            f"select_page={(t_page_end - t_page_start)*1000:.1f} ms total={(t1 - t0)*1000:.1f} ms"
            f"{size_note}"
        )

    response = jsonify(
        {
            "status": "ok",
            "page_key": page_key,
            "page": page,
            "trans_status_counts": book_data.get("trans_status_counts"),
            "page_count": book_data.get("page_count"),
            "title": book_data.get("title"),
        }
    )

    if _perf_api_enabled():
        load_ms = (t_load_end - t_load_start) * 1000.0
        select_ms = (t_page_end - t_page_start) * 1000.0
        total_ms = (t1 - t0) * 1000.0
        response.headers["Server-Timing"] = (
            f"load_json;dur={load_ms:.1f}, "
            f"select_page;dur={select_ms:.1f}, "
            f"total;dur={total_ms:.1f}"
        )

    return response


# API: 全文検索（src_joined/trans_text/trans_auto）
@app.route("/api/search/<path:pdf_name>")
def search_api(pdf_name: str):
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

    query = (request.args.get("q") or "").strip()
    try:
        limit = int(request.args.get("limit") or 200)
    except Exception:
        limit = 200
    limit = max(1, min(limit, 2000))

    try:
        results = search_paragraphs_in_book(json_path, query, limit=limit)
    except Exception as e:
        app.logger.exception("search failed")
        return jsonify({"status": "error", "message": f"検索エラー: {str(e)}"}), 500

    return jsonify({"status": "ok", "query": query, "count": len(results), "results": results})


@app.route("/api/url_book/create", methods=["POST"])
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
        book_name = _normalize_pdf_name(book_name)
        if not book_name:
            return jsonify({"status": "error", "message": "book_nameが不正です"}), 400
        if not book_name.startswith(URL_BOOK_PREFIX):
            book_name = f"{URL_BOOK_PREFIX}{book_name}"
    else:
        slug = _sanitize_folder_name(host.replace(":", "_")) or host.replace(":", "_")
        book_name = f"{URL_BOOK_PREFIX}{slug}"

    _, json_path = get_paths(book_name)
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
            _ensure_url_page_nav(book_data)
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

    profiles = load_site_profiles(CONFIG_FOLDER)
    profile = get_site_profile(profiles, host)
    title = (payload.get("title") or "").strip() or None

    try:
        book_data = build_url_book_data(normalized, title=title, site_profile=profile)
        _ensure_url_page_nav(book_data)
        save_url_book(json_path, book_data)
    except Exception as e:
        app.logger.exception("URL book create failed")
        return jsonify({"status": "error", "message": f"URL取得に失敗しました: {str(e)}"}), 500

    return jsonify({
        "status": "ok",
        "book_name": book_name,
        "exists": False,
        "title": book_data.get("title"),
        "page_count": book_data.get("page_count"),
        "page_nav": book_data.get("page_nav") or {},
    })


@app.route("/api/url_book/navigate", methods=["POST"])
def navigate_url_book_api():
    payload = request.get_json(silent=True) or {}
    book_name = _normalize_pdf_name(payload.get("book_name") or "")
    if not book_name or not _is_url_book_name(book_name):
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

    profiles = load_site_profiles(CONFIG_FOLDER)
    profile = get_site_profile(profiles, root_host)

    try:
        page_number, page_data, added = ensure_url_page_in_book(book_data, normalized, site_profile=profile)
        nav_changed = _ensure_url_page_nav(book_data)
        if added or nav_changed:
            save_url_book(json_path, book_data)
    except Exception as e:
        app.logger.exception("URL book navigate failed")
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


@app.route("/api/url_book/import_html", methods=["POST", "OPTIONS"])
def import_url_book_html_api():
    if request.method == "OPTIONS":
        resp = app.make_response("")
        resp.status_code = 204
        return _corsify_response(resp)

    payload = request.get_json(silent=True) or {}
    book_name = _normalize_pdf_name(payload.get("book_name") or "")
    if not book_name:
        book_name = _get_current_url_book()
    if not book_name or not _is_url_book_name(book_name):
        resp = jsonify({"status": "error", "message": "book_nameが不正です"})
        resp.status_code = 400
        return _corsify_response(resp)

    raw_url = (payload.get("url") or "").strip()
    normalized = normalize_url(raw_url)
    if not normalized:
        resp = jsonify({"status": "error", "message": "URLが不正です"})
        resp.status_code = 400
        return _corsify_response(resp)

    html_text = payload.get("html") or ""
    force = bool(payload.get("force", False))

    _, json_path = get_paths(book_name)
    if not os.path.exists(json_path):
        resp = jsonify({"status": "error", "message": "URLブックが存在しません"})
        resp.status_code = 404
        return _corsify_response(resp)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
    except Exception as e:
        resp = jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"})
        resp.status_code = 500
        return _corsify_response(resp)

    root_host = (book_data or {}).get("source_host") or normalize_host((book_data or {}).get("source_root_url") or "")
    target_host = normalize_host(normalized)
    if root_host and target_host and root_host != target_host:
        resp = jsonify({"status": "error", "message": "別ドメインのURLはこのブックに追加できません"})
        resp.status_code = 400
        return _corsify_response(resp)

    profiles = load_site_profiles(CONFIG_FOLDER)
    profile = get_site_profile(profiles, root_host)

    try:
        page_number, page_data, added, updated = ensure_url_page_in_book_from_html(
            book_data,
            normalized,
            html_text,
            site_profile=profile,
            force=force,
        )
        nav_changed = _ensure_url_page_nav(book_data)
        if added or updated or nav_changed:
            save_url_book(json_path, book_data)
    except Exception as e:
        app.logger.exception("URL book import_html failed")
        resp = jsonify({"status": "error", "message": f"HTML取り込みに失敗しました: {str(e)}"})
        resp.status_code = 500
        return _corsify_response(resp)

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
    _set_url_import_event(book_name, event)

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
    return _corsify_response(resp)


@app.route("/api/url_book/import_url", methods=["POST"])
def import_url_book_url_api():
    payload = request.get_json(silent=True) or {}
    book_name = _normalize_pdf_name(payload.get("book_name") or "")
    if not book_name:
        book_name = _get_current_url_book()
    if not book_name or not _is_url_book_name(book_name):
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

    profiles = load_site_profiles(CONFIG_FOLDER)
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
        nav_changed = _ensure_url_page_nav(book_data)
        if added or updated or nav_changed:
            save_url_book(json_path, book_data)
    except Exception as e:
        app.logger.exception("URL book import_url failed")
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
    _set_url_import_event(book_name, event)

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


@app.route("/api/url_book/import_event/<path:book_name>", methods=["GET"])
def url_book_import_event_api(book_name: str):
    normalized = _normalize_pdf_name(book_name or "")
    if not normalized or not _is_url_book_name(normalized):
        return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

    event = _get_url_import_event(normalized)
    if not event:
        return jsonify({"status": "ok", "event": None}), 200

    return jsonify({"status": "ok", "event": event}), 200


@app.route("/api/url_book/site_rules/<path:book_name>", methods=["GET", "POST"])
def url_book_site_rules_api(book_name: str):
    normalized = _normalize_pdf_name(book_name or "")
    if not normalized or not _is_url_book_name(normalized):
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

    profiles = load_site_profiles(CONFIG_FOLDER)
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
    include_selectors = _normalize_selector_list(payload.get("include_selectors"))
    add_selectors = _normalize_selector_list(payload.get("add_selectors"))
    exclude_selectors = _normalize_selector_list(payload.get("exclude_selectors"))

    profiles[host] = {
        "include_selectors": include_selectors,
        "add_selectors": add_selectors,
        "exclude_selectors": exclude_selectors,
    }
    try:
        _save_site_profiles(CONFIG_FOLDER, profiles)
    except Exception as e:
        return jsonify({"status": "error", "message": f"ルールの保存に失敗しました: {str(e)}"}), 500

    rule_event = {
        "id": uuid.uuid4().hex,
        "book_name": normalized,
        "kind": "rule_update",
        "created_at": int(time.time()),
    }
    _set_url_import_event(normalized, rule_event)

    return jsonify({
        "status": "ok",
        "host": host,
        "site_rules": profiles[host],
    }), 200


@app.route("/api/url_book/current", methods=["GET", "POST", "OPTIONS"])
def current_url_book_api():
    if request.method == "OPTIONS":
        resp = app.make_response("")
        resp.status_code = 204
        return _corsify_response(resp)

    if request.method == "GET":
        resp = jsonify({"status": "ok", "book_name": _get_current_url_book()})
        return _corsify_response(resp)

    payload = request.get_json(silent=True) or {}
    book_name = _normalize_pdf_name(payload.get("book_name") or "")
    if not book_name or not _is_url_book_name(book_name):
        resp = jsonify({"status": "error", "message": "book_nameが不正です"})
        resp.status_code = 400
        return _corsify_response(resp)

    _set_current_url_book(book_name)
    resp = jsonify({"status": "ok", "book_name": book_name})
    return _corsify_response(resp)


@app.route("/api/url_book/page_nav/<path:book_name>", methods=["GET", "PUT"])
def url_book_page_nav_api(book_name: str):
    normalized = _normalize_pdf_name(book_name or "")
    if not normalized or not _is_url_book_name(normalized):
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
        changed = _ensure_url_page_nav(book_data)
        if changed:
            save_url_book(json_path, book_data)
        return jsonify({
            "status": "ok",
            "page_nav": book_data.get("page_nav") or {},
            "revision": _parse_int((book_data.get("page_nav") or {}).get("revision"), 1),
        }), 200

    payload = request.get_json(silent=True) or {}
    expected_revision = _parse_int(payload.get("revision"), 0)
    changed = _ensure_url_page_nav(book_data)
    current_revision = _parse_int((book_data.get("page_nav") or {}).get("revision"), 1)
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
    _ensure_url_page_nav(book_data)
    next_revision = current_revision + 1
    book_data["page_nav"]["revision"] = next_revision
    save_url_book(json_path, book_data)

    return jsonify({
        "status": "ok",
        "page_nav": book_data.get("page_nav") or {},
        "revision": next_revision,
    }), 200


@app.route("/api/url_book/page_nav/move", methods=["POST"])
def move_url_book_page_nav_api():
    payload = request.get_json(silent=True) or {}
    book_name = _normalize_pdf_name(payload.get("book_name") or "")
    if not book_name or not _is_url_book_name(book_name):
        return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

    node_id = str(payload.get("node_id") or "").strip()
    op = str(payload.get("op") or "").strip().lower()
    expected_revision = _parse_int(payload.get("revision"), 0)
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

    changed = _ensure_url_page_nav(book_data)
    page_nav = book_data.get("page_nav") or {}
    current_revision = _parse_int(page_nav.get("revision"), 1)
    if changed:
        save_url_book(json_path, book_data)

    if expected_revision != current_revision:
        return jsonify({
            "status": "error",
            "message": "ページリストが更新されています。再読み込みしてください",
            "revision": current_revision,
            "page_nav": page_nav,
        }), 409

    ok, message = _move_url_page_nav_node(page_nav, node_id, op)
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


@app.route("/api/url_book/page_nav/rebuild", methods=["POST"])
def rebuild_url_book_page_nav_api():
    payload = request.get_json(silent=True) or {}
    book_name = _normalize_pdf_name(payload.get("book_name") or "")
    if not book_name or not _is_url_book_name(book_name):
        return jsonify({"status": "error", "message": "book_nameが不正です"}), 400

    _, json_path = get_paths(book_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "URLブックが存在しません"}), 404

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
    except Exception as e:
        return jsonify({"status": "error", "message": f"URLブックの読み込みに失敗しました: {str(e)}"}), 500

    before_revision = _parse_int((book_data.get("page_nav") or {}).get("revision"), 1)
    changed = _ensure_url_page_nav(book_data)

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


@app.route("/api/url_book/crawl", methods=["POST"])
def crawl_url_book_api():
    payload = request.get_json(silent=True) or {}
    book_name = _normalize_pdf_name(payload.get("book_name") or "")
    if not book_name or not _is_url_book_name(book_name):
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
    profiles = load_site_profiles(CONFIG_FOLDER)
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
        app.logger.exception("URL book crawl failed")
        return jsonify({"status": "error", "message": f"クロール失敗: {str(e)}"}), 500

    added_count = 0
    for url in discovered:
        try:
            _, _, added = ensure_url_page_in_book(book_data, url, site_profile=profile)
            if added:
                added_count += 1
        except Exception as e:
            app.logger.warning(f"Failed to add URL {url}: {e}")
            continue

    nav_changed = _ensure_url_page_nav(book_data)
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


# API:PDFからbook_dataファイル生成
@app.route("/api/extract_paragraphs/<path:pdf_name>", methods=["POST"])
def create_book_data_api(pdf_name):
    if _is_url_book_name(pdf_name):
        return jsonify({"status": "error", "message": "URLブックはパラグラフ抽出不要です"}), 400
    
    pdf_path, json_path = get_paths(pdf_name)
    
    # リクエストボディから current_page を取得
    data = request.get_json(silent=True) or {}
    current_page = data.get("current_page")
    
    try:
        if os.path.exists(json_path):
            # 既存JSONがある場合：現在のページを再抽出
            if not current_page:
                return jsonify({"status": "error", "message": "current_page が指定されていません"}), 400
            
            try:
                page_number = int(current_page)
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": "current_page が不正です"}), 400
            
            reextract_page(pdf_path, json_path, page_number)
            return jsonify({"status": "ok", "message": f"ページ {page_number} を再抽出しました"}), 200
        else:
            # 新規抽出
            extract_paragraphs(pdf_path, json_path)
            return jsonify({"status": "ok", "message": "パラグラフ抽出完了"}), 200
    except Exception as e:
        app.logger.error(f"extract_paragraphs error: {str(e)}")
        return jsonify({"status": "error", "message": f"パラグラフ抽出エラー: {str(e)}"}), 500


# API:ファイル全翻訳
@app.route("/api/translate_all/<path:pdf_name>", methods=["POST"])
def translate_all_api(pdf_name):
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 400
    try:
        # 翻訳前に必ず文書全体へ対訳置換を適用
        _apply_dict_replace_for_range(pdf_name, json_path)

        _, stats = paraparatrans_json_file(json_path, 1, 9999)

        # settingsの該当PDF分だけ同期（PDFごとのjson_mtimeで追従）
        settings_path = os.path.join(DATA_FOLDER, "paraparatrans.settings.json")
        sync_one_pdf_settings_from_json(
            settings_path=settings_path,
            base_folder=BASE_FOLDER,
            pdf_name=pdf_name,
            indent=4,
        )
        return jsonify({"status": "ok", "stats": stats}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"全翻訳エラー: {str(e)}"}), 500

# API:短文翻訳
@app.route("/api/translate_engine", methods=["GET", "POST"])
def translate_engine_api():
    if request.method == "GET":
        return jsonify({
            "status": "ok",
            "engine": get_current_translator(),
            "supported": get_supported_translators(),
        }), 200

    data = request.get_json(silent=True) or {}
    requested = (data.get("engine") or "").strip().lower()
    if not requested:
        return jsonify({"status": "error", "message": "engineが指定されていません"}), 400

    try:
        active = set_current_translator(requested)
    except Exception as e:
        return jsonify({"status": "error", "message": f"翻訳エンジン切替エラー: {str(e)}"}), 400

    settings = _load_app_settings()
    settings["translator"] = active
    try:
        _save_app_settings(settings)
    except Exception as e:
        app.logger.warning(f"translator setting save failed: {str(e)}")

    return jsonify({
        "status": "ok",
        "engine": active,
        "supported": get_supported_translators(),
    }), 200


@app.route("/api/translate", methods=["POST"])
def translate_api():
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"status": "error", "message": "No text provided"}), 400

    text = data["text"]
    source = data.get("source", "EN")
    target = data.get("target", "JA")

    print(f"FOR DEBUG(LEFT50/1TRANS):{text[:50]}")

    try:
        translated_text = translate_text(text, source, target)
        print(f"FOR DEBUG(LEFT50/1TRANS):{translated_text[:50]}")
        return jsonify({"status": "ok", "translated_text": translated_text}), 200
    except Exception as e:
        app.logger.error(f"Translation error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# パラグラフの翻訳を保存するAPI
@app.route("/api/export_html/<path:pdf_name>", methods=["POST"])
def export_html_api(pdf_name):
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 400
    try:
        display_unit = request.form.get("display_unit") or "page"
        json2html(json_path, display_unit=display_unit)
    except Exception as e:
        return jsonify({"status": "error", "message": f"HTML生成エラー: {str(e)}"}), 500
    out_path = os.path.splitext(json_path)[0] + ".html"
    rel = os.path.relpath(out_path, APP_DIR)
    return jsonify({"status": "ok", "path": rel}), 200


@app.route("/api/download_html/<path:pdf_name>")
def download_html_api(pdf_name):
    """対訳HTMLをダウンロードする（無ければ生成して返す）。"""
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

    out_path = os.path.splitext(json_path)[0] + ".html"
    if not os.path.exists(out_path):
        try:
            display_unit = request.args.get("display_unit") or "page"
            json2html(json_path, display_unit=display_unit)
        except Exception as e:
            return jsonify({"status": "error", "message": f"HTML生成エラー: {str(e)}"}), 500

    try:
        return send_file(out_path, as_attachment=True, download_name=os.path.basename(out_path))
    except TypeError:
        # Flask の古い版互換 (download_name 未対応)
        return send_file(out_path, as_attachment=True)


def _structure_folder() -> str:
    folder = os.path.join(DATA_FOLDER, "structure")
    os.makedirs(folder, exist_ok=True)
    return folder


def _structure_path(pdf_name: str) -> str:
    # pdf_name は拡張子なしの前提（既存コードに合わせる）
    return os.path.join(_structure_folder(), f"{pdf_name}.structure.json")


@app.route("/api/export_structure/<path:pdf_name>", methods=["POST"])
def export_structure_api(pdf_name):
    """著作権配慮用の '文書構造ファイル' を出力する。

    - src_html/src_text/src_joined/src_replaced/trans_auto/trans_text を除去
    - data/structure/<pdf_name>.structure.json に保存
    """
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 400

    try:
        book_data = load_json(json_path)
        structure_data = structure_strip(book_data)
        out_path = _structure_path(pdf_name)
        atomicsave_json(out_path, structure_data)
        rel = os.path.relpath(out_path, APP_DIR)
        return jsonify({"status": "ok", "path": rel}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"構造ファイル出力エラー: {str(e)}"}), 500


@app.route("/api/export_text/<path:pdf_name>", methods=["POST"])
def export_text_api(pdf_name):
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 400

    payload = request.get_json(silent=True) or {}
    fmt = (payload.get("format") or "txt").lower().strip()
    fields = payload.get("fields") or []
    include_page_numbers = bool(payload.get("include_page_numbers", True))
    include_header = bool(payload.get("include_header", False))
    include_footer = bool(payload.get("include_footer", False))
    include_remove = bool(payload.get("include_remove", False))

    if fmt not in {"txt", "md"}:
        return jsonify({"status": "error", "message": "format は txt か md を指定してください"}), 400
    if not isinstance(fields, list):
        return jsonify({"status": "error", "message": "fields は配列で指定してください"}), 400

    allowed_fields = {"src_text", "src_joined", "src_replaced", "trans_auto", "trans_text"}
    fields = [f for f in fields if f in allowed_fields]
    if not fields or len(fields) > 2:
        return jsonify({"status": "error", "message": "fields は1〜2件で指定してください"}), 400

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        content = _build_text_export_content(
            book_data,
            fields,
            include_page_numbers=include_page_numbers,
            include_header=include_header,
            include_footer=include_footer,
            include_remove=include_remove,
            fmt=fmt,
        )
        out_path = os.path.splitext(json_path)[0] + f".{fmt}"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        rel = os.path.relpath(out_path, APP_DIR)
        return jsonify({"status": "ok", "path": rel}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"テキスト出力エラー: {str(e)}"}), 500


@app.route("/api/download_text/<path:pdf_name>/<string:fmt>")
def download_text_api(pdf_name, fmt: str):
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

    fmt = (fmt or "txt").lower().strip()
    if fmt not in {"txt", "md"}:
        return jsonify({"status": "error", "message": "format は txt か md を指定してください"}), 400

    out_path = os.path.splitext(json_path)[0] + f".{fmt}"
    if not os.path.exists(out_path):
        return jsonify({"status": "error", "message": "出力ファイルが存在しません"}), 404

    try:
        return send_file(out_path, as_attachment=True, download_name=os.path.basename(out_path))
    except TypeError:
        return send_file(out_path, as_attachment=True)


@app.route("/api/download_structure/<path:pdf_name>")
def download_structure_api(pdf_name):
    """既存の文書構造ファイルをダウンロードする（無ければ生成して返す）。"""
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

    out_path = _structure_path(pdf_name)
    if not os.path.exists(out_path):
        try:
            book_data = load_json(json_path)
            structure_data = structure_strip(book_data)
            atomicsave_json(out_path, structure_data)
        except Exception as e:
            return jsonify({"status": "error", "message": f"構造ファイル生成エラー: {str(e)}"}), 500

    try:
        return send_file(out_path, as_attachment=True, download_name=os.path.basename(out_path))
    except TypeError:
        # Flask の古い版互換 (download_name 未対応)
        return send_file(out_path, as_attachment=True)


@app.route("/api/download_extension/chrome")
def download_chrome_extension_api():
    """Chrome/Edge用ローカル拡張をZIPでダウンロードする。"""
    ext_dir = os.path.join(APP_DIR, "tools", "chrome_extension_paraparatrans")
    if not os.path.isdir(ext_dir):
        return jsonify({"status": "error", "message": "拡張フォルダが見つかりません"}), 404

    zip_buffer = io.BytesIO()
    root_name = "chrome_extension_paraparatrans"

    try:
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for folder, _, files in os.walk(ext_dir):
                rel_folder = os.path.relpath(folder, ext_dir)
                for file_name in files:
                    abs_path = os.path.join(folder, file_name)
                    rel_path = os.path.join(rel_folder, file_name) if rel_folder != "." else file_name
                    arcname = os.path.join(root_name, rel_path)
                    zf.write(abs_path, arcname)

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name="chrome_extension_paraparatrans.zip",
            mimetype="application/zip",
        )
    except TypeError:
        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            as_attachment=True,
            attachment_filename="chrome_extension_paraparatrans.zip",
            mimetype="application/zip",
        )


@app.route("/api/import_structure/<path:pdf_name>", methods=["POST"])
def import_structure_api(pdf_name):
    """文書構造ファイルを取り込み、既存JSONの構造情報のみ更新する。

    - 更新前に data/backup に元JSONを複写
    - src_html/src_text/src_joined/src_replaced/trans_auto/trans_text は更新しない
    - join が変化した場合は src_joined/src_replaced を再構築する
    """
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 400

    imported = None

    upfile = request.files.get("file")
    if upfile and getattr(upfile, "filename", ""):
        try:
            imported = structure_load_json_from_upload(upfile)
        except Exception as e:
            return jsonify({"status": "error", "message": f"アップロードJSONの読み取りに失敗: {str(e)}"}), 400
    else:
        # JSONボディでも受け取れるようにする
        imported = request.get_json(silent=True)

    if not isinstance(imported, dict):
        return jsonify({"status": "error", "message": "取り込みデータが不正です（JSON object ではありません）"}), 400

    try:
        book_data = load_json(json_path)

        backup_path = structure_ensure_backup_copy(json_path, backup_dir=os.path.join(DATA_FOLDER, "backup"))

        book_data, stats, join_changed = structure_merge_into_book(book_data, imported)

        # join が変わった場合は派生項目を再構築（src_joined/src_replaced/trans_status が変化し得る）
        if join_changed:
            join_apply_all(book_data, sep="", normalize_head=True)

        # trans_status などが変わる可能性があるので再集計
        recalc_trans_status_counts(book_data)

        atomicsave_json(json_path, book_data)
        return jsonify(
            {
                "status": "ok",
                "backup": os.path.relpath(backup_path, APP_DIR),
                "stats": stats,
                "join_changed": bool(join_changed),
                "trans_status_counts": book_data.get("trans_status_counts"),
            }
        ), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"構造ファイル取り込みエラー: {str(e)}"}), 500


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


def _apply_dict_replace_for_range(pdf_name: str, json_path: str, start_page: int | None = None, end_page: int | None = None):
    dict_paths = dict_service.get_active_dict_paths(pdf_name)
    merged_path = dict_service.merged_dict_file(dict_paths)
    try:
        if start_page is None or end_page is None:
            return file_replace_with_dict(json_path, merged_path)
        return file_replace_with_dict(json_path, merged_path, start_page, end_page)
    finally:
        try:
            os.remove(merged_path)
        except OSError:
            pass

@app.route("/api/paraparatrans/<path:pdf_name>", methods=["POST"])
def paraparatrans_api(pdf_name):
    start_page = request.form.get("start_page", type=int)
    end_page = request.form.get("end_page", type=int)
    if not pdf_name or start_page is None or end_page is None:
        return jsonify({"status": "error", "message": "pdf_name, start_page, end_page は必須です"}), 400
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "対象のJSONファイルが存在しません"}), 404

    print ("json_path:" + json_path + " start_page:" + str(start_page) + " end_page:" + str(end_page))
    try:
        # 翻訳対象範囲に必ず対訳置換を適用してから翻訳する
        _apply_dict_replace_for_range(pdf_name, json_path, start_page, end_page)

        updated_data, stats = paraparatrans_json_file(json_path, start_page, end_page)

        # 差分返却: 更新対象ページのみ返す（クライアント側で bookData にマージして全体再取得を避ける）
        pages_delta = {}
        pages = updated_data.get("pages", {})
        for page in range(start_page, end_page + 1):
            key = str(page)
            if key in pages:
                pages_delta[key] = pages[key]

        delta = {
            "pages": pages_delta,
            "trans_status_counts": updated_data.get("trans_status_counts"),
        }

        # settingsの該当PDF分だけ同期（翻訳数表示の追従）
        settings_path = os.path.join(DATA_FOLDER, "paraparatrans.settings.json")
        sync_one_pdf_settings_from_json(
            settings_path=settings_path,
            base_folder=BASE_FOLDER,
            pdf_name=pdf_name,
            indent=4,
        )
        # 互換のため data も残す（旧クライアントは全体更新前提だったが、現状 data は未使用）
        return jsonify({"status": "ok", "delta": delta, "data": delta, "stats": stats}), 200
    except Exception as e:
        app.logger.error(f"翻訳処理中にエラーが発生しました: {str(e)}")
        return jsonify({"status": "error", "message": f"翻訳処理中にエラーが発生しました: {str(e)}"}), 500


@app.route("/api/align_trans_by_src_joined/<path:pdf_name>", methods=["POST"])
def align_trans_by_src_joined_api(pdf_name):
    """同一 src_joined の訳を、より上位 trans_status の訳へ揃える。"""
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "対象のJSONファイルが存在しません"}), 404

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        _, changed, pages_changed = align_translations_by_src_joined_collect_pages(book_data)
        recalc_trans_status_counts(book_data)
        atomicsave_json(json_path, book_data)

        pages_delta = {}
        pages = book_data.get("pages", {}) or {}
        for key in pages_changed:
            if key in pages:
                pages_delta[key] = pages[key]

        delta = {
            "pages": pages_delta,
            "trans_status_counts": book_data.get("trans_status_counts"),
        }

        return jsonify(
            {
                "status": "ok",
                "changed": changed,
                "trans_status_counts": book_data.get("trans_status_counts"),
                "delta": delta,
            }
        ), 200
    except Exception as e:
        app.logger.error(f"訳揃え処理中にエラーが発生しました: {str(e)}")
        return jsonify({"status": "error", "message": f"訳揃え処理中にエラーが発生しました: {str(e)}"}), 500

# APIW:book_data取得
@app.route("/api/reload_book_data/<path:pdf_name>", methods=["GET"])
def reload_book_data_api(pdf_name):
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404
    with open(json_path, "r", encoding="utf-8") as f:
        book_data = json.load(f)
    return jsonify(book_data), 200

@app.route("/pdf_view/<path:pdf_name>")
def pdf_view(pdf_name):
    pdf_path, _ = get_paths(pdf_name)
    if not os.path.exists(pdf_path):
        app.logger.error(f"File not found: {pdf_path}")
        return "PDFファイルが見つかりません", 404

    # BytesIO を返すと Range/条件付きリクエストが効かず PDF.js が遅くなりがちなので、
    # 実ファイルパスを send_file で返してブラウザ側キャッシュ/Range を活かす。
    resp = send_file(pdf_path, as_attachment=False, conditional=True)
    try:
        resp.cache_control.public = True
        resp.cache_control.max_age = 3600
    except Exception:
        pass
    return resp

# PDFの指定ページを表示するAPI
@app.route("/pdf_view/<path:pdf_name>/<int:page_number>")
def pdf_view_page(pdf_name, page_number):
    pdf_path, _ = get_paths(pdf_name)
    if not os.path.exists(pdf_path):
        app.logger.error(f"File not found: {pdf_path}")
        return "PDFファイルが見つかりません", 404
    with open(pdf_path, "rb") as f:
        reader = PdfReader(f)
        if page_number < 1 or page_number > len(reader.pages):
            return "ページが存在しません", 404
        writer = PdfWriter()
        writer.add_page(reader.pages[page_number - 1])
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        safe_name = os.path.splitext(os.path.basename(pdf_path))[0]
        return send_file(output, download_name=f"{safe_name}_page_{page_number}.pdf", as_attachment=False)


@app.route("/api/save_order/<path:pdf_name>", methods=["POST"])
def save_order_api(pdf_name):
    order_json = request.form.get("order_json")
    title = request.form.get("title")
    
    if not pdf_name or not order_json:
        return jsonify({"status": "error", "message": "pdf_name と order_json は必須です"}), 400

    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONが存在しません"}), 404

    with open(json_path, "r", encoding="utf-8") as f:
        book_data = json.load(f)

    new_order = json.loads(order_json) # new_order は配列のままと想定
    paragraphs_dict = book_data.get("paragraphs", {}) # 辞書として取得

    changed_count = 0
    last_processed_item = {} # 保存時のログ表示用

    for item in new_order:
        page_number = str(item.get("page_number"))
        p_id_str = str(item.get("id"))
        new_order_val = item.get("order")
        new_block_tag = item.get("block_tag")
        new_group_id = item.get("group_id")
        new_join = item.get("join", 0)
        last_processed_item = item # ログ用に保持

        print (f"  Found ID: {p_id_str}, Current Order: {p.get('order')}, Block Tag: {p.get('block_tag')}, Group ID: {p.get('group_id')}, Join: {p.get('join')}")
        print(f"Processing ID: {p_id_str}, Order: {new_order_val}, Block Tag: {new_block_tag}, Group ID: {new_group_id}, Join: {new_join}")

        p = book_data["pages"][page_number]["paragraphs"][p_id_str]
        updated = False
        if p.get("order") != new_order_val:
            p["order"] = new_order_val
            updated = True
        if new_block_tag is not None and p.get("block_tag") != new_block_tag:
            p["block_tag"] = new_block_tag
            updated = True
        if new_group_id is not None and p.get("group_id") != new_group_id:
            p["group_id"] = new_group_id
            updated = True
        if new_join is not None and p.get("join") != new_join:
            p["join"] = new_join
            updated = True
        if updated:
            changed_count += 1
            print(f"  Updated ID: {p_id_str}")

    if title is not None and book_data.get("title") != title:
        book_data["title"] = title
        changed_count += 1
        print("Title updated.")

    if changed_count > 0:
        temp_file = f"{json_path}.{uuid.uuid4().hex}.tmp"  # ユニークな一時ファイル名を生成
        try:
            # 保存時のログは最後に処理したアイテム情報を使う (ループ変数はスコープ外になる可能性があるため)
            log_p_id = str(last_processed_item.get("id", "N/A"))
            log_order = last_processed_item.get("order", "N/A")
            log_block_tag = last_processed_item.get("block_tag", "N/A")
            log_group_id = last_processed_item.get("group_id", "N/A")
            log_join = last_processed_item.get("join", "N/A")
            print(f"Writing changes to file. Last processed item for logging - ID: {log_p_id}, Order: {log_order}, Block Tag: {log_block_tag}, Group ID: {log_group_id}, Join: {log_join}")

            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(book_data, f, ensure_ascii=False, indent=2) # book_data["paragraphs"] は辞書のまま保存
            os.replace(temp_file, json_path)  # アトミックにリネーム
        except Exception as e:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return jsonify({"status": "error", "message": f"保存中のエラー: {str(e)}"}), 500

    return jsonify({"status": "ok", "changed": changed_count}), 200


@app.route("/api/auto_tagging/<path:pdf_name>", methods=["POST"])
def auto_tagging_api(pdf_name):
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404
    try:
        current_page = request.form.get("current_page", type=int)
        structure_tagging(json_path, SIMBLE_DICT_PATH)
        join_flags_in_file(json_path, SIMBLE_DICT_PATH)

        delta = None
        if current_page is not None:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
            page_key = str(current_page)
            page_obj = (book_data.get("pages", {}) or {}).get(page_key)
            if page_obj is not None:
                delta = {
                    "pages": {page_key: page_obj},
                    "trans_status_counts": book_data.get("trans_status_counts"),
                }

    except Exception as e:
        return jsonify({"status": "error", "message": f"自動タグ付けエラー: {str(e)}"}), 500
    return jsonify({"status": "ok", "message": "自動タグ付け完了", "delta": delta}), 200


@app.route("/api/rebuild_src_text/<path:pdf_name>", methods=["POST"])
def rebuild_src_text_api(pdf_name):
    """src_html から src_text を再生成し、シンボル置換（symbolfont_dict）を適用する。"""
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404

    try:
        current_page = request.form.get("current_page", type=int)
        changed = rebuild_src_text_in_file(json_path, SYMBOLFONT_DICT_PATH)
    except Exception as e:
        return jsonify({"status": "error", "message": f"シンボル置換エラー: {str(e)}"}), 500

    delta = None
    if current_page is not None:
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        page_key = str(current_page)
        page_obj = (book_data.get("pages", {}) or {}).get(page_key)
        if page_obj is not None:
            delta = {
                "pages": {page_key: page_obj},
                "trans_status_counts": book_data.get("trans_status_counts"),
            }

    return jsonify({"status": "ok", "message": f"シンボル置換完了 (更新: {changed}段落)", "changed": changed, "delta": delta}), 200

# API: スタイルによるblock_tag一括更新
@app.route("/api/update_block_tags_by_style/<path:pdf_name>", methods=["POST"])
def update_block_tags_by_style_api(pdf_name):
    data = request.get_json()
    target_style = data.get("target_style")
    target_tag = data.get("target_tag")
    current_page = data.get("current_page")

    if not target_style or not target_tag:
        return jsonify({"status": "error", "message": "target_style と target_tag は必須です"}), 400

    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404

    try:
        # parapara_tagging_by_style.py の関数を呼び出す
        tag_paragraphs_by_style(json_path, target_style, target_tag)

        delta = None
        if current_page is not None:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
            page_key = str(int(current_page))
            page_obj = (book_data.get("pages", {}) or {}).get(page_key)
            if page_obj is not None:
                delta = {
                    "pages": {page_key: page_obj},
                    "trans_status_counts": book_data.get("trans_status_counts"),
                }

        # 成功レスポンスを返す
        return jsonify({"status": "ok", "message": "スタイルによるblock_tag一括更新が完了しました", "delta": delta}), 200

    except Exception as e:
        app.logger.error(f"スタイルによるblock_tag一括更新エラー: {str(e)}")
        return jsonify({"status": "error", "message": f"スタイルによるblock_tag一括更新エラー: {str(e)}"}), 500


# API: スタイル + Y範囲による block_tag 更新（header/footer/remove）
@app.route("/api/update_block_tags_by_style_y/<path:pdf_name>", methods=["POST"])
def update_block_tags_by_style_y_api(pdf_name):
    data = request.get_json() or {}
    target_style = data.get("target_style")
    y0 = data.get("y0")
    y1 = data.get("y1")
    action = data.get("action")
    current_page = data.get("current_page")

    if not target_style:
        return jsonify({"status": "error", "message": "target_style は必須です"}), 400
    if y0 is None or y1 is None:
        return jsonify({"status": "error", "message": "y0 と y1 は必須です"}), 400
    if action not in ["header", "footer", "remove"]:
        return jsonify({"status": "error", "message": "action は header/footer/remove のいずれかです"}), 400

    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404

    try:
        changed = tag_paragraphs_by_style_y_in_file(json_path, target_style, float(y0), float(y1), action)

        delta = None
        if current_page is not None:
            with open(json_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
            page_key = str(int(current_page))
            page_obj = (book_data.get("pages", {}) or {}).get(page_key)
            if page_obj is not None:
                delta = {
                    "pages": {page_key: page_obj},
                    "trans_status_counts": book_data.get("trans_status_counts"),
                }

        return jsonify({"status": "ok", "message": f"更新しました (変更: {changed}段落)", "changed": changed, "delta": delta}), 200
    except Exception as e:
        app.logger.error(f"スタイル+Y範囲によるblock_tag一括更新エラー: {str(e)}")
        return jsonify({"status": "error", "message": f"スタイル+Y範囲によるblock_tag一括更新エラー: {str(e)}"}), 500


@app.route("/api/join_replaced_paragraphs/<path:pdf_name>", methods=["POST"])
def auto_join_replaced_paragraphs_api(pdf_name):
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404
    try:
        current_page = request.form.get("current_page", type=int)
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)

        join_apply_all(book_data, sep="", normalize_head=True)
        recalc_trans_status_counts(book_data)
        atomicsave_json(json_path, book_data)

        delta = None
        if current_page is not None:
            page_key = str(current_page)
            page_obj = (book_data.get("pages", {}) or {}).get(page_key)
            if page_obj is not None:
                delta = {
                    "pages": {page_key: page_obj},
                    "trans_status_counts": book_data.get("trans_status_counts"),
                }
    except Exception as e:
        return jsonify({"status": "error", "message": f"置換文結合エラー: {str(e)}"}), 500
    return jsonify(
        {
            "status": "ok",
            "message": "置換文結合完了",
            "trans_status_counts": book_data.get("trans_status_counts"),
            "delta": delta,
        }
    ), 200


@app.route("/api/reextract_table_from_selection/<path:pdf_name>", methods=["POST"])
def reextract_table_from_selection_api(pdf_name):
    if _is_url_book_name(pdf_name):
        return jsonify({"status": "error", "message": "URLブックは対象外です"}), 400

    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404
    if not os.path.exists(pdf_path):
        return jsonify({"status": "error", "message": "PDFファイルが存在しません"}), 404

    data = request.get_json(silent=True) or {}
    page_number = data.get("current_page") or data.get("page_number")
    rows = data.get("rows")
    cols = data.get("cols")
    header_text = data.get("header_text")
    paragraph_ids = data.get("paragraph_ids") or []
    desired_rows = data.get("rows")
    desired_cols = data.get("cols")
    header_text = data.get("header_text")

    try:
        desired_rows = int(desired_rows) if desired_rows is not None and str(desired_rows).strip() else None
    except Exception:
        desired_rows = None

    try:
        desired_cols = int(desired_cols) if desired_cols is not None and str(desired_cols).strip() else None
    except Exception:
        desired_cols = None

    try:
        page_number = int(page_number)
    except Exception:
        return jsonify({"status": "error", "message": "current_page が不正です"}), 400

    if page_number <= 0:
        return jsonify({"status": "error", "message": "current_page は1以上で指定してください"}), 400

    if not isinstance(paragraph_ids, list):
        return jsonify({"status": "error", "message": "paragraph_ids は配列で指定してください"}), 400

    paragraph_ids = [str(pid).strip() for pid in paragraph_ids if str(pid).strip()]
    if len(paragraph_ids) < 1:
        return jsonify({"status": "error", "message": "1行以上選択してください"}), 400

    page_key = str(page_number)

    try:
        book_data = load_json(json_path)
        page_obj = (book_data.get("pages", {}) or {}).get(page_key)
        if not isinstance(page_obj, dict):
            return jsonify({"status": "error", "message": "対象ページが見つかりません"}), 404

        page_paragraphs = page_obj.get("paragraphs", {}) or {}

        available_ids = [pid for pid in paragraph_ids if pid in page_paragraphs]
        if len(available_ids) < 1:
            return jsonify({"status": "error", "message": "選択段落が見つかりません"}), 404

        table_id = f"p{page_number}_{uuid.uuid4().hex[:8]}"

        with fitz.open(pdf_path) as doc:
            page_index = page_number - 1
            if page_index < 0 or page_index >= len(doc):
                return jsonify({"status": "error", "message": "対象ページ番号が範囲外です"}), 400

            page = doc[page_index]
            added = append_markdown_table_rows_from_selection(
                page=page,
                page_number=page_number,
                page_paragraphs=page_paragraphs,
                paragraph_ids=available_ids,
                table_id=table_id,
                rows=rows,
                cols=cols,
                header_text=header_text,
            )

        if added <= 0:
            return jsonify({"status": "error", "message": "再抽出結果が0件でした"}), 200

        recalc_trans_status_counts(book_data)
        atomicsave_json(json_path, book_data)

        delta = {
            "pages": {page_key: (book_data.get("pages", {}) or {}).get(page_key)},
            "trans_status_counts": book_data.get("trans_status_counts"),
        }
        return jsonify(
            {
                "status": "ok",
                "message": f"テーブル行を{added}件追加しました",
                "added": added,
                "delta": delta,
            }
        ), 200
    except Exception as e:
        app.logger.error(f"table reextract error: {str(e)}")
        return jsonify({"status": "error", "message": f"テーブル再抽出エラー: {str(e)}"}), 500


@app.route("/api/table_grid_suggest/<path:pdf_name>", methods=["POST"])
def table_grid_suggest_api(pdf_name):
    if _is_url_book_name(pdf_name):
        return jsonify({"status": "error", "message": "URLブックは対象外です"}), 400

    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404
    if not os.path.exists(pdf_path):
        return jsonify({"status": "error", "message": "PDFファイルが存在しません"}), 404

    data = request.get_json(silent=True) or {}
    page_number = data.get("current_page") or data.get("page_number")
    paragraph_ids = data.get("paragraph_ids") or []
    desired_rows = data.get("rows")
    desired_cols = data.get("cols")
    header_text = data.get("header_text")

    try:
        desired_rows = int(desired_rows) if desired_rows is not None and str(desired_rows).strip() else None
    except Exception:
        desired_rows = None

    try:
        desired_cols = int(desired_cols) if desired_cols is not None and str(desired_cols).strip() else None
    except Exception:
        desired_cols = None

    try:
        page_number = int(page_number)
    except Exception:
        return jsonify({"status": "error", "message": "current_page が不正です"}), 400

    if page_number <= 0:
        return jsonify({"status": "error", "message": "current_page は1以上で指定してください"}), 400

    if not isinstance(paragraph_ids, list):
        return jsonify({"status": "error", "message": "paragraph_ids は配列で指定してください"}), 400

    paragraph_ids = [str(pid).strip() for pid in paragraph_ids if str(pid).strip()]
    if len(paragraph_ids) < 1:
        return jsonify({"status": "error", "message": "1行以上選択してください"}), 400

    page_key = str(page_number)

    try:
        book_data = load_json(json_path)
        page_obj = (book_data.get("pages", {}) or {}).get(page_key)
        if not isinstance(page_obj, dict):
            return jsonify({"status": "error", "message": "対象ページが見つかりません"}), 404

        page_paragraphs = page_obj.get("paragraphs", {}) or {}
        available_ids = [pid for pid in paragraph_ids if pid in page_paragraphs]
        if len(available_ids) < 1:
            return jsonify({"status": "error", "message": "選択段落が見つかりません"}), 404

        with fitz.open(pdf_path) as doc:
            page_index = page_number - 1
            if page_index < 0 or page_index >= len(doc):
                return jsonify({"status": "error", "message": "対象ページ番号が範囲外です"}), 400

            page = doc[page_index]
            suggestion = suggest_table_shape_for_selection(
                page=page,
                page_paragraphs=page_paragraphs,
                paragraph_ids=available_ids,
                desired_rows=desired_rows,
                desired_cols=desired_cols,
                header_text=str(header_text).strip() if header_text else None,
            )

        if not suggestion.get("ok"):
            return jsonify({"status": "error", "message": suggestion.get("message") or "推測に失敗しました"}), 200

        return jsonify(
            {
                "status": "ok",
                "rows": suggestion.get("rows"),
                "cols": suggestion.get("cols"),
                "clip_rect": suggestion.get("clip_rect"),
                "preview_cell_rects": suggestion.get("preview_cell_rects") or [],
                "header_text": suggestion.get("header_text") or "",
            }
        ), 200
    except Exception as e:
        app.logger.error(f"table grid suggest error: {str(e)}")
        return jsonify({"status": "error", "message": f"テーブルグリッド推測エラー: {str(e)}"}), 500

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

@app.route("/api/update_book_info/<path:pdf_name>", methods=["POST"])
def update_book_info_api(pdf_name):
    settings_path = os.path.join(DATA_FOLDER, "paraparatrans.settings.json")
    
    # settingsファイルが存在しない場合はエラーを返す
    if not os.path.exists(settings_path):
        return jsonify({"status": "error", "message": "settingsファイルが存在しません"}), 404

    # リクエストからデータを取得
    data = request.get_json()
    new_title = data.get("title")
    new_page_count = data.get("page_count")
    new_trans_status_counts = data.get("trans_status_counts")

    if not new_title:
        return jsonify({"status": "error", "message": "titleが指定されていません"}), 400

    try:
        # settingsファイルを読み込む
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)

        # 指定されたPDF名が存在するか確認
        if pdf_name not in settings["files"]:
            return jsonify({"status": "error", "message": f"{pdf_name}がsettingsに存在しません"}), 404

        # タイトルを更新
        settings["files"][pdf_name]["title"] = new_title

        # ページ数を更新
        if new_page_count is not None:
            settings["files"][pdf_name]["page_count"] = new_page_count

        # 翻訳ステータスカウントを更新
        if new_trans_status_counts is not None:
            settings["files"][pdf_name]["trans_status_counts"] = new_trans_status_counts

        # 更新内容をファイルに書き込む
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

        return jsonify({"status": "ok", "message": "文書情報が更新されました"}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"文書情報更新中にエラーが発生しました: {str(e)}"}), 500

def recalc_trans_status_counts(book_data):
    counts = {"none": 0, "auto": 0, "draft": 0, "fixed": 0}
    pages_dict = book_data.get("pages", {})  # ページ辞書を取得
    for page_id, page in pages_dict.items():
        paragraphs_dict = page.get("paragraphs", {})
        for p in paragraphs_dict.values():
            st = p.get("trans_status", "none")
            if st in counts:
                counts[st] += 1
            else:
                counts["none"] += 1
                print(f"Warning: Unknown trans_status '{st}' found in paragraph ID {p.get('id', 'N/A')} on page {page_id}. Counted as 'none'.")
    book_data["trans_status_counts"] = counts


_TRANS_STATUS_KEYS = ("none", "auto", "draft", "fixed")


def _normalize_trans_status(status):
    if status in _TRANS_STATUS_KEYS:
        return status
    return "none"


def ensure_trans_status_counts(book_data):
    """book_data["trans_status_counts"] を差分更新できる形に正規化する。"""
    counts = book_data.get("trans_status_counts")
    if not isinstance(counts, dict):
        counts = {}
    normalized = {}
    for k in _TRANS_STATUS_KEYS:
        v = counts.get(k, 0)
        try:
            normalized[k] = int(v)
        except Exception:
            normalized[k] = 0
    book_data["trans_status_counts"] = normalized
    return normalized


def is_trans_status_counts_usable_for_delta(book_data) -> bool:
    counts = book_data.get("trans_status_counts")
    if not isinstance(counts, dict):
        return False
    return all(k in counts for k in _TRANS_STATUS_KEYS)


def apply_trans_status_delta(book_data, old_status, new_status):
    """trans_status の変更分だけ trans_status_counts を更新する（全件再集計を避ける）。"""
    counts = ensure_trans_status_counts(book_data)
    old_s = _normalize_trans_status(old_status)
    new_s = _normalize_trans_status(new_status)
    if old_s == new_s:
        return

    # 念のため負数は避ける（counts が古い/壊れていても暴走しないように）
    counts[old_s] = max(0, counts.get(old_s, 0) - 1)
    counts[new_s] = counts.get(new_s, 0) + 1

# 単パラグラフの翻訳を保存するAPI
@app.route("/api/update_paragraph/<path:pdf_name>", methods=["POST"])
def update_paragraph_api(pdf_name):
    data = request.get_json()
    page_number = str(data.get("page_number"))
    id = str(data["id"])
    new_src_text = data["src_text"]
    new_trans_auto = data["trans_auto"]
    new_trans_text = data["trans_text"]
    new_comment = data.get("comment")
    new_status = data["trans_status"]
    new_block_tag = data["block_tag"]
    new_join = data.get("join")
    new_markup = data.get("markup")

    print("update_paragraph_api:" + json.dumps(data, indent=2, ensure_ascii=False))

    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "(update_paragraph_api 1)JSONが存在しません"}), 400

    book_data = load_json(json_path)

    paragraph = book_data["pages"][page_number]["paragraphs"][id]
    if not paragraph:
        return jsonify({"status": "error", "message": "(update_paragraph_api 2)該当パラグラフが見つかりません"}), 404

    # trans_status_counts は全件再集計だと重いので、基本は変更分だけ更新する。
    # ただし counts が欠損/破損している場合は、最後に1回だけ再集計する。
    old_status = paragraph.get("trans_status", "none")
    old_status_norm = _normalize_trans_status(old_status)
    can_delta = is_trans_status_counts_usable_for_delta(book_data)
    if can_delta:
        # これから old_status を 1 減らすので、0 以下は不整合とみなして再集計へ
        try:
            if int(book_data["trans_status_counts"].get(old_status_norm, 0)) <= 0:
                can_delta = False
        except Exception:
            can_delta = False

    old_src_text = "" if paragraph.get("src_text") is None else str(paragraph.get("src_text"))
    new_src_text_norm = "" if new_src_text is None else str(new_src_text)

    paragraph["src_text"] = new_src_text_norm
    if old_src_text != new_src_text_norm:
        paragraph["src_joined"] = new_src_text_norm
        paragraph["src_replaced"] = new_src_text_norm
    paragraph["trans_auto"] = new_trans_auto
    paragraph["trans_text"] = new_trans_text
    if new_comment is not None:
        paragraph["comment"] = new_comment
    paragraph["trans_status"] = new_status
    paragraph["block_tag"] = new_block_tag
    if isinstance(new_markup, list):
        paragraph["markup"] = new_markup

    join_changed = False
    if new_join is not None:
        try:
            desired_join = 1 if int(new_join) == 1 else 0
        except Exception:
            desired_join = 0
        old_join = 1 if int(paragraph.get("join", 0)) == 1 else 0
        if old_join != desired_join:
            refs = join_iter_paragraph_refs(book_data)
            index = join_build_index(refs)
            join_apply_change(
                book_data,
                (page_number, id),
                desired_join,
                refs=refs,
                index=index,
                sep="",
                normalize_head=True,
            )
            join_changed = True

            # 既存データ互換: join=0 はキーごと消す運用
            if desired_join == 0:
                try:
                    if "join" in paragraph:
                        del paragraph["join"]
                except Exception:
                    pass

    paragraph["modified_at"] = datetime.datetime.now().isoformat()

    # join が変わると複数段落の trans_status が変わり得るので、カウントは再集計する
    if join_changed:
        recalc_trans_status_counts(book_data)
        can_delta = False
    elif can_delta:
        apply_trans_status_delta(book_data, old_status, new_status)
    else:
        recalc_trans_status_counts(book_data)

    try:
        atomicsave_json(json_path, book_data)  # アトミックセーブ
        return jsonify(
            {
                "status": "ok",
                "trans_status_counts": book_data.get("trans_status_counts"),
                "reload_book_data": bool(join_changed),
            }
        ), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message:": "(update_paragraph_api 3)" + str(ve)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"(update_paragraph_api 4): {str(e)}"}), 500


# 複数パラグラフを更新するAPI
@app.route("/api/update_paragraphs/<path:pdf_name>", methods=["POST"])
def update_paragraphs_api(pdf_name):
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404

    # requestはpage,idを付加されたparagraphs
    # request-title
    #         paragraphs[]
    request_data = request.get_json()
    if not request_data or "title" not in request_data:
        return jsonify({"status": "error", "message": "title がありません"}), 400

    print("update_paragraphs_api:" + json.dumps(request_data, indent=2, ensure_ascii=False))

    try:
        book_data = load_json(json_path)  # JSONファイルを読み込む

        request_title = request_data.get("title")
        if request_title is not None:
            book_data["title"] = request_title


        def apply_update(p, upd_value): # 第2引数は更新内容のオブジェクト
            # デバッグ用にupd_valueをprint
            # print(json.dumps(upd_value, indent=2, ensure_ascii=False))

            p["modified_at"] = datetime.datetime.now().isoformat()
            p["src_text"] = upd_value.get("src_text", p.get("src_text"))
            p["trans_text"] = upd_value.get("trans_text", p.get("trans_text"))
            p["comment"] = upd_value.get("comment", p.get("comment", ""))
            p["trans_status"] = upd_value.get("trans_status", p.get("trans_status"))
            p["order"] = upd_value.get("order", p.get("order"))
            p["block_tag"] = upd_value.get("block_tag", p.get("block_tag"))

            group_id = upd_value.get("group_id", None)
            # group_idがparagraphs_dictに存在しない場合は、group_idを削除
            if group_id is not None:
                p["group_id"] = group_id
            elif "group_id" in p:
                del p["group_id"]  # group_idを削除

            # join は波及更新が必要なので、ここでは触らない（後段で join_apply_change する）

        join_updates = []  # (page_number(str), id(str), desired_join(0/1))

        # 差分更新ができる場合は差分で、無理なら最後に1回だけ再集計する
        can_delta = is_trans_status_counts_usable_for_delta(book_data)
        if can_delta:
            ensure_trans_status_counts(book_data)

        request_paragraphs = request_data.get("paragraphs")
        for request_paragraph in request_paragraphs:
            page_number = str(request_paragraph.get("page_number"))
            id = str(request_paragraph.get("id"))
            # print(f"page:{page_number} id:{id}")
            paragraph_dict = book_data["pages"][page_number]["paragraphs"][id]

            desired_join = 1 if request_paragraph.get("join") == 1 else 0
            old_join = 1 if int(paragraph_dict.get("join", 0)) == 1 else 0
            if old_join != desired_join:
                join_updates.append((page_number, id, desired_join))

            old_status = paragraph_dict.get("trans_status", "none")
            if can_delta:
                old_status_norm = _normalize_trans_status(old_status)
                try:
                    if int(book_data["trans_status_counts"].get(old_status_norm, 0)) <= 0:
                        can_delta = False
                except Exception:
                    can_delta = False
            apply_update(paragraph_dict, request_paragraph)
            new_status = paragraph_dict.get("trans_status", "none")
            if can_delta:
                apply_trans_status_delta(book_data, old_status, new_status)

        join_changed = False
        if join_updates:
            refs = join_iter_paragraph_refs(book_data)
            index = join_build_index(refs)
            for page_number, id, desired_join in join_updates:
                join_apply_change(
                    book_data,
                    (page_number, id),
                    desired_join,
                    refs=refs,
                    index=index,
                    sep="",
                    normalize_head=True,
                )
                join_changed = True

                # 既存データ互換: join=0 はキーごと消す
                if desired_join == 0:
                    try:
                        p = book_data["pages"][page_number]["paragraphs"][id]
                        if "join" in p:
                            del p["join"]
                    except Exception:
                        pass

        # join が変わると複数段落の trans_status が変わり得るので、カウントは再集計する
        if join_changed:
            recalc_trans_status_counts(book_data)
            can_delta = False
        elif not can_delta:
            recalc_trans_status_counts(book_data)

        atomicsave_json(json_path, book_data)
        return jsonify(
            {
                "status": "ok",
                "trans_status_counts": book_data.get("trans_status_counts"),
                "reload_book_data": bool(join_changed),
            }
        ), 200

    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"更新中にエラーが発生しました: {str(e)}"}), 500


@app.route("/api/delete_paragraphs/<path:pdf_name>", methods=["POST"])
def delete_paragraphs_api(pdf_name):
    """選択したパラグラフを削除"""
    pdf_path, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404

    request_data = request.get_json()
    if not request_data or "paragraphs" not in request_data:
        return jsonify({"status": "error", "message": "paragraphs がありません"}), 400

    try:
        book_data = load_json(json_path)
        request_paragraphs = request_data.get("paragraphs")
        
        if not request_paragraphs:
            return jsonify({"status": "error", "message": "削除対象がありません"}), 400

        deleted_count = 0
        for request_paragraph in request_paragraphs:
            page_number = str(request_paragraph.get("page_number"))
            paragraph_id = str(request_paragraph.get("id"))
            
            if page_number not in book_data["pages"]:
                continue
            
            page_paragraphs = book_data["pages"][page_number]["paragraphs"]
            if paragraph_id in page_paragraphs:
                del page_paragraphs[paragraph_id]
                deleted_count += 1

        # trans_status_counts を再集計
        recalc_trans_status_counts(book_data)

        # order を再計算（ページごと）
        affected_pages = set(str(p.get("page_number")) for p in request_paragraphs)
        for page_number in affected_pages:
            if page_number not in book_data["pages"]:
                continue
            page_paragraphs = book_data["pages"][page_number]["paragraphs"]
            sorted_paragraphs = sorted(
                page_paragraphs.values(),
                key=lambda x: x.get("order", 0)
            )
            for i, paragraph in enumerate(sorted_paragraphs, start=1):
                paragraph["order"] = i

        atomicsave_json(json_path, book_data)
        
        return jsonify(
            {
                "status": "ok",
                "message": f"{deleted_count}個のパラグラフを削除しました",
                "deleted_count": deleted_count,
                "trans_status_counts": book_data.get("trans_status_counts"),
            }
        ), 200

    except Exception as e:
        app.logger.error(f"delete_paragraphs error: {str(e)}")
        return jsonify({"status": "error", "message": f"削除中にエラーが発生しました: {str(e)}"}), 500


# json を読み込んでオブジェクトを戻す
def load_json(json_path: str):
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"{json_path} not found")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

@app.route("/partials/data_export_dialog")
def data_export_dialog_partial():
    return render_template("_data_export_dialog.html")


# API: ブック内のスタイル一覧を取得
@app.route("/api/book_styles/<path:pdf_name>")
def get_book_styles_api(pdf_name):
    """Get all styles from the book's JSON file."""
    _, json_path = get_paths(pdf_name)
    if not os.path.exists(json_path):
        return jsonify({"status": "error", "message": "JSONファイルが存在しません"}), 404

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        
        styles = book_data.get("styles", {}) or {}
        return jsonify({"status": "ok", "styles": styles}), 200
    except Exception as e:
        app.logger.error(f"Error getting book styles: {str(e)}")
        return jsonify({"status": "error", "message": f"スタイル取得エラー: {str(e)}"}), 500


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
