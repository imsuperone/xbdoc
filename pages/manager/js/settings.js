// Document Memory Assistant - settings module
(function (App) {
  "use strict";
  const { $, api, esc, state } = App;

function initBackupButtons() {
  const exportBtn = $("exportBackupBtn");
  if (exportBtn) {
    exportBtn.addEventListener("click", async () => {
      try {
        App.showToast("正在导出绑定备份，请稍候……");
        const data = await api.get("bindings/export");
        const map = (data && typeof data === "object" && !Array.isArray(data)) ? data : {};
        const blob = new Blob([JSON.stringify(map, null, 2)], { type: "application/json" });
        const dt = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `xbdoc-bindings-${dt.getFullYear()}${pad(dt.getMonth() + 1)}${pad(dt.getDate())}-${pad(dt.getHours())}${pad(dt.getMinutes())}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
        App.showToast(`已导出 ${Object.keys(map).length} 个会话的绑定配置。`);
      } catch (err) {
        App.showToast("备份导出失败：" + err.message);
      }
    });
  }

  const importBtn = $("importBackupBtn");
  const fileEl = $("importBackupFile");
  if (importBtn && fileEl) {
    importBtn.addEventListener("click", () => fileEl.click());
    fileEl.addEventListener("change", async () => {
      const f = fileEl.files[0];
      fileEl.value = "";
      if (!f) return;
      let map;
      try {
        map = JSON.parse(await f.text());
      } catch (e) {
        App.showToast("所选文件并非合法的 JSON 格式。");
        return;
      }
      if (!map || typeof map !== "object" || Array.isArray(map) || !Object.keys(map).length) {
        App.showToast("备份文件中未包含绑定数据。");
        return;
      }
      const n = Object.keys(map).length;
      if (!(await App.uiConfirm(`将从备份导入 ${n} 个会话配置，并合并至现有配置，是否继续？`, "导入确认"))) return;
      const replace = await App.uiConfirm("是否覆盖现有全部配置？选择“覆盖”将替换现有配置，选择“取消”则仅合并新增项。", "覆盖现有配置");
      try {
        const res = await api.post(`bindings/import?mode=${replace ? "replace" : "merge"}`, map);
        const skipped = (res.skipped_docs || []).length;
        App.showToast(`已导入 ${res.applied || 0} 个会话的配置${skipped ? `，其中 ${skipped} 个文档不存在，已跳过` : ""}。`);
        await App.loadBindings();
        await App.searchGroups("");
      } catch (err) {
        App.showToast("备份导入失败：" + err.message);
      }
    });
  }
}

function syncPlatformUI(cfg) {
  if (!cfg) cfg = state.settingsConfig || {};
  const preset = String(cfg.platform_preset || "onebot").trim().toLowerCase();
  const allowed = String(cfg.allowed_platforms !== undefined ? cfg.allowed_platforms : (preset === "onebot" ? "onebot, aiocqhttp" : "")).trim();

  const allowedInp = $("cfgAllowedPlatforms");
  if (allowedInp && document.activeElement !== allowedInp) {
    allowedInp.value = allowed;
  }

  const tokens = allowed
    ? allowed.split(/[,，、;；\s]+/).map((t) => t.trim().toLowerCase()).filter(Boolean)
    : [];
  const isAll = tokens.length === 0 || tokens.includes("all") || tokens.includes("*");

  const stdList = ["onebot", "aiocqhttp", "matrix", "telegram", "discord", "lark"];
  state.customPlatforms = isAll ? [] : tokens.filter((t) => !stdList.includes(t) && t !== "all" && t !== "*");

  document.querySelectorAll(".plat-cb").forEach((cb) => {
    const v = cb.value;
    if (v === "all") cb.checked = isAll;
    else cb.checked = !isAll && tokens.includes(v);
  });

  renderCustomPlatTags();

  const sel = $("sel_platform_preset");
  if (sel && document.activeElement !== sel) {
    if (["all", "onebot", "onebot_matrix", "custom"].includes(preset)) {
      sel.value = preset;
    } else {
      if (isAll) sel.value = "all";
      else if (tokens.includes("matrix") && (tokens.includes("onebot") || tokens.includes("aiocqhttp")) && state.customPlatforms.length === 0) sel.value = "onebot_matrix";
      else if ((tokens.includes("onebot") || tokens.includes("aiocqhttp")) && tokens.length <= 2 && state.customPlatforms.length === 0) sel.value = "onebot";
      else sel.value = "custom";
    }
  }
}

function renderCustomPlatTags() {
  const wrap = $("customPlatTagsWrap");
  if (!wrap) return;
  wrap.innerHTML = state.customPlatforms.map((p, idx) => `
    <span class="platform-tag-pill">
      ${esc(p)}
      <span class="tag-rm" data-rm-idx="${idx}" title="删除">&times;</span>
    </span>
  `).join("");
}

function savePlatformSelection(fromPreset) {
  const sel = $("sel_platform_preset");
  const presetVal = sel ? sel.value : "custom";
  let finalStr = "";

  if (fromPreset && presetVal === "onebot") {
    finalStr = "onebot, aiocqhttp";
    state.customPlatforms = [];
  } else if (fromPreset && presetVal === "onebot_matrix") {
    finalStr = "onebot, aiocqhttp, matrix";
    state.customPlatforms = [];
  } else if (fromPreset && presetVal === "all") {
    finalStr = "all";
    state.customPlatforms = [];
  } else {
    const selected = [];
    let isAll = false;
    document.querySelectorAll(".plat-cb").forEach((cb) => {
      if (cb.checked) {
        if (cb.value === "all") isAll = true;
        else selected.push(cb.value);
      }
    });
    if (isAll || (selected.length === 0 && state.customPlatforms.length === 0 && presetVal === "all")) {
      finalStr = "all";
      state.customPlatforms = [];
    } else {
      const set = new Set([...selected, ...state.customPlatforms]);
      finalStr = Array.from(set).join(", ");
    }
  }

  const inp = $("cfgAllowedPlatforms");
  if (inp) inp.value = finalStr;

  syncPlatformUI({
    allowed_platforms: finalStr,
    platform_preset: presetVal,
  });
}

function initPlatformManager() {
  const sel = $("sel_platform_preset");
  if (sel) {
    sel.addEventListener("change", () => {
      savePlatformSelection(true);
    });
  }

  const chipsWrap = $("platformChips");
  if (chipsWrap) {
    chipsWrap.addEventListener("change", (ev) => {
      if (ev.target && ev.target.classList.contains("plat-cb")) {
        const cb = ev.target;
        if (cb.value === "all" && cb.checked) {
          document.querySelectorAll(".plat-cb").forEach((other) => {
            if (other !== cb) other.checked = false;
          });
          state.customPlatforms = [];
        } else if (cb.checked) {
          const allCb = document.querySelector('.plat-cb[value="all"]');
          if (allCb) allCb.checked = false;
        }
        if (sel) sel.value = "custom";
        savePlatformSelection(false);
      }
    });
  }

  const addBtn = $("btn_add_custom_plat");
  const customInp = $("inp_custom_plat");
  if (addBtn && customInp) {
    const doAdd = () => {
      const val = customInp.value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
      if (!val) return;
      if (!state.customPlatforms.includes(val)) {
        state.customPlatforms.push(val);
        const allCb = document.querySelector('.plat-cb[value="all"]');
        if (allCb) allCb.checked = false;
        if (sel) sel.value = "custom";
        savePlatformSelection(false);
      }
      customInp.value = "";
    };
    addBtn.addEventListener("click", doAdd);
    customInp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        doAdd();
      }
    });
  }

  const tagsWrap = $("customPlatTagsWrap");
  if (tagsWrap) {
    tagsWrap.addEventListener("click", (e) => {
      const rm = e.target.closest(".tag-rm");
      if (rm) {
        const idx = parseInt(rm.getAttribute("data-rm-idx"), 10);
        if (!isNaN(idx) && idx >= 0 && idx < state.customPlatforms.length) {
          state.customPlatforms.splice(idx, 1);
          if (sel) sel.value = "custom";
          savePlatformSelection(false);
        }
      }
    });
  }

  const allowedInp = $("cfgAllowedPlatforms");
  if (allowedInp) {
    allowedInp.addEventListener("input", () => {
      if (sel) sel.value = "custom";
      syncPlatformUI({
        allowed_platforms: allowedInp.value,
        platform_preset: "custom",
      });
    });
  }
}

async function loadSettings() {
  try {
    const res = await api.get("settings");
    state.settingsMeta = res.meta || {};
    state.settingsConfig = res.config || {};
    renderSettings();
    syncPlatformUI(state.settingsConfig);
    // 服务端配置是唯一真相源，回填完才揭开首帧
    if (App.applyUiPrefs(state.settingsConfig)) App.persistUiPrefs();
  } catch (e) {
    console.error("[DocMemory] loadSettings error:", e);
    App.showToast("插件设置获取失败：" + e.message);
  } finally {
    App.revealUiPrefs();
  }
}

function renderSettings() {
  const container = $("settingsForm");
  if (!container) return;
  // hidden 的 UI 偏好及专属平台卡片配置项，不进通用设置表单
  const keys = Object.keys(state.settingsMeta).filter((k) => !(state.settingsMeta[k] || {}).hidden && k !== "platform_preset" && k !== "allowed_platforms");
  if (!keys.length) {
    container.innerHTML = `<span class="helper">当前暂无可配置项。</span>`;
    return;
  }

  container.innerHTML = keys.map((k) => {
    const m = state.settingsMeta[k] || {};
    const type = m.type || "int";
    const desc = m.description || k;
    const hint = m.hint || "";
    const val = state.settingsConfig[k];

    if (type === "bool") {
      const on = Boolean(val);
      return `
        <div class="m3-switch-row" data-setting="${esc(k)}">
          <div>
            <div class="switch-label-title">${esc(desc)}</div>
            <div class="switch-label-sub">${esc(hint)}</div>
          </div>
          <label class="m3-switch"><input type="checkbox" data-switch="${esc(k)}" ${on ? "checked" : ""} /><span class="switch-slider"></span></label>
        </div>`;
    }

    const min = k === "chunk_size" ? 200 : 0;
    const step = 1;
    return `
      <div class="form-group" data-setting="${esc(k)}">
        <label class="form-label" for="set_${esc(k)}">
          ${esc(desc)}
          <span class="helper">${esc(hint)}</span>
        </label>
        <input type="number" id="set_${esc(k)}" class="m3-field" inputmode="numeric"
               value="${val === undefined || val === null ? "" : esc(val)}"
               min="${min}" step="${step}" />
      </div>`;
  }).join("");
}

function collectSettings() {
  const out = {};
  for (const [k, m] of Object.entries(state.settingsMeta)) {
    if (k === "platform_preset" || k === "allowed_platforms") continue;
    if ((m.type || "int") === "bool") {
      const sw = document.querySelector(`[data-switch="${k}"]`);
      out[k] = sw ? sw.checked : Boolean(m.default);
    } else {
      const el = $("set_" + k);
      if (!el) continue;
      const n = parseInt(el.value, 10);
      // 非法整数不发送，让后端保留现值；后端仍会做范围收敛
      if (Number.isFinite(n)) out[k] = n;
    }
  }
  const sel = $("sel_platform_preset");
  out.platform_preset = sel ? sel.value : "onebot";
  const allowedEl = $("cfgAllowedPlatforms");
  out.allowed_platforms = allowedEl ? allowedEl.value.trim() : "onebot, aiocqhttp";
  return out;
}

function applySettingsValues(src) {
  for (const [k, m] of Object.entries(state.settingsMeta)) {
    if (k === "platform_preset" || k === "allowed_platforms") continue;
    const val = src[k] !== undefined ? src[k] : m.default;
    if ((m.type || "int") === "bool") {
      const sw = document.querySelector(`[data-switch="${k}"]`);
      if (sw) sw.checked = Boolean(val);
    } else {
      const el = $("set_" + k);
      if (el) el.value = val === undefined || val === null ? "" : val;
    }
  }
  syncPlatformUI(src);
}

function initSettings() {
  initPlatformManager();
  const saveBtn = $("saveSettingsBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const config = collectSettings();
      try {
        const res = await api.post("settings/save", { config });
        state.settingsConfig = res.config || config;
        state.settingsMeta = res.meta || state.settingsMeta;
        renderSettings();
        syncPlatformUI(state.settingsConfig);
        App.showToast("插件设置已保存并生效。");
      } catch (err) {
        App.showToast("设置保存失败：" + err.message);
      }
    });
  }

  const resetBtn = $("resetSettingsBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      applySettingsValues({});
      App.showToast("已填入默认值，保存后方可生效。");
    });
  }
}

  App.initBackupButtons = initBackupButtons;
  App.loadSettings = loadSettings;
  App.initSettings = initSettings;
})(window.DocMemoryApp = window.DocMemoryApp || {});
