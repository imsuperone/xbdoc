// xbdoc WebUI 网络层：桥接探测 + 后端 API + 上传/下载
// 被 app.js 依赖（index.html 里先加载本文件），通过 window.DocMemoryApi 暴露。
(function () {
  "use strict";

  const PLUGIN_ID = "astrbot_plugin_xbdoc";

  // ---- Safe Bridge & API Layer ----
  function getBridge() {
    try {
      if (window.AstrBotPluginPage && typeof window.AstrBotPluginPage.apiGet === "function") {
        return window.AstrBotPluginPage;
      }
      if (window.bridge && typeof window.bridge.apiGet === "function") {
        return window.bridge;
      }
      if (window.parent && window.parent.AstrBotPluginPage && typeof window.parent.AstrBotPluginPage.apiGet === "function") {
        return window.parent.AstrBotPluginPage;
      }
      if (window.parent && window.parent.bridge && typeof window.parent.bridge.apiGet === "function") {
        return window.parent.bridge;
      }
    } catch (e) {
      console.warn("[DocMemory] getBridge cross-frame check ignored:", e);
    }
    return null;
  }

  let _detectedPrefix = null;
  // 全局唯一的探测锁：首屏三个并发请求共享同一次探测，不再各扫 5 个前缀
  let _detectFlight = null;

  const GET_PREFIXES = [
    `/${PLUGIN_ID}/`,
    `/api/plugins/${PLUGIN_ID}/`,
    `api/`,
    `./api/`,
    `./`,
  ];
  const POST_PREFIXES = [
    `/${PLUGIN_ID}/`,
    `/api/plugins/${PLUGIN_ID}/`,
    `api/`,
    `./api/`,
    `./`,
  ];

  async function tryFetchJson(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
      const errText = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${errText || res.statusText}`);
    }
    return await res.json();
  }

  // 带并发合并的前缀请求：已有探测结果直连；已有扫描在飞则等它结束复用结果；
  // 都没有才自己扫一遍。首屏三个并发请求只产生一次扫描。
  async function _requestWithPrefixes(prefixes, urlOf, options) {
    if (_detectedPrefix) {
      try {
        return await tryFetchJson(urlOf(_detectedPrefix), options);
      } catch (e) {}
    }
    if (_detectFlight) {
      try {
        await _detectFlight;
      } catch (e) {}
      if (_detectedPrefix) {
        try {
          return await tryFetchJson(urlOf(_detectedPrefix), options);
        } catch (e) {}
      }
    }
    const flight = (async () => {
      for (const p of prefixes) {
        try {
          const r = await tryFetchJson(urlOf(p), options);
          _detectedPrefix = p;
          return r;
        } catch (e) {}
      }
      throw new Error("__no_prefix__");
    })();
    _detectFlight = flight;
    try {
      return await flight;
    } finally {
      if (_detectFlight === flight) _detectFlight = null;
    }
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const res = String(reader.result || "");
        resolve(res.includes(",") ? res.split(",")[1] : res);
      };
      reader.onerror = (e) => reject(e);
      reader.readAsDataURL(file);
    });
  }

  const api = {
    async ready() {
      const b = getBridge();
      if (b && typeof b.ready === "function") {
        try {
          await b.ready();
        } catch (e) {
          console.warn("[DocMemory] bridge.ready error:", e);
        }
      }
    },

    async get(endpoint, params = {}) {
      const cleanParams = { ...params };
      const b = getBridge();
      if (b && typeof b.apiGet === "function") {
        return await b.apiGet(endpoint, cleanParams);
      }

      const qs = new URLSearchParams(cleanParams).toString();
      const queryStr = qs ? `?${qs}` : "";

      try {
        return await _requestWithPrefixes(GET_PREFIXES, (p) => `${p}${endpoint}${queryStr}`, undefined);
      } catch (e) {
        throw new Error(`无法连接至插件后端 API (${endpoint})`);
      }
    },

    async post(endpoint, data = {}) {
      const b = getBridge();
      if (b && typeof b.apiPost === "function") {
        return await b.apiPost(endpoint, data);
      }

      const options = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      };

      try {
        return await _requestWithPrefixes(POST_PREFIXES, (p) => `${p}${endpoint}`, options);
      } catch (e) {
        throw new Error(`请求后端失败 (${endpoint})`);
      }
    },

    async upload(endpoint, file) {
      // 上传唯一链路：base64 JSON 直传（与后端 _api_upload_doc 一一对应）。
      // 决策记录（审计行 #7）：方向列原定「保留文件表单通道一条」，但实测 iframe 跨域下
      // 表单对象跨文档克隆失效、文件字段名与后端解析不匹配（本文件历史注释记载的实测 bug），
      // base64 才是可靠路径，且旧后端 base64 本就支持 50MB 源文件上限——故定案 base64-only，
      // 方向列被实测约束否决。
      // 不再静默 fallback：失败直接抛错，由调用方 toast 展示。
      if (!file) {
        throw new Error("上传请求未成功发送：缺少文件");
      }
      let b64;
      try {
        b64 = await fileToBase64(file);
      } catch (e) {
        throw new Error("上传请求未成功发送：文件读取失败");
      }
      if (!b64) {
        throw new Error("上传请求未成功发送：文件内容为空");
      }
      try {
        return await api.post(endpoint, {
          filename: file.name,
          file_base64: b64,
        });
      } catch (e) {
        throw new Error(`上传请求未成功发送：${e.message}`);
      }
    },

    async download(endpoint, params = {}) {
      const b = getBridge();
      if (b && typeof b.download === "function") {
        return await b.download(endpoint, params);
      }

      const qs = new URLSearchParams(params).toString();
      // 已探测前缀优先，其次走标准 POST 前缀表（与 upload 共用，不再各写一份）
      const prefixes = _detectedPrefix
        ? [_detectedPrefix, ...POST_PREFIXES]
        : POST_PREFIXES;
      const pfx = prefixes[0];
      const url = `${pfx}${endpoint}${qs ? "?" + qs : ""}`;

      const link = document.createElement("a");
      link.href = url;
      link.download = "";
      link.target = "_blank";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    },
  };

  window.DocMemoryApi = api;
})();
