const statusOptions = [
    { value: 0, text: "0:大文字小文字を区別しない" },
    { value: 1, text: "1:大文字小文字を区別する" },
    { value: 5, text: "5:対象外（再抽出防止）" },
    { value: 6, text: "6:自動翻訳済み（カタカナ)" },
    { value: 7, text: "7:自動翻訳済み（翻訳しても英字）" },
    { value: 8, text: "8:自動翻訳済み" },
    { value: 9, text: "9:未翻訳" },
];

const state = {
    entries: [],
    filter: "",
    dictPath: "",
    dictCatalog: [],
    selectedIndexes: new Set(),
    comparePath: "",
    compareMap: {},
    pdfName: "",
    statusFilter: "all",
};

function $(id) {
    return document.getElementById(id);
}

function setStatus(message, isError = false) {
    const el = $("dictStatus");
    if (!el) return;
    el.textContent = message || "";
    el.style.color = isError ? "#b00020" : "#0a7a0a";
}

function normalizeFilter(value) {
    return (value || "").toLowerCase().trim();
}

function matchesFilter(entry) {
    const target = `${entry.original_word} ${entry.translated_word}`.toLowerCase();
    if (!target.includes(state.filter)) return false;
    if (state.statusFilter === "all") return true;
    return String(entry.status ?? "") === state.statusFilter;
}

function renderRow(entry, index, displayIndex) {
    const tr = document.createElement("tr");
    tr.dataset.index = String(index);

    const selectCell = document.createElement("td");
    const selectBox = document.createElement("input");
    selectBox.type = "checkbox";
    selectBox.checked = state.selectedIndexes.has(index);
    selectBox.addEventListener("change", () => {
        if (selectBox.checked) {
            state.selectedIndexes.add(index);
        } else {
            state.selectedIndexes.delete(index);
        }
        updateSelectAllState();
    });
    selectCell.appendChild(selectBox);

    const idxCell = document.createElement("td");
    idxCell.textContent = String(displayIndex);

    const originalCell = document.createElement("td");
    const originalInput = document.createElement("input");
    originalInput.className = "dict-maintenance__input";
    originalInput.type = "text";
    originalInput.value = entry.original_word || "";
    originalInput.addEventListener("input", () => {
        entry.original_word = originalInput.value;
        updateCompareCell();
    });
    originalCell.appendChild(originalInput);

    const translatedCell = document.createElement("td");
    const translatedInput = document.createElement("input");
    translatedInput.className = "dict-maintenance__input";
    translatedInput.type = "text";
    translatedInput.value = entry.translated_word || "";
    translatedInput.addEventListener("input", () => {
        entry.translated_word = translatedInput.value;
    });
    translatedCell.appendChild(translatedInput);

    const statusCell = document.createElement("td");
    const statusSelect = document.createElement("select");
    statusOptions.forEach((option) => {
        const opt = document.createElement("option");
        opt.value = String(option.value);
        opt.textContent = option.text;
        statusSelect.appendChild(opt);
    });
    statusSelect.value = String(entry.status ?? 0);
    statusSelect.addEventListener("change", () => {
        entry.status = parseInt(statusSelect.value, 10) || 0;
    });
    statusCell.appendChild(statusSelect);

    const compareCell = document.createElement("td");
    compareCell.className = "dict-maintenance__compare";
    function updateCompareCell() {
        const compareValue = state.compareMap[entry.original_word];
        if (compareValue) {
            compareCell.textContent = `${compareValue.translated_word} (${compareValue.status_text})`;
            compareCell.classList.remove("is-empty");
        } else {
            compareCell.textContent = "-";
            compareCell.classList.add("is-empty");
        }
    }
    updateCompareCell();

    const countCell = document.createElement("td");
    const countInput = document.createElement("input");
    countInput.className = "dict-maintenance__count-input";
    countInput.type = "number";
    countInput.value = String(entry.count ?? 0);
    countInput.disabled = true;
    countCell.appendChild(countInput);

    const actionCell = document.createElement("td");
    const deleteButton = document.createElement("button");
    deleteButton.className = "dict-maintenance__delete";
    deleteButton.type = "button";
    deleteButton.textContent = "削除";
    deleteButton.addEventListener("click", () => {
        if (!confirm("この行を削除しますか?")) return;
        state.entries.splice(index, 1);
        state.selectedIndexes.delete(index);
        state.selectedIndexes = new Set([...state.selectedIndexes].map((i) => (i > index ? i - 1 : i)));
        renderTable();
    });
    actionCell.appendChild(deleteButton);

    tr.appendChild(selectCell);
    tr.appendChild(idxCell);
    tr.appendChild(originalCell);
    tr.appendChild(translatedCell);
    tr.appendChild(statusCell);
    tr.appendChild(compareCell);
    tr.appendChild(countCell);
    tr.appendChild(actionCell);

    return tr;
}

function renderTable() {
    const tbody = $("dictTableBody");
    if (!tbody) return;
    tbody.innerHTML = "";

    let displayIndex = 1;
    state.entries.forEach((entry, index) => {
        if (!matchesFilter(entry)) return;
        tbody.appendChild(renderRow(entry, index, displayIndex));
        displayIndex += 1;
    });

    const rowCount = $("dictRowCount");
    if (rowCount) {
        rowCount.textContent = `${displayIndex - 1} / ${state.entries.length} 行表示`;
    }

    updateSelectAllState();
}

function updateSelectAllState() {
    const selectAll = $("dictSelectAll");
    if (!selectAll) return;
    const visibleIndexes = state.entries
        .map((_, index) => index)
        .filter((index) => matchesFilter(state.entries[index]));
    if (!visibleIndexes.length) {
        selectAll.checked = false;
        selectAll.indeterminate = false;
        return;
    }
    const selectedCount = visibleIndexes.filter((index) => state.selectedIndexes.has(index)).length;
    selectAll.checked = selectedCount === visibleIndexes.length;
    selectAll.indeterminate = selectedCount > 0 && selectedCount < visibleIndexes.length;
}

function toggleSelectAll(checked) {
    const visibleIndexes = state.entries
        .map((_, index) => index)
        .filter((index) => matchesFilter(state.entries[index]));
    if (checked) {
        visibleIndexes.forEach((index) => state.selectedIndexes.add(index));
    } else {
        visibleIndexes.forEach((index) => state.selectedIndexes.delete(index));
    }
    renderTable();
}

async function fetchEntries() {
    setStatus("読み込み中...", false);
    try {
        const response = await fetch(`/api/dict/list?dict_path=${encodeURIComponent(state.dictPath)}`);
        const data = await response.json();
        if (!response.ok || data.status !== "ok") {
            throw new Error(data.message || `読み込みに失敗しました (${response.status})`);
        }
        state.entries = Array.isArray(data.entries) ? data.entries : [];
        state.dictPath = data.dict_path || state.dictPath;
        state.selectedIndexes.clear();
        setStatus("読み込み完了", false);
        renderTable();
    } catch (error) {
        console.error("dict list error:", error);
        setStatus(String(error), true);
    }
}

async function saveEntries() {
    setStatus("保存中...", false);
    const payload = {
        dict_path: state.dictPath,
        entries: state.entries.map((entry) => ({
            original_word: (entry.original_word || "").trim(),
            translated_word: (entry.translated_word || "").trim(),
            status: entry.status ?? 0,
            count: entry.count ?? 0,
        })),
    };

    try {
        const response = await fetch("/api/dict/bulk_update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok || data.status !== "ok") {
            throw new Error(data.message || `保存に失敗しました (${response.status})`);
        }
        setStatus(`保存しました (${data.count ?? payload.entries.length} 件)`, false);
        await fetchEntries();
    } catch (error) {
        console.error("dict save error:", error);
        setStatus(String(error), true);
    }
}

function addRow() {
    state.entries.push({
        original_word: "",
        translated_word: "",
        status: 0,
        count: 0,
    });
    renderTable();

    const tbody = $("dictTableBody");
    const lastRow = tbody?.lastElementChild;
    const input = lastRow?.querySelector("input");
    if (input) {
        input.focus();
    }
}

function attachEvents() {
    const filterInput = $("dictFilterInput");
    const statusFilter = $("dictStatusFilter");
    const reloadButton = $("dictReloadButton");
    const addRowButton = $("dictAddRowButton");
    const saveButton = $("dictSaveButton");
    const selectAll = $("dictSelectAll");
    const dictFileSelect = $("dictFileSelect");
    const dictOpenButton = $("dictOpenButton");
    const dictCreateBookButton = $("dictCreateBookButton");
    const moveButton = $("dictMoveButton");
    const copyButton = $("dictCopyButton");
    const deleteSelectedButton = $("dictDeleteSelectedButton");
    const compareSelect = $("dictCompareSelect");

    if (filterInput) {
        filterInput.addEventListener("input", () => {
            state.filter = normalizeFilter(filterInput.value);
            renderTable();
        });
    }
    if (statusFilter) {
        statusFilter.addEventListener("change", () => {
            state.statusFilter = statusFilter.value || "all";
            renderTable();
        });
    }
    reloadButton?.addEventListener("click", fetchEntries);
    addRowButton?.addEventListener("click", addRow);
    saveButton?.addEventListener("click", saveEntries);
    selectAll?.addEventListener("change", () => toggleSelectAll(selectAll.checked));
    dictOpenButton?.addEventListener("click", () => {
        const target = dictFileSelect?.value;
        if (target) {
            state.dictPath = target;
            fetchEntries();
        }
    });
    dictCreateBookButton?.addEventListener("click", createBookDict);
    compareSelect?.addEventListener("change", () => {
        state.comparePath = compareSelect.value || "";
        fetchCompareMap();
    });
    moveButton?.addEventListener("click", () => transferSelected("move"));
    copyButton?.addEventListener("click", () => transferSelected("copy"));
    deleteSelectedButton?.addEventListener("click", () => transferSelected("delete"));
}

document.addEventListener("DOMContentLoaded", () => {
    const params = new URLSearchParams(window.location.search);
    state.dictPath = params.get("dict_path") || "";
    state.pdfName = params.get("pdf_name") || "";
    attachEvents();
    initStatusFilter();
    loadDictCatalog();
});

function initStatusFilter() {
    const statusFilter = $("dictStatusFilter");
    if (!statusFilter) return;
    statusFilter.innerHTML = "";
    const allOption = document.createElement("option");
    allOption.value = "all";
    allOption.textContent = "すべて";
    statusFilter.appendChild(allOption);
    statusOptions.forEach((option) => {
        const opt = document.createElement("option");
        opt.value = String(option.value);
        opt.textContent = option.text;
        statusFilter.appendChild(opt);
    });
    statusFilter.value = state.statusFilter;
}

async function createBookDict() {
    if (!state.pdfName) {
        alert("固有辞書の対象ブックが指定されていません。");
        return;
    }
    if (!confirm("固有辞書を作成しますか?")) return;
    setStatus("固有辞書を作成中...", false);
    try {
        const response = await fetch(`/api/dict/create_book/${encodeURIComponent(state.pdfName)}`, {
            method: "POST",
        });
        const data = await response.json();
        if (!response.ok || data.status !== "ok") {
            throw new Error(data.message || `作成に失敗しました (${response.status})`);
        }
        setStatus(`固有辞書を作成しました: ${data.dict_path || ""}`, false);
        state.dictPath = data.dict_path || state.dictPath;
        await loadDictCatalog();
        if (state.dictPath) {
            fetchEntries();
        }
    } catch (error) {
        console.error("dict create book error:", error);
        setStatus(String(error), true);
    }
}

async function loadDictCatalog() {
    try {
        const response = await fetch("/api/dict/catalog");
        const data = await response.json();
        if (!response.ok || data.status !== "ok") {
            throw new Error(data.message || `辞書一覧の取得に失敗しました (${response.status})`);
        }
        state.dictCatalog = Array.isArray(data.dicts) ? data.dicts : [];
        renderDictSelects();
        if (!state.dictPath) {
            state.dictPath = data.default_path || state.dictPath;
        }
        if (!state.comparePath && state.dictCatalog.length > 0) {
            const fallback = state.dictCatalog.find((item) => item.path !== state.dictPath);
            state.comparePath = fallback?.path || state.dictCatalog[0]?.path || "";
        }
        if (state.dictPath) {
            fetchEntries();
        }
        if (state.comparePath) {
            fetchCompareMap();
        }
    } catch (error) {
        console.error("dict catalog error:", error);
        setStatus(String(error), true);
    }
}

function renderDictSelects() {
    const dictFileSelect = $("dictFileSelect");
    const targetSelect = $("dictTargetSelect");
    const compareSelect = $("dictCompareSelect");
    if (!dictFileSelect || !targetSelect || !compareSelect) return;

    dictFileSelect.innerHTML = "";
    targetSelect.innerHTML = "";
    compareSelect.innerHTML = "";

    state.dictCatalog.forEach((item) => {
        if (!item?.path) return;
        const option = document.createElement("option");
        option.value = item.path;
        option.textContent = item.label || item.path;
        dictFileSelect.appendChild(option);

        const targetOption = document.createElement("option");
        targetOption.value = item.path;
        targetOption.textContent = item.label || item.path;
        targetSelect.appendChild(targetOption);

        const compareOption = document.createElement("option");
        compareOption.value = item.path;
        compareOption.textContent = item.label || item.path;
        compareSelect.appendChild(compareOption);
    });

    if (state.dictPath) {
        dictFileSelect.value = state.dictPath;
    }
    if (state.comparePath) {
        compareSelect.value = state.comparePath;
    }
}

async function fetchCompareMap() {
    if (!state.comparePath) {
        state.compareMap = {};
        renderTable();
        return;
    }
    try {
        const response = await fetch(`/api/dict/compare?dict_path=${encodeURIComponent(state.comparePath)}`);
        const data = await response.json();
        if (!response.ok || data.status !== "ok") {
            throw new Error(data.message || `比較辞書の取得に失敗しました (${response.status})`);
        }
        const rawEntries = data.entries || {};
        const statusLookup = new Map(statusOptions.map((item) => [item.value, item.text]));
        state.compareMap = Object.fromEntries(
            Object.entries(rawEntries).map(([key, value]) => {
                const statusText = statusLookup.get(value.status) || String(value.status ?? "");
                return [key, { ...value, status_text: statusText }];
            })
        );
        renderTable();
    } catch (error) {
        console.error("dict compare error:", error);
        setStatus(String(error), true);
    }
}

function getSelectedEntries() {
    const indexes = [...state.selectedIndexes].sort((a, b) => a - b);
    return indexes.map((index) => ({ entry: state.entries[index], index }));
}

async function transferSelected(action) {
    const selected = getSelectedEntries();
    if (!selected.length) {
        alert("対象の行を選択してください。");
        return;
    }

    const targetSelect = $("dictTargetSelect");
    const targetPath = targetSelect?.value || "";
    if ((action === "move" || action === "copy") && !targetPath) {
        alert("移動/複写先を選択してください。");
        return;
    }
    if (action === "move" && targetPath === state.dictPath) {
        alert("移動先が同じ辞書です。");
        return;
    }

    const confirmMap = {
        move: "選択した行を移動しますか?",
        copy: "選択した行を複写しますか?",
        delete: "選択した行を削除しますか?",
    };
    if (!confirm(confirmMap[action] || "実行しますか?")) return;

    const payload = {
        source_path: state.dictPath,
        target_path: targetPath,
        action,
        entries: selected.map((item) => ({
            original_word: (item.entry?.original_word || "").trim(),
            translated_word: (item.entry?.translated_word || "").trim(),
            status: item.entry?.status ?? 0,
            count: item.entry?.count ?? 0,
        })),
    };

    try {
        const response = await fetch("/api/dict/transfer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok || data.status !== "ok") {
            throw new Error(data.message || `操作に失敗しました (${response.status})`);
        }
        setStatus(data.message || "完了しました", false);
        await fetchEntries();
    } catch (error) {
        console.error("dict transfer error:", error);
        setStatus(String(error), true);
    }
}
