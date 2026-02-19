# ParaParaTrans Chrome Extension (Local)

This extension sends the current page HTML to a ParaParaTrans URL book via `http://localhost:5077`.

## Install (Chrome/Edge)

1. Open `chrome://extensions` (or `edge://extensions`).
2. Turn on **Developer mode**.
3. Click **Load unpacked** and select this folder.
4. Pin the extension if you want quick access.

## Use

1. Start ParaParaTrans (`python pdf-paraparatrans.py`).
2. Open the target page (tab or iframe). If using the URL panel, keep that page visible.
3. (First time) Click the extension icon.
4. Set `ParaParaTrans URL` (example: `http://localhost:5077`).
5. (Optional) Set `Book name` if you don't want to use the current open book.
6. Use one of the capture methods:
	- Extension popup: **Send current page**.
	- Right click inside the page/iframe: **ParaParaTrans: 取込**（既存ページは再取込）.
	- Right click for rules:
	  - **ParaParaTrans: この階層以下を取得**
	  - **ParaParaTrans: この要素を取得**
	  - **ParaParaTrans: この要素を排除**

The page is added to the URL book using `/api/url_book/import_html`.

## Notes

- The extension uses `http://*/*` and `https://*/*` host permissions to access the active page and iframes.
- You can narrow permissions in `manifest.json` to specific domains if needed.
- If the page already exists in the book, enable **Overwrite if exists**.
- If `Book name` is empty, the extension uses the currently opened URL book in ParaParaTrans.
