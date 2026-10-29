"""会话与绑定：平台清洗、会话 key 规范化、绑定增删改查、seen 记录。"""

import re
import time
from typing import Any, Dict, List, Tuple

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .common import _MODE_PRIORITY, PLUGIN_NAME, _locked

class StoreSessionsMixin:
    """会话与绑定：平台清洗、会话 key 规范化、绑定增删改查、seen 记录。"""

    @staticmethod
    def _clean_platform(v: Any) -> str:
        """平台名清洗：字符串直接用；PlatformMetadata 之类对象取 .name；其他一律丢弃。

        绝不 str() 整个对象——那会产生 PlatformMetadata(name=...) 这种垃圾 key。
        返回统一小写的规范平台 id（别名归一 + 大小写归一，全插件唯一实现）。
        """
        if isinstance(v, str):
            cand = v.strip().lower()
        elif v is None:
            return ""
        else:
            name = getattr(v, "name", None)
            cand = name.strip().lower() if isinstance(name, str) else ""
        if not cand or len(cand) > 32 or not re.match(r"^[a-z0-9_\-]+$", cand):
            return ""
        if cand in (
            "aiocqhttp", "aihttpcq", "cqhttp", "onebot",
            "onebot_v11", "onebotv11", "onebot11",
            "napcat", "lagrange", "llonebot", "gocqhttp", "qq", "chronocat",
        ):
            return "onebot"
        return cand

    @staticmethod
    def _platform_of(event: Any) -> str:
        """提取事件所属平台（onebot/telegram/...），取不到返回空串，不抛异常。"""
        try:
            # 官方 API 优先（新版 AstrBot 事件自带 get_platform_name）
            gpn = getattr(event, "get_platform_name", None)
            if callable(gpn):
                try:
                    pn = StoreSessionsMixin._clean_platform(gpn())
                    if pn:
                        return pn
                except Exception:
                    pass
            for attr in ("platform_id", "platform"):
                try:
                    pn = StoreSessionsMixin._clean_platform(getattr(event, attr, ""))
                except Exception:
                    continue
                if pn:
                    return pn
            try:
                msg_obj = getattr(event, "message_obj", None)
                pn = StoreSessionsMixin._clean_platform(
                    getattr(msg_obj, "platform_id", "") or getattr(msg_obj, "platform", ""))
                if pn:
                    return pn
            except Exception:
                pass
            umo = getattr(event, "unified_msg_origin", "") or ""
            if isinstance(umo, str) and ":" in umo:
                return StoreSessionsMixin._clean_platform(umo.split(":", 1)[0])
            return ""
        except Exception:
            return ""

    def is_platform_allowed(self, platform: str = "") -> bool:
        """检查指定平台是否允许运行本插件。

        别名归一只走 _clean_platform（aiocqhttp 等 → onebot）；预设 onebot /
        onebot_matrix 展开为平台串，custom 与其他值读 allowed_platforms。
        """
        p = self._clean_platform(platform)
        if not p:
            return True
        preset = str(self._cfg("platform_preset") or "").strip().lower()
        if preset in ("all", "*", ""):
            return True
        if preset == "onebot":
            allowed = "onebot"
        elif preset == "onebot_matrix":
            allowed = "onebot, matrix"
        else:  # custom 或其他值：一律按 allowed_platforms 平台列表处理
            allowed = str(self._cfg("allowed_platforms") or "")
        tokens = {t for t in (self._clean_platform(x) for x in re.split(r"[,，、;；\s]+", allowed)) if t}
        if not tokens or "all" in tokens:
            return True
        return p in tokens

    def _private_identity(self, event: AstrMessageEvent) -> Tuple[str, str]:
        """私聊身份提取：(uid, nickname)；uid 取不到返回空串。"""
        uid = nickname = ""
        msg_obj = getattr(event, "message_obj", None)
        sender = getattr(msg_obj, "sender", None) if msg_obj is not None else None
        if sender is not None:
            for a in ("user_id", "id", "qq", "uid"):
                uid = str(getattr(sender, a, "") or "").strip()
                if uid:
                    break
            for a in ("nickname", "remark", "card", "name"):
                nickname = str(getattr(sender, a, "") or "").strip()
                if nickname:
                    break
        if not uid:
            ck = self._canonical_key(event)
            if ck.startswith("private:"):
                uid = ck.split(":")[-1]
        return uid, nickname

    def _record_seen(self, event: AstrMessageEvent) -> None:
        """记录会话基础信息，供 WebUI 模糊搜索/绑定选用（群聊与私聊通用，唯一实现）。"""
        try:
            platform = self._platform_of(event)
            if platform == "webchat":
                return
            if not platform and not getattr(self, "_platform_warned", False):
                self._platform_warned = True
                logger.warning(
                    f"[{PLUGIN_NAME}] 事件中取不到平台名，会话 key 将回落为无平台格式；"
                    f"请确认 AstrBot 版本/适配器是否上报平台信息。"
                )

            gid = str(event.get_group_id() or "").strip()
            if gid and "probe" not in gid.lower():
                kind, ident = "group", gid
                if not platform and gid.isdigit():
                    platform = "onebot"
                group_name = ""
                grp = getattr(event.message_obj, "group", None)
                if grp is not None:
                    group_name = str(getattr(grp, "group_name", "") or "").strip()
            else:
                ident, group_name = self._private_identity(event)
                if not ident or "probe" in ident.lower():
                    return
                kind = "private"
                if platform == "onebot":
                    ident = re.sub(r"\D", "", ident) or ident

            # key 与 _canonical_key 同构：kind:platform:ident，无平台回落 kind:ident
            key = f"{kind}:{platform}:{ident}" if platform else f"{kind}:{ident}"
            now = int(time.time())
            ent = self._seen_groups.setdefault(key, {
                "gid": ident, "group_name": group_name, "platform": platform,
                "kind": kind, "last_seen": now, "msg_count": 0,
            })
            ent["kind"] = kind
            ent["last_seen"] = now
            ent["msg_count"] = int(ent.get("msg_count", 0)) + 1
            if group_name and group_name != ent.get("group_name"):
                ent["group_name"] = group_name
            if platform and not ent.get("platform"):
                ent["platform"] = platform

            if ent["msg_count"] % 25 == 0 or (now - self._seen_save_ts) > 45:
                self._seen_save_ts = now
                self._save_seen()
        except Exception:
            pass

    @staticmethod
    def _split_session_key(cks: str):
        """拆会话 key -> (kind, platform|None, ident)。

        新格式 kind:platform:ident 原样拆；老格式 kind:ident 平台为 None；脏串 kind 为空。
        """
        parts = str(cks or "").strip().split(":")
        if len(parts) >= 3 and parts[0].lower() in ("group", "private"):
            return parts[0].lower(), parts[1].strip() or None, ":".join(parts[2:]).strip()
        if len(parts) == 2 and parts[0].lower() in ("group", "private"):
            return parts[0].lower(), None, parts[1].strip()
        return "", None, str(cks or "").strip()

    @staticmethod
    def _canonical_key_str(k: str) -> str:
        s = str(k or "").strip()
        if not s:
            return ""
        # 新规范 kind:platform:ident：合法平台统一归一（aiocqhttp/aihttpcq -> onebot），脏平台保留供 _is_sane_key 拦截
        kind, plat, ident = StoreSessionsMixin._split_session_key(s)
        if kind and plat and ident:
            norm_plat = StoreSessionsMixin._clean_platform(plat) or plat
            return f"{kind}:{norm_plat}:{ident}"
        if s.lower().startswith("group:"):
            tail = s.split(":", 1)[1].strip()
            return f"group:{tail}" if tail else ""
        if s.isdigit():
            return f"group:{s}"
        m = re.search(r"(?:GroupMessage|group)\s*:\s*(\S+)", s, re.IGNORECASE)
        if m:
            gid = m.group(1).rstrip(",;)>]")
            return f"group:{gid}"
        # 私聊不再冒充 group，避免私聊号与群号碰撞；统一归一为 private:xxx
        mp = re.search(r"(?:FriendMessage|PrivateMessage|Private|Friend|User)\s*:\s*(\S+)", s, re.IGNORECASE)
        if mp:
            raw_uid = mp.group(1).rstrip(",;)>]")
            return f"private:{raw_uid}" if raw_uid else s
        parts = s.split(":")
        if parts and parts[-1].isdigit():
            # 无法判断群/私时保守返回原串，由调用方按群优先处理
            return s
        return s

    def _canonical_key(self, event_or_str: Any) -> str:
        """事件 -> 规范会话 key。新格式 kind:platform:ident（平台隔离，防跨平台同号串台）。

        gid/sender 属权威 id，有平台就限定；umo 纯启发式，原样归一不二次限定；
        平台取不到时回落老格式，保证不断连。
        """
        if isinstance(event_or_str, str):
            return self._canonical_key_str(event_or_str)
        plat = self._platform_of(event_or_str)
        try:
            gid = str(event_or_str.get_group_id() or "").strip()
            if gid:
                # 适配器已返回限定/复合格式（如 group:xxx / group:plat:gid）时直接规范化
                if ":" in gid:
                    return self._canonical_key_str(gid)
                return f"group:{plat}:{gid}" if plat else f"group:{gid}"
        except Exception:
            pass
        umo = str(getattr(event_or_str, "unified_msg_origin", "") or "").strip()
        ck = self._canonical_key_str(umo)
        if ck.startswith("private:") or ck.startswith("group:"):
            return ck
        # 私聊兜底：尝试取 sender id（权威 id，有平台就限定）
        try:
            for attr in ("sender_id", "user_id", "qq", "uid"):
                uid = str(getattr(event_or_str, attr, "") or "").strip()
                if uid:
                    if plat in ("onebot", "aiocqhttp"):
                        uid = re.sub(r"\D", "", uid) or uid
                    return f"private:{plat}:{uid}" if plat else f"private:{uid}"
            msg_obj = getattr(event_or_str, "message_obj", None)
            sender = getattr(msg_obj, "sender", None) if msg_obj is not None else None
            if sender is not None:
                uid = str(getattr(sender, "user_id", "") or getattr(sender, "id", "") or "").strip()
                if uid:
                    if plat in ("onebot", "aiocqhttp"):
                        uid = re.sub(r"\D", "", uid) or uid
                    return f"private:{plat}:{uid}" if plat else f"private:{uid}"
        except Exception:
            pass
        return ck or "default"

    @staticmethod
    def _is_sane_key(cks: str) -> bool:
        """key 可用性：限定 key 的平台段必须合法（字母数字下划线短横，≤32），且排除 webchat/probe 污染。

        历史 bug 曾把 PlatformMetadata 整对象 repr 写进 key，或把 webchat:probe_xbdoc 写入会话记录，
        这类残骸直接丢弃。无平台段的老/裸 key 视为可用。
        """
        s_low = str(cks or "").strip().lower()
        if not s_low or "probe" in s_low or "webchat" in s_low or "functools.partial" in s_low:
            return False
        kind, plat, _ident = StoreSessionsMixin._split_session_key(cks)
        if kind and plat:
            if len(plat) > 32 or not re.match(r"^[A-Za-z0-9_\-]+$", plat):
                return False
            if plat.lower() == "webchat":
                return False
        if _ident and "probe" in _ident.lower():
            return False
        return True

    def _normalize_bindings(self, raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """标准化绑定：key 归一、模式归一，同 key 条目确定性合并。"""
        out: Dict[str, Dict[str, Any]] = {}
        if not isinstance(raw, dict):
            return out
        canon_raw_keys = {self._canonical_key_str(str(rk)) for rk in raw.keys()}
        for k, v in raw.items():
            ck = self._canonical_key_str(str(k))
            if not ck or not isinstance(v, dict):
                continue
            if not self._is_sane_key(ck):
                logger.warning(f"[{PLUGIN_NAME}] 丢弃污染会话 key: {str(k)[:80]}")
                continue
            # 若 seen 或同表已有平台限定（如 group:onebot:123456），自动合并，杜绝新旧 key 双存
            ck = self._qualify_session_key(ck)
            _k2, _p2, _id2 = self._split_session_key(ck)
            if _k2 == "group" and not _p2 and _id2:
                _ob_key = f"group:onebot:{_id2}"
                if _ob_key in out or _ob_key in raw or _ob_key in canon_raw_keys:
                    ck = _ob_key
            new_ent = {
                "doc_ids": [str(i) for i in (v.get("doc_ids") or [])],
                "prompt": str(v.get("prompt") or "").strip(),
                "shield": bool(v.get("shield", False)),
                "mode": self._normalize_mode(v.get("mode")) or "reference",
                "force_system_prompt": bool(v.get("force_system_prompt", False)),
                # 保留未知字段（如 ignore_history），避免打开WebUI就丢配置
                **{kk: vv for kk, vv in v.items() if kk not in (
                    "doc_ids", "prompt", "shield", "mode", "force_system_prompt")},
            }
            # platform 脏字段直接拔（合法的才留，展示用；key 自带限定不受影响）
            _pf = self._clean_platform(new_ent.pop("platform", ""))
            if _pf:
                new_ent["platform"] = _pf
            if ck not in out:
                out[ck] = new_ent
            else:
                self._merge_entries(out[ck], new_ent)
        return out

    @staticmethod
    def _seen_platforms(kind: str, ident: str, seen: Dict[str, Any]) -> set:
        """seen 中认领该 (kind, id) 的平台集合（恰为 1 个时才可安全限定）"""
        plats = set()
        for meta in (seen or {}).values():
            if not isinstance(meta, dict):
                continue
            is_priv = str(meta.get("kind") or "") == "private"
            if is_priv != (kind == "private"):
                continue
            if str(meta.get("gid") or "").strip() != ident:
                continue
            p = StoreSessionsMixin._clean_platform(meta.get("platform") or "")
            if p:
                plats.add(p)
        return plats

    def _candidate_keys(self, event_or_key: Any) -> List[str]:
        """会话解析候选表（全插件唯一实现）：canonical 优先，历史脏 key 与平台限定别名兜后。

        顺序即优先级：_resolve_session 取首个命中，_find_matching_keys 取全部命中。
        """
        if isinstance(event_or_key, str):
            raw = [event_or_key, self._canonical_key_str(event_or_key)]
        else:
            ck = self._canonical_key(event_or_key)
            umo = str(getattr(event_or_key, "unified_msg_origin", "") or "").strip()
            raw = [ck, umo, self._canonical_key_str(umo)]
        out: List[str] = []
        for c in raw:
            ckc = self._canonical_key_str(c) if c else ""
            if ckc and ckc not in out:
                out.append(ckc)
        _k, _p, _id = self._split_session_key(out[0] if out else "")
        if _k and _id:
            alts = [f"{_k}:onebot:{_id}", f"{_k}:{_id}"] if (not _p or _p == "onebot") else [f"{_k}:{_id}"]
            for alt in alts:
                if alt not in out:
                    out.append(alt)
        return out or ["default"]

    @staticmethod
    def _merge_entries(cur: Dict[str, Any], old: Dict[str, Any]) -> Dict[str, Any]:
        """同会话两条目合并（加载时去重用）：doc 并集保序，开关取或，模式按强度。"""
        merged_ids = list(cur.get("doc_ids", []))
        for d in old.get("doc_ids", []):
            if d not in merged_ids:
                merged_ids.append(d)
        cur["doc_ids"] = merged_ids
        if not str(cur.get("prompt") or "").strip():
            cur["prompt"] = str(old.get("prompt") or "")
        for flag in ("shield", "force_system_prompt", "ignore_history"):
            cur[flag] = bool(cur.get(flag)) or bool(old.get(flag))
        if _MODE_PRIORITY.get(str(old.get("mode") or "reference"), 0) > \
                _MODE_PRIORITY.get(str(cur.get("mode") or "reference"), 0):
            cur["mode"] = old.get("mode")
        if not cur.get("platform"):
            _pf = StoreSessionsMixin._clean_platform(old.get("platform", ""))
            if _pf:
                cur["platform"] = _pf
        # 其余未知字段只补不盖（创建时缺省已齐，此处多为 ignore_history 等开关的或合并）
        for kk, vv in old.items():
            if kk not in ("doc_ids", "prompt", "shield", "force_system_prompt",
                          "ignore_history", "mode", "platform"):
                cur.setdefault(kk, vv)
        return cur

    def _qualify_session_key(self, raw_key: str) -> str:
        """WebUI 手填 key 补平台限定：已限定原样；老格式按 seen 单一认领补足，多认领/无认领原样返回。"""
        ck = self._canonical_key_str(raw_key)
        kind, plat, ident = self._split_session_key(ck)
        if not kind or plat or not ident:
            return ck
        plats = self._seen_platforms(kind, ident, getattr(self, "_seen_groups", None) or {})
        if len(plats) == 1:
            qualified = f"{kind}:{plats.pop()}:{ident}"
            logger.info(f"[{PLUGIN_NAME}] 会话 key 已补平台限定: {ck} -> {qualified}")
            return qualified
        if len(plats) > 1:
            logger.warning(
                f"[{PLUGIN_NAME}] 会话 {ck} 被多平台认领 {sorted(plats)}，"
                f"保持原样，请在 WebUI 用完整 key（kind:platform:id）指定。"
            )
        return ck

    def _get_entry(self, session_key: str) -> Dict[str, Any]:
        ck = self._canonical_key_str(session_key)
        return self._bindings.setdefault(ck, {
            "doc_ids": [], "prompt": "", "shield": False, "mode": "none", "force_system_prompt": False,
        })

    def _resolve_session(self, event_or_key: Any, create: bool = False) -> Tuple[str, Dict[str, Any]]:
        """全插件统一会话解析：候选按 _candidate_keys 顺序命中 bindings。

        返回 (matched_key, entry)。create=False 时未命中返回 {} 且绝不写 bindings，
        调用方拿到的 key 即真正生效的 key。
        """
        cands = self._candidate_keys(event_or_key)
        for ck in cands:
            if ck in self._bindings:
                return ck, self._bindings[ck]
        primary = cands[0] if cands else "default"
        if create:
            return primary, self._get_entry(primary)
        return primary, {}

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        """归一化模式名；未知输入返回空串（调用方自行报错/回落，不静默串改）。"""
        m = str(mode or "").lower().strip()
        if m in ("system", "sys", "s", "强制", "提示词", "1"):
            return "system"
        if m in ("workspace", "ws", "w", "工作区", "沙箱", "3"):
            return "workspace"
        if m in ("reference", "ref", "r", "参考", "仅参考", "资料", "0"):
            return "reference"
        if m in ("none", "n", "无", "不注入", "2"):
            return "none"
        return ""

    def _effective_mode(self, ent: Dict[str, Any]) -> str:
        """生效模式：无有效绑定文档（或模式缺失/非法）一律回落 none —— 全插件唯一回落实现。

        保存 / 导入 / 删文档 / 切模式 / 状态与注入读取全部走这里，杜绝各处复制规则。
        """
        if not [d for d in ent.get("doc_ids", []) if d in self._index]:
            return "none"
        return self._normalize_mode(ent.get("mode")) or "none"

    @staticmethod
    def _parse_doc_ids(*parts: str) -> List[str]:
        """解析文档 ID：兼容空格/逗号/分号分隔，自动去重保序。"""
        ids: List[str] = []
        for p in parts:
            if not p:
                continue
            for tok in re.split(r"[\s,;，；]+", str(p)):
                t = tok.strip().strip(",;")
                if t and t not in ids:
                    ids.append(t)
        return ids

    def _find_matching_keys(self, event: AstrMessageEvent) -> List[str]:
        """本会话所有命中的绑定 Key（命中在前、primary 兜后），解绑按全量命中清理。"""
        cands = self._candidate_keys(event)
        keys = [ck for ck in cands if ck in self._bindings]
        primary = cands[0] if cands else "default"
        if primary not in keys:
            keys.append(primary)
        return keys

    def get_bound_doc_ids(self, event: AstrMessageEvent) -> List[str]:
        # 与注入链路共用同一会话解析，避免状态显示与实际生效不一致
        return list(self._effective_session(event).get("doc_ids", []))

    def _effective_session(self, event: AstrMessageEvent) -> Dict[str, Any]:
        """获取本会话综合生效配置（canonical 优先、脏 key 兼容，matched_key 即真实命中）。"""
        key, ent = self._resolve_session(event, create=False)
        doc_ids = [d for d in ent.get("doc_ids", []) if d in self._index]
        return {
            "doc_ids": doc_ids,
            "prompt": str(ent.get("prompt") or "").strip(),
            "shield": bool(ent.get("shield", False)),
            "mode": self._effective_mode(ent),
            "force_system_prompt": bool(ent.get("force_system_prompt", False)),
            "ignore_history": bool(ent.get("ignore_history", False)),
            "matched_key": key,
        }

    @_locked
    def bind_docs(self, session_key: str, doc_ids: List[str]) -> List[str]:
        """写入会话文档绑定：改内存 + 落盘一体（本插件唯一条目文档写口）。"""
        valid = [d for d in doc_ids if d in self._index]
        self._get_entry(session_key)["doc_ids"] = valid
        self._save_json(self.bindings_path, self._bindings)
        return valid

    @_locked
    def bind_docs_report(self, event_or_key: Any, doc_ids: List[str]) -> Dict[str, Any]:
        """聊天 bind 的带锁 RMW 写口：锁内算 existed/added/dup 并复用 bind_docs 落盘。

        把回复所需的快照（key/added/dup/total/mode）一次性带回，调用方出锁后再拼消息，
        handler 不再自己持锁读改写 bindings + 二次 _save_json（审计 #3/#8）。
        """
        key, _ = self._resolve_session(event_or_key, create=False)
        existed = [d for d in (self._bindings.get(key) or {}).get("doc_ids", []) if d in self._index]
        added = [i for i in doc_ids if i not in existed]
        dup = [i for i in doc_ids if i in existed]
        self.bind_docs(key, existed + added)  # 唯一写口（RLock 可重入），内部落盘
        ent = self._bindings.get(key) or {}
        return {
            "key": key,
            "added": added,
            "dup": dup,
            "total": len(existed) + len(added),
            "mode": self._effective_mode(ent),
        }

    def _prune_empty_entry(self, session_key: str) -> bool:
        """解绑后若该会话无文档、无提示词、无屏蔽/强制/断史且为默认模式（reference / none），则彻底删除条目。

        避免 bindings.json 堆积空壳，会话列表看着像“没解掉”。
        """
        ck = self._canonical_key_str(session_key)
        ent = self._bindings.get(ck)
        if not ent:
            return False
        if (
            not ent.get("doc_ids")
            and not str(ent.get("prompt") or "").strip()
            and not ent.get("shield", False)
            and not ent.get("force_system_prompt", False)
            and not ent.get("ignore_history", False)
            and str(ent.get("mode") or "reference") in ("reference", "none")
        ):
            self._bindings.pop(ck, None)
            return True
        return False

    @_locked
    def set_session_prompt(self, session_key: str, prompt: str) -> Dict[str, Any]:
        """写专属提示词（内存+落盘一体）；清空后空壳随之 prune。"""
        ent = self._get_entry(session_key)
        ent["prompt"] = (prompt or "").strip()
        ck = self._canonical_key_str(session_key)
        self._prune_empty_entry(ck)
        self._save_json(self.bindings_path, self._bindings)
        return self._bindings.get(ck) or {}

    @_locked
    def set_session_mode(self, session_key: str, mode: str) -> Dict[str, Any]:
        """写生效模式（内存+落盘一体）；无文档按唯一回落规则强制 none。"""
        ent = self._get_entry(session_key)
        ent["mode"] = self._normalize_mode(mode) or "none"
        ent["mode"] = self._effective_mode(ent)
        self._save_json(self.bindings_path, self._bindings)
        return ent

    @_locked
    def set_session_flag(self, session_key: str, field: str, value: bool) -> Dict[str, Any]:
        """写会话开关（shield / force_system_prompt / ignore_history）并落盘，空壳随之 prune。

        三个开关共用这一条写口，聊天指令不再各自改 dict 再手动 save。
        """
        ent = self._get_entry(session_key)
        ent[field] = bool(value)
        ck = self._canonical_key_str(session_key)
        self._prune_empty_entry(ck)
        self._save_json(self.bindings_path, self._bindings)
        return ent

    @_locked
    def save_binding_payload(
        self,
        session_key: str,
        doc_ids: List[str],
        fields: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any], List[str]]:
        """WebUI 保存绑定的唯一写口（改内存+落盘一体）：key 归一补平台限定 → 写条目 →
        无文档按唯一规则回落 mode → prune → 落盘，返回 (生效 key, 条目, 有效 doc_ids)。

        fields 只含调用方显式给出的键（mode 已由 Web 层校验归一）；空壳被 prune 时条目返回 {}。
        """
        key = self._qualify_session_key(self._canonical_key_str(session_key))
        valid = [d for d in doc_ids if d in self._index]
        ent = self._get_entry(key)
        for f, v in fields.items():
            ent[f] = v
        ent["doc_ids"] = valid
        ent["mode"] = self._effective_mode(ent)
        self._prune_empty_entry(key)
        self._save_json(self.bindings_path, self._bindings)
        return key, self._bindings.get(key) or {}, valid

    @_locked
    def unbind_docs(self, event: AstrMessageEvent, tokens: List[str]) -> Dict[str, Any]:
        """解绑本会话文档（内存+落盘一体），返回回复所需状态（拼回复在锁外做）。

        tokens 空 = 恢复出厂：按命中 keys 全清（文档、提示词、屏蔽、强制、断史、模式）；
        非空 = 从含文档条目移除指定文档，移完无文档则一并恢复出厂。
        """
        keys = self._find_matching_keys(event)
        main_key = keys[0]
        targets = [k for k in keys if (self._bindings.get(k) or {}).get("doc_ids")]
        touched = 0
        removed: List[str] = []
        not_found: List[str] = []
        remaining = 0

        def _factory_reset(ent: Dict[str, Any]) -> None:
            ent["doc_ids"] = []
            ent["prompt"] = ""
            ent["shield"] = False
            ent["force_system_prompt"] = False
            ent["ignore_history"] = False
            # 恢复出厂即无有效文档：走唯一回落（_effective_mode ⇒ none），
            # 不再在这里复制第五份「无文档⇒回落」规则（审计 #4）
            ent["mode"] = self._effective_mode(ent)

        if not tokens:
            # 留空 = 恢复出厂（README「解绑即恢复出厂」）：按 keys 全清而非仅含文档的
            # targets——无文档但有提示词/开关的会话同样要恢复出厂。
            for k in keys:
                ent = self._bindings.get(k)
                if not ent:
                    continue
                _factory_reset(ent)
                if self._prune_empty_entry(k):
                    touched += 1
        elif targets:
            for t in tokens:
                hit = False
                for k in targets:
                    ent = self._bindings.get(k) or {}
                    if t in ent.get("doc_ids", []):
                        ent["doc_ids"] = [d for d in ent["doc_ids"] if d != t]
                        hit = True
                (removed if hit else not_found).append(t)
            # 若解绑后已无文档，视为彻底解绑：提示词/屏蔽/强制/断史一并清除
            remaining = sum(len((self._bindings.get(k) or {}).get("doc_ids", [])) for k in targets)
            if remaining == 0:
                for k in targets:
                    _factory_reset(self._bindings.get(k) or {})
                for k in targets:
                    self._prune_empty_entry(k)

        self._save_json(self.bindings_path, self._bindings)
        return {
            "key": main_key,
            "targets": len(targets),
            "touched": touched,
            "removed": removed,
            "not_found": not_found,
            "remaining": remaining,
        }

    @_locked
    def import_bindings(self, payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
        """导入绑定备份（内存+落盘一体）：body 即导出的原样 map；merge 合并 / replace 覆盖。

        不存在的文档 id 自动跳过并回告；非法条目跳过；空壳不落盘；mode 统一走唯一回落。
        """
        applied, skipped_docs, skipped_keys = 0, [], []
        if mode == "replace":
            self._bindings = {}
        for k, v in payload.items():
            if not isinstance(v, dict):
                skipped_keys.append(str(k))
                continue
            ck = self._canonical_key_str(str(k))
            if not ck:
                skipped_keys.append(str(k))
                continue
            raw_ids = v.get("doc_ids") or []
            if not isinstance(raw_ids, list):
                raw_ids = []
            docs = [str(d).strip() for d in raw_ids if str(d).strip()]
            kept = [d for d in docs if d in self._index]
            skipped_docs.extend(d for d in docs if d not in self._index)
            new_ent = {
                "doc_ids": kept,
                "prompt": str(v.get("prompt") or "").strip(),
                "shield": bool(v.get("shield", False)),
                "force_system_prompt": bool(v.get("force_system_prompt", False)),
                "mode": self._normalize_mode(v.get("mode")) or "reference",
                "ignore_history": bool(v.get("ignore_history", False)),
            }
            if ck in self._bindings:
                self._merge_entries(self._bindings[ck], new_ent)
            else:
                self._bindings[ck] = new_ent
            ent = self._bindings.get(ck)
            if ent:
                ent["mode"] = self._effective_mode(ent)
            self._prune_empty_entry(ck)
            if ck in self._bindings:
                applied += 1
        self._save_json(self.bindings_path, self._bindings)
        return {
            "ok": True,
            "mode": mode,
            "applied": applied,
            "skipped_docs": sorted(set(skipped_docs)),
            "skipped_keys": skipped_keys,
        }
