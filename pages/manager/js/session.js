// Document Memory Assistant - session module
// 服务端（core/store/sessions.py）是会话 key 唯一真源：/bindings 与 /groups 返回的键
// 均已规范化（kind:platform:ident）。本模块只做手动输入的「认领」：已有绑定按尾号
// 精确匹配（群聊优先），都没有则按可选前缀补全。
(function (App) {
  "use strict";
  const { state } = App;

  function claimBindingKey(v, opts) {
    const raw = (v || "").trim();
    if (!raw) return "";
    if (state.bindingsMap[raw]) return raw;
    const tail = raw.split(":").pop();
    const keys = Object.keys(state.bindingsMap);
    const tailEq = (k) => String(k || "").split(":").pop() === tail;
    const grp = keys.find((k) => k.startsWith("group:") && tailEq(k));
    if (grp) return grp;
    const priv = keys.find((k) => k.startsWith("private:") && tailEq(k));
    if (priv) return priv;
    const anyHit = keys.find(tailEq);
    if (anyHit) return anyHit;
    if (opts && opts.claimPrefix && /^\d{5,}$/.test(raw)) return opts.claimPrefix + "onebot:" + raw;
    return "";
  }

  App.claimBindingKey = claimBindingKey;
})(window.DocMemoryApp = window.DocMemoryApp || {});
