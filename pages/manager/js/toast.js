// Document Memory Assistant - toast module
(function (App) {
  "use strict";
  const { state } = App;

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

function _toastTypeOf(msg, explicit) {
  if (explicit === "ok" || explicit === "bad" || explicit === "info") return explicit;
  const s = String(msg ?? "");
  if (/失败|错误|异常|超出|并非|不支持|无法|不存在|未包含|超时|未检出|非法/.test(s)) return "bad";
  if (/请先|请填写|请稍候|请至少|正在|尚未|暂未/.test(s)) return "info";
  if (/已|成功|完成|就绪|生效|完毕|恢复默认/.test(s)) return "ok";
  return "info";
}

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

  App._copyText = _copyText;
  App.showToast = showToast;
  App.uiConfirm = uiConfirm;
})(window.DocMemoryApp = window.DocMemoryApp || {});
