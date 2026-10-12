# 更新日志

## v1.2.31

- 优化会话绑定标准化与读取性能：`_normalize_bindings` 预计算规范化键集合，将合并查重复杂度由 $O(B^2)$ 降至 $O(B)$；只读接口 `_api_list_bindings` 与 `_get_all_merged_groups` 直接复用已标准化内存表，消除每次查询的整表二次克隆。
- 精简 WebUI 冗余结构与请求：移除 `index.html` 与 `app.js` 中已废弃的隐藏分段按钮 DOM 及监听，将列表内切换生效模式与解绑改为就地更新 `bindingsMap`，减少整表重拉请求。

## v1.2.30

- 修复 LLM 工具 `doc_memory_list` 与 `doc_memory_search` 使用 `yield event.plain_result(...)` 导致 AstrBot Agent 工具循环把结果直接作为聊天消息发入群聊（从而触发转图发送两张图片）的严重问题，改为标准 `return str` 返回给模型。
- 新增单次请求级工具按需裁剪：当本群/本会话未绑定任何文档或生效模式非 `reference` 时，自动从当前 LLM 请求的 `func_tool` 列表中隐藏 `doc_memory_list` / `doc_memory_search`，杜绝模型无意义调用。
- 修复跨平台同号会话在 `_session_keys` 与 `_resolve_session` 中误回落到 `onebot` 命名空间的问题。

## v1.2.29

- 重构群聊选择表为与 `xbnext` / `xbimg` 一致的无滚动条三列固定布局（`群聊名称` / `群号` / `操作`），移除冗余拥挤的「当前状态」列，移动端无需左右拖动即可完整展示。
- 隐藏内部滚动容器滚动条，并优化移动端表单行与按钮组自适应排版。

## v1.2.28

- 大幅优化 WebUI 首屏与切换页签加载速度：主题与强调色支持本地预读秒开（兜底等待降至 150ms），优先加载核心设置与文档库，群聊绑定列表改为按需懒加载 + 后台预热，版本更新检测移至后台异步执行。
- 统一 WebUI 开关样式与移动端适配：将「强制注入系统提示词」与「本群屏蔽 AstrBot 人格」改为与 `xbnext` 同款的无框行内滑动开关（`.m3-switch`），修复移动端搜索框与设置网格溢出问题。

## v1.2.27

- 彻底统一 `aiocqhttp` / `aihttpcq` 与 `onebot` 会话标识，自动清洗 `webchat` 与 `probe` 脏会话条目，前后端按群号严格去重。
- 修复 OneBot 主动拉取群列表时的 `functools.partial` 陷阱与并发超时问题，支持热重载立即刷新子模块。
- 优化 WebUI 群聊选择表展示（仅显示纯群号）及移动端表格与开关自适应排版。


