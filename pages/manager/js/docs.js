// Document Memory Assistant - docs module
(function (App) {
  "use strict";
  const { $, api, esc, state } = App;

async function loadDocs() {
  try {
    const res = await api.get("docs");
    state.docsList = res.docs || [];
    renderDocs(state.docsList);
    for (const id of Array.from(state.selectedDocIds)) {
      if (!state.docsList.some((d) => d.doc_id === id)) state.selectedDocIds.delete(id);
    }
    renderDocChips();
  } catch (e) {
    console.error("[DocMemory] loadDocs error:", e);
    App.showToast("文档列表获取失败：" + e.message);
  }
}

function renderDocs(list) {
  const container = $("docGrid");
  if (!container) return;

  if (!list.length) {
    container.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <h3>暂无已入库文档</h3>
        <p>可将 .md / .txt / .pdf / .docx 文件拖放至上方区域进行上传</p>
      </div>`;
    return;
  }

  container.innerHTML = list.map((doc) => {
    const suffix = (doc.suffix || "").replace(".", "").toLowerCase();
    let typeClass = "txt";
    let typeLabel = (suffix || "TXT").toUpperCase();
    if (suffix === "md" || suffix === "markdown") {
      typeClass = "md";
    } else if (suffix === "pdf") {
      typeClass = "pdf";
    } else if (suffix === "docx") {
      typeClass = "docx";
    }

    return `
      <div class="doc-card" data-id="${esc(doc.doc_id)}">
        <div class="doc-card-top">
          <div class="doc-type-icon ${typeClass}">${esc(typeLabel)}</div>
          <div class="doc-card-info">
            <div class="doc-card-title" title="${esc(doc.filename)}">${esc(doc.filename)}</div>
            <div class="doc-card-badges">
              <span class="badge-pill id-badge">ID: ${esc(doc.doc_id)}</span>
              <span class="badge-pill">${esc(doc.chunks)} 切片</span>
              <span class="badge-pill">${esc(doc.text_len)} 字</span>
            </div>
          </div>
        </div>
        <div class="doc-card-actions">
          <button class="m3-btn m3-btn-outlined m3-btn-sm" data-act="preview" data-id="${esc(doc.doc_id)}" type="button">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
            预览
          </button>
          <button class="m3-btn m3-btn-tonal m3-btn-sm" data-act="download" data-id="${esc(doc.doc_id)}" type="button">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM17 13l-5 5-5-5h3V9h4v4h3z"/></svg>
            下载
          </button>
          <button class="m3-btn m3-btn-tonal m3-btn-sm" data-act="attach" data-id="${esc(doc.doc_id)}" type="button">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>
            绑定
          </button>
          <button class="m3-btn m3-btn-danger m3-btn-sm" data-act="delete" data-id="${esc(doc.doc_id)}" title="删除文档" type="button">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function initDocGridEvents() {
  const container = $("docGrid");
  if (!container) return;

  container.addEventListener("click", async (e) => {
    const badge = e.target.closest(".id-badge");
    if (badge) {
      const card = badge.closest(".doc-card");
      const did = card ? card.dataset.id : "";
      if (did) {
        if (await App._copyText(did)) {
          App.showToast(`文档 ID 已复制：${did}`);
        } else {
          App.showToast(`文档 ID 为：${did}`);
        }
      }
      return;
    }

    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    e.stopPropagation();

    const act = btn.dataset.act;
    const id = btn.dataset.id;
    if (!id) return;

    if (act === "preview") {
      App.openReader(id, 1);
    } else if (act === "download") {
      try {
        App.showToast("正在下载文档，请稍候……");
        await api.download("docs/download", { doc_id: id });
      } catch (err) {
        App.showToast("文档下载失败：" + err.message);
      }
    } else if (act === "attach") {
      state.selectedDocIds.add(id);
      renderDocChips();
      App.switchTab("tab-bindings");
      const sk = $("sessionKey");
      if (sk) sk.focus();
      App.showToast("已将该文档添加至绑定表单。");
    } else if (act === "delete") {
      if (!(await App.uiConfirm(`确定删除文档 ${id} 吗？相关绑定将同步清理，此操作不可恢复。`, "删除确认"))) return;
      try {
        App.showToast(`正在删除文档（ID：${id}），请稍候……`);
        await api.post("docs/delete", { doc_id: id });
        App.showToast("文档已删除，相关绑定已同步清理。");
        await loadDocs();
        await App.loadBindings();
      } catch (err) {
        App.showToast("文档删除失败：" + err.message);
      }
    }
  });
}

function initDocSearch() {
  const input = $("docSearchInput");
  if (!input) return;

  let timer = null;
  input.addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const q = e.target.value.trim().toLowerCase();
      if (!q) {
        renderDocs(state.docsList);
        return;
      }
      const filtered = state.docsList.filter((d) =>
        (d.filename || "").toLowerCase().includes(q) || (d.doc_id || "").toLowerCase().includes(q)
      );
      renderDocs(filtered);
    }, 150);
  });
}

function initDropzone() {
  const fileInput = $("fileInput");
  const dropzone = $("dropzone");
  const progress = $("uploadProgress");

  if (!fileInput || !dropzone) return;

  // File selected
  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (file) handleUpload(file);
    fileInput.value = "";
  });

  // Drag events
  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("drag-over");
  });

  ["dragleave", "dragend"].forEach((type) => {
    dropzone.addEventListener(type, () => dropzone.classList.remove("drag-over"));
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag-over");
    const file = e.dataTransfer && e.dataTransfer.files ? e.dataTransfer.files[0] : null;
    if (file) handleUpload(file);
  });

  async function handleUpload(file) {
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) {
      App.showToast("文件大小超出 50MB 上限，请拆分后重新上传。");
      return;
    }
    if (progress) progress.style.display = "block";
    App.showToast(`正在上传并处理文件 ${file.name}，请稍候……`, 5000);

    try {
      const res = await api.upload("docs/upload", file);
      if (progress) progress.style.display = "none";
      App.showToast(`文档 ${res.doc?.filename || file.name} 已完成入库。`);
      await loadDocs();
    } catch (err) {
      if (progress) progress.style.display = "none";
      App.showToast("文档上传失败：" + err.message);
    }
  }
}

function renderDocChips() {
  const container = $("docChipsPicker");
  if (!container) return;

  if (!state.docsList.length) {
    container.innerHTML = `<span class="helper">知识库中暂无文档，请先前往文档库完成上传。</span>`;
    return;
  }

  container.innerHTML = state.docsList.map((d) => {
    const isSelected = state.selectedDocIds.has(d.doc_id);
    return `
      <div class="doc-select-chip ${isSelected ? "selected" : ""}" data-id="${esc(d.doc_id)}" role="button" tabindex="0">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <path d="${isSelected ? 'M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z' : 'M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z'}"/>
        </svg>
        <span>${esc(d.filename)}</span>
      </div>
    `;
  }).join("");

  const hasDocs = state.selectedDocIds.size > 0;
  const modeRow = $("docModeRow");
  const modeSub = $("docModeSub");
  if (modeRow) {
    if (hasDocs) {
      modeRow.classList.remove("disabled");
      modeRow.querySelectorAll("button").forEach((b) => b.disabled = false);
      if (modeSub) modeSub.textContent = "设置文档在会话中的角色定位与隔离级别";
    } else {
      modeRow.classList.add("disabled");
      modeRow.querySelectorAll("button").forEach((b) => b.disabled = true);
      if (modeSub) modeSub.textContent = "请先在上方选择需要绑定的文档";
    }
  }
}

function initDocChipsEvents() {
  const container = $("docChipsPicker");
  if (!container) return;

  container.addEventListener("click", (e) => {
    const chip = e.target.closest(".doc-select-chip");
    if (!chip) return;
    const id = chip.dataset.id;
    if (!id) return;

    if (state.selectedDocIds.has(id)) {
      state.selectedDocIds.delete(id);
    } else {
      state.selectedDocIds.add(id);
    }
    renderDocChips();
  });
}

  App.loadDocs = loadDocs;
  App.initDocGridEvents = initDocGridEvents;
  App.initDocSearch = initDocSearch;
  App.initDropzone = initDropzone;
  App.renderDocChips = renderDocChips;
  App.initDocChipsEvents = initDocChipsEvents;
})(window.DocMemoryApp = window.DocMemoryApp || {});
