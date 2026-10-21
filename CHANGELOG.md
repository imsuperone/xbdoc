# 更新日志 (Changelog)

## v1.2.33 (2026-10-21)

- **版本获取接口统一规范**：
  - 新增标准 `GET /astrbot_plugin_xbdoc/version` 统一版本查询路由，单源自 `metadata.yaml`；
  - 确保与全系插件（xbnext, xbbot_beta, xbimg, xb2img）一致，支持多仓统一版本检测与强制更新。
- **平台标识与检索优化**：
  - 规范统一 `aiocqhttp` / `onebot` 平台标识映射，避免群列表与会话记录产生重复冗余。

## v1.2.32 (2026-10-13)

- **修复 Google Gemini 499 / 上下文错误**：修复开启「屏蔽原人格 (`shield`)」或「强制替换系统词 (`force_system_prompt`)」时向 `req.contexts` 列表额外插入 `{"role": "system"}` 消息字典导致 Gemini 报错（400/499 上下文错误）、系统词重复发送双份以及 `/new` 新对话后仍显示「上下文 1 条」的问题。
- **历史切断清理优化**：`/xbdoc no` 开启时彻底清空 `contexts` 与 `messages` 列表，避免残留 `system` 消息干扰后续模型请求。
