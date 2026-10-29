// Document Memory Assistant - reader module
(function (App) {
  "use strict";
  const { $, api, state } = App;

function readerCacheSet(k, v) {
  if (state.readerCache.size >= 60) {
    const oldest = state.readerCache.keys().next().value;
    state.readerCache.delete(oldest);
  }
  state.readerCache.set(k, v);
}

async function openReader(docId, chunk = 1) {
  state.currentReaderDoc = docId;
  state.currentReaderChunk = chunk;
  const modal = $("readerModal");
  if (!modal) return;

  modal.classList.add("open");

  const titleEl = $("readerTitle");
  const subEl = $("readerSub");
  const textEl = $("readerText");
  const prevBtn = $("prevChunkBtn");
  const nextBtn = $("nextChunkBtn");

  if (titleEl) titleEl.textContent = "正在加载文档切片……";
  if (subEl) subEl.textContent = `切片 ${chunk}`;
  if (textEl) textEl.textContent = "正在从服务器获取文档片段，请稍候……";

  const cacheKey = `${docId}:${chunk}`;
  const applyRes = (res) => {
    state.currentReaderTotal = res.total || 1;
    state.currentReaderChunk = res.chunk || chunk;
    if (titleEl) titleEl.textContent = res.meta?.filename || res.filename || docId;
    if (subEl) subEl.textContent = `切片 ${res.chunk} / ${res.total} (共 ${res.meta?.text_len || 0} 字)`;
    if (textEl) textEl.textContent = res.preview || "该切片暂无文本内容。";

    if (prevBtn) prevBtn.disabled = state.currentReaderChunk <= 1;
    if (nextBtn) nextBtn.disabled = state.currentReaderChunk >= state.currentReaderTotal;
    // 预取下一片：翻页更快，失败静默
    const next = state.currentReaderChunk + 1;
    if (next <= state.currentReaderTotal && !state.readerCache.has(`${docId}:${next}`)) {
      api.get("docs/content", { doc_id: docId, chunk: next }).then(
        (r) => readerCacheSet(`${docId}:${next}`, r),
        () => {}
      );
    }
  };

  const cached = state.readerCache.get(cacheKey);
  if (cached) {
    applyRes(cached);
    return;
  }
  try {
    const res = await api.get("docs/content", { doc_id: docId, chunk });
    readerCacheSet(cacheKey, res);
    // 用户已翻到别处则丢弃本次结果，避免乱序覆盖
    if (state.currentReaderDoc !== docId || state.currentReaderChunk !== chunk) return;
    applyRes(res);
  } catch (err) {
    if (textEl) textEl.textContent = "文档切片读取失败：" + err.message;
  }
}

function closeReader() {
  const modal = $("readerModal");
  if (modal) modal.classList.remove("open");
}

function initReaderEvents() {
  const closeBtn = $("closeReaderBtn");
  if (closeBtn) closeBtn.addEventListener("click", closeReader);

  const modal = $("readerModal");
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeReader();
    });
  }

  const prevBtn = $("prevChunkBtn");
  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      if (state.currentReaderDoc && state.currentReaderChunk > 1) {
        openReader(state.currentReaderDoc, state.currentReaderChunk - 1);
      }
    });
  }

  const nextBtn = $("nextChunkBtn");
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      if (state.currentReaderDoc && state.currentReaderChunk < state.currentReaderTotal) {
        openReader(state.currentReaderDoc, state.currentReaderChunk + 1);
      }
    });
  }

  const copyBtn = $("copyChunkBtn");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const textEl = $("readerText");
      const text = textEl ? textEl.textContent : "";
      if (!text) return;
      // 统一走 App._copyText（clipboard → execCommand 兜底），不再维护第二套回退链
      if (await App._copyText(text)) {
        App.showToast("切片文本已复制至剪贴板。");
      } else {
        App.showToast("文本复制失败，请手动选取并复制。");
      }
    });
  }

  const bindBtn = $("bindFromReaderBtn");
  if (bindBtn) {
    bindBtn.addEventListener("click", () => {
      if (state.currentReaderDoc) {
        state.selectedDocIds.add(state.currentReaderDoc);
        App.renderDocChips();
        closeReader();
        App.switchTab("tab-bindings");
        const input = $("sessionKey");
        if (input) input.focus();
        App.showToast("已选择该文档，请指定需要绑定的会话。");
      }
    });
  }
}

  App.openReader = openReader;
  App.initReaderEvents = initReaderEvents;
})(window.DocMemoryApp = window.DocMemoryApp || {});
