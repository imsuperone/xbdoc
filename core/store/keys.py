"""会话身份代数：平台清洗、key 拆分/归一/合法性、候选表生成。

全部为纯函数（无状态、无 AstrBot 依赖），是全插件会话识别的唯一规则源；
core/store/sessions.py 将 Mixin 的同名静态方法绑定到这里的一个实现上，
调用方仍走 self._xxx，实现只有一份。
"""

import re
from typing import Any, List, Optional, Tuple

# 平台别名归一表：aiocqhttp 系协议端统一为 onebot（全插件唯一别名来源）
_ONEBOT_ALIASES = frozenset((
    "aiocqhttp", "aihttpcq", "cqhttp", "onebot",
    "onebot_v11", "onebotv11", "onebot11",
    "napcat", "lagrange", "llonebot", "gocqhttp", "qq", "chronocat",
))

_PLATFORM_RE = re.compile(r"^[a-z0-9_\-]+$")


def clean_platform(v: Any) -> str:
    """平台名清洗：字符串直接用；PlatformMetadata 之类对象取 .name；其他一律丢弃。

    绝不 str() 整个对象——那会产生 PlatformMetadata(name=...) 这种垃圾 key。
    返回统一小写的规范平台 id（别名归一 + 大小写归一）。
    """
    if isinstance(v, str):
        cand = v.strip().lower()
    elif v is None:
        return ""
    else:
        name = getattr(v, "name", None)
        cand = name.strip().lower() if isinstance(name, str) else ""
    if not cand or len(cand) > 32 or not _PLATFORM_RE.match(cand):
        return ""
    if cand in _ONEBOT_ALIASES:
        return "onebot"
    return cand


def platform_of(event: Any) -> str:
    """提取事件所属平台（onebot/telegram/...），取不到返回空串，不抛异常。"""
    try:
        # 官方 API 优先（新版 AstrBot 事件自带 get_platform_name）
        gpn = getattr(event, "get_platform_name", None)
        if callable(gpn):
            try:
                pn = clean_platform(gpn())
                if pn:
                    return pn
            except Exception:
                pass
        for attr in ("platform_id", "platform"):
            try:
                pn = clean_platform(getattr(event, attr, ""))
            except Exception:
                continue
            if pn:
                return pn
        try:
            msg_obj = getattr(event, "message_obj", None)
            pn = clean_platform(
                getattr(msg_obj, "platform_id", "") or getattr(msg_obj, "platform", ""))
            if pn:
                return pn
        except Exception:
            pass
        umo = getattr(event, "unified_msg_origin", "") or ""
        if isinstance(umo, str) and ":" in umo:
            return clean_platform(umo.split(":", 1)[0])
        return ""
    except Exception:
        return ""


def split_session_key(cks: str) -> Tuple[str, Optional[str], str]:
    """拆会话 key -> (kind, platform|None, ident)。

    新格式 kind:platform:ident 原样拆；老格式 kind:ident 平台为 None；脏串 kind 为空。
    """
    parts = str(cks or "").strip().split(":")
    if len(parts) >= 3 and parts[0].lower() in ("group", "private"):
        return parts[0].lower(), parts[1].strip() or None, ":".join(parts[2:]).strip()
    if len(parts) == 2 and parts[0].lower() in ("group", "private"):
        return parts[0].lower(), None, parts[1].strip()
    return "", None, str(cks or "").strip()


def canonical_key_str(k: str) -> str:
    """会话 key 归一（字符串口径，唯一实现）。

    新规范 kind:platform:ident：合法平台统一归一（aiocqhttp/aihttpcq -> onebot），
    脏平台保留供 is_sane_key 拦截；历史启发式仅用于兼容旧版本写入的脏 key。
    """
    s = str(k or "").strip()
    if not s:
        return ""
    kind, plat, ident = split_session_key(s)
    if kind and plat and ident:
        norm_plat = clean_platform(plat) or plat
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


def canonical_key(event_or_key: Any) -> str:
    """事件 -> 规范会话 key。新格式 kind:platform:ident（平台隔离，防跨平台同号串台）。

    gid/sender 属权威 id，有平台就限定；umo 纯启发式，原样归一不二次限定；
    平台取不到时回落老格式，保证不断连。
    """
    if isinstance(event_or_key, str):
        return canonical_key_str(event_or_key)
    plat = platform_of(event_or_key)
    try:
        gid = str(event_or_key.get_group_id() or "").strip()
        if gid:
            # 适配器已返回限定/复合格式（如 group:xxx / group:plat:gid）时直接规范化
            if ":" in gid:
                return canonical_key_str(gid)
            return f"group:{plat}:{gid}" if plat else f"group:{gid}"
    except Exception:
        pass
    umo = str(getattr(event_or_key, "unified_msg_origin", "") or "").strip()
    ck = canonical_key_str(umo)
    if ck.startswith("private:") or ck.startswith("group:"):
        return ck
    # 私聊兜底：尝试取 sender id（权威 id，有平台就限定）
    try:
        for attr in ("sender_id", "user_id", "qq", "uid"):
            uid = str(getattr(event_or_key, attr, "") or "").strip()
            if uid:
                if plat in ("onebot", "aiocqhttp"):
                    uid = re.sub(r"\D", "", uid) or uid
                return f"private:{plat}:{uid}" if plat else f"private:{uid}"
        msg_obj = getattr(event_or_key, "message_obj", None)
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


def candidate_keys(event_or_key: Any) -> List[str]:
    """会话解析候选表（全插件唯一实现）：canonical 优先，历史脏 key 与平台限定别名兜后。

    顺序即优先级：解析取首个命中，解绑清理取全部命中。
    """
    if isinstance(event_or_key, str):
        raw = [event_or_key, canonical_key_str(event_or_key)]
    else:
        ck = canonical_key(event_or_key)
        umo = str(getattr(event_or_key, "unified_msg_origin", "") or "").strip()
        raw = [ck, umo, canonical_key_str(umo)]
    out: List[str] = []
    for c in raw:
        ckc = canonical_key_str(c) if c else ""
        if ckc and ckc not in out:
            out.append(ckc)
    kind, plat, ident = split_session_key(out[0] if out else "")
    if kind and ident:
        alts = [f"{kind}:onebot:{ident}", f"{kind}:{ident}"] if (not plat or plat == "onebot") else [f"{kind}:{ident}"]
        for alt in alts:
            if alt not in out:
                out.append(alt)
    return out or ["default"]


def is_sane_key(cks: str) -> bool:
    """key 可用性：限定 key 的平台段必须合法（字母数字下划线短横，≤32），且排除 webchat/probe 污染。

    历史 bug 曾把 PlatformMetadata 整对象 repr 写进 key，或把 webchat:probe_xbdoc 写入会话记录，
    这类残骸直接丢弃。无平台段的老/裸 key 视为可用。
    """
    s_low = str(cks or "").strip().lower()
    if not s_low or "probe" in s_low or "webchat" in s_low or "functools.partial" in s_low:
        return False
    kind, plat, ident = split_session_key(cks)
    if kind and plat:
        if len(plat) > 32 or not re.match(r"^[A-Za-z0-9_\-]+$", plat):
            return False
        if plat.lower() == "webchat":
            return False
    if ident and "probe" in ident.lower():
        return False
    return True
