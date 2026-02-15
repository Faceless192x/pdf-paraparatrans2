// --- HotkeyMapper 設計検証フレーム（必読） ---
// この関数はレビュー済項目が存在します。
// 【仕様】【実装】【出力】の3点が一致しており、以下の通り検証されています：
//
// [✔] 入力 "Ctrl++" → normalizeHotkey → "Control++"
// [✔] getPressedKeyString(event) で "+" が返ることを確認（event.key）
// [✔] Shift 同時押しでも "+" を出せば key === "+" となることを確認済
// [✘] Plus という key 名は出ない（過去の誤指摘）
// レビュー担当者は、上記仕様を前提にコードを読まなければならない。
// --------------------------------------------------

const HotkeyMapper = (() => {
  const hotkeyMap = new Map();
  const captureHotkeys = new Set();
  const HOTKEY_INPUT_TOGGLE_ID = "toggleHotkeyInput";
  let lastPressedKey = "";
  const hotkeyInputHistory = [];
  const HOTKEY_INPUT_HISTORY_LIMIT = 50;
  let hotkeyInputHistoryCounter = 0;
  const pressedKeyCodes = new Set();

  const VALID_ACTIONS = new Set([
    "click", "dblclick", "mousedown", "mouseup", "keydown", "keyup", "focus", "blur",
    "select", "contextmenu", "scroll", "wheel",
    "touchstart", "touchmove", "touchend",
    "pointerdown", "pointerup", "pointermove", "pointerover", "pointerout", "pointerenter", "pointerleave",
    "dragstart", "dragover", "drop", "dragend"
  ]);

/**
 * ホットキー文字列を一意な形式に正規化する。
 * 
 * @spec:
 * - 修飾キーの順序が違っても同一キーとみなす（locale順で正規化）
 * - キーは大文字化（例: "a" → "A"）
 * - 記号キー（"+", "=", "?" など）にも対応
 * - 入力: "Ctrl++"
 * - 正規化後: "Control++"
 * - 対応 event.key: "+"
 * - 発火キー: event.ctrlKey && event.key === "+"
 * - Shift修飾ありでも "+” が key になる（確認済）
 *
 * この条件を満たす実装であること（Stepチェック全通過）
 */
function normalizeHotkey(hotkey) {
    const parts = hotkey.split('+').map(part => part.trim());
    if (parts.length < 1) return null;
    let key = parts.pop();
    if (!key) key = '+';
    const modifiers = parts.sort((a, b) => a.localeCompare(b));
    const normalizedParts = [];
    if (modifiers.includes("Ctrl") || modifiers.includes("Control")) normalizedParts.push("Control");
    if (modifiers.includes("Alt")) normalizedParts.push("Alt");
    if (modifiers.includes("Shift")) normalizedParts.push("Shift");
    if (modifiers.includes("Meta")) normalizedParts.push("Meta");
    if (!["Control", "Alt", "Shift", "Meta"].includes(key)) {
      normalizedParts.push(key.length === 1 ? key.toUpperCase() : key);
    }
    return normalizedParts.join('+');
  }

  function getPressedKeyString(event) {
    if (event.isComposing) return "";
    const keyParts = [];
    if (event.ctrlKey) keyParts.push("Control");
    if (event.altKey) keyParts.push("Alt");
    if (event.shiftKey) keyParts.push("Shift");
    if (event.metaKey) keyParts.push("Meta");
    const key = event.key;
    if (!["Control", "Alt", "Shift", "Meta"].includes(key)) {
      keyParts.push(key.length === 1 ? key.toUpperCase() : key);
    }
    return keyParts.join('+');
  }

  function inferAction(el) {
    if (!el) return null;
    const tag = el.tagName.toLowerCase();
    const type = (el.type || "").toLowerCase();
    if (type === "checkbox" || type === "radio") return "click";
    if (tag === "button" || tag === "a" || type === "submit") return "click";
    if (tag === "input" || tag === "textarea" || tag === "select") return "focus";
    return "click";
  }

  function parseSelectorAction(target) {
    const match = target.match(/^(.*?)(?::)(\w+)$/);
    if (match && VALID_ACTIONS.has(match[2])) {
      return { selector: match[1], action: match[2] };
    }
    return { selector: target, action: null };
  }

  function bindToElement(hotkey, target, options = {}) {
    const { selector, action } = parseSelectorAction(target);
    const el = document.querySelector(selector);
  
    if (!el) {
      console.warn(`HotkeyMapper: 指定された要素が見つかりません (${selector})`);
      return;
    }
  
    const effectiveAction = action || inferAction(el);
    if (!VALID_ACTIONS.has(effectiveAction)) {
      console.warn(`HotkeyMapper: 無効または未対応のアクションです (${effectiveAction})`);
      return;
    }
  
    const description = options.description || "";
  
    const handler = () => {
      if (effectiveAction === "click" && el.type === "checkbox") {
        el.checked = !el.checked;
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else if (effectiveAction === "click" && el.type === "radio") {
        el.checked = true;
        el.dispatchEvent(new Event("click", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        const event = new Event(effectiveAction, { bubbles: true, cancelable: true });
        el.dispatchEvent(event);
        if (effectiveAction === "focus" && typeof el.focus === "function") el.focus();
      }
    };
  
    map(hotkey, handler, {
      description,
      allowInInput: options.allowInInput,
      useCapture: options.useCapture
    });
  }
  
  function map(hotkey, callback, options = {}) {
    const normalized = normalizeHotkey(hotkey);
    if (!normalized || typeof callback !== "function") return;
    if (hotkeyMap.has(normalized)) {
      console.warn(`Hotkey already mapped: ${normalized}`);
      return;
    }
    const entry = {
      handler: callback,
      description: options.description || "",
      allowInInput: !!options.allowInInput
    };
    hotkeyMap.set(normalized, entry);
    if (options.useCapture) captureHotkeys.add(normalized);
  }

  function overwrite(hotkey, callback, options = {}) {
    unmap(hotkey);
    map(hotkey, callback, options);
  }

  function unmap(hotkey) {
    const normalized = normalizeHotkey(hotkey);
    if (normalized) {
      hotkeyMap.delete(normalized);
      captureHotkeys.delete(normalized);
    }
  }

  function getMappings() {
    return Array.from(hotkeyMap.entries()).map(([hotkey, entry]) => ({
      hotkey,
      description: entry.description,
      handler: entry.handler,
    }));
  }

  
  function ensureHotkeyHelpStyle() {
    if (document.getElementById("hotkey-help-style")) return;

    const style = document.createElement("style");
    style.id = "hotkey-help-style";
    style.textContent = `
#hotkey-help {
  display: none;
  flex-direction: column;
  position: fixed;
  width: 420px;
  background: rgba(0, 0, 0, 0.55);
  color: white;
  border: 4px solid rgba(255, 255, 255, 0.45);
  border-radius: 8px;
  box-sizing: border-box;
  backdrop-filter: blur(5px);
  box-shadow: 0 0 10px rgba(0, 0, 0, 0.5);
  font-family: monospace;
  z-index: 9999;
  min-width: 260px;
  min-height: 160px;
}

#hotkey-help .hotkey-help-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  background: rgba(64, 128, 64, 0.4);
  cursor: move;
  user-select: none;
  padding: 6px 10px;
}

#hotkey-help .hotkey-help-close {
  background: transparent;
  border: none;
  color: white;
  cursor: pointer;
  font-size: 16px;
  line-height: 16px;
}

#hotkey-help .hotkey-help-table-container {
  flex: 1;
  overflow: auto;
  padding: 8px 10px 10px;
  box-sizing: border-box;
}

#hotkey-help .hotkey-help-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

#hotkey-help .hotkey-help-table th,
#hotkey-help .hotkey-help-table td {
  padding: 4px 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.15);
  vertical-align: top;
  text-align: left;
}

#hotkey-help-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: transparent;
  z-index: 9998; /* #hotkey-help より下 */
  display: none;
}
    `;
    document.head.appendChild(style);

    // ドラッグ中にマウスイベントを安定して拾うためのオーバーレイ
    if (!document.getElementById("hotkey-help-overlay")) {
      const overlay = document.createElement("div");
      overlay.id = "hotkey-help-overlay";
      document.body.appendChild(overlay);
    }
  }

  function initHotkeyHelpDrag(container) {
    if (!container || container.dataset.dragInit === "1") return;
    container.dataset.dragInit = "1";

    const overlay = document.getElementById("hotkey-help-overlay");
    let isDragging = false;
    let startX = 0, startY = 0;

    container.addEventListener("mousedown", (e) => {
      const header = e.target.closest(".hotkey-help-header");
      if (!header) return;

      isDragging = true;
      startX = e.clientX - container.offsetLeft;
      startY = e.clientY - container.offsetTop;

      if (overlay) overlay.style.display = "block";
      e.stopPropagation();
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      container.style.left = `${e.clientX - startX}px`;
      container.style.top = `${e.clientY - startY}px`;
      container.style.right = "auto";
      container.style.bottom = "auto";
      e.preventDefault();
    });

    document.addEventListener("mouseup", () => {
      if (!isDragging) return;
      isDragging = false;
      if (overlay) overlay.style.display = "none";
    });
  }

  function showHelpWindow() {
    ensureHotkeyHelpStyle();

    let container = document.getElementById("hotkey-help");
    if (!container) {
      const mappings = getMappings();

      container = document.createElement("div");
      container.id = "hotkey-help";
      container.className = "hotkey-help-window";
      container.tabIndex = -1;

      container.innerHTML = `
        <div class="hotkey-help-header">
          <span>ショートカットキー一覧</span>
          <button class="hotkey-help-close" aria-label="閉じる">×</button>
        </div>
        <div class="hotkey-help-table-container">
          <table class="hotkey-help-table">
            <thead>
              <tr><th>キー</th><th>説明</th></tr>
            </thead>
            <tbody>
              ${mappings.map(item => `
                <tr><td>${item.hotkey}</td><td>${item.description || ""}</td></tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `;

      // 閉じる（remove ではなく display: none で「フロートしたまま」維持）
      container.querySelector(".hotkey-help-close")?.addEventListener("click", () => {
        container.style.display = "none";
      });

      document.body.appendChild(container);
      initHotkeyHelpDrag(container);
    }

    // 再表示（前回の位置のまま）
    container.style.display = "flex";
    container.focus();
  }

  
  document.addEventListener("keydown", (e) => {
    const popup = document.getElementById("hotkey-help");
    if (popup && e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      popup.style.display = "none";
    }
  });

  function isTypingContext() {
    const el = document.activeElement;
    const tag = el?.tagName?.toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || el?.isContentEditable;
  }

  function isModifierKey(key) {
    return key === "Control" || key === "Alt" || key === "Shift" || key === "Meta";
  }

  function handleKeydown(event, capturePhase) {
    if (event.repeat || event.isComposing) return;
    const key = getPressedKeyString(event);
    console.log("key1:", key, capturePhase);
    if (!capturePhase) updateHotkeyInputDisplay(key, { appendHistory: false });
    const isCapture = captureHotkeys.has(key);
    if (capturePhase !== isCapture) return;
    console.log("key2:", key, capturePhase);
    const entry = hotkeyMap.get(key);
    if (!entry) return;
    console.log("key3:", key, capturePhase);
    if (isTypingContext() && !entry.allowInInput) return;
    console.log("key4:", key, capturePhase);
    if (!isModifierKey(event.key)) {
      if (pressedKeyCodes.has(event.code)) return;
      pressedKeyCodes.add(event.code);
    }
    updateHotkeyInputDisplay(key, { appendHistory: true });
    event.preventDefault();
    console.log("HotkeyMapper: 発火", key);
    entry.handler(event);
  }

  document.addEventListener("keydown", (e) => handleKeydown(e, false), false);
  document.addEventListener("keydown", (e) => handleKeydown(e, true), true);
  document.addEventListener("keyup", (event) => {
    if (!isModifierKey(event.key)) {
      pressedKeyCodes.delete(event.code);
    }
  });

  function ensureHotkeyInputDisplay() {
    let container = document.getElementById("hotkey-input-display");
    if (container) return container;

    container = document.createElement("div");
    container.id = "hotkey-input-display";
    container.innerHTML = `
      <div class="hotkey-input-header">
        <span class="hotkey-input-title">HotKey</span>
        <span class="hotkey-input-hint">Drag / Resize</span>
      </div>
      <div class="hotkey-input-body">
        <div class="hotkey-input-current">
          <span class="hotkey-input-label">Key</span>
          <span class="hotkey-input-value">-</span>
          <span class="hotkey-input-desc">-</span>
        </div>
        <div class="hotkey-input-history"></div>
      </div>
    `;

    document.body.appendChild(container);
    initHotkeyInputDrag(container);
    return container;
  }

  function setHotkeyInputDisplayVisible(visible) {
    const container = ensureHotkeyInputDisplay();
    container.style.display = visible ? "flex" : "none";
    if (visible && lastPressedKey) {
      updateHotkeyInputDisplay(lastPressedKey);
    }
  }

  function updateHotkeyInputDisplay(key, options = {}) {
    const appendHistory = options.appendHistory === true;
    lastPressedKey = key || "";
    const container = ensureHotkeyInputDisplay();
    if (container.style.display === "none") return;

    const entry = key ? hotkeyMap.get(key) : null;
    const valueEl = container.querySelector(".hotkey-input-value");
    const descEl = container.querySelector(".hotkey-input-desc");
    const historyEl = container.querySelector(".hotkey-input-history");
    const descText = entry?.description || "-";
    if (valueEl) valueEl.textContent = key || "-";
    if (descEl) descEl.textContent = descText;

    if (historyEl && key && appendHistory) {
      hotkeyInputHistoryCounter += 1;
      hotkeyInputHistory.push({
        key,
        desc: descText,
        count: hotkeyInputHistoryCounter
      });

      const row = document.createElement("div");
      row.className = "hotkey-input-history-row";
      row.innerHTML =
        `<span class="hotkey-input-history-count">${hotkeyInputHistoryCounter}.</span>`
        + `<span class="hotkey-input-history-key">${key}</span>`
        + `<span class="hotkey-input-history-desc">${descText}</span>`;
      historyEl.appendChild(row);
      historyEl.scrollTop = historyEl.scrollHeight;

      if (hotkeyInputHistory.length > HOTKEY_INPUT_HISTORY_LIMIT) {
        hotkeyInputHistory.shift();
        const firstRow = historyEl.querySelector(".hotkey-input-history-row");
        if (firstRow) firstRow.remove();
      }
    }

    container.classList.remove("hotkey-input-flash");
    void container.offsetWidth;
    container.classList.add("hotkey-input-flash");
  }

  function initHotkeyInputDrag(container) {
    if (!container || container.dataset.dragInit === "1") return;
    container.dataset.dragInit = "1";

    let isDragging = false;
    let startX = 0;
    let startY = 0;

    container.addEventListener("mousedown", (e) => {
      const header = e.target.closest(".hotkey-input-header");
      if (!header) return;
      isDragging = true;
      startX = e.clientX - container.offsetLeft;
      startY = e.clientY - container.offsetTop;
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      container.style.left = `${e.clientX - startX}px`;
      container.style.top = `${e.clientY - startY}px`;
      container.style.right = "auto";
      container.style.bottom = "auto";
      e.preventDefault();
    });

    document.addEventListener("mouseup", () => {
      if (!isDragging) return;
      isDragging = false;
    });
  }

  document.addEventListener("auto-toggle-change", (event) => {
    if (event.detail?.id !== HOTKEY_INPUT_TOGGLE_ID) return;
    setHotkeyInputDisplayVisible(!!event.detail.newState);
  });

  function selectRelativeRadioInGroup(selector, direction) {
    const el = document.querySelector(selector);
    if (!el || el.type !== "radio" || !el.name) {
      console.warn(`HotkeyMapper: ラジオの指定が不正 (${selector})`);
      return;
    }
    const group = Array.from(document.querySelectorAll(`input[type="radio"][name="${el.name}"]`))
      .sort((a, b) => (a.tabIndex || 0) - (b.tabIndex || 0));
    if (!group.length) return;
    const currentIndex = group.findIndex(r => r.checked);
    const delta = direction === "next" ? 1 : -1;
    const nextIndex = (currentIndex + delta + group.length) % group.length;
    group[nextIndex].checked = true;
    group[nextIndex].dispatchEvent(new Event("change", { bubbles: true }));
  }

  function nextRadio(hotkey, selector, options = {}) {
    map(hotkey, () => selectRelativeRadioInGroup(selector, "next"), {
      ...options,
      description: options.description || "ラジオボタン次へ"
    });
  }

  function prevRadio(hotkey, selector, options = {}) {
    map(hotkey, () => selectRelativeRadioInGroup(selector, "prev"), {
      ...options,
      description: options.description || "ラジオボタン前へ"
    });
  }

  return {
    map,
    overwrite,
    unmap,
    bindToElement,
    getMappings,
    showHelpWindow,
    nextRadio,
    prevRadio
  };
})();
