const statusEl = document.getElementById("status");
const baseUrlInput = document.getElementById("baseUrl");
const bookNameInput = document.getElementById("bookName");
const forceUpdateInput = document.getElementById("forceUpdate");
const preferExternalInput = document.getElementById("preferExternal");
const sendButton = document.getElementById("sendButton");

const STORAGE_KEY = "paraparatrans_capture_settings";

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "#b00020" : "#1b5e20";
}

function normalizeBaseUrl(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "";
  return trimmed.replace(/\/+$/, "");
}

function isLocalhostUrl(url) {
  return /^(https?:\/\/)(localhost|127\.0\.0\.1)(:\d+)?\//i.test(url || "");
}

function pickBestFrame(frames, preferExternal) {
  const valid = frames.filter((item) => item && item.url && item.html);
  if (!valid.length) return null;

  let candidates = valid;
  if (preferExternal) {
    const external = valid.filter((item) => !isLocalhostUrl(item.url));
    if (external.length) candidates = external;
  }

  candidates.sort((a, b) => (b.textLength || 0) - (a.textLength || 0));
  return candidates[0] || null;
}

function captureFrames(tabId) {
  return chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => {
      try {
        const url = window.location.href || "";
        if (!url || url.startsWith("chrome://") || url.startsWith("about:")) {
          return null;
        }
        const html = document.documentElement ? document.documentElement.outerHTML : "";
        const textLength = document.body ? document.body.innerText.trim().length : 0;
        const title = document.title || "";
        return {
          url,
          title,
          html,
          textLength,
          isTop: window === window.top,
        };
      } catch (err) {
        return null;
      }
    },
  });
}

async function loadSettings() {
  const data = await chrome.storage.sync.get(STORAGE_KEY);
  const settings = data[STORAGE_KEY] || {};
  baseUrlInput.value = settings.baseUrl || "http://localhost:5077";
  bookNameInput.value = settings.bookName || "";
  forceUpdateInput.checked = Boolean(settings.forceUpdate);
  preferExternalInput.checked = settings.preferExternal !== false;
}

async function saveSettings() {
  const settings = {
    baseUrl: normalizeBaseUrl(baseUrlInput.value),
    bookName: bookNameInput.value.trim(),
    forceUpdate: forceUpdateInput.checked,
    preferExternal: preferExternalInput.checked,
  };
  await chrome.storage.sync.set({ [STORAGE_KEY]: settings });
}

async function handleSend() {
  setStatus("");
  const baseUrl = normalizeBaseUrl(baseUrlInput.value);
  let bookName = bookNameInput.value.trim();

  if (!baseUrl) {
    setStatus("ParaParaTrans URL is required.", true);
    return;
  }
  if (!bookName) {
    try {
      const currentRes = await fetch(`${baseUrl}/api/url_book/current`);
      const currentData = await currentRes.json().catch(() => ({}));
      if (currentRes.ok && currentData.status === "ok" && currentData.book_name) {
        bookName = String(currentData.book_name || "").trim();
      }
    } catch (e) {
      // ignore and fall through
    }
  }
  if (!bookName) {
    setStatus("Book name is empty. Open a URL book first.", true);
    return;
  }

  sendButton.disabled = true;
  setStatus("Capturing page...");

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      setStatus("Active tab not found.", true);
      sendButton.disabled = false;
      return;
    }

    const injections = await captureFrames(tab.id);
    const frames = injections.map((item) => item.result).filter(Boolean);
    const selected = pickBestFrame(frames, preferExternalInput.checked);
    if (!selected) {
      setStatus("No page content found.", true);
      sendButton.disabled = false;
      return;
    }

    setStatus("Sending to ParaParaTrans...");

    const apiUrl = `${baseUrl}/api/url_book/import_html`;
    const payload = {
      book_name: bookName,
      url: selected.url,
      html: selected.html,
      force: forceUpdateInput.checked,
    };

    const response = await fetch(apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status !== "ok") {
      setStatus(data.message || `Request failed (${response.status})`, true);
      sendButton.disabled = false;
      return;
    }

    const flags = [];
    if (data.added) flags.push("added");
    if (data.updated) flags.push("updated");
    if (data.exists) flags.push("exists");
    const suffix = flags.length ? ` (${flags.join(", ")})` : "";

    setStatus(`Done: page ${data.page_number}${suffix}`);
  } catch (err) {
    setStatus(`Error: ${err.message || err}`, true);
  } finally {
    sendButton.disabled = false;
    await saveSettings();
  }
}

baseUrlInput.addEventListener("change", saveSettings);
bookNameInput.addEventListener("change", saveSettings);
forceUpdateInput.addEventListener("change", saveSettings);
preferExternalInput.addEventListener("change", saveSettings);
sendButton.addEventListener("click", handleSend);

loadSettings();
