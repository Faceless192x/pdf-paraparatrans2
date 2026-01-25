/** 画面に対するショートカットキーを */

HotkeyMapper.map("ArrowUp", () => moveCurrentParagraphUp(false), { description: "パラグラフを移動(上)"});
HotkeyMapper.map("ArrowDown", () => moveCurrentParagraphDown(false), { description: "パラグラフを移動(下)"});
HotkeyMapper.map("Shift+ArrowUp", () => moveCurrentParagraphUp(true), { description: "選択しながら移動(上)"});
HotkeyMapper.map("Shift+ArrowDown", () => moveCurrentParagraphDown(true), { description: "選択しながら移動(下)"});

HotkeyMapper.map("Home", () => setCurrentParagraph(0, false, { scrollBehavior: 'auto' }), { description: "先頭パラグラフ" });
HotkeyMapper.map("End", () => {
    const paragraphs = (typeof getAllParagraphs === 'function') ? getAllParagraphs() : [];
    if (!paragraphs || paragraphs.length === 0) return;
    setCurrentParagraph(paragraphs.length - 1, false, { scrollBehavior: 'auto' });
}, { description: "末尾パラグラフ" });

HotkeyMapper.map("Ctrl+ArrowUp", () => focusNearestHeading(-1), { description: "前の見出し"});
HotkeyMapper.map("Ctrl+ArrowDown", () => focusNearestHeading(1), { description: "次の見出し"});
HotkeyMapper.map("Ctrl+Shift+ArrowUp", selectUntilPreviousHeading, { description: "前の見出しまで選択"});
HotkeyMapper.map("Ctrl+Shift+ArrowDown", selectUntilNextHeading, { description: "次の見出しまで選択"});

HotkeyMapper.map("ArrowLeft", prevPage, { description: "前のページ" });
HotkeyMapper.map("ArrowRight", nextPage, { description: "次のページ" });
HotkeyMapper.map("Ctrl+ArrowLeft", prevPage, { description: "前のページ" });
HotkeyMapper.map("Ctrl+ArrowRight", nextPage, { description: "次のページ" });
HotkeyMapper.map("Ctrl+Shift+ArrowLeft", prevPage, { description: "前のページ" });
HotkeyMapper.map("Ctrl+Shift+ArrowRight", nextPage, { description: "次のページ" });

HotkeyMapper.map("/", focusPageNumberInput, { description: "ページ番号へフォーカス", useCapture: true });

// パラグラフに対する編集はAltキー
//moveSelectedByOffset
HotkeyMapper.map("Alt+0", () => updateBlockTagForSelected("p"), { description: "タグ:p", useCapture : true });
HotkeyMapper.map("Alt+1", () => updateBlockTagForSelected("h1"), { description: "タグ:h1", useCapture : true });
HotkeyMapper.map("Alt+2", () => updateBlockTagForSelected("h2"), { description: "タグ:h2", useCapture : true });
HotkeyMapper.map("Alt+3", () => updateBlockTagForSelected("h3"), { description: "タグ:h3", useCapture : true });
HotkeyMapper.map("Alt+4", () => updateBlockTagForSelected("h4"), { description: "タグ:h4", useCapture : true });
HotkeyMapper.map("Alt+5", () => updateBlockTagForSelected("h5"), { description: "タグ:h5", useCapture : true });
HotkeyMapper.map("Alt+6", () => updateBlockTagForSelected("h6"), { description: "タグ:h6", useCapture : true });
HotkeyMapper.map("Alt+7", () => updateBlockTagForSelected("header"), { description: "タグ:header", useCapture : true });
HotkeyMapper.map("Alt+8", () => updateBlockTagForSelected("footer"), { description: "タグ:footer", useCapture : true });
HotkeyMapper.map("Alt+9", () => updateBlockTagForSelected("remove"), { description: "タグ:remove", useCapture : true });
HotkeyMapper.map("Alt+L", () => updateBlockTagForSelected("li"), { description: "タグ:li", useCapture : true });
HotkeyMapper.map("Alt+T", () => updateBlockTagForSelected("tr"), { description: "タグ:tr", useCapture : true });
HotkeyMapper.map("Alt+H", () => updateBlockTagForSelected("th"), { description: "タグ:th", useCapture : true });

HotkeyMapper.map("Alt+.", toggleGroupSelectedParagraphs, { description: "グループ化/解除" });
HotkeyMapper.map("Alt++", toggleJoinForSelected, { description: "パラグラフ結合/解除" });
HotkeyMapper.map("Alt+;", toggleJoinForSelected, { description: "パラグラフ結合/解除" });
HotkeyMapper.map("Ctrl+Alt++", joinParagraphs, { description: "2.連結", useCapture: true });

HotkeyMapper.map("Alt+N", () => updateTransStatusForSelected("none"), { description: "ステータス:none", useCapture : true });
HotkeyMapper.map("Alt+A", () => updateTransStatusForSelected("auto"), { description: "ステータス:auto", useCapture : true });
HotkeyMapper.map("Alt+D", () => updateTransStatusForSelected("draft"), { description: "ステータス:draft", useCapture : true });
HotkeyMapper.map("Alt+F", () => updateTransStatusForSelected("fixed"), { description: "ステータス:fixed", useCapture : true });

HotkeyMapper.map("Alt+J", () => DictPopup.show(), { description: "対訳辞書登録", useCapture : true });
HotkeyMapper.map("Alt+C", resetTranslationForSelected, { description: "翻訳クリア", useCapture : true });

HotkeyMapper.map("Alt+/", translateCurrentParagraph, { description: "パラグラフを翻訳", useCapture: true, allowInInput: true });

HotkeyMapper.map("Alt+ArrowUp", () => moveSelectedByOffset(-1), { description: "選択（なければカレント）を上へ"});
HotkeyMapper.map("Alt+ArrowDown", () => moveSelectedByOffset(1), { description: "選択（なければカレント）を下へ"});
HotkeyMapper.map("Ctrl+Alt+ArrowUp", moveSelectedBelowPreviousHeading, { description: "選択（なければカレント）を前の見出しの下に移動" });
HotkeyMapper.map("Ctrl+Alt+ArrowDown", moveSelectedAboveNextHeading, { description: "選択（なければカレント）を次の見出しの上に移動" });

// Alt+Home/End: 先頭/末尾へ移動 + block_tag を header/footer に
HotkeyMapper.map("Alt+Home", () => {
    moveSelectedBefore(0);
    updateBlockTagForSelected("header");
}, { description: "選択（なければカレント）を先頭へ + header", useCapture : true });

HotkeyMapper.map("Alt+End", () => {
    moveSelectedAfter(9999);
    updateBlockTagForSelected("footer");
}, { description: "選択（なければカレント）を末尾へ + footer", useCapture : true });


// Ctrl+Alt+Home/End: カレント段落の style + Y範囲で文書全体に header/footer を適用
HotkeyMapper.map("Ctrl+Alt+Home", () => {
    void applyCurrentParagraphStyleYToAll("header");
}, { description: "(要確認) カレントと同style+Y範囲を全体header", useCapture: true });

HotkeyMapper.map("Ctrl+Alt+End", () => {
    void applyCurrentParagraphStyleYToAll("footer");
}, { description: "(要確認) カレントと同style+Y範囲を全体footer", useCapture: true });

HotkeyMapper.map("F2", () => toggleEditUICurrent(), { description: "編集切り替え", useCapture : true });

//

HotkeyMapper.map("Escape", resetSelection, { description: "選択解除" });
HotkeyMapper.map("Ctrl+S", saveCurrentPageOrder, { description: "構造保存" });
HotkeyMapper.map("Ctrl+Alt+/", transPage, { description: "ページ翻訳", useCapture: true });
HotkeyMapper.map("PageUp", rollUp, { description: "スクロールアップ" });
HotkeyMapper.map("PageDown", rollDown, { description: "スクロールダウン" });
HotkeyMapper.map("RollUp", rollUp, { description: "スクロールアップ" });
HotkeyMapper.map("RollDown", rollDown, { description: "スクロールダウン" });


function rollUp() {
    const srcPanel = document.getElementById('srcPanel'); // srcPanelの要素を取得
    srcPanel.focus();
    if (srcPanel) {
        srcPanel.scrollBy({ top: -srcPanel.clientHeight, behavior: 'smooth' }); // 1画面分上にスクロール
    }
}

function rollDown() {
    const srcPanel = document.getElementById('srcPanel'); // srcPanelの要素を取得
    srcPanel.focus();
    if (srcPanel) {
        srcPanel.scrollBy({ top: srcPanel.clientHeight, behavior: 'smooth' }); // 1画面分下にスクロール
    }
}

function focusPageNumberInput() {
    const el = document.getElementById('pageInput');
    if (!el) return;

    el.focus();
    try {
        if (typeof el.select === 'function') el.select();
        else if (typeof el.setSelectionRange === 'function') {
            const v = String(el.value ?? "");
            el.setSelectionRange(0, v.length);
        }
    } catch (e) {
        // type=number 等で選択操作が不可の場合があるため無視
    }
}

function moveCurrentParagraphUp(shiftKey) {
    moveCurrentParagraphBy(-1, shiftKey);
}
function moveCurrentParagraphDown(shiftKey) {
    moveCurrentParagraphBy(1, shiftKey);
}

function toggleGroupSelectedParagraphsUp() {
    toggleGroupSelectedParagraphs(-1);
}
function toggleGroupSelectedParagraphsDown() {
    toggleGroupSelectedParagraphs(1);
}

function translateCurrentParagraph() {
    const currentDiv = document.querySelector('.paragraph-box.current');
    if (!currentDiv) return;

    const idStr = (currentDiv.id || '').replace('paragraph-', '');
    const paragraphDict = bookData?.pages?.[currentPage]?.paragraphs?.[idStr];
    if (!paragraphDict) return;

    // 翻訳入力は src_replaced(置換後) のみを使用。
    // 空の場合は空のまま翻訳APIへ渡す（フォールバックしない）。
    if (typeof transParagraph !== 'function') {
        console.warn('transParagraph is not defined');
        return;
    }
    transParagraph(paragraphDict, currentDiv);
}


async function applyCurrentParagraphStyleYToAll(action) {
    try {
        const currentDiv = document.querySelector('.paragraph-box.current');
        if (!currentDiv) return;

        const idStr = (currentDiv.id || '').replace('paragraph-', '');
        const paragraphDict = bookData?.pages?.[currentPage]?.paragraphs?.[idStr];
        if (!paragraphDict) return;

        const targetStyle = paragraphDict.base_style;
        const bbox = paragraphDict.bbox;
        if (!targetStyle || !bbox || !Array.isArray(bbox) || bbox.length < 4) {
            alert("カレント段落の style または bbox が取得できません。");
            return;
        }

        // bbox = [x0, y0, x1, y1]
        const eps = 1.0;
        let y0 = Number(bbox[1]);
        let y1 = Number(bbox[3]);
        if (!Number.isFinite(y0) || !Number.isFinite(y1)) {
            alert("カレント段落の bbox(y0/y1) が不正です。");
            return;
        }
        if (y0 > y1) {
            const tmp = y0;
            y0 = y1;
            y1 = tmp;
        }
        const rangeY0 = y0 - eps;
        const rangeY1 = y1 + eps;

        // 対象件数を数えて確認（全体一括のため必須）
        let count = 0;
        for (const page of Object.values(bookData?.pages || {})) {
            for (const p of Object.values(page?.paragraphs || {})) {
                if (p.base_style !== targetStyle) continue;
                const b = p.bbox;
                if (!b || !Array.isArray(b) || b.length < 4) continue;
                const py0 = Number(b[1]);
                const py1 = Number(b[3]);
                if (!Number.isFinite(py0) || !Number.isFinite(py1)) continue;
                if (rangeY0 <= py0 && py1 <= rangeY1) count++;
            }
        }

        if (count === 0) {
            alert(`対象が見つかりませんでした（style='${targetStyle}', y=${rangeY0.toFixed(1)}..${rangeY1.toFixed(1)}）`);
            return;
        }

        const msg = `文書全体の処理です。\n` +
            `カレント段落と同じ style + Y範囲の段落（${count}件）を '${action}' に更新します。\n` +
            `style='${targetStyle}'\n` +
            `y0=${rangeY0.toFixed(1)}, y1=${rangeY1.toFixed(1)}\n\n` +
            `よろしいですか？`;
        if (!confirm(msg)) return;

        if (typeof taggingByStyleY !== 'function') {
            alert('taggingByStyleY が見つかりません（fetch.js の読み込みを確認してください）');
            return;
        }
        await taggingByStyleY(targetStyle, rangeY0, rangeY1, action);
    } catch (e) {
        console.error('applyCurrentParagraphStyleYToAll error:', e);
        alert('一括更新中にエラーが発生しました。');
    }
}

function onKeyDown(event, divSrc, paragraph, srcText, transText, blockTagSpan) {
    if (event.key === 'Escape' && divSrc.classList.contains('editing')) {
        divSrc.classList.remove('editing');
        srcText.contentEditable = false;
        transText.contentEditable = false;
        divSrc.querySelector('.edit-ui').style.display = 'none';
        divSrc.querySelector('.edit-button').style.visibility = 'visible'; // visibilityを直接操作
        $("#srcParagraphs").sortable("enable");
        divSrc.style.cursor = 'move';

        srcText.innerHTML = paragraph.src_text;
        transText.innerHTML = paragraph.trans_text;
        paragraph.block_tag = blockTagSpan.innerText;

        // 元のtrans_statusに基づいて背景色を復元
        updateEditUiBackground(divSrc, paragraph.trans_status);
    }
}


