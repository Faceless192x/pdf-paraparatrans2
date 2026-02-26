// Debug: set `window.TOC_DEBUG = true` to enable console logs.
function tocDebugLog(...args) {
  if (window.TOC_DEBUG) {
    console.log(...args);
  }
}

function isUrlBookTocMode() {
  const bodyType = document.body?.dataset?.bookType;
  if (bodyType === 'url') return true;
  return String(bookData?.source_type || '') === 'url';
}

function applyTocColumnModeStyles() {
  const pageCols = document.querySelectorAll('.toc-page');
  const srcCols = document.querySelectorAll('.toc-src');
  const transCols = document.querySelectorAll('.toc-trans');
  const readToggleState = (toggleId, fallback = true) => {
    const input = document.getElementById(`auto-toggle-input-${toggleId}`);
    if (input && input.type === 'checkbox') {
      return Boolean(input.checked);
    }
    if (window.autoToggle && typeof window.autoToggle.getState === 'function') {
      const cached = window.autoToggle.getState(toggleId);
      if (typeof cached === 'boolean') return cached;
    }
    return fallback;
  };

  const showPage = readToggleState('toggleTocPage', true);
  const showSrc = readToggleState('toggleTocSrc', true);
  const showTrans = readToggleState('toggleTocTrans', true);

  const setDisplay = (elements, value) => {
    elements.forEach((el) => {
      el.style.display = value;
    });
  };

  setDisplay(pageCols, showPage ? 'table-cell' : 'none');
  setDisplay(srcCols, showSrc ? 'table-cell' : 'none');
  setDisplay(transCols, showTrans ? 'table-cell' : 'none');

  const srcMarkers = document.querySelectorAll('.url-nav-src .toc-toggle, .url-nav-src .toc-toggle-blank');
  const transMarkers = document.querySelectorAll('.url-nav-trans .toc-toggle, .url-nav-trans .toc-toggle-blank');
  const srcGaps = document.querySelectorAll('.url-nav-src .url-nav-toggle-gap');
  const transGaps = document.querySelectorAll('.url-nav-trans .url-nav-toggle-gap');

  const showSrcMarker = showSrc;
  const showTransMarker = !showSrc && showTrans;

  srcMarkers.forEach((el) => {
    el.style.display = showSrcMarker ? 'flex' : 'none';
  });
  transMarkers.forEach((el) => {
    el.style.display = showTransMarker ? 'flex' : 'none';
  });
  srcGaps.forEach((el) => {
    el.style.display = showSrcMarker ? 'inline-block' : 'none';
  });
  transGaps.forEach((el) => {
    el.style.display = showTransMarker ? 'inline-block' : 'none';
  });
}

window.applyTocColumnModeStyles = applyTocColumnModeStyles;

function shortUrlForNav(rawUrl) {
  const text = String(rawUrl || '').trim();
  if (!text) return '';
  try {
    const u = new URL(text);
    const path = `${u.pathname || '/'}${u.search || ''}`;
    return `${u.host}${path}`;
  } catch (_e) {
    return text;
  }
}

function getFirstParagraphForUrlPage(page) {
  const paragraphs = (page && typeof page === 'object' && page.paragraphs && typeof page.paragraphs === 'object')
    ? Object.values(page.paragraphs)
    : [];
  if (!Array.isArray(paragraphs) || paragraphs.length === 0) {
    return null;
  }

  const list = paragraphs
    .filter((p) => p && typeof p === 'object')
    .map((p) => {
      const order = Number(p.order);
      const columnOrder = Number(p.column_order);
      const bboxY = Number(Array.isArray(p.bbox) ? p.bbox[1] : 0);
      return {
        paragraph: p,
        order: Number.isFinite(order) ? order : Number.MAX_SAFE_INTEGER,
        columnOrder: Number.isFinite(columnOrder) ? columnOrder : Number.MAX_SAFE_INTEGER,
        bboxY: Number.isFinite(bboxY) ? bboxY : Number.MAX_SAFE_INTEGER,
      };
    });

  if (list.length === 0) return null;

  list.sort((a, b) => {
    if (a.order !== b.order) return a.order - b.order;
    if (a.columnOrder !== b.columnOrder) return a.columnOrder - b.columnOrder;
    if (a.bboxY !== b.bboxY) return a.bboxY - b.bboxY;
    return String(a.paragraph?.id || '').localeCompare(String(b.paragraph?.id || ''));
  });

  return list[0].paragraph;
}

function ensureUrlPageNavClientState() {
  if (!isUrlBookTocMode()) return null;
  if (!bookData || typeof bookData !== 'object') return null;

  const pages = (bookData.pages && typeof bookData.pages === 'object') ? bookData.pages : {};
  const pageIds = Object.keys(pages).length > 0
    ? Object.keys(pages)
    : Object.keys(bookData.page_url_map || {});
  pageIds.sort((a, b) => {
    const aa = Number(a);
    const bb = Number(b);
    if (Number.isFinite(aa) && Number.isFinite(bb)) return aa - bb;
    return String(a).localeCompare(String(b));
  });

  if (!bookData.page_nav || typeof bookData.page_nav !== 'object') {
    bookData.page_nav = { root_children: [], nodes: {}, selected_node_id: '', revision: 1 };
  }
  const nav = bookData.page_nav;
  if (!Array.isArray(nav.root_children)) nav.root_children = [];
  if (!nav.nodes || typeof nav.nodes !== 'object') nav.nodes = {};

  const pageToNode = {};
  const usedIds = new Set(Object.keys(nav.nodes));
  for (const [nodeId, node] of Object.entries(nav.nodes)) {
    const pageId = String(node?.page_id || '');
    if (pageId) pageToNode[pageId] = nodeId;
  }

  const appendRoot = [];
  for (const pageId of pageIds) {
    if (pageToNode[pageId]) continue;
    let nodeId = `n_${String(pageId).replace(/[^a-zA-Z0-9_-]/g, '_')}`;
    if (!nodeId) nodeId = 'n_page';
    let suffix = 2;
    while (usedIds.has(nodeId)) {
      nodeId = `${nodeId}_${suffix}`;
      suffix += 1;
    }
    usedIds.add(nodeId);
    nav.nodes[nodeId] = {
      id: nodeId,
      page_id: String(pageId),
      parent_id: null,
      children: [],
      collapsed: false,
      manual_title: null,
    };
    appendRoot.push(nodeId);
  }
  if (appendRoot.length > 0) {
    nav.root_children.push(...appendRoot);
  }

  if (!nav.selected_node_id || !nav.nodes[nav.selected_node_id]) {
    nav.selected_node_id = nav.root_children[0] || '';
  }
  if (!Number.isFinite(Number(nav.revision)) || Number(nav.revision) < 1) {
    nav.revision = 1;
  }
  return nav;
}

window.ensureUrlPageNavClientState = ensureUrlPageNavClientState;

function refreshUrlNavRowVisibility() {
  if (!isUrlBookTocMode()) return;
  const nav = ensureUrlPageNavClientState();
  if (!nav) return;

  const openSet = new Set();
  const walk = (nodeId, parentVisible) => {
    const node = nav.nodes[nodeId];
    if (!node) return;
    const row = document.querySelector(`#toc-row-${nodeId}`);
    if (row) {
      row.style.display = parentVisible ? 'table-row' : 'none';
      const isOpen = !Boolean(node.collapsed);
      row.setAttribute('data-open', isOpen ? 'true' : 'false');
      if (isOpen) openSet.add(nodeId);
    }
    const childVisible = parentVisible && !Boolean(node.collapsed);
    for (const childId of node.children || []) {
      walk(childId, childVisible);
    }
  };

  for (const rootId of nav.root_children || []) {
    walk(rootId, true);
  }
}

function renderUrlPageNavRows() {
  const nav = ensureUrlPageNavClientState();
  if (!nav) return '';

  const rows = [];
  const visited = new Set();

  const walk = (nodeId, parentId = null, nestLevel = 1) => {
    const node = nav.nodes[nodeId];
    if (!node || visited.has(nodeId)) return;
    visited.add(nodeId);

    const pageId = String(node.page_id || '');
    const page = bookData?.pages?.[pageId] || {};
    const preview = bookData?.page_preview_map?.[pageId] || {};
    const pageUrl = String(page.url || bookData?.page_url_map?.[pageId] || '').trim();
    const firstParagraph = getFirstParagraphForUrlPage(page);
    const paragraphId = String(firstParagraph?.id || preview?.paragraph_id || '').trim();
    const indentText = '　'.repeat(Math.max(0, nestLevel - 1));
    const srcLabel = String(
      firstParagraph?.src_text
      || preview?.src_text
      || firstParagraph?.src_joined
      || node.manual_title
      || page.title
      || pageUrl
      || `Page ${pageId}`
    ).trim();
    const transLabel = String(
      firstParagraph?.trans_text
      || preview?.trans_text
      || firstParagraph?.trans_auto
      || shortUrlForNav(pageUrl)
      || ''
    ).trim();
    const hasChildren = Array.isArray(node.children) && node.children.length > 0;
    const rowId = `toc-row-${nodeId}`;
    const rowClass = parentId ? `child-of-${parentId}` : '';
    const selectedClass = String(nav.selected_node_id || '') === nodeId ? 'toc-row-selected' : '';
    const isOpen = !Boolean(node.collapsed);

    const toggleMarker = hasChildren
      ? `<span class="toc-toggle nest-level-${nestLevel}" data-target="${nodeId}"></span>`
      : `<span class="toc-toggle-blank nest-level-${nestLevel}"></span>`;

    rows.push(`
      <tr id="${rowId}" class="${rowClass} ${selectedClass}" data-row-id="${nodeId}" data-node-id="${nodeId}" data-parent="${parentId || ''}" data-nest-level="${nestLevel}" data-open="${isOpen ? 'true' : 'false'}">
        <td class="toc-page">${pageId}</td>
        <td class="toc-src url-nav-src">
          ${toggleMarker}<span class="url-nav-toggle-gap" aria-hidden="true"></span><a class="url-nav-label" href="#" data-node-id="${nodeId}" data-page-number="${pageId}" data-id="${paragraphId}">${indentText}${srcLabel}</a>
        </td>
        <td class="toc-trans url-nav-trans">
          ${toggleMarker}<span class="url-nav-toggle-gap" aria-hidden="true"></span><a class="url-nav-label" href="#" data-node-id="${nodeId}" data-page-number="${pageId}" data-id="${paragraphId}">${indentText}${transLabel}</a>
        </td>
      </tr>
    `);

    for (const childId of node.children || []) {
      walk(childId, nodeId, Math.min(6, nestLevel + 1));
    }
  };

  for (const rootId of nav.root_children || []) {
    walk(rootId, null, 1);
  }

  return rows.join('\n');
}

async function moveSelectedUrlNav(op) {
  if (!isUrlBookTocMode()) return;
  const nav = ensureUrlPageNavClientState();
  if (!nav) return;

  const nodeId = String(nav.selected_node_id || '').trim();
  if (!nodeId) return;

  try {
    const res = await fetch('/api/url_book/page_nav/move', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        book_name: pdfName,
        node_id: nodeId,
        op,
        revision: Number(nav.revision || 1),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.status !== 'ok') {
      if (res.status === 409 && data.page_nav) {
        bookData.page_nav = data.page_nav;
        showToc();
      }
      alert(data.message || `ページリスト更新に失敗しました (${res.status})`);
      return;
    }
    bookData.page_nav = data.page_nav || bookData.page_nav;
    showToc();
  } catch (e) {
    alert(`ページリスト更新に失敗しました: ${e}`);
  }
}

async function rebuildUrlNavTree() {
  if (!isUrlBookTocMode()) return;
  if (!confirm('現在のページツリーをページ同期します。よろしいですか？')) return;

  try {
    const res = await fetch('/api/url_book/page_nav/rebuild', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ book_name: pdfName }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.status !== 'ok') {
      alert(data.message || `ページツリー同期に失敗しました (${res.status})`);
      return;
    }
    bookData.page_nav = data.page_nav || bookData.page_nav;
    showToc();
  } catch (e) {
    alert(`ページツリー同期に失敗しました: ${e}`);
  }
}

function bindUrlNavControls() {
  const rebuildButton = document.getElementById('urlNavRebuild');
  if (rebuildButton && !rebuildButton.dataset.bound) {
    rebuildButton.dataset.bound = '1';
    rebuildButton.addEventListener('click', () => {
      rebuildUrlNavTree();
    });
  }

  const map = [
    ['urlNavMoveUp', 'up'],
    ['urlNavMoveDown', 'down'],
    ['urlNavIndent', 'indent'],
    ['urlNavOutdent', 'outdent'],
  ];
  for (const [id, op] of map) {
    const button = document.getElementById(id);
    if (!button || button.dataset.bound) continue;
    button.dataset.bound = '1';
    button.addEventListener('click', () => {
      moveSelectedUrlNav(op);
    });
  }
}

function updateTocHeaderMode() {
  const isUrl = isUrlBookTocMode();
  const actions = document.getElementById('urlPageNavActions');

  if (actions) {
    actions.style.display = isUrl ? 'inline-flex' : 'none';
  }
}

function initTocPanel() {
  tocDebugLog("Initializing TOC Panel");
  bindUrlNavControls();
}

function headlineParagraphs() {
  // 事前計算済みの目次（サーバ生成）を優先
  if (Array.isArray(bookData?.toc)) {
    return bookData.toc;
  }

  // bookData.pages{}をループして、各ページの段落を取得
  // その中から、block_tagがh1〜h6のものを抽出して、数値化したページ番号、order順で配列に格納する
  const headlines = [];

  for (const [page_number, page] of Object.entries(bookData["pages"])) {
    for (const [id, paragraphDict] of Object.entries(page["paragraphs"])) {
      const joinFlag = Number(paragraphDict?.join ?? 0);
      if (/^h[1-6]$/.test(paragraphDict["block_tag"]) && joinFlag !== 1) {
        headlines.push({
          rowId: paragraphDict["page_number"] + "_" + paragraphDict["id"],
          page_number: paragraphDict["page_number"],
          id: paragraphDict["id"],
          order: paragraphDict["order"] || 0,
          column_order: paragraphDict["column_order"] || 0,
          y0: paragraphDict["bbox"][1],
          block_tag: paragraphDict["block_tag"],
          src_joined:paragraphDict["src_joined"],
          trans_text:paragraphDict["trans_text"],
          join: joinFlag,
        });
      }
    }
  }

  // ページ番号とorder順でソート
  headlines.sort((a, b) => {
    if (a.page_number !== b.page_number) {
      return a.page_number - b.page_number; // ページ番号でソート
    }
    if (a.order !== b.order) return a.order - b.order;
    if (a.column_order !== b.column_order) return a.column_order - b.column_order;
    return a.y0 - b.y0;
  });

  return headlines;
}

function showToc(isTrans) {
  const tbody = document.querySelector(".tocTable tbody");

  updateTocHeaderMode();

  if (isUrlBookTocMode()) {
    tbody.innerHTML = renderUrlPageNavRows();
    refreshUrlNavRowVisibility();
    applyTocColumnModeStyles();
    return;
  }

  const paragraphsArray = headlineParagraphs();
  
  if (paragraphsArray.length === 0) {
    tbody.innerHTML = "";
  } else {
    // 辞書の値を配列にして buildTocTree に渡す
    const tocTree = buildTocTree(paragraphsArray);
    tbody.innerHTML = renderTocTableRows(tocTree);
    expandUpToLimit(30);
  }

  applyTocColumnModeStyles();
}

function renderTocTableRows(tocNode) {
  const rows = [];

  function walk(node, parentId = null) {
    if (node.block_tag !== "h0") {
      const hasChildren = node.children && node.children.length > 0;
      const rowId = `toc-row-${node.rowId}`;
      const nestLevelClass = `nest-level-${node.nestLevel}`;
      const rowClass = parentId ? `child-of-${parentId}` : "";

      const toggleMarker = hasChildren
        ? `<span class="toc-toggle ${nestLevelClass}" data-target="${node.rowId}"></span>`
        : `<span class="toc-toggle-blank ${nestLevelClass}"></span>`;

      rows.push(`
        <tr id="${rowId}" class="${rowClass}" data-row-id="${node.rowId}" data-id="${node.id}" data-parent="${parentId || ""}" data-nest-level="${node.nestLevel}" data-open="true">
          <td class="toc-page">${node.page_number}</td>
          <td class="toc-src toc-${node.block_tag}">
            ${toggleMarker}<a href="#" data-id="${node.id}" data-page-number="${node.page_number}">${node.src_joined}</a>
          </td>
          <td class="toc-trans toc-${node.block_tag}">
            ${toggleMarker}<a href="#" data-id="${node.id}" data-page-number="${node.page_number}">${node.trans_text}</a>
          </td>
        </tr>
      `);
    }

    for (const child of node.children || []) {
      walk(child, node.rowId);
    }
  }

  walk(tocNode);
  return rows.join("\n");
}


function buildTocTree(paragraphsArray) { // 引数を配列として受け取る
  // 配列をフィルタリング
  const headlines = paragraphsArray.filter(p => /^h[1-6]$/.test(p.block_tag) && Number(p?.join ?? 0) !== 1);

  const root = {
    rowId: "-1_-1", // ルートノードのIDは特別扱い
    id: "-1", // ルートノードのIDは特別扱い
    page_number: "-1",
    block_tag: "h0",
    src_joined: "src_root",
    trans_text: "trans_root",
    level: 0,
    nestLevel: 0,
    children: [],
  };

  const stack = [root];

  for (const headline of headlines) {
    const level = parseInt(headline.block_tag.slice(1));
    const node = {
      rowId: headline.rowId,
      id: headline.id,
      page_number: headline.page_number,
      block_tag: headline.block_tag,
      src_joined: headline.src_joined,
      trans_text: headline.trans_text,
      level,
      nestLevel: 0,
      children: [],
    };

    // 適切な親を探す
    while (stack.length > 0 && stack[stack.length - 1].level >= level) {
      stack.pop();
    }

    const parent = stack[stack.length - 1];
    node.nestLevel = parent.nestLevel + 1; // nestLevel を決定
    parent.children.push(node);
    stack.push(node);
  }

  return root;
}

// トグルクリックイベント
document.addEventListener("click", function (e) {
  if (e.target.classList.contains("toc-toggle")) {
    const toggleEl = e.target;
    const targetId = toggleEl.dataset.target;
    tocDebugLog("Toggle clicked:", targetId);
    const parentRow = document.querySelector(`#toc-row-${targetId}`);

    if (isUrlBookTocMode()) {
      const nav = ensureUrlPageNavClientState();
      if (!nav || !nav.nodes?.[targetId]) return;
      nav.nodes[targetId].collapsed = !Boolean(nav.nodes[targetId].collapsed);
      refreshUrlNavRowVisibility();
      return;
    }

    const wasOpen = parentRow.getAttribute("data-open") === "true";
    parentRow.setAttribute("data-open", wasOpen ? "false" : "true");

    updateDescendantVisibility(targetId);
  }
});

// 子の表示制御を再帰的に行う
function updateDescendantVisibility(parentId) {
  const parentRow = document.querySelector(`#toc-row-${parentId}`);
  const isOpen = parentRow.getAttribute("data-open") === "true";

  const childRows = document.querySelectorAll(`.child-of-${parentId}`);

  childRows.forEach(row => {
    const isDirectChild = row.dataset.parent === parentId;

    if (isOpen && isDirectChild) {
      row.style.display = "table-row";
    } else {
      row.style.display = "none";
    }

    // すべての子に対して data-open=false をセット（開いてる親でも孫は非表示にするため）
    row.setAttribute("data-open", "false");

    // 再帰的に孫以下の表示状態を更新
    updateDescendantVisibility(row.dataset.rowId);
  });
}

//目次を指定した閾値を超えるネストレベルまで展開する関数
function expandUpToLimit(maxCount = 20) {
  const rows = [...document.querySelectorAll(".tocTable tbody tr")];
  const nestLevelCounts = {};
  let total = 0;
  let maxNestLevel = 6;

  // 各ネストレベルごとの件数をカウント
  for (const row of rows) {
    const nestLevel = parseInt(row.dataset.nestLevel);
    nestLevelCounts[nestLevel] = (nestLevelCounts[nestLevel] || 0) + 1;
  }

  // maxCount を超えない最大のネストレベルを算出
  for (let nestLevel = 1; nestLevel <= 6; nestLevel++) {
    total += nestLevelCounts[nestLevel] || 0;
    if (total > maxCount) {
      maxNestLevel = nestLevel - 1;
      break;
    }
  }

  // 少なくともネストレベル1は表示する
  if (maxNestLevel < 1) {
    maxNestLevel = 1;
  }

  // 各行の表示・トグル状態を設定
  for (const row of rows) {
    const nestLevel = parseInt(row.dataset.nestLevel);
    const show = nestLevel <= maxNestLevel;
    const open = nestLevel < maxNestLevel; // maxNestLevel の行は閉じた状態にする

    row.style.display = show ? "table-row" : "none";
    row.setAttribute("data-open", show ? (open ? "true" : "false") : "false");
  }
}

document.addEventListener("click", function (event) {
  const link = event.target.closest(".toc-src a, .toc-trans a");
  if (!link) return;

  event.preventDefault();

  if (isUrlBookTocMode()) {
    const nodeId = String(link.dataset.nodeId || '').trim();
    const pageNumber = parseInt(link.dataset.pageNumber, 10);
    const paragraphId = String(link.dataset.id || '').trim();
    const nav = ensureUrlPageNavClientState();
    if (nav && nodeId && nav.nodes?.[nodeId]) {
      nav.selected_node_id = nodeId;
      showToc();
    }

    const scrollToParagraph = () => {
      if (!paragraphId) return;
      const el = document.getElementById(`paragraph-${paragraphId}`);
      if (el) el.scrollIntoView({ behavior: 'auto', block: 'start' });
    };

    if (Number.isFinite(pageNumber) && pageNumber >= 1) {
      if (pageNumber !== currentPage) {
        jumpToPage(pageNumber);
        setTimeout(scrollToParagraph, 500);
      } else {
        scrollToParagraph();
      }
    }
    return;
  }

  const id = link.dataset.id;
  const page_number = parseInt(link.dataset.pageNumber);

  const scrollTo = () => {
    const el = document.getElementById(`paragraph-${id}`);
    // 目次クリック時は「見出しへ即移動」させる（スムーズスクロール無効）
    if (el) el.scrollIntoView({ behavior: "auto", block: "start" });
  };

  if (page_number !== currentPage) {
    jumpToPage(page_number);
    setTimeout(scrollTo, 500); // ページ描画完了後にスクロール
  } else {
    scrollTo();
  }
});
