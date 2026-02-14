(function () {
  function $(id) {
    return document.getElementById(id);
  }

  function escapeRegExp(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function buildQueryRegex(query) {
    const terms = String(query || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (terms.length === 0) return null;
    const pattern = terms.map(escapeRegExp).join("|");
    return new RegExp(`(${pattern})`, "gi");
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function highlightSnippet(text, query) {
    const regex = buildQueryRegex(query);
    if (!regex) return escapeHtml(text);

    const raw = String(text ?? "");
    let last = 0;
    let out = "";
    let m;
    regex.lastIndex = 0;
    while ((m = regex.exec(raw)) !== null) {
      const start = m.index;
      const matched = m[0];
      const end = start + matched.length;
      if (start > last) {
        out += escapeHtml(raw.slice(last, start));
      }
      out += `<span class="search-highlight">${escapeHtml(matched)}</span>`;
      last = end;
    }
    if (last < raw.length) {
      out += escapeHtml(raw.slice(last));
    }
    return out;
  }

  const SearchHighlight = {
    clear(root) {
      const scope = root || document;
      scope.querySelectorAll("span.search-highlight").forEach((span) => {
        const text = document.createTextNode(span.textContent || "");
        span.replaceWith(text);
      });
      // normalize nearby text nodes (best-effort)
      try {
        if (scope && scope.normalize) scope.normalize();
      } catch (_) {
        // ignore
      }
    },

    applyToParagraph(paragraphEl, query) {
      if (!paragraphEl) return;
      if (paragraphEl.classList.contains("editing")) return;

      const regex = buildQueryRegex(query);
      this.clear(paragraphEl);
      if (!regex) return;

      const targets = paragraphEl.querySelectorAll(
        ".src-text, .src-joined, .trans-auto, .trans-text"
      );
      targets.forEach((el) => this._highlightElement(el, regex));
    },

    _highlightElement(el, regex) {
      if (!el) return;
      if (el.isContentEditable) return;

      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
        acceptNode: (node) => {
          if (!node || !node.nodeValue || !node.nodeValue.trim()) {
            return NodeFilter.FILTER_REJECT;
          }
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          if (parent.closest("a")) return NodeFilter.FILTER_REJECT;
          if (parent.isContentEditable) return NodeFilter.FILTER_REJECT;
          if (parent.closest("span.search-highlight")) {
            return NodeFilter.FILTER_REJECT;
          }
          return NodeFilter.FILTER_ACCEPT;
        },
      });

      const nodes = [];
      let n;
      while ((n = walker.nextNode())) nodes.push(n);

      for (const textNode of nodes) {
        const text = textNode.nodeValue;
        regex.lastIndex = 0;
        if (!regex.test(text)) continue;
        regex.lastIndex = 0;

        const frag = document.createDocumentFragment();
        let last = 0;
        let m;
        while ((m = regex.exec(text)) !== null) {
          const start = m.index;
          const matched = m[0];
          if (start > last) {
            frag.appendChild(document.createTextNode(text.slice(last, start)));
          }
          const span = document.createElement("span");
          span.className = "search-highlight";
          span.textContent = matched;
          frag.appendChild(span);
          last = start + matched.length;
        }
        if (last < text.length) {
          frag.appendChild(document.createTextNode(text.slice(last)));
        }
        textNode.parentNode.replaceChild(frag, textNode);
      }
    },
  };

  window.SearchHighlight = SearchHighlight;

  async function waitForParagraphElement(paraId, timeoutMs = 2500) {
    const deadline = Date.now() + timeoutMs;
    const elId = `paragraph-${paraId}`;
    while (Date.now() < deadline) {
      const el = document.getElementById(elId);
      if (el) return el;
      await new Promise((r) => setTimeout(r, 50));
    }
    return null;
  }

  const TocSearchPanel = {
    lastQuery: "",
    lastResults: [],

    init() {
      const input = $("tocSearchInput");
      const button = $("tocSearchButton");
      const clearButton = $("tocSearchClearButton");
      const results = $("tocSearchResults");

      if (!input || !button || !clearButton || !results) return;

      button.addEventListener("click", () => this.search(input.value));
      clearButton.addEventListener("click", () => {
        input.value = "";
        this.lastQuery = "";
        this.lastResults = [];
        this.setStatus("");
        this.renderResults([]);
        // clear highlight on current page
        const pageRoot = document.getElementById("srcParagraphs");
        if (pageRoot) SearchHighlight.clear(pageRoot);
        if (typeof clearHighlights === "function") {
          clearHighlights();
        }
        if (typeof pdfClearFindHighlight === "function") {
          pdfClearFindHighlight();
        }
      });

      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          this.search(input.value);
        }
      });

      results.addEventListener("click", (e) => {
        const row = e.target.closest(".search-result");
        if (!row) return;
        const page = parseInt(row.dataset.pageNumber, 10);
        const id = row.dataset.id;
        if (!Number.isFinite(page) || !id) return;
        void this.jumpTo(page, id);
      });
    },

    setStatus(text) {
      const el = $("tocSearchStatus");
      if (!el) return;
      el.textContent = text || "";
    },

    async search(q) {
      const query = String(q || "").trim();
      this.lastQuery = query;

      if (!query) {
        this.setStatus("検索語を入力してください");
        this.renderResults([]);
        return;
      }

      if (typeof pdfName === "undefined" || !pdfName) {
        this.setStatus("pdfName が未初期化です");
        return;
      }

      this.setStatus("検索中…");

      try {
        const url = `/api/search/${encodeURIComponent(pdfName)}?q=${encodeURIComponent(
          query
        )}&limit=200`;
        const res = await fetch(url);
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status !== "ok") {
          this.setStatus(data.message || `検索に失敗しました (${res.status})`);
          this.renderResults([]);
          return;
        }

        const results = Array.isArray(data.results) ? data.results : [];
        this.setStatus(`${results.length} 件`);
        this.renderResults(results);
        this.lastResults = results;
        this.applyHighlightsForCurrentPage();
      } catch (e) {
        this.setStatus(`検索に失敗しました: ${e}`);
        this.renderResults([]);
      }
    },

    applyHighlightsForCurrentPage() {
      const query = this.lastQuery;
      const pageRoot = document.getElementById("srcParagraphs");
      if (pageRoot) SearchHighlight.clear(pageRoot);

      if (!query) {
        if (typeof pdfClearFindHighlight === "function") {
          pdfClearFindHighlight();
        }
        if (typeof clearHighlights === "function") {
          clearHighlights();
        }
        return;
      }

      const pageNum = typeof currentPage !== "undefined" ? currentPage : null;
      if (!pageNum) return;

      const hits = (this.lastResults || []).filter(
        (r) => Number(r.page_number) === Number(pageNum)
      );

      hits.forEach((r) => {
        const el = document.getElementById(`paragraph-${r.id}`);
        if (el) SearchHighlight.applyToParagraph(el, query);
      });

      if (typeof clearHighlights === "function") {
        clearHighlights();
      }

      if (typeof pdfFindHighlight === "function") {
        const applied = pdfFindHighlight(query, { highlightAll: true });
        if (applied) return;
      }
    },

    renderResults(results) {
      const container = $("tocSearchResults");
      if (!container) return;
      container.innerHTML = "";

      for (const r of results) {
        const row = document.createElement("div");
        row.className = "search-result";
        row.dataset.pageNumber = String(r.page_number ?? "");
        row.dataset.id = String(r.id ?? "");

        const page = document.createElement("div");
        page.className = "search-page";
        page.textContent = String(r.page_number ?? "-");

        const snippet = document.createElement("div");
        snippet.className = "search-snippet";
        snippet.innerHTML = highlightSnippet(String(r.snippet ?? ""), this.lastQuery);

        row.appendChild(page);
        row.appendChild(snippet);
        container.appendChild(row);
      }
    },

    async jumpTo(pageNumber, paragraphId) {
      const query = this.lastQuery;

      // clear highlight on current page before jumping
      const pageRoot = document.getElementById("srcParagraphs");
      if (pageRoot) SearchHighlight.clear(pageRoot);

      if (typeof jumpToPage !== "function") {
        this.setStatus("jumpToPage が見つかりません");
        return;
      }

      if (pageNumber !== currentPage) {
        await jumpToPage(pageNumber);
      }

      const el = await waitForParagraphElement(paragraphId);
      if (!el) {
        this.setStatus("段落が見つかりません（表示更新待ちに失敗）");
        return;
      }

      el.scrollIntoView({ behavior: "auto", block: "start" });
      SearchHighlight.applyToParagraph(el, query);

      if (typeof setCurrentParagraph === "function") {
        const paragraphs = typeof getAllParagraphs === "function" ? getAllParagraphs() : [];
        const idx = paragraphs.findIndex((p) => p.id === `paragraph-${paragraphId}`);
        if (idx >= 0) {
          setCurrentParagraph(idx, false, { scrollIntoView: false });
          this.applyHighlightsForCurrentPage();
          return;
        }
      }

      const paragraphDict =
        typeof bookData !== "undefined"
          ? bookData?.pages?.[currentPage]?.paragraphs?.[paragraphId]
          : null;
      if (paragraphDict?.bbox && typeof highlightRectsOnPage === "function") {
        highlightRectsOnPage(currentPage, [paragraphDict.bbox]);
      } else if (typeof clearHighlights === "function") {
        clearHighlights();
      }
      this.applyHighlightsForCurrentPage();
    },
  };

  window.TocSearchPanel = TocSearchPanel;

  document.addEventListener("DOMContentLoaded", () => {
    TocSearchPanel.init();
  });
})();
