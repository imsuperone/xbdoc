// Document Memory Assistant - version module
(function (App) {
  "use strict";
  const { $, state } = App;

function initRefreshButton() {
  const btn = $("refreshAllBtn");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    App.showToast("正在刷新全部数据，请稍候……");
    try {
      await Promise.all([App.loadDocs(), App.loadBindings(), App.loadSettings(), App.searchGroups("")]);
      App.showToast("全部数据已刷新完毕。");
    } catch (err) {
      App.showToast("部分数据刷新失败：" + err.message);
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

async function fetchAndApplyVersion() {
  try {
    const res = await window.DocMemoryApi.get("version");
    if (res && res.version) {
      document.querySelectorAll(".version-tag").forEach((el) => {
        el.textContent = res.version;
        el.dataset.ver = res.version;
      });
    }
  } catch (_) {}
}

function checkForUpdate() {
  try {
    const tag = document.querySelector(".version-tag");
    if (!tag) return;
    const local = String(tag.dataset.ver || "").trim().replace(/^v/i, "");
    if (!local) return;
    const ctrl = typeof AbortController === "function" ? new AbortController() : null;
    const timer = ctrl ? setTimeout(() => { try { ctrl.abort(); } catch (_) {} }, 4000) : null;
    fetch("https://raw.githubusercontent.com/imsuperone/xbdoc/main/metadata.yaml", {
      cache: "no-store",
      signal: ctrl ? ctrl.signal : undefined,
    })
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
      })
      .finally(() => { if (timer) clearTimeout(timer); });
  } catch (e) {
    console.warn("[DocMemory] update check error:", e);
  }
}

  App.initRefreshButton = initRefreshButton;
  App.fetchAndApplyVersion = fetchAndApplyVersion;
  App.checkForUpdate = checkForUpdate;
})(window.DocMemoryApp = window.DocMemoryApp || {});
