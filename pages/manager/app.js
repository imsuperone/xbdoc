// Document Memory Assistant - Android 16 (Material 3 Expressive) Client
(function () {
  "use strict";

  // 网络层来自 api.js（index.html 中先加载），此处只取引用
  const api = window.DocMemoryApi;
  if (!api) {
    throw new Error("[DocMemory] api.js 未加载，请检查 index.html 的 script 顺序");
  }

  // ---- DOM Helper ----
  const $ = (id) => document.getElementById(id);

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  // ---- Toast（与 xbbot_beta 同款：右下堆叠 + 类型色 + 点击复制） ----
  let _lastToastText = "";
  let _lastToastTime = 0;
  const _TOAST_MAX = 4;
  const _TOAST_ICON = {
    ok: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>',
    bad: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>'
  };
  const _TOAST_COPY_SVG = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>';
  const _TOAST_DONE_SVG = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>';

  // 类型自动识别（显式传 type 时以显式为准）：失败类 → bad，进行中/提示 → info，完成类 → ok
  function _toastTypeOf(msg, explicit) {
    if (explicit === "ok" || explicit === "bad" || explicit === "info") return explicit;
    const s = String(msg ?? "");
    if (/失败|错误|异常|超出|并非|不支持|无法|不存在|未包含|超时|未检出|非法/.test(s)) return "bad";
    if (/请先|请填写|请稍候|请至少|正在|尚未|暂未/.test(s)) return "info";
    if (/已|成功|完成|就绪|生效|完毕|恢复默认/.test(s)) return "ok";
    return "info";
  }

  // 沙箱里 navigator.clipboard 常被禁，退到 execCommand；都不行则选中文本让用户手动复制
  async function _copyText(text) {
    const s = String(text ?? "");
    if (!s) return false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(s);
        return true;
      }
    } catch (e) {}
    try {
      const ta = document.createElement("textarea");
      ta.value = s;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;padding:0;border:0;";
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, s.length);
      const ok = document.execCommand("copy");
      ta.remove();
      return !!ok;
    } catch (e) { return false; }
  }

  function _ensureToastContainer() {
    let c = document.getElementById("toastContainer");
    if (!c) {
      c = document.createElement("div");
      c.id = "toastContainer";
      c.className = "toast-container";
      c.setAttribute("aria-live", "polite");
      document.body.appendChild(c);
    }
    return c;
  }

  function showToast(msg, type, duration) {
    // 兼容旧签名 showToast(msg, 3000)：第二参是数字即为时长
    if (typeof type === "number") { duration = type; type = ""; }
    const text = String(msg ?? "");
    const now = Date.now();
    if (_lastToastText === text && now - _lastToastTime < 1200) return; // 过滤 1.2 秒内完全相同的重复弹窗
    _lastToastText = text;
    _lastToastTime = now;

    const container = _ensureToastContainer();
    const kind = _toastTypeOf(text, type);
    const t = document.createElement("div");
    t.className = "m3-toast" + (kind === "ok" ? " okk" : kind === "bad" ? " badk" : "");
    t.setAttribute("role", "status");

    const ic = document.createElement("span");
    ic.className = "m3-toast-ic";
    ic.innerHTML = _TOAST_ICON[kind] || _TOAST_ICON.info;
    t.appendChild(ic);

    const body = document.createElement("div");
    body.className = "m3-toast-text";
    body.textContent = text;
    t.appendChild(body);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "m3-toast-copy";
    btn.title = "复制这条通知";
    btn.setAttribute("aria-label", "复制这条通知");
    btn.innerHTML = _TOAST_COPY_SVG;
    t.appendChild(btn);

    // 长文本给更久，留出阅读与复制时间
    const life = duration || Math.min(9000, Math.max(3000, 2400 + text.length * 45));
    let timer = 0;
    const dismiss = () => {
      t.classList.add("out");
      setTimeout(() => t.remove(), 300);
    };
    const arm = (ms) => { clearTimeout(timer); timer = setTimeout(dismiss, ms); };

    const doCopy = async () => {
      if (await _copyText(text)) {
        btn.innerHTML = _TOAST_DONE_SVG;
        btn.classList.add("done");
        btn.title = "已复制";
        setTimeout(() => {
          btn.innerHTML = _TOAST_COPY_SVG;
          btn.classList.remove("done");
          btn.title = "复制这条通知";
        }, 1600);
        arm(Math.max(life, 4000));
      } else {
        // 剪贴板被拦：全选文本，用户 Ctrl/Cmd+C 兜底
        try {
          const sel = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(body);
          sel.removeAllRanges();
          sel.addRange(range);
        } catch (e) {}
        btn.title = "自动复制失败，已选中文本，请手动 Ctrl+C";
        arm(Math.max(life, 6000));
      }
    };

    btn.addEventListener("click", (e) => { e.stopPropagation(); doCopy(); });
    t.addEventListener("click", () => {
      // 用户正在手动选词时不打断
      try { if (String(window.getSelection())) return; } catch (e) {}
      doCopy();
    });

    container.appendChild(t);
    while (container.children.length > _TOAST_MAX) container.removeChild(container.firstChild);
    arm(life);
  }

  // ---- 页内确认框（沙箱 iframe 中原生 confirm 被拦截恒返回 false，危险操作必须页内确认） ----
  function _buildConfirmOverlay(message, okText) {
    const ov = document.createElement("div");
    ov.className = "xb-confirm-overlay";
    const card = document.createElement("div");
    card.className = "xb-confirm-card";
    const msg = document.createElement("div");
    msg.className = "xb-confirm-msg";
    msg.textContent = message;
    card.appendChild(msg);
    const actions = document.createElement("div");
    actions.className = "xb-confirm-actions";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "m3-btn secondary-btn";
    cancelBtn.textContent = "取消";
    const okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.className = "m3-btn primary-btn";
    okBtn.textContent = okText;
    actions.appendChild(cancelBtn);
    actions.appendChild(okBtn);
    card.appendChild(actions);
    ov.appendChild(card);
    return { ov, okBtn, cancelBtn };
  }

  function uiConfirm(message, okText = "确定") {
    return new Promise((resolve) => {
      const { ov, okBtn, cancelBtn } = _buildConfirmOverlay(message, okText);
      const done = (v) => { try { ov.remove(); } catch (e) {} resolve(v); };
      okBtn.addEventListener("click", () => done(true));
      cancelBtn.addEventListener("click", () => done(false));
      ov.addEventListener("click", (e) => { if (e.target === ov) done(false); });
      document.body.appendChild(ov);
      okBtn.focus();
    });
  }

  // ---- State Management ----
  let docsList = [];
  let bindingsMap = {};
  let groupsCache = [];
  let selectedDocIds = new Set();
  let loadedSessionKey = "";
  let promptDirty = false;
  let currentReaderDoc = null;
  let currentReaderChunk = 1;
  let currentReaderTotal = 1;
  let currentShield = "off";
  let currentDocMode = "none";
  let currentForcePrompt = false;
  let currentBindingFilter = "all";

  // ---- Theme Handling ----
  function initTheme() {
    try {
      // 无本地缓存可读（服务端是唯一真相源，由 applyUiPrefs() 回填）；
      // 首帧先按系统深浅色给个合理初值，随后被服务端值覆盖。
      const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      applyTheme(prefersDark ? "dark" : "light");

      const btn = $("themeToggleBtn");
      if (btn) {
        btn.addEventListener("click", () => {
          const cur = document.documentElement.getAttribute("data-theme") || "light";
          const next = cur === "dark" ? "light" : "dark";
          applyTheme(next);
          persistUiPrefs();
          // Re-tint accent variables for the new theme (custom color or theme default)
          const picker = $("accentPicker");
          if (picker) {
            if (picker.dataset.custom) applyAccentColor(picker.value, false);
            else applyAccentColor("", false);
          }
          showToast(`当前界面已切换为${next === "dark" ? "深色" : "浅色"}模式。`);
        });
      }
      // 取色回填交给紧随其后的 initAccentPicker() → applyUiPrefs()（服务端配置），不在这里动。
    } catch (e) {
      console.warn("[DocMemory] initTheme failed:", e);
    }
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const icon = $("themeIcon");
    if (!icon) return;
    if (theme === "dark") {
      icon.innerHTML = `<path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1zM5.99 4.58c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58zm12.37 12.37c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41l-1.06-1.06zm1.06-10.96c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06zM7.05 18.36c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06z"/>`;
    } else {
      icon.innerHTML = `<path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9 9-4.03 9-9c0-.46-.04-.92-.1-1.36-.98 1.37-2.58 2.26-4.4 2.26-2.98 0-5.4-2.42-5.4-5.4 0-1.81.89-3.42 2.26-4.4-.44-.06-.9-.1-1.36-.1z"/>`;
    }
  }

  // ---- Accent Color Engine (ported from xbimg) ----
  function mixHex(hexA, hexB, ratio) {
    const toRgb = (h) => [1, 3, 5].map((i) => parseInt(h.substr(i, 2), 16));
    const a = toRgb(hexA), b = toRgb(hexB);
    const mixed = a.map((v, i) => Math.round(v * ratio + b[i] * (1 - ratio)));
    return "#" + mixed.map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, "0")).join("");
  }

  const _ACCENT_VARS = ["--m3-sys-color-primary", "--m3-sys-color-on-primary", "--m3-sys-color-primary-container", "--m3-sys-color-surface", "--m3-sys-color-surface-container", "--m3-sys-color-surface-container-high", "--m3-sys-color-surface-container-highest", "--m3-seg-ink"];

  function _relLum(hex) {
    const c = [1, 3, 5].map((i) => {
      const v = parseInt(hex.substr(i, 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }

  function _contrastOk(fg, bg) {
    const l1 = _relLum(fg), l2 = _relLum(bg);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05) >= 3.0;
  }

  function applyAccentColor(hex, save) {
    void save;
    const v = typeof hex === "string" ? hex.trim() : "";
    const ok = /^#[0-9a-fA-F]{6}$/.test(v);
    const root = document.documentElement;
    if (ok) {
      const dark = (root.getAttribute("data-theme") || "light") === "dark";
      // 只染强调系（primary / primary-container），surface 系保持主题原色，避免整页被染脏
      const tinted = {
        "--m3-sys-color-primary": v,
        "--m3-sys-color-primary-container": dark ? mixHex(v, "#1B2C42", 0.45) : mixHex(v, "#E4EAF2", 0.25),
      };
      for (const k in tinted) {
        try { root.style.setProperty(k, tinted[k]); } catch (e) {}
      }
      try {
        root.style.setProperty("--m3-sys-color-on-primary", _contrastOk("#FFFFFF", v) ? "#FFFFFF" : (dark ? "#06263F" : "#1E1B16"));
        let segBg = "";
        try { segBg = getComputedStyle(root).getPropertyValue("--m3-sys-color-surface-container-high").trim(); } catch (e) { segBg = ""; }
        if (!/^#[0-9a-fA-F]{6}$/.test(segBg)) segBg = dark ? "#232A33" : "#FFFFFF";
        root.style.setProperty("--m3-seg-ink", _contrastOk(v, segBg) ? v : (dark ? "#EAE6DF" : "#1E1B16"));
      } catch (e) {}
    } else {
      for (const k of _ACCENT_VARS) {
        try { root.style.removeProperty(k); } catch (e) {}
      }
    }
    const picker = $("accentPicker");
    if (picker) {
      if (ok) {
        picker.value = v;
        picker.dataset.custom = "1";
      } else {
        delete picker.dataset.custom;
        try {
          const def = getComputedStyle(document.documentElement).getPropertyValue("--m3-sys-color-primary").trim() || "#4A90D9";
          picker.value = /^#[0-9a-fA-F]{6}$/.test(def) ? def : "#4A90D9";
        } catch (e) {}
      }
    }
  }

  function initAccentPicker() {
    // 首帧把取色器对齐到当前主题的默认 primary；权威取色值由 applyUiPrefs()
    // 从服务端回填（不读 localStorage，那里在沙箱里拿不到东西）。
    applyAccentColor("", false);
    const picker = $("accentPicker");
    if (picker) {
      picker.addEventListener("input", () => applyAccentColor(picker.value, false));
      picker.addEventListener("change", () => { applyAccentColor(picker.value, false); persistUiPrefs(); });
      picker.addEventListener("dblclick", () => { applyAccentColor("", false); persistUiPrefs(); });
    }
    const resetBtn = $("accentResetBtn");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        applyAccentColor("", false);
        persistUiPrefs();
        showToast("已恢复默认主题颜色。");
      });
    }
  }

  // ---- UI 偏好（主题色 + 深浅色）落服务端 ----
  // AstrBot 用沙箱 iframe 载插件页，localStorage 不可用：本地缓存这条路走不通，
  // 服务端配置是唯一真相源（不留任何本地副本）。
  // 与 xbimg 同款——改由 settings/save 持久化，本地记录仅作首帧快速回填。
  function revealUiPrefs() {
    try { document.documentElement.removeAttribute("data-boot"); } catch (e) {}
  }

  let _uiPrefTimer = null;
  function persistUiPrefs() {
    if (_uiPrefTimer) clearTimeout(_uiPrefTimer);
    _uiPrefTimer = setTimeout(() => {
      _uiPrefTimer = null;
      const picker = $("accentPicker");
      const cfg = {
        ui_theme_mode: document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light",
        ui_accent_color: (picker && picker.dataset.custom) ? picker.value : "",
      };
      // 只发这两个键：save_plugin_config 按 CONFIG_DEFAULTS 逐键合并，缺键不动，不会冲掉别的设置
      api.post("settings/save", { config: cfg }).then((res) => {
        if (!res || !res.config) console.warn("[DocMemory] 保存 UI 偏好失败:", res);
      }).catch((e) => {
        console.warn("[DocMemory] 保存 UI 偏好失败:", e);
      });
    }, 600);
  }

  // 返回 true = 服务端还没记过深浅色，调用方需回写一次，否则沙箱里下次刷新仍是默认
  function applyUiPrefs(cfg) {
    const s = (cfg && typeof cfg === "object") ? cfg : {};
    let needSeed = false;
    if (s.ui_theme_mode === "dark" || s.ui_theme_mode === "light") {
      applyTheme(s.ui_theme_mode);
    } else {
      needSeed = true;
    }
    if (Object.prototype.hasOwnProperty.call(s, "ui_accent_color")) {
      applyAccentColor(String(s.ui_accent_color || "").trim(), false);
    }
    return needSeed;
  }

  function hexToHsv(hex) {
    const r = parseInt(hex.substr(1, 2), 16) / 255;
    const g = parseInt(hex.substr(3, 2), 16) / 255;
    const b = parseInt(hex.substr(5, 2), 16) / 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    const d = mx - mn;
    let h = 0;
    if (d !== 0) {
      if (mx === r) h = 60 * (((g - b) / d) % 6);
      else if (mx === g) h = 60 * ((b - r) / d + 2);
      else h = 60 * ((r - g) / d + 4);
    }
    if (h < 0) h += 360;
    return { h: h, s: mx === 0 ? 0 : d / mx, v: mx };
  }

  function hsvToHex(h, s, v) {
    const c = v * s;
    const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    const m = v - c;
    let rp = 0, gp = 0, bp = 0;
    if (h < 60) { rp = c; gp = x; bp = 0; }
    else if (h < 120) { rp = x; gp = c; bp = 0; }
    else if (h < 180) { rp = 0; gp = c; bp = x; }
    else if (h < 240) { rp = 0; gp = x; bp = c; }
    else if (h < 300) { rp = x; gp = 0; bp = c; }
    else { rp = c; gp = 0; bp = x; }
    const to2 = (n) => Math.round((n + m) * 255).toString(16).padStart(2, "0");
    return "#" + to2(rp) + to2(gp) + to2(bp);
  }

  function initAccentPopover() {
    const btn = $("accentPickerBtn");
    const picker = $("accentPicker");
    const pop = $("accentPopover");
    if (!btn || !picker || !pop) return;
    const sv = $("accentSv");
    const svDot = $("accentSvDot");
    const hue = $("accentHue");
    const hueDot = $("accentHueDot");
    const hexInput = $("accentHex");
    const current = $("accentCurrent");
    const presets = $("accentPresets");
    let st = { h: 210, s: 0.66, v: 0.85 };
    let open = false;

    function currentHex() {
      const v = (picker.value || "").trim();
      if (/^#[0-9a-fA-F]{6}$/.test(v)) return v;
      try {
        const def = getComputedStyle(document.documentElement).getPropertyValue("--m3-sys-color-primary").trim();
        if (/^#[0-9a-fA-F]{6}$/.test(def)) return def;
      } catch (e) {}
      return "#4A90D9";
    }

    function paint() {
      const hex = hsvToHex(st.h, st.s, st.v);
      if (sv) sv.style.background = "linear-gradient(to top,#000,transparent),linear-gradient(to right,#fff,transparent),hsl(" + Math.round(st.h) + ",100%,50%)";
      if (svDot) { svDot.style.left = (st.s * 100) + "%"; svDot.style.top = ((1 - st.v) * 100) + "%"; svDot.style.background = hex; }
      if (hueDot) { hueDot.style.left = (st.h / 360 * 100) + "%"; hueDot.style.background = "hsl(" + Math.round(st.h) + ",100%,50%)"; }
      if (hexInput && document.activeElement !== hexInput) hexInput.value = hex;
      if (current) current.style.background = hex;
    }

    function commit(fireChange) {
      const hex = hsvToHex(st.h, st.s, st.v);
      picker.value = hex;
      picker.dispatchEvent(new Event("input"));
      if (fireChange) picker.dispatchEvent(new Event("change"));
      if (hexInput) hexInput.value = hex;
      if (current) current.style.background = hex;
    }

    function place() {
      pop.hidden = false;
      const r = btn.getBoundingClientRect();
      const w = pop.offsetWidth || 240;
      const hgt = pop.offsetHeight || 260;
      const vw = window.innerWidth, vh = window.innerHeight;
      let left = r.left + 20 - w / 2;
      left = Math.max(8, Math.min(left, Math.max(8, vw - w - 8)));
      let top = r.bottom + 8;
      if (top + hgt > vh - 8) top = Math.max(8, r.top - hgt - 8);
      pop.style.left = left + "px";
      pop.style.top = top + "px";
    }

    function show() {
      st = hexToHsv(currentHex());
      paint();
      place();
      open = true;
    }

    function hide() {
      pop.hidden = true;
      open = false;
    }

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (open) hide();
      else show();
    });

    pop.addEventListener("click", (e) => e.stopPropagation());

    function svSet(e) {
      const r = sv.getBoundingClientRect();
      st.s = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      st.v = Math.max(0, Math.min(1, 1 - (e.clientY - r.top) / r.height));
      paint();
      commit(false);
    }

    if (sv) {
      sv.addEventListener("pointerdown", (e) => {
        try { sv.setPointerCapture(e.pointerId); } catch (err) {}
        svSet(e);
        const mv = (ev) => svSet(ev);
        const up = () => {
          sv.removeEventListener("pointermove", mv);
          picker.dispatchEvent(new Event("change"));
        };
        sv.addEventListener("pointermove", mv);
        sv.addEventListener("pointerup", up, { once: true });
      });
    }

    function hueSet(e) {
      const r = hue.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      st.h = ratio * 360;
      if (st.h >= 360) st.h = 359.9;
      paint();
      commit(false);
    }

    if (hue) {
      hue.addEventListener("pointerdown", (e) => {
        try { hue.setPointerCapture(e.pointerId); } catch (err) {}
        hueSet(e);
        const mv = (ev) => hueSet(ev);
        const up = () => {
          hue.removeEventListener("pointermove", mv);
          picker.dispatchEvent(new Event("change"));
        };
        hue.addEventListener("pointermove", mv);
        hue.addEventListener("pointerup", up, { once: true });
      });
    }

    function applyHexInput() {
      const v = (hexInput.value || "").trim();
      if (/^#[0-9a-fA-F]{6}$/.test(v)) {
        st = hexToHsv(v);
        paint();
        picker.value = v;
        picker.dispatchEvent(new Event("input"));
        picker.dispatchEvent(new Event("change"));
        if (current) current.style.background = v;
      } else {
        hexInput.value = currentHex();
      }
    }

    if (hexInput) {
      hexInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") applyHexInput();
        if (e.key === "Escape") hide();
      });
      hexInput.addEventListener("blur", applyHexInput);
      hexInput.addEventListener("click", (e) => e.stopPropagation());
    }

    if (presets) {
      presets.addEventListener("click", (e) => {
        const b = e.target.closest("button[data-color]");
        if (!b) return;
        const v = b.getAttribute("data-color") || "";
        if (!/^#[0-9a-fA-F]{6}$/.test(v)) return;
        st = hexToHsv(v);
        paint();
        picker.value = v;
        picker.dispatchEvent(new Event("input"));
        picker.dispatchEvent(new Event("change"));
        if (current) current.style.background = v;
      });
    }

    document.addEventListener("click", (e) => {
      if (!open) return;
      if (!e.target.closest("#accentPopover") && !e.target.closest("#accentPickerBtn")) hide();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && open) hide();
    });

    window.addEventListener("resize", () => { if (open) place(); });
  }

  // ---- Navigation Tabs (xbimg framework pattern: data-tab <-> data-section) ----
  function initTabs() {
    const tabs = document.querySelectorAll(".cat-tab");
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        switchTab(tab.dataset.tab);
      });
    });
  }

  function switchTab(tabId) {
    document.querySelectorAll(".cat-tab").forEach((t) => {
      t.classList.toggle("active", t.getAttribute("data-tab") === tabId);
    });
    document.querySelectorAll(".settings-section").forEach((p) => {
      p.classList.toggle("active", p.getAttribute("data-section") === tabId);
    });
  }

  // ---- Load Docs ----
  async function loadDocs() {
    try {
      const res = await api.get("docs");
      docsList = res.docs || res.data?.docs || [];
      renderDocs(docsList);
      for (const id of Array.from(selectedDocIds)) {
        if (!docsList.some((d) => d.doc_id === id)) selectedDocIds.delete(id);
      }
      renderDocChips();
    } catch (e) {
      console.error("[DocMemory] loadDocs error:", e);
      showToast("文档列表获取失败：" + e.message);
    }
  }

  // ---- Load Bindings ----
  async function loadBindings() {
    try {
      const res = await api.get("bindings");
      bindingsMap = res.bindings || {};
      renderBindings();
    } catch (e) {
      console.error("[DocMemory] loadBindings error:", e);
      showToast("绑定列表获取失败：" + e.message);
    }
  }

  // ---- Render Document Cards with Event Delegation ----
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

  // Attach Document Grid Click Delegation (Runs once, never drops events)
  function initDocGridEvents() {
    const container = $("docGrid");
    if (!container) return;

    container.addEventListener("click", async (e) => {
      const badge = e.target.closest(".id-badge");
      if (badge) {
        const card = badge.closest(".doc-card");
        const did = card ? card.dataset.id : "";
        if (did) {
          try {
            await navigator.clipboard.writeText(did);
            showToast(`文档 ID 已复制：${did}`);
          } catch {
            showToast(`文档 ID 为：${did}`);
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
        openReader(id, 1);
      } else if (act === "download") {
        try {
          showToast("正在下载文档，请稍候……");
          await api.download("docs/download", { doc_id: id });
        } catch (err) {
          showToast("文档下载失败：" + err.message);
        }
      } else if (act === "attach") {
        selectedDocIds.add(id);
        renderDocChips();
        switchTab("tab-bindings");
        const sk = $("sessionKey");
        if (sk) sk.focus();
        showToast("已将该文档添加至绑定表单。");
      } else if (act === "delete") {
        try {
          showToast(`正在删除文档（ID：${id}），请稍候……`);
          await api.post("docs/delete", { doc_id: id });
          showToast("文档已删除，相关绑定已同步清理。");
          await loadDocs();
          await loadBindings();
        } catch (err) {
          showToast("文档删除失败：" + err.message);
        }
      }
    });
  }

  // ---- Document Search Filter (150ms 防抖：输入过程中不反复全量重排) ----
  function initDocSearch() {
    const input = $("docSearchInput");
    if (!input) return;

    let timer = null;
    input.addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const q = e.target.value.trim().toLowerCase();
        if (!q) {
          renderDocs(docsList);
          return;
        }
        const filtered = docsList.filter((d) =>
          (d.filename || "").toLowerCase().includes(q) || (d.doc_id || "").toLowerCase().includes(q)
        );
        renderDocs(filtered);
      }, 150);
    });
  }

  // ---- File Upload & Drag & Drop ----
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
        showToast("文件大小超出 50MB 上限，请拆分后重新上传。");
        return;
      }
      if (progress) progress.style.display = "block";
      showToast(`正在上传并处理文件 ${file.name}，请稍候……`, 5000);

      try {
        const res = await api.upload("docs/upload", file);
        if (progress) progress.style.display = "none";
        showToast(`文档 ${res.doc?.filename || file.name} 已完成入库。`);
        await loadDocs();
      } catch (err) {
        if (progress) progress.style.display = "none";
        showToast("文档上传失败：" + err.message);
      }
    }
  }

  // ---- Document Chips Picker (Bindings View) ----
  function renderDocChips() {
    const container = $("docChipsPicker");
    if (!container) return;

    if (!docsList.length) {
      container.innerHTML = `<span class="helper">知识库中暂无文档，请先前往文档库完成上传。</span>`;
      return;
    }

    container.innerHTML = docsList.map((d) => {
      const isSelected = selectedDocIds.has(d.doc_id);
      return `
        <div class="doc-select-chip ${isSelected ? "selected" : ""}" data-id="${esc(d.doc_id)}" role="button" tabindex="0">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="${isSelected ? 'M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z' : 'M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z'}"/>
          </svg>
          <span>${esc(d.filename)}</span>
        </div>
      `;
    }).join("");

    const hasDocs = selectedDocIds.size > 0;
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

      if (selectedDocIds.has(id)) {
        selectedDocIds.delete(id);
      } else {
        selectedDocIds.add(id);
      }
      renderDocChips();
    });
  }

  // ---- Group Search Auto-Suggest ----
  let suggestTimer = null;
  let suggestSeq = 0; // 单调序号：旧请求先回也直接丢弃，防联想结果乱序覆盖
  async function searchGroups(q = "") {
    const mySeq = ++suggestSeq;
    try {
      const res = await api.get("groups", q ? { q, limit: 30 } : { limit: 30 });
      if (mySeq !== suggestSeq) return null;
      groupsCache = res.groups || res.data?.groups || [];
      return groupsCache;
    } catch (e) {
      return mySeq === suggestSeq ? [] : null;
    }
  }

  function renderGroupSuggest(list) {
    const box = $("suggestDropdown");
    if (!box) return;

    if (!list || !list.length) {
      box.classList.remove("open");
      box.innerHTML = "";
      return;
    }

    box.innerHTML = list.slice(0, 15).map((g) => {
      const isPrivate = g.kind === "private";
      const firstLetter = (g.group_name || g.gid || (isPrivate ? "私" : "群")).charAt(0).toUpperCase();
      return `
        <div class="suggest-card" data-key="${esc(g.session_key || ('group:' + g.gid))}">
          <div style="display:flex; align-items:center;">
            <div class="suggest-avatar">${esc(firstLetter)}</div>
            <div class="suggest-info">
              <strong>${esc(g.group_name || ((isPrivate ? "私聊 " : "群聊 ") + g.gid))}</strong>
              <span>${esc(g.platform ? g.platform + ' · ' : '')}${isPrivate ? "私聊 UID" : "群号"}: ${esc(g.gid)} ${g.msg_count ? ' · ' + esc(g.msg_count) + '条发言' : ''}</span>
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
    if (!input || !box) return;

    if (fetchBtn) {
      fetchBtn.addEventListener("click", async () => {
        const originalHtml = fetchBtn.innerHTML;
        fetchBtn.disabled = true;
        fetchBtn.innerHTML = `<span>正在获取……</span>`;
        showToast("正在从机器人适配器获取群聊列表，请稍候……", 4000);

        try {
          let res = null;
          try {
            res = await api.post("groups/fetch");
          } catch (e) {
            res = await api.get("groups", { refresh: "1" });
          }

          const list = res.groups || res.data?.groups || [];
          const newCount = res.new_fetched !== undefined ? res.new_fetched : list.length;
          // 后端 debug 直出拉群失败原因（0 适配器/超时/空返回/异常原文），不再靠猜
          const dbg = res.debug || res.data?.debug || {};
          const bad = (dbg.details || []).filter((d) => !/: ok\(/.test(d)).slice(0, 2);
          const reason = `（找到适配器 ${dbg.bots ?? "?"} 个${bad.length ? "；" + bad.join("；") : ""}）`;
          if (list.length) {
            groupsCache = list;
          } else {
            const g = await searchGroups("");
            if (g) groupsCache = g;
          }
          renderGroupSuggest(groupsCache);
          input.focus();

          if (newCount > 0) {
            showToast(`已从适配器获取 ${newCount} 个群聊（共收录 ${groupsCache.length} 个）。`, 3500);
          } else if (groupsCache.length > 0) {
            showToast(`适配器未返回新的群聊${reason}，当前共列出 ${groupsCache.length} 个已知群聊。`, 6000);
          } else {
            showToast(`未获取到新的群聊${reason}。协议不支持时，在群聊中发送一条消息即可自动记录，或手动填写 group:群号。`, 7000);
          }
        } catch (err) {
          showToast("群聊列表获取失败：" + err.message);
        } finally {
          fetchBtn.disabled = false;
          fetchBtn.innerHTML = originalHtml;
        }
      });
    }

    box.addEventListener("click", (e) => {
      const card = e.target.closest(".suggest-card");
      if (!card) return;
      const key = card.dataset.key;
      input.value = key;
      box.classList.remove("open");
      resetSessionControls();
      selectedDocIds.clear();
      renderDocChips();
      loadExistingSessionSettings(key);
    });

    // 手填 Key 切走时：命中已知会话则载入，否则重置提示词/开关为默认，避免把上个群的配置存到新群
    // 后缀精确匹配：限定 key（group:plat:123）同样能被纯数字/老格式命中
    function findBindingKey(v) {
      const s = (v || "").trim();
      if (!s) return "";
      if (bindingsMap[s]) return s;
      const tailEq = (k) => String(k || "").split(":").pop() === s;
      if (/^\d{5,}$/.test(s)) {
        // 纯数字可能是群号也可能是私聊 UID：已存在的绑定优先命中，避免串台
        const priv = Object.keys(bindingsMap).find((k) => k.startsWith("private:") && tailEq(k));
        const grp = Object.keys(bindingsMap).find((k) => k.startsWith("group:") && tailEq(k));
        if (priv && !grp) return priv;
        if (grp) return grp;
      }
      return Object.keys(bindingsMap).find(tailEq) || "";
    }

    function resetSessionControls() {
      const bp = $("bindPrompt");
      if (bp) bp.value = "";
      promptDirty = false;
      setShieldChoice("off");
      setForceChoice("off");
      currentDocMode = "none";
      const group = $("docModeGroup");
      if (group) {
        group.querySelectorAll(".segmented-choice-btn").forEach((btn) => {
          btn.classList.toggle("active", btn.dataset.val === "none");
        });
      }
    }

    input.addEventListener("change", () => {
      const v = input.value.trim();
      if (!v || v === loadedSessionKey) return;
      const hit = findBindingKey(v);
      if (hit) {
        input.value = hit;
        loadExistingSessionSettings(hit);
      } else {
        loadedSessionKey = v;
        resetSessionControls();
      }
    });

    const promptEl = $("bindPrompt");
    if (promptEl) {
      promptEl.addEventListener("input", () => { promptDirty = true; updatePromptCount(); });
    }

    input.addEventListener("input", () => {
      clearTimeout(suggestTimer);
      const q = input.value.trim();
      if (!q) {
        searchGroups("").then((list) => { if (list) renderGroupSuggest(list); });
        return;
      }
      if (/^group:\d+$/.test(q)) {
        box.classList.remove("open");
        return;
      }
      suggestTimer = setTimeout(async () => {
        const list = await searchGroups(q);
        if (list) renderGroupSuggest(list);
      }, 220);
    });

    const showList = async () => {
      const q = input.value.trim();
      if (/^group:\d+$/.test(q)) return;
      const list = groupsCache.length ? groupsCache : await searchGroups(q);
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

  // ---- Prompt Char Counter (live count next to the textarea) ----
  function updatePromptCount() {
    const box = $("bindPrompt");
    const label = $("promptCharCount");
    if (!box || !label) return;
    const n = (box.value || "").length;
    label.textContent = n > 0 ? `已输入 ${n} 字。` : "";
  }

  function loadExistingSessionSettings(key) {
    const entry = bindingsMap[key];
    loadedSessionKey = key || "";
    promptDirty = false;
    if (!entry) return;

    selectedDocIds.clear();
    const docs = entry.docs || [];
    docs.forEach((d) => selectedDocIds.add(typeof d === "string" ? d : d.doc_id));
    renderDocChips();

    const promptEl = $("bindPrompt");
    if (promptEl) promptEl.value = entry.prompt || "";
    updatePromptCount();

    const shieldVal = entry.shield ? "on" : "off";
    setShieldChoice(shieldVal);

    const forceVal = entry.force_system_prompt ? "on" : "off";
    setForceChoice(forceVal);

    let modeVal = "reference";
    if (entry.mode === "system" || entry.mode === "workspace" || entry.mode === "none") {
      modeVal = entry.mode;
    }
    _applyDocMode(modeVal);
  }

  // ---- Document Execution Mode Choice Buttons ----
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
    if (selectedDocIds.size === 0) {
      showToast("请先选择需要绑定的文档，再设置生效模式。");
      return;
    }
    _applyDocMode(val);
  }

  function _applyDocMode(val) {
    if (val === "system" || val === "workspace" || val === "reference" || val === "none") {
      currentDocMode = val;
    } else {
      currentDocMode = "none";
    }
    const group = $("docModeGroup");
    if (!group) return;

    group.querySelectorAll(".segmented-choice-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === currentDocMode);
    });
  }

  // ---- Force System Prompt Choice Buttons ----
  function initForceChoice() {
    const group = $("forceChoiceGroup");
    if (!group) return;

    group.addEventListener("click", (e) => {
      const btn = e.target.closest(".segmented-choice-btn");
      if (!btn) return;
      setForceChoice(btn.dataset.val);
    });
  }

  function setForceChoice(val) {
    currentForcePrompt = val === "on";
    const group = $("forceChoiceGroup");
    if (!group) return;

    group.querySelectorAll(".segmented-choice-btn").forEach((btn) => {
      btn.classList.toggle("active", (btn.dataset.val === "on") === currentForcePrompt);
    });
  }

  // ---- Shield Switch Choice Buttons (Only On / Off, No Global) ----
  function initShieldChoice() {
    const group = $("shieldChoiceGroup");
    if (!group) return;

    group.addEventListener("click", (e) => {
      const btn = e.target.closest(".segmented-choice-btn");
      if (!btn) return;
      setShieldChoice(btn.dataset.val);
    });
  }

  function setShieldChoice(val) {
    currentShield = val === "on" ? "on" : "off";
    const group = $("shieldChoiceGroup");
    if (!group) return;

    group.querySelectorAll(".segmented-choice-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === currentShield);
    });
  }

  // ---- Binding Form Save & Reset ----
  function initBindingForm() {
    const resetBtn = $("resetBindFormBtn");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        const sk = $("sessionKey");
        const bp = $("bindPrompt");
        if (sk) sk.value = "";
        if (bp) bp.value = "";
        loadedSessionKey = "";
        promptDirty = false;
        updatePromptCount();
        selectedDocIds.clear();
        renderDocChips();
        setShieldChoice("off");
        setForceChoice("off");
        _applyDocMode("none");
        showToast("表单内容已清空。");
      });
    }

    const saveBtn = $("saveBindBtn");
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
        const input = $("sessionKey");
        let key = input ? input.value.trim() : "";
        if (!key) {
          showToast("请填写或选择目标会话标识（例如 group:123456）。");
          if (input) input.focus();
          return;
        }

        if (/^\d{5,}$/.test(key)) {
          // 纯数字：已有绑定按后缀精确认领（含限定 key），都没有默认按群号；后端还会按 seen 再补限定
          const tailEq = (k) => String(k || "").split(":").pop() === key;
          const privHit = Object.keys(bindingsMap).find((k) =>
            k.startsWith("private:") && tailEq(k));
          const grpHit = Object.keys(bindingsMap).find((k) =>
            k.startsWith("group:") && tailEq(k));
          const hit = grpHit || privHit;
          if (hit) {
            key = hit;
          } else {
            key = "group:" + key;
          }
          input.value = key;
        }

        const ids = Array.from(selectedDocIds);
        const promptEl = $("bindPrompt");
        // 未动过提示词框时沿用该会话已有提示词，防止手填Key把别的群/旧值覆盖掉；
        // 只有亲手改过才按框内值保存（含清空）。
        let prompt;
        if (promptDirty || !bindingsMap[key]) {
          prompt = promptEl ? promptEl.value.trim() : "";
        } else {
          const curText = promptEl ? promptEl.value.trim() : "";
          const storedText = (bindingsMap[key].prompt || "").trim();
          prompt = curText !== storedText ? curText : storedText;
        }
        const shield = currentShield === "on";
        // 未选文档时模式强制回落（后端同样会强制），避免存下无效模式
        const mode = ids.length > 0 ? (currentDocMode || "none") : "reference";
        const forceSys = currentForcePrompt;

        try {
          await api.post("bindings/save", {
            session_key: key,
            doc_ids: ids,
            prompt: prompt,
            shield: shield,
            mode: mode,
            force_system_prompt: forceSys,
          });
          showToast("会话绑定与配置已保存。");
          loadedSessionKey = key;
          promptDirty = false;
          await loadBindings();
          await searchGroups("");
        } catch (err) {
          showToast("配置保存失败：" + err.message);
        }
      });
    }
  }

  // ---- Render Active Bindings List ----
  function renderBindings() {
    const container = $("bindingList");
    if (!container) return;

    const allKeys = Object.keys(bindingsMap);

    // Compute Shield counts (Only On vs Off)
    let onCount = 0;
    let offCount = 0;

    allKeys.forEach((k) => {
      if (Boolean((bindingsMap[k] || {}).shield)) onCount++;
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
      const sh = Boolean((bindingsMap[k] || {}).shield);
      if (currentBindingFilter === "shield_on") return sh === true;
      if (currentBindingFilter === "shield_off") return sh === false;
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
      const raw = bindingsMap[k] || {};
      const docs = raw.docs || [];
      const prompt = raw.prompt || "";
      const isShield = Boolean(raw.shield);
      const shieldClass = isShield ? "shield-badge-on" : "shield-badge-off";
      const shieldTag = isShield ? "屏蔽已开启（清空原人格）" : "屏蔽已关闭（保留原人格）";

      const curMode = raw.mode === "system" ? "system" : (raw.mode === "workspace" ? "workspace" : (raw.mode === "none" ? "none" : "reference"));

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

  // ---- Shield Filter Tabs Handler ----
  function initShieldFilter() {
    const group = $("shieldFilterGroup");
    if (!group) return;

    group.addEventListener("click", (e) => {
      const chip = e.target.closest(".shield-filter-chip");
      if (!chip) return;
      group.querySelectorAll(".shield-filter-chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      currentBindingFilter = chip.dataset.filter || "all";
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
          try {
            await navigator.clipboard.writeText(sk);
            showToast(`会话标识已复制：${sk}`);
          } catch {
            showToast(`会话标识为：${sk}`);
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
        const cur = bindingsMap[key] || {};
        if (cur.mode === targetMode) return;

        const modeLabels = {
          system: "已切换至强制遵守文档（系统提示词）模式。",
          workspace: "已切换至模拟工作区模式。",
          reference: "已切换至仅作参考资料模式。",
          none: "已切换至无（不注入文档）模式。",
        };

        try {
          await api.post("bindings/save", {
            session_key: key,
            doc_ids: (cur.docs || []).map((d) => (typeof d === "string" ? d : d.doc_id)),
            prompt: cur.prompt || "",
            shield: Boolean(cur.shield),
            force_system_prompt: Boolean(cur.force_system_prompt),
            mode: targetMode,
          });
          showToast(modeLabels[targetMode] || "模式已更新");
          await loadBindings();
        } catch (err) {
          showToast("生效模式切换失败：" + err.message);
        }
        return;
      }

      if (act === "edit") {
        const input = $("sessionKey");
        if (input) {
          input.value = key;
          loadExistingSessionSettings(key);
          window.scrollTo({ top: 180, behavior: "smooth" });
          showToast("会话配置已载入。");
        }
      } else if (act === "unbind") {
        try {
          showToast(`正在解除 ${key} 的文档绑定与相关配置，请稍候……`);
          await api.post("bindings/save", {
            session_key: key,
            doc_ids: [],
            prompt: "",
            shield: false,
            force_system_prompt: false,
            mode: "reference",
          });
          // 如果当前输入框恰好载入了该群，同步清空表单已勾选文档并禁用模式
          const curInputKey = ($("sessionKey")?.value || "").trim();
          if (curInputKey === key) {
            selectedDocIds.clear();
            renderDocChips();
          }
          showToast(`已解除 ${key} 的全部文档绑定。`);
          await loadBindings();
        } catch (err) {
          showToast("绑定解除失败：" + err.message);
        }
      }
    });
  }

  // ---- Bottom Sheet Document Reader (带切片缓存 + 下一片预取，翻页不再每次等网络) ----
  const readerCache = new Map(); // key: `${docId}:${chunk}` -> res，简单有界（最多 60 片）
  function readerCacheSet(k, v) {
    if (readerCache.size >= 60) {
      const oldest = readerCache.keys().next().value;
      readerCache.delete(oldest);
    }
    readerCache.set(k, v);
  }
  async function openReader(docId, chunk = 1) {
    currentReaderDoc = docId;
    currentReaderChunk = chunk;
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
      currentReaderTotal = res.total || 1;
      currentReaderChunk = res.chunk || chunk;
      if (titleEl) titleEl.textContent = res.meta?.filename || res.filename || docId;
      if (subEl) subEl.textContent = `切片 ${res.chunk} / ${res.total} (共 ${res.meta?.text_len || 0} 字)`;
      if (textEl) textEl.textContent = res.preview || "该切片暂无文本内容。";

      if (prevBtn) prevBtn.disabled = currentReaderChunk <= 1;
      if (nextBtn) nextBtn.disabled = currentReaderChunk >= currentReaderTotal;
      // 预取下一片：翻页更快，失败静默
      const next = currentReaderChunk + 1;
      if (next <= currentReaderTotal && !readerCache.has(`${docId}:${next}`)) {
        api.get("docs/content", { doc_id: docId, chunk: next }).then(
          (r) => readerCacheSet(`${docId}:${next}`, r),
          () => {}
        );
      }
    };

    const cached = readerCache.get(cacheKey);
    if (cached) {
      applyRes(cached);
      return;
    }
    try {
      const res = await api.get("docs/content", { doc_id: docId, chunk });
      readerCacheSet(cacheKey, res);
      // 用户已翻到别处则丢弃本次结果，避免乱序覆盖
      if (currentReaderDoc !== docId || currentReaderChunk !== chunk) return;
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
        if (currentReaderDoc && currentReaderChunk > 1) {
          openReader(currentReaderDoc, currentReaderChunk - 1);
        }
      });
    }

    const nextBtn = $("nextChunkBtn");
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        if (currentReaderDoc && currentReaderChunk < currentReaderTotal) {
          openReader(currentReaderDoc, currentReaderChunk + 1);
        }
      });
    }

    const copyBtn = $("copyChunkBtn");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        const textEl = $("readerText");
        const text = textEl ? textEl.textContent : "";
        if (!text) return;
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
          } else {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
          }
          showToast("切片文本已复制至剪贴板。");
        } catch (e) {
          showToast("文本复制失败，请手动选取并复制。");
        }
      });
    }

    const bindBtn = $("bindFromReaderBtn");
    if (bindBtn) {
      bindBtn.addEventListener("click", () => {
        if (currentReaderDoc) {
          selectedDocIds.add(currentReaderDoc);
          renderDocChips();
          closeReader();
          switchTab("tab-bindings");
          const input = $("sessionKey");
          if (input) input.focus();
          showToast("已选择该文档，请指定需要绑定的会话。");
        }
      });
    }
  }

  // ---- Backup Export / Import (bindings 原样 JSON，无额外格式) ----
  function initBackupButtons() {
    const exportBtn = $("exportBackupBtn");
    if (exportBtn) {
      exportBtn.addEventListener("click", async () => {
        try {
          showToast("正在导出绑定备份，请稍候……");
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
          showToast(`已导出 ${Object.keys(map).length} 个会话的绑定配置。`);
        } catch (err) {
          showToast("备份导出失败：" + err.message);
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
          showToast("所选文件并非合法的 JSON 格式。");
          return;
        }
        if (!map || typeof map !== "object" || Array.isArray(map) || !Object.keys(map).length) {
          showToast("备份文件中未包含绑定数据。");
          return;
        }
        const n = Object.keys(map).length;
        if (!(await uiConfirm(`将从备份导入 ${n} 个会话配置，并合并至现有配置，是否继续？`, "导入确认"))) return;
        const replace = await uiConfirm("是否覆盖现有全部配置？选择“覆盖”将替换现有配置，选择“取消”则仅合并新增项。", "覆盖现有配置");
        try {
          const res = await api.post(`bindings/import?mode=${replace ? "replace" : "merge"}`, map);
          const skipped = (res.skipped_docs || []).length;
          showToast(`已导入 ${res.applied || 0} 个会话的配置${skipped ? `，其中 ${skipped} 个文档不存在，已跳过` : ""}。`);
          await loadBindings();
          await searchGroups("");
        } catch (err) {
          showToast("备份导入失败：" + err.message);
        }
      });
    }
  }

  // ---- Plugin Settings (WebUI 配置页) ----
  let settingsMeta = {};
  let settingsConfig = {};

  async function loadSettings() {
    try {
      const res = await api.get("settings");
      settingsMeta = res.meta || {};
      settingsConfig = res.config || {};
      renderSettings();
      // 服务端配置是唯一真相源，回填完才揭开首帧
      if (applyUiPrefs(settingsConfig)) persistUiPrefs();
    } catch (e) {
      console.error("[DocMemory] loadSettings error:", e);
      showToast("插件设置获取失败：" + e.message);
    } finally {
      revealUiPrefs();
    }
  }

  function renderSettings() {
    const container = $("settingsForm");
    if (!container) return;
    // hidden 的 UI 偏好（主题色/深浅色）由顶栏控件维护，不进设置表单
    const keys = Object.keys(settingsMeta).filter((k) => !(settingsMeta[k] || {}).hidden);
    if (!keys.length) {
      container.innerHTML = `<span class="helper">当前暂无可配置项。</span>`;
      return;
    }

    container.innerHTML = keys.map((k) => {
      const m = settingsMeta[k] || {};
      const type = m.type || "int";
      const desc = m.description || k;
      const hint = m.hint || "";
      const val = settingsConfig[k];

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
    for (const [k, m] of Object.entries(settingsMeta)) {
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
    return out;
  }

  function applySettingsValues(src) {
    for (const [k, m] of Object.entries(settingsMeta)) {
      const val = src[k] !== undefined ? src[k] : m.default;
      if ((m.type || "int") === "bool") {
        const sw = document.querySelector(`[data-switch="${k}"]`);
        if (sw) sw.checked = Boolean(val);
      } else {
        const el = $("set_" + k);
        if (el) el.value = val === undefined || val === null ? "" : val;
      }
    }
  }

  function initSettings() {
    const container = $("settingsForm");
    if (container) {
      container.addEventListener("click", (e) => {
        const btn = e.target.closest(".segmented-choice-btn");
        if (!btn) return;
        const group = btn.closest(".segmented-choice");
        if (!group) return;
        group.querySelectorAll(".segmented-choice-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
      });
    }

    const saveBtn = $("saveSettingsBtn");
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        const config = collectSettings();
        try {
          const res = await api.post("settings/save", { config });
          settingsConfig = res.config || config;
          settingsMeta = res.meta || settingsMeta;
          renderSettings();
          showToast("插件设置已保存并生效。");
        } catch (err) {
          showToast("设置保存失败：" + err.message);
        }
      });
    }

    const resetBtn = $("resetSettingsBtn");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        applySettingsValues({});
        showToast("已填入默认值，保存后方可生效。");
      });
    }
  }

  // ---- Refresh All Data Button ----
  function initRefreshButton() {
    const btn = $("refreshAllBtn");
    if (!btn) return;

    btn.addEventListener("click", async () => {
      showToast("正在刷新全部数据，请稍候……");
      try {
        await Promise.all([loadDocs(), loadBindings(), loadSettings(), searchGroups("")]);
        showToast("全部数据已刷新完毕。");
      } catch (err) {
        showToast("部分数据刷新失败：" + err.message);
      }
    });
  }

  function _verCmp(a, b) {
    const pa = String(a).replace(/^v/i, "").split(".").map((n) => parseInt(n, 10) || 0);
    const pb = String(b).replace(/^v/i, "").split(".").map((n) => parseInt(n, 10) || 0);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      const d = (pa[i] || 0) - (pb[i] || 0);
      if (d) return d;
    }
    return 0;
  }

  function checkForUpdate() {
    try {
      const tag = document.querySelector(".version-tag");
      if (!tag) return;
      const local = String(tag.dataset.ver || "").trim().replace(/^v/i, "");
      if (!local) return;
      fetch("https://raw.githubusercontent.com/imsuperone/xbdoc/main/metadata.yaml", { cache: "no-store" })
        .then((r) => (r && r.ok ? r.text() : Promise.reject(new Error("bad response"))))
        .then((t) => {
          const m = /version:\s*["']?v?([0-9]+(?:\.[0-9]+)*)/i.exec(t || "");
          if (m && _verCmp(m[1], local) > 0) {
            const remote = String(m[1]).replace(/^v/i, "");
            tag.textContent = "检测到更新 " + remote + "  当前版本号 " + local;
          } else {
            tag.textContent = local;
          }
        })
        .catch((e) => {
          tag.textContent = local;
          console.warn("[DocMemory] update check skipped:", e);
        });
    } catch (e) {
      console.warn("[DocMemory] update check error:", e);
    }
  }

  // ---- App Startup Entry ----
  async function startApp() {
    console.log("[DocMemory] Starting Android 16 UI application...");

    // 1. Synchronous UI initialization (never blocks)
    initTheme();
    initAccentPicker();
    initAccentPopover();
    initTabs();
    initDocGridEvents();
    initDocSearch();
    initDropzone();
    initDocChipsEvents();
    initGroupSuggest();
    initDocMode();
    initShieldChoice();
    initForceChoice();
    initShieldFilter();
    initBindingForm();
    initBindingListEvents();
    initReaderEvents();
    initBackupButtons();
    initSettings();
    initRefreshButton();
    updatePromptCount();
    checkForUpdate();

    // 2. Connect with bridge if available
    try {
      await api.ready();
    } catch (e) {
      console.warn("[DocMemory] api.ready fallback:", e);
    }

    // 3. Load backend data
    try {
      await Promise.all([loadDocs(), loadBindings(), loadSettings(), searchGroups("")]);
      console.log("[DocMemory] Initial data loaded successfully.");
    } catch (e) {
      console.warn("[DocMemory] Initial data load partial failure:", e);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startApp);
  } else {
    startApp();
  }
})();
