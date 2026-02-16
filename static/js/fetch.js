function canUseSessionStorage() {
    try {
        return typeof window !== 'undefined' && !!window.sessionStorage;
    } catch (e) {
        return false;
    }
}

function getPageCacheKey() {
    return `ppt.pages.${encodeURIComponent(pdfName || '')}`;
}

function restorePageCacheFromSession() {
    if (!canUseSessionStorage()) return false;
    if (!bookData || !bookData.__json_mtime) return false;
    const key = getPageCacheKey();
    let raw = null;
    try {
        raw = window.sessionStorage.getItem(key);
    } catch (e) {
        return false;
    }
    if (!raw) return false;

    try {
        const payload = JSON.parse(raw);
        if (!payload || payload.mtime !== bookData.__json_mtime) return false;
        if (!payload.pages || typeof payload.pages !== 'object') return false;
        bookData.pages = payload.pages;
        return true;
    } catch (e) {
        return false;
    }
}

function savePageCacheToSession() {
    if (!canUseSessionStorage()) return false;
    if (!bookData || !bookData.__json_mtime) return false;
    if (!bookData.pages || typeof bookData.pages !== 'object') return false;
    const key = getPageCacheKey();
    const payload = {
        mtime: bookData.__json_mtime,
        pages: bookData.pages,
    };
    try {
        window.sessionStorage.setItem(key, JSON.stringify(payload));
        return true;
    } catch (e) {
        return false;
    }
}

function clearPageCacheForSession() {
    if (!canUseSessionStorage()) return;
    const key = getPageCacheKey();
    try {
        window.sessionStorage.removeItem(key);
    } catch (e) {
        // ignore
    }
}

async function fetchBookData() {
    try {
        const metaRes = await fetch(`/api/book_meta/${encodePdfNamePath(pdfName)}`);
        if (metaRes.status === 206) {
            confirm("まだパラグラフ抽出がされていません。");
            return;
        }
        if (!metaRes.ok) {
            throw new Error(`HTTP error! status: ${metaRes.status}`);
        }

        const metaPayload = await metaRes.json();
        const meta = metaPayload?.meta ?? metaPayload;

        // bookData をメタ情報で初期化（pages はページ単位で遅延ロード）
        bookData = {
            ...(meta || {}),
            pages: {},
            toc: [],
        };
        bookData.__json_mtime = meta?.json_mtime ?? null;

        document.getElementById("titleInput").value = bookData.title;
        document.getElementById("pageCount").innerText = bookData.page_count;
        document.getElementById("pageInput").max = bookData.page_count;

        updateTransStatusCounts(bookData.trans_status_counts);
        updateBookStyles();

        const restored = restorePageCacheFromSession();
        const hasCachedPage = !!bookData.pages?.[String(currentPage)];

        // 目次と表示ページを並列に取得
        await Promise.all([
            fetchAndApplyToc(),
            (restored && hasCachedPage) ? Promise.resolve(true) : fetchAndApplyPage(currentPage),
        ]);

        showToc();
        await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
        if (typeof enablePagePrefetch === 'function') {
            enablePagePrefetch();
        }
    } catch (error) {
        console.error("Error fetching book data:", error);
        alert("書籍データの取得中にエラーが発生しました。"); // ユーザーへの通知
    }
}

async function fetchAndApplyToc() {
    try {
        const response = await fetch(`/api/book_toc/${encodePdfNamePath(pdfName)}`);
        if (!response.ok) {
            return false;
        }
        const data = await response.json();
        if (data.status !== 'ok') {
            return false;
        }
        if (!Array.isArray(data.toc)) {
            return false;
        }
        bookData.toc = data.toc;
        bookData.__toc_stale = false;
        return true;
    } catch (e) {
        console.warn('fetchAndApplyToc failed:', e);
        return false;
    }
}

function applyBookDelta(delta) {
    if (!delta || typeof delta !== 'object') return false;

    let changed = false;

    if (delta.pages && typeof delta.pages === 'object') {
        if (!bookData.pages || typeof bookData.pages !== 'object') {
            bookData.pages = {};
        }
        if (bookData.__stale_token && !bookData.__page_fresh_token) {
            bookData.__page_fresh_token = {};
        }
        for (const [pageKey, pageObj] of Object.entries(delta.pages)) {
            bookData.pages[pageKey] = pageObj;
            if (bookData.__stale_token && bookData.__page_fresh_token) {
                bookData.__page_fresh_token[String(pageKey)] = bookData.__stale_token;
            }
            changed = true;

            // TOC の部分更新（該当ページに見出しがあれば反映）
            if (Array.isArray(bookData.toc) && pageObj && pageObj.paragraphs) {
                for (const p of Object.values(pageObj.paragraphs)) {
                    if (!p) continue;
                    const blockTag = p.block_tag;
                    const joinFlag = Number(p?.join ?? 0);
                    if (!/^h[1-6]$/.test(blockTag) || joinFlag === 1) continue;

                    const rowId = `${p.page_number}_${p.id}`;
                    const existing = bookData.toc.find((t) => t && t.rowId === rowId);
                    if (existing) {
                        existing.src_joined = p.src_joined;
                        existing.trans_text = p.trans_text;
                        existing.block_tag = p.block_tag;
                        existing.order = p.order || 0;
                        existing.column_order = p.column_order || 0;
                    }
                }
            }
        }
    }

    if (delta.trans_status_counts && typeof delta.trans_status_counts === 'object') {
        bookData.trans_status_counts = delta.trans_status_counts;
        updateTransStatusCounts(bookData.trans_status_counts);
        changed = true;
    }

    if (changed) {
        savePageCacheToSession();
    }

    return changed;
}

function markAllPagesStale() {
    // 全体更新系操作の後、他ページの表示が古くなるのを防ぐため
    // ページ遷移時に /api/book_page で最新を取る
    bookData.__stale_token = Date.now();
    bookData.__page_fresh_token = bookData.__page_fresh_token || {};
    bookData.__toc_stale = true;
    clearPageCacheForSession();
}

async function fetchAndApplyPage(pageNum) {
    try {
        const tFetch = (window.PERF_NAV && typeof perfNow === 'function') ? perfNow() : null;
        const url = `/api/book_page/${encodePdfNamePath(pdfName)}/${encodeURIComponent(pageNum)}`;
        const response = await fetch(url);
        if (!response.ok) {
            return false;
        }
        let data = null;
        if (tFetch !== null && typeof perfLog === 'function') {
            const tRead = perfNow();
            const rawText = await response.text();
            const tParse = perfNow();
            data = JSON.parse(rawText);
            const tDone = perfNow();
            const sizeKb = (rawText.length / 1024).toFixed(1);
            if (typeof performance !== 'undefined' && typeof performance.getEntriesByName === 'function') {
                const absUrl = new URL(url, window.location.href).toString();
                const entries = performance.getEntriesByName(absUrl) || [];
                const entry = entries.length > 0 ? entries[entries.length - 1] : null;
                if (entry) {
                    const ttfb = (entry.responseStart - entry.startTime).toFixed(1);
                    const xfer = (entry.responseEnd - entry.responseStart).toFixed(1);
                    const net = entry.duration.toFixed(1);
                    perfLog("fetchAndApplyPage(net)", tFetch, `(page ${pageNum}, ttfb ${ttfb} ms, xfer ${xfer} ms, net ${net} ms)`);
                    const reqStart = (entry.requestStart - entry.startTime).toFixed(1);
                    const respStart = (entry.responseStart - entry.startTime).toFixed(1);
                    const respEnd = (entry.responseEnd - entry.startTime).toFixed(1);
                    perfLog("fetchAndApplyPage(timeline)", tFetch, `(page ${pageNum}, request ${reqStart} ms, response ${respStart}..${respEnd} ms)`);
                } else {
                    perfLog("fetchAndApplyPage(net)", tFetch, `(page ${pageNum}, no ResourceTiming entry)`);
                }
            }
            const serverTiming = response.headers.get('server-timing');
            if (serverTiming) {
                perfLog("fetchAndApplyPage(server)", tFetch, `(page ${pageNum}, ${serverTiming})`);
            }
            perfLog("fetchAndApplyPage(fetch)", tFetch, `(page ${pageNum})`);
            perfLog("fetchAndApplyPage(read)", tRead, `(page ${pageNum}, kb ${sizeKb})`);
            perfLog("fetchAndApplyPage(parse)", tParse, `(page ${pageNum})`);
            perfLog("fetchAndApplyPage(total)", tFetch, `(page ${pageNum})`);
        } else {
            data = await response.json();
        }
        if (data.status !== 'ok') {
            return false;
        }

        if (!bookData.pages || typeof bookData.pages !== 'object') {
            bookData.pages = {};
        }
        bookData.pages[String(data.page_key)] = data.page;

        if (data.trans_status_counts) {
            bookData.trans_status_counts = data.trans_status_counts;
            updateTransStatusCounts(bookData.trans_status_counts);
        }

        // stale 管理
        if (bookData.__stale_token) {
            bookData.__page_fresh_token = bookData.__page_fresh_token || {};
            bookData.__page_fresh_token[String(data.page_key)] = bookData.__stale_token;
        }

        savePageCacheToSession();

        return true;
    } catch (e) {
        console.warn('fetchAndApplyPage failed:', e);
        return false;
    }
}

async function ensurePageFresh(pageNum) {
    const tFresh = (window.PERF_NAV && typeof perfNow === 'function') ? perfNow() : null;
    const pageKey = String(pageNum);

    // 未ロードなら常に取得
    if (!bookData?.pages || !bookData.pages[pageKey]) {
        const ok = await fetchAndApplyPage(pageNum);
        if (tFresh !== null && typeof perfLog === 'function') {
            perfLog("ensurePageFresh(miss)", tFresh, `(page ${pageNum})`);
        }
        return ok;
    }

    const staleToken = bookData.__stale_token;
    if (!staleToken) {
        if (tFresh !== null && typeof perfLog === 'function') {
            perfLog("ensurePageFresh(hit)", tFresh, `(page ${pageNum})`);
        }
        return true;
    }

    const freshMap = bookData.__page_fresh_token || {};
    if (freshMap[pageKey] === staleToken) {
        if (tFresh !== null && typeof perfLog === 'function') {
            perfLog("ensurePageFresh(fresh)", tFresh, `(page ${pageNum})`);
        }
        return true;
    }
    const ok = await fetchAndApplyPage(pageNum);
    if (tFresh !== null && typeof perfLog === 'function') {
        perfLog("ensurePageFresh(refetch)", tFresh, `(page ${pageNum})`);
    }
    return ok;
}

/** @function transPage */
async function transPage() {
    await saveCurrentPageOrder(); // 順序を保存してから翻訳 (saveOrderもasyncにする必要あり)
    if (!confirm("現在のページを翻訳します。よろしいですか？")) return;
    showLog();

    let applied = false;

    try {
        const response = await fetch(`/api/paraparatrans/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: '&start_page=' + encodeURIComponent(currentPage) +
                '&end_page=' + encodeURIComponent(currentPage)
        });
        const data = await response.json();
        if (data.status === "ok") {
            console.log('翻訳が成功しました。');
            applied = applyBookDelta(data.delta || data.data);
            if (data.stats) {
                alert(formatTranslationStatsMessage("ページ翻訳が完了しました", data.stats));
            } else {
                alert("ページ翻訳が完了しました");
            }
        } else {
            console.error('エラー:', data.message);
            alert('翻訳エラー(response): ' + data.message);
        }
        hideLog();
    } catch (error) {
        console.error('Error:', error);
        alert('翻訳中にエラー(catch)');
    } finally {
        // 成功時は差分適用で全体再取得を回避。適用できなかった場合のみ従来通り全体再取得する。
        if (applied) {
            await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
        } else {
            await fetchBookData();
        }
    }
}

/** @function dictReplacePage */
async function dictReplacePage() {
    await saveCurrentPageOrder(); // 順序を保存してから置換
    if (!confirm("現在のページを対訳辞書で置換します。よろしいですか？")) return;
    showLog();

    let applied = false;

    try {
        const response = await fetch(`/api/dict_replace_pages/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: '&start_page=' + encodeURIComponent(currentPage) +
                '&end_page=' + encodeURIComponent(currentPage)
        });
        const data = await response.json();
        if (data.status === "ok") {
            console.log('ページ対訳置換が成功しました。');
            applied = applyBookDelta(data.delta);
        } else {
            console.error('エラー:', data.message);
            alert('ページ対訳置換エラー(response): ' + data.message);
        }
        hideLog();
    } catch (error) {
        console.error('Error:', error);
        alert('ページ対訳置換中にエラー(catch)');
    } finally {
        if (applied) {
            await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
        } else {
            await fetchBookData();
        }
    }
}

/** @function alignTransBySrcJoined */
async function alignTransBySrcJoined() {
    await saveCurrentPageOrder();
    const msg = "同一src_joinedの訳を文書全体で揃えます。\nよろしいですか？";
    if (!confirm(msg)) return;
    showLog();

    let applied = false;

    try {
        const response = await fetch(`/api/align_trans_by_src_joined/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: ''
        });
        const data = await response.json();
        if (data.status === "ok") {
            console.log(`訳揃えが成功しました。updated=${data.changed}`);
            applied = applyBookDelta(data.delta);
            // 文書全体が対象なので目次も更新しておく
            await fetchAndApplyToc();
            showToc();
        } else {
            console.error('エラー:', data.message);
            alert('訳揃えエラー(response): ' + data.message);
        }
        hideLog();
    } catch (error) {
        console.error('Error:', error);
        alert('訳揃え中にエラー(catch)');
    } finally {
        if (applied) {
            await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
        } else {
            await fetchBookData();
        }
    }
}

async function dictReplaceAll() {
    let msg = "全ページに対して対訳辞書による置換を行います";
    msg += "\nこの処理は時間がかかります。";
    msg += "\n応答がなくてもページを閉じないでください。";
    msg += "\n\nよろしいですか？";
    if (!confirm(msg)) return;
    showLog();

    let applied = false;

    try {
        const response = await fetch(`/api/dict_replace_pages/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: '&start_page=1' +
                '&end_page=' + bookData.page_count
        });
        const data = await response.json();
        if (data.status === "ok") {
            applied = applyBookDelta(data.delta);
            alert("全対訳置換が成功しました");
        } else {
            console.error("対訳置換エラー:", data.message);
            alert("対訳置換エラー: " + data.message);
        }
    } catch (error) {
        console.error("dictReplaceAllエラー:", error);
        alert("dictReplaceAll エラー: " + error);
    } finally {
        if (applied) {
            await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
        } else {
            await fetchBookData();
        }
    }
}


async function transAllPages() {
    await saveCurrentPageOrder(); // saveOrderもasyncにする必要あり
    const totalPages = bookData.page_count;
    if (!confirm(`全 ${totalPages} ページを翻訳します。よろしいですか？`)) return;
    showLog();

    let applied = false;

    try {
        const response = await fetch(`/api/paraparatrans/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: '&start_page=' + encodeURIComponent(1) +
                '&end_page=' + encodeURIComponent(totalPages)
        });
        const data = await response.json();
        if (data.status === "ok") {
            console.log('翻訳が成功しました。');
            applied = applyBookDelta(data.delta || data.data);
            await fetchAndApplyToc();
            showToc();
            if (data.stats) {
                alert(formatTranslationStatsMessage("全ページ翻訳が完了しました", data.stats));
            } else {
                alert("全ページ翻訳が完了しました");
            }
        } else {
            console.error('エラー:', data.message);
            alert('翻訳エラー(response): ' + data.message);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('翻訳中にエラー(catch)');
    } finally {
        if (applied) {
            await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
        } else {
            await fetchBookData();
        }
    }
}

function formatTranslationStatsMessage(title, stats) {
    const pages = stats.pages_processed ?? 0;
    const target = stats.paragraphs_target ?? 0;
    const translated = stats.translated ?? 0;
    const failed = stats.failed ?? 0;
    const fallback = stats.translated_fallback ?? 0;
    const skippedEmpty = stats.skipped_empty_src ?? 0;
    const skippedHF = stats.skipped_header_footer ?? 0;
    const missing = stats.missing_from_batch ?? 0;

    let msg = `${title}\n`;
    msg += `ページ数: ${pages}\n`;
    msg += `対象段落: ${target}\n`;
    msg += `翻訳成功: ${translated}\n`;
    msg += `翻訳失敗: ${failed}\n`;
    if (fallback > 0) msg += `フォールバック(単体翻訳): ${fallback}\n`;
    if (missing > 0) msg += `マーカー欠落(推定): ${missing}\n`;
    if (skippedEmpty > 0) msg += `スキップ(空): ${skippedEmpty}\n`;
    if (skippedHF > 0) msg += `スキップ(header/footer): ${skippedHF}\n`;
    return msg.trim();
}

async function extractParagraphs(){
    if(!confirm("PDFを解析してJSONを新規生成します。よろしいですか？")) return;
    showLog();

    let form = new FormData();
    try {
        const response = await fetch(`/api/extract_paragraphs/${encodePdfNamePath(pdfName)}`, {
            method: "POST",
            body: form
        });
        const res = await response.json();
        if(res.status === "ok"){
            alert("パラグラフ抽出完了");
            location.reload(); // リロード前にfetchBookDataを呼ぶ意味は薄い
            // await fetchBookData(); // 必要ならリロード後に実行されるようにする
        } else {
            alert(res.message);
        }
    } catch (error) {
        console.error("extractParagraphs error:", error);
        alert("パラグラフ抽出中にエラーが発生しました。");
    }
}


async function autoTagging() {
    let msg = "全ページのblock_tagがpであるパラグラフに対して独自ルールでおおまかなタグ付けを行います";
    msg += "\n1回だけの実行を推奨します。";
    msg += "\nすでにp以外に設定しているblock_tagは変更されませんが、見出しからpに変更したパラグラフは再度見出しに戻ります。";
    msg += "\n\nよろしいですか？";
    if (!confirm(msg)) return;

    try {
        const body = '&current_page=' + encodeURIComponent(currentPage);
        const response = await fetch(`/api/auto_tagging/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body
        });
        const result = await response.json();
        if (result.status === "ok") {
            alert("自動タグ付けが成功しました");
            markAllPagesStale();
            const applied = applyBookDelta(result.delta);
            await fetchAndApplyToc();
            showToc();
            if (applied) {
                await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
            } else {
                await fetchBookData();
            }
        } else {
            alert("自動タグ付けエラー: " + result.message);
        }
    } catch (error) {
        console.error("autoTagging error:", error);
        alert("自動タグ付け中にエラーが発生しました");
    }
}


async function rebuildSrcTextFromHtml() {
    let msg = "全ページの段落について src_html から src_text を作り直し、シンボル置換（symbolfont_dict）を適用します";
    msg += "\n（辞書を更新した後に何度でも実行できます）";
    msg += "\n\nよろしいですか？";
    if (!confirm(msg)) return;

    await saveCurrentPageOrder();
    try {
        const body = '&current_page=' + encodeURIComponent(currentPage);
        const response = await fetch(`/api/rebuild_src_text/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body
        });
        const result = await response.json();
        if (result.status === "ok") {
            alert(result.message || "シンボル置換が完了しました");
            markAllPagesStale();
            const applied = applyBookDelta(result.delta);
            await fetchAndApplyToc();
            showToc();
            if (applied) {
                await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
            } else {
                await fetchBookData();
            }
        } else {
            alert("シンボル置換エラー: " + (result.message || "unknown"));
        }
    } catch (error) {
        console.error("rebuildSrcTextFromHtml error:", error);
        alert("シンボル置換中にエラーが発生しました");
    }
}

async function taggingByStyle(targetStyle, targetTag) {
    try {
        const response = await fetch(`/api/update_block_tags_by_style/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                target_style: targetStyle,
                target_tag: targetTag,
                current_page: currentPage
            })
        });

        const result = await response.json();

        if (result.status === "ok") {
            alert("スタイルの一括更新が完了しました。");
            markAllPagesStale();
            const applied = applyBookDelta(result.delta);
            await fetchAndApplyToc();
            showToc();
            if (applied) {
                await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
            } else {
                await fetchBookData();
            }
        } else {
            alert(`スタイルの一括更新に失敗しました: ${result.message}`);
        }
    } catch (error) {
        console.error('スタイル一括更新エラー:', error);
        alert('スタイルの一括更新中にエラーが発生しました。');
    }
}


async function taggingByStyleY(targetStyle, y0, y1, action) {
    try {
        const response = await fetch(`/api/update_block_tags_by_style_y/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                target_style: targetStyle,
                y0: y0,
                y1: y1,
                action: action,
                current_page: currentPage
            })
        });

        const result = await response.json();

        if (result.status === "ok") {
            alert(result.message || "スタイル+Y範囲の一括更新が完了しました。");
            markAllPagesStale();
            const applied = applyBookDelta(result.delta);
            await fetchAndApplyToc();
            showToc();
            if (applied) {
                await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
            } else {
                await fetchBookData();
            }
        } else {
            alert(`スタイル+Y範囲の一括更新に失敗しました: ${result.message}`);
        }
    } catch (error) {
        console.error('スタイル+Y範囲 一括更新エラー:', error);
        alert('スタイル+Y範囲の一括更新中にエラーが発生しました。');
    }
}


async function joinParagraphs() {
    let msg = "全ページのパラグラフに対して結合処理を行います";
    msg += "\n「置換文」列の置換はいったんリセットされます。";
    msg += "\nこの処理で「訳文」列が変更されることはありません。";
    msg += "\n\nよろしいですか？";
    if (!confirm(msg)) return;


    await saveCurrentPageOrder(); // 順序を保存してから翻訳 (saveOrderもasyncにする必要あり)
    try {
        const response = await fetch(`/api/join_replaced_paragraphs/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: '&current_page=' + encodeURIComponent(currentPage)
        });
        const data = await response.json();
        if (data.status === "ok") {
            const applied = applyBookDelta(data.delta);
            alert("「連結文」「置換文」列を更新しました");
            markAllPagesStale();
            await fetchAndApplyToc();
            showToc();
            if (applied) {
                await jumpToPage(currentPage, { replaceHistory: true, forceRender: true, preserveScroll: true });
            } else {
                await fetchBookData();
            }
        } else {
            alert("連結文結合エラー: " + data.message);
        }
    } catch (error) {
        console.error("autoTagging error:", error);
        alert("連結文結合中にエラーが発生しました");
    }
}

async function dictCreate() {
    try {
        const response = await fetch(`/api/dict_create/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        });
        const data = await response.json();
        if (data.status === "ok") {
            alert("辞書生成が成功しました");
        } else {
            alert("辞書生成エラー: " + data.message);
        }
    } catch (error) {
        console.error("dictCreate error:", error); // エラーログのタイポ修正
        alert("辞書生成中にエラーが発生しました");
    }
}

async function dictTrans() {
    try {
        const response = await fetch(`/api/dict_trans/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        });
        const data = await response.json();
        if (data.status === "ok") {
            alert("辞書翻訳が成功しました");
        } else {
            alert("辞書翻訳エラー: " + data.message);
        }
    } catch (error) {
        console.error("dictTrans error:", error); // エラーログのタイポ修正
        alert("辞書翻訳中にエラーが発生しました");
    }
}

/** * @function updateTransStatusCounts
 * @param {Object} counts - 翻訳ステータスのカウントオブジェクト
 * ページ内順序再発行＆保存処理
 */
async function saveCurrentPageOrder() {
    const container = document.getElementById('srcParagraphs');
    const children = container.children;
    sendParagraphs = [];

    // ページ内のパラグラフをループして、順序を取得
    for (let i = 0; i < children.length; i++) {
        const divP = children[i];
        const idElem = divP.querySelector('.paragraph-id');
        if (!idElem) continue;

        const id = idElem.innerText.trim();
        const groupClass = Array.from(divP.classList).find(cls => cls.startsWith('group-id-'));
        // group_id は文字列として扱う（数値にパースしない）
        const groupId = groupClass ? groupClass.replace('group-id-', '') : undefined;

        paragraphDict = bookData["pages"][currentPage]["paragraphs"][id];
        // 本当はpを更新してるのでorder以外の更新は不要
        if (paragraphDict) {
            paragraphDict.order = i + 1; // 1-based index
            // bookData["pages"][currentPage]["paragraphs"][id].block_tag = blockTag;
            paragraphDict.group_id = groupId;
        } else {
            throw new Error(`saveOrder: Paragraph data not found for ID ${currentPage} ${id} in paragraphs`);
        }

        // 送信用配列にデータを追加
        sendParagraphs.push(
            {
                id: id,
                page_number: paragraphDict.page_number,
                order: paragraphDict.order,
                block_tag: paragraphDict.block_tag,
                trans_status: paragraphDict.trans_status,
                group_id: paragraphDict?.group_id,
                join: paragraphDict?.join
            }
        );
    }

    console.log("saveOrder: Sending updates:", sendParagraphs.length);
    await updateParagraphs(sendParagraphs); // updateParagraphsもasyncなのでawait
}

async function exportHtml() {
    await saveCurrentPageOrder(); // saveOrderもasyncにする必要あり
    try {
        const response = await fetch(`/api/export_html/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: '' // 特に送信するデータがなければ空文字でOK
        });
        const data = await response.json();
        if (data.status === "ok") {
            // 生成後、ダウンロードも実行
            window.location.href = `/api/download_html/${encodePdfNamePath(pdfName)}`;
            alert(`対訳HTMLを出力しました: ${data.path ?? ''}`);
        } else {
            alert("エラー: " + data.message);
        }
    } catch (error) {
        console.error("Error exporting HTML:", error);
        alert("対訳HTML出力中にエラーが発生しました");
    }
}


async function exportDocStructure() {
    // 未保存の順序・group_id などが構造に含まれるため、先に保存
    await saveCurrentPageOrder();
    try {
        const response = await fetch(`/api/export_structure/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: ''
        });
        const data = await response.json();
        if (data.status === "ok") {
            // 生成後、ダウンロードも実行
            window.location.href = `/api/download_structure/${encodePdfNamePath(pdfName)}`;
            alert(`構造ファイルを出力しました: ${data.path}`);
        } else {
            alert("エラー: " + data.message);
        }
    } catch (error) {
        console.error("Error exporting doc structure:", error);
        alert("構造ファイル出力中にエラーが発生しました");
    }
}


function openDataExportDialog() {
    const dialog = document.getElementById('dataExportDialog');
    if (!dialog) return;
    dialog.style.display = 'flex';
    updateDataExportFieldState();
    reloadDictSelection();
}


function openDictMaintenance() {
    const pdfNameParam = window.pdfName ? `?pdf_name=${encodeURIComponent(window.pdfName)}` : '';
    window.open(`/dict_maintenance${pdfNameParam}`, '_blank', 'noopener');
}

function openDictMaintenanceForPath(dictPath) {
    if (!dictPath) {
        openDictMaintenance();
        return;
    }
    const pdfNameParam = window.pdfName ? `&pdf_name=${encodeURIComponent(window.pdfName)}` : '';
    const url = `/dict_maintenance?dict_path=${encodeURIComponent(dictPath)}${pdfNameParam}`;
    window.open(url, '_blank', 'noopener');
}

const dictSelectionState = {
    configDicts: [],
    bookDict: null,
    selectedPaths: [],
};

function setDictSelectionStatus(message, isError = false) {
    const status = document.getElementById('dictSelectionStatus');
    if (!status) return;
    status.textContent = message || '';
    status.style.color = isError ? '#b00020' : '#0a7a0a';
}

function getDictSelectionItems() {
    const items = [];
    dictSelectionState.configDicts.forEach((item) => {
        if (!item?.path) return;
        items.push({
            path: item.path,
            label: item.label || item.path,
        });
    });
    if (dictSelectionState.bookDict?.path) {
        items.push({
            path: dictSelectionState.bookDict.path,
            label: dictSelectionState.bookDict.label || dictSelectionState.bookDict.path,
        });
    }
    return items;
}

function moveSelectedDict(path, delta) {
    const idx = dictSelectionState.selectedPaths.indexOf(path);
    if (idx < 0) return;
    const next = idx + delta;
    if (next < 0 || next >= dictSelectionState.selectedPaths.length) return;
    const temp = dictSelectionState.selectedPaths[idx];
    dictSelectionState.selectedPaths[idx] = dictSelectionState.selectedPaths[next];
    dictSelectionState.selectedPaths[next] = temp;
    renderDictSelection();
}

function toggleSelectedDict(path, checked) {
    const idx = dictSelectionState.selectedPaths.indexOf(path);
    if (checked && idx < 0) {
        dictSelectionState.selectedPaths.push(path);
    } else if (!checked && idx >= 0) {
        dictSelectionState.selectedPaths.splice(idx, 1);
    }
    renderDictSelection();
}

function renderDictSelection() {
    const container = document.getElementById('dictSelectionList');
    if (!container) return;
    container.innerHTML = '';

    const items = getDictSelectionItems();
    if (!items.length) {
        const empty = document.createElement('div');
        empty.textContent = '辞書がありません';
        container.appendChild(empty);
        return;
    }

    const selectedSet = new Set(dictSelectionState.selectedPaths);
    const selectedItems = dictSelectionState.selectedPaths.map((path) => {
        const item = items.find((entry) => entry.path === path);
        return item || { path, label: path };
    });
    const unselectedItems = items.filter((item) => !selectedSet.has(item.path));

    selectedItems.forEach((item, index) => {
        const row = document.createElement('div');
        row.className = 'dict-selection-row';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = true;
        checkbox.addEventListener('change', (e) => {
            toggleSelectedDict(item.path, e.target.checked);
        });

        const label = document.createElement('span');
        label.className = 'dict-selection-label';
        label.textContent = item.label;

        const actions = document.createElement('span');
        actions.className = 'dict-selection-actions';

        const upButton = document.createElement('button');
        upButton.type = 'button';
        upButton.textContent = '↑';
        upButton.disabled = index === 0;
        upButton.addEventListener('click', () => moveSelectedDict(item.path, -1));

        const downButton = document.createElement('button');
        downButton.type = 'button';
        downButton.textContent = '↓';
        downButton.disabled = index === selectedItems.length - 1;
        downButton.addEventListener('click', () => moveSelectedDict(item.path, 1));

        actions.appendChild(upButton);
        actions.appendChild(downButton);

        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.textContent = '編集';
        editButton.addEventListener('click', () => openDictMaintenanceForPath(item.path));

        row.appendChild(checkbox);
        row.appendChild(label);
        row.appendChild(actions);
        row.appendChild(editButton);
        container.appendChild(row);
    });

    unselectedItems.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'dict-selection-row';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = false;
        checkbox.addEventListener('change', (e) => {
            toggleSelectedDict(item.path, e.target.checked);
        });

        const label = document.createElement('span');
        label.className = 'dict-selection-label';
        label.textContent = item.label;

        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.textContent = '編集';
        editButton.addEventListener('click', () => openDictMaintenanceForPath(item.path));

        row.appendChild(checkbox);
        row.appendChild(label);
        row.appendChild(editButton);
        container.appendChild(row);
    });
}

async function reloadDictSelection() {
    if (!window.pdfName) return;
    setDictSelectionStatus('読み込み中...', false);
    try {
        const response = await fetch(`/api/dict/selection/${encodePdfNamePath(pdfName)}`);
        const data = await response.json();
        if (!response.ok || data.status !== 'ok') {
            throw new Error(data.message || `辞書一覧の取得に失敗しました (${response.status})`);
        }
        dictSelectionState.configDicts = Array.isArray(data.config_dicts) ? data.config_dicts : [];
        dictSelectionState.bookDict = data.book_dict || null;
        dictSelectionState.selectedPaths = Array.isArray(data.selected_paths) ? data.selected_paths : [];
        renderDictSelection();
        setDictSelectionStatus('読み込み完了', false);
    } catch (error) {
        console.error('dict selection load error:', error);
        setDictSelectionStatus(String(error), true);
    }
}

async function saveDictSelection() {
    if (!window.pdfName) return;
    setDictSelectionStatus('保存中...', false);
    try {
        const response = await fetch(`/api/dict/selection/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                dict_paths: dictSelectionState.selectedPaths,
            }),
        });
        const data = await response.json();
        if (!response.ok || data.status !== 'ok') {
            throw new Error(data.message || `保存に失敗しました (${response.status})`);
        }
        dictSelectionState.selectedPaths = Array.isArray(data.selected_paths) ? data.selected_paths : dictSelectionState.selectedPaths;
        renderDictSelection();
        setDictSelectionStatus('保存しました', false);
    } catch (error) {
        console.error('dict selection save error:', error);
        setDictSelectionStatus(String(error), true);
    }
}


function closeDataExportDialog() {
    const dialog = document.getElementById('dataExportDialog');
    if (!dialog) return;
    dialog.style.display = 'none';
    setDataExportStatus('');
}


function getSelectedExportFields() {
    const inputs = document.querySelectorAll('.data-export-field');
    const selected = [];
    inputs.forEach((input) => {
        if (input.checked) selected.push(input.value);
    });
    return selected;
}


function updateDataExportFieldState() {
    const inputs = document.querySelectorAll('.data-export-field');
    const selected = getSelectedExportFields();
    const isLimitReached = selected.length >= 2;

    inputs.forEach((input) => {
        if (!input.checked) {
            input.disabled = isLimitReached;
        } else {
            input.disabled = false;
        }
    });

    const hint = document.getElementById('dataExportFieldHint');
    if (hint) {
        hint.textContent = `2つまで選択できます。現在 ${selected.length} / 2`;
    }
}


function setDataExportStatus(message, isError = false) {
    const status = document.getElementById('dataExportStatus');
    if (!status) return;
    status.textContent = message || '';
    status.style.color = isError ? '#b00020' : '#0a7a0a';
}


async function exportTextOrMd() {
    await saveCurrentPageOrder();
    const formatSelect = document.getElementById('dataExportFormat');
    const includePage = document.getElementById('dataExportIncludePage');
    const includeHeader = document.getElementById('dataExportIncludeHeader');
    const includeFooter = document.getElementById('dataExportIncludeFooter');
    const includeRemove = document.getElementById('dataExportIncludeRemove');
    const fields = getSelectedExportFields();

    if (!fields.length || fields.length > 2) {
        alert('出力項目は1〜2件で選択してください。');
        return;
    }

    const format = formatSelect ? formatSelect.value : 'md';
    const includePageNumbers = !!includePage?.checked;
    const includeHeaderFlag = !!includeHeader?.checked;
    const includeFooterFlag = !!includeFooter?.checked;
    const includeRemoveFlag = !!includeRemove?.checked;

    setDataExportStatus('出力中...', false);

    try {
        const response = await fetch(`/api/export_text/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                format: format,
                fields: fields,
                include_page_numbers: includePageNumbers,
                include_header: includeHeaderFlag,
                include_footer: includeFooterFlag,
                include_remove: includeRemoveFlag
            })
        });
        const data = await response.json();
        if (data.status === 'ok') {
            window.location.href = `/api/download_text/${encodePdfNamePath(pdfName)}/${encodeURIComponent(format)}`;
            setDataExportStatus(`出力しました: ${data.path ?? ''}`, false);
        } else {
            setDataExportStatus(data.message || '出力に失敗しました', true);
            alert('エラー: ' + data.message);
        }
    } catch (error) {
        console.error('Error exporting text:', error);
        setDataExportStatus('テキスト出力中にエラーが発生しました', true);
        alert('テキスト出力中にエラーが発生しました');
    }
}


document.addEventListener('DOMContentLoaded', function () {
    const inputs = document.querySelectorAll('.data-export-field');
    inputs.forEach((input) => {
        input.addEventListener('change', updateDataExportFieldState);
    });
    updateDataExportFieldState();
});


function openDocStructurePicker() {
    const input = document.getElementById('docStructureFileInput');
    if (!input) {
        alert('ファイル選択UIが見つかりません');
        return;
    }
    // 同じファイルを連続で選択しても change が発火するようにクリア
    input.value = '';
    input.click();
}


async function importDocStructureFile(fileList) {
    try {
        if (!fileList || fileList.length === 0) return;
        const file = fileList[0];
        if (!file) return;

        const form = new FormData();
        form.append('file', file);

        const response = await fetch(`/api/import_structure/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            body: form
        });
        const data = await response.json();
        if (data.status === 'ok') {
            const msg = [
                '構造ファイルを取り込みました。',
                data.backup ? `バックアップ: ${data.backup}` : null,
                data.join_changed ? 'join変更が検出され、連結文を再構築しました。' : null,
            ].filter(Boolean).join('\n');
            alert(msg);
            await fetchBookData();
        } else {
            alert('エラー: ' + data.message);
        }
    } catch (error) {
        console.error('Error importing doc structure:', error);
        alert('構造ファイル取り込み中にエラーが発生しました');
    }
}

// updateParagraphs も fetch を使うので async にする
async function updateParagraphs(sendParagraphs, title = null) {
    const payload = {
        paragraphs: sendParagraphs,
        title: title || document.getElementById('titleInput').value
    };

    try {
        const response = await fetch(`/api/update_paragraphs/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (data.status === "ok") {
            isPageEdited = false;
            console.log("パラグラフ更新が成功しました");
            if (data.trans_status_counts) {
                updateTransStatusCounts(data.trans_status_counts);
            }
            if (data.reload_book_data) {
                await fetchBookData();
            }
        } else {
            console.error("パラグラフ更新エラー:", data.message);
            alert("パラグラフ更新エラー: " + data.message);
        }
    } catch (error) {
        console.error("パラグラフ更新中にエラーが発生しました:", error);
        alert("パラグラフ更新中にエラーが発生しました");
    }
}

async function transParagraph(paragraph, divSrc) {
    try {
        const textToTranslate = (paragraph?.src_replaced ?? '');
        const response = await fetch('/api/translate', {
            method: 'POST',
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ text: textToTranslate })
        });
        const data = await response.json();
        console.log("翻訳結果:", data.translated_text);
        if (data.status === "ok") {
            paragraph.trans_auto = data.translated_text;
            paragraph.trans_text = data.translated_text;
            paragraph.trans_status = "auto";
            divSrc.querySelector('.trans-auto').innerHTML = paragraph.trans_auto;
            divSrc.querySelector('.trans-text').innerHTML = paragraph.trans_text;
            let autoRadio = divSrc.querySelector(`input[name='status-${paragraph.id}'][value='auto']`);
            updateEditUiBackground(divSrc, paragraph.trans_status);
            if (autoRadio) { autoRadio.checked = true; }

            // ページ翻訳などで再読込された際に「未保存の訳」が英語に戻らないよう、ここで永続化する
            if (typeof saveParagraphData === 'function') {
                await saveParagraphData(paragraph);
            } else {
                console.warn('saveParagraphData is not available; translation will not be persisted.');
            }
        } else {
            console.error("パラグラフ更新エラー:", data.message);
            alert("パラグラフ更新エラー: " + data.message);
        }
    } catch (error) {
        // ユーザーにポップアップでエラーを通知
        console.error('Error:', error);
        alert('翻訳中にエラーが発生しました。詳細はコンソールを確認してください。');
    }
}

async function updateBookInfo() {
    try {
        const payload = {
            title: document.getElementById('titleInput').value,
            page_count: bookData.page_count, // ページ数を追加
            trans_status_counts: bookData.trans_status_counts // 翻訳ステータスカウントを追加
        };        
        const response = await fetch(`/api/update_book_info/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (data.status === "ok") {
            console.log("文書情報が正常に更新されました。");
        } else {
            console.error("文書情報更新エラー:", data.message);
            alert("文書情報更新エラー: " + data.message);
        }
    } catch (error) {
        console.error("文書情報更新中にエラーが発生しました:", error);
        alert("文書情報更新中にエラーが発生しました。");
    }
}
