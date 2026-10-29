# 更新日志 (Changelog)

## v1.2.36 (2026-10-29)

- **浏览器端到端验证（真实前端 × 真实后端逻辑）**：搭建本地冒烟服务（`tests/webui_smoke.py`，本地件），用 Chrome 无头浏览器实测全部页面链路——首屏渲染、文档预览翻页、绑定载入与模式切换保存、平台勾选/自定义平台同步、设置落盘、base64 上传入库与删除，零 pageerror、零业务 4xx/5xx；过程中抓出并修复 `groups.js` 行模板残留的 `isBound` 悬空引用（该缺陷会导致群表与绑定列表整体渲染失败，语法检查无法发现）。
- **兼容层对照 AstrBot v4.29.3 本体逐一核实**：`register_web_api`/`json_response`/`error_response`/`file_response`/`PluginRequest.json(default)`/`query.get(k,d,type=)` 签名全部吻合；桥接 `AstrBotPluginPage.apiGet` 直传响应体（父端 `a.data?.data ?? a.data`），删除 `res.data?.` 兜底正确；插件页 iframe 沙箱确无 `allow-same-origin`，localStorage 必然抛错，主题偏好落服务端为必要设计；真实框架 Python 下插件导入成功，两个 LLM 工具被真实装饰器注册。
- **修复 WebUI 平台选择崩溃**：设置页 `savePlatformSelection` 引用了未定义变量 `_customPlatforms`，勾选平台/添加自定义平台全部报错失效；现正确读写 `state.customPlatforms`（浏览器端到端实测通过）。
- **修复注入阻塞事件循环**：参考资料 / 强制遵守 / 工作区模式的文档读取与检索（冷缓存需解 PDF、全量分词，秒级）改走线程池，不再卡住 AstrBot 整个事件循环（与 `/xbdoc read`、WebUI 预览同口径）。
- **修复网络层重复请求**：前缀探测成功后，请求失败不再对全部前缀重发同一请求（此前业务报错会被重放多遍并掩盖为「无法连接」）；真实错误原样透出。
- **修复 `/xbdoc prompt_clear` 提示**：未设置提示词时如实回「未设置」，不再误报「已清空」。
- **架构收敛（一接口一实现）**：
  - 检索编排 `retrieve` / `build_inject_text` 从 `main.py` 移入 `core/store/search.py`，`main.py` 只剩入口 + LLM 钩子 + 指令分发；
  - 平台别名只在 `_clean_platform` 一处，`is_platform_allowed` 改为预设串展开（`onebot` / `onebot_matrix` / `custom`），删除 30 行硬编码白名单；
  - `_clean_platform` 输出统一小写（平台 id 规范形），`WebChat`/`OneBot` 等大小写混写在 seen 记录、白名单、key 归一全部一致，存量混写 key 加载时自动迁移；
  - seen 记录群/私两份合并为 `_record_seen` 单实现；会话解析候选表合并为 `_candidate_keys`（`_session_keys` 删除）；
  - 三个缓存桶的「LRU 上限 + 写后复验」抽成 `_cache_put`；
  - WebUI 群合并视图 `_get_all_merged_groups` 由 115 行双份分支收紧为一份，绑定空壳不再覆盖 seen 展示信息，session_key 接管规则确定化（旧实现受 set 遍历序影响）。
- **冗余清理**：前端删除对服务端已规范化 key 的二次归一与合并循环（`strongerMode` / `_MODE_PRIORITY` / `normalizeSessionKeyClient` 随之移除）；`res.data?.` 双层兜底、`/bindings/save` 回包冗余字段、10 余个仅模块内使用的 `App.*` 导出、4 个死 CSS 类、函数内重复 import 一并删除；首屏绑定预取不再等 200ms 定时器。
- **文档对齐**：README 删除不存在的「旧数据迁移」声明；接口总账重建于 `aidocs/ARCHITECTURE.md`（Web 13 条 / 聊天 15 组 / LLM 2 工具 + 1 注入，一接口一实现对照）。

## v1.2.35 (2026-10-28)

- **架构拆分（无行为变更）**：
  - `core/store.py` 拆为 `core/store/` 包：`common` / `persistence` / `documents` / `sessions` / `config` 五个模块，`XbdocStoreMixin` 作为聚合出口保持外部导入不变；
  - `pages/manager/app.js` 拆为 `pages/manager/js/` 下 10 个按序加载的经典脚本模块（`shared` / `toast` / `session` / `theme` / `docs` / `groups` / `bindings` / `reader` / `settings` / `version`），共享状态集中到 `App.state`；
  - 插件热重载列表同步覆盖 `core.store` 子模块。
- **修复沙箱主题失效**：AstrBot 插件页 iframe 无 `allow-same-origin`，`localStorage` 抛异常时 `initTheme` 会整体中断，导致深浅色切换按钮无响应；现仅将缓存读取包进 try，主题应用与事件绑定照常执行。

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
