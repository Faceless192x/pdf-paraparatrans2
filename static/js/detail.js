// detail.htmlのグローバル変数は3つ
pdfName = document.body.dataset.pdfName;
bookData = {};
currentPage = 1;

function getPageFromUrl() {
    try {
        const url = new URL(window.location.href);
        const q = url.searchParams.get('page');
        if (q) {
            const n = parseInt(q, 10);
            return Number.isFinite(n) ? n : null;
        }

        const hash = (url.hash || '').replace(/^#/, '');
        if (!hash) return null;

        const hashParams = new URLSearchParams(hash);
        const h = hashParams.get('page') || hashParams.get('p');
        if (!h) return null;
        const n = parseInt(h, 10);
        return Number.isFinite(n) ? n : null;
    } catch (e) {
        console.warn('getPageFromUrl failed:', e);
        return null;
    }
}

function clampPage(pageNum) {
    let page = parseInt(pageNum, 10);
    if (!Number.isFinite(page) || page < 1) page = 1;

    const max = parseInt(bookData?.page_count, 10);
    if (Number.isFinite(max) && max > 0) {
        page = Math.min(Math.max(1, page), max);
    }
    return page;
}

function updateUrlForPage(pageNum, { replace = false } = {}) {
    const page = parseInt(pageNum, 10);
    if (!Number.isFinite(page) || page < 1) return;

    const url = new URL(window.location.href);
    const current = url.searchParams.get('page');
    if (current === String(page) && (history.state?.page === page)) {
        return;
    }
    url.searchParams.set('page', String(page));

    const state = { page };
    if (replace) {
        history.replaceState(state, '', url);
    } else {
        history.pushState(state, '', url);
    }
}

window.onload = async function() { // async を追加
    const pageFromUrl = getPageFromUrl();
    if (pageFromUrl) {
        currentPage = pageFromUrl;
    }

    // 初期状態をURLに反映（履歴は増やさない）
    updateUrlForPage(currentPage, { replace: true });

    initResizers();
    initTocPanel();
    initPdfPanel();
    initSrcPanel();
    await fetchBookData(); // await を追加
};

document.addEventListener('DOMContentLoaded', function() {
    console.log("DOMContentLoaded");
    // 再描画ボタン（現在は非表示）
    document.getElementById('renderButton').addEventListener('click', renderParagraphs);
    // 構成保存
    document.getElementById('saveOrderButton').addEventListener('click', saveForce);
    // ページ翻訳
    document.getElementById('pageDictReplaceButton').addEventListener('click', dictReplacePage);
    document.getElementById('pageTransButton').addEventListener('click', transPage);
    document.getElementById('alignTransBySrcJoinedButton').addEventListener('click', alignTransBySrcJoined);
    // 辞書登録ボタン
    document.getElementById('openDictButton').addEventListener('click', () => {
        // DictPopup.show() は dict.js で定義されている
        if (window.DictPopup) {
            window.DictPopup.show();
        } else {
            console.error("DictPopup is not available.");
        }
    });


    window.autoToggle.init();
    // トグル/チェックボックスのカスタムイベント
    document.addEventListener('auto-toggle-change', autoToggleChanged);

    // ブラウザの戻る/進むでページ移動
    window.addEventListener('popstate', async (event) => {
        const page = event?.state?.page ?? getPageFromUrl();
        if (!page) return;
        const targetPage = clampPage(page);
        if (targetPage === currentPage) return;
        await jumpToPage(targetPage, { updateUrl: false });
    });
});

// すべてのauto-toggleの状態変化を監視する（toggleごとでもよいが、リスナーを増やさないことを選択）
function autoToggleChanged(event) {
    const id = event.detail.id;
    const newState = event.detail.newState;
    console.log(`トグルスイッチ ${id} が ${newState ? 'ON' : 'OFF'} に変更されました。`);

    if (id === 'toggleTocPanel') {
        // 目次パネルのON/OFF
        let panel = document.getElementById("tocPanel");
        let resizer = document.getElementById("resizer1");
        if (newState){
            panel.classList.remove("hidden");
            resizer.classList.remove("hidden");
            // showToc();
        } else {
            panel.classList.add("hidden");
            resizer.classList.add("hidden");
        }
    } else if (id==='togglePdfPanel') {
        // PDFパネルのON/OFF
        let panel = document.getElementById("pdfPanel");
        let resizer = document.getElementById("resizer2");
        if (newState){
            panel.classList.remove("hidden");
            resizer.classList.remove("hidden");
        } else {
            panel.classList.add("hidden");
            resizer.classList.add("hidden");
        }
    } else if (id === 'toggleSrcHtml') {
        // 「HTML」列のON/OFF
        document.querySelectorAll('.src-html').forEach(el => {
            el.style.display = newState ? 'block' : 'none';
        });
    } else if (id === 'toggleSrcText') {
        // 「原文」列のON/OFF
        document.querySelectorAll('.src-text').forEach(el => {
            el.style.display = newState ? 'block' : 'none';
        });
    } else if (id === 'toggleSrcJoined') {
        // 「連結文」列のON/OFF
        document.querySelectorAll('.src-joined').forEach(el => {
            el.style.display = newState ? 'block' : 'none';
        });
    } else if (id === 'toggleSrcReplaced') {
        // 「置換文」列のON/OFF
        document.querySelectorAll('.src-replaced').forEach(el => {
            el.style.display = newState ? 'block' : 'none';
        });
    } else if (id === 'toggleTransAuto') {
        // 「自動」列のON/OFF
        document.querySelectorAll('.trans-auto').forEach(el => {
            el.style.display = newState ? 'block' : 'none';
        });
    } else if (id === 'toggleTransText') {
        // 「訳文」列のON/OFF
        document.querySelectorAll('.trans-text').forEach(el => {
            el.style.display = newState ? 'block' : 'none';
        });
    } else if (id === 'toggleCommentText') {
        // 「コメント」列のON/OFF
        document.querySelectorAll('.comment-text').forEach(el => {
            el.style.display = newState ? 'block' : 'none';
        });
    } else if (id === 'toggleTocPage') {
        // 見出し「Page」のON/OFF
        document.querySelectorAll('.toc-page').forEach(el => {
            el.style.display = newState ? 'table-cell' : 'none';
        });
    } else if (id === 'toggleTocSrc') {
        // 「原文」見出しのON/OFF
        document.querySelectorAll('.toc-src').forEach(el => {
            el.style.display = newState ? 'table-cell' : 'none';
        });
    } else if (id === 'toggleTocTrans') {
        // 「訳文」見出しのON/OFF
        document.querySelectorAll('.toc-trans').forEach(el => {
            el.style.display = newState ? 'table-cell' : 'none';
        });
    }
    
}


// boookDataから「見出しスタイル一覧」を読み込み
function updateBookStyles() {
    if (!bookData.styles) {
        console.warn("styles が存在しません");
        return;
    }

    const styleElement = document.querySelector("style.book-data-styles");
    if (!styleElement) {
        console.error("スタイルタグが見つかりません: .book-data-styles");
        return;
    }

    let newStyles = "";
    for (let className in bookData.styles) {
        if (bookData.styles.hasOwnProperty(className)) {
            newStyles += `.${className} { ${bookData.styles[className]} }\n`;
        }
    }

    styleElement.innerHTML = newStyles;
}

// 翻訳進捗状況を更新
function updateTransStatusCounts(counts) {
    if (!counts) {
        console.warn("counts が存在しません");
        return;
    }

    // settings更新(updateBookInfo)で使うため、bookData にも保持しておく
    if (typeof bookData === 'object' && bookData) {
        bookData.trans_status_counts = counts;
    }

    document.getElementById("countNone").innerText = counts.none;
    document.getElementById("countAuto").innerText = counts.auto;
    document.getElementById("countDraft").innerText = counts.draft;
    document.getElementById("countFixed").innerText = counts.fixed;
}

/* ---------------------------------------
   PDFパネルに「ウインドウ幅に合わせる」を外部から適用
   - iframe.contentWindow.PDFViewerApplication を介して制御
--------------------------------------- */
function fitToWidth() {
    const iframe = document.getElementById("pdfIframe");
    if (!iframe) return;

    const viewerWin = iframe.contentWindow;
    // PDF.jsがまだロードされていない場合はリトライ
    if (!viewerWin ||
        !viewerWin.PDFViewerApplication ||
        !viewerWin.PDFViewerApplication.pdfViewer) {
        console.log("PDF.js not ready -> retry fitToWidth");
        setTimeout(fitToWidth, 300);
        return;
    }

    // 「ウインドウ幅に合わせる」と同じ設定
    viewerWin.PDFViewerApplication.pdfViewer.currentScaleValue = "page-width";
    console.log("fitToWidth: set page-width");
}

async function prevPage() { // async を追加
    console.log("prevPage");
    if (currentPage > 1) {
        // ここでカレントぺーずを変えてはいけない
        await jumpToPage(currentPage - 1);
    }
}

async function nextPage() { // async を追加
    if (currentPage < parseInt(bookData.page_count,10)) {
        // ここでカレントぺーずを変えてはいけない
        await jumpToPage(currentPage + 1);
    }
}

async function jumpToPage(pageNum, options = {}) { // async を追加
    const { updateUrl = true, replaceHistory = false, forceRender = false } = options;

    const targetPage = clampPage(pageNum);

    console.log("jumpToPage:pageNum " + pageNum);
    console.log("currentPage " + currentPage);
    console.log("pageInput.value" + document.getElementById("pageInput").value);

    // 同一ページ指定の場合は、通常はURL同期のみ。
    // ただしデータ更新後などは forceRender で再描画する。
    if (targetPage === currentPage) {
        document.getElementById("pageInput").value = currentPage;
        if (updateUrl) {
            updateUrlForPage(currentPage, { replace: replaceHistory });
        }

        // 初回遷移時など、同一ページでもPDFビューアが未ロードの場合があるため必ず反映する。
        ensurePdfViewerLoaded(currentPage);
        setPdfViewerPage(currentPage);

        if (forceRender) {
            renderParagraphs({ resetScrollTop: true });
            document.getElementById("srcPanel").focus();
            setCurrentParagraph(0, false, { scrollIntoView: false });
        }
        return;
    }

    if (isPageEdited) {
        await saveCurrentPageOrder(); // await を追加
    }

    // 保存後にページを移動する
    currentPage = targetPage;
    document.getElementById("pageInput").value = currentPage;

    if (updateUrl) {
        updateUrlForPage(currentPage, { replace: replaceHistory });
    }

    // PDFはフルPDFを一度だけ読み込み、ページ移動は PDFViewerApplication 経由で行う。
    // これにより「毎回iframeを再ロード」「サーバ側で1ページPDFを都度生成」を避けて高速化する。
    ensurePdfViewerLoaded(currentPage);
    setPdfViewerPage(currentPage);

    renderParagraphs({ resetScrollTop: true });
    document.getElementById("srcPanel").focus();
    setCurrentParagraph(0, false, { scrollIntoView: false });
}

function ensurePdfViewerLoaded(initialPage = 1) {
    const iframe = document.getElementById('pdfIframe');
    if (!iframe) return;

    const pdfFileUrl = `/pdf_view/${encodeURIComponent(pdfName)}`;
    // PDF.js側の挙動をURLで固定
    // - disableautofetch=true: 先読みを抑制して初回の負荷を下げる
    // - enablescripting=false: PDF内スクリプトを無効化
    // - scrollmode=page: 単ページ（ページ単位スクロール）に固定
    // - spreadmode=none: 見開き表示を無効化
    const viewerBaseUrl = `/static/pdfjs/web/viewer.html?file=${encodeURIComponent(pdfFileUrl)}`
        + `&disableautofetch=true&enablescripting=false`
        + `&scrollmode=page&spreadmode=none`;

    if (iframe.dataset.viewerBaseUrl !== viewerBaseUrl) {
        iframe.dataset.viewerBaseUrl = viewerBaseUrl;
        iframe.src = `${viewerBaseUrl}#page=${initialPage}`;
    }
}

function setPdfViewerPage(pageNum) {
    const iframe = document.getElementById('pdfIframe');
    if (!iframe) return;

    const viewerWin = iframe.contentWindow;
    if (!viewerWin || !viewerWin.PDFViewerApplication || !viewerWin.PDFViewerApplication.pdfViewer) {
        setTimeout(() => setPdfViewerPage(pageNum), 100);
        return;
    }

    const app = viewerWin.PDFViewerApplication;
    const apply = () => {
        app.pdfViewer.currentPageNumber = pageNum;
        // 既存挙動に合わせて「幅に合わせる」を維持
        app.pdfViewer.currentScaleValue = 'page-width';
    };

    if (app.pdfDocument) {
        apply();
    } else {
        viewerWin.document.addEventListener('documentloaded', apply, { once: true });
    }
}

function initResizers() {
    // 目次パネルとPDFパネルの間のリサイズ
    const resizer1 = document.getElementById('resizer1');
    const tocPanel = document.getElementById('tocPanel');
    const pdfPanel = document.getElementById('pdfPanel');
    const overlay = document.getElementById('overlay');

    let startX, startWidthToc;
    resizer1.addEventListener('mousedown', function(e) {
        startX = e.clientX;
        startWidthToc = tocPanel.getBoundingClientRect().width;
        document.addEventListener('mousemove', resizeToc);
        document.addEventListener('mouseup', stopResizeToc);
    });

    function resizeToc(e) {
        const dx = e.clientX - startX;
        tocPanel.style.width = (startWidthToc + dx) + 'px';
    }

    function stopResizeToc() {
        document.removeEventListener('mousemove', resizeToc);
        document.removeEventListener('mouseup', stopResizeToc);
    }

    // PDFパネルとsrcPanelの間のリサイズ
    const resizer2 = document.getElementById('resizer2');
    let startX2, startWidthPdf;
    const minPdfWidth = 200; // 最小幅を200pxに設定（必要に応じて調整）

    resizer2.addEventListener('mousedown', function(e) {
        e.preventDefault(); // ドラッグ中の不要な選択などを防止
        startX2 = e.clientX;
        startWidthPdf = pdfPanel.getBoundingClientRect().width;
        overlay.style.display = 'block'; // オーバーレイを表示
        document.addEventListener('mousemove', resizePdf);
        document.addEventListener('mouseup', stopResizePdf);
    });

    function resizePdf(e) {
        const dx = e.clientX - startX2;
        // 左方向のドラッグで幅が縮む
        let newWidth = startWidthPdf + dx;
        if (newWidth < minPdfWidth) {
            newWidth = minPdfWidth;
        }
        pdfPanel.style.width = newWidth + 'px';
    }

    function stopResizePdf() {
        overlay.style.display = 'none';
        document.removeEventListener('mousemove', resizePdf);
        document.removeEventListener('mouseup', stopResizePdf);
        // リサイズ完了後に「page-width」を再適用
        setTimeout(fitToWidth, 100);
    }
}

async function saveForce() {
    isPageEdited = true;
    saveCurrentPageOrder();
    updateBookInfo();
}
