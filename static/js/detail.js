// detail.htmlのグローバル変数は3つ
pdfName = document.body.dataset.pdfName;
bookData = {};
currentPage = 1;

// PDF.js ビューア内のページ移動と、ParaParaTrans 側のページ移動を同期するための状態
let pdfViewerLastAppSetPage = null;
let pdfViewerLastAppSetAt = 0;
let pdfViewerSyncAttachInProgress = false;
let pdfViewerSyncIsJumping = false;
let pdfViewerSyncPendingPage = null;

function attachPdfViewerPageSync() {
    const iframe = document.getElementById('pdfIframe');
    if (!iframe) return;

    // viewer が差し替わった（再ロードされた）場合に備えて、紐づけキーで判定
    const viewerKey = iframe.dataset.viewerBaseUrl || iframe.src || '';
    if (iframe.dataset.pageSyncAttached === '1' && iframe.dataset.pageSyncFor === viewerKey) {
        return;
    }
    if (pdfViewerSyncAttachInProgress) return;
    pdfViewerSyncAttachInProgress = true;

    const tryAttach = () => {
        const viewerWin = iframe.contentWindow;
        const app = viewerWin?.PDFViewerApplication;

        if (!app || !app.eventBus) {
            setTimeout(tryAttach, 200);
            return;
        }

        // 旧ハンドラが残っていれば剥がす（同一 viewer でも再アタッチの可能性があるため）
        try {
            if (iframe._pageChangingHandler && typeof app.eventBus.off === 'function') {
                app.eventBus.off('pagechanging', iframe._pageChangingHandler);
            }
        } catch (_) {
            // ignore
        }

        const handler = async (evt) => {
            const raw = evt?.pageNumber ?? evt?.page;
            const pageNum = parseInt(raw, 10);
            if (!Number.isFinite(pageNum) || pageNum < 1) return;

            // アプリ側が直前に設定したページ変更は無視（ループ防止）
            const dt = Date.now() - (pdfViewerLastAppSetAt || 0);
            if (pdfViewerLastAppSetPage === pageNum && dt >= 0 && dt < 800) {
                return;
            }

            const targetPage = clampPage(pageNum);
            if (targetPage === currentPage) return;

            // 連打（高速スクロール等）時は最後の1回だけ反映
            if (pdfViewerSyncIsJumping) {
                pdfViewerSyncPendingPage = targetPage;
                return;
            }
            pdfViewerSyncIsJumping = true;
            try {
                await jumpToPage(targetPage, { updateUrl: true, preserveScroll: true });
            } finally {
                pdfViewerSyncIsJumping = false;
                if (pdfViewerSyncPendingPage && pdfViewerSyncPendingPage !== currentPage) {
                    const p = pdfViewerSyncPendingPage;
                    pdfViewerSyncPendingPage = null;
                    // 次のtickで反映（呼び出しスタックを浅くする）
                    setTimeout(() => {
                        jumpToPage(p, { updateUrl: true, preserveScroll: true });
                    }, 0);
                } else {
                    pdfViewerSyncPendingPage = null;
                }
            }
        };

        app.eventBus.on('pagechanging', handler);
        iframe._pageChangingHandler = handler;
        iframe.dataset.pageSyncAttached = '1';
        iframe.dataset.pageSyncFor = viewerKey;
        pdfViewerSyncAttachInProgress = false;
    };

    tryAttach();
}

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

        // 「登録して全置換」ボタンのカスタムイベントを受けて全置換処理を実行
        window.addEventListener('dict-replace-all', async function(e) {
            if (typeof dictReplaceAll === 'function') {
                await dictReplaceAll();
            } else {
                alert('全置換関数(dictReplaceAll)が見つかりません。');
            }
        });
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
    const { updateUrl = true, replaceHistory = false, forceRender = false, preserveScroll = false } = options;

    const targetPage = clampPage(pageNum);

    console.log("jumpToPage:pageNum " + pageNum);
    console.log("currentPage " + currentPage);
    console.log("pageInput.value" + document.getElementById("pageInput").value);

    // 同一ページ指定の場合は、通常はURL同期のみ。
    // ただしデータ更新後などは forceRender で再描画する。
    if (targetPage === currentPage) {
        if (typeof ensurePageFresh === 'function') {
            await ensurePageFresh(targetPage);
        }
        const srcPanel = document.getElementById("srcPanel");
        const savedScrollTop = (preserveScroll && srcPanel) ? srcPanel.scrollTop : null;
        const savedParagraphIndex = (typeof currentParagraphIndex === 'number') ? currentParagraphIndex : 0;

        document.getElementById("pageInput").value = currentPage;
        if (updateUrl) {
            updateUrlForPage(currentPage, { replace: replaceHistory });
        }

        // 初回遷移時など、同一ページでもPDFビューアが未ロードの場合があるため必ず反映する。
        ensurePdfViewerLoaded(currentPage);
        setPdfViewerPage(currentPage);

        if (forceRender) {
            renderParagraphs({ resetScrollTop: !preserveScroll });
            document.getElementById("srcPanel").focus();

            if (preserveScroll) {
                setCurrentParagraph(savedParagraphIndex, false, { scrollIntoView: false, scrollBehavior: 'auto' });
                if (srcPanel && savedScrollTop !== null) {
                    srcPanel.scrollTop = savedScrollTop;
                }
            } else {
                setCurrentParagraph(0, false, { scrollIntoView: false });
            }
        }
        return;
    }

    if (isPageEdited) {
        await saveCurrentPageOrder(); // await を追加
    }

    // 保存後にページを移動する
    currentPage = targetPage;
    document.getElementById("pageInput").value = currentPage;

    if (typeof ensurePageFresh === 'function') {
        await ensurePageFresh(currentPage);
    }

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

    // PDF.js 側のページ移動（サムネイル/ページリスト等）で ParaParaTrans 側も追従する
    attachPdfViewerPageSync();
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
        // アプリ側起因のページ変更としてマーク（イベントループ抑制）
        pdfViewerLastAppSetPage = pageNum;
        pdfViewerLastAppSetAt = Date.now();
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

    // Pointer Events + setPointerCapture でドラッグの取りこぼしを防ぐ
    function setupResizerPointerDrag(resizerEl, {
        onStart,
        onMove,
        onEnd,
    }) {
        if (!resizerEl) return;

        let isDragging = false;
        let activePointerId = null;
        let cleanupWindowListeners = null;

        const endDrag = (reason = 'end') => {
            if (!isDragging) return;
            isDragging = false;

            document.body.classList.remove('is-resizing');
            if (overlay) overlay.style.display = 'none';

            try {
                if (activePointerId != null) {
                    resizerEl.releasePointerCapture(activePointerId);
                }
            } catch (_) {
                // ignore
            }

            activePointerId = null;
            resizerEl.removeEventListener('pointermove', handlePointerMove);
            resizerEl.removeEventListener('pointerup', handlePointerUp);
            resizerEl.removeEventListener('pointercancel', handlePointerCancel);
            resizerEl.removeEventListener('lostpointercapture', handleLostPointerCapture);
            if (cleanupWindowListeners) {
                cleanupWindowListeners();
                cleanupWindowListeners = null;
            }
            if (onEnd) onEnd(reason);
        };

        const handlePointerMove = (e) => {
            if (!isDragging) return;
            if (activePointerId != null && e.pointerId !== activePointerId) return;
            e.preventDefault();
            if (onMove) onMove(e);
        };
        const handlePointerUp = (e) => {
            if (activePointerId != null && e.pointerId !== activePointerId) return;
            e.preventDefault();
            endDrag('pointerup');
        };
        const handlePointerCancel = () => endDrag('pointercancel');
        const handleLostPointerCapture = () => endDrag('lostpointercapture');

        resizerEl.addEventListener('pointerdown', (e) => {
            // 左ボタン/主ポインタのみ（右クリックやマルチタッチを除外）
            if (e.button !== 0 || e.isPrimary === false) return;
            e.preventDefault();

            isDragging = true;
            activePointerId = e.pointerId;
            document.body.classList.add('is-resizing');
            if (overlay) overlay.style.display = 'block';

            if (onStart) onStart(e);
            try {
                resizerEl.setPointerCapture(activePointerId);
            } catch (_) {
                // ignore
            }

            resizerEl.addEventListener('pointermove', handlePointerMove);
            resizerEl.addEventListener('pointerup', handlePointerUp);
            resizerEl.addEventListener('pointercancel', handlePointerCancel);
            resizerEl.addEventListener('lostpointercapture', handleLostPointerCapture);

            // Alt+Tab 等でupが来ないケースの保険
            const onBlur = () => endDrag('blur');
            const onVisibilityChange = () => {
                if (document.visibilityState !== 'visible') endDrag('visibilitychange');
            };
            window.addEventListener('blur', onBlur);
            document.addEventListener('visibilitychange', onVisibilityChange);
            cleanupWindowListeners = () => {
                window.removeEventListener('blur', onBlur);
                document.removeEventListener('visibilitychange', onVisibilityChange);
            };
        });
    }

    let startX1 = 0;
    let startWidthToc = 0;
    const minTocWidth = 200;
    setupResizerPointerDrag(resizer1, {
        onStart: (e) => {
            startX1 = e.clientX;
            startWidthToc = tocPanel.getBoundingClientRect().width;
        },
        onMove: (e) => {
            const dx = e.clientX - startX1;
            const newWidth = Math.max(minTocWidth, startWidthToc + dx);
            tocPanel.style.width = newWidth + 'px';
        },
    });

    // PDFパネルとsrcPanelの間のリサイズ
    const resizer2 = document.getElementById('resizer2');
    let startX2 = 0;
    let startWidthPdf = 0;
    const minPdfWidth = 200; // 最小幅を200pxに設定（必要に応じて調整）

    setupResizerPointerDrag(resizer2, {
        onStart: (e) => {
            startX2 = e.clientX;
            startWidthPdf = pdfPanel.getBoundingClientRect().width;
        },
        onMove: (e) => {
            const dx = e.clientX - startX2;
            // 左方向のドラッグで幅が縮む
            let newWidth = startWidthPdf + dx;
            if (newWidth < minPdfWidth) {
                newWidth = minPdfWidth;
            }
            pdfPanel.style.width = newWidth + 'px';
        },
        onEnd: () => {
            // リサイズ完了後に「page-width」を再適用
            setTimeout(fitToWidth, 100);
        },
    });
}

async function saveForce() {
    isPageEdited = true;
    saveCurrentPageOrder();
    updateBookInfo();
}
