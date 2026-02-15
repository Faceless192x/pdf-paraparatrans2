import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _wait_for_http(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 500:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"Server not ready at {url}: {last_error}")


def _post_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)


def _post(url: str) -> dict:
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)


def _ensure_extracted(base_url: str, pdf_name: str) -> None:
    encoded = urllib.parse.quote(pdf_name, safe="/")
    url = f"{base_url}/api/extract_paragraphs/{encoded}"
    try:
        _post(url)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        raise RuntimeError(f"extract_paragraphs failed: {exc.code} {body}")


def _start_server(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["FLASK_DEBUG"] = "0"
    env["PARAPARATRANS_DATA_DIR"] = os.path.join(PROJECT_ROOT, "data")
    env["PARAPARATRANS_CONFIG_DIR"] = os.path.join(PROJECT_ROOT, "config")
    return subprocess.Popen(
        [sys.executable, "pdf-paraparatrans.py"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    with contextlib.suppress(Exception):
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        with contextlib.suppress(Exception):
            proc.kill()


def _read_server_output(proc: subprocess.Popen) -> str:
    if not proc.stdout:
        return ""
    try:
        return proc.stdout.read() or ""
    except Exception:
        return ""


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _run_ui_checks(base_url: str, pdf_name: str, headless: bool) -> None:
    encoded = urllib.parse.quote(pdf_name, safe="/")
    detail_path = f"/detail/{encoded}"
    folder = ""
    if "/" in pdf_name:
        folder = pdf_name.rsplit("/", 1)[0]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()

        page.goto(base_url, wait_until="networkidle")
        link = page.locator(f'a[href*="{detail_path}"]')

        try:
            link.wait_for(timeout=5000)
        except Exception:
            if folder:
                folder_q = urllib.parse.quote(folder)
                folder_link = page.locator(f'a[href*="?dir={folder_q}"]')
                folder_link.first.wait_for(timeout=10000)
                folder_link.first.click()
                page.wait_for_url(f"**?dir={folder_q}**", timeout=15000)
            link.wait_for(timeout=15000)

        link.first.click()

        page.wait_for_url(f"**{detail_path}**", timeout=15000)
        page.locator("#srcParagraphs .paragraph-box").first.wait_for(timeout=15000)

        panel = page.locator("#pdfPanel")
        panel.wait_for(timeout=10000)

        def panel_hidden() -> bool:
            cls = panel.get_attribute("class") or ""
            return "hidden" in cls.split()

        _assert(panel_hidden() is False, "pdfPanel should be visible initially")

        page.locator("#auto-toggle-input-togglePdfPanel").click()
        page.wait_for_function(
            "document.getElementById('pdfPanel').classList.contains('hidden')"
        )
        _assert(panel_hidden() is True, "pdfPanel should be hidden after toggle")

        page.locator("#auto-toggle-input-togglePdfPanel").click()
        page.wait_for_function(
            "!document.getElementById('pdfPanel').classList.contains('hidden')"
        )
        _assert(panel_hidden() is False, "pdfPanel should be visible after re-toggle")

        page.fill("#tocSearchInput", "Momentum")
        page.click("#tocSearchButton")
        page.locator("#tocSearchResults .search-result").first.wait_for(timeout=15000)

        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run UI smoke test with Playwright.")
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL of the app. Defaults to http://localhost:<port>.",
    )
    parser.add_argument(
        "--pdf-name",
        default="sandbox/trpg_sample",
        help="PDF name without extension.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode.",
    )
    parser.add_argument(
        "--start-server",
        action="store_true",
        help="Start the Flask server automatically.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5079,
        help="Port to use when starting the server.",
    )

    args = parser.parse_args()
    if not args.base_url:
        args.base_url = f"http://localhost:{args.port}"

    server_proc = None
    error = None
    try:
        if args.start_server:
            server_proc = _start_server(args.port)
            _wait_for_http(args.base_url)
        else:
            _wait_for_http(args.base_url)

        _ensure_extracted(args.base_url, args.pdf_name)
        _run_ui_checks(args.base_url, args.pdf_name, headless=args.headless)
    except BaseException as exc:
        error = exc
        print("UI smoke test failed:")
        traceback.print_exc()
    finally:
        if server_proc is not None:
            _stop_server(server_proc)

    if error is not None:
        if server_proc is not None:
            output = _read_server_output(server_proc).strip()
            if output:
                print("\n--- Server output ---")
                print(output)
        return 1

    print("UI smoke test passed")
    return 0


if __name__ == "__main__":
    exit_code = main()
    print(f"Exit code: {exit_code}")
    sys.exit(exit_code)
