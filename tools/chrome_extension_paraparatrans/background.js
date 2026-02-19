const STORAGE_KEY = "paraparatrans_capture_settings";
const MENU_ID = "paraparatrans_capture_page";
const MENU_ID_INCLUDE = "paraparatrans_rule_include";
const MENU_ID_ADD = "paraparatrans_rule_add";
const MENU_ID_EXCLUDE = "paraparatrans_rule_exclude";
const CONTEXT_TTL_MS = 15000;

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

function getBadgeColor(isError) {
  return isError ? "#b00020" : "#1b5e20";
}

async function setBadge(text, isError = false) {
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color: getBadgeColor(isError) });
  if (text) {
    setTimeout(() => {
      chrome.action.setBadgeText({ text: "" });
    }, 3000);
  }
}

function captureFrame(tabId, frameId) {
  return chrome.scripting.executeScript({
    target: { tabId, frameIds: [frameId] },
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

function captureAllFrames(tabId) {
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

async function getSettings() {
  const data = await chrome.storage.sync.get(STORAGE_KEY);
  const settings = data[STORAGE_KEY] || {};
  return {
    baseUrl: normalizeBaseUrl(settings.baseUrl || "http://localhost:5077"),
    bookName: String(settings.bookName || "").trim(),
    forceUpdate: Boolean(settings.forceUpdate),
    preferExternal: settings.preferExternal !== false,
  };
}

async function sendPayload(baseUrl, payload) {
  const apiUrl = `${baseUrl}/api/url_book/import_html`;
  const response = await fetch(apiUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.status !== "ok") {
    const message = data.message || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return data;
}

async function fetchSiteRules(baseUrl, bookName) {
  const response = await fetch(
    `${baseUrl}/api/url_book/site_rules/${encodeURIComponent(bookName)}`
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.status !== "ok") {
    const message = data.message || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return data.site_rules || {};
}

async function saveSiteRules(baseUrl, bookName, rules) {
  const response = await fetch(
    `${baseUrl}/api/url_book/site_rules/${encodeURIComponent(bookName)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rules || {}),
    }
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.status !== "ok") {
    const message = data.message || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return data.site_rules || {};
}

async function resolveBookName(baseUrl, fallback) {
  if (fallback) return fallback;
  const response = await fetch(`${baseUrl}/api/url_book/current`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.status !== "ok" || !data.book_name) {
    return "";
  }
  return String(data.book_name || "").trim();
}

function normalizeSelectorList(values) {
  if (!Array.isArray(values)) return [];
  return values
    .map((item) => String(item || "").trim())
    .filter((item) => item.length > 0);
}

function appendSelector(list, selector) {
  const next = normalizeSelectorList(list);
  if (!selector || next.includes(selector)) {
    return next;
  }
  next.push(selector);
  return next;
}

async function getLastContextTarget(tabId, frameId) {
  if (typeof tabId !== "number") return null;
  const execTarget = { tabId };
  if (typeof frameId === "number") {
    execTarget.frameIds = [frameId];
  }
  const result = await chrome.scripting.executeScript({
    target: execTarget,
    func: () => {
      const payload = window.__pptLastContextTarget || null;
      return payload;
    },
  });
  const payload = result.map((item) => item.result).find(Boolean) || null;
  if (!payload || !payload.selector) return null;
  if (payload.time && Date.now() - payload.time > CONTEXT_TTL_MS) {
    return null;
  }
  return payload;
}

async function handleCapture(info, tab, forceOverride = null) {
  console.log("ParaParaTrans capture start", {
    tabId: tab && tab.id,
    tabUrl: tab && tab.url,
    frameId: info && info.frameId,
  });
  await setBadge("RUN", false);
  if (!tab || !tab.id) {
    console.warn("ParaParaTrans capture aborted: no active tab");
    await setBadge("ERR", true);
    return;
  }

  const settings = await getSettings();
  if (!settings.baseUrl) {
    console.warn("ParaParaTrans capture aborted: baseUrl not set");
    await setBadge("SET", true);
    return;
  }

  const bookName = await resolveBookName(settings.baseUrl, settings.bookName);
  if (!bookName) {
    console.warn("ParaParaTrans capture aborted: bookName not set");
    await setBadge("SET", true);
    return;
  }

  let frames = [];
  if (typeof info.frameId === "number") {
    const single = await captureFrame(tab.id, info.frameId);
    frames = single.map((item) => item.result).filter(Boolean);
  }

  if (!frames.length) {
    const all = await captureAllFrames(tab.id);
    frames = all.map((item) => item.result).filter(Boolean);
  }

  console.log("ParaParaTrans capture frames", {
    count: frames.length,
  });

  const selected = pickBestFrame(frames, settings.preferExternal);
  if (!selected) {
    console.warn("ParaParaTrans capture aborted: no eligible frame");
    await setBadge("NO", true);
    return;
  }

  console.log("ParaParaTrans capture selected", {
    url: selected.url,
    textLength: selected.textLength,
    isTop: selected.isTop,
  });

  const forceValue =
    typeof forceOverride === "boolean" ? forceOverride : settings.forceUpdate;

  const payload = {
    book_name: bookName,
    url: selected.url,
    html: selected.html,
    force: forceValue,
  };

  try {
    const data = await sendPayload(settings.baseUrl, payload);
    const badge = data.added ? "ADD" : data.updated ? "UPD" : "EXS";
    await setBadge(badge, false);
    console.log("ParaParaTrans capture response", {
      pageNumber: data.page_number,
      added: data.added,
      updated: data.updated,
      exists: data.exists,
    });
    if (tab && tab.id) {
      chrome.tabs.sendMessage(tab.id, { type: "ppt-refresh", kind: "import" });
    }
    console.log("ParaParaTrans capture done");
  } catch (err) {
    await setBadge("ERR", true);
    console.error("ParaParaTrans capture failed", err);
  }
}

async function handleRuleUpdate(info, tab, ruleType) {
  console.log("ParaParaTrans rule update start", {
    ruleType,
    frameId: info && info.frameId,
    tabId: tab && tab.id,
  });
  await setBadge("RUN", false);

  if (!tab || !tab.id) {
    await setBadge("ERR", true);
    return;
  }

  const settings = await getSettings();
  if (!settings.baseUrl) {
    await setBadge("SET", true);
    return;
  }

  const bookName = await resolveBookName(settings.baseUrl, settings.bookName);
  if (!bookName) {
    await setBadge("SET", true);
    return;
  }

  const contextTarget = await getLastContextTarget(tab.id, info.frameId);
  if (!contextTarget || !contextTarget.selector) {
    console.warn("ParaParaTrans rule update aborted: no selector");
    await setBadge("NO", true);
    return;
  }

  try {
    const rules = await fetchSiteRules(settings.baseUrl, bookName);
    const payload = {
      include_selectors: normalizeSelectorList(rules.include_selectors),
      add_selectors: normalizeSelectorList(rules.add_selectors),
      exclude_selectors: normalizeSelectorList(rules.exclude_selectors),
    };

    if (ruleType === "include") {
      payload.include_selectors = appendSelector(
        payload.include_selectors,
        contextTarget.selector
      );
    } else if (ruleType === "add") {
      payload.add_selectors = appendSelector(
        payload.add_selectors,
        contextTarget.selector
      );
    } else if (ruleType === "exclude") {
      payload.exclude_selectors = appendSelector(
        payload.exclude_selectors,
        contextTarget.selector
      );
    }

    await saveSiteRules(settings.baseUrl, bookName, payload);
    const badge = ruleType === "include" ? "INC" : ruleType === "add" ? "ADD" : "EXC";
    await setBadge(badge, false);
    console.log("ParaParaTrans rule updated", {
      ruleType,
      selector: contextTarget.selector,
    });
    if (tab && tab.id) {
      chrome.tabs.sendMessage(tab.id, { type: "ppt-refresh", kind: "rule_update" });
    }
  } catch (err) {
    await setBadge("ERR", true);
    console.error("ParaParaTrans rule update failed", err);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_ID,
      title: "ParaParaTrans: 取込",
      contexts: ["page", "frame"],
    });
    chrome.contextMenus.create({
      id: MENU_ID_INCLUDE,
      title: "ParaParaTrans: この階層以下を取得",
      contexts: ["page", "frame"],
    });
    chrome.contextMenus.create({
      id: MENU_ID_ADD,
      title: "ParaParaTrans: この要素を取得",
      contexts: ["page", "frame"],
    });
    chrome.contextMenus.create({
      id: MENU_ID_EXCLUDE,
      title: "ParaParaTrans: この要素を排除",
      contexts: ["page", "frame"],
    });
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  console.log("ParaParaTrans context menu clicked", {
    menuId: info.menuItemId,
    frameId: info.frameId,
    tabId: tab && tab.id,
  });

  if (info.menuItemId === MENU_ID) {
    handleCapture(info, tab, true);
    return;
  }
  if (info.menuItemId === MENU_ID_INCLUDE) {
    handleRuleUpdate(info, tab, "include");
    return;
  }
  if (info.menuItemId === MENU_ID_ADD) {
    handleRuleUpdate(info, tab, "add");
    return;
  }
  if (info.menuItemId === MENU_ID_EXCLUDE) {
    handleRuleUpdate(info, tab, "exclude");
  }
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (!message || message.type !== "ppt-capture-request") {
    return;
  }

  const tab = sender && sender.tab;
  if (!tab || typeof tab.id !== "number") {
    setBadge("ERR", true);
    return;
  }

  const info = {
    menuItemId: MENU_ID,
    frameId: typeof sender.frameId === "number" ? sender.frameId : undefined,
  };
  const force = message.force !== false;
  handleCapture(info, tab, force);
});
