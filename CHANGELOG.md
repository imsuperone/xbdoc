# 更新日志

## v1.2.27

- 彻底统一 `aiocqhttp` / `aihttpcq` 与 `onebot` 会话标识，自动清洗 `webchat` 与 `probe` 脏会话条目，前后端按群号严格去重。
- 修复 OneBot 主动拉取群列表时的 `functools.partial` 陷阱与并发超时问题，支持热重载立即刷新子模块。
- 优化 WebUI 群聊选择表展示（仅显示纯群号）及移动端表格与开关自适应排版。

