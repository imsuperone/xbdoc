"""xbdoc 指令层：/xbdoc 子指令实现。

被主插件多继承（Mixin），无 @filter 装饰方法，由主入口 doc_cmd 分发调用。
"""

import hashlib
import re
import time
from typing import Any, Dict, List, Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

try:
    from .store import PLUGIN_NAME
except ImportError:
    from store import PLUGIN_NAME


def mode_label(mode: str) -> str:
    """模式统一文案（状态/提示词/绑定回显共用，改一处全生效）"""
    m = str(mode or "").lower()
    if m == "system":
        return "⚡ 强制遵守（系统提示词）"
    if m == "workspace":
        return "💻 模拟工作区"
    if m == "none":
        return "🚫 无（不注入文档）"
    return "📖 仅作参考资料"


def shield_label(shield: bool) -> str:
    """屏蔽统一文案"""
    return "🛡️ 开启（已清空原人格）" if shield else "👤 关闭（保留原人格）"


def force_label(force: bool) -> str:
    """强制系统词统一文案"""
    return "⚡ 开启（清空其他提示词，专属提示词唯一生效）" if force else "关闭"


# ======================================================================
# 指令 Mixin（参数约定：doc_cmd 统一解析后传入 args/tail，handler 不再各自切 raw）
# ======================================================================

class XbdocCommandsMixin:

    async def _cmd_help(self, event: AstrMessageEvent):
        menu = (
            "📚 文档记忆助手 · 指令菜单\n\n"
            "📖 查看\n"
            "• /xbdoc status — 本群状态；/xbdoc list — 文档列表\n"
            "• /xbdoc workspace — 工作区挂载清单\n"
            "• /xbdoc search <词> — 检索绑定文档；/xbdoc read <ID> [n] — 预览切片\n\n"
            "🔗 绑定（管理员）\n"
            "• /xbdoc bind <ID...> — 追加绑定，自动合并\n"
            "• /xbdoc unbind [ID...] — 解绑，留空全清（含提示词/屏蔽）\n\n"
            "🎛️ 模式（管理员）\n"
            "• /xbdoc mode system|workspace|reference|none — 切换生效模式\n"
            "• /xbdoc shield on|off — 清空/保留原人格\n"
            "• /xbdoc force on|off — 专属提示词唯一生效\n\n"
            "🏷️ 提示词（管理员）\n"
            "• /xbdoc prompt — 查看；/xbdoc prompt_set <内容> — 设置\n"
            "• /xbdoc prompt_clear — 清除\n\n"
            "🧹 历史（管理员）\n"
            "• /xbdoc no [off] — 忘掉此前消息 / 恢复\n\n"
            "💡 模式：system 强制遵守 · workspace 工作区 · reference 仅参考"
        )
        yield event.plain_result(menu)


    async def doc_list(self, event: AstrMessageEvent):
        """查看知识库中所有文档 /xbdoc list"""
        docs = self.list_documents()
        if not docs:
            yield event.plain_result(
                "📚 知识库当前暂无入库文档。\n\n"
                "请在 WebUI 后端管理台上传文档后再进行绑定。"
            )
            return

        lines = [f"📚 知识库文档列表（共 {len(docs)} 篇）\n"]
        for idx, m in enumerate(docs[:30], 1):
            lines.append(f"[{idx}] {m['filename']}")
            lines.append(f"• 文档ID：{m['doc_id']}")
            lines.append(f"• 规模：{m['chunks']} 切片 · {m['text_len']:,} 字\n")

        lines.append("💡 绑定到本群：/xbdoc bind <文档ID>")
        yield event.plain_result("\n".join(lines).strip())


    def _state_of(self, event: AstrMessageEvent) -> Dict[str, Any]:
        """status / prompt / workspace 共用的状态收集：一次会话解析取全部展示字段。

        旧逻辑各命令先 get_bound_doc_ids 再 _session_keys 再 _effective_session，
        一条查询白做 2-3 次完整解析；现在统一只解析一次。
        """
        sess = self._effective_session(event)
        ids = sess.get("doc_ids", [])
        prompt = str(sess.get("prompt") or "").strip()
        mode = str(sess.get("mode") or "reference")
        force = bool(sess.get("force_system_prompt", False))
        return {
            "key": str(sess.get("matched_key") or "default"),
            "ids": ids,
            "mode": mode,
            "mode_text": mode_label(mode) if ids else "➖ 无（未绑定文档）",
            "shield_text": shield_label(bool(sess.get("shield", False))),
            "force_text": force_label(force),
            "force": force,
            "prompt": prompt,
            "prompt_text": f"已设置（{len(prompt)}字）" if prompt else "未设置",
            "prompt_preview": (prompt[:260] + "…") if len(prompt) > 260 else prompt,
        }


    @staticmethod
    def _render_state(st: Dict[str, Any], variant: str) -> List[str]:
        """status / prompt / workspace 共用的状态渲染：一份状态、三种口径，只此一份实现。"""
        lines = [f"• 生效模式：{st['mode_text']}"]
        if variant != "workspace":
            lines.append(f"• 人格屏蔽：{st['shield_text']}")
        if variant == "status":
            lines += [
                f"• 强制系统词：{st['force_text']}",
                f"• 专属提示词：{st['prompt_text']}",
            ]
        elif variant == "prompt":
            lines += [
                f"• 绑定文档：{len(st['ids'])} 篇",
                f"• 专属提示词：\n{st['prompt_preview'] or '（未设置）'}",
            ]
        elif st["ids"]:
            lines.append(f"• 挂载文件数量：共 {len(st['ids'])} 篇文档")
        return lines


    async def doc_status(self, event: AstrMessageEvent):
        """查看本会话绑定的文档 /xbdoc status"""
        st = self._state_of(event)
        ids = st["ids"]

        lines = [
            "📌 本群文档记忆状态\n",
            f"• 会话标识：{st['key']}",
            *self._render_state(st, "status"),
            "",
        ]
        if not ids:
            if st["prompt"]:
                lines.append("💡 当前未绑定文档，专属系统提示词正常独立生效中。")
                if st["force"]:
                    lines.append("⚡ 强制注入模式已激活：已清空其他提示词，专属提示词作为底层唯一系统词。")
            else:
                lines.append("⚠️ 本群当前未绑定任何文档。")
                lines.append("💡 发送 /xbdoc list 查看可用文档，或发送 /xbdoc bind <ID> 快速绑定。")
        else:
            lines.append(f"📖 已绑定文档（共 {len(ids)} 篇）：")
            for idx, d in enumerate(ids, 1):
                meta = self._index.get(d, {})
                fname = meta.get("filename", d)
                lines.append(f"{idx}. {fname}（ID: {d}）")
            lines.append("")
            if st["mode"] == "workspace":
                lines.append("💻 说明：当前会话处于独立工作区沙箱，大模型仅对工作区内的挂载文档进行严谨分析与回答。")
            elif st["mode"] == "system":
                lines.append("⚡ 说明：大模型已将文档作为最高系统设定执行，强制遵守文档规则与设定。")
            elif st["mode"] == "none":
                lines.append("🚫 说明：当前模式下不注入文档，仅保留专属提示词与人格屏蔽等配置。")
            else:
                lines.append("📖 说明：群内提问相关内容时，AI 将检索片段作为参考资料引用回答。")
            lines.append("\n💡 切换模式：/xbdoc mode workspace / system / reference / none")
            lines.append("💡 查看工作区：/xbdoc workspace")
            lines.append("💡 切换屏蔽：/xbdoc shield on / off")
        yield event.plain_result("\n".join(lines).strip())


    async def doc_workspace(self, event: AstrMessageEvent):
        """查看当前模拟工作区状态与文件清单 /xbdoc workspace"""
        st = self._state_of(event)
        ids = st["ids"]
        head = f"💻 模拟工作区详情（{st['key']}）\n"

        if not ids:
            yield event.plain_result("\n".join([
                head,
                *self._render_state(st, "workspace"),
                "⚠️ 当前工作区尚未挂载用户文档。",
                "💡 发送 /xbdoc list 查看可用文档，使用 /xbdoc bind <ID> 挂载文件到工作区。",
            ]).strip())
            return

        lines = [
            head,
            *self._render_state(st, "workspace"),
            "",
            "📁 工作区根目录 [/workspace] 文件清单：",
        ]
        total_len = 0
        for idx, did in enumerate(ids, 1):
            meta = self._index.get(did, {})
            fname = meta.get("filename", did)
            tlen = meta.get("text_len", 0)
            total_len += tlen
            lines.append(f"{idx}. /workspace/{fname}")
            lines.append(f"   ├─ ID: {did}")
            lines.append(f"   └─ 大小: {meta.get('chunks', 1)} 切片 · {tlen:,} 字符")

        lines.append(f"\n📊 工作区总文本容量：{total_len:,} 字符")
        if st["mode"] != "workspace":
            lines.append("\n💡 发送 /xbdoc mode workspace 可切换为工作区模式。")
        yield event.plain_result("\n".join(lines).strip())


    async def doc_bind(self, event: AstrMessageEvent, args: List[str]):
        """绑定文档 /xbdoc bind <id1> [id2...]（追加到本群已有绑定，管理员）"""
        ids = self._parse_doc_ids(*args)
        if not ids:
            yield event.plain_result(
                "❌ 用法错误：/xbdoc bind <文档ID1> [文档ID2...]\n"
                "💡 可先发送 /xbdoc list 查看知识库中可用的文档 ID。"
            )
            return
        bad = [i for i in ids if i not in self._index]
        if bad:
            yield event.plain_result(f"❌ 绑定失败：以下 ID 不存在于知识库中：\n{', '.join(bad)}\n\n💡 请发送 /xbdoc list 查看可用 ID。")
            return
        # 读改写与落盘全在 store 写口锁内完成（bind_docs_report），快照出锁后拼回复（审计 #3/#8）
        rep = self.bind_docs_report(event, ids)
        key = rep["key"]
        lines = [f"✅ 绑定成功！已关联到本群（{key}）：\n"]
        for did in rep["added"]:
            lines.append(f"• 新增：{(self._index.get(did) or {}).get('filename', did)}（ID: {did}）")
        for did in rep["dup"]:
            lines.append(f"• 已在绑定中：{(self._index.get(did) or {}).get('filename', did)}（ID: {did}）")
        lines.append(f"\n本群共绑定 {rep['total']} 篇，当前模式：{mode_label(rep['mode'])}")
        lines.append("💡 切换为强制遵守模式：/xbdoc mode system")
        lines.append("💡 切换为参考资料模式：/xbdoc mode reference")
        yield event.plain_result("\n".join(lines).strip())


    async def doc_unbind(self, event: AstrMessageEvent, args: List[str]):
        """解绑文档 /xbdoc unbind [id...]，留空则清空绑定（管理员）"""
        tokens = self._parse_doc_ids(*args)
        # 读改写与落盘全在 store 写口锁内完成（unbind_docs：含恢复出厂与 prune），
        # 返回 Dict 后出锁拼回复（审计 #3/#4/#8）；三分支文案与旧实现逐字一致
        r = self.unbind_docs(event, tokens)
        key = r["key"]
        targets = r["targets"]
        if not tokens:
            # 留空 = 恢复出厂（README「解绑即恢复出厂」）：文档、提示词、屏蔽、强制注入、断史、
            # 模式一并清除。按 keys 全清而非仅含文档的 targets——无文档但有提示词/开关的
            # 会话同样要恢复出厂（此前漏清，与 WebUI 解绑分叉）。
            if not r["touched"] and not targets:
                msg = f"⚠️ 本群（{key}）当前未绑定任何文档。"
            else:
                tail = "相关配置已彻底移除。" if r["touched"] else "已回到默认配置。"
                msg = f"✅ 已清空本群（{key}）的所有文档绑定，专属提示词、屏蔽与强制注入已一并清除。{tail}"
        elif not targets:
            msg = f"⚠️ 本群（{key}）当前未绑定任何文档。"
        else:
            msg = f"✅ 解绑完成（{key}）："
            if r["removed"]:
                msg += f"\n• 已移除：{', '.join(r['removed'])}"
            if r["not_found"]:
                msg += f"\n• 未绑定/不存在：{', '.join(r['not_found'])}"
            if r["remaining"] == 0:
                msg += "\n• 本群已无绑定文档，提示词与屏蔽已一并清除。"
            else:
                msg += f"\n本群当前剩余：{r['remaining']} 篇文档。"
        yield event.plain_result(msg)


    async def doc_search(self, event: AstrMessageEvent, args: List[str]):
        """检索绑定文档 /xbdoc search <关键词>"""
        q = " ".join(args).strip()
        if not q:
            yield event.plain_result("❌ 用法错误：/xbdoc search <关键词或提问内容>")
            return
        ids = self.get_bound_doc_ids(event)
        if not ids:
            yield event.plain_result("⚠️ 本群尚未绑定任何文档，请先使用 /xbdoc bind <ID> 绑定。")
            return
        hits = self.retrieve(q, ids, self._cfg_int("top_k"))
        if not hits:
            yield event.plain_result(f"🔍 未在已绑定文档中检索到与「{q}」相关的片段，可尝试更换搜索词。")
            return
        out = [f"🔍 检索结果（关键词：{q}，匹配 {len(hits)} 处）\n"]
        for idx, h in enumerate(hits, 1):
            out.append(f"【{idx}】《{h['filename']}》片段{h['chunk_idx']+1}（相关度: {h['score']}）")
            out.append(f"{h['text'][:400]}\n")
        yield event.plain_result("\n".join(out)[:3500].strip())


    async def doc_read(self, event: AstrMessageEvent, args: List[str]):
        """预览文档切片 /xbdoc read <id> [片段号]"""
        doc_id = args[0] if args else ""
        num = args[1] if len(args) > 1 else "1"
        if not doc_id:
            yield event.plain_result("❌ 用法错误：/xbdoc read <文档ID> [片段号]，ID 可用 /xbdoc list 查看。")
            return
        if doc_id not in self._index:
            yield event.plain_result(f"❌ 未找到文档 ID「{doc_id}」，请发送 /xbdoc list 查看可用 ID。")
            return
        try:
            n = max(1, int(num or "1"))
        except Exception:
            n = 1
        chunks = self._load_chunks(doc_id)
        if not chunks:
            yield event.plain_result("⚠️ 该文档暂无可用文本切片。")
            return
        n = min(n, len(chunks))
        meta = self._index[doc_id]
        yield event.plain_result(
            f"📄 预览《{meta['filename']}》（ID: {doc_id}）\n"
            f"进度：片段 {n} / {len(chunks)}\n\n"
            f"{chunks[n-1][:1500]}"
        )


    async def doc_prompt(self, event: AstrMessageEvent):
        """查看本群提示词、生效模式与屏蔽状态 /xbdoc prompt"""
        # 一次会话解析取全部字段 + 共享 prompt 渲染变体（审计 #9/#10b：不再各命令各拼一份状态）
        st = self._state_of(event)
        body = "\n".join(self._render_state(st, "prompt"))
        yield event.plain_result(
            "🧩 本群配置详情\n\n"
            f"{body}\n\n"
            "⚙️ 管理指令：\n"
            "• /xbdoc mode system | workspace | reference | none\n"
            "• /xbdoc shield on | off\n"
            "• /xbdoc prompt_set <内容>\n"
            "• /xbdoc prompt_clear"
        )


    async def doc_mode(self, event: AstrMessageEvent, args: List[str]):
        """设置本群文档生效模式 /xbdoc mode workspace|system|reference|none（管理员，需先绑定文档）"""
        read_key, ent = self._resolve_session(event, create=False)
        if not [d for d in ent.get("doc_ids", []) if d in self._index]:
            yield event.plain_result(
                f"⚠️ 本群（{read_key}）当前未绑定任何文档，无法切换生效模式。\n\n"
                "💡 请先使用 /xbdoc bind <ID> 绑定文档后再切换。"
            )
            return
        raw = " ".join(args).strip().lower()
        if not raw:
            yield event.plain_result(
                f"📌 当前群生效模式：{mode_label(ent.get('mode'))}\n\n"
                "切换指令：\n"
                "• /xbdoc mode workspace（模拟工作区，仅限工作区文档）\n"
                "• /xbdoc mode system（强制遵守文档，角色与指令模式）\n"
                "• /xbdoc mode reference（仅作参考资料，知识库问答）\n"
                "• /xbdoc mode none（无：绑定文档但不注入，仅提示词/屏蔽生效）"
            )
            return
        norm = self._normalize_mode(raw)
        if not norm:
            yield event.plain_result(
                f"❌ 未知模式「{raw}」，可用：workspace / system / reference / none（首字母 w / s / r / n 也可）。"
            )
            return
        # 写口自带锁+落盘（set_session_mode），resolve 与调用都不持行级锁（审计 #8）
        self.set_session_mode(read_key, norm)
        if norm == "workspace":
            yield event.plain_result(
                f"💻 本群模式已切换为【模拟工作区】！\n\n"
                f"当前会话已挂载进入独立工作区沙箱 (/workspace)，上下文中【仅包含】绑定的文档文件，模型将严格基于工作区文件进行专业分析、开发与问答。\n"
                f"💡 可发送 /xbdoc workspace 查看工作区挂载清单。"
            )
        elif norm == "system":
            yield event.plain_result(
                f"⚡ 本群模式已切换为【强制遵守文档】！\n\n"
                f"文档将直接作为最高优先级系统提示词载入大模型，AI 将严格遵循文档中的一切角色设定、语言规范与指令要求。"
            )
        elif norm == "none":
            yield event.plain_result(
                f"🚫 本群模式已切换为【无】！绑定文档保留但不再注入，仅专属提示词/屏蔽生效。"
            )
        else:
            yield event.plain_result(
                f"📖 本群模式已切换为【仅作参考资料】！\n\n"
                f"文档将作为外部知识库，仅在群友提问相关内容时检索片段供 AI 参考回答。"
            )


    async def doc_prompt_set(self, event: AstrMessageEvent, tail: str):
        """设置本群专属提示词 /xbdoc prompt_set <内容>（管理员；不设上限，保证完整注入）"""
        text = (tail or "").strip()
        if len(text) < 2:
            yield event.plain_result("用法：/xbdoc prompt_set <本群专属提示词内容>，至少2个字。")
            return
        # 写口自带锁+落盘（set_session_prompt），消息在锁外拼（审计 #8）
        key, _ = self._resolve_session(event, create=False)
        self.set_session_prompt(key, text)
        yield event.plain_result(
            f"✅【本群专属提示词已生效】\n"
            f"会话标识：{key}\n"
            f"提示词字数：{len(text)} 字\n\n"
            f"💡 可发送 /xbdoc prompt 查看详情，发送 /xbdoc prompt_clear 可清除。"
        )


    async def doc_prompt_clear(self, event: AstrMessageEvent):
        """清空本群提示词 /xbdoc prompt_clear（管理员）"""
        # 读判在锁外（展示性预读），清空走写口 set_session_prompt("", 自带 prune+落盘)，消息出锁（审计 #8）
        key, ent = self._resolve_session(event, create=False)
        if not ent:
            msg = f"⚠️ 本群（{key}）当前未设置专属提示词。"
        elif not ent.get("prompt"):
            msg = f"✅ 已清空本群（{key}）专属提示词。"
        else:
            self.set_session_prompt(key, "")
            msg = f"✅ 已清空本群（{key}）专属提示词。"
        yield event.plain_result(msg)


    @staticmethod
    def _parse_on_off(raw: str, cur: bool) -> Optional[bool]:
        """解析 on/off 类开关：显式值返回目标，未填返回取反，无效返回 None。"""
        raw = (raw or "").strip().lower()
        if raw in ("on", "开", "1", "true"):
            return True
        if raw in ("off", "关", "0", "false"):
            return False
        if not raw:
            return not cur
        return None


    def _toggle_flag_cmd(
        self,
        event: AstrMessageEvent,
        args: List[str],
        field: str,
        usage: str,
        on_msg: str,
        off_msg: str,
    ) -> str:
        """shield / force 共用的开关指令骨架（审计 #10a）：读-判-写同构，文案逐字保留。

        cur 预读与 _parse_on_off 是展示性读取，锁外做；仅值确实变化才走 set_session_flag
        写口（自带锁+落盘+prune）。旧实现「值未变」与「已切换」两分支文案本就逐字相同，
        此处按 target 取一份，消息一律在锁外拼（审计 #8）。
        """
        raw = " ".join(args)
        key, _ = self._resolve_session(event, create=False)
        cur = bool((self._bindings.get(key) or {}).get(field, False))
        target = self._parse_on_off(raw, cur)
        if target is None:
            return usage
        if bool(target) != cur:
            self.set_session_flag(key, field, bool(target))
        return (on_msg if target else off_msg).format(key=key)


    async def doc_shield(self, event: AstrMessageEvent, args: List[str]):
        """本群屏蔽 AstrBot 原人格开关 /xbdoc shield on|off（管理员）"""
        yield event.plain_result(self._toggle_flag_cmd(
            event, args, "shield",
            "❌ 用法错误：/xbdoc shield on（开启） | off（关闭）",
            "🛡️ 本群已开启人格屏蔽！已彻底清空 AstrBot 自带人格，进入纯文档/提示词模式。",
            "👤 本群已关闭人格屏蔽！已恢复 AstrBot 原有人格。",
        ))


    async def doc_force(self, event: AstrMessageEvent, args: List[str]):
        """切换强制注入系统提示词开关 /xbdoc force on|off（管理员）"""
        yield event.plain_result(self._toggle_flag_cmd(
            event, args, "force_system_prompt",
            "用法：/xbdoc force on (开启强制注入) | off (关闭)",
            "⚡【强制注入系统提示词已开启】\n会话（{key}）：将清空其他一切提示词，强制本群专属提示词为唯一底层系统提示词。",
            "✅【强制注入系统提示词已关闭】\n会话（{key}）：已恢复正常模式。",
        ))


    async def doc_no(self, event: AstrMessageEvent, args: List[str]):
        """清空历史记忆并停止读取此指令之前的消息 /xbdoc no [off]"""
        raw = " ".join(args).strip().lower()
        # 裸写 ignore_history 改走 set_session_flag 写口（自带锁+落盘+prune），消息在锁外拼（审计 #3/#8）
        key, _ = self._resolve_session(event, create=False)
        if raw in ("off", "恢复", "false", "0", "no_off", "reset", "yes"):
            if self._bindings.get(key):
                # 已有条目才写：无条目不开空壳、不落盘（与旧行为一致）
                self.set_session_flag(key, "ignore_history", False)
            logger.info(f"[{PLUGIN_NAME}] [doc no] 恢复历史读取 (会话: {key})")
            msg = f"✅ 已恢复读取历史消息上下文（会话：{key}）。"
        else:
            self.set_session_flag(key, "ignore_history", True)
            logger.info(f"[{PLUGIN_NAME}] [doc no] 清空历史记忆 (会话: {key})")
            msg = (
                f"🧹【已清空历史消息记忆】\n\n"
                f"本群（{key}）已彻底清空并停止读取此指令之前的所有消息！\n"
                "此前哪怕有聊天记录也会全部忘掉，后续仅响应当前提问与绑定文档。\n\n"
                "💡 如需恢复读取历史聊天：/xbdoc no off"
            )

        # 同步重置当前底层对话会话 ID（仅开启断史时；字段不存在则跳过）
        if raw not in ("off", "恢复", "false", "0", "no_off", "reset", "yes"):
            try:
                for s_attr in ("session", "_session", "conversation"):
                    sess_obj = getattr(event, s_attr, None)
                    if sess_obj is not None:
                        for cid_attr in ("cid", "curr_cid", "conversation_id"):
                            if hasattr(sess_obj, cid_attr):
                                setattr(sess_obj, cid_attr, hashlib.md5(f"{key}:{time.time()}".encode()).hexdigest()[:8])
            except Exception:
                pass

        yield event.plain_result(msg)
