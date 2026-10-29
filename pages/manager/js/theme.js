// Document Memory Assistant - theme module
(function (App) {
  "use strict";
  const { $, api, state } = App;

  const _ACCENT_VARS = ["--m3-sys-color-primary", "--m3-sys-color-on-primary", "--m3-sys-color-primary-container", "--m3-sys-color-surface", "--m3-sys-color-surface-container", "--m3-sys-color-surface-container-high", "--m3-sys-color-surface-container-highest", "--m3-seg-ink"];

function initTheme() {
  // AstrBot 沙箱 iframe 无 allow-same-origin：localStorage 读取会抛 SecurityError。
  // 这里只把「读缓存」包起来，后续主题应用与事件绑定必须照常执行（否则切换按钮失效）。
  let cached = "";
  try {
    cached = localStorage.getItem("xbdoc_ui_theme") || "";
  } catch (e) {}
  if (cached === "dark" || cached === "light") {
    applyTheme(cached);
  } else {
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(prefersDark ? "dark" : "light");
  }

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
      App.showToast(`当前界面已切换为${next === "dark" ? "深色" : "浅色"}模式。`);
    });
  }
  // 取色回填交给紧随其后的 initAccentPicker() → applyUiPrefs()（服务端配置），不在这里动。
}

function applyTheme(theme) {
  const mode = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", mode);
  try { localStorage.setItem("xbdoc_ui_theme", mode); } catch (e) {}
  const icon = $("themeIcon");
  if (!icon) return;
  if (mode === "dark") {
    icon.innerHTML = `<path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1zM5.99 4.58c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58zm12.37 12.37c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41l-1.06-1.06zm1.06-10.96c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06zM7.05 18.36c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06z"/>`;
  } else {
    icon.innerHTML = `<path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9 9-4.03 9-9c0-.46-.04-.92-.1-1.36-.98 1.37-2.58 2.26-4.4 2.26-2.98 0-5.4-2.42-5.4-5.4 0-1.81.89-3.42 2.26-4.4-.44-.06-.9-.1-1.36-.1z"/>`;
  }
}

function mixHex(hexA, hexB, ratio) {
  const toRgb = (h) => [1, 3, 5].map((i) => parseInt(h.substr(i, 2), 16));
  const a = toRgb(hexA), b = toRgb(hexB);
  const mixed = a.map((v, i) => Math.round(v * ratio + b[i] * (1 - ratio)));
  return "#" + mixed.map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, "0")).join("");
}

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
    try { localStorage.setItem("xbdoc_ui_accent", v); } catch (e) {}
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
      App.showToast("已恢复默认主题颜色。");
    });
  }
}

function revealUiPrefs() {
  try { document.documentElement.removeAttribute("data-boot"); } catch (e) {}
}

function persistUiPrefs() {
  if (state.uiPrefTimer) clearTimeout(state.uiPrefTimer);
  state.uiPrefTimer = setTimeout(() => {
    state.uiPrefTimer = null;
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

  App.initTheme = initTheme;
  App.initAccentPicker = initAccentPicker;
  App.revealUiPrefs = revealUiPrefs;
  App.persistUiPrefs = persistUiPrefs;
  App.applyUiPrefs = applyUiPrefs;
  App.initAccentPopover = initAccentPopover;
})(window.DocMemoryApp = window.DocMemoryApp || {});
