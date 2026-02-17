function openUrlRuleDialog() {
    if (!isUrlBook()) return;
    const dialog = document.getElementById('urlRuleDialog');
    if (!dialog) return;
    dialog.style.display = 'flex';
    loadUrlRuleDialog();
}

function closeUrlRuleDialog() {
    const dialog = document.getElementById('urlRuleDialog');
    if (!dialog) return;
    dialog.style.display = 'none';
}

function isUrlRuleDialogOpen() {
    const dialog = document.getElementById('urlRuleDialog');
    if (!dialog) return false;
    return dialog.style.display !== 'none';
}

function setUrlRuleStatus(message, isError = false) {
    const statusEl = document.getElementById('urlRuleStatus');
    if (!statusEl) return;
    statusEl.textContent = message || '';
    statusEl.style.color = isError ? '#b00020' : '#1b5e20';
}

function splitSelectors(value) {
    return String(value || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line.length > 0);
}

function joinSelectors(selectors) {
    if (!Array.isArray(selectors)) return '';
    return selectors.join('\n');
}

async function loadUrlRuleDialog() {
    if (!pdfName) return;
    setUrlRuleStatus('');
    try {
        const res = await fetch(`/api/url_book/site_rules/${encodePdfNamePath(pdfName)}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status !== 'ok') {
            setUrlRuleStatus(data.message || '取得に失敗しました', true);
            return;
        }

        const rules = data.site_rules || {};
        const includeEl = document.getElementById('urlRuleInclude');
        const addEl = document.getElementById('urlRuleAdd');
        const excludeEl = document.getElementById('urlRuleExclude');
        if (includeEl) includeEl.value = joinSelectors(rules.include_selectors);
        if (addEl) addEl.value = joinSelectors(rules.add_selectors);
        if (excludeEl) excludeEl.value = joinSelectors(rules.exclude_selectors);
    } catch (e) {
        setUrlRuleStatus('取得に失敗しました', true);
    }
}

async function saveUrlRuleDialog() {
    if (!pdfName) return;
    const includeEl = document.getElementById('urlRuleInclude');
    const addEl = document.getElementById('urlRuleAdd');
    const excludeEl = document.getElementById('urlRuleExclude');
    const payload = {
        include_selectors: splitSelectors(includeEl ? includeEl.value : ''),
        add_selectors: splitSelectors(addEl ? addEl.value : ''),
        exclude_selectors: splitSelectors(excludeEl ? excludeEl.value : ''),
    };

    setUrlRuleStatus('保存中...');
    try {
        const res = await fetch(`/api/url_book/site_rules/${encodePdfNamePath(pdfName)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status !== 'ok') {
            setUrlRuleStatus(data.message || '保存に失敗しました', true);
            return;
        }
        setUrlRuleStatus('保存しました');
    } catch (e) {
        setUrlRuleStatus('保存に失敗しました', true);
    }
}
