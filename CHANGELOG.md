# 更新日志

## v1.2.20 — 2026-10-08

- 🔧 **绑定写口全数收归 store（审计 #3/#8）**：`bindings.json` 落盘与条目直改收敛为唯一写口（`bind_docs_report` / `save_binding_payload` / `unbind_docs` / `set_session_prompt` / `set_session_flag`），commands 侧 8 处行级锁与裸落盘归零——读判锁外、写口锁内改+落盘、回复一律出锁拼，`@_locked` 重入嵌套消失。
- 🔧 **「无文档 ⇒ reference」单源（审计 #4）**：`store._effective_mode` 为全插件唯一回落（保存/导入/删文档/状态读取全走它），前端复写规则删除。
- 🔧 **save 响应即渲染（审计 #2）**：抽共享 `_binding_entry_view`（`GET /bindings` 与 save 回包同源），回包带 `entry`（prune 时 null），前端直更本地映射，删「保存→丢弃→重拉」；顶层 `docs`/`platform` 无人消费字段删除。
- 🔧 **会话 Key 认领合一（审计 #5）**：`claimBindingKey` 统一选择载入与保存前认领，tie-break 固定为 精确键 → group → private → 任意尾段 →（保存路径）纯数字补前缀。
- 🔧 **/groups 刷新单入口（审计 #6）**：删主备两连 fallback，唯一 `POST groups/fetch`；`GET /groups` 降为只读搜索。
- 🔧 **上传 base64 单链（审计 #7）**：前后端收敛为 base64 JSON 一条，删 FormData/多前缀探测与静默 fallback，失败细分四类报错，50MB 源文件上限保留；决策记录：iframe 跨域表单对象克隆失效是实测 bug，方向列「留 multipart 一条」被实测约束否决，定案 base64-only（注释入 `api.js`）。
- 🔧 **shield/force 参数化骨架与状态渲染合一（审计 #10a/#10b）**：`_toggle_flag_cmd` 共享读-判-写（两分支文案逐字保留）；`doc_prompt` 接入 `_state_of`/`_render_state("prompt")`，status/workspace/prompt 三指令同源渲染。
- 🔁 **锁归属终验（审计 #12）**：`delete_document` 与切片缓存的批量 unlink 移出 `_save_lock`（锁内只护内存态+小 JSON）；`save_plugin_config` 改显式锁，config 生效后再作废缓存；「无文档回落」在 `_factory_reset` 同步改走 `_effective_mode`（审计 #4 收尾）。
- 🧪 **门禁**：compileall 0、`test_retrieval`/`test_plugin` 双 PASSED、`node --check` ×2 = 0、grep 归零（行级锁/裸落盘/裸 reference/refresh=1/FormData 代码 0 命中）、`pack --check` OK。未做真机回归。

## v1.2.19 — 2026-10-08

- 🐛 **修复 WebUI 解绑与聊天解绑语义分叉**：`bindings/save` 支持 `ignore_history` 字段，WebUI 解绑载荷显式清除断史——`/xbdoc no` 过的会话经 WebUI 解绑后不再残留空壳，空配置条目恢复「解绑即彻底删除」。
- 🐛 **聊天 `/xbdoc unbind` 补全恢复出厂**：留空解绑对「无文档但有提示词/开关」的会话同样清空并删除条目（此前直接提示未绑定、漏清提示词），与 WebUI 及 README「解绑即恢复出厂」承诺一致。
- 📚 **README 新增接口总账与架构审计**：13 条 Web API / 15 组聊天指令 / 2 个 LLM 工具逐条映射唯一实现，附 12 条数据流收敛清单。
