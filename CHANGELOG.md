# 更新日志 (Changelog)

## v1.2.34 (2026-10-28)

- **WebUI 页面元数据补全**：`metadata.yaml` 新增 `pages` 声明，控制台页面标题由默认的 `manager` 变为「文档记忆」。
- **前后端一致性修复**：
  - 前端平台别名表与后端 `_clean_platform` 对齐（补 `onebot*` / `chronocat` 等），消除同一 key 前后端归一结果不一致；
  - 绑定列表合并 mode 时改为按 `_MODE_PRIORITY` 取更强项，与后端 `_merge_entries` 一致。
- **`/xbdoc no yes` 语义修正**：`yes` 不再被当作“恢复历史”，与 `/xbdoc no on` 的直觉一致。
- **性能**：`/xbdoc read` 与 WebUI 文档预览改为线程池读取分片，避免大文档首次加载阻塞事件循环。
- **WebUI 网络层**：GET/POST 前缀表合并为一份；请求默认 60 秒超时（上传 5 分钟）；下载前确保前缀已探测，修复非默认前缀下下载 404。
- **版本号**：读不到 `metadata.yaml` 时返回 `unknown`，不再回退到写死的旧版本号。

## v1.2.33 (2026-10-21)

- **版本获取接口统一规范**：
  - 新增标准 `GET /astrbot_plugin_xbdoc/version` 统一版本查询路由，单源自 `metadata.yaml`；
  - 确保与全系插件（xbnext, xbbot_beta, xbimg, xb2img）一致，支持多仓统一版本检测与强制更新。
- **平台标识与检索优化**：
  - 规范统一 `aiocqhttp` / `onebot` 平台标识映射，避免群列表与会话记录产生重复冗余。

## v1.2.32 (2026-10-13)

- **修复 Google Gemini 499 / 上下文错误**：修复开启「屏蔽原人格 (`shield`)」或「强制替换系统词 (`force_system_prompt`)」时向 `req.contexts` 列表额外插入 `{"role": "system"}` 消息字典导致 Gemini 报错（400/499 上下文错误）、系统词重复发送双份以及 `/new` 新对话后仍显示「上下文 1 条」的问题。
- **历史切断清理优化**：`/xbdoc no` 开启时彻底清空 `contexts` 与 `messages` 列表，避免残留 `system` 消息干扰后续模型请求。
