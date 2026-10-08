# 文档记忆助手

AstrBot 零 Embedding 文档记忆插件：WebUI 上传 md / txt / pdf / docx / json 文档，按群 / 私聊独立绑定，对话时自动引用检索结果。

本插件基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) —— 开源的一站式 Agent 聊天机器人平台，支持主流 IM 平台与多种大模型接入，内置 WebUI 与插件扩展体系。使用文档见 [docs.astrbot.app](https://docs.astrbot.app)。

- 项目主页：https://github.com/imsuperone/xbdoc
- 插件 ID：`astrbot_plugin_xbdoc`
- 当前版本：`v1.2.22`（要求 AstrBot `>=4.16`）

## 核心特性

- 四种生效模式：`system` 强制遵守 / `workspace` 工作区模拟 / `reference` 按需参考 / `none` 不注入（新建绑定默认）。
- 零 Embedding 检索：无需向量模型，多语言分词 + BM25（idf + 长度归一），切片词频全缓存，Top-K 注入。
- 按群彻底隔离：绑定、提示词、屏蔽、模式按会话独立，跨平台同号群互不干扰。
- 群专属提示词：无文档也可独立生效；`shield` 清空原人格、`force` 强制唯一系统词。
- 解绑即恢复出厂：`/xbdoc unbind` 留空清空文档、提示词、屏蔽、强制注入，空配置条目彻底删除。
- 历史遗忘：`/xbdoc no` 截断此前全部上下文，`off` 恢复。
- WebUI 管理台：文档上传 / 预览 / 下载、群搜索、绑定表单、模式直选、深浅主题、绑定备份导出 / 导入（合并或覆盖，不存在的文档自动跳过）。
- 旧数据目录自动迁移（`astrbot_plugin_doc_memory` / `xbdoc`）。

## 安装

1. AstrBot 后台 → 插件 → 从链接安装，填入 `https://github.com/imsuperone/xbdoc.git`；
2. 重启 AstrBot（解析 PDF / DOCX 时会自动安装 `requirements.txt` 依赖）；
3. 聊天发送 `/xbdoc` 查看菜单，WebUI 打开「文档记忆助手」页面传文档、绑群。

## 聊天指令（`/xbdoc` 群内管理）

<details>
<summary>指令总览</summary>

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
<summary>绑定（管理员）</summary>

| 指令 | 说明 |
| --- | --- |
| `/xbdoc bind <ID...>` | 追加绑定，自动合并 |
| `/xbdoc unbind [ID...]` | 解绑；留空全清，提示词一并清除 |

</details>

<details>
<summary>模式（管理员，需先绑定文档）</summary>

| 指令 | 说明 |
| --- | --- |
| `/xbdoc mode s\|w\|r\|n` | 强制遵守 / 工作区 / 仅参考 / 无 |
| `/xbdoc shield on\|off` | 清空 / 保留原人格 |
| `/xbdoc force on\|off` | 专属提示词唯一生效 |

</details>

<details>
<summary>提示词（管理员）</summary>

| 指令 | 说明 |
| --- | --- |
| `/xbdoc prompt` | 查看本群配置详情 |
| `/xbdoc prompt_set <内容>` | 设置专属提示词 |
| `/xbdoc prompt_clear` | 清除专属提示词 |

</details>

<details>
<summary>历史（管理员）</summary>

| 指令 | 说明 |
| --- | --- |
| `/xbdoc no [off]` | 忘掉此前消息 / 恢复 |

</details>

## 依赖

- `pypdf >= 4.3.0`、`python-docx >= 1.1.2`（仅 PDF / DOCX 需要，纯文本、Markdown、JSON 开箱即用）；
- 上传上限 50MB；切片长度 / 重叠 / Top-K / 注入上限 / 自动注入 / 未命保底 / 私聊绑定等均可在 WebUI「插件设置」页调整。

## 备注

- 私聊独立绑定受 `allow_private_bind` 控制（默认开启），和机器人私聊一句后即可在 WebUI 搜到并绑定。
- 会话命名空间按 `group:平台:群号` / `private:平台:UID` 划分，跨平台同号群彻底隔离；WebUI 手填短格式（`group:123`）按 seen 自动补平台限定。
- `/xbdoc mode` 支持 `s / w / r / n` 快捷（system / workspace / reference / none 无），未知模式会明确报错，不静默回落。
- 新建绑定默认 `none`（不注入文档）：聊天端、WebUI 表单与后端缺省一致；存量绑定模式不受影响，需 `/xbdoc mode` 切换才恢复注入。
- `force` 开启但专属提示词为空时不会清空原人格；`shield` 开启仍会清空（符合其语义）。
- `/xbdoc forget` 等同于 `/xbdoc no`，同样仅管理员可用。
- 关闭 `auto_inject` 后不再自动检索文档，但专属提示词与屏蔽依然生效。
- 数据持久化在 `data/plugin_data/astrbot_plugin_xbdoc`（`index.json` / `bindings.json` / `seen_groups.json` / `plugin_config.json` / `docs/`）。
- 卸载重装不会丢数据；要彻底清零请先停服再删除上述数据目录。

## 更新日志

见 [CHANGELOG.md](./CHANGELOG.md)。
