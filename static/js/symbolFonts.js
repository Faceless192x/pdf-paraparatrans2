// symbolFonts.js - Symbol Font Registration Dialog Handler

let currentBookData = null;
let currentStyles = {};
let selectedFontStyle = null;

// Helper function to get CSS variable values - supports both light and dark modes
function getThemeColor(propertyName, defaultValue = '#000000') {
    try {
        const value = getComputedStyle(document.documentElement).getPropertyValue(propertyName).trim();
        return value || defaultValue;
    } catch (e) {
        return defaultValue;
    }
}

// Helper function to detect dark mode
function isDarkMode() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function openSymbolFontsDialog() {
    const dialog = document.getElementById('symbolFontsDialog');
    if (dialog) {
        dialog.style.display = 'flex';
        // Reset the dialog when opening
        document.getElementById('styleLoadStatus').textContent = '';
        document.getElementById('stylesList').innerHTML = '';
        document.getElementById('selectedFontStyle').value = '';
        document.getElementById('symbolFontReplacement').value = '';
        document.getElementById('symbolFontStatus').textContent = '';
        document.getElementById('registeredSymbolsList').innerHTML = '';
        loadRegisteredSymbols();
    }
}

function closeSymbolFontsDialog() {
    const dialog = document.getElementById('symbolFontsDialog');
    if (dialog) {
        dialog.style.display = 'none';
    }
}

function loadBookStyles() {
    const pdfName = document.body.getAttribute('data-pdf-name');
    const statusEl = document.getElementById('styleLoadStatus');
    const stylesList = document.getElementById('stylesList');
    
    statusEl.textContent = '読み込み中...';
    stylesList.innerHTML = '';
    
    fetch(`/api/book_styles/${encodeURIComponent(pdfName)}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'ok' && data.styles) {
                currentStyles = data.styles;
                displayStyles(data.styles);
                statusEl.textContent = `${Object.keys(data.styles).length} 個のスタイルが見つかりました`;
            } else {
                statusEl.textContent = 'スタイルが見つかりません';
            }
        })
        .catch(error => {
            console.error('Error loading styles:', error);
            statusEl.textContent = `エラー: ${error.message}`;
        });
}

function displayStyles(styles) {
    const stylesList = document.getElementById('stylesList');
    stylesList.innerHTML = '';
    
    if (!styles || Object.keys(styles).length === 0) {
        const emptyMsg = document.createElement('p');
        emptyMsg.textContent = 'スタイルが見つかりません';
        emptyMsg.style.cssText = `padding: 10px; color: ${getThemeColor('--text-muted', '#9aa3af')}; background-color: ${getThemeColor('--surface', '#ffffff')};`;
        stylesList.appendChild(emptyMsg);
        return;
    }
    
    const styleEntries = Object.entries(styles).sort();
    
    const table = document.createElement('table');
    const surfaceStrongColor = getThemeColor('--surface-strong', '#f6f8fa');
    const borderColor = getThemeColor('--table-border-strong', 'rgba(31, 41, 51, 0.3)');
    const accentColor = getThemeColor('--accent', '#0f766e');
    const accentDarkColor = getThemeColor('--accent-strong', '#0b4f4a');
    const surfaceAccentColor = getThemeColor('--surface-accent', '#eef6f2');
    const textMutedColor = getThemeColor('--text-muted', '#6b7280');
    const textPrimaryColor = getThemeColor('--text-primary', '#1f2933');
    
    table.style.cssText = 'width: 100%; border-collapse: collapse; font-size: 12px;';
    
    // Header row
    const headerRow = table.insertRow();
    headerRow.style.backgroundColor = surfaceStrongColor;
    headerRow.style.color = textPrimaryColor;
    const headerCells = ['フォント名', 'スタイル定義', '操作'];
    headerCells.forEach(cellText => {
        const cell = headerRow.insertCell();
        cell.textContent = cellText;
        cell.style.cssText = `padding: 8px; border-bottom: 1px solid ${borderColor}; font-weight: bold; color: ${textPrimaryColor};`;
    });
    
    // Data rows
    styleEntries.forEach(([styleKey, styleValue]) => {
        const row = table.insertRow();
        row.style.cursor = 'pointer';
        row.style.borderBottom = `1px solid ${getThemeColor('--table-border', 'rgba(31, 41, 51, 0.15)')}`;
        row.style.color = textPrimaryColor;
        row.onmouseover = () => { row.style.backgroundColor = surfaceAccentColor; };
        row.onmouseout = () => { row.style.backgroundColor = ''; };
        
        // Font name cell
        const fontCell = row.insertCell();
        fontCell.textContent = styleKey;
        fontCell.style.padding = '8px';
        fontCell.style.color = textPrimaryColor;
        
        // Style definition cell
        const styleCell = row.insertCell();
        styleCell.textContent = styleValue;
        styleCell.style.cssText = `padding: 8px; font-size: 11px; color: ${textMutedColor}; word-break: break-word;`;
        
        // Action cell
        const actionCell = row.insertCell();
        const selectBtn = document.createElement('button');
        selectBtn.textContent = '選択';
        selectBtn.type = 'button';
        selectBtn.style.cssText = `padding: 5px 10px; background-color: ${accentColor}; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 11px;`;
        selectBtn.onclick = (e) => {
            e.stopPropagation();
            selectFontStyle(styleKey, styleValue);
        };
        selectBtn.onmouseover = () => { selectBtn.style.backgroundColor = accentDarkColor; };
        selectBtn.onmouseout = () => { selectBtn.style.backgroundColor = accentColor; };
        actionCell.appendChild(selectBtn);
        actionCell.style.padding = '8px';
    });
    
    stylesList.appendChild(table);
}

function selectFontStyle(styleKey, styleValue) {
    selectedFontStyle = styleKey;
    document.getElementById('selectedFontStyle').value = styleKey;
    document.getElementById('symbolFontStatus').textContent = '';
    // Scroll to and highlight the selected row
    const stylesList = document.getElementById('stylesList');
    const rows = stylesList.querySelectorAll('table tbody tr');
    const accentSoftColor = getThemeColor('--accent-soft', 'rgba(15, 118, 110, 0.12)');
    rows.forEach(row => {
        row.style.backgroundColor = row.querySelector('button') && row.querySelector('button').textContent === '選択' && row.cells[0].textContent === styleKey ? accentSoftColor : '';
    });
}

function registerSymbolFont() {
    if (!selectedFontStyle) {
        alert('フォント名を選択してください');
        return;
    }
    
    const replacement = document.getElementById('symbolFontReplacement').value.trim();
    if (!replacement) {
        alert('置換後の文字列を入力してください');
        return;
    }
    
    const statusEl = document.getElementById('symbolFontStatus');
    statusEl.textContent = '送信中...';
    
    const pdfName = document.body.getAttribute('data-pdf-name');
    
    fetch('/api/register_symbolfont', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            font_style: selectedFontStyle,
            replacement: replacement
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        const successColor = '#27ae60';
        if (data.status === 'ok') {
            statusEl.textContent = '✓ 登録しました';
            statusEl.style.color = successColor;
            document.getElementById('symbolFontReplacement').value = '';
            document.getElementById('selectedFontStyle').value = '';
            selectedFontStyle = null;
            // Reload the registered symbols list
            setTimeout(() => {
                loadRegisteredSymbols();
                statusEl.textContent = '';
            }, 1500);
        } else {
            throw new Error(data.message || 'Unknown error');
        }
    })
    .catch(error => {
        const errorColor = '#e74c3c';
        console.error('Error registering symbol font:', error);
        statusEl.textContent = `エラー: ${error.message}`;
        statusEl.style.color = errorColor;
    });
}

function loadRegisteredSymbols() {
    const registeredList = document.getElementById('registeredSymbolsList');
    registeredList.innerHTML = '';
    
    fetch('/api/get_registered_symbolfonts')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'ok' && data.symbols) {
                displayRegisteredSymbols(data.symbols);
            }
        })
        .catch(error => {
            console.error('Error loading registered symbols:', error);
        });
}

function displayRegisteredSymbols(symbols) {
    const registeredList = document.getElementById('registeredSymbolsList');
    
    if (!symbols || Object.keys(symbols).length === 0) {
        const emptyMsg = document.createElement('p');
        emptyMsg.textContent = '登録されたシンボルはありません';
        emptyMsg.style.cssText = `padding: 10px; color: ${getThemeColor('--text-muted', '#9aa3af')}; background-color: ${getThemeColor('--surface-accent', '#eef6f2')};`;
        registeredList.appendChild(emptyMsg);
        return;
    }
    
    const table = document.createElement('table');
    const surfaceStrongColor = getThemeColor('--surface-strong', '#f6f8fa');
    const borderColor = getThemeColor('--table-border-strong', 'rgba(31, 41, 51, 0.3)');
    const textPrimaryColor = getThemeColor('--text-primary', '#1f2933');
    const accentSoftColor = getThemeColor('--accent-soft', 'rgba(15, 118, 110, 0.12)');
    const deleteRedColor = '#e74c3c';
    const deleteRedDarkColor = '#c0392b';
    
    table.style.cssText = 'width: 100%; border-collapse: collapse; font-size: 12px;';
    
    // Header row
    const headerRow = table.insertRow();
    headerRow.style.backgroundColor = surfaceStrongColor;
    headerRow.style.color = textPrimaryColor;
    const headerCells = ['フォント.キャラクター', '置換後文字列', '削除'];
    headerCells.forEach(cellText => {
        const cell = headerRow.insertCell();
        cell.textContent = cellText;
        cell.style.cssText = `padding: 8px; border-bottom: 1px solid ${borderColor}; font-weight: bold; color: ${textPrimaryColor};`;
    });
    
    // Data rows
    Object.entries(symbols).sort().forEach(([key, replacement]) => {
        const row = table.insertRow();
        row.style.borderBottom = `1px solid ${getThemeColor('--table-border', 'rgba(31, 41, 51, 0.15)')}`;
        row.style.color = textPrimaryColor;
        row.onmouseover = () => { row.style.backgroundColor = accentSoftColor; };
        row.onmouseout = () => { row.style.backgroundColor = ''; };
        
        // Key cell
        const keyCell = row.insertCell();
        keyCell.textContent = key;
        keyCell.style.cssText = `padding: 8px; font-family: monospace; color: ${textPrimaryColor};`;
        
        // Replacement cell
        const replacementCell = row.insertCell();
        replacementCell.textContent = replacement;
        replacementCell.style.cssText = `padding: 8px; color: ${textPrimaryColor};`;
        
        // Delete cell
        const deleteCell = row.insertCell();
        const deleteBtn = document.createElement('button');
        deleteBtn.textContent = '削除';
        deleteBtn.type = 'button';
        deleteBtn.style.cssText = `padding: 5px 10px; background-color: ${deleteRedColor}; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 11px;`;
        deleteBtn.onclick = (e) => {
            e.stopPropagation();
            deleteSymbolFont(key);
        };
        deleteBtn.onmouseover = () => { deleteBtn.style.backgroundColor = deleteRedDarkColor; };
        deleteBtn.onmouseout = () => { deleteBtn.style.backgroundColor = deleteRedColor; };
        deleteCell.appendChild(deleteBtn);
        deleteCell.style.padding = '8px';
    });
    
    registeredList.appendChild(table);
}

function deleteSymbolFont(key) {
    if (!confirm(`${key} を削除してもよろしいですか?`)) {
        return;
    }
    
    fetch('/api/delete_symbolfont', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            key: key
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.status === 'ok') {
            loadRegisteredSymbols();
        } else {
            throw new Error(data.message || 'Unknown error');
        }
    })
    .catch(error => {
        console.error('Error deleting symbol font:', error);
        alert(`削除に失敗しました: ${error.message}`);
    });
}

// Initialize event listeners when the script loads
document.addEventListener('DOMContentLoaded', function() {
    const openSymbolFontsBtn = document.getElementById('openSymbolFontsButton');
    if (openSymbolFontsBtn) {
        openSymbolFontsBtn.addEventListener('click', openSymbolFontsDialog);
    }
});
