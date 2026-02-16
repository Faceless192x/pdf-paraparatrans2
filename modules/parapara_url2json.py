import datetime
import html
import json
import os
import re
import time
import uuid
from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Comment


_BAD_CLASS_RE = re.compile(
    r"(nav|footer|header|sidebar|ads?|promo|sponsor|breadcrumb|cookie|popup|modal|newsletter|share|social|comment|related|recommend|subscribe)",
    re.IGNORECASE,
)

_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre")

_ALLOWED_INLINE_TAGS = {"a", "em", "strong", "code", "span", "br"}


def normalize_url(raw_url: str) -> Optional[str]:
    if not isinstance(raw_url, str):
        return None
    raw = raw_url.strip()
    if not raw:
        return None

    parsed = urlsplit(raw)
    if not parsed.scheme:
        parsed = urlsplit("http://" + raw)

    if parsed.scheme not in ("http", "https"):
        return None

    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    normalized = urlunsplit((parsed.scheme, netloc, path, parsed.query, ""))
    return normalized


def normalize_host(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower()
    except Exception:
        return ""


def load_site_profiles(config_folder: str) -> Dict[str, Any]:
    path = os.path.join(config_folder, "url_site_profiles.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def get_site_profile(profiles: Dict[str, Any], host: str) -> Optional[Dict[str, Any]]:
    if not host:
        return None
    profile = profiles.get(host)
    if isinstance(profile, dict):
        return profile
    return None


def _atomic_save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def save_url_book(path: str, book_data: Dict[str, Any]) -> None:
    _atomic_save_json(path, book_data)


def fetch_html(url: str, timeout: int = 15) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


def _strip_noise(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "canvas", "form", "input"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()


def _is_noise_element(el) -> bool:
    if not getattr(el, "name", None):
        return False
    if el.name in ("nav", "footer", "header", "aside"):
        return True

    attr_text = " ".join([
        str(el.get("id") or ""),
        " ".join(el.get("class") or []),
    ])
    return bool(_BAD_CLASS_RE.search(attr_text))


def _score_candidate(el) -> float:
    text = el.get_text(" ", strip=True)
    if not text:
        return 0.0
    text_len = len(text)
    if text_len < 200:
        return 0.0
    link_text_len = sum(len(a.get_text(" ", strip=True)) for a in el.find_all("a"))
    link_density = link_text_len / max(1, text_len)
    p_count = len(el.find_all("p"))
    score = (text_len * (1.0 - link_density)) + (p_count * 40.0)

    if _is_noise_element(el):
        score *= 0.2
    return score


def _pick_content_roots(soup: BeautifulSoup, site_profile: Optional[Dict[str, Any]]) -> List[Any]:
    if site_profile:
        include_selectors = site_profile.get("include_selectors") or []
        if isinstance(include_selectors, list) and include_selectors:
            roots: List[Any] = []
            for selector in include_selectors:
                roots.extend(soup.select(selector))
            if roots:
                return roots

    main = soup.find("main")
    if main:
        return [main]
    article = soup.find("article")
    if article:
        return [article]

    candidates = soup.find_all(["article", "section", "div", "main", "body"])
    scored = [(c, _score_candidate(c)) for c in candidates]
    scored = [pair for pair in scored if pair[1] > 0]
    if scored:
        scored.sort(key=lambda x: x[1], reverse=True)
        return [scored[0][0]]

    body = soup.find("body")
    return [body] if body else [soup]


def _apply_exclude_selectors(soup: BeautifulSoup, site_profile: Optional[Dict[str, Any]]) -> None:
    if not site_profile:
        return
    exclude_selectors = site_profile.get("exclude_selectors") or []
    if not isinstance(exclude_selectors, list):
        return
    for selector in exclude_selectors:
        for el in soup.select(selector):
            try:
                el.decompose()
            except Exception:
                pass


def _build_inline_html(node, base_url: str) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return html.escape(node)
    if getattr(node, "name", None) is None:
        return html.escape(str(node))

    name = node.name.lower()
    if name == "a":
        href = node.get("href") or ""
        abs_href = normalize_url(urljoin(base_url, href)) if href else None
        text = node.get_text(" ", strip=True)
        if not text:
            return ""
        safe_text = html.escape(text)
        if abs_href:
            safe_href = html.escape(abs_href, quote=True)
            return f"<a href=\"{safe_href}\" data-url=\"{safe_href}\">{safe_text}</a>"
        return safe_text

    if name == "br":
        return "<br>"

    parts = []
    for child in node.children:
        parts.append(_build_inline_html(child, base_url))
    inner = "".join(parts)

    if name in _ALLOWED_INLINE_TAGS and name != "a":
        return f"<{name}>{inner}</{name}>"

    return inner


def _extract_blocks_from_roots(roots: Iterable[Any], base_url: str) -> List[Tuple[str, str, str]]:
    blocks: List[Tuple[str, str, str]] = []
    seen = set()

    for root in roots:
        if not root:
            continue
        for el in root.find_all(_BLOCK_TAGS, recursive=True):
            if el in seen:
                continue
            seen.add(el)
            if _is_noise_element(el):
                continue

            tag = el.name.lower()
            text = el.get_text(" ", strip=True)
            if not text:
                continue

            min_len = 5 if tag.startswith("h") else 30
            if len(text) < min_len:
                continue

            inline_html = _build_inline_html(el, base_url)
            blocks.append((tag, text, inline_html))

    return blocks


def _extract_title(soup: BeautifulSoup) -> str:
    for selector in ("meta[property='og:title']", "meta[name='twitter:title']"):
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            return str(tag.get("content")).strip()

    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        if title:
            return title

    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
        if title:
            return title

    return ""


def extract_page_from_html(
    html_text: str,
    page_url: str,
    site_profile: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Tuple[str, str, str]]]:
    soup = BeautifulSoup(html_text, "html.parser")
    _strip_noise(soup)
    _apply_exclude_selectors(soup, site_profile)
    roots = _pick_content_roots(soup, site_profile)
    blocks = _extract_blocks_from_roots(roots, page_url)
    if not blocks:
        fallback_text = soup.get_text(" ", strip=True)
        if fallback_text:
            blocks = [("p", fallback_text, html.escape(fallback_text))]
    title = _extract_title(soup)
    return title, blocks


def _build_paragraphs(
    page_number: int,
    blocks: List[Tuple[str, str, str]],
) -> Dict[str, Dict[str, Any]]:
    paragraphs: Dict[str, Dict[str, Any]] = {}
    now = datetime.datetime.now().isoformat()

    order = 0
    for tag, text, inline_html in blocks:
        order += 1
        pid = f"{page_number}_{order}"
        paragraphs[pid] = {
            "id": pid,
            "src_text": inline_html,
            "src_html": inline_html,
            "src_joined": text,
            "src_replaced": text,
            "trans_auto": "",
            "trans_text": "",
            "trans_status": "none",
            "block_tag": tag if tag.startswith("h") else "p",
            "modified_at": now,
            "base_style": "",
            "bbox": [0, 0, 0, 0],
            "column_order": 1,
            "page_number": page_number,
            "order": order,
            "comment": "",
        }
    return paragraphs


def _recalc_trans_status_counts(book_data: Dict[str, Any]) -> Dict[str, int]:
    counts = {"none": 0, "auto": 0, "draft": 0, "fixed": 0}
    pages = book_data.get("pages") or {}
    for page in pages.values():
        paragraphs = (page or {}).get("paragraphs") or {}
        for p in paragraphs.values():
            status = (p or {}).get("trans_status") or "none"
            if status not in counts:
                status = "none"
            counts[status] += 1
    book_data["trans_status_counts"] = counts
    return counts


def build_url_book_data(
    root_url: str,
    *,
    title: Optional[str] = None,
    site_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    html_text = fetch_html(root_url)
    page_title, blocks = extract_page_from_html(html_text, root_url, site_profile)

    page_number = 1
    paragraphs = _build_paragraphs(page_number, blocks)
    book_title = title or page_title or root_url

    normalized_root = normalize_url(root_url) or root_url
    host = normalize_host(normalized_root)

    book_data: Dict[str, Any] = {
        "version": "2.0.0",
        "source_type": "url",
        "source_root_url": normalized_root,
        "source_host": host,
        "src_filename": normalized_root,
        "title": book_title,
        "page_count": 1,
        "styles": {},
        "page_url_map": {"1": normalized_root},
        "url_to_page": {normalized_root: "1"},
        "pages": {
            "1": {
                "url": normalized_root,
                "title": page_title or book_title,
                "paragraphs": paragraphs,
            }
        },
    }

    _recalc_trans_status_counts(book_data)
    return book_data


def ensure_url_page_in_book(
    book_data: Dict[str, Any],
    url: str,
    *,
    site_profile: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Dict[str, Any], bool]:
    normalized = normalize_url(url)
    if not normalized:
        raise ValueError("invalid url")

    url_to_page = book_data.get("url_to_page") or {}
    if normalized in url_to_page:
        page_key = str(url_to_page[normalized])
        page = (book_data.get("pages") or {}).get(page_key)
        return int(page_key), page or {}, False

    html_text = fetch_html(normalized)
    page_title, blocks = extract_page_from_html(html_text, normalized, site_profile)

    pages = book_data.setdefault("pages", {})
    page_number = int(book_data.get("page_count") or 0) + 1
    page_key = str(page_number)
    paragraphs = _build_paragraphs(page_number, blocks)

    pages[page_key] = {
        "url": normalized,
        "title": page_title or normalized,
        "paragraphs": paragraphs,
    }

    page_url_map = book_data.setdefault("page_url_map", {})
    page_url_map[page_key] = normalized

    url_to_page[normalized] = page_key
    book_data["url_to_page"] = url_to_page

    book_data["page_count"] = page_number
    _recalc_trans_status_counts(book_data)

    return page_number, pages[page_key], True


_SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico",
    ".mp3", ".wav", ".ogg", ".mp4", ".avi", ".mov", ".webm", ".mkv",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dmg", ".pkg", ".deb", ".rpm",
    ".css", ".js", ".json", ".xml", ".woff", ".woff2", ".ttf", ".eot",
}


def _normalize_for_crawl(raw_url: str, base_url: str, strip_fragment: bool = True, strip_query: bool = False) -> Optional[str]:
    if not isinstance(raw_url, str):
        return None
    raw = raw_url.strip()
    if not raw:
        return None

    absolute = urljoin(base_url, raw)
    parsed = urlsplit(absolute)

    if parsed.scheme not in ("http", "https"):
        return None

    path = parsed.path or "/"
    ext = os.path.splitext(path)[1].lower()
    if ext in _SKIP_EXTENSIONS:
        return None

    netloc = parsed.netloc.lower()
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    query = "" if strip_query else parsed.query
    fragment = "" if strip_fragment else parsed.fragment

    normalized = urlunsplit((parsed.scheme, netloc, path, query, fragment))
    return normalized


def _check_robots_txt(base_url: str, target_url: str, user_agent: str = "*") -> bool:
    try:
        parsed = urlsplit(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, target_url)
    except Exception:
        return True


def _extract_links_from_html(html_text: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        if not href:
            continue
        rel = a.get("rel") or []
        if "nofollow" in rel:
            continue
        normalized = _normalize_for_crawl(href, base_url, strip_fragment=True, strip_query=False)
        if normalized:
            links.append(normalized)
    return links


def crawl_site(
    root_url: str,
    *,
    path_prefix: Optional[str] = None,
    max_pages: int = 100,
    respect_robots: bool = True,
    site_profile: Optional[Dict[str, Any]] = None,
    delay_sec: float = 0.5,
) -> List[str]:
    root_normalized = normalize_url(root_url)
    if not root_normalized:
        raise ValueError("invalid root_url")

    root_parsed = urlsplit(root_normalized)
    root_host = root_parsed.netloc.lower()

    visited: Set[str] = set()
    queue = deque([root_normalized])
    discovered_urls = []

    def is_allowed(url: str) -> bool:
        parsed = urlsplit(url)
        if parsed.netloc.lower() != root_host:
            return False
        if path_prefix:
            if not parsed.path.startswith(path_prefix):
                return False
        if respect_robots and not _check_robots_txt(root_normalized, url):
            return False
        return True

    while queue and len(visited) < max_pages:
        current = queue.popleft()
        if current in visited:
            continue
        if not is_allowed(current):
            continue

        visited.add(current)
        discovered_urls.append(current)

        try:
            html_text = fetch_html(current)
            links = _extract_links_from_html(html_text, current)
            for link in links:
                if link not in visited:
                    queue.append(link)
        except Exception:
            pass

        if delay_sec > 0 and queue:
            time.sleep(delay_sec)

    return discovered_urls

