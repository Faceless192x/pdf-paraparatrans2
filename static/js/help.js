// help.js
// Debug: set `window.HELP_DEBUG = true` to enable console logs.

const helpDebugLog = (...args) => {
  if (window.HELP_DEBUG) {
    console.log(...args);
  }
};

let helpSections = {};
let helpMarkdownText = '';
let activeTooltip = null;

const escapeHtml = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

const slugifyHeading = (text) => String(text ?? '')
  .trim()
  .toLowerCase()
  .replace(/<[^>]*>/g, '')
  .replace(/[`*_~]/g, '')
  .replace(/\s+/g, '-')
  .replace(/[^\w\-ぁ-んァ-ン一-龠]/g, '-');

const renderInlineMarkdown = (text) => {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return html;
};

const markdownToPlainText = (markdownText) => String(markdownText ?? '')
  .replace(/^#+\s*/gm, '')
  .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1 ($2)')
  .replace(/`([^`]+)`/g, '$1')
  .replace(/\*\*([^*]+)\*\*/g, '$1')
  .replace(/\r/g, '')
  .replace(/\n{3,}/g, '\n\n')
  .trim();

const renderMarkdownToHtml = (markdownText) => {
  const lines = String(markdownText ?? '').replace(/\r/g, '').split('\n');
  const html = [];
  let inUl = false;
  let inOl = false;
  let inParagraph = false;

  const closeParagraph = () => {
    if (inParagraph) {
      html.push('</p>');
      inParagraph = false;
    }
  };

  const closeLists = () => {
    if (inUl) {
      html.push('</ul>');
      inUl = false;
    }
    if (inOl) {
      html.push('</ol>');
      inOl = false;
    }
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      closeParagraph();
      closeLists();
      return;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      closeParagraph();
      closeLists();
      const level = headingMatch[1].length;
      const text = headingMatch[2].trim();
      const id = slugifyHeading(text);
      html.push(`<h${level} id="${id}">${renderInlineMarkdown(text)}</h${level}>`);
      return;
    }

    const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (ulMatch) {
      closeParagraph();
      if (inOl) {
        html.push('</ol>');
        inOl = false;
      }
      if (!inUl) {
        html.push('<ul>');
        inUl = true;
      }
      html.push(`<li>${renderInlineMarkdown(ulMatch[1])}</li>`);
      return;
    }

    const olMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (olMatch) {
      closeParagraph();
      if (inUl) {
        html.push('</ul>');
        inUl = false;
      }
      if (!inOl) {
        html.push('<ol>');
        inOl = true;
      }
      html.push(`<li>${renderInlineMarkdown(olMatch[1])}</li>`);
      return;
    }

    closeLists();
    if (!inParagraph) {
      html.push('<p>');
      inParagraph = true;
    } else {
      html.push('<br>');
    }
    html.push(renderInlineMarkdown(trimmed));
  });

  closeParagraph();
  closeLists();
  return html.join('');
};

const parseHelpMarkdown = (markdownText) => {
  helpDebugLog('Parsing markdown text...');
  const sections = {};
  const lines = String(markdownText ?? '').trim().split('\n');
  let currentId = null;
  let currentContent = [];

  for (const line of lines) {
    const trimmedLine = line.trim();
    const sectionMatch = trimmedLine.match(/^##\s*(.+)$/);
    if (sectionMatch) {
      if (currentId && currentContent.length > 0) {
        sections[currentId] = currentContent.join('\n').trim();
      }
      currentId = sectionMatch[1].trim();
      currentContent = [];
      helpDebugLog(`Found section: ${currentId}`);
    } else if (currentId !== null) {
      currentContent.push(line);
    }
  }

  if (currentId && currentContent.length > 0) {
    sections[currentId] = currentContent.join('\n').trim();
  }
  helpDebugLog('Markdown parsing complete. Resulting sections:', sections);
  return sections;
};

const ensureTooltipElement = () => {
  let tooltip = document.getElementById('help-inline-tooltip');
  if (tooltip) return tooltip;
  tooltip = document.createElement('div');
  tooltip.id = 'help-inline-tooltip';
  tooltip.className = 'help-inline-tooltip';
  tooltip.style.display = 'none';
  document.body.appendChild(tooltip);
  return tooltip;
};

const hideHelpTooltip = () => {
  const tooltip = document.getElementById('help-inline-tooltip');
  if (!tooltip) return;
  tooltip.style.display = 'none';
  tooltip.innerHTML = '';
  activeTooltip = null;
};

const positionHelpTooltip = (tooltip, reference) => {
  const rect = reference.getBoundingClientRect();
  const margin = 10;
  const maxWidth = Math.min(window.innerWidth - 20, 640);
  tooltip.style.maxWidth = `${maxWidth}px`;
  tooltip.style.left = '10px';
  tooltip.style.top = '10px';
  tooltip.style.display = 'block';

  const tooltipRect = tooltip.getBoundingClientRect();
  let left = rect.left;
  let top = rect.bottom + margin;

  if (left + tooltipRect.width > window.innerWidth - 10) {
    left = Math.max(10, window.innerWidth - tooltipRect.width - 10);
  }
  if (top + tooltipRect.height > window.innerHeight - 10) {
    top = Math.max(10, rect.top - tooltipRect.height - margin);
  }

  tooltip.style.left = `${Math.max(10, left)}px`;
  tooltip.style.top = `${Math.max(10, top)}px`;
};

const showHelpTooltip = (reference) => {
  const helpId = reference.getAttribute('data-help-id');
  if (!helpId) return;
  const section = helpSections[helpId];
  if (!section) return;

  const tooltip = ensureTooltipElement();
  tooltip.innerHTML = renderMarkdownToHtml(section);
  positionHelpTooltip(tooltip, reference);
  activeTooltip = reference;
};

const bindHelpTooltip = (reference) => {
  if (!reference || reference.dataset.helpBound === '1') return;
  const helpId = reference.getAttribute('data-help-id');
  if (!helpId) return;
  const section = helpSections[helpId];
  if (!section) return;

  reference.dataset.helpBound = '1';
  reference.dataset.helpText = markdownToPlainText(section);
  reference.setAttribute('title', markdownToPlainText(section));

  reference.addEventListener('mouseenter', () => showHelpTooltip(reference));
  reference.addEventListener('focus', () => showHelpTooltip(reference));
  reference.addEventListener('mouseleave', () => {
    if (activeTooltip === reference) hideHelpTooltip();
  });
  reference.addEventListener('blur', () => {
    if (activeTooltip === reference) hideHelpTooltip();
  });
}

const initializeHelp = async () => {
  try {
    const response = await fetch('/static/parapara-help.md');
    helpMarkdownText = await response.text();
    helpSections = parseHelpMarkdown(helpMarkdownText);
    helpDebugLog('Help sections loaded and parsed.');
  } catch (error) {
    console.error('Failed to fetch or parse help.md:', error);
    return;
  }

  document.querySelectorAll('[data-help-id]').forEach(bindHelpTooltip);
};

const extractHeadings = (markdownText) => {
  const lines = String(markdownText ?? '').replace(/\r/g, '').split('\n');
  return lines
    .map((line) => line.trim())
    .map((line) => line.match(/^(#{1,6})\s+(.+)$/))
    .filter(Boolean)
    .map((match) => ({
      level: match[1].length,
      text: match[2].trim(),
      id: slugifyHeading(match[2].trim()),
    }));
};

const buildTocHtml = (headings) => {
  if (!headings.length) return '';
  const root = [];
  const stack = [{ level: 0, children: root }];

  headings.forEach((heading) => {
    const item = { ...heading, children: [] };
    while (stack.length > 1 && heading.level <= stack[stack.length - 1].level) {
      stack.pop();
    }
    stack[stack.length - 1].children.push(item);
    stack.push(item);
  });

  const renderItems = (items) => {
    if (!items.length) return '';
    return `<ul>${items.map((item) => `
      <li class="level-${item.level}"><a href="#${item.id}">${escapeHtml(item.text)}</a>${renderItems(item.children)}</li>
    `).join('')}</ul>`;
  };

  return renderItems(root);
};

const showFullHelp = async () => {
  try {
    if (!helpMarkdownText) {
      const response = await fetch('/static/parapara-help.md');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      helpMarkdownText = await response.text();
      if (!Object.keys(helpSections).length) {
        helpSections = parseHelpMarkdown(helpMarkdownText);
      }
    }

    const htmlContent = renderMarkdownToHtml(helpMarkdownText);
    const headings = extractHeadings(helpMarkdownText);

    const modalOverlay = document.createElement('div');
    modalOverlay.classList.add('help-modal-overlay');

    const modalContent = document.createElement('div');
    modalContent.classList.add('help-modal-content');

    const modalHeader = document.createElement('div');
    modalHeader.classList.add('help-modal-header');
    modalHeader.innerHTML = '<h2>ヘルプ</h2>';

    const closeButton = document.createElement('button');
    closeButton.classList.add('help-modal-close');
    closeButton.setAttribute('aria-label', '閉じる');
    closeButton.innerHTML = '&times;';
    closeButton.onclick = () => {
      document.body.removeChild(modalOverlay);
    };

    modalHeader.appendChild(closeButton);

    const modalBody = document.createElement('div');
    modalBody.classList.add('help-modal-body');

    const tocNav = document.createElement('nav');
    tocNav.classList.add('help-toc');
    tocNav.innerHTML = buildTocHtml(headings);

    const contentDiv = document.createElement('div');
    contentDiv.classList.add('help-content');
    contentDiv.innerHTML = htmlContent;

    modalBody.appendChild(tocNav);
    modalBody.appendChild(contentDiv);

    modalContent.appendChild(modalHeader);
    modalContent.appendChild(modalBody);
    modalOverlay.appendChild(modalContent);
    document.body.appendChild(modalOverlay);

    modalOverlay.addEventListener('click', (event) => {
      if (event.target === modalOverlay) {
        document.body.removeChild(modalOverlay);
      }
    });

    const onKeyDown = (event) => {
      if (event.key === 'Escape' && document.body.contains(modalOverlay)) {
        document.body.removeChild(modalOverlay);
        document.removeEventListener('keydown', onKeyDown);
      }
    };
    document.addEventListener('keydown', onKeyDown);

    tocNav.querySelectorAll('a').forEach(link => {
      link.onclick = (e) => {
        e.preventDefault();
        const targetId = link.getAttribute('href').substring(1);
        const targetElement = contentDiv.querySelector(`#${CSS.escape(targetId)}`);
        if (targetElement) {
          targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      };
    });
  } catch (error) {
    console.error('Failed to show full help:', error);
    alert('ヘルプを開けませんでした。');
  }
};

window.showFullHelp = showFullHelp;

document.addEventListener('DOMContentLoaded', () => {
  const fullHelpButton = document.getElementById('show-full-help');
  if (fullHelpButton) {
    fullHelpButton.addEventListener('click', showFullHelp);
  }

  initializeHelp();

  window.addEventListener('scroll', () => {
    if (activeTooltip) showHelpTooltip(activeTooltip);
  }, true);
  window.addEventListener('resize', () => {
    if (activeTooltip) showHelpTooltip(activeTooltip);
  });
  document.addEventListener('click', (event) => {
    const tooltip = document.getElementById('help-inline-tooltip');
    if (!tooltip || tooltip.style.display === 'none') return;
    if (tooltip.contains(event.target)) return;
    if (event.target.closest('[data-help-id]')) return;
    hideHelpTooltip();
  });
});
