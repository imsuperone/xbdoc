// Document Memory Assistant - bindings module
(function (App) {
  "use strict";
  const { $, api, esc, state } = App;

function updatePromptCount() {
  const box = $("bindPrompt");
  const label = $("promptCharCount");
  if (!box || !label) return;
  const n = (box.value || "").length;
  label.textContent = n > 0 ? `已输入 ${n} 字。` : "";
}

function loadExistingSessionSettings(key) {
  const entry = state.bindingsMap[key];
  state.loadedSessionKey = key || "";
  state.promptDirty = false;
  if (!entry) return;

  state.selectedDocIds.clear();
  const docs = entry.docs || [];
  docs.forEach((d) => state.selectedDocIds.add(typeof d === "string" ? d : d.doc_id));
  App.renderDocChips();

  const promptEl = $("bindPrompt");
  if (promptEl) promptEl.value = entry.prompt || "";
  updatePromptCount();

  const shieldVal = entry.shield ? "on" : "off";
  setShieldChoice(shieldVal);

  const forceVal = entry.force_system_prompt ? "on" : "off";
  setForceChoice(forceVal);

  let modeVal = "none";
  if (entry.mode === "system" || entry.mode === "workspace" || entry.mode === "reference" || entry.mode === "none") {
    modeVal = entry.mode;
  }
  _applyDocMode(modeVal);
}

function initDocMode() {
  const group = $("docModeGroup");
  if (!group) return;

  group.addEventListener("click", (e) => {
    const btn = e.target.closest(".segmented-choice-btn");
    if (!btn) return;
    setDocMode(btn.dataset.val);
  });
}

function setDocMode(val) {
  if (state.selectedDocIds.size === 0) {
    App.showToast("请先选择需要绑定的文档，再设置生效模式。");
    return;
  }
  _applyDocMode(val);
}

function _applyDocMode(val) {
  if (val === "system" || val === "workspace" || val === "reference" || val === "none") {
    state.currentDocMode = val;
  } else {
    state.currentDocMode = "none";
  }
  const group = $("docModeGroup");
  if (!group) return;

  group.querySelectorAll(".segmented-choice-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.val === state.currentDocMode);
  });
}

function initForceChoice() {
  const sw = $("forceSwitchToggle");
  if (sw) {
    sw.addEventListener("change", () => {
      setForceChoice(sw.checked ? "on" : "off");
    });
  }
}

function setForceChoice(val) {
  state.currentForcePrompt = val === "on";
  const sw = $("forceSwitchToggle");
  if (sw) sw.checked = state.currentForcePrompt;
}

function initShieldChoice() {
  const sw = $("shieldSwitchToggle");
  if (sw) {
    sw.addEventListener("change", () => {
      setShieldChoice(sw.checked ? "on" : "off");
    });
  }
}

function setShieldChoice(val) {
  state.currentShield = val === "on" ? "on" : "off";
  const sw = $("shieldSwitchToggle");
  if (sw) sw.checked = state.currentShield === "on";
}

function initBindingForm() {
  const resetBtn = $("resetBindFormBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      const sk = $("sessionKey");
      const bp = $("bindPrompt");
      if (sk) sk.value = "";
      if (bp) bp.value = "";
      state.loadedSessionKey = "";
      state.promptDirty = false;
      updatePromptCount();
      state.selectedDocIds.clear();
      App.renderDocChips();
      setShieldChoice("off");
      setForceChoice("off");
      _applyDocMode("none");
      App.renderGroupSwitchTable();
      App.showToast("表单内容已清空。");
    });
  }

  const saveBtn = $("saveBindBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      const input = $("sessionKey");
      let key = input ? input.value.trim() : "";
      if (!key) {
        App.showToast("请填写或选择目标会话标识（例如 group:123456）。");
        if (input) input.focus();
        return;
      }

      if (/^\d{5,}$/.test(key)) {
        // 纯数字：与选择载入共用 App.claimBindingKey（审计 #5）——已有绑定按后缀精确认领
        // （群聊优先），都没有默认补 group: 前缀；后端还会按 seen 再补限定
        key = App.claimBindingKey(key, { claimPrefix: "group:" });
        input.value = key;
      }

      const ids = Array.from(state.selectedDocIds);
      const promptEl = $("bindPrompt");
      // 未动过提示词框时沿用该会话已有提示词，防止手填Key把别的群/旧值覆盖掉；
      // 只有亲手改过才按框内值保存（含清空）。
      let prompt;
      if (state.promptDirty || !state.bindingsMap[key]) {
        prompt = promptEl ? promptEl.value.trim() : "";
      } else {
        const curText = promptEl ? promptEl.value.trim() : "";
        const storedText = (state.bindingsMap[key].prompt || "").trim();
        prompt = curText !== storedText ? curText : storedText;
      }
      const shield = state.currentShield === "on";
      // 模式只提交表单所选（审计 #4）：「无文档⇒none」的回落只在 store._effective_mode
      // 一处（save_binding_payload 落盘前强制），前端不再复写第二份规则
      const mode = state.currentDocMode || "none";
      const forceSys = state.currentForcePrompt;

      try {
        // save 响应即渲染（审计 #2）：回包 entry 与 GET /bindings 同源，直接更新本地映射
        // → renderBindings()，删除「保存→丢弃→重拉」的 App.loadBindings()
        const res = await api.post("bindings/save", {
          session_key: key,
          doc_ids: ids,
          prompt: prompt,
          shield: shield,
          mode: mode,
          force_system_prompt: forceSys,
        });
        App.showToast("会话绑定与配置已保存。");
        state.loadedSessionKey = key;
        state.promptDirty = false;
        const sk = (res && res.session_key) || key;
        if (res && res.session_key) {
          if (res.entry) {
            state.bindingsMap[sk] = res.entry;
          } else {
            // 空壳被后端 prune（entry=null）：与整表重拉口径一致，从列表删键
            delete state.bindingsMap[sk];
          }
        }
        renderBindings();
        // 群建议框的「已绑定」标记来自服务端（/groups 合并 bindings），state.groupsCache 是
        // 服务端快照且 focus 时非空即复用不重查——这里刷新它保证建议框状态正确，保留
        await App.searchGroups("");
      } catch (err) {
        App.showToast("配置保存失败：" + err.message);
      }
    });
  }
}

function renderBindings() {
  App.renderGroupSwitchTable();
  const container = $("bindingList");
  if (!container) return;

  const allKeys = Object.keys(state.bindingsMap);

  // Compute Shield counts (Only On vs Off)
  let onCount = 0;
  let offCount = 0;

  allKeys.forEach((k) => {
    if (Boolean((state.bindingsMap[k] || {}).shield)) onCount++;
    else offCount++;
  });

  const cAll = $("countAll");
  const cOn = $("countShieldOn");
  const cOff = $("countShieldOff");
  if (cAll) cAll.textContent = allKeys.length;
  if (cOn) cOn.textContent = onCount;
  if (cOff) cOff.textContent = offCount;

  // Filter keys
  const filteredKeys = allKeys.filter((k) => {
    const sh = Boolean((state.bindingsMap[k] || {}).shield);
    if (state.currentBindingFilter === "shield_on") return sh === true;
    if (state.currentBindingFilter === "shield_off") return sh === false;
    return true;
  });

  if (!allKeys.length) {
    container.innerHTML = `
      <div class="empty-state">
        <h3>当前暂无已绑定的会话</h3>
        <p>可在上方选择群聊与文档完成绑定，亦可在群聊中发送 /xbdoc bind 指令进行快捷绑定。</p>
      </div>`;
    return;
  }

  if (!filteredKeys.length) {
    container.innerHTML = `
      <div class="empty-state">
        <h3>未找到符合筛选条件的会话</h3>
        <p>当前筛选条件下暂无匹配记录，可点击“全部会话”查看所有记录。</p>
      </div>`;
    return;
  }

  container.innerHTML = filteredKeys.map((k) => {
    const raw = state.bindingsMap[k] || {};
    const docs = raw.docs || [];
    const prompt = raw.prompt || "";
    const isShield = Boolean(raw.shield);
    const shieldClass = isShield ? "shield-badge-on" : "shield-badge-off";
    const shieldTag = isShield ? "屏蔽已开启（清空原人格）" : "屏蔽已关闭（保留原人格）";

    const curMode = raw.mode === "system" ? "system" : (raw.mode === "workspace" ? "workspace" : (raw.mode === "reference" ? "reference" : "none"));

    // Session Name display（私聊显示昵称/私聊 UID，不与群混淆）
    const isPrivateSession = raw.kind === "private" || k.startsWith("private:");
    const groupDisplayName = raw.group_name
      ? raw.group_name
      : (raw.gid ? `${isPrivateSession ? "私聊" : "群聊"} ${raw.gid}` : k);

    return `
      <div class="binding-card" data-key="${esc(k)}">
        <div class="binding-card-meta">
          <div class="binding-card-key">
            <span class="binding-group-name">${esc(groupDisplayName)}</span>
            <span class="badge-pill id-badge">${esc(k)}</span>
          </div>
          <div class="binding-card-docs">
            ${docs.length ? docs.map((d) => `<span class="doc-tag">${esc(d.filename || d.doc_id || d)}</span>`).join("") : '<span class="helper">暂无绑定文档</span>'}
            ${raw.force_system_prompt ? '<span class="badge-pill" style="background:#fee2e2; color:#991b1b; font-weight:700; border:1px solid #f87171;">强制唯一系统提示词</span>' : ''}
            <span class="badge-pill ${shieldClass}">${esc(shieldTag)}</span>
            ${prompt ? `<span class="badge-pill" style="background:var(--m3-status-purple-bg); color:var(--m3-status-purple);">专属提示词（共${prompt.length}字）</span>` : ''}
          </div>
          <div class="mode-select-row">
            <span style="font-size:12px; font-weight:600; color:var(--m3-sys-color-outline); margin-right:4px;">生效模式：</span>
            ${docs.length ? `
              <button class="mode-btn-pill ${curMode === 'none' ? 'active' : ''}" data-act="set-mode" data-mode="none" data-key="${esc(k)}" type="button">不注入</button>
              <button class="mode-btn-pill ${curMode === 'reference' ? 'active' : ''}" data-act="set-mode" data-mode="reference" data-key="${esc(k)}" type="button">仅作参考</button>
              <button class="mode-btn-pill ${curMode === 'system' ? 'active' : ''}" data-act="set-mode" data-mode="system" data-key="${esc(k)}" type="button">强制系统提示词</button>
              <button class="mode-btn-pill ${curMode === 'workspace' ? 'active' : ''}" data-act="set-mode" data-mode="workspace" data-key="${esc(k)}" type="button">工作区模式</button>
            ` : `
              <span class="helper" style="font-size:12px;">（当前未绑定文档，生效模式不可用，仅专属系统提示词生效）</span>
            `}
          </div>
        </div>
        <div class="binding-card-actions">
          <button class="m3-btn m3-btn-tonal m3-btn-sm" data-act="edit" data-key="${esc(k)}" type="button">载入编辑</button>
          <button class="m3-btn m3-btn-danger m3-btn-sm" data-act="unbind" data-key="${esc(k)}" type="button">解绑</button>
        </div>
      </div>
    `;
  }).join("");
}

function initShieldFilter() {
  const group = $("shieldFilterGroup");
  if (!group) return;

  group.addEventListener("click", (e) => {
    const chip = e.target.closest(".shield-filter-chip");
    if (!chip) return;
    group.querySelectorAll(".shield-filter-chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    state.currentBindingFilter = chip.dataset.filter || "all";
    renderBindings();
  });
}

function initBindingListEvents() {
  const container = $("bindingList");
  if (!container) return;

  container.addEventListener("click", async (e) => {
    const idBadge = e.target.closest(".id-badge");
    if (idBadge) {
      const card = idBadge.closest(".binding-card");
      const sk = card ? card.dataset.key : "";
      if (sk) {
        if (await App._copyText(sk)) {
          App.showToast(`会话标识已复制：${sk}`);
        } else {
          App.showToast(`会话标识为：${sk}`);
        }
      }
      return;
    }

    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    const key = btn.dataset.key;
    if (!key) return;

    if (act === "set-mode") {
      const targetMode = btn.dataset.mode;
      const cur = state.bindingsMap[key] || {};
      if (cur.mode === targetMode) return;

      const modeLabels = {
        system: "已切换至强制遵守文档（系统提示词）模式。",
        workspace: "已切换至模拟工作区模式。",
        reference: "已切换至仅作参考资料模式。",
        none: "已切换至无（不注入文档）模式。",
      };

      try {
        const res = await api.post("bindings/save", {
          session_key: key,
          doc_ids: (cur.docs || []).map((d) => (typeof d === "string" ? d : d.doc_id)),
          prompt: cur.prompt || "",
          shield: Boolean(cur.shield),
          force_system_prompt: Boolean(cur.force_system_prompt),
          mode: targetMode,
        });
        App.showToast(modeLabels[targetMode] || "模式已更新");
        const sk = (res && res.session_key) || key;
        if (res && res.entry) state.bindingsMap[sk] = res.entry;
        renderBindings();
      } catch (err) {
        App.showToast("生效模式切换失败：" + err.message);
      }
      return;
    }

    if (act === "edit") {
      const input = $("sessionKey");
      if (input) {
        input.value = key;
        loadExistingSessionSettings(key);
        App.renderGroupSwitchTable();
        window.scrollTo({ top: 180, behavior: "smooth" });
        App.showToast("会话配置已载入。");
      }
    } else if (act === "unbind") {
      if (!(await App.uiConfirm(`确定解除 ${key} 的全部绑定与会话配置吗？该群提示词、模式与开关将一并重置。`, "解绑确认"))) return;
      try {
        App.showToast(`正在解除 ${key} 的文档绑定与相关配置，请稍候……`);
        // 全空字段 + ignore_history:false：后端按空壳 prune 规则直接删除条目（恢复出厂）
        const res = await api.post("bindings/save", {
          session_key: key,
          doc_ids: [],
          prompt: "",
          shield: false,
          force_system_prompt: false,
          ignore_history: false,
        });
        // 如果当前输入框恰好载入了该群，同步清空表单已勾选文档并禁用模式
        const curInputKey = ($("sessionKey")?.value || "").trim();
        if (curInputKey === key) {
          state.selectedDocIds.clear();
          App.renderDocChips();
        }
        App.showToast(`已解除 ${key} 的全部文档绑定。`);
        const sk = (res && res.session_key) || key;
        delete state.bindingsMap[key];
        if (res && res.entry) state.bindingsMap[sk] = res.entry;
        else delete state.bindingsMap[sk];
        renderBindings();
        await App.searchGroups("");
      } catch (err) {
        App.showToast("绑定解除失败：" + err.message);
      }
    }
  });
}

  App.updatePromptCount = updatePromptCount;
  App.loadExistingSessionSettings = loadExistingSessionSettings;
  App.initDocMode = initDocMode;
  App.initForceChoice = initForceChoice;
  App.setForceChoice = setForceChoice;
  App.initShieldChoice = initShieldChoice;
  App.setShieldChoice = setShieldChoice;
  App.initBindingForm = initBindingForm;
  App.renderBindings = renderBindings;
  App.initShieldFilter = initShieldFilter;
  App.initBindingListEvents = initBindingListEvents;
})(window.DocMemoryApp = window.DocMemoryApp || {});
