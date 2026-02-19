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
    // 編集辞書のOR条件フィルタ
    filterStatuses: new Set(), // チェックされた状態番号 (0,1,5,6,7,8,9)
    // 比較辞書フィルタ（□あり □なし）
    compareMatchExists: false,
    compareMatchNoEntry: false,
    // 比較辞書のOR条件フィルタ
    compareFilterStatuses: new Set(), // チェックされた状態番号 (0,1,5,6,7,8,9)
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

function updateStatusCounts() {
    // 編集辞書の状態件数を計算
    const counts = {0: 0, 1: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0};
    state.entries.forEach(entry => {
        const status = entry.status ?? 0;
        if (counts.hasOwnProperty(status)) {
            counts[status]++;
        }
    });
    
    // 編集辞書の件数を表示
    [0, 1, 5, 6, 7, 8, 9].forEach(status => {
        const cell = $(`dictStatusCount${status}`);
        if (cell) cell.textContent = counts[status];
    });
    
    // 比較辞書の状態件数を計算
    const compareCounts = {0: 0, 1: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0};
    Object.values(state.compareMap).forEach(entry => {
        const status = entry.status ?? 0;
        if (compareCounts.hasOwnProperty(status)) {
            compareCounts[status]++;
        }
    });
    
    // 比較辞書の件数を表示
    [0, 1, 5, 6, 7, 8, 9].forEach(status => {
        const cell = $(`dictCompareStatusCount${status}`);
        if (cell) cell.textContent = compareCounts[status];
    });
}

function matchesFilter(entry) {
    const entryStatus = entry.status ?? 0;
    
    // 編集辞書のOR条件フィルタ（□0-9）
    if (state.filterStatuses.size > 0) {
        if (!state.filterStatuses.has(entryStatus)) {
            return false;
        }
    }
    
    // 比較辞書フィルタ（□あり □なし）
    const compareValue = state.compareMap[entry.original_word];
    // 両方チェックまたは両方未チェック → フィルタなし
    // 「あり」のみチェック → 比較辞書にある項目のみ
    // 「なし」のみチェック → 比較辞書にない項目のみ
    if (state.compareMatchExists && !state.compareMatchNoEntry) {
        if (!compareValue) return false;
    } else if (!state.compareMatchExists && state.compareMatchNoEntry) {
        if (compareValue) return false;
    }
    
    // 比較辞書のOR条件フィルタ（□0-9）
    if (state.compareFilterStatuses && state.compareFilterStatuses.size > 0 && compareValue) {
        const compareStatus = compareValue.status ?? 0;
        if (!state.compareFilterStatuses.has(compareStatus)) {
            return false;
        }
    }
    
    return true;
}

function renderRow(entry, index, displayIndex) {
    const tr = document.createElement("tr");
    tr.dataset.index = String(index);

    // チェックボックス
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

    // 編集辞書: 単語
    const originalCell = document.createElement("td");
    const originalInput = document.createElement("input");
    originalInput.className = "dict-maintenance__input";
    originalInput.type = "text";
    originalInput.value = entry.original_word || "";
    originalInput.addEventListener("input", () => {
        entry.original_word = originalInput.value;
    });
    originalCell.appendChild(originalInput);

    // 編集辞書: 訳語
    const translatedCell = document.createElement("td");
    const translatedInput = document.createElement("input");
    translatedInput.className = "dict-maintenance__input";
    translatedInput.type = "text";
    translatedInput.value = entry.translated_word || "";
    translatedInput.addEventListener("input", () => {
        entry.translated_word = translatedInput.value;
    });
    translatedCell.appendChild(translatedInput);

    // 編集辞書: 状態
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

    // 編集辞書: 回数
    const countCell = document.createElement("td");
    const countInput = document.createElement("input");
    countInput.className = "dict-maintenance__count-input";
    countInput.type = "number";
    countInput.value = String(entry.count ?? 0);
    countInput.disabled = true;
    countCell.appendChild(countInput);

    // 比較辞書: 訳語
    const compareTranslatedCell = document.createElement("td");
    const compareValue = state.compareMap[entry.original_word];
    if (compareValue) {
        compareTranslatedCell.textContent = compareValue.translated_word || "-";
    } else {
        compareTranslatedCell.textContent = "-";
        compareTranslatedCell.style.color = "#999";
    }

    // 比較辞書: 状態
    const compareStatusCell = document.createElement("td");
    if (compareValue) {
        compareStatusCell.textContent = compareValue.status_text || String(compareValue.status ?? "");
    } else {
        compareStatusCell.textContent = "-";
        compareStatusCell.style.color = "#999";
    }

    // 比較辞書: 回数
    const compareCountCell = document.createElement("td");
    if (compareValue) {
        compareCountCell.textContent = String(compareValue.count ?? 0);
    } else {
        compareCountCell.textContent = "-";
        compareCountCell.style.color = "#999";
    }

    tr.appendChild(selectCell);
    tr.appendChild(originalCell);
    tr.appendChild(translatedCell);
    tr.appendChild(statusCell);
    tr.appendChild(countCell);
    tr.appendChild(compareTranslatedCell);
    tr.appendChild(compareStatusCell);
    tr.appendChild(compareCountCell);

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
    updateStatusCounts();
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
    const selectAll = $("dictSelectAll");
    const dictFileSelect = $("dictFileSelect");
    const dictOpenButton = $("dictOpenButton");
    const compareSelect = $("dictCompareSelect");
    const dictCompareButton = $("dictCompareButton");
    const addRowButton = $("dictAddRowButton");
    const saveButton = $("dictSaveButton");
    const deleteSelectedButton = $("dictDeleteSelectedButton");
    const dictCopyToCompareButton = $("dictCopyToCompareButton");
    const dictAutoTranslateButton = $("dictAutoTranslateButton");

    // 編集辞書のOR条件フィルタ (□0-9)
    [0, 1, 5, 6, 7, 8, 9].forEach(status => {
        const checkbox = $(`dictFilterStatus${status}`);
        if (checkbox) {
            checkbox.addEventListener("change", () => {
                if (checkbox.checked) {
                    state.filterStatuses.add(status);
                } else {
                    state.filterStatuses.delete(status);
                }
                renderTable();
            });
        }
    });

    // 比較辞書のOR条件フィルタ (□0-9)
    [0, 1, 5, 6, 7, 8, 9].forEach(status => {
        const checkbox = $(`dictCompareFilterStatus${status}`);
        if (checkbox) {
            checkbox.addEventListener("change", () => {
                if (checkbox.checked) {
                    state.compareFilterStatuses.add(status);
                } else {
                    state.compareFilterStatuses.delete(status);
                }
                renderTable();
            });
        }
    });

    // 比較辞書フィルタ（□あり □なし）
    const compareMatchExists = $("dictCompareMatchExists");
    const compareMatchNoEntry = $("dictCompareMatchNoEntry");
    if (compareMatchExists) {
        compareMatchExists.addEventListener("change", () => {
            state.compareMatchExists = compareMatchExists.checked;
            renderTable();
        });
    }
    if (compareMatchNoEntry) {
        compareMatchNoEntry.addEventListener("change", () => {
            state.compareMatchNoEntry = compareMatchNoEntry.checked;
            renderTable();
        });
    }

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
    dictCompareButton?.addEventListener("click", () => {
        const target = compareSelect?.value;
        if (target) {
            state.comparePath = target;
            fetchCompareMap();
        }
    });
    compareSelect?.addEventListener("change", () => {
        state.comparePath = compareSelect.value || "";
    });
    dictCopyToCompareButton?.addEventListener("click", () => transferSelected("copy"));
    deleteSelectedButton?.addEventListener("click", () => transferSelected("delete"));
    dictAutoTranslateButton?.addEventListener("click", () => autoTranslate());
}

document.addEventListener("DOMContentLoaded", () => {
    const params = new URLSearchParams(window.location.search);
    state.dictPath = params.get("dict_path") || "";
    state.comparePath = params.get("compare_path") || "";
    state.pdfName = params.get("pdf_name") || "";
    attachEvents();
    loadDictCatalog();
});

function autoTranslate() {
    alert("自動翻訳機能は未実装です。");
}

async function loadDictCatalog() {
    try {
        const response = await fetch("/api/dict/catalog");
        const data = await response.json();
        if (!response.ok || data.status !== "ok") {
            throw new Error(data.message || `辞書一覧の取得に失敗しました (${response.status})`);
        }
        state.dictCatalog = Array.isArray(data.dicts) ? data.dicts : [];
        if (!state.dictPath) {
            state.dictPath = data.default_path || state.dictPath;
        }
        if (!state.comparePath && state.dictCatalog.length > 0) {
            const fallback = state.dictCatalog.find((item) => item.path !== state.dictPath);
            state.comparePath = fallback?.path || state.dictCatalog[0]?.path || "";
        }
        renderDictSelects();
        const dictFileSelect = $("dictFileSelect");
        const compareSelect = $("dictCompareSelect");
        if (dictFileSelect?.value) {
            state.dictPath = dictFileSelect.value;
        }
        if (compareSelect?.value) {
            state.comparePath = compareSelect.value;
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
    const compareSelect = $("dictCompareSelect");
    if (!dictFileSelect || !compareSelect) return;

    dictFileSelect.innerHTML = "";
    compareSelect.innerHTML = "";

    state.dictCatalog.forEach((item) => {
        if (!item?.path) return;
        const option = document.createElement("option");
        option.value = item.path;
        option.textContent = item.label || item.path;
        dictFileSelect.appendChild(option);

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

    // 移動/複写先は比較辞書を使用
    const targetPath = state.comparePath;
    if ((action === "move" || action === "copy") && !targetPath) {
        alert("比較辞書を選択してください。");
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
