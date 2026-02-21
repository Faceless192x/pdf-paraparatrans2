let selectedParagraphs = new Set(); // 選択されたパラグラフのIDを格納
// ページ内のパラグラフのインデックス
let currentParagraphIndex = 0;
//ページが編集されたことを表す変数
let isPageEdited = false;
let pendingMarkupSelection = null;
let pendingMarkupParagraphContext = null;

const MARKUP_COLUMN_CLASS_TO_KEY = {
    'src-text': 'src_text',
    'src-joined': 'src_joined',
    'src-replaced': 'src_replaced',
    'trans-auto': 'trans_auto',
    'trans-text': 'trans_text',
    'comment-text': 'comment',
};

const MARKUP_TARGET_COLUMN_SELECTOR = '.src-text, .src-joined, .src-replaced, .trans-auto, .trans-text, .comment-text';

function generateMarkupId() {
    return `mu_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function getMarkupToolsContainer() {
    return document.getElementById('markupTools');
}

function clearPendingMarkupSelection() {
    pendingMarkupSelection = null;
    pendingMarkupParagraphContext = null;
}

function showMarkupTools() {
    const tools = getMarkupToolsContainer();
    if (tools) tools.style.display = 'inline-flex';
}

function getColumnClassName(columnElement) {
    if (!columnElement) return null;
    for (const className of Object.keys(MARKUP_COLUMN_CLASS_TO_KEY)) {
        if (columnElement.classList.contains(className)) {
            return className;
        }
    }
    return null;
}

function findTextOffsetInElement(rootEl, targetNode, targetOffset) {
    if (!rootEl || !targetNode) return null;
    let offset = 0;
    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        if (node === targetNode) {
            return offset + Math.min(targetOffset, node.nodeValue.length);
        }
        offset += node.nodeValue.length;
    }
    return null;
}

function getSelectionInfoForMarkup(selection) {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    const startNode = range.startContainer;
    const endNode = range.endContainer;
    if (!startNode || !endNode) return null;

    const startElement = startNode.nodeType === Node.ELEMENT_NODE ? startNode : startNode.parentElement;
    const endElement = endNode.nodeType === Node.ELEMENT_NODE ? endNode : endNode.parentElement;
    if (!startElement || !endElement) return null;

    const startColumn = startElement.closest(MARKUP_TARGET_COLUMN_SELECTOR);
    const endColumn = endElement.closest(MARKUP_TARGET_COLUMN_SELECTOR);
    if (!startColumn || !endColumn || startColumn !== endColumn) return null;

    const paragraphBox = startColumn.closest('.paragraph-box');
    if (!paragraphBox) return null;

    const paragraphId = String((paragraphBox.id || '').replace('paragraph-', ''));
    if (!paragraphId) return null;

    const columnClassName = getColumnClassName(startColumn);
    if (!columnClassName) return null;

    const columnKey = MARKUP_COLUMN_CLASS_TO_KEY[columnClassName];
    if (!columnKey) return null;

    const start = findTextOffsetInElement(startColumn, range.startContainer, range.startOffset);
    const end = findTextOffsetInElement(startColumn, range.endContainer, range.endOffset);
    if (start == null || end == null) return null;

    const rangeStart = Math.min(start, end);
    const rangeEnd = Math.max(start, end);
    if (rangeStart === rangeEnd) return null;

    return {
        pageNumber: String(currentPage),
        paragraphId,
        columnClassName,
        columnKey,
        start: rangeStart,
        end: rangeEnd,
    };
}

function getParagraphContextForMarkup(selection) {
    if (!selection || selection.rangeCount === 0) return null;
    const range = selection.getRangeAt(0);
    const startNode = range.startContainer;
    if (!startNode) return null;

    const startElement = startNode.nodeType === Node.ELEMENT_NODE ? startNode : startNode.parentElement;
    if (!startElement) return null;

    const paragraphBox = startElement.closest('.paragraph-box');
    if (!paragraphBox) return null;

    const paragraphId = String((paragraphBox.id || '').replace('paragraph-', ''));
    if (!paragraphId) return null;

    return {
        pageNumber: String(currentPage),
        paragraphId,
    };
}

function removeExistingMarkupDecorations(columnElement) {
    if (!columnElement) return;
    const nodes = Array.from(columnElement.querySelectorAll('span.ppt-markup'));
    nodes.forEach((node) => {
        const parent = node.parentNode;
        while (node.firstChild) {
            parent.insertBefore(node.firstChild, node);
        }
        parent.removeChild(node);
    });
}

function createRangeByTextOffsets(rootEl, start, end) {
    if (!rootEl || start >= end) return null;
    let cursor = 0;
    let startNode = null;
    let endNode = null;
    let startOffsetInNode = 0;
    let endOffsetInNode = 0;

    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        const textLength = node.nodeValue.length;
        const nodeStart = cursor;
        const nodeEnd = cursor + textLength;

        if (!startNode && start >= nodeStart && start <= nodeEnd) {
            startNode = node;
            startOffsetInNode = Math.min(start - nodeStart, textLength);
        }
        if (!endNode && end >= nodeStart && end <= nodeEnd) {
            endNode = node;
            endOffsetInNode = Math.min(end - nodeStart, textLength);
            break;
        }

        cursor = nodeEnd;
    }

    if (!startNode || !endNode) return null;
    const range = document.createRange();
    range.setStart(startNode, startOffsetInNode);
    range.setEnd(endNode, endOffsetInNode);
    if (range.collapsed) return null;
    return range;
}

function applySingleMarkup(columnElement, markup) {
    if (!columnElement || !markup) return;
    const start = Number(markup.start);
    const end = Number(markup.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return;

    const range = createRangeByTextOffsets(columnElement, start, end);
    if (!range) return;

    const span = document.createElement('span');
    span.classList.add('ppt-markup');
    if (markup.type === 'underline') {
        span.classList.add('ppt-markup-underline');
    } else {
        span.classList.add('ppt-markup-highlight');
    }
    if (markup.id) {
        span.dataset.markupId = String(markup.id);
    }

    const fragment = range.extractContents();
    span.appendChild(fragment);
    range.insertNode(span);
}

function applyParagraphMarkup(paragraphDiv, paragraphDict) {
    if (!paragraphDiv || !paragraphDict) return;
    const markups = Array.isArray(paragraphDict.markup) ? paragraphDict.markup : [];
    paragraphDiv.querySelectorAll(MARKUP_TARGET_COLUMN_SELECTOR).forEach(removeExistingMarkupDecorations);
    if (markups.length === 0) return;

    const grouped = {};
    markups.forEach((item) => {
        if (!item || !item.column) return;
        if (!grouped[item.column]) grouped[item.column] = [];
        grouped[item.column].push(item);
    });

    Object.entries(grouped).forEach(([columnKey, entries]) => {
        const className = Object.keys(MARKUP_COLUMN_CLASS_TO_KEY).find((k) => MARKUP_COLUMN_CLASS_TO_KEY[k] === columnKey);
        if (!className) return;
        const columnElement = paragraphDiv.querySelector(`.${className}`);
        if (!columnElement) return;

        entries
            .slice()
            .sort((a, b) => Number(b.start) - Number(a.start) || Number(b.end) - Number(a.end))
            .forEach((item) => applySingleMarkup(columnElement, item));
    });
}

async function addMarkupToCurrentSelection(markupType) {
    if (!pendingMarkupSelection) return;
    const selection = pendingMarkupSelection;

    if (selection.pageNumber !== String(currentPage)) {
        clearPendingMarkupSelection();
        return;
    }

    const paragraphDict = bookData?.pages?.[currentPage]?.paragraphs?.[selection.paragraphId];
    if (!paragraphDict) {
        clearPendingMarkupSelection();
        return;
    }

    if (!Array.isArray(paragraphDict.markup)) {
        paragraphDict.markup = [];
    }

    const markupTypeKey = markupType === 'underline' ? 'underline' : 'highlight';
    const start = Number(selection.start);
    const end = Number(selection.end);
    const columnKey = selection.columnKey;

    const overlaps = paragraphDict.markup.filter((item) => {
        if (!item || item.column !== columnKey || item.type !== markupTypeKey) return false;
        const mStart = Number(item.start);
        const mEnd = Number(item.end);
        if (!Number.isFinite(mStart) || !Number.isFinite(mEnd)) return false;
        return start < mEnd && end > mStart;
    });

    if (overlaps.length > 0) {
        paragraphDict.markup = paragraphDict.markup.filter((item) => !overlaps.includes(item));
    } else {
        paragraphDict.markup.push({
            id: generateMarkupId(),
            column: columnKey,
            start,
            end,
            type: markupTypeKey,
        });
    }

    const paragraphDiv = document.getElementById(`paragraph-${selection.paragraphId}`);
    if (paragraphDiv) {
        applyParagraphMarkup(paragraphDiv, paragraphDict);
    }

    await saveParagraphData(paragraphDict);

    const browserSelection = window.getSelection();
    if (browserSelection) {
        browserSelection.removeAllRanges();
    }
    clearPendingMarkupSelection();
}

async function clearParagraphMarkup() {
    const context = pendingMarkupParagraphContext || getParagraphContextForMarkup(window.getSelection());
    if (!context) return;
    if (context.pageNumber !== String(currentPage)) return;

    const paragraphDict = bookData?.pages?.[currentPage]?.paragraphs?.[context.paragraphId];
    if (!paragraphDict || !Array.isArray(paragraphDict.markup) || paragraphDict.markup.length === 0) return;

    paragraphDict.markup = [];
    const paragraphDiv = document.getElementById(`paragraph-${context.paragraphId}`);
    if (paragraphDiv) {
        applyParagraphMarkup(paragraphDiv, paragraphDict);
    }
    await saveParagraphData(paragraphDict);
}

function refreshPendingMarkupSelection() {
    const selection = window.getSelection();
    const selectionInfo = getSelectionInfoForMarkup(selection);
    pendingMarkupSelection = selectionInfo;
    pendingMarkupParagraphContext = getParagraphContextForMarkup(selection);

    if (!selectionInfo && !pendingMarkupParagraphContext) {
        clearPendingMarkupSelection();
        return;
    }
    showMarkupTools();
}

function initMarkupTools() {
    const highlightButton = document.getElementById('markupHighlightButton');
    const underlineButton = document.getElementById('markupUnderlineButton');
    const clearParagraphButton = document.getElementById('markupClearParagraphButton');
    if (!highlightButton || !underlineButton || !clearParagraphButton) return;

    highlightButton.addEventListener('click', async () => {
        await addMarkupToCurrentSelection('highlight');
    });
    underlineButton.addEventListener('click', async () => {
        await addMarkupToCurrentSelection('underline');
    });
    clearParagraphButton.addEventListener('click', async () => {
        await clearParagraphMarkup();
    });

    document.addEventListener('selectionchange', () => {
        refreshPendingMarkupSelection();
    });

    document.addEventListener('mousedown', (event) => {
        const tools = getMarkupToolsContainer();
        if (!tools) return;
        if (tools.contains(event.target)) return;
        const inSrcPanel = !!event.target.closest('#srcPanel');
        if (!inSrcPanel) {
            clearPendingMarkupSelection();
        }
    });
}

// 非編集表示用: テキスト中のURLを自動リンク化
const URL_PATTERN = /\b((?:https?:\/\/|www\.)[^\s<]+[^\s<\)\]\}>,\.!?;:"'])/gi;

function normalizeUrlForHref(urlText) {
    const t = String(urlText || '').trim();
    if (!t) return null;
    if (/^https?:\/\//i.test(t)) return t;
    if (/^www\./i.test(t)) return `http://${t}`;
    return null;
}

function isUrlBookContext() {
    return !!(bookData && bookData.source_type === 'url');
}

function isInternalUrl(url) {
    if (!isUrlBookContext()) return false;
    const root = bookData.source_root_url || '';
    const host = bookData.source_host || '';
    if (!host) return false;
    try {
        const resolved = new URL(url, root || window.location.href);
        return resolved.host === host;
    } catch (e) {
        return false;
    }
}

function linkifyTextNode(textNode) {
    const text = textNode.nodeValue;
    if (!text || !URL_PATTERN.test(text)) return;
    URL_PATTERN.lastIndex = 0;

    const frag = document.createDocumentFragment();
    let lastIndex = 0;
    let match;
    while ((match = URL_PATTERN.exec(text)) !== null) {
        const urlText = match[1];
        const start = match.index;
        const end = start + urlText.length;
        if (start > lastIndex) {
            frag.appendChild(document.createTextNode(text.slice(lastIndex, start)));
        }

        const href = normalizeUrlForHref(urlText);
        if (href) {
            const a = document.createElement('a');
            a.textContent = urlText;
            a.href = href;
            if (isInternalUrl(href)) {
                a.dataset.url = href;
            } else {
                a.target = '_blank';
                a.rel = 'noopener noreferrer';
            }
            frag.appendChild(a);
        } else {
            frag.appendChild(document.createTextNode(urlText));
        }

        lastIndex = end;
    }
    if (lastIndex < text.length) {
        frag.appendChild(document.createTextNode(text.slice(lastIndex)));
    }

    textNode.parentNode.replaceChild(frag, textNode);
}

function linkifyElement(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return;
    if (el.isContentEditable) return;

    const walker = document.createTreeWalker(
        el,
        NodeFilter.SHOW_TEXT,
        {
            acceptNode: (node) => {
                if (!node?.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
                const parent = node.parentElement;
                if (!parent) return NodeFilter.FILTER_REJECT;
                if (parent.closest('a')) return NodeFilter.FILTER_REJECT;
                if (parent.isContentEditable) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        }
    );

    const nodes = [];
    let n;
    while ((n = walker.nextNode())) nodes.push(n);
    nodes.forEach(linkifyTextNode);
}

function linkifyParagraphBox(divSrc) {
    if (!divSrc) return;
    if (divSrc.classList.contains('editing')) return;
    divSrc.querySelectorAll('.src-text, .src-joined, .src-replaced, .trans-auto, .trans-text, .comment-text')
        .forEach(linkifyElement);
}

document.addEventListener('click', async (event) => {
    const anchor = event.target.closest('#srcPanel a');
    if (!anchor) return;
    if (anchor.isContentEditable) return;
    if (!isUrlBookContext()) return;

    const targetUrl = anchor.dataset.url || anchor.getAttribute('href');
    if (!targetUrl) return;

    if (!isInternalUrl(targetUrl)) {
        return;
    }

    event.preventDefault();
    if (typeof confirmAndAddUrlPage === 'function') {
        await confirmAndAddUrlPage(targetUrl);
    } else if (typeof navigateUrlBook === 'function') {
        await navigateUrlBook(targetUrl);
    }
});

function initSrcPanel() {
    $("#srcParagraphs").sortable({
    // ドラッグ用ハンドルのみ有効にするために handle オプションを指定
    handle: ".drag-handle",
        update: function (event, ui) {
            saveCurrentPageOrder();
        }
    });
}

// 編集ボックスの単文での翻訳
function onTransButtonClick(event, paragraph, divSrc) {
    transParagraph(paragraph, divSrc);
}

async function onSaveButtonClick(event, paragraph, divSrc, srcText, transText, blockTagSelect, blockTagSpan) {
    // たぶん関数内がいろいろ無駄なことになっているのであとでリファクタリング
    const commentText = divSrc.querySelector('.comment-text');
    
    divSrc.classList.remove('editing');
    srcText.contentEditable = false;
    transText.contentEditable = false;
    // コメント列は常に編集可能な状態を保つ（contentEditable = true のまま）
    // commentText.contentEditable = false; // ← 実行しない
    
    divSrc.querySelector('.edit-ui').style.display = 'none';
    $("#srcParagraphs").sortable("enable");
    divSrc.style.cursor = '';

    const id = paragraph.id;
    const selectedStatus = divSrc.querySelector(`input[name='status-${id}']:checked`);

    paragraphDict = bookData["pages"][currentPage]["paragraphs"][id];
    if (paragraphDict) {
        const srcTextChanged = paragraph.src_text !== srcText.innerHTML;
        
        paragraphDict.src_text = srcText.innerHTML;
        paragraphDict.trans_text = transText.innerHTML;
        paragraphDict.comment = commentText ? commentText.innerHTML : (paragraphDict.comment ?? "");
        paragraphDict.block_tag = blockTagSelect.value;
        paragraphDict.trans_status = selectedStatus ? selectedStatus.value : paragraphDict.trans_status;

        // src_text が変更された場合、src_joined と src_replaced を src_text の値でセット
        if (srcTextChanged) {
            paragraphDict.src_joined = srcText.innerHTML;
            paragraphDict.src_replaced = srcText.innerHTML;
            
            // ブラウザ上の表示もすぐに更新
            const srcJoinedEl = divSrc.querySelector('.src-joined');
            const srcReplacedEl = divSrc.querySelector('.src-replaced');
            if (srcJoinedEl) srcJoinedEl.innerHTML = srcText.innerHTML;
            if (srcReplacedEl) srcReplacedEl.innerHTML = srcText.innerHTML;
        }

        const joinCheckbox = divSrc.querySelector('.join-checkbox');
        const joinOn = !!joinCheckbox?.checked;
        if (joinOn) {
            paragraphDict.join = 1;
        } else if ('join' in paragraphDict) {
            delete paragraphDict.join;
        }
    } else {
        console.warn(`Paragraph with ID ${id} not found in paragraphs.`);
    }

    blockTagSpan.innerText = blockTagSelect.value;

    // パラグラフの背景をblock_tagに基づいて更新
    const blockTagClass = `block-tag-${blockTagSelect.value}`;
    divSrc.className = divSrc.className.replace(/block-tag-\S+/g, '').trim() + ` ${blockTagClass}`;

    const editBox = divSrc.querySelector('.edit-box');
    editBox.className = `edit-box status-${selectedStatus.value}`;

    //edit-box

// サーバー保存
    try {
        await saveParagraphData(paragraphDict);

        // 保存成功後に「元の値」を更新（次回キャンセル時に戻す先）
        if (srcText) srcText.dataset.original = srcText.innerHTML;
        if (transText) transText.dataset.original = transText.innerHTML;
        if (commentText) commentText.dataset.original = commentText.innerHTML;
        updateEditUiBackground(divSrc, paragraphDict.trans_status);

        // 非編集表示に戻った後、URLをリンク化
        linkifyParagraphBox(divSrc);
        applyParagraphMarkup(divSrc, paragraphDict);
    } catch (error) {
        console.error('Error saving paragraph:', error);
        alert('データ保存中にエラーが発生しました。詳細はコンソールを確認してください。');
    }
}

function onEditCancelClick(event, paragraph, divSrc, srcText, transText, blockTagSpan) {
    divSrc.classList.remove('editing');
    srcText.contentEditable = false;
    transText.contentEditable = false;
    divSrc.querySelector('.edit-ui').style.display = 'none';
    divSrc.querySelector('.edit-button').style.visibility = 'visible'; // visibilityを直接操作
    $("#srcParagraphs").sortable("enable");
    divSrc.style.cursor = '';

    srcText.innerHTML = paragraph.src_text;
    transText.innerHTML = paragraph.trans_text;
    paragraph.block_tag = blockTagSpan.innerText;

    // 元のtrans_statusに基づいて背景色を復元
    updateEditUiBackground(divSrc, paragraph.trans_status);
}

/** @function renderParagraphs */
function renderParagraphs(options = {}) {
    const tStart = (window.PERF_NAV && typeof perfNow === 'function') ? perfNow() : null;
    const { resetScrollTop = false } = options;
    if (resetScrollTop) {
        const srcPanel = document.getElementById("srcPanel");
        if (srcPanel) srcPanel.scrollTop = 0;
    }

    if (!bookData?.pages?.[String(currentPage)]) {
        console.warn(`renderParagraphs skipped: page data not loaded (${currentPage})`);
        const srcContainer = document.getElementById("srcParagraphs");
        if (srcContainer) {
            srcContainer.style.display = 'block';
            srcContainer.innerHTML = `<div class="paragraph-box">Loading page ${currentPage}...</div>`;
        }
        return;
    }

    let srcContainer = document.getElementById("srcParagraphs");
    srcContainer.style.display = 'none'; // チラつき防止にいったん非表示
    srcContainer.innerHTML = "";

    // URLブックの場合、ページURLを先頭に表示
    if (isUrlBookContext() && bookData?.pages?.[String(currentPage)]?.url) {
        const pageUrl = bookData.pages[String(currentPage)].url;
        const urlBox = document.createElement("div");
        urlBox.className = "paragraph-box url-header";
        urlBox.style.cssText = "background: #f0f8ff; border-left: 4px solid #4a90e2; padding: 8px 12px; margin-bottom: 12px; font-size: 0.9em;";
        const urlLink = document.createElement("a");
        urlLink.href = pageUrl;
        urlLink.target = "_blank";
        urlLink.rel = "noopener noreferrer";
        urlLink.textContent = pageUrl;
        urlLink.style.cssText = "color: #4a90e2; text-decoration: none; word-break: break-all;";
        urlLink.addEventListener('mouseenter', () => { urlLink.style.textDecoration = 'underline'; });
        urlLink.addEventListener('mouseleave', () => { urlLink.style.textDecoration = 'none'; });
        const label = document.createElement("span");
        label.textContent = "🔗 ";
        label.style.marginRight = "4px";
        urlBox.appendChild(label);
        urlBox.appendChild(urlLink);
        srcContainer.appendChild(urlBox);
    }



    const paragraphsArray = Object.values(bookData["pages"][currentPage]["paragraphs"]);
    // order順/column_order/y0順にソート
    paragraphsArray.sort((a, b) => {
        if (a.order !== b.order) return a.order - b.order;
        if (a.column_order !== b.column_order) return a.column_order - b.column_order;
        return a.bbox[1] - b.bbox[1]; // y0順にソート
    });

    // 現在のページに表示するパラグラフのみをフィルタリング（ソート後に実施）
    const currentPageParagraphs = paragraphsArray;

    for (let i = 0; i < currentPageParagraphs.length; i++) {
        let p = currentPageParagraphs[i];

        let divSrc = document.createElement("div");
        let blockTagClass = `block-tag-${p.block_tag}`;
        let joinClass = p.join === 1 ? 'visible' : ''; // 修正: visible クラスのみ使用

        let statusClass = `status-${p.trans_status}`;
        divSrc.className = `paragraph-box ${blockTagClass}`;

        // グループ情報に基づいてクラスを付与
        if (p.group_id) {
            const prev = currentPageParagraphs[i - 1];
            const next = currentPageParagraphs[i + 1];
            const sameGroupPrev = prev?.group_id === p.group_id;
            const sameGroupNext = next?.group_id === p.group_id;

            if (!sameGroupPrev && sameGroupNext) {
                divSrc.classList.add('group-start');
            } else if (sameGroupPrev && sameGroupNext) {
                divSrc.classList.add('group-middle');
            } else if (sameGroupPrev && !sameGroupNext) {
                divSrc.classList.add('group-end');
            } else {
                divSrc.classList.add('group-start', 'group-end');
            }

            divSrc.classList.add(`group-id-${p.group_id}`);
        }

        divSrc.id = `paragraph-${p.id}`;
        divSrc.innerHTML = `
            <div class='src-html'>${p.src_html}</div>
            <div class='src-text' data-original="${p.src_text}">${p.src_text}</div>
            <div class='src-joined'>${p.src_joined}</div>
            <div class='src-replaced'>${p.src_replaced}</div>
            <div class='trans-auto'>${p.trans_auto}</div>
            <div class='trans-text' data-original="${p.trans_text}">${p.trans_text}</div>
            <div class='comment-text' data-original="${p.comment ?? ''}">${p.comment ?? ''}</div>
            <div class='edit-box ${statusClass}'>
                <div class='join ${joinClass}'></div>
                <button class='edit-button'>...</button>
                <div class="drag-handle">
                    <span class='paragraph-id'>${p.id}</span>
                    <span class="block-tag">${p.block_tag}</span>
                </div>
                <div class='edit-ui ${statusClass}'>
                    <label class='join-toggle'><input type='checkbox' class='join-checkbox'> 結合</label>
                    <button class='reset-translation-button'>翻訳クリア</button>
                    <label>種別:
                        <select class="type-select">
                            <option value="p">p</option>
                            <option value="h1">h1</option>
                            <option value="h2">h2</option>
                            <option value="h3">h3</option>
                            <option value="h4">h4</option>
                            <option value="h5">h5</option>
                            <option value="h6">h6</option>
                            <option value="li">li</option>
                            <option value="ul">ul</option>
                            <option value="dd">dd</option>
                            <option value="tr">tr</option>
                            <option value="th">th</option>
                            <option value="header">header</option>
                            <option value="footer">footer</option>
                            <option value="remove">remove</option>
                        </select>
                    </label>
                    <button class='style-update-button'>同スタイルを一括更新</button>
                    <span>  </span>
                    <button class='trans-button'>自動翻訳</button>
                    <label><input type='radio' name='status-${p.id}' value='none'> 未翻訳</label>
                    <label><input type='radio' name='status-${p.id}' value='auto'> 自動翻訳</label>
                    <label><input type='radio' name='status-${p.id}' value='draft'> 下訳</label>
                    <label><input type='radio' name='status-${p.id}' value='fixed'> 確定</label>
                    <button class='save-button'>保存</button>
                </div>
            </div>
        `;
        srcContainer.appendChild(divSrc);

        // 非編集表示のURLをリンク化（編集ボックス内は対象外）
        linkifyParagraphBox(divSrc);
        applyParagraphMarkup(divSrc, p);

        // イベントリスナーの登録
        let editButton = divSrc.querySelector('.edit-button');
        let transButton = divSrc.querySelector('.trans-button');
        let styleUpdateButton = divSrc.querySelector('.style-update-button'); // 追加
        let saveButton = divSrc.querySelector('.save-button');
        let srcText = divSrc.querySelector('.src-text');
        let transText = divSrc.querySelector('.trans-text');
        let blockTagSelect = divSrc.querySelector('.type-select');
        let blockTagSpan = divSrc.querySelector('.block-tag'); // 修正: block_tag spanのクラス名を正しく指定
        let resetTranslationButton = divSrc.querySelector('.reset-translation-button'); // 追加
        let joinCheckbox = divSrc.querySelector('.join-checkbox');

        blockTagSelect.value = p.block_tag;
        let statusRadio = divSrc.querySelector(`input[name='status-${p.id}'][value='${p.trans_status}']`);
        if (statusRadio) { statusRadio.checked = true; }

        if (joinCheckbox) {
            joinCheckbox.checked = (p.join === 1);
            joinCheckbox.addEventListener('change', () => {
                const idStr = String(p.id);
                const paragraphDict = bookData?.pages?.[currentPage]?.paragraphs?.[idStr];
                const joinEl = divSrc.querySelector('.join');

                if (joinCheckbox.checked) {
                    if (paragraphDict) paragraphDict.join = 1;
                    if (joinEl) joinEl.classList.add('visible');
                } else {
                    if (paragraphDict && ('join' in paragraphDict)) delete paragraphDict.join;
                    if (joinEl) joinEl.classList.remove('visible');
                }
            });
        }

        editButton.addEventListener('click', () => toggleEditUI(divSrc));
        transButton.addEventListener('click', (e) => onTransButtonClick(e, p, divSrc));
        styleUpdateButton.addEventListener('click', (e) => onStyleUpdateButtonClick(e, p, divSrc)); // 追加
        saveButton.addEventListener('click', (e) => onSaveButtonClick(e, p, divSrc, srcText, transText, blockTagSelect, blockTagSpan));
        resetTranslationButton.addEventListener('click', (e) => resetTranslation(p)); // 追加

        // コメント列を常に直接編集可能に設定
        let commentText = divSrc.querySelector('.comment-text');
        if (commentText) {
            commentText.contentEditable = true;
            commentText.addEventListener('blur', async () => {
                // コメント内容が変更されている場合、自動保存
                const newComment = commentText.innerHTML;
                if (p.comment !== newComment) {
                    p.comment = newComment;
                    paragraphDict = bookData["pages"][currentPage]["paragraphs"][p.id];
                    if (paragraphDict) {
                        paragraphDict.comment = newComment;
                        try {
                            await saveParagraphData(paragraphDict);
                            commentText.dataset.original = newComment;
                        } catch (error) {
                            console.error('Error saving comment:', error);
                            // エラー時は表示を戻す（自動的に重要でないため）
                        }
                    }
                }
            });
        }

        // ラジオボタンの変更イベントリスナーを追加
        addRadioChangeListener(divSrc, p);
    }

    window.autoToggle.dispatchAll();
    srcContainer.style.display = 'block'; // 再表示

    if (tStart !== null && typeof perfLog === 'function') {
        const count = Object.values(bookData?.pages?.[currentPage]?.paragraphs || {}).length;
        perfLog("renderParagraphs(total)", tStart, `(page ${currentPage}, paragraphs ${count})`);
    }
}

// スタイル一括更新ボタンのクリックイベントハンドラ
async function onStyleUpdateButtonClick(event, paragraph, divSrc) {
    const targetStyle = paragraph.base_style; // 現在のパラグラフのスタイルを取得
    const targetTag = divSrc.querySelector('.type-select').value; // 選択されているblock_tagを取得

    // header/footer/remove は style + Y範囲 で一括更新する
    const isSpecial = (targetTag === 'header' || targetTag === 'footer' || targetTag === 'remove');
    const eps = 1.0;

    let rangeY0 = null;
    let rangeY1 = null;
    if (isSpecial) {
        const bbox = paragraph?.bbox;
        if (!bbox || !Array.isArray(bbox) || bbox.length < 4) {
            alert('この段落の bbox が取得できないため、style+Y範囲の一括更新はできません。');
            return;
        }
        let y0 = Number(bbox[1]);
        let y1 = Number(bbox[3]);
        if (!Number.isFinite(y0) || !Number.isFinite(y1)) {
            alert('この段落の bbox(y0/y1) が不正です。');
            return;
        }
        if (y0 > y1) {
            const tmp = y0;
            y0 = y1;
            y1 = tmp;
        }
        rangeY0 = y0 - eps;
        rangeY1 = y1 + eps;
    }

    // 対象パラグラフの数をカウント
    let count = 0;
    for (const page of Object.values(bookData["pages"])) {
        for (const p of Object.values(page["paragraphs"])) {
            if (p.base_style !== targetStyle) continue;
            if (isSpecial) {
                const b = p.bbox;
                if (!b || !Array.isArray(b) || b.length < 4) continue;
                const py0 = Number(b[1]);
                const py1 = Number(b[3]);
                if (!Number.isFinite(py0) || !Number.isFinite(py1)) continue;
                if (rangeY0 <= py0 && py1 <= rangeY1) count++;
            } else {
                count++;
            }
        }
    }

    if (count === 0) {
        alert(`スタイル '${targetStyle}' を持つパラグラフは見つかりませんでした。`);
        return;
    }

    let msg = `このパラグラフと同じスタイル '${targetStyle}' のパラグラフ ${count} 件をすべて '${targetTag}' に更新します。`;
    if (isSpecial) {
        msg += `\n(判定条件: style + Y範囲 y0=${rangeY0.toFixed(1)}, y1=${rangeY1.toFixed(1)})`;
    }
    msg += `\n\n文書全体の処理です。よろしいですか？`;

    const confirmation = confirm(msg);
    if (!confirmation) return;

    if (isSpecial) {
        if (typeof taggingByStyleY !== 'function') {
            alert('taggingByStyleY が見つかりません（fetch.js の読み込みを確認してください）');
            return;
        }
        await taggingByStyleY(targetStyle, rangeY0, rangeY1, targetTag);
    } else {
        await taggingByStyle(targetStyle, targetTag);
    }
}


function toggleSrcHtml(event) {
    const checked = event.target.checked;
    document.querySelectorAll('.src-html').forEach(el => {
        el.style.display = checked ? 'block' : 'none';
    });
}

function toggleSrc(event) {
    const checked = event.target.checked;
    document.querySelectorAll('.src-text').forEach(el => {
        el.style.display = checked ? 'block' : 'none';
    });
}

function toggleSrcReplaced(event) {
    const checked = event.target.checked;
    document.querySelectorAll('.src-replaced').forEach(el => {
        el.style.display = checked ? 'block' : 'none';
    });
}

function toggleTransAuto(event) {
    const checked = event.target.checked;
    document.querySelectorAll('.trans-auto').forEach(el => {
        el.style.display = checked ? 'block' : 'none';
    });
}

function toggleTrans(event) {
    const checked = event.target.checked;
    document.querySelectorAll('.trans-text').forEach(el => {
        el.style.display = checked ? 'block' : 'none';
    });
}

function toggleSrcJoined(event) {
    const checked = event.target.checked;
    document.querySelectorAll('.src-joined').forEach(el => {
        el.style.display = checked ? 'block' : 'none';
    });
}

// 編集パラグラフのデータをJSONに保存
/** @function saveParagraphData */
async function saveParagraphData(paragraphDict) {
    try {
        const response = await fetch(`/api/update_paragraph/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
            body: JSON.stringify({
                page_number: paragraphDict.page_number,
                id: paragraphDict.id,
                src_text: paragraphDict.src_text,
                trans_auto: paragraphDict.trans_auto,
                trans_text: paragraphDict.trans_text,
                comment: paragraphDict.comment ?? "",
                trans_status: paragraphDict.trans_status,
                block_tag: paragraphDict.block_tag,
                join: paragraphDict.join === 1 ? 1 : 0,
                markup: Array.isArray(paragraphDict.markup) ? paragraphDict.markup : []
            })
        });
        const data = await response.json(); // await を追加

        console.log('Success:', data);

        if (data.status === "ok") {
            console.log('Success:', data);
            // サーバーへの保存が成功した場合のみクライアント側を更新
            if (bookData["pages"][currentPage]["paragraphs"][paragraphDict.id]) {
                 Object.assign(bookData["pages"][currentPage]["paragraphs"][paragraphDict.id], paragraphDict);
            } else {
                 console.warn(`saveParagraphData: Paragraph with ID ${paragraphDict.id} not found in paragraphs during update.`);
            }
            updateTransStatusCounts(data.trans_status_counts); // サーバーからの最新カウントを使用
            if (data.reload_book_data) {
                await fetchBookData();
            }
        } else {
            console.error('Error:', data.message);
            alert('データ保存中にエラーが発生しました: ' + data.message);
            // エラー時は元の状態に戻すなどの処理が必要な場合がある
        }
    } catch (error) { // catch ブロックを追加
        console.error('Error:', error);
        alert('データ保存中にエラーが発生しました。詳細はコンソールを確認してください。');
    }
}

// ラジオボタンの切り替えでedit-uiの背景色を変更
function updateEditUiBackground(divSrc, transStatus) {
    const editUi = divSrc.querySelector('.edit-ui');
    if (editUi) {
        editUi.className = `edit-ui status-${transStatus}`;
    }

    const editBox = divSrc.querySelector('.edit-box');
    if (editBox) {
        editBox.className = `edit-box status-${transStatus}`;
    }
}

// ラジオボタンの変更イベントを追加
function addRadioChangeListener(divSrc, paragraph) {
    const radios = divSrc.querySelectorAll(`input[name='status-${paragraph.id}']`);
    radios.forEach(radio => {
        radio.addEventListener('change', (event) => {
            const selectedStatus = event.target.value;
            updateEditUiBackground(divSrc, selectedStatus);
        });
    });
}

/** @function resetSelection */
function resetSelection() {
    document.querySelectorAll('.paragraph-box.selected').forEach(el => el.classList.remove('selected'));
}

/** @function selectParagraphRange */
// 範囲を指定してパラグラフを選択リストに追加
function selectParagraphRange(startIndex, endIndex) {
    const all = Array.from(document.querySelectorAll('.paragraph-box'));
    const [start, end] = [startIndex, endIndex].sort((a, b) => a - b);

    for (let i = 0; i < all.length; i++) {
        if (i >= start && i <= end) {
            all[i].classList.add('selected');
        } else {
            all[i].classList.remove('selected');
        }
    }
}

/*マウスクリック */
document.addEventListener('click', (event) => {
    document.querySelectorAll('.edit-ui').forEach(editUI => {
        if (editUI.style.display === 'block') {
            const paragraphBox = editUI.closest('.paragraph-box');
            // ✨ そのパラグラフ外をクリックしたらキャンセル
            if (!paragraphBox.contains(event.target)) {
                cancelEditUI(paragraphBox);
            }
        }
    });

    const paragraphBox = event.target.closest('.paragraph-box');
    if (!paragraphBox) return;

    const paragraphs = Array.from(document.querySelectorAll('.paragraph-box'));
    const clickedIndex = paragraphs.indexOf(paragraphBox);

    if (event.shiftKey) {
        // Shiftキーが押されている場合、範囲選択
        const currentIndex = currentParagraphIndex;
        selectParagraphRange(currentIndex, clickedIndex);
    } else if (event.ctrlKey) {
        // Ctrlキーが押されている場合、選択をトグル
        setCurrentParagraph(clickedIndex, event.shiftKey);
    } else {
        // 通常クリックの場合、選択をリセットしてカレントを変更
        resetSelection();
        setCurrentParagraph(clickedIndex, event.shiftKey);
    }
});

/** @function moveSelectedAfter */
// “targetIndex” を受け取り、同じインデックスにある要素を取得して挿入
function moveSelectedAfter(targetIndex) {
    const container = document.getElementById('srcParagraphs');
    const currentDiv = document.querySelector('.paragraph-box.current');
    const selected = getSelectedOrCurrentParagraphsInOrder();
    if (selected.length === 0) return;
    const children = container.children;
    // 下限チェックのみ。上限を超えたら末尾扱い
    if (targetIndex < 0) return;
    // nextSibling が null なら appendChild と同義で末尾に移動
    const refNode = targetIndex >= children.length
        ? null
        : children[targetIndex].nextSibling;
    selected.forEach(el => container.insertBefore(el, refNode));
    isPageEdited = true;

    // 移動後も「カレント段落」とスクロール位置を追随させる
    const focusDiv = currentDiv || selected[0];
    if (focusDiv) {
        const paragraphs = getAllParagraphs();
        const newIndex = paragraphs.indexOf(focusDiv);
        if (newIndex >= 0) {
            // isShiftHeld=true で選択状態は維持したままカレントだけ更新
            setCurrentParagraph(newIndex, true);
        } else {
            focusDiv.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
    }
}

/** @function moveSelectedBefore */
// “targetIndex” を受け取り、同じインデックスにある要素を取得して挿入
function moveSelectedBefore(targetIndex) {
    const container = document.getElementById('srcParagraphs');
    const currentDiv = document.querySelector('.paragraph-box.current');
    const selected = getSelectedOrCurrentParagraphsInOrder();
    if (selected.length === 0) return;
    const children = container.children;
    // 範囲チェック
    if (targetIndex < 0 || targetIndex >= children.length) return;
    const target = children[targetIndex];
    selected.forEach(el => container.insertBefore(el, target));
    isPageEdited = true;

    // 移動後も「カレント段落」とスクロール位置を追随させる
    const focusDiv = currentDiv || selected[0];
    if (focusDiv) {
        const paragraphs = getAllParagraphs();
        const newIndex = paragraphs.indexOf(focusDiv);
        if (newIndex >= 0) {
            setCurrentParagraph(newIndex, true);
        } else {
            focusDiv.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
    }
}

/** @function moveSelectedByOffset 
 * 選択されたパラグラフ範囲をオフセット分だけ in-place 移動 */
function moveSelectedByOffset(offset) {
  const container = document.getElementById('srcParagraphs');
    const currentDiv = document.querySelector('.paragraph-box.current');
    const selected = getSelectedOrCurrentParagraphsInOrder();
  if (selected.length === 0) return;

  const children = Array.from(container.children);
  // 選択要素の先頭/末尾インデックスを取得
  const idxs = selected.map(el => children.indexOf(el)).sort((a, b) => a - b);
  const from = offset < 0 ? idxs[0] : idxs[idxs.length - 1];
  const to = from + offset;
  if (to < 0 || to >= children.length) return;

  const target = children[to];
  // 前に挿入するなら target、自動末尾扱いなら target.nextSibling
  const refNode = offset < 0 ? target : target.nextSibling;
  selected.forEach(el => container.insertBefore(el, refNode));
  isPageEdited = true;

  // 移動後も「カレント段落」とスクロール位置を追随させる
  const focusDiv = currentDiv || selected[0];
  if (focusDiv) {
      const paragraphs = getAllParagraphs();
      const newIndex = paragraphs.indexOf(focusDiv);
      if (newIndex >= 0) {
          // isShiftHeld=true で選択状態は維持したままカレントだけ更新
          setCurrentParagraph(newIndex, true);
      } else {
          focusDiv.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
  }
}

/** @function getSelectedParagraphsInOrder */
function getSelectedParagraphsInOrder() {
    return Array.from(
        document.querySelectorAll('.paragraph-box.selected, .paragraph-box.current')
    );
}

function getSelectedParagraphsOnlyInOrder() {
    return Array.from(document.querySelectorAll('.paragraph-box.selected'));
}

// 移動系で使う：複数選択時に「選択のみ」を対象にし、カレントが選択外なら巻き込まない。
// 選択が無い場合のみカレントを対象にする。
function getSelectedOrCurrentParagraphsInOrder() {
    const selectedOnly = getSelectedParagraphsOnlyInOrder();
    if (selectedOnly.length > 0) return selectedOnly;
    const current = document.querySelector('.paragraph-box.current');
    return current ? [current] : [];
}

/** @function: updateBlockTagForSelected */
function updateBlockTagForSelected(blockTag) {
    const selected = getSelectedParagraphsInOrder();
    // 何も選択されていない場合はカレントレコードを更新
    if (selected.length === 0) {
        selected.push(document.querySelector('.paragraph-box.current'));
    }

    selected.forEach(div => {
        updateBlockTag(div, blockTag);
    });
}

/** @function: updateBlockTag */
function updateBlockTag(paragraphDiv, blockTag) {
    const id = paragraphDiv.id.replace('paragraph-', '');
    const p = bookData["pages"][currentPage]["paragraphs"][id];
    if (!p) {
        console.error(`Paragraph with ID ${id} not found in paragraphs`);
        return;
    }
    
    p.block_tag = blockTag;

    const blockTagSpan = paragraphDiv.querySelector('.block-tag');
    const typeSelect = paragraphDiv.querySelector('.type-select');
    blockTagSpan.innerText = blockTag;
    if (typeSelect) typeSelect.value = blockTag;

    const currentStatus = p.trans_status;

    // クラス更新：既存の block-tag-* と status-* だけを更新
    paragraphDiv.classList.remove(
        ...Array.from(paragraphDiv.classList).filter(cls => cls.startsWith('block-tag-') || cls.startsWith('status-'))
    );
    paragraphDiv.classList.add(`block-tag-${blockTag}`);
    // paragraphDiv.classList.add(`block-tag-${blockTag}`, `status-${currentStatus}`);
    isPageEdited = true; // ページが編集されたことを示すフラグを立てる
}


/** @function: updateTransStatusForSelected */
function updateTransStatusForSelected(transStatus) {
    const selected = getSelectedParagraphsInOrder();
    // 何も選択されていない場合はカレントレコードを更新
    if (selected.length === 0) {
        selected.push(document.querySelector('.paragraph-box.current'));
    }

    selected.forEach(div => {
        updateTransStatus(div, transStatus);
    });
}

/** @function: updatetransStatus */
function updateTransStatus(paragraphDiv, transStatus) {
    const id = paragraphDiv.id.replace('paragraph-', '');
    const paragraphDict = bookData["pages"][currentPage]["paragraphs"][id];
    if (!paragraphDict) {
        console.error(`Paragraph with ID ${id} not found in paragraphs`);
        return;
    }
    paragraphDict.trans_status = transStatus;

    // edit-boxのクラスを更新
    const editBox = paragraphDiv.querySelector('.edit-box');
    if (editBox) {
        editBox.className = `edit-box status-${transStatus}`;
    }

    // edit-uiのクラスを更新
    const editUi = paragraphDiv.querySelector('.edit-ui');
    if (editUi) {
        editUi.className = `edit-ui status-${transStatus}`;
    }

    // ラジオボタンの状態を更新
    const statusRadio = paragraphDiv.querySelector(`input[name='status-${id}'][value='${transStatus}']`);
    if (statusRadio) {
        statusRadio.checked = true;
    }

    isPageEdited = true; // ページが編集されたことを示すフラグを立てる
}


function getAllParagraphs() {
    return Array.from(document.querySelectorAll('.paragraph-box'));
}

/** @function setCurrentParagraph 
 * 指定されたインデックスのパラグラフをカレントにする
*/
function setCurrentParagraph(index, isShiftHeld = false, options = {}) {
    const {
        scrollIntoView = true,
        scrollBlock = 'center',
        scrollBehavior = 'smooth',
    } = options;
    const paragraphs = getAllParagraphs();

    // 常にページ全体のパラグラフを処理
    paragraphs.forEach(p => {
        // カレントを解除
        p.classList.remove('current');
        if (!isShiftHeld) {
            // shiftキーが押されていなければ、選択を解除
            p.classList.remove('selected');
        }
    });

    index = Math.max(0, Math.min(index, paragraphs.length - 1));
    currentParagraphIndex = index;

    const current = paragraphs[currentParagraphIndex];

    if (!current) return; // インデックスが無効な場合は何もしない
    current.classList.add('current');
    // current.classList.add('selected');

    if (scrollIntoView) {
        current.scrollIntoView({ block: scrollBlock, behavior: scrollBehavior });
    }

    const id = current.id.replace('paragraph-', '');
    const paragraphDict = bookData["pages"][currentPage]["paragraphs"][id];

    if (paragraphDict && paragraphDict.bbox && Array.isArray(paragraphDict.bbox) && paragraphDict.bbox.length === 4) {
        // pdfPanel.js の関数を呼び出してハイライト
        // highlightRectsOnPage は矩形の配列を期待するため、bbox を配列でラップする
        if (typeof highlightRectsOnPage === 'function') {
            highlightRectsOnPage(currentPage, [paragraphDict.bbox]);
        } else {
            console.warn("highlightRectsOnPage function is not defined in pdfPanel.js");
        }
    } else {
        // ハイライト情報がない場合は既存のハイライトをクリア
        if (typeof clearHighlights === 'function') {
            clearHighlights();
        }
        // console.warn(`Paragraph data or first_line_bbox not found for ID: ${id}`);
    }
}

/*** @function toggleCurrentParagraphSelection */
function toggleCurrentParagraphSelection() {
    const paragraphs = getAllParagraphs();
    const current = paragraphs[currentParagraphIndex];
    current.classList.toggle('selected');
}

/** @function moveCurrentParagraphBy 
 * 現在のパラグラフを指定されたオフセット分だけ移動
 * expandSelection=true(通常はshiftキーが押されている場合)は選択範囲を拡張
*/
function moveCurrentParagraphBy(offset, expandSelection = false) {
    const paragraphs = getAllParagraphs();
    const nextIndex = currentParagraphIndex + offset;

    if (nextIndex < 0 || nextIndex >= paragraphs.length) return;

    if (expandSelection) {
        paragraphs[currentParagraphIndex].classList.add('selected');
        paragraphs[nextIndex].classList.add('selected');
    }

    setCurrentParagraph(nextIndex, expandSelection);
}

/** @function getSelectedParagraphsInOrder
 * 選択されたパラグラフに対するグループ化/解除
 */
function toggleGroupSelectedParagraphs() {
    const selected = getSelectedParagraphsInOrder();
    if (selected.length < 2) return;

    // 先頭のグループクラスとパラグラフidを取得
    const firstParagraphIdStr = selected[0].id.replace('paragraph-', '');
    const firstParagraphDict = bookData["pages"][currentPage]["paragraphs"][firstParagraphIdStr]; // 辞書アクセス
    const firstGroupId = firstParagraphDict?.group_id; // 先頭のグループIDを取得 (数値またはundefined)
    const firstGroupIdStr = firstGroupId?.toString(); // クラス名比較用に文字列化

    // グループ化されているかどうかの判定（先頭要素がグループIDを持っているか）
    const isGrouped = !!firstGroupId;

    if (isGrouped) {
        // ✅ グループ解除：選択された要素が属するグループ全体を解除
        const all = getAllParagraphs(); // DOM要素のリスト
        all.forEach(div => {
            const idStr = div.id.replace('paragraph-', '');
            const p = bookData["pages"][currentPage]["paragraphs"][idStr]; // 辞書アクセス
            // 解除対象のグループIDを持つパラグラフのデータを更新
            if (p && p.group_id === firstGroupId) {
                p.group_id = undefined; // または null
                // DOM要素のクラスも更新
                div.classList.remove(`group-id-${firstGroupIdStr}`, 'group-start', 'group-middle', 'group-end');
            }
        });
    } else {
        // ✅ グループ化：選択範囲を新しいグループにする
        // 新しいグループIDは選択範囲の先頭パラグラフのIDを使用 (文字列として)
        const newGroupId = firstParagraphIdStr;
        const newGroupClass = `group-id-${newGroupId}`;

        selected.forEach((div, index) => {
            const idStr = div.id.replace('paragraph-', '');
            const p = bookData["pages"][currentPage]["paragraphs"][idStr]; // 辞書アクセス
            if (p) {
                p.group_id = newGroupId; // データ更新 (文字列IDをグループIDとして設定)
            }

            // 既存のgroup-idクラスを削除
            div.classList.remove(...Array.from(div.classList).filter(cls => cls.startsWith('group-id-')));
            // 新しいグループIDを追加
            div.classList.add(newGroupClass);
            if (index === 0) div.classList.add('group-start');
            else if (index === selected.length - 1) div.classList.add('group-end');
            else div.classList.add('group-middle');
        });
    }
    isPageEdited = true; // ページが編集されたことを示すフラグを立てる

}

/** @function toggleJoinForSelected
 * 選択されたパラグラフに対して join クラスをトグルする
 */
async function toggleJoinForSelected() {
    
    const selectedParagraphs = getSelectedParagraphsInOrder(); // 選択されたパラグラフを取得
    if (selectedParagraphs.length === 0) {
        console.warn("選択されたパラグラフがありません。");
        return;
    }

    if (typeof updateParagraphs !== 'function') {
        console.warn('updateParagraphs が見つかりません（fetch.js の読み込みを確認してください）');
        return;
    }

    const sendParagraphs = [];

    selectedParagraphs.forEach(divP => {
        const id = divP.id.replace('paragraph-', '');
        const p = bookData["pages"][currentPage]["paragraphs"][id];
        if (!p || p.page_number == null) {
            console.warn(`toggleJoinForSelected: paragraph not found or page_number missing: ${currentPage} ${id}`);
            return;
        }
        const joinElement = divP.querySelector('.join');
        if (!joinElement) {
            console.warn(`パラグラフ ${divP.id} に join 要素が見つかりませんでした。`);
            return;
        }

        const isVisible = joinElement.classList.toggle('visible');
        if (isVisible) {
            p.join = 1;
        } else {
            if (p && ('join' in p)) delete p.join;
        }

        const joinCheckbox = divP.querySelector('.join-checkbox');
        if (joinCheckbox) joinCheckbox.checked = isVisible;

        sendParagraphs.push({
            id: id,
            page_number: p.page_number,
            join: isVisible ? 1 : 0
        });
    });

    if (sendParagraphs.length === 0) return;

    isPageEdited = true; // ページが編集されたことを示すフラグを立てる
    
    // カーソルを砂時計に変更
    const originalCursor = document.body.style.cursor;
    document.body.style.cursor = 'wait';
    
    try {
        // join 変更はサーバ側で src_joined を再計算し、必要に応じて再読込が走る。
        // このとき、未保存の order/group 変更があると巻き戻るので、ページ全体を保存してから反映する。
        if (typeof saveCurrentPageOrder === 'function') {
            await saveCurrentPageOrder();
        } else {
            await updateParagraphs(sendParagraphs);
        }
    } catch (e) {
        console.error('toggleJoinForSelected: updateParagraphs failed', e);
        alert('join保存中にエラーが発生しました（詳細はコンソールを確認してください）');
    } finally {
        // カーソルを元に戻す
        document.body.style.cursor = originalCursor || 'auto';
    }
}

function toggleEditUICurrent() {
    const current = document.querySelector('.paragraph-box.current');
    if (!current) return;
    const editUI = current.querySelector('.edit-ui');
    if (!editUI) return;
    const isVisible = editUI && editUI.style.display === 'block';

    if (isVisible) {
        cancelEditUI(current);
    } else {
        toggleEditUI(current);
    }
}

function toggleEditUI(divSrc) {
    const editUI = divSrc.querySelector('.edit-ui');
    if (!editUI) return;
    const isVisible = editUI && editUI.style.display === 'block';

    if (isVisible) {
        cancelEditUI(divSrc);
    } else {
        // 他を全部閉じる
        document.querySelectorAll('.edit-ui').forEach(ui => {
            const box = ui.closest('.paragraph-box');
            if (box !== divSrc) cancelEditUI(box);
        });

        divSrc.classList.add('editing');
        const srcText = divSrc.querySelector('.src-text');
        const transText = divSrc.querySelector('.trans-text');
        const commentText = divSrc.querySelector('.comment-text');

        // 編集時は「元の文字列」に戻す（リンク化で混入した <a> を編集させない）
        if (srcText?.dataset?.original != null) srcText.innerHTML = srcText.dataset.original;
        if (transText?.dataset?.original != null) transText.innerHTML = transText.dataset.original;
        if (commentText?.dataset?.original != null) commentText.innerHTML = commentText.dataset.original;

        editUI.style.display = 'block';
        if (srcText) srcText.contentEditable = true;
        if (transText) transText.contentEditable = true;
        if (commentText) commentText.contentEditable = true;
        $("#srcParagraphs").sortable("disable");
        divSrc.style.cursor = 'text';
    }
}

function cancelEditUI(divSrc) {
    const editUI = divSrc.querySelector('.edit-ui');
    if (!editUI || editUI.style.display !== 'block') return;
    editUI.style.display = 'none';

    divSrc.classList.remove('editing');
    const srcText = divSrc.querySelector('.src-text');
    const transText = divSrc.querySelector('.trans-text');
    const commentText = divSrc.querySelector('.comment-text');
    const editButton = divSrc.querySelector('.edit-button');
    if (srcText) {
        srcText.contentEditable = false;
        srcText.innerHTML = srcText.dataset.original;
    }
    if (transText) {
        transText.contentEditable = false;
        transText.innerHTML = transText.dataset.original;
    }
    if (commentText) {
        // コメント列は常に編集可能な状態を保つ（contentEditableはtrueのまま）
        // commentText.contentEditable = false; // ← 実行しない
        // commentText.innerHTML の復元もしない
    }

    // 非編集表示に戻った後、URLをリンク化
    linkifyParagraphBox(divSrc);
    const idStr = (divSrc.id || '').replace('paragraph-', '');
    const paragraphDict = bookData?.pages?.[currentPage]?.paragraphs?.[idStr];
    applyParagraphMarkup(divSrc, paragraphDict);
    // if (editButton) editButton.style.visibility = 'visible';
    $("#srcParagraphs").sortable("enable");
    divSrc.style.cursor = '';
}

/** @function focusNearestHeading */
function focusNearestHeading(direction) {
    const paragraphs = getAllParagraphs();
    let index = currentParagraphIndex;

    while (true) {
        index += direction;

        // 範囲外に出た場合
        if (index < 0) {
            console.warn('見出しが見つかりませんでした。先頭に移動します。');
            setCurrentParagraph(0); // 先頭パラグラフに移動
            return;
        }
        if (index >= paragraphs.length) {
            console.warn('見出しが見つかりませんでした。末尾に移動します。');
            setCurrentParagraph(paragraphs.length - 1); // 末尾パラグラフに移動
            return;
        }

        const paragraph = paragraphs[index];
        const idStr = paragraph.id.replace('paragraph-', '');
        const p = bookData["pages"][currentPage]["paragraphs"][idStr]; // 辞書アクセス

        // 見出し (h1 ～ h6) の場合に移動
        if (p && /^h[1-6]$/.test(p.block_tag)) {
            setCurrentParagraph(index);
            return;
        }
    }
}

function isHeadingParagraphDiv(paragraphDiv) {
    if (!paragraphDiv) return false;
    const idStr = (paragraphDiv.id || '').replace('paragraph-', '');
    const p = bookData?.pages?.[currentPage]?.paragraphs?.[idStr];
    return !!(p && /^h[1-6]$/.test(p.block_tag));
}

function findPreviousHeadingIndex(paragraphs, fromIndex, skipSet = null) {
    for (let i = fromIndex - 1; i >= 0; i--) {
        const el = paragraphs[i];
        if (skipSet && skipSet.has(el)) continue;
        if (isHeadingParagraphDiv(el)) return i;
    }
    return -1;
}

function findNextHeadingIndex(paragraphs, fromIndex, skipSet = null) {
    for (let i = fromIndex + 1; i < paragraphs.length; i++) {
        const el = paragraphs[i];
        if (skipSet && skipSet.has(el)) continue;
        if (isHeadingParagraphDiv(el)) return i;
    }
    return -1;
}

function moveParagraphElementsRelativeToHeading(movingElements, mode, preserveSelection) {
    const container = document.getElementById('srcParagraphs');
    if (!container) return;
    if (!movingElements || movingElements.length === 0) return;

    const all = Array.from(container.children);
    const movingSet = new Set(movingElements);

    const currentDiv = document.querySelector('.paragraph-box.current');
    const focusDiv = (currentDiv && movingSet.has(currentDiv)) ? currentDiv : movingElements[0];
    const focusIndex = focusDiv ? all.indexOf(focusDiv) : -1;
    if (focusIndex < 0) return;

    const remaining = all.filter(el => !movingSet.has(el));

    let insertIndexInRemaining = 0;
    if (mode === 'prevHeadingBelow') {
        const prevHeadingIndex = findPreviousHeadingIndex(all, focusIndex, movingSet);
        if (prevHeadingIndex < 0) {
            insertIndexInRemaining = 0;
        } else {
            const headingEl = all[prevHeadingIndex];
            const headingPos = remaining.indexOf(headingEl);
            insertIndexInRemaining = headingPos >= 0 ? headingPos + 1 : 0;
        }
    } else if (mode === 'nextHeadingAbove') {
        const nextHeadingIndex = findNextHeadingIndex(all, focusIndex, movingSet);
        if (nextHeadingIndex < 0) {
            insertIndexInRemaining = remaining.length;
        } else {
            const headingEl = all[nextHeadingIndex];
            const headingPos = remaining.indexOf(headingEl);
            insertIndexInRemaining = headingPos >= 0 ? headingPos : remaining.length;
        }
    } else {
        console.warn(`Unknown move mode: ${mode}`);
        return;
    }

    const refNode = remaining[insertIndexInRemaining] || null;
    movingElements.forEach(el => container.insertBefore(el, refNode));
    isPageEdited = true;

    const paragraphs = getAllParagraphs();
    const newIndex = paragraphs.indexOf(focusDiv);
    if (newIndex >= 0) {
        setCurrentParagraph(newIndex, preserveSelection);
    }
}

function moveCurrentBelowPreviousHeading() {
    const currentDiv = document.querySelector('.paragraph-box.current');
    if (!currentDiv) return;
    moveParagraphElementsRelativeToHeading([currentDiv], 'prevHeadingBelow', false);
}

function moveCurrentAboveNextHeading() {
    const currentDiv = document.querySelector('.paragraph-box.current');
    if (!currentDiv) return;
    moveParagraphElementsRelativeToHeading([currentDiv], 'nextHeadingAbove', false);
}

function moveSelectedBelowPreviousHeading() {
    const selected = getSelectedOrCurrentParagraphsInOrder();
    if (!selected || selected.length === 0) return;
    moveParagraphElementsRelativeToHeading(selected, 'prevHeadingBelow', true);
}

function moveSelectedAboveNextHeading() {
    const selected = getSelectedOrCurrentParagraphsInOrder();
    if (!selected || selected.length === 0) return;
    moveParagraphElementsRelativeToHeading(selected, 'nextHeadingAbove', true);
}

/** @function selectUntilNextHeading */
function selectUntilNextHeading() {
    const paragraphs = getAllParagraphs();
    let index = currentParagraphIndex;
    let foundHeading = false;

    while (index < paragraphs.length - 1) {
        index++;

        const paragraph = paragraphs[index];
        const idStr = paragraph.id.replace('paragraph-', '');
        const p = bookData["pages"][currentPage]["paragraphs"][idStr]; // 辞書アクセス

        // 見出し (h1 ～ h6) に到達したら終了
        if (p && /^h[1-6]$/.test(p.block_tag)) {
            foundHeading = true;
            break;
        }

        // 選択状態にする
        paragraph.classList.add('selected');
    }

    // 見出しが見つからなければ末尾行まで選択
    if (!foundHeading) {
        for (let i = currentParagraphIndex + 1; i < paragraphs.length; i++) {
            paragraphs[i].classList.add('selected');
        }
    } else {
        // 見出しが見つかった場合、カレント行を見出しの手前に設定
        index--;
    }

    // 選択範囲の末尾をカレントにしてフォーカス
    setCurrentParagraph(index, true);
}

/** @function selectUntilPreviousHeading */
function selectUntilPreviousHeading() {
    const paragraphs = getAllParagraphs();
    let index = currentParagraphIndex;
    let foundHeading = false;

    while (index > 0) {
        index--;

        const paragraph = paragraphs[index];
        const idStr = paragraph.id.replace('paragraph-', '');
        const p = bookData["pages"][currentPage]["paragraphs"][idStr]; // 辞書アクセス

        // 見出し (h1 ～ h6) に到達したら終了
        if (p && /^h[1-6]$/.test(p.block_tag)) {
            foundHeading = true;
            break;
        }

        // 選択状態にする
        paragraph.classList.add('selected');
    }

    // 見出しが見つからなければ先頭行まで選択
    if (!foundHeading) {
        for (let i = 0; i < currentParagraphIndex; i++) {
            paragraphs[i].classList.add('selected');
        }
    }

    // 選択範囲の先頭をカレントにしてフォーカス
    setCurrentParagraph(index, true);
}

/** @function resetTranslationForParagraph
 * 指定されたパラグラフの翻訳関連情報をリセットする
 * src_joined の内容を src_replaced, trans_auto, trans_text にコピーし、翻訳状態を none に戻す
 */
async function resetTranslation(paragraphDict) {
    if (paragraphDict) {
        paragraphDict.src_replaced = paragraphDict.src_joined;
        paragraphDict.trans_auto = paragraphDict.src_joined; // src_joined をコピー
        paragraphDict.trans_text = paragraphDict.src_joined; // src_joined をコピー
        paragraphDict.trans_status = 'none'; // 翻訳状態を none にリセット

        try {
            await saveParagraphData(paragraphDict);
        } catch (error) {
            console.error('Error saving paragraph:', error);
            alert('データ保存中にエラーが発生しました。詳細はコンソールを確認してください。');
        }

        // DOM要素の表示も更新が必要であればここに追加
        const paragraphDiv = document.getElementById(`paragraph-${paragraphDict.id}`);
        if (paragraphDiv) {
            paragraphDiv.querySelector('.src-replaced').innerText = paragraphDict.src_replaced;
            paragraphDiv.querySelector('.trans-auto').innerText = paragraphDict.trans_auto;
            paragraphDiv.querySelector('.trans-text').innerText = paragraphDict.trans_text;
            // ステータス表示の更新
            const editBox = paragraphDiv.querySelector('.edit-box');
            if (editBox) {
                editBox.className = `edit-box status-${paragraphDict.trans_status}`;
            }
            const editUi = paragraphDiv.querySelector('.edit-ui');
            if (editUi) {
                editUi.className = `edit-ui status-${paragraphDict.trans_status}`;
            }
             const statusRadio = paragraphDiv.querySelector(`input[name='status-${paragraphDict.id}'][value='${paragraphDict.trans_status}']`);
            if (statusRadio) {
                statusRadio.checked = true;
            }
        }
        isPageEdited = true; // ページが編集されたことを示すフラグを立てる
    } else {
        console.warn("resetTranslationForParagraph: paragraphDict is undefined.");
    }
}

/** @function resetTranslationForSelectedParagraphs
 * 選択されたすべてのパラグラフの翻訳関連情報をリセットする
 */
async function resetTranslationForSelected() {
    if (!confirm("選択されたパラグラフのJoined列を翻訳列にコピーします。よろしいですか？")) return;

    const selectedParagraphs = getSelectedParagraphsInOrder(); // 選択されたパラグラフのDOM要素を取得
    if (selectedParagraphs.length === 0) {
        console.warn("選択されたパラグラフがありません。");
        return;
    }

    for (const divP of selectedParagraphs) {
        const id = divP.id.replace('paragraph-', '');
        const paragraphDict = bookData["pages"][currentPage]["paragraphs"][id];
        if (paragraphDict) {
            await resetTranslation(paragraphDict);
        } else {
            console.warn(`resetTranslationForSelectedParagraphs: Paragraph with ID ${id} not found in paragraphs.`);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initMarkupTools();
});
