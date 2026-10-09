# 文档记忆助手 v1.2.25

> 面向 AstrBot 的知识库插件：上传文档，对话时按需引用，无需向量模型。

## 简介

支持 md / txt / pdf / docx / json 文档，经 WebUI 上传后按群或私聊独立绑定；检索采用多语言分词与 BM25，纯内存计算，不依赖 Embedding 模型。

本插件基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 开发。AstrBot 是一个松耦合、异步、支持多消息平台部署，具有易用的插件系统和完善的大语言模型（LLM）接入功能的聊天机器人及开发框架，使用文档见 [docs.astrbot.app](https://docs.astrbot.app)。

- 插件 ID：`astrbot_plugin_xbdoc`
- 当前版本：`v1.2.25`
- 运行要求：AstrBot `>=4.16`
- 仓库：https://github.com/imsuperone/xbdoc

## 功能

- 生效模式：`system` 强制遵守、`workspace` 工作区模拟、`reference` 按需参考、`none` 不注入（新建绑定默认）。
- 会话隔离：绑定、提示词、屏蔽、模式按群或私聊独立保存，互不影响。
- 专属提示词：`shield` 清空原人格，`force` 让专属提示词唯一生效。
- 解绑恢复：留空解绑清空文档、提示词与开关，恢复出厂状态。
- 文档管理：WebUI 上传、预览、下载、群搜索与备份导入导出。
- 旧数据迁移：自动迁移 `astrbot_plugin_doc_memory` 与 `xbdoc` 旧数据目录。

## 安装

1. AstrBot 后台 → 插件 → 从链接安装 `https://github.com/imsuperone/xbdoc.git`；
2. 重启 AstrBot，PDF / DOCX 解析依赖会自动安装。

## 指令

| 指令 | 说明 |
| :--- | :--- |
| `/xbdoc` | 完整菜单 |
| `/xbdoc status` | 本群绑定与模式状态 |
| `/xbdoc list` | 知识库文档列表 |
| `/xbdoc workspace` | 工作区挂载清单 |
| `/xbdoc search <词>` | 检索绑定文档 |
| `/xbdoc read <ID> [n]` | 预览文档切片 |
| `/xbdoc bind <ID...>` / `unbind [ID...]` | 绑定 / 解绑（管理员；解绑留空全清） |
| `/xbdoc mode s\|w\|r\|n` | 切换生效模式（管理员） |
| `/xbdoc shield on\|off` / `force on\|off` | 屏蔽原人格 / 专属提示词唯一生效（管理员） |
| `/xbdoc prompt` / `prompt_set <内容>` / `prompt_clear` | 专属提示词（管理员） |
| `/xbdoc no [off]` | 忘掉此前消息 / 恢复（管理员） |

## 说明

- `mode` 支持 `s / w / r / n` 快捷参数，未知模式明确报错，不静默回落。
- 新建绑定默认 `none`，存量绑定模式不变，需 `mode` 切换才恢复注入。
- 私聊绑定由 `allow_private_bind` 控制（默认开启）；关闭 `auto_inject` 后不自动检索，专属提示词与屏蔽仍生效。
- 依赖 `pypdf`、`python-docx`（仅 PDF / DOCX 需要），上传上限 50MB。
- 数据位于 `data/plugin_data/astrbot_plugin_xbdoc`，卸载重装不丢数据。
- 许可证：MIT，见 [LICENSE](./LICENSE)。
