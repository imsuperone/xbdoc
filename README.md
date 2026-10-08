# 文档记忆助手

📚 AstrBot 零 Embedding 文档记忆插件，WebUI 上传 md / txt / pdf / docx / json 文档，按群/私聊独立绑定，大模型对话自动引用。

-   📦 项目主页：[https://github.com/imsuperone/xbdoc](https://github.com/imsuperone/xbdoc)
-   🔌 插件 ID：`astrbot_plugin_xbdoc`
-   📌 版本：`v1.2.18`，要求 AstrBot `>=4.16`

---

## 🌟 核心特性

-   ⚡ **四大生效模式**：`system` 强制遵守（文档直灌系统提示词） / `workspace` 模拟工作区（`/workspace/` 沙箱挂载） / `reference` 仅作参考资料（提问时按需检索） / `none` 无（绑定但不注入，聊天端新建绑定默认）。
-   🧠 **零 Embedding 检索**：无需向量模型，多语言分词 + BM25（idf + 长度归一），切片词频全缓存，Top-K 注入。
-   👥 **按群彻底隔离**：会话 Key 归一（`group:` / `private:`），绑定、提示词、屏蔽、模式各群独立。
-   🏷️ **群专属提示词**：无文档也可独立生效；`shield` 清空原人格、`force` 强制唯一系统词，三模式下恰好生效一次。
-   🧹 **解绑即恢复出厂**：`/xbdoc unbind` 留空清空文档、提示词、屏蔽、强制注入，空配置条目彻底删除。
-   🧠 **历史强行遗忘**：`/xbdoc no` 截断此前全部上下文，`off` 恢复。
-   💻 **WebUI 管理台**：文档上传 / 预览 / 下载、群搜索（含适配器主动拉取）、绑定表单、模式直选、深浅主题、绑定备份导出 / 导入（合并或覆盖，不存在的文档自动跳过）。
-   📦 **改名无痛迁移**：`astrbot_plugin_doc_memory` / `xbdoc` 旧数据目录自动移动迁移。

---

## 🚀 安装

1.  AstrBot 后台 → **插件** → **从链接安装**，填入：
    
    https://github.com/imsuperone/xbdoc.git
    
2.  重启 AstrBot，插件自动加载（如需 PDF / DOCX 解析会自动安装 `requirements.txt` 依赖）。
3.  聊天发送 `/xbdoc` 查看菜单，WebUI 打开 `文档记忆助手` 页面传文档、绑群。

## 🚀 聊天指令（`/xbdoc` 群内管理，点开分组查看）

<details>
<summary>📖 查看</summary>

| 指令 | 说明 |
| --- | --- |
| `/xbdoc` | 完整菜单 |
| `/xbdoc status` | 本群绑定、模式、屏蔽、提示词状态 |
| `/xbdoc list` | 知识库文档与 ID |
| `/xbdoc workspace` | 工作区挂载清单 |
| `/xbdoc search <词>` | 检索绑定文档 |
| `/xbdoc read <ID> [n]` | 预览文档切片 |

</details>

<details>
<summary>🔗 绑定（管理员）</summary>

| 指令 | 说明 |
| --- | --- |
| `/xbdoc bind <ID...>` | 追加绑定，自动合并 |
| `/xbdoc unbind [ID...]` | 解绑；留空全清，提示词一并清除 |

</details>

<details>
<summary>🎛️ 模式（管理员，需先绑定文档）</summary>

| 指令 | 说明 |
| --- | --- |
| `/xbdoc mode s\|w\|r\|n` | 强制遵守 / 工作区 / 仅参考 / 无 |
| `/xbdoc shield on\|off` | 清空 / 保留原人格 |
| `/xbdoc force on\|off` | 专属提示词唯一生效 |

</details>

<details>
<summary>🏷️ 提示词（管理员）</summary>

| 指令 | 说明 |
| --- | --- |
| `/xbdoc prompt` | 查看本群配置详情 |
| `/xbdoc prompt_set <内容>` | 设置专属提示词 |
| `/xbdoc prompt_clear` | 清除专属提示词 |

</details>

<details>
<summary>🧹 历史（管理员）</summary>

| 指令 | 说明 |
| --- | --- |
| `/xbdoc no [off]` | 忘掉此前消息 / 恢复 |

</details>

---

## 📦 依赖

-   `pypdf >= 4.3.0`、`python-docx >= 1.1.2`（仅 PDF / DOCX 需要，纯文本、Markdown、JSON 开箱即用）
-   上传上限 50MB；切片长度 / 重叠 / Top-K / 注入上限 / 自动注入 / 未命中保底 / 私聊绑定 / 性能日志均可在 WebUI「插件设置」页调整。

## 🧾 备注

-   私聊独立绑定受 `allow_private_bind` 控制（默认开启），和机器人私聊一句后即可在 WebUI 搜到并绑定。
-   会话命名空间按 `group:平台:群号` / `private:平台:UID` 划分，跨平台同号群彻底隔离；WebUI 手填短格式（`group:123`）按 seen 自动补平台限定。
-   `/xbdoc mode` 支持 `s / w / r / n` 快捷（system / workspace / reference / none 无），未知模式会明确报错，不再静默回落。
-   聊天端新建绑定默认 `none`（无，不注入文档），与 WebUI 表单一致；存量绑定模式不受影响，需 `/xbdoc mode` 切换才恢复注入。
-   `force` 开启但专属提示词为空时不再清空原人格；`shield` 开启仍会清空（符合其语义）。
-   `/xbdoc forget` 等同于 `/xbdoc no`，同样仅管理员可用。
-   关闭 `auto_inject` 后不再自动检索文档，但专属提示词与屏蔽依然生效。
-   数据持久化在 `data/plugin_data/astrbot_plugin_xbdoc`（`index.json` / `bindings.json` / `seen_groups.json` / `plugin_config.json` / `docs/`）。
-   卸载重装不会丢数据；要彻底清零请先停服再删除上述数据目录。

---

## 🔌 接口总账（一接口一实现 · 2026-10-08 测绘）

全仓接口只有一条链路：**Web 13 条**在 `core/webapi.py:39-51` 单点注册；**聊天 15 组**走
`main.py:420` `/xbdoc` 单入口（派发表 `main.py:462-481`）；**LLM 面 2 工具 + 1 注入**。
三条路最终都只经 `core/store.py` 落盘（`bindings.json` / `index.json` / `plugin_config.json`），
检索统一走 `core/retrieval.py`（BM25，纯内存）。下表 file:line 为 2026-10-08 AST 实测。

### Web API（13 条）

| 方法 | 路径（前缀 `/astrbot_plugin_xbdoc/`） | HTTP 实现 | 数据出口（唯一） |
| --- | --- | --- | --- |
| GET | `/docs` | `webapi.py:72` | `store.py:561 list_documents` |
| POST | `/docs/upload` | `webapi.py:76` | `store.py:451 add_document`（线程池执行） |
| POST | `/docs/delete` | `webapi.py:146` | `store.py:522 delete_document` |
| GET | `/docs/content` | `webapi.py:158` | `store.py:568 _load_chunks` |
| GET | `/docs/download` | `webapi.py:173` | `docs/` 原文件 |
| GET | `/groups` | `webapi.py:651` | seen + 绑定合并视图 |
| POST/GET | `/groups/fetch` | `webapi.py:627` | 平台群拉取（与 `/groups?refresh=1` 同事双路，见审计 #6） |
| GET | `/bindings` | `webapi.py:184` | 内存 `_bindings` 加富视图 |
| POST | `/bindings/save` | `webapi.py:216` | `store.py:969 bind_docs` + `:999/:1007` |
| GET | `/bindings/export` | `webapi.py:274` | `_bindings` 快照 |
| POST | `/bindings/import` | `webapi.py:279` | `_merge_entries` + 落盘 |
| GET | `/settings` | `webapi.py:53` | `store.py:1035/1046` |
| POST | `/settings/save` | `webapi.py:59` | `store.py:1057 save_plugin_config` |

### 聊天指令（15 组，每组唯一函数，别名同函数无第二实现）

`main.py:462-481` 派发表 → `core/commands.py`：help `:43`、list `:67`、status `:87`、
workspace `:138`、bind `:176`、unbind `:212`、search `:271`、read `:292`、prompt `:319`、
mode `:345`、prompt_set `:396`、prompt_clear `:413`、shield `:442`、force `:468`、
no `:494`（别名 forget / clear_history / 重置记忆指向同一函数）。

### LLM 面（与聊天共用实现，非第二套）

| 接口 | 实现 | 复用 |
| --- | --- | --- |
| 工具 `doc_memory_search` | `main.py:360` | 与 `/xbdoc search` 同走 `main.py:60 retrieve` |
| 工具 `doc_memory_list` | `main.py:379` | 与 `/xbdoc list` 同走 `store.py:561` |
| 系统提示词注入 | `main.py:203 _inject_docs` | `main.py:151 build_inject_text` |

---

## 🏗️ 架构与数据流审计（2026-10-08）

分层摆法本身是对的：`main.py`（聊天 / LLM / 注入）与 `core/webapi.py`（HTTP）→
`core/store.py` 唯一持久出口 → `data/`，检索 `core/retrieval.py` 纯内存，**没有
ABCD 式过度拆分，也没有空转包装层**。以下为测绘出的数据反复传输与多实现
（收敛清单，附实测位置）：

| # | 事实 | 位置 | 收敛 |
| --- | --- | --- | --- |
| 1 | **WebUI 解绑与聊天解绑语义不一致**（唯一正确性级问题）：聊天清 `ignore_history`，WebUI 不清 → `/xbdoc no` 过的会话经 WebUI 解绑后剩空壳，与「解绑即恢复出厂」矛盾 | 清：`commands.py:229`；不清：`app.js:1456-1463`、`webapi.py:245-253`；prune 依赖：`store.py:990` | 服务端 `_api_save_binding` 统一清 |
| 2 | 保存→丢弃→重拉：`bindings/save` 返回完整条目客户端不用，立刻重取；`GET /bindings` 还算了无人消费的 `docs`（含 `list_documents()` 全量加锁排序） | `app.js:1264-1268`、`webapi.py:213`、`app.js:621` | save 响应即渲染，删多余字段 |
| 3 | 绑定写口不统一：`bindings.json` 落盘 16 处（10 处在 store 外）、条目直改 28 处 | `_save_json(bindings_path)`：`commands.py`×8、`webapi.py`×2、`store.py`×6 | 统一经 store 方法 |
| 4 | 「无文档 ⇒ 模式回落 reference」规则写 5 处 | `app.js:1252`、`webapi.py:254,319`、`store.py:1010,551` | 只留 store 一处 |
| 5 | 会话 Key 归一后端 7 实现 + 前端 2 实现 | `store.py:665,678,707,812,848,934,873`、`app.js:992,1222` | 只留 store 一份 |
| 6 | `/groups` 与 `/groups/fetch` 干同一件事，客户端还写了主备两连 | `webapi.py:651` vs `:627`、`app.js:941-945` | 合一条 |
| 7 | 上传 3 传输 × 3 解析（base64 / multipart files / form） | `webapi.py:84-117`、`api.js:156-198` | 留 multipart 一条 |
| 8 | handler 已持 `_save_lock` 又调 `@_locked` 方法（RLock 重入，无意义加锁）并持锁拼回复字符串 | `commands.py:190→196`、`webapi.py:240→243` | 锁只护状态改写 |
| 9 | 一条查询做 2-3 次完整会话解析 | `commands.py:89-91`、`store.py:947` | 一次解析取全部字段 |
| 10 | `doc_shield` 与 `doc_force` 逐行同构（各 24 行）；status / prompt / workspace 三处重拼同一状态 | `commands.py:442` vs `:468`；`:87/:319/:138` | 参数化合一、一个 `render_status()` |
| 11 | 死字段写而未读：`has_entry`、`first_seen`、`size`、`docs`、`platform`、`total`、`count`、`warning` | `store.py:964`、`webapi.py:213,205,662,634,646` | 删 |
| 12 | 热路径锁竞争：消息注入的缓存命中也要取放 `_save_lock`；上传 / 配置保存在锁内做磁盘写与批量 unlink | `store.py:571,626`、`:489,502,516`、`:1120-1124` | 锁内只护内存态，磁盘 I/O 出锁 |
