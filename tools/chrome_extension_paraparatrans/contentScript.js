function cssEscape(value) {
  if (typeof CSS !== "undefined" && CSS.escape) {
    return CSS.escape(value);
  }
  return String(value || "").replace(/[^a-zA-Z0-9_-]/g, function (ch) {
    const hex = ch.charCodeAt(0).toString(16);
    return "\\" + hex + " ";
  });
}

function buildSimpleSelector(el) {
  const tag = (el.tagName || "").toLowerCase();
  if (!tag) return "";

  if (el.id) {
    return "#" + cssEscape(el.id);
  }

  const classes = Array.from(el.classList || [])
    .map((cls) => cls.trim())
    .filter((cls) => cls.length > 0)
    .slice(0, 2)
    .map((cls) => "." + cssEscape(cls));

  if (classes.length) {
    return tag + classes.join("");
  }

  let selector = tag;
  if (el.parentElement) {
    const siblings = Array.from(el.parentElement.children || []).filter(
      (node) => (node.tagName || "").toLowerCase() === tag
    );
    if (siblings.length > 1) {
      const index = siblings.indexOf(el) + 1;
      selector += ":nth-of-type(" + index + ")";
    }
  }

  return selector;
}

function buildSelector(el) {
  if (!el || !el.tagName) return "";

  const parts = [];
  let current = el;
  let depth = 0;
  while (current && current.tagName && depth < 4) {
    const part = buildSimpleSelector(current);
    if (!part) break;
    parts.unshift(part);
    if (part.startsWith("#")) {
      break;
    }
    current = current.parentElement;
    depth += 1;
  }

  return parts.join(" > ");
}

function storeContextTarget(event) {
  const target = event.target;
  const selector = buildSelector(target);
  if (!selector) return;
  window.__pptLastContextTarget = {
    selector,
    time: Date.now(),
    url: window.location.href || "",
  };
}

if (!window.__pptContextListenerAttached) {
  window.addEventListener("contextmenu", storeContextTarget, true);
  window.__pptContextListenerAttached = true;
}

window.__pptUrlBridgeUntil = 0;

function isUrlBridgeEnabled() {
  return Date.now() <= Number(window.__pptUrlBridgeUntil || 0);
}

function enableUrlBridge(ttlMs = 4000) {
  const ttl = Number(ttlMs) || 4000;
  window.__pptUrlBridgeUntil = Date.now() + Math.max(1000, ttl);
}

function forwardBridgeEnableToChildFrames(ttlMs = 4000) {
  const iframes = Array.from(document.querySelectorAll("iframe"));
  for (const frame of iframes) {
    try {
      if (frame && frame.contentWindow) {
        frame.contentWindow.postMessage({ type: "ppt-url-bridge-enable", ttlMs }, "*");
      }
    } catch (_) {
      // ignore cross-origin access issues
    }
  }
}

function findAnchorElement(target) {
  let node = target;
  while (node) {
    if (node.tagName && String(node.tagName).toLowerCase() === "a") {
      return node;
    }
    node = node.parentElement;
  }
  return null;
}

function handleBridgeLinkClick(event) {
  if (!isUrlBridgeEnabled()) return;
  const anchor = findAnchorElement(event.target);
  if (!anchor || !anchor.href) return;

  const target = String(anchor.getAttribute("target") || "").toLowerCase();
  if (target !== "_top" && target !== "_parent") return;

  event.preventDefault();
  event.stopPropagation();

  window.top.postMessage(
    {
      type: "ppt-url-preview-open-url",
      url: anchor.href,
    },
    "*"
  );
}

if (!window.__pptBridgeClickAttached) {
  window.addEventListener("click", handleBridgeLinkClick, true);
  window.__pptBridgeClickAttached = true;
}

function isParaParaTransPage() {
  const origin = window.location.origin || "";
  return origin.startsWith("http://localhost:5077") || origin.startsWith("http://127.0.0.1:5077");
}

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.type !== "ppt-refresh") return;
  if (window !== window.top) return;
  if (!isParaParaTransPage()) return;
  window.postMessage({ type: "ppt-refresh", kind: message.kind || "import" }, "*");
});

window.addEventListener("message", (event) => {
  const data = event && event.data;
  if (!data || data.type !== "ppt-capture-request") return;

  const force = data.force !== false;
  chrome.runtime.sendMessage({
    type: "ppt-capture-request",
    force,
  });
});

window.addEventListener("message", (event) => {
  const data = event && event.data;
  if (!data || data.type !== "ppt-capture-peek-url") return;

  const url = window.location.href || "";
  window.top.postMessage({
    type: "ppt-capture-current-url",
    url,
  }, "*");
});

window.addEventListener("message", (event) => {
  const data = event && event.data;
  if (!data || data.type !== "ppt-url-bridge-enable") return;
  const ttlMs = Number(data.ttlMs || 4000);
  enableUrlBridge(ttlMs);
  forwardBridgeEnableToChildFrames(ttlMs);
});
