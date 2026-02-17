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
