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
        _post_json(url, {"current_page": 1})
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


def _run_hotkey_checks(page) -> None:
    page.keyboard.press("Control+Shift+K")
    hud = page.locator("#hotkey-input-display")
    hud.wait_for(state="visible", timeout=5000)

    page.locator("#hotkey-input-display .hotkey-input-close").click()
    hud.wait_for(state="hidden", timeout=3000)

    page.keyboard.press("Control+Shift+K")
    hud.wait_for(state="visible", timeout=5000)

    box_before = hud.bounding_box()
    _assert(box_before is not None, "hotkey HUD bounding box is missing")

    drag_from_x = box_before["x"] + (box_before["width"] / 2)
    drag_from_y = box_before["y"] + 8
    page.mouse.move(drag_from_x, drag_from_y)
    page.mouse.down()
    page.mouse.move(drag_from_x + 60, drag_from_y + 40)
    page.mouse.up()

    box_after = hud.bounding_box()
    _assert(box_after is not None, "hotkey HUD bounding box is missing after drag")
    _assert(
        abs(box_after["x"] - box_before["x"]) > 5 or abs(box_after["y"] - box_before["y"]) > 5,
        "hotkey HUD should move after drag",
    )

    page.locator("#srcPanel").click()

    page.keyboard.press("ArrowUp")
    page.locator("#hotkey-input-display .hotkey-input-value").wait_for(timeout=3000)
    key_text = page.locator("#hotkey-input-display .hotkey-input-value").inner_text()
    desc_text = page.locator("#hotkey-input-display .hotkey-input-desc").inner_text()
    _assert(key_text == "ArrowUp", f"hotkey HUD key mismatch: {key_text}")
    _assert("パラグラフを移動(上)" in desc_text, "hotkey HUD description missing")

    page.keyboard.press("ArrowDown")
    history_rows = page.locator("#hotkey-input-display .hotkey-input-history-row")
    history_rows.first.wait_for(timeout=3000)
    _assert(history_rows.count() >= 2, "hotkey HUD should show history rows")

    page.wait_for_function(
        "() => {"
        "  const el = document.querySelector('#hotkey-input-display .hotkey-input-history');"
        "  if (!el) return false;"
        "  return el.scrollTop + el.clientHeight >= el.scrollHeight;"
        "}",
        timeout=3000,
    )


def _run_dict_auto_translate_selected_checks(base_url: str, page) -> None:
    payload_capture = {"payload": None}
    list_entries = [
        {"original_word": "Rune", "translated_word": "", "status": 9, "count": 1},
        {"original_word": "Glorantha", "translated_word": "", "status": 9, "count": 1},
    ]

    page.route(
        "**/api/dict/catalog",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "status": "ok",
                    "dicts": [{"path": "config/dict.txt", "label": "dict.txt"}],
                    "default_path": "config/dict.txt",
                }
            ),
        ),
    )
    page.route(
        "**/api/dict/list**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "status": "ok",
                    "entries": list_entries,
                    "dict_path": "config/dict.txt",
                }
            ),
        ),
    )
    page.route(
        "**/api/dict/compare**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "ok", "entries": {}, "dict_path": "config/dict.txt"}),
        ),
    )

    def _handle_auto_translate(route):
        raw = route.request.post_data or "{}"
        payload_capture["payload"] = json.loads(raw)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "ok", "message": "自動翻訳を実行しました (1 件)", "count": 1}),
        )

    page.route("**/api/dict/auto_translate", _handle_auto_translate)

    page.goto(f"{base_url}/dict_maintenance", wait_until="networkidle")
    page.locator("#dictTableBody tr").first.wait_for(timeout=10000)

    page.locator("#dictTableBody tr").nth(0).locator("input[type='checkbox']").check()
    page.locator("#dictAutoTranslateButton").click()

    deadline = time.time() + 5
    while payload_capture["payload"] is None and time.time() < deadline:
        time.sleep(0.05)

    payload = payload_capture["payload"]
    _assert(payload is not None, "auto translate API payload was not captured")
    _assert(payload.get("dict_path") == "config/dict.txt", "dict_path mismatch")
    entries = payload.get("entries") or []
    _assert(len(entries) == 1, f"selected-only payload expected 1 entry, got {len(entries)}")
    _assert(entries[0].get("original_word") == "Rune", "selected entry mismatch")


def _run_resume_page_checks(base_url: str, detail_path: str, page) -> None:
    page.goto(f"{base_url}{detail_path}", wait_until="networkidle")
    page.locator("#srcParagraphs .paragraph-box").first.wait_for(timeout=15000)

    page_count_text = page.locator("#pageCount").inner_text().strip()
    page_count = int(page_count_text)
    _assert(page_count >= 2, f"resume-page test requires at least 2 pages, got {page_count}")

    page.click("button:has-text('▶')")
    page.wait_for_function(
        "() => String(document.getElementById('pageInput')?.value || '') === '2'",
        timeout=10000,
    )
    page.wait_for_timeout(900)

    page.goto(base_url, wait_until="networkidle")
    link = page.locator(f'a[href*="{detail_path}"]')
    link.first.wait_for(timeout=15000)
    link.first.click()

    page.wait_for_url(f"**{detail_path}**", timeout=15000)
    page.locator("#srcParagraphs .paragraph-box").first.wait_for(timeout=15000)
    page.wait_for_function(
        "() => String(document.getElementById('pageInput')?.value || '') === '2'",
        timeout=15000,
    )


def _run_table_reextract_button_checks(page) -> None:
    payload_capture = {"payload": None}
    suggest_capture = {"called": False}

    def _handle_suggest(route):
        suggest_capture["called"] = True
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "status": "ok",
                    "rows": 2,
                    "cols": 3,
                    "clip_rect": [0, 0, 100, 100],
                    "preview_cell_rects": [
                        [0, 0, 33, 50],
                        [33, 0, 66, 50],
                        [66, 0, 100, 50],
                        [0, 50, 33, 100],
                        [33, 50, 66, 100],
                        [66, 50, 100, 100],
                    ],
                }
            ),
        )

    page.route("**/api/table_grid_suggest/**", _handle_suggest)

    def _handle_reextract(route):
        raw = route.request.post_data or "{}"
        payload_capture["payload"] = json.loads(raw)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "ok", "message": "テーブル行を1件追加しました", "delta": None}),
        )

    page.route("**/api/reextract_table_from_selection/**", _handle_reextract)
    def _on_dialog(dialog):
        try:
            if dialog.type == "prompt":
                dialog.accept("2,3")
            else:
                dialog.accept()
        except Exception:
            pass

    page.on("dialog", _on_dialog)

    page.locator("#reextractTableButton").wait_for(timeout=10000)

    boxes = page.locator("#srcParagraphs .paragraph-box")
    boxes.first.wait_for(timeout=15000)
    count = boxes.count()
    _assert(count >= 2, f"table reextract test requires at least 2 paragraphs, got {count}")

    page.evaluate(
        "() => {"
        "  const rows = Array.from(document.querySelectorAll('#srcParagraphs .paragraph-box'));"
        "  rows.forEach((el) => el.classList.remove('selected'));"
        "  if (rows[0]) rows[0].classList.add('selected');"
        "  if (rows[1]) rows[1].classList.add('selected');"
        "}"
    )
    page.locator("#reextractTableButton").click()

    deadline = time.time() + 5
    while (not suggest_capture["called"]) and time.time() < deadline:
        time.sleep(0.05)

    _assert(suggest_capture["called"], "table grid suggest API was not called")
    page.wait_for_timeout(300)


def _run_ollama_chunk_tuner_checks(page) -> None:
    result = page.evaluate(
        "() => {"
        "  const key = 'ppt.ollama.chunk_profile.v1';"
        "  try { window.localStorage.removeItem(key); } catch (e) {}"
        "  currentTranslateEngine = 'ollama';"
        "  const before = loadOllamaChunkProfile();"
        "  const req = buildParaparatransRequestPayload(1, 1);"
        "  updateOllamaChunkProfileWithResult({"
        "    success: true,"
        "    elapsedMs: 18000,"
        "    stats: { failed: 0, missing_from_batch: 0, group_max_chars: req.groupMaxChars },"
        "    requestedGroupMaxChars: req.groupMaxChars,"
        "  });"
        "  const afterSuccess = loadOllamaChunkProfile();"
        "  updateOllamaChunkProfileWithResult({"
        "    success: false,"
        "    elapsedMs: 0,"
        "    requestedGroupMaxChars: afterSuccess.chunk_max_chars,"
        "  });"
        "  const afterFailure = loadOllamaChunkProfile();"
        "  return {"
        "    body: req.body,"
        "    groupMaxChars: req.groupMaxChars,"
        "    beforeChunk: before.chunk_max_chars,"
        "    afterSuccessChunk: afterSuccess.chunk_max_chars,"
        "    afterFailureChunk: afterFailure.chunk_max_chars,"
        "  };"
        "}"
    )

    body = str(result.get("body") or "")
    group_max_chars = int(result.get("groupMaxChars") or 0)
    before_chunk = int(result.get("beforeChunk") or 0)
    after_success_chunk = int(result.get("afterSuccessChunk") or 0)
    after_failure_chunk = int(result.get("afterFailureChunk") or 0)

    _assert("group_max_chars=" in body, "paraparatrans payload should include group_max_chars for ollama")
    _assert(group_max_chars >= 600, f"group_max_chars should be >= 600, got {group_max_chars}")
    _assert(after_success_chunk > before_chunk, "chunk size should increase after a fast successful translation")
    _assert(after_failure_chunk < after_success_chunk, "chunk size should decrease after a failed translation")


def _run_translate_progress_checks(page) -> None:
    result = page.evaluate(
        "async () => {"
        "  const markerId = 'test-progress-id';"
        "  startSrcTranslateProgress('page', markerId);"
        "  handleSrcTranslateProgressLine('2026-03-06 00:00:00 [INFO] [PROGRESS] {\\\"kind\\\":\\\"translation\\\",\\\"phase\\\":\\\"start\\\",\\\"id\\\":\\\"test-progress-id\\\",\\\"done\\\":0,\\\"total\\\":10}');"
        "  const startLabel = String(document.getElementById('srcTranslateProgressLabel')?.textContent || '');"
        "  handleSrcTranslateProgressLine('2026-03-06 00:00:01 [INFO] [PROGRESS] {\\\"kind\\\":\\\"translation\\\",\\\"phase\\\":\\\"step\\\",\\\"id\\\":\\\"test-progress-id\\\",\\\"done\\\":3,\\\"total\\\":10,\\\"page\\\":1}');"
        "  const label = String(document.getElementById('srcTranslateProgressLabel')?.textContent || '');"
        "  const etaPattern = /予想完了\\s+([^\\s]+)/;"
        "  const etaBeforeMatch = label.match(etaPattern);"
        "  await new Promise((resolve) => setTimeout(resolve, 1200));"
        "  const labelAfterWait = String(document.getElementById('srcTranslateProgressLabel')?.textContent || '');"
        "  const etaAfterMatch = labelAfterWait.match(etaPattern);"
        "  const width = String(document.getElementById('srcTranslateProgressBar')?.style.width || '0%');"
        "  const ariaNow = String(document.getElementById('srcTranslateProgressTrack')?.getAttribute('aria-valuenow') || '0');"
        "  finishSrcTranslateProgress(true);"
        "  return { startLabel, label, labelAfterWait, etaBefore: etaBeforeMatch ? etaBeforeMatch[1] : '', etaAfter: etaAfterMatch ? etaAfterMatch[1] : '', width, ariaNow };"
        "}"
    )

    start_label = str(result.get("startLabel") or "")
    label = str(result.get("label") or "")
    label_after_wait = str(result.get("labelAfterWait") or "")
    eta_before = str(result.get("etaBefore") or "")
    eta_after = str(result.get("etaAfter") or "")
    width_text = str(result.get("width") or "0%").replace("%", "")
    aria_now = int(float(str(result.get("ariaNow") or "0")))
    width = float(width_text) if width_text else 0.0

    _assert("0/10" in start_label, f"start progress label should contain 0/10, got: {start_label}")
    _assert("経過" in start_label, f"start progress label should contain elapsed seconds, got: {start_label}")
    _assert("予想完了" in start_label, f"start progress label should contain ETA, got: {start_label}")
    _assert("3/10" in label, f"progress label should contain 3/10, got: {label}")
    _assert("経過" in label, f"progress label should contain elapsed seconds, got: {label}")
    _assert("予想完了" in label, f"progress label should contain ETA, got: {label}")
    _assert("予想完了" in label_after_wait, f"progress label after wait should contain ETA, got: {label_after_wait}")
    _assert(bool(eta_before), f"ETA should be extractable before wait, label: {label}")
    _assert(bool(eta_after), f"ETA should be extractable after wait, label: {label_after_wait}")
    _assert(eta_before == eta_after, f"ETA should not drift without progress updates: before={eta_before}, after={eta_after}")
    _assert(width >= 30.0, f"progress bar width should be >= 30%, got: {width}")
    _assert(aria_now >= 30, f"aria-valuenow should be >= 30, got: {aria_now}")


def _run_help_checks(base_url: str, page) -> None:
    console_messages = []

    def _handle_console(msg) -> None:
        console_messages.append(msg.text)

    page.on("console", _handle_console)
    page.goto(base_url, wait_until="networkidle")

    refresh_button = page.get_by_role("button", name="一覧を更新")
    refresh_button.wait_for(timeout=10000)
    refresh_button.hover()
    tooltip = page.locator(".help-tooltip-popup")
    tooltip.wait_for(state="visible", timeout=5000)
    _assert(tooltip.inner_text().strip() != "", "help tooltip should contain text")

    page.locator("#show-full-help").click()
    modal = page.locator(".help-modal-overlay")
    modal.wait_for(state="visible", timeout=5000)
    _assert(page.locator(".help-content h1").first.inner_text().strip() != "", "help modal should render headings")

    disallowed_logs = [
        message for message in console_messages
        if "Failed to load libraries" in message or "ERR_BLOCKED_BY_CLIENT" in message
    ]
    _assert(not disallowed_logs, f"help UI should not rely on blocked CDN assets: {disallowed_logs}")


def _run_ui_checks(
    base_url: str,
    pdf_name: str,
    headless: bool,
    help_only: bool,
    hotkey_only: bool,
    dict_auto_translate_only: bool,
    resume_page_only: bool,
    table_reextract_only: bool,
    ollama_chunk_only: bool,
    translate_progress_only: bool,
) -> None:
    encoded = urllib.parse.quote(pdf_name, safe="/")
    detail_path = f"/detail/{encoded}"
    folder = ""
    if "/" in pdf_name:
        folder = pdf_name.rsplit("/", 1)[0]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()

        if help_only:
            _run_help_checks(base_url, page)
            browser.close()
            return

        if dict_auto_translate_only:
            _run_dict_auto_translate_selected_checks(base_url, page)
            browser.close()
            return

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

        if hotkey_only:
            _run_hotkey_checks(page)
            browser.close()
            return

        if resume_page_only:
            _run_resume_page_checks(base_url, detail_path, page)
            browser.close()
            return

        if table_reextract_only:
            _run_table_reextract_button_checks(page)
            browser.close()
            return

        if ollama_chunk_only:
            _run_ollama_chunk_tuner_checks(page)
            browser.close()
            return

        if translate_progress_only:
            _run_translate_progress_checks(page)
            browser.close()
            return

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
    parser.add_argument(
        "--help-only",
        action="store_true",
        help="Run only Help tooltip/modal checks.",
    )
    parser.add_argument(
        "--hotkey-only",
        action="store_true",
        help="Run only the hotkey HUD checks.",
    )
    parser.add_argument(
        "--dict-auto-translate-only",
        action="store_true",
        help="Run only dict maintenance selected auto-translate checks.",
    )
    parser.add_argument(
        "--resume-page-only",
        action="store_true",
        help="Run only last-open-page resume checks.",
    )
    parser.add_argument(
        "--table-reextract-only",
        action="store_true",
        help="Run only selected-rows table reextract button checks.",
    )
    parser.add_argument(
        "--ollama-chunk-only",
        action="store_true",
        help="Run only Ollama adaptive chunk tuner checks.",
    )
    parser.add_argument(
        "--translate-progress-only",
        action="store_true",
        help="Run only translation progress bar live-update checks.",
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

        if not args.help_only:
            _ensure_extracted(args.base_url, args.pdf_name)
        _run_ui_checks(
            args.base_url,
            args.pdf_name,
            headless=args.headless,
            help_only=args.help_only,
            hotkey_only=args.hotkey_only,
            dict_auto_translate_only=args.dict_auto_translate_only,
            resume_page_only=args.resume_page_only,
            table_reextract_only=args.table_reextract_only,
            ollama_chunk_only=args.ollama_chunk_only,
            translate_progress_only=args.translate_progress_only,
        )
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
