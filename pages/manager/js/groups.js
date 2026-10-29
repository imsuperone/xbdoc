// Document Memory Assistant - groups module
(function (App) {
  "use strict";
  const { $, api, esc, state } = App;

async function ensureBindingsLoaded() {
  if (state.bindingsPrefetched) return;
  state.bindingsPrefetched = true;
  try {
    await Promise.all([loadBindings(), searchGroups("")]);
  } catch (e) {}
}

function switchTab(tabId) {
  document.querySelectorAll(".cat-tab").forEach((t) => {
    t.classList.toggle("active", t.getAttribute("data-tab") === tabId);
  });
  document.querySelectorAll(".settings-section").forEach((p) => {
    p.classList.toggle("active", p.getAttribute("data-section") === tabId);
  });
  if (tabId === "tab-bindings") {
    ensureBindingsLoaded();
  }
}

async function loadBindings() {
  try {
    const res = await api.get("bindings");
    // 服务端已做 key 归一与同会话合并（_normalize_bindings），这里直接采用
    state.bindingsMap = res.bindings || {};
    App.renderBindings();
  } catch (e) {
    console.error("[DocMemory] loadBindings error:", e);
    App.showToast("绑定列表获取失败：" + e.message);
  }
}

async function searchGroups(q = "") {
  const mySeq = ++state.suggestSeq;
  try {
    const res = await api.get("groups", q ? { q, limit: 60 } : { limit: 60 });
    if (mySeq !== state.suggestSeq) return null;
    if (!q) {
      state.groupsCache = res.groups || [];
      renderGroupSwitchTable();
    }
    return res.groups || [];
  } catch (e) {
    return mySeq === state.suggestSeq ? [] : null;
  }
}

function renderGroupSwitchTable() {
  const wrap = $("groupSwitchTableWrap");
  if (!wrap) return;

  const searchEl = $("groupTableSearch");
  const kw = searchEl && searchEl.value ? searchEl.value.trim().toLowerCase() : "";
  const curSelKey = ($("sessionKey") && $("sessionKey").value ? $("sessionKey").value.trim() : "");

  // /groups 与 /bindings 的键均为服务端规范化键，按 (kind, gid) 去重合并
  const byDedup = new Map();
  const upsert = (key, kind, gid, name, bound) => {
    if (!gid || /probe|webchat/i.test(gid)) return;
    if (kind === "private" && !/^\d+$/.test(gid)) return;
    const dedupId = `${kind}:${gid}`;
    const prev = byDedup.get(dedupId);
    const entry = state.bindingsMap[key];
    byDedup.set(dedupId, {
      session_key: entry ? key : (prev && prev.bound ? prev.session_key : key),
      gid: gid,
      group_name: name || (prev && prev.group_name) || "",
      kind: kind,
      bound: Boolean(bound || entry || (prev && prev.bound)),
    });
  };

  (state.groupsCache || []).forEach((g) => {
    const key = String(g.session_key || ("group:onebot:" + g.gid));
    const kind = String(g.kind || (key.startsWith("private:") ? "private" : "group"));
    upsert(key, kind, String(g.gid || key.split(":").pop() || ""), String(g.group_name || ""), Boolean(g.bound));
  });
  Object.keys(state.bindingsMap || {}).forEach((key) => {
    const b = state.bindingsMap[key] || {};
    const kind = String(b.kind || (key.startsWith("private:") ? "private" : "group"));
    upsert(key, kind, String(b.gid || key.split(":").pop() || ""), String(b.group_name || ""), true);
  });

  const filtered = Array.from(byDedup.values()).filter((g) => {
    if (!kw) return true;
    return (g.group_name && g.group_name.toLowerCase().includes(kw)) ||
           (g.gid && g.gid.toLowerCase().includes(kw)) ||
           (g.session_key && g.session_key.toLowerCase().includes(kw));
  });

  filtered.sort((a, b) => {
    if (a.bound !== b.bound) return a.bound ? -1 : 1;
    return String(a.gid).localeCompare(String(b.gid));
  });

  if (!filtered.length) {
    wrap.innerHTML = `<div class="empty-state" style="padding:20px 12px;"><p>${kw ? "未找到匹配的群聊或会话" : "暂未获取到群聊列表，可点击右上角「刷新机器人群列表」或在下方输入框直接填写群号"}</p></div>`;
    return;
  }

  const rowsHtml = filtered.map((g) => {
    const isPrivate = g.kind === "private" || g.session_key.startsWith("private:");
    const nameText = g.group_name || ((isPrivate ? "私聊 " : "群聊 ") + (g.gid || g.session_key));
    const isSelected = Boolean(curSelKey && (curSelKey === g.session_key || curSelKey.split(":").pop() === g.gid));
    const boundDot = g.bound ? `<span class="group-bound-dot" title="已配置绑定"></span>` : "";

    return `
      <tr class="${isSelected ? "is-selected" : (g.bound ? "is-enabled" : "")}" data-select-key="${esc(g.session_key)}">
        <td class="group-cell-name" title="${esc(nameText)}">${boundDot}${esc(nameText)}</td>
        <td class="group-cell-id" title="${esc(g.session_key)}">${esc(g.gid || g.session_key)}</td>
        <td class="group-cell-action">
          <button type="button" class="m3-btn ${isSelected ? "primary-btn" : "secondary-btn"} m3-btn-sm" data-select-key="${esc(g.session_key)}">
            ${isSelected ? "已选中" : "选择"}
          </button>
        </td>
      </tr>
    `;
  }).join("");

  wrap.innerHTML = `
    <table class="group-switch-table">
      <thead>
        <tr>
          <th>群聊名称</th>
          <th>群号</th>
          <th class="group-cell-action">操作</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function renderGroupSuggest(list) {
  const box = $("suggestDropdown");
  if (!box) return;

  const cleanList = [];
  const seenDedup = new Set();
  (list || []).forEach((g) => {
    const sk = String(g.session_key || ("group:onebot:" + g.gid));
    const kind = g.kind || (sk.startsWith("private:") ? "private" : "group");
    const gid = String(g.gid || sk.split(":").pop() || "");
    if (!gid || /probe|webchat/i.test(gid)) return;
    const dedup = `${kind}:${gid}`;
    if (seenDedup.has(dedup)) return;
    seenDedup.add(dedup);
    cleanList.push(Object.assign({}, g, { session_key: sk, gid: gid }));
  });

  if (!cleanList.length) {
    box.classList.remove("open");
    box.innerHTML = "";
    return;
  }

  box.innerHTML = cleanList.slice(0, 15).map((g) => {
    const isPrivate = g.kind === "private";
    const firstLetter = (g.group_name || g.gid || (isPrivate ? "私" : "群")).charAt(0).toUpperCase();
    return `
      <div class="suggest-card" data-key="${esc(g.session_key || ('group:onebot:' + g.gid))}">
        <div style="display:flex; align-items:center;">
          <div class="suggest-avatar">${esc(firstLetter)}</div>
          <div class="suggest-info">
            <strong>${esc(g.group_name || ((isPrivate ? "私聊 " : "群聊 ") + g.gid))}</strong>
            <span>${isPrivate ? "私聊 UID" : "群号"}: ${esc(g.gid)} ${g.msg_count ? ' · ' + esc(g.msg_count) + '条发言' : ''}</span>
          </div>
        </div>
        ${g.bound ? '<span class="badge-pill" style="background:var(--m3-sys-color-primary-container); color:var(--m3-sys-color-primary); font-weight:600;">已绑定</span>' : '<span class="badge-pill">选择</span>'}
      </div>
    `;
  }).join("");

  box.classList.add("open");
}

function initGroupSuggest() {
  const input = $("sessionKey");
  const box = $("suggestDropdown");
  const fetchBtn = $("fetchBotGroupsBtn");
  const tableSearch = $("groupTableSearch");
  const tableWrap = $("groupSwitchTableWrap");
  if (!input || !box) return;

  function selectSessionKey(key) {
    if (!key) return;
    input.value = key;
    box.classList.remove("open");
    resetSessionControls();
    state.selectedDocIds.clear();
    App.renderDocChips();
    App.loadExistingSessionSettings(key);
    renderGroupSwitchTable();
  }

  if (tableSearch) {
    tableSearch.addEventListener("input", () => renderGroupSwitchTable());
  }

  if (tableWrap) {
    tableWrap.addEventListener("click", (e) => {
      const rowOrBtn = e.target.closest("[data-select-key]");
      if (!rowOrBtn) return;
      const key = rowOrBtn.getAttribute("data-select-key");
      if (key) {
        selectSessionKey(key);
        App.showToast(`已选中会话：${key}`);
      }
    });
  }

  if (fetchBtn) {
    fetchBtn.addEventListener("click", async () => {
      const originalHtml = fetchBtn.innerHTML;
      fetchBtn.disabled = true;
      fetchBtn.innerHTML = `<span>正在获取……</span>`;
      App.showToast("正在从机器人适配器获取群聊列表，请稍候……", 4000);

      try {
        const res = await api.post("groups/fetch");

        const list = res.groups || [];
        const newCount = res.new_fetched !== undefined ? res.new_fetched : list.length;
        const dbg = res.debug || {};
        const bad = (dbg.details || []).filter((d) => !/: ok\(/.test(d)).slice(0, 2);
        const reason = `（找到适配器 ${dbg.bots ?? "?"} 个${bad.length ? "；" + bad.join("；") : ""}）`;
        if (list.length) {
          state.groupsCache = list;
        } else {
          const g = await searchGroups("");
          if (g) state.groupsCache = g;
        }
        renderGroupSwitchTable();

        if (newCount > 0) {
          App.showToast(`已从适配器获取 ${newCount} 个群聊（共收录 ${state.groupsCache.length} 个）。`, 3500);
        } else if (state.groupsCache.length > 0) {
          App.showToast(`群列表已刷新（当前共列出 ${state.groupsCache.length} 个已知群聊）。`, 3500);
        } else {
          App.showToast(`未获取到新的群聊${reason}。协议不支持时，在群聊中发送一条消息即可自动记录，或手动填写 group:群号。`, 6000);
        }
      } catch (err) {
        App.showToast("群聊列表获取失败：" + err.message);
      } finally {
        fetchBtn.disabled = false;
        fetchBtn.innerHTML = originalHtml;
      }
    });
  }

  box.addEventListener("click", (e) => {
    const card = e.target.closest(".suggest-card");
    if (!card) return;
    selectSessionKey(card.dataset.key);
  });

  function resetSessionControls() {
    const bp = $("bindPrompt");
    if (bp) bp.value = "";
    state.promptDirty = false;
    App.setShieldChoice("off");
    App.setForceChoice("off");
    state.currentDocMode = "none";
    const group = $("docModeGroup");
    if (group) {
      group.querySelectorAll(".segmented-choice-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.val === "none");
      });
    }
  }

  input.addEventListener("change", () => {
    const v = input.value.trim();
    if (!v || v === state.loadedSessionKey) return;
    const hit = App.claimBindingKey(v);
    if (hit) {
      input.value = hit;
      App.loadExistingSessionSettings(hit);
    } else {
      state.loadedSessionKey = v;
      resetSessionControls();
    }
    renderGroupSwitchTable();
  });

  const promptEl = $("bindPrompt");
  if (promptEl) {
    promptEl.addEventListener("input", () => { state.promptDirty = true; App.updatePromptCount(); });
  }

  input.addEventListener("input", () => {
    clearTimeout(state.suggestTimer);
    const q = input.value.trim();
    if (!q) {
      box.classList.remove("open");
      renderGroupSwitchTable();
      return;
    }
    if (/^(?:group|private):(?:[A-Za-z0-9_\-]+:)?\d+$/.test(q)) {
      box.classList.remove("open");
      renderGroupSwitchTable();
      return;
    }
    state.suggestTimer = setTimeout(async () => {
      const list = await searchGroups(q);
      if (list) renderGroupSuggest(list);
    }, 220);
  });

  const showList = async () => {
    const q = input.value.trim();
    if (!q || /^(?:group|private):(?:[A-Za-z0-9_\-]+:)?\d+$/.test(q)) return;
    const list = await searchGroups(q);
    if (list) renderGroupSuggest(list);
  };

  input.addEventListener("focus", showList);
  input.addEventListener("click", showList);

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#sessionKey") && !e.target.closest("#suggestDropdown") && !e.target.closest("#fetchBotGroupsBtn")) {
      box.classList.remove("open");
    }
  });
}

  App.ensureBindingsLoaded = ensureBindingsLoaded;
  App.switchTab = switchTab;
  App.loadBindings = loadBindings;
  App.searchGroups = searchGroups;
  App.renderGroupSwitchTable = renderGroupSwitchTable;
  App.initGroupSuggest = initGroupSuggest;
})(window.DocMemoryApp = window.DocMemoryApp || {});
