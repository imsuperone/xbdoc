// Document Memory Assistant - shared runtime (window.DocMemoryApp)
// AstrBot 插件页运行在 sandbox="allow-scripts" 的 iframe 中：
// 不使用 ES module（跨源 import 会被 CORS 拦截），改用按序加载的经典脚本 + 单一命名空间。
(function () {
  "use strict";

  const App = (window.DocMemoryApp = window.DocMemoryApp || {});

  // api.js 先行加载（index.html 中排在所有模块之前），此处只取引用
  App.api = window.DocMemoryApi;
  if (!App.api) {
    throw new Error("[DocMemory] api.js 未加载，请检查 index.html 的 script 顺序");
  }

  App.$ = (id) => document.getElementById(id);

  App.esc = function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  };

  // 跨模块共享的运行时状态（原 app.js 顶部的散落变量集中于此）
  App.state = {
    docsList: [],
    bindingsMap: {},
    groupsCache: [],
    selectedDocIds: new Set(),
    loadedSessionKey: "",
    promptDirty: false,
    currentReaderDoc: null,
    currentReaderChunk: 1,
    currentReaderTotal: 1,
    currentShield: "off",
    currentDocMode: "none",
    currentForcePrompt: false,
    currentBindingFilter: "all",
    bindingsPrefetched: false,
    suggestTimer: null,
    suggestSeq: 0,
    uiPrefTimer: null,
    settingsMeta: {},
    settingsConfig: {},
    customPlatforms: [],
    readerCache: new Map(),
  };
})();
