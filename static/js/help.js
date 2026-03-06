// help.js
// Debug: set `window.HELP_DEBUG = true` to enable console logs.

const helpDebugLog = (...args) => {
  if (window.HELP_DEBUG) {
    console.log(...args);
  }
};

let helpSections = {};
let helpTooltipEl = null;
let activeHelpTarget = null;

const escapeHtml = (value) => String(value || '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

const slugifyHeading = (value) => String(value || '')
  .trim()
  .toLowerCase()
  .replace(/[^\w\u3040-\u30ff\u3400-\u9fff -]+/g, '')
  .replace(/\s+/g, '-')
  .replace(/-+/g, '-');

const normalizeInlineBreaks = (value) => String(value || '').replace(/<br\s*\/?>/gi, '\n');

const renderInlineMarkdown = (value) => {
  let html = escapeHtml(normalizeInlineBreaks(value));
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_match, text, href) => {
    try {
      const url = new URL(href);
      if (!['http:', 'https:'].includes(url.protocol)) {
        return escapeHtml(text);
      }
      return `<a href="${escapeHtml(url.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(text)}</a>`;
    } catch (_err) {
      return escapeHtml(text);
    }
  });
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  return html.replace(/\n/g, '<br>');
};

const renderMarkdown = (markdownText) => {
  const lines = String(markdownText || '').replace(/\r\n?/g, '\n').split('\n');
  const htmlParts = [];
  const headings = [];
  let paragraphLines = [];
  let listType = null;
  let inCodeBlock = false;
  let codeLines = [];

  const flushParagraph = () => {
    if (!paragraphLines.length) return;
    htmlParts.push(`<p>${renderInlineMarkdown(paragraphLines.join('\n'))}</p>`);
    paragraphLines = [];
  };

  const closeList = () => {
    if (!listType) return;
    htmlParts.push(listType === 'ol' ? '</ol>' : '</ul>');
    listType = null;
  };

  const flushCodeBlock = () => {
    htmlParts.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
    codeLines = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.replace(/\t/g, '    ');
    const trimmed = line.trim();

    if (trimmed.startsWith('```')) {
      flushParagraph();
      closeList();
      if (inCodeBlock) {
        flushCodeBlock();
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
        codeLines = [];
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(rawLine);
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      closeList();
      const level = headingMatch[1].length;
      const text = headingMatch[2].trim();
      const id = slugifyHeading(text) || `heading-${headings.length + 1}`;
      headings.push({ id, text, level });
      htmlParts.push(`<h${level} id="${id}">${renderInlineMarkdown(text)}</h${level}>`);
      continue;
    }

    const listMatch = line.match(/^\s*((?:[-*])|(?:\d+\.))\s+(.+)$/);
    if (listMatch) {
      flushParagraph();
      const nextListType = /\d+\./.test(listMatch[1]) ? 'ol' : 'ul';
      if (listType !== nextListType) {
        closeList();
        htmlParts.push(nextListType === 'ol' ? '<ol>' : '<ul>');
        listType = nextListType;
      }
      htmlParts.push(`<li>${renderInlineMarkdown(listMatch[2].trim())}</li>`);
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      closeList();
      continue;
    }

    closeList();
    paragraphLines.push(trimmed);
  }

  flushParagraph();
  closeList();
  if (inCodeBlock) {
    flushCodeBlock();
  }

  return {
    html: htmlParts.join('\n'),
    headings,
  };
};

const parseHelpMarkdown = (markdownText) => {
  helpDebugLog('Parsing help markdown...');
  const sections = {};
  const lines = String(markdownText || '').replace(/\r\n?/g, '\n').split('\n');
  let currentId = null;
  let currentContent = [];

  for (const line of lines) {
    const trimmed = line.trim();
    const sectionMatch = trimmed.match(/^##\s*(.+)$/);
    if (sectionMatch) {
      if (currentId && currentContent.length > 0) {
        sections[currentId] = currentContent.join('\n').trim();
      }
      currentId = sectionMatch[1].trim();
      currentContent = [];
    } else if (currentId !== null) {
      currentContent.push(line);
    }
  }

  if (currentId && currentContent.length > 0) {
    sections[currentId] = currentContent.join('\n').trim();
  }
  return sections;
};

const buildTocTree = (headings) => {
  const root = [];
  const stack = [{ level: 0, children: root }];
  headings.forEach((heading) => {
    while (stack.length > 1 && heading.level <= stack[stack.length - 1].level) {
      stack.pop();
    }
    const node = { ...heading, children: [] };
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  });
  return root;
};

const buildTocHtml = (items) => {
  if (!items.length) return '';
  let html = '<ul>';
  items.forEach((item) => {
    html += `<li class="level-${item.level}"><a href="#${item.id}">${escapeHtml(item.text)}</a>`;
    html += buildTocHtml(item.children || []);
    html += '</li>';
  });
  html += '</ul>';
  return html;
};

const ensureTooltipElement = () => {
  if (helpTooltipEl) return helpTooltipEl;
  helpTooltipEl = document.createElement('div');
  helpTooltipEl.className = 'help-tooltip-popup';
  helpTooltipEl.setAttribute('role', 'tooltip');
  document.body.appendChild(helpTooltipEl);
  return helpTooltipEl;
};

const hideTooltip = () => {
  if (!helpTooltipEl) return;
  helpTooltipEl.classList.remove('is-visible');
  activeHelpTarget = null;
};

const positionTooltip = (target) => {
  if (!helpTooltipEl || !target) return;
  const rect = target.getBoundingClientRect();
  const margin = 10;
  const maxWidth = Math.min(window.innerWidth - 24, 720);
  helpTooltipEl.style.maxWidth = `${maxWidth}px`;
  helpTooltipEl.style.left = '12px';
  helpTooltipEl.style.top = '12px';

  const tooltipRect = helpTooltipEl.getBoundingClientRect();
  let left = rect.left;
  if (left + tooltipRect.width > window.innerWidth - margin) {
    left = window.innerWidth - tooltipRect.width - margin;
  }
  if (left < margin) {
    left = margin;
  }

  let top = rect.bottom + margin;
  if (top + tooltipRect.height > window.innerHeight - margin) {
    top = rect.top - tooltipRect.height - margin;
  }
  if (top < margin) {
    top = margin;
  }

  helpTooltipEl.style.left = `${Math.round(left)}px`;
  helpTooltipEl.style.top = `${Math.round(top)}px`;
};

const showTooltip = (target) => {
  const helpId = target.getAttribute('data-help-id');
  const section = helpSections[helpId];
  if (!section) {
    hideTooltip();
    return;
  }

  const tooltip = ensureTooltipElement();
  tooltip.innerHTML = `<div class="help-tooltip-title">${escapeHtml(helpId)}</div><div class="help-tooltip-body">${renderMarkdown(section).html}</div>`;
  tooltip.classList.add('is-visible');
  activeHelpTarget = target;
  positionTooltip(target);
};

const bindHelpTooltips = () => {
  const elements = document.querySelectorAll('[data-help-id]');
  elements.forEach((element) => {
    element.addEventListener('mouseenter', () => showTooltip(element));
    element.addEventListener('focus', () => showTooltip(element));
    element.addEventListener('mouseleave', hideTooltip);
    element.addEventListener('blur', hideTooltip);
  });
  window.addEventListener('scroll', () => {
    if (activeHelpTarget) {
      positionTooltip(activeHelpTarget);
    }
  }, true);
  window.addEventListener('resize', () => {
    if (activeHelpTarget) {
      positionTooltip(activeHelpTarget);
    }
  });
};

const initializeHelp = async () => {
  try {
    const response = await fetch('/static/parapara-help.md');
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const text = await response.text();
    helpSections = parseHelpMarkdown(text);
    bindHelpTooltips();
    helpDebugLog('Help sections loaded and tooltips initialized.');
  } catch (error) {
    console.error('Failed to fetch or parse help.md:', error);
  }
};

const showFullHelp = async () => {
  try {
    const response = await fetch('/static/parapara-help.md');
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const markdownText = await response.text();
    const rendered = renderMarkdown(markdownText);

    const modalOverlay = document.createElement('div');
    modalOverlay.classList.add('help-modal-overlay');

    const modalContent = document.createElement('div');
    modalContent.classList.add('help-modal-content');

    const modalHeader = document.createElement('div');
    modalHeader.classList.add('help-modal-header');
    modalHeader.innerHTML = '<h2>Help Documentation</h2>';

    const closeButton = document.createElement('button');
    closeButton.classList.add('help-modal-close');
    closeButton.innerHTML = '&times;';
    closeButton.onclick = () => {
      document.body.removeChild(modalOverlay);
    };

    modalHeader.appendChild(closeButton);

    const modalBody = document.createElement('div');
    modalBody.classList.add('help-modal-body');

    const tocNav = document.createElement('nav');
    tocNav.classList.add('help-toc');
    tocNav.innerHTML = buildTocHtml(buildTocTree(rendered.headings));

    const contentDiv = document.createElement('div');
    contentDiv.classList.add('help-content');
    contentDiv.innerHTML = rendered.html;

    modalBody.appendChild(tocNav);
    modalBody.appendChild(contentDiv);

    modalContent.appendChild(modalHeader);
    modalContent.appendChild(modalBody);
    modalOverlay.appendChild(modalContent);
    modalOverlay.addEventListener('click', (event) => {
      if (event.target === modalOverlay) {
        document.body.removeChild(modalOverlay);
      }
    });

    document.body.appendChild(modalOverlay);

    tocNav.querySelectorAll('a').forEach((link) => {
      link.onclick = (event) => {
        event.preventDefault();
        const targetId = link.getAttribute('href').substring(1);
        const targetElement = document.getElementById(targetId);
        if (targetElement && contentDiv.contains(targetElement)) {
          targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      };
    });
  } catch (error) {
    console.error('Failed to show full help:', error);
    alert('Failed to load help documentation.');
  }
};

const onHelpReady = () => {
  initializeHelp();

  const fullHelpButton = document.getElementById('show-full-help');
  if (fullHelpButton) {
    fullHelpButton.addEventListener('click', showFullHelp);
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', onHelpReady);
} else {
  onHelpReady();
}
