// symbol_fonts_maintenance.js - Symbol Fonts Maintenance Page Handler

let currentPdf = null;
let selectedFont = null;
let currentFonts = {};
let currentMappings = {};
let editingRows = new Set();

function encodePdfNamePath(value) {
  if (typeof value !== 'string') {
    return '';
  }
  return encodeURIComponent(value).replace(/%2F/gi, '/');
}

function normalizeBookName(value) {
  if (typeof value !== 'string') return '';
  return value.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '').trim();
}

function parseBookNameFromReferrer() {
  try {
    const ref = document.referrer || '';
    if (!ref) return '';
    const url = new URL(ref, window.location.origin);
    const marker = '/detail/';
    const idx = url.pathname.indexOf(marker);
    if (idx < 0) return '';
    const encoded = url.pathname.slice(idx + marker.length);
    if (!encoded) return '';
    return normalizeBookName(decodeURIComponent(encoded));
  } catch (_e) {
    return '';
  }
}

function resolveTargetBookName() {
  const urlParams = new URLSearchParams(window.location.search);
  const pdf_name_param = urlParams.get('pdf_name');
  const book_param = urlParams.get('book');
  const pdf_param = urlParams.get('pdf');
  const localStorage_val = (() => {
    try {
      return localStorage.getItem('ppt.symbol_fonts.pdf_name') || '';
    } catch (_e) {
      return '';
    }
  })();
  const referrer_val = parseBookNameFromReferrer();
  
  console.log('[symbol_fonts_maintenance.js] resolveTargetBookName candidates:', {
    pdf_name_param,
    book_param,
    pdf_param,
    localStorage_val,
    referrer_val,
  });
  
  // Priority: URL params (detail.html should pass these) > referrer (always accurate from current page) > localStorage (stale)
  const candidates = [
    pdf_name_param,
    book_param,
    pdf_param,
    referrer_val,  // Moved before localStorage to use current page context
    localStorage_val,
  ];
  for (let i = 0; i < candidates.length; i++) {
    const candidate = candidates[i];
    const normalized = normalizeBookName(candidate || '');
    if (normalized) {
      console.log(`[symbol_fonts_maintenance.js] Using candidate #${i}:`, candidate, '-> normalized:', normalized);
      return normalized;
    }
  }
  console.log('[symbol_fonts_maintenance.js] No valid candidate found, returning empty string');
  return '';
}

function removeLegacySelectorUi() {
  const legacySelect = document.getElementById('pdfSelect');
  const legacyLoadButton = document.getElementById('loadFontsButton');
  const legacyLabel = document.querySelector('label[for="pdfSelect"]');
  if (legacySelect) legacySelect.remove();
  if (legacyLoadButton) legacyLoadButton.remove();
  if (legacyLabel) legacyLabel.remove();
}

// Initialize page
document.addEventListener('DOMContentLoaded', async () => {
  console.log('[symbol_fonts_maintenance.js] DOMContentLoaded started');
  console.log('[symbol_fonts_maintenance.js] window.location.href:', window.location.href);
  console.log('[symbol_fonts_maintenance.js] window.location.search:', window.location.search);
  console.log('[symbol_fonts_maintenance.js] document.referrer:', document.referrer);
  
  removeLegacySelectorUi();

  const selectedBookParam = resolveTargetBookName();
  
  console.log('[symbol_fonts_maintenance.js] Resolved symbol fonts target:', {
    search: window.location.search,
    referrer: document.referrer || '',
    selectedBookParam: selectedBookParam,
  });

  const targetBookNameEl = document.getElementById('targetBookName');
  const bookSourceInfoEl = document.getElementById('bookSourceInfo');
  const statusEl = document.getElementById('loadStatus');

  if (!selectedBookParam) {
    currentPdf = null;
    if (targetBookNameEl) targetBookNameEl.textContent = '(未指定)';
    if (bookSourceInfoEl) bookSourceInfoEl.textContent = '抽出元: -';
    if (statusEl) {
      statusEl.textContent = 'エラー: book(pdf) パラメータがありません';
      statusEl.style.color = '#e74c3c';
    }
  } else {
    currentPdf = selectedBookParam;
    try {
      localStorage.setItem('ppt.symbol_fonts.pdf_name', selectedBookParam);
    } catch (_e) {
      // ignore storage errors
    }
    if (targetBookNameEl) targetBookNameEl.textContent = selectedBookParam;
    if (bookSourceInfoEl) bookSourceInfoEl.textContent = '抽出元: 対象ブックの book_data.styles';
    console.log('Using fixed book from query parameter:', selectedBookParam);
    await loadFonts();
  }

  // Event listeners
  document.getElementById('addMappingButton').addEventListener('click', addMappingRow);
  document.getElementById('fillCharacterCodesButton').addEventListener('click', fillMissingCharacterCodes);
  document.getElementById('saveMappingsButton').addEventListener('click', saveMappings);
});

// CSS variable helper functions
function getThemeColor(propertyName, defaultValue = '#000000') {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(propertyName).trim();
    return value || defaultValue;
  } catch (e) {
    return defaultValue;
  }
}

// Load fonts from fixed target book
async function loadFonts() {
  if (!currentPdf) {
    alert('対象ブックが指定されていません');
    return;
  }

  const statusEl = document.getElementById('loadStatus');
  statusEl.textContent = '読み込み中...';
  statusEl.style.color = getThemeColor('--text-muted', '#666');

  try {
    const response = await fetch(`/api/book_fonts/${encodePdfNamePath(currentPdf)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    if (data.status === 'ok') {
      currentFonts = data.fonts || {};
      
      // Load current mappings FIRST before displaying fonts list
      await loadCurrentMappings();
      
      // NOW display fonts list with complete mapping data
      displayFontsList();
      
      statusEl.textContent = `${currentPdf} / ${Object.keys(currentFonts).length}個のフォントが見つかりました`;
      statusEl.style.color = getThemeColor('--text-muted', '#666');
    } else {
      throw new Error(data.message || 'Unknown error');
    }
  } catch (error) {
    console.error('Error loading fonts:', error);
    statusEl.textContent = `エラー: ${error.message}`;
    statusEl.style.color = '#e74c3c';
  }
}

// Display fonts list
function displayFontsList() {
  const fontsList = document.getElementById('fontsList');
  fontsList.innerHTML = '';

  const surfaceColor = getThemeColor('--surface', '#fff');
  const textColor = getThemeColor('--text-primary', '#333');
  const accentColor = getThemeColor('--accent', '#27ae60');

  console.log('[displayFontsList] Starting display with currentMappings:', Object.keys(currentMappings).length, 'entries');

  Object.keys(currentFonts).sort().forEach(fontName => {
    const item = document.createElement('div');
    item.className = 'font-item';
    item.dataset.fontName = fontName;
    
    // Check if this font has any mappings
    const fontMappings = {};
    Object.entries(currentMappings).forEach(([key, value]) => {
      if (key.startsWith(fontName + '.')) {
        fontMappings[key] = value;
      }
    });
    
    // Create display text with status indicator
    const hasMapping = Object.keys(fontMappings).length > 0;
    const statusIcon = hasMapping ? '✓' : '○';
    const displayText = `${statusIcon} ${fontName}`;
    
    console.log(`[displayFontsList] Font: ${fontName}, mappings: ${Object.keys(fontMappings).length}, hasMapping: ${hasMapping}`);
    
    item.textContent = displayText;
    item.style.backgroundColor = surfaceColor;
    item.style.color = textColor;
    
    // Add visual accent for registered fonts
    if (hasMapping) {
      item.style.fontWeight = 'bold';
      item.style.borderLeft = `3px solid ${accentColor}`;
      item.style.paddingLeft = '8px';
    }
    
    // Add tooltip showing number of entries
    if (hasMapping) {
      item.title = `${Object.keys(fontMappings).length}個のマッピング登録済み`;
    } else {
      item.title = '未登録（新規作成可能）';
    }
    
    item.addEventListener('click', () => selectFont(fontName));
    fontsList.appendChild(item);
  });
}

function getKeyboardCharacterCodes() {
  const chars = [];
  for (let code = 33; code <= 126; code++) {
    chars.push(String.fromCharCode(code));
  }
  return chars;
}

function getCharacterCodesInTable() {
  const tableBody = document.getElementById('mappingsTableBody');
  const rows = tableBody.querySelectorAll('tr');
  const existing = new Set();
  rows.forEach((row) => {
    const cells = row.querySelectorAll('td');
    if (cells.length >= 3) {
      const keyInput = cells[1].querySelector('input');
      if (!keyInput) return;
      const key = keyInput.value.trim();
      if (!selectedFont || !key.startsWith(selectedFont + '.')) return;
      const charCode = key.substring((selectedFont + '.').length);
      if (charCode.length === 1) {
        existing.add(charCode);
      }
    }
  });
  return existing;
}

function appendMappingRow(fontName, charCode, replacementValue = '') {
  const tableBody = document.getElementById('mappingsTableBody');
  const row = tableBody.insertRow();

  const surfaceColor = getThemeColor('--surface', '#fff');
  const textColor = getThemeColor('--text-primary', '#333');
  row.style.backgroundColor = surfaceColor;
  row.style.color = textColor;

  const checkCell = row.insertCell();
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'mapping-checkbox';
  checkCell.appendChild(checkbox);

  const keyCell = row.insertCell();
  const keyInput = document.createElement('input');
  keyInput.type = 'text';
  keyInput.className = 'mapping-input';
  keyInput.value = `${fontName}.${charCode}`;
  keyInput.readOnly = true;
  keyInput.style.backgroundColor = 'rgba(0, 0, 0, 0.05)';
  keyInput.style.fontFamily = 'monospace';
  keyCell.appendChild(keyInput);

  const replCell = row.insertCell();
  const replInput = document.createElement('input');
  replInput.type = 'text';
  replInput.className = 'mapping-input';
  replInput.value = replacementValue;
  replInput.style.fontFamily = 'monospace';
  replInput.addEventListener('change', () => {
    editingRows.add(row);
  });
  replCell.appendChild(replInput);

  const btnCell = row.insertCell();
  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'btn-delete';
  deleteBtn.textContent = '削除';
  deleteBtn.addEventListener('click', (e) => {
    e.preventDefault();
    row.remove();
  });
  btnCell.appendChild(deleteBtn);

  editingRows.add(row);
}

function fillMissingCharacterCodes() {
  if (!selectedFont) {
    alert('フォントを選択してください');
    return;
  }

  const allCodes = getKeyboardCharacterCodes();
  const existingCodes = getCharacterCodesInTable();
  let addedCount = 0;

  allCodes.forEach((charCode) => {
    if (!existingCodes.has(charCode)) {
      appendMappingRow(selectedFont, charCode, charCode);
      addedCount += 1;
    }
  });

  document.getElementById('noMappingMessage').style.display = 'none';

  const statusEl = document.getElementById('loadStatus');
  if (statusEl) {
    statusEl.textContent = addedCount > 0
      ? `✓ 未登録キャラクターを ${addedCount} 件補完しました`
      : '✓ 補完対象はありません';
    statusEl.style.color = addedCount > 0 ? '#27ae60' : getThemeColor('--text-muted', '#666');
    setTimeout(() => {
      statusEl.textContent = '';
    }, 3000);
  }
}

// Select font
async function selectFont(fontName) {
  selectedFont = fontName;

  // Update UI
  const items = document.querySelectorAll('.font-item');
  items.forEach(item => {
    item.classList.remove('selected');
    if (item.dataset.fontName === fontName) {
      item.classList.add('selected');
    }
  });

  // Update title
  document.getElementById('selectedFontTitle').textContent = `フォント: ${fontName}`;

  // Check if mappings exist for this font
  const fontMappings = {};
  Object.entries(currentMappings).forEach(([key, value]) => {
    if (key.startsWith(fontName + '.')) {
      const charPart = key.substring((fontName + '.').length);
      fontMappings[charPart] = value;
    }
  });

  // If no mappings exist, offer to create new ones
  if (Object.keys(fontMappings).length === 0) {
    showCreateMappingsDialog(fontName);
  } else {
    // Show editor controls for existing mappings
    document.getElementById('addMappingButton').style.display = 'inline-block';
    document.getElementById('fillCharacterCodesButton').style.display = 'inline-block';
    document.getElementById('saveMappingsButton').style.display = 'inline-block';
    document.getElementById('noMappingMessage').style.display = 'none';
    document.getElementById('mappingsEditor').style.display = 'block';

    // Display mappings for this font
    displayMappingsForFont(fontName);
  }
}

// Show create mappings dialog
async function showCreateMappingsDialog(fontName) {
  const confirmed = await showConfirmDialog(
    `このフォントの置換辞書を作成しますか？`,
    `関数: ${fontName}\n\nはい → 初期マッピング行を生成します\nいいえ → キャンセルします`
  );

  if (confirmed) {
    // Show editor controls
    document.getElementById('addMappingButton').style.display = 'inline-block';
    document.getElementById('fillCharacterCodesButton').style.display = 'inline-block';
    document.getElementById('saveMappingsButton').style.display = 'inline-block';
    document.getElementById('noMappingMessage').style.display = 'none';
    document.getElementById('mappingsEditor').style.display = 'block';

    // Generate initial mapping rows
    createInitialMappingRows(fontName);
  }
}

// Show confirm dialog
function showConfirmDialog(title, message) {
  return new Promise((resolve) => {
    const dialog = document.createElement('div');
    dialog.style.cssText = `
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.5);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 10000;
    `;

    const content = document.createElement('div');
    content.style.cssText = `
      background: white;
      padding: 20px;
      border-radius: 8px;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
      min-width: 300px;
      font-family: system-ui, -apple-system, sans-serif;
    `;

    const titleEl = document.createElement('h2');
    titleEl.textContent = title;
    titleEl.style.cssText = 'margin: 0 0 12px 0; font-size: 16px; color: #333;';
    content.appendChild(titleEl);

    const msgEl = document.createElement('p');
    msgEl.textContent = message;
    msgEl.style.cssText = 'margin: 0 0 20px 0; color: #666; white-space: pre-wrap; font-size: 14px;';
    content.appendChild(msgEl);

    const btnContainer = document.createElement('div');
    btnContainer.style.cssText = 'display: flex; gap: 10px; justify-content: flex-end;';

    const noBtn = document.createElement('button');
    noBtn.textContent = 'いいえ';
    noBtn.style.cssText = `
      padding: 8px 16px;
      background: #e0e0e0;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
    `;
    noBtn.addEventListener('click', () => {
      dialog.remove();
      resolve(false);
    });
    btnContainer.appendChild(noBtn);

    const yesBtn = document.createElement('button');
    yesBtn.textContent = 'はい';
    yesBtn.style.cssText = `
      padding: 8px 16px;
      background: #27ae60;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
    `;
    yesBtn.addEventListener('click', () => {
      dialog.remove();
      resolve(true);
    });
    btnContainer.appendChild(yesBtn);

    content.appendChild(btnContainer);
    dialog.appendChild(content);
    document.body.appendChild(dialog);
  });
}

// Create initial mapping rows for new font
function createInitialMappingRows(fontName) {
  const tableBody = document.getElementById('mappingsTableBody');
  tableBody.innerHTML = '';
  editingRows.clear();
  selectedFont = fontName;
  fillMissingCharacterCodes();
}

// Load current mappings from server
async function loadCurrentMappings() {
  try {
    console.log('[loadCurrentMappings] Starting to fetch registered symbolfonts...');
    const response = await fetch('/api/get_registered_symbolfonts');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    
    const data = await response.json();
    console.log('[loadCurrentMappings] Response status:', data.status);
    console.log('[loadCurrentMappings] Raw symbols data:', data.symbols);

    if (data.status === 'ok') {
      currentMappings = data.symbols || {};
      
      // Extract unique font names
      const fontNames = new Set();
      Object.keys(currentMappings).forEach(key => {
        const fontName = key.split('.')[0];
        fontNames.add(fontName);
      });
      
      console.log('[loadCurrentMappings] Loaded mappings:', Object.keys(currentMappings).length, 'entries');
      console.log('[loadCurrentMappings] Font names found:', Array.from(fontNames).sort());
    }
  } catch (error) {
    console.error('[loadCurrentMappings] Error loading mappings:', error);
  }
}

// Display mappings for selected font
function displayMappingsForFont(fontName) {
  const tableBody = document.getElementById('mappingsTableBody');
  tableBody.innerHTML = '';
  editingRows.clear();

  const surfaceColor = getThemeColor('--surface', '#fff');
  const textColor = getThemeColor('--text-primary', '#333');

  // Get all mappings for this font
  const fontMappings = {};
  Object.entries(currentMappings).forEach(([key, value]) => {
    if (key.startsWith(fontName + '.')) {
      const charPart = key.substring((fontName + '.').length);
      fontMappings[charPart] = value;
    }
  });

  // Display each mapping
  Object.entries(fontMappings).sort().forEach(([charCode, replacement]) => {
    const row = tableBody.insertRow();
    row.style.backgroundColor = surfaceColor;
    row.style.color = textColor;

    // Checkbox
    const checkCell = row.insertCell();
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'mapping-checkbox';
    checkCell.appendChild(checkbox);

    // Font.Character
    const keyCell = row.insertCell();
    const keyInput = document.createElement('input');
    keyInput.type = 'text';
    keyInput.className = 'mapping-input';
    keyInput.value = `${fontName}.${charCode}`;
    keyInput.readOnly = true;
    keyInput.style.backgroundColor = 'rgba(0, 0, 0, 0.05)';
    keyCell.appendChild(keyInput);

    // Replacement
    const replCell = row.insertCell();
    const replInput = document.createElement('input');
    replInput.type = 'text';
    replInput.className = 'mapping-input';
    replInput.value = replacement;
    replInput.style.fontFamily = 'monospace';
    replInput.addEventListener('change', () => {
      editingRows.add(row);
    });
    replCell.appendChild(replInput);

    // Delete button
    const btnCell = row.insertCell();
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'btn-delete';
    deleteBtn.textContent = '削除';
    deleteBtn.addEventListener('click', (e) => {
      e.preventDefault();
      row.remove();
      editingRows.add(row);
    });
    btnCell.appendChild(deleteBtn);
  });

  // Show message if no mappings
  if (Object.keys(fontMappings).length === 0) {
    document.getElementById('noMappingMessage').textContent = 'このフォントのマッピングがありません。「マッピング追加」で新規作成してください';
    document.getElementById('noMappingMessage').style.display = 'flex';
  }
}

// Add mapping row
function addMappingRow() {
  if (!selectedFont) {
    alert('フォントを選択してください');
    return;
  }

  const tableBody = document.getElementById('mappingsTableBody');
  const row = tableBody.insertRow();

  const surfaceColor = getThemeColor('--surface', '#fff');
  const textColor = getThemeColor('--text-primary', '#333');
  row.style.backgroundColor = surfaceColor;
  row.style.color = textColor;

  // Checkbox
  const checkCell = row.insertCell();
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'mapping-checkbox';
  checkCell.appendChild(checkbox);

  // Font.Character input
  const keyCell = row.insertCell();
  const keyInput = document.createElement('input');
  keyInput.type = 'text';
  keyInput.className = 'mapping-input';
  keyInput.placeholder = `${selectedFont}.[キャラクターコード]`;
  keyInput.style.fontFamily = 'monospace';
  keyInput.addEventListener('change', () => {
    editingRows.add(row);
  });
  keyCell.appendChild(keyInput);

  // Replacement input
  const replCell = row.insertCell();
  const replInput = document.createElement('input');
  replInput.type = 'text';
  replInput.className = 'mapping-input';
  replInput.placeholder = '置換後文字列';
  replInput.style.fontFamily = 'monospace';
  replInput.addEventListener('change', () => {
    editingRows.add(row);
  });
  replCell.appendChild(replInput);

  // Delete button
  const btnCell = row.insertCell();
  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'btn-delete';
  deleteBtn.textContent = '削除';
  deleteBtn.addEventListener('click', (e) => {
    e.preventDefault();
    row.remove();
  });
  btnCell.appendChild(deleteBtn);

  editingRows.add(row);
  document.getElementById('noMappingMessage').style.display = 'none';
}

// Save mappings
async function saveMappings() {
  if (!selectedFont) {
    alert('フォントを選択してください');
    return;
  }

  const tableBody = document.getElementById('mappingsTableBody');
  const rows = tableBody.querySelectorAll('tr');
  const updatedMappings = {};
  let hasErrors = false;

  // Collect mappings from table
  rows.forEach((row) => {
    const cells = row.querySelectorAll('td');
    if (cells.length >= 2) {
      const keyInput = cells[1].querySelector('input');
      const replInput = cells[2].querySelector('input');
      
      if (keyInput && replInput) {
        // Clean up whitespace and remove problematic characters
        const key = keyInput.value.trim().replace(/\n/g, '').replace(/\r/g, '').replace(/\t/g, '');
        const replacement = replInput.value.trim().replace(/\n/g, '').replace(/\r/g, '');

        if (key && replacement) {
          if (!key.startsWith(selectedFont + '.')) {
            alert(`キーは"${selectedFont}."で始まる必要があります: ${key}`);
            hasErrors = true;
            return;
          }
          updatedMappings[key] = replacement;
        }
      }
    }
  });

  if (hasErrors) return;

  // Save to server
  try {
    const response = await fetch('/api/update_symbolfont_mappings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        font_name: selectedFont,
        mappings: updatedMappings
      })
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    if (data.status === 'ok') {
      // Reload mappings
      await loadCurrentMappings();
      displayMappingsForFont(selectedFont);
      
      // Refresh fonts list to update registration status
      displayFontsList();
      
      editingRows.clear();
      
      // Show success message
      const statusEl = document.getElementById('loadStatus');
      statusEl.textContent = '✓ 保存しました';
      statusEl.style.color = '#27ae60';
      setTimeout(() => {
        statusEl.textContent = '';
      }, 3000);
    } else {
      throw new Error(data.message || 'Unknown error');
    }
  } catch (error) {
    console.error('Error saving mappings:', error);
    alert(`保存エラー: ${error.message}`);
  }
}
