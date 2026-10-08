"""xbdoc 存储层：持久化、文档 CRUD、切片缓存、会话绑定解析、配置读取。

被主插件多继承（Mixin），不含任何 @filter 装饰方法。
"""

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
    _HAS_DATA_PATH = True
except Exception:
    _HAS_DATA_PATH = False

try:
    from .retrieval import (
        ALLOWED_SUFFIXES,
        chunk_text,
        extract_text_from_bytes,
        tokenize,
    )
except ImportError:
    from retrieval import (
        ALLOWED_SUFFIXES,
        chunk_text,
        extract_text_from_bytes,
        tokenize,
    )

PLUGIN_NAME = "astrbot_plugin_xbdoc"

# 配置唯一来源（无 _conf_schema.json）：默认值 + data_dir/plugin_config.json 覆盖 + 运行时 self.config
CONFIG_DEFAULTS: Dict[str, Any] = {
    "chunk_size": 1500,
    "chunk_overlap": 200,
    "top_k": 3,
    "max_inject_chars": 6000,
    "auto_inject": True,
    "fallback_inject": True,
    "allow_private_bind": True,
    "perf_log": False,
    # UI 偏好：AstrBot 用沙箱 iframe 载插件页，localStorage 被禁，
    # 主题色/深浅色只存本地刷新即丢，必须落服务端。见下方 CONFIG_META 同名键（hidden）。
    "ui_accent_color": "",
    "ui_theme_mode": "",
}

# 配置项元数据：供 WebUI 设置页渲染（description/hint 与原 _conf_schema.json 对齐）
CONFIG_META: Dict[str, Dict[str, Any]] = {
    "chunk_size": {
        "description": "文档切片长度（字符数）",
        "hint": "段落优先切分，超出此长度自动截断。建议 1500 兼顾效果与 token 消耗。",
        "type": "int",
    },
    "chunk_overlap": {
        "description": "切片重叠字符数",
        "hint": "保留上下文连贯性，建议为 chunk_size 的 10%~20%。",
        "type": "int",
    },
    "top_k": {
        "description": "单次检索注入片段数量",
        "hint": "建议 3~5 片段，避免挤占模型上下文。",
        "type": "int",
    },
    "max_inject_chars": {
        "description": "单次注入最大字符上限",
        "hint": "0 表示不限制，保证完整注入；防止提示词过长超出大模型单次承载能力可设正数。",
        "type": "int",
    },
    "auto_inject": {
        "description": "自动检索与上下文注入",
        "hint": "开启后在模型对话前自动检索相关片段注入。",
        "type": "bool",
    },
    "fallback_inject": {
        "description": "未命中时保底注入首片段",
        "hint": "检索无关键词命中时，保底载入绑定文档首片段，确保模型拥有文档认知；关闭则无命中不注入。",
        "type": "bool",
    },
    "allow_private_bind": {
        "description": "允许私聊会话独立绑定",
        "hint": "关闭后仅群聊生效。",
        "type": "bool",
    },
    "perf_log": {
        "description": "性能日志（排查回复慢）",
        "hint": "开启后每条回复记录插件耗时、注入字数与上下文规模，定位慢的原因。",
        "type": "bool",
    },
    # 隐藏的 UI 偏好（主题色/深浅色）：AstrBot 沙箱 iframe 禁 localStorage，必须落服务端。
    # hidden=True → 设置页不渲染、collectSettings 不发送，因此手动保存不会覆盖这两个键。
    "ui_accent_color": {
        "description": "界面主题色",
        "hint": "由顶栏取色器写入，不在设置页手工编辑。",
        "type": "string",
        "hidden": True,
    },
    "ui_theme_mode": {
        "description": "界面深浅色",
        "hint": "由顶栏切换按钮写入，不在设置页手工编辑。",
        "type": "string",
        "hidden": True,
    },
}

# 模式强度（隔离级别）：脏 key 合并时高强度胜出，保证结果与遍历顺序无关
_MODE_PRIORITY = {"none": -1, "reference": 0, "system": 1, "workspace": 2}


def _locked(method):
    """串行化写方法：与 _save_lock（RLock）配合，可嵌套，不死锁。"""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._save_lock:
            return method(self, *args, **kwargs)
    return wrapper


# ======================================================================
# 存储 Mixin
# ======================================================================

class XbdocStoreMixin:

    def _init_store(self) -> None:
        """初始化持久化存储：路径、缓存、锁、数据加载与标准化（变化才回写）。"""
        # 锁与缓存必须先就绪：后续 _save_json/_load_chunks 依赖它们
        # RLock：读改写关键区（bind/unbind/入库）可与内部的 _save_json 嵌套加锁，不死锁
        self._save_lock = threading.RLock()  # 落盘+绑定锁：防 WebUI 与聊天指令并发写撕裂
        # 细锁：只护四个缓存字典的 LRU 触达/回填，注入与检索热路径不再抢全局 _save_lock。
        # 锁序恒为 _save_lock → _cache_lock（写路径先全局后细锁），反向永不发生，故不死锁
        self._cache_lock = threading.RLock()
        # 字节流写盘互斥：与状态锁解耦（字节入参不可变，写盘期间无需护内存态）
        self._io_lock = threading.Lock()
        # 专用线程池：上传入库等重活不占默认 executor；提交空任务预热线程，首传免 spawn 延迟
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="xbdoc")
        try:
            self._executor.submit(lambda: None)
        except Exception:
            pass
        self._chunk_cache: Dict[str, List[str]] = {}  # 内存缓存：doc_id -> chunks
        self._chunk_tokens_cache: Dict[str, List[Counter]] = {}  # 性能优化：doc_id -> 每切片词频
        self._seen_save_ts = 0  # 群记录节流时间戳（仅内存，不落盘）
        self._fulltext_cache: Dict[str, str] = {}  # doc_id -> 全文（system/workspace 免每消息重拼）
        self._bm25_cache: Dict[str, Any] = {}  # BM25 全局量缓存（key 命中即复用）
        # 持久化存储路径
        self._latest_bot = None
        self.data_dir = self._resolve_data_dir()
        self.docs_dir = self.data_dir / "docs"
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.data_dir / "index.json"
        self.bindings_path = self.data_dir / "bindings.json"
        self.seen_path = self.data_dir / "seen_groups.json"
        self.config_path = self.data_dir / "plugin_config.json"
        # 崩溃残留的 tmp 先清，避免越积越多（正常 save 结束无残留）
        try:
            for _tmp in self.data_dir.glob("*.tmp"):
                try:
                    _tmp.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            for _tmp in self.docs_dir.glob("*.tmp"):
                try:
                    _tmp.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        # 加载并自动标准化数据（有变才回写，避免每次启动空转 I/O）
        self._index: Dict[str, Dict[str, Any]] = self._load_json(self.index_path, {})
        # 索引损坏时回落为空字典，避免后续 .get 崩溃
        if not isinstance(self._index, dict):
            self._index = {}
        # WebUI 覆盖配置：叠加在 AstrBot 注入的 self.config 之上（删除 _conf_schema.json 后唯一持久入口）
        self._load_plugin_config_overlay()
        _raw_seen = self._load_json(self.seen_path, {})
        # 污染自清：坏 key 整条扔；platform 脏字段——有真限定 key 的只清字段，
        # 无限定 key 配垃圾平台的整条扔（不可信，群下次露面自动重建）
        self._seen_groups = {}
        _scrubbed = 0
        if isinstance(_raw_seen, dict):
            for _k, _v in _raw_seen.items():
                if not self._is_sane_key(str(_k)):
                    _scrubbed += 1
                    continue
                if isinstance(_v, dict):
                    if _v.get("platform") and not self._clean_platform(_v.get("platform")):
                        _kk, _kplat, _iid = self._split_session_key(str(_k))
                        if _kplat:
                            _v["platform"] = ""
                        else:
                            _scrubbed += 1
                            continue
                    self._seen_groups[_k] = _v
        if _scrubbed:
            logger.warning(f"[{PLUGIN_NAME}] 启动清理污染群记录 {_scrubbed} 条")
            self._save_seen()
        _raw_bindings = self._load_json(self.bindings_path, {})
        self._bindings: Dict[str, Dict[str, Any]] = self._normalize_bindings(_raw_bindings)
        if self._bindings != _raw_bindings and self.bindings_path.exists():
            self._save_json(self.bindings_path, self._bindings)


    def save_all(self) -> None:
        """全量落盘（terminate 唯一调用）。"""
        self._save_json(self.index_path, self._index)
        self._save_json(self.bindings_path, self._bindings)
        self._save_seen()


    # ---------- 路径与持久化 ----------
    def _resolve_data_dir(self) -> Path:
        if _HAS_DATA_PATH:
            try:
                return Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
            except Exception:
                pass
        _plug_root = Path(__file__).resolve().parent.parent
        for cand in [
            _plug_root.parent.parent.parent / "data" / "plugin_data" / PLUGIN_NAME,
            Path.cwd() / "data" / "plugin_data" / PLUGIN_NAME,
            _plug_root / "data_store",
        ]:
            try:
                cand.mkdir(parents=True, exist_ok=True)
                return cand.resolve()
            except Exception:
                continue
        # 终极兜底：系统临时目录（可写、独立、不污染工程；重启不丢由 AstrBot 数据目录保证）
        fallback = Path(tempfile.gettempdir()) / PLUGIN_NAME
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback.resolve()
        except Exception:
            return fallback


    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] 读取 {path.name} 失败: {e}")
            # 损坏文件先备份再丢弃，避免下次保存直接覆盖丢失现场
            try:
                if path.exists() and path.stat().st_size > 0:
                    bak = path.with_name(f"{path.stem}.corrupt-{int(time.time())}.bak")
                    bak.write_bytes(path.read_bytes())
                    logger.warning(f"[{PLUGIN_NAME}] 已备份损坏文件: {bak.name}")
            except Exception:
                pass
        return default


    def _save_json(self, path: Path, data: Any, indent: Optional[int] = None) -> None:
        # 原子写：先落 tmp 再 os.replace，同文件系统下读方永不见半截文件
        # 默认紧凑（省 IO/磁盘）；需人工编辑的文件（如 plugin_config.json）显式传 indent=2
        try:
            with self._save_lock:
                tmp = path.with_name(f"{path.name}.tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
                os.replace(tmp, path)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 保存 {path.name} 失败: {e}")


    def _save_bytes_atomic(self, path: Path, data: bytes) -> None:
        """二进制原子写（切片缓存/入库原文件）：只持 _io_lock，不占状态锁——

        写盘是可并行的慢活，护住 _save_lock 会把读路径整段卡住；字节入参不可变，
        同路径写者由 _io_lock 互斥，os.replace 原子可见。
        """
        with self._io_lock:
            tmp = path.with_name(f"{path.name}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)


    def _save_seen(self) -> None:
        if len(self._seen_groups) > 500:
            items = sorted(
                self._seen_groups.items(),
                key=lambda kv: kv[1].get("last_seen", 0),
                reverse=True,
            )[:500]
            self._seen_groups = dict(items)
        self._save_json(self.seen_path, self._seen_groups)


    @staticmethod
    def _clean_platform(v: Any) -> str:
        """平台名清洗：字符串直接用；PlatformMetadata 之类对象取 .name；其他一律丢弃。

        绝不 str() 整个对象——那会产生 PlatformMetadata(name=...) 这种垃圾 key。
        """
        if isinstance(v, str):
            cand = v.strip()
        elif v is None:
            return ""
        else:
            name = getattr(v, "name", None)
            cand = name.strip() if isinstance(name, str) else ""
        if not cand or len(cand) > 32 or not re.match(r"^[A-Za-z0-9_\-]+$", cand):
            return ""
        return cand

    @staticmethod
    def _platform_of(event: Any) -> str:
        """提取事件所属平台（onebot/telegram/...），取不到返回空串，不抛异常。"""
        try:
            # 官方 API 优先（新版 AstrBot 事件自带 get_platform_name）
            gpn = getattr(event, "get_platform_name", None)
            if callable(gpn):
                try:
                    pn = XbdocStoreMixin._clean_platform(gpn())
                    if pn:
                        return pn
                except Exception:
                    pass
            for attr in ("platform_id", "platform"):
                try:
                    pn = XbdocStoreMixin._clean_platform(getattr(event, attr, ""))
                except Exception:
                    continue
                if pn:
                    return pn
            try:
                msg_obj = getattr(event, "message_obj", None)
                pn = XbdocStoreMixin._clean_platform(
                    getattr(msg_obj, "platform_id", "") or getattr(msg_obj, "platform", ""))
                if pn:
                    return pn
            except Exception:
                pass
            umo = getattr(event, "unified_msg_origin", "") or ""
            if isinstance(umo, str) and ":" in umo:
                return XbdocStoreMixin._clean_platform(umo.split(":", 1)[0])
            return ""
        except Exception:
            return ""

    def _record_seen_group(self, event: AstrMessageEvent) -> None:
        """记录会话基础信息，供 WebUI 模糊搜索/绑定选用（群聊与私聊通用）。"""
        try:
            platform = self._platform_of(event)
            if not platform and not getattr(self, "_platform_warned", False):
                self._platform_warned = True
                logger.warning(
                    f"[{PLUGIN_NAME}] 事件中取不到平台名，会话 key 将回落为无平台格式；"
                    f"请确认 AstrBot 版本/适配器是否上报平台信息。"
                )

            gid = str(event.get_group_id() or "").strip()
            if not gid:
                self._record_seen_private(event, platform)
                return

            group_name = ""
            grp = getattr(event.message_obj, "group", None)
            if grp is not None:
                group_name = str(getattr(grp, "group_name", "") or "").strip()

            now = int(time.time())
            # seen 键同样平台限定（group:plat:gid），跨平台同号不再互相覆盖
            seen_key = f"group:{platform}:{gid}" if platform else gid
            ent = self._seen_groups.setdefault(seen_key, {
                "gid": gid, "group_name": group_name, "platform": platform,
                "kind": "group",
                "last_seen": now, "msg_count": 0,
            })
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

    def _record_seen_private(self, event: AstrMessageEvent, platform: str) -> None:
        """记录私聊会话（sender 昵称复用 group_name 字段展示，kind 标记区分）。"""
        try:
            uid = ""
            nickname = ""
            try:
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
            except Exception:
                pass
            if not uid:
                ck = self._canonical_key(event)
                if ck.startswith("private:"):
                    uid = ck.split(":", 1)[1]
            if not uid:
                return
            uid = re.sub(r"\D", "", uid) or uid
            key = f"private:{platform}:{uid}" if platform else f"private:{uid}"

            now = int(time.time())
            ent = self._seen_groups.setdefault(key, {
                "gid": uid, "group_name": nickname, "platform": platform,
                "kind": "private",
                "last_seen": now, "msg_count": 0,
            })
            ent["kind"] = "private"
            ent["last_seen"] = now
            ent["msg_count"] = int(ent.get("msg_count", 0)) + 1
            if nickname and nickname != ent.get("group_name"):
                ent["group_name"] = nickname
            if platform and not ent.get("platform"):
                ent["platform"] = platform

            if ent["msg_count"] % 25 == 0 or (now - self._seen_save_ts) > 45:
                self._seen_save_ts = now
                self._save_seen()
        except Exception:
            pass


    # ---------- 文档管理 ----------
    @staticmethod
    def _safe_filename(name: str) -> str:
        name = (name or "unnamed").strip().replace("\\", "_").replace("/", "_")
        name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name) or "unnamed"
        # ext4 等按字节限长（255B）：中文占 3 字节，超限会写盘崩溃
        return name.encode("utf-8")[:200].decode("utf-8", errors="ignore") or "unnamed"


    def add_document(self, filename: str, data: bytes) -> Dict[str, Any]:
        """入库文档：提取/切片/写盘等慢活在锁外做，锁只护 _index 与缓存的状态改写。

        读路径（list_documents/_load_chunks 等）共享 _save_lock——若在锁内做
        秒级的大文件提取或几十 MB 的写盘，事件循环上的 WebUI/聊天读会被整段卡住。
        """
        filename = self._safe_filename(filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise RuntimeError(f"不支持的类型 {suffix or '(无后缀)'}，支持格式: {sorted(ALLOWED_SUFFIXES)}")
        if not data:
            raise RuntimeError("空文件，无法入库")
        if len(data) > 50 * 1024 * 1024:
            raise RuntimeError("文件超出 50MB 上限，请拆分后上传")

        text = extract_text_from_bytes(suffix, data).strip()  # 锁外：秒级慢活

        if len(text) < 2:
            raise RuntimeError("提取纯文本内容过少，拒绝入库")

        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        doc_id = hashlib.md5(f"{filename}:{len(data)}:{text_hash}".encode("utf-8")).hexdigest()[:10]
        stored_name = f"{doc_id}_{filename}"
        # 切片参数一次性相邻取值，避免与配置保存并发时取到混合参数
        chunks = chunk_text(text, self._cfg_int("chunk_size"), self._cfg_int("chunk_overlap"))
        meta = {
            "doc_id": doc_id,
            "filename": filename,
            "stored_name": stored_name,
            "suffix": suffix,
            "text_len": len(text),
            "chunks": len(chunks),
            "updated_at": int(time.time()),
        }
        # 只读取旧文件名（_index 字典读取原子），供下面锁外清理残留用
        old_stored = str((self._index.get(doc_id) or {}).get("stored_name", ""))

        # 锁外磁盘写：新原文件与切片缓存先落盘，读者最坏看到的是「文件已就位、索引未发布」
        self._save_bytes_atomic(self.docs_dir / stored_name, data)
        self._save_bytes_atomic(
            self.data_dir / f"chunks_{doc_id}.json",
            json.dumps(chunks, ensure_ascii=False).encode("utf-8"),
        )

        with self._save_lock:
            self._index[doc_id] = meta
            with self._cache_lock:
                self._chunk_cache[doc_id] = chunks  # 更新内存缓存
                self._chunk_tokens_cache.pop(doc_id, None)  # 词频缓存失效，下次检索重建
                self._fulltext_cache.pop(doc_id, None)  # 全文缓存失效
            # BM25 全局量与绑定集合相关：任何文档变更都可能改变 idf，直接整桶清空最稳
            try:
                _bm25 = getattr(self, "_bm25_cache", None)
                if isinstance(_bm25, dict):
                    _bm25.clear()
            except Exception:
                pass
            self._save_json(self.index_path, self._index)  # 小 JSON，锁内落盘

        # 锁外：删同 ID 旧文件（索引已切换到新文件，读者不再需要它）
        if old_stored and old_stored != stored_name:
            try:
                old_p = self.docs_dir / old_stored
                if old_p.exists():
                    old_p.unlink()
            except Exception:
                pass
        logger.info(f"[{PLUGIN_NAME}] 入库文档 {filename} id={doc_id} chunks={len(chunks)}")
        return meta


    def delete_document(self, doc_id: str) -> bool:
        """删文档：锁只护 _index/缓存/绑定的状态改写与小 JSON 落盘，磁盘 unlink 出锁。"""
        stored = ""
        with self._save_lock:
            meta = self._index.pop(doc_id, None)
            if not meta:
                return False
            stored = str(meta.get("stored_name", ""))
            with self._cache_lock:  # 清除内存缓存（与 _cache_touch 同锁，命中触达不抢全局锁）
                self._chunk_cache.pop(doc_id, None)
                self._chunk_tokens_cache.pop(doc_id, None)
                self._fulltext_cache.pop(doc_id, None)
            try:
                _bm25 = getattr(self, "_bm25_cache", None)
                if isinstance(_bm25, dict):
                    _bm25.clear()
            except Exception:
                pass

            # 同步清理所有绑定引用；无有效文档的会话按唯一回落规则切 none 并尝试删除空条目
            changed = False
            for key, ent in list(self._bindings.items()):
                if doc_id in ent.get("doc_ids", []):
                    ent["doc_ids"] = [i for i in ent["doc_ids"] if i != doc_id]
                    ent["mode"] = self._effective_mode(ent)
                    self._prune_empty_entry(key)
                    changed = True
            self._save_json(self.index_path, self._index)
            if changed:
                self._save_json(self.bindings_path, self._bindings)

        # 锁外磁盘清理：索引已摘除（_load_chunks 按 _index 复验），读者不再需要这两个文件；
        # 慢 I/O 不占状态锁（审计 #12「锁内只护内存态，磁盘 I/O 出锁」）
        targets = [self.data_dir / f"chunks_{doc_id}.json"]
        if stored:
            targets.insert(0, self.docs_dir / stored)
        for p in targets:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        return True


    def list_documents(self) -> List[Dict[str, Any]]:
        # 读也持锁：与 add/delete 锁内改 _index 对齐，锁内取快照、锁外排序
        with self._save_lock:
            items = list(self._index.values())
        return sorted(items, key=lambda m: m.get("updated_at", 0), reverse=True)


    def _cache_touch(self, cache: Dict[str, Any], doc_id: str) -> Optional[Any]:
        """LRU 触达：命中即移到队尾并返回，未命中或文档已删返回 None。

        只持 _cache_lock（注入/检索热路径不再抢全局 _save_lock）：字典 pop/回写原子，
        写后复验 _index —— 与并发删除（先删索引再弹缓存）的任意时序交错都会回滚收敛，
        不会把已删文档的内容留在缓存里。
        """
        with self._cache_lock:
            val = cache.pop(doc_id, None)
            if val is None:
                return None
            cache[doc_id] = val
            if doc_id not in self._index:
                cache.pop(doc_id, None)  # 写后复验：删除已发生，回滚
                return None
            return val


    def _load_chunks(self, doc_id: str) -> List[str]:
        # 内存缓存命中（命中即移到队尾，变 FIFO 为 LRU，热点文档不被挤掉）；
        # 热路径只取细锁 _cache_lock，与落盘写家互不阻塞
        hit = self._cache_touch(self._chunk_cache, doc_id)
        if hit is not None:
            return hit

        cache = self.data_dir / f"chunks_{doc_id}.json"
        try:
            if cache.exists():
                data = json.loads(cache.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    result = [str(x) for x in data]
                    self._remember_chunks(doc_id, result)
                    return result
        except Exception:
            pass

        meta = self._index.get(doc_id)
        if not meta:
            return []
        try:
            raw = (self.docs_dir / str(meta["stored_name"])).read_bytes()
            text = extract_text_from_bytes(str(meta.get("suffix", "")), raw)
            chunks = chunk_text(text, self._cfg_int("chunk_size"), self._cfg_int("chunk_overlap"))
            # 提取期间文档可能已被删除：锁内复验后才写缓存文件，防留下孤儿 chunks_*.json
            with self._save_lock:
                if doc_id not in self._index:
                    return []
                self._save_bytes_atomic(cache, json.dumps(chunks, ensure_ascii=False).encode("utf-8"))
                self._remember_chunks(doc_id, chunks)
            return chunks
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 重建切片失败 {doc_id}: {e}")
            return []


    def _remember_chunks(self, doc_id: str, chunks: List[str]) -> None:
        """缓存切片并做简单上限保护，防止文档过多时内存无限增长。"""
        with self._cache_lock:
            if len(self._chunk_cache) > 200:
                try:
                    oldest = next(iter(self._chunk_cache))
                    self._chunk_cache.pop(oldest, None)
                    self._chunk_tokens_cache.pop(oldest, None)
                except Exception:
                    pass
            self._chunk_cache[doc_id] = chunks
            if doc_id not in self._index:
                # 写后复验：与并发删除（先删索引再弹缓存）任意交错都会回滚，不复活已删内容
                self._chunk_cache.pop(doc_id, None)


    def _get_chunk_counters(self, doc_id: str) -> List[Counter]:
        """获取每切片词频（缓存），避免每次提问重复分词全量切片。"""
        cached = self._cache_touch(self._chunk_tokens_cache, doc_id)
        if cached is not None:
            return cached
        chunks = self._load_chunks(doc_id)
        counters = [Counter(tokenize(ch)) for ch in chunks]
        with self._cache_lock:
            if len(self._chunk_tokens_cache) > 200:
                try:
                    oldest = next(iter(self._chunk_tokens_cache))
                    self._chunk_tokens_cache.pop(oldest, None)
                except Exception:
                    pass
            self._chunk_tokens_cache[doc_id] = counters
            if doc_id not in self._index:  # 写后复验：文档已删则回滚，防删除后复活缓存
                self._chunk_tokens_cache.pop(doc_id, None)
        return counters


    def _get_full_text(self, doc_id: str) -> str:
        """获取文档全文（缓存）：system/workspace 模式每消息复用，入库/删除时失效。"""
        cached = self._cache_touch(self._fulltext_cache, doc_id)
        if cached is not None:
            return cached
        text = "\n".join(self._load_chunks(doc_id))
        with self._cache_lock:
            if len(self._fulltext_cache) > 50:
                try:
                    self._fulltext_cache.pop(next(iter(self._fulltext_cache)))
                except Exception:
                    pass
            self._fulltext_cache[doc_id] = text
            if doc_id not in self._index:  # 写后复验：文档已删则回滚，防删除后复活缓存
                self._fulltext_cache.pop(doc_id, None)
        return text


    # ---------- 会话与绑定管理 ----------
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
        # 新规范 kind:platform:ident 直接透传
        kind, plat, ident = XbdocStoreMixin._split_session_key(s)
        if kind and plat and ident:
            return f"{kind}:{plat}:{ident}"
        if s.lower().startswith("group:"):
            tail = s.split(":", 1)[1].strip()
            return f"group:{tail}" if tail else ""
        if s.isdigit():
            return f"group:{s}"
        m = re.search(r"(?:GroupMessage|group)\s*:\s*(\d+)", s, re.IGNORECASE)
        if m:
            return f"group:{m.group(1)}"
        # 私聊不再冒充 group，避免私聊号与群号碰撞；统一归一为 private:xxx
        mp = re.search(r"(?:FriendMessage|PrivateMessage|Private|Friend|User)\s*:\s*(\S+)", s, re.IGNORECASE)
        if mp:
            uid = re.sub(r"\D", "", mp.group(1)) or mp.group(1).strip()
            return f"private:{uid}" if uid else s
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
                    uid = re.sub(r"\D", "", uid) or uid
                    return f"private:{plat}:{uid}" if plat else f"private:{uid}"
            msg_obj = getattr(event_or_str, "message_obj", None)
            sender = getattr(msg_obj, "sender", None) if msg_obj is not None else None
            if sender is not None:
                uid = str(getattr(sender, "user_id", "") or getattr(sender, "id", "") or "").strip()
                if uid:
                    uid = re.sub(r"\D", "", uid) or uid
                    return f"private:{plat}:{uid}" if plat else f"private:{uid}"
        except Exception:
            pass
        return ck or "default"


    @staticmethod
    def _is_sane_key(cks: str) -> bool:
        """key 可用性：限定 key 的平台段必须合法（字母数字下划线短横，≤32）。

        历史 bug 曾把 PlatformMetadata 整对象 repr 写进 key，这类残骸永远匹配不到
        真实事件，直接丢弃。无平台段的老/裸 key 视为可用。
        """
        kind, plat, _ident = XbdocStoreMixin._split_session_key(cks)
        if kind and plat:
            if len(plat) > 32 or not re.match(r"^[A-Za-z0-9_\-]+$", plat):
                return False
        return True

    def _normalize_bindings(self, raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """标准化绑定：key 归一、模式归一，同 key 条目确定性合并。"""
        out: Dict[str, Dict[str, Any]] = {}
        if not isinstance(raw, dict):
            return out
        for k, v in raw.items():
            ck = self._canonical_key_str(str(k))
            if not ck or not isinstance(v, dict):
                continue
            if not self._is_sane_key(ck):
                logger.warning(f"[{PLUGIN_NAME}] 丢弃污染会话 key: {str(k)[:80]}")
                continue
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
            p = str(meta.get("platform") or "").strip()
            if p:
                plats.add(p)
        return plats


    def _session_keys(self, event: AstrMessageEvent) -> List[str]:
        ck = self._canonical_key(event)
        keys = [ck]
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        for cand in (umo, self._canonical_key_str(umo)):
            if cand and cand not in keys:
                keys.append(cand)
        return keys


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
            _pf = XbdocStoreMixin._clean_platform(old.get("platform", ""))
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
        plats = self._seen_platforms(kind, ident, self._seen_groups)
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
        """全插件统一会话解析：canonical 优先命中，其次兼容历史脏 key。

        返回 (matched_key, entry)。create=False 时未命中返回 {} 且绝不写 bindings，
        调用方拿到的 key 即真正生效的 key，不再各算一遍；候选表只来自 _session_keys
        （其内部即 _canonical_key_str 单实现归一），此处不再自算第二份。
        """
        if isinstance(event_or_key, str):
            cands = [event_or_key]
        else:
            try:
                cands = self._session_keys(event_or_key) or ["default"]
            except Exception:
                cands = ["default"]
        for k in cands:
            ck = self._canonical_key_str(k)
            if ck and ck in self._bindings:
                return ck, self._bindings[ck]
        primary_ck = self._canonical_key_str(cands[0]) if cands else "default"
        if not primary_ck:
            primary_ck = "default"
        if create:
            return primary_ck, self._get_entry(primary_ck)
        return primary_ck, {}


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
        """找到本会话所有命中的绑定 Key（解决新旧 Key 并存导致解绑遗漏）。

        候选表只取一次 _session_keys（归一走 _canonical_key_str 单实现），
        命中者在前、canonical 兜底在后，不再重复算第二遍 canonical。
        """
        keys: List[str] = []
        primary = ""
        for k in self._session_keys(event):
            ck = self._canonical_key_str(k)
            if not ck:
                continue
            if not primary:
                primary = ck
            if ck in self._bindings and ck not in keys:
                keys.append(ck)
        if primary and primary not in keys:
            keys.append(primary)
        if not keys:  # 全部候选归一为空的病态兜底：与 _resolve_session 的 default 口径一致
            keys.append("default")
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


    # ---------- 插件配置（WebUI 读写 + data_dir 持久化） ----------
    def _load_plugin_config_overlay(self) -> None:
        """把 data_dir/plugin_config.json 中的合法键叠加到 self.config（WebUI 保存优先）。"""
        try:
            persisted = self._load_json(self.config_path, {})
            if not isinstance(persisted, dict) or not persisted:
                return
            base = getattr(self, "config", None)
            cfg = dict(base) if hasattr(base, "items") else {}
            for k in CONFIG_DEFAULTS:
                if k in persisted:
                    cfg[k] = persisted[k]
            self.config = cfg
        except Exception:
            pass

    def get_plugin_config(self) -> Dict[str, Any]:
        """当前生效配置：默认值打底，仅回传已知键。"""
        out: Dict[str, Any] = {}
        for k, d in CONFIG_DEFAULTS.items():
            try:
                v = self._cfg(k, d)
            except Exception:
                v = d
            out[k] = v
        return out

    def get_config_meta(self) -> Dict[str, Dict[str, Any]]:
        """设置页渲染元数据：key -> {description, hint, type, default}。"""
        return {
            k: {
                **meta,
                "default": CONFIG_DEFAULTS.get(k),
            }
            for k, meta in CONFIG_META.items()
        }

    def save_plugin_config(self, incoming: Any) -> Dict[str, Any]:
        """校验并保存 WebUI 设置；仅接受 CONFIG_DEFAULTS 已知键，类型/范围收敛后写回。

        锁只护 config 快照改写与小 JSON 落盘；切片缓存作废中的批量 unlink 是慢 I/O，
        移到出锁后做（审计 #12「锁内只护内存态，磁盘 I/O 出锁」）。
        """
        if not isinstance(incoming, dict):
            raise ValueError("config 须为对象")
        invalidate = False
        with self._save_lock:
            cfg = dict(getattr(self, "config", None) or {})
            # 记录切片参数旧值：变更时作废存量切片缓存（否则改 chunk_size 只对新上传生效）
            old_chunk_params = (cfg.get("chunk_size"), cfg.get("chunk_overlap"))
            for k in CONFIG_DEFAULTS:
                if k not in incoming:
                    continue
                v = incoming[k]
                if CONFIG_META.get(k, {}).get("type") == "bool":
                    if isinstance(v, str):
                        v = v.strip().lower() in ("1", "true", "yes", "on")
                    cfg[k] = bool(v)
                elif CONFIG_META.get(k, {}).get("type") == "string":
                    # 文本型配置：不走下面的 int() 收敛（int("") 抛错即 continue，主题色会永远存不进去）。
                    # 按键做白名单校验，脏值直接丢弃保留现值
                    s = str(v if v is not None else "").strip()
                    if k == "ui_accent_color":
                        if s:
                            body = s[1:] if s.startswith("#") else ""
                            if len(body) != 6 or any(c not in "0123456789abcdefABCDEF" for c in body):
                                continue
                            s = "#" + body
                    elif k == "ui_theme_mode" and s not in ("", "light", "dark"):
                        continue
                    cfg[k] = s
                else:
                    try:
                        iv = int(v)
                    except Exception:
                        continue
                    if k == "max_inject_chars":
                        cfg[k] = max(0, iv)
                    elif k in ("chunk_size", "chunk_overlap", "top_k"):
                        if iv < 0 or (iv == 0 and k != "chunk_overlap"):
                            continue
                        if k == "chunk_size":
                            iv = max(200, iv)
                        elif k == "chunk_overlap":
                            iv = max(0, iv)
                        cfg[k] = iv
            # 切片参数有变：作废全部切片缓存，下次读取按新参数惰性重建——
            # 否则存量文档永远停留在旧参数，WebUI 改 chunk_size 看起来“无效”
            invalidate = (cfg.get("chunk_size"), cfg.get("chunk_overlap")) != old_chunk_params
            # 合并后的完整快照落盘（缺失键补默认，便于人工编辑）
            snapshot = {k: cfg.get(k, CONFIG_DEFAULTS[k]) for k in CONFIG_DEFAULTS}
            self.config = {**cfg, **snapshot}
            self._save_json(self.config_path, snapshot, indent=2)
        if invalidate:
            # 新配置已生效后再作废：内存清桶 + 锁外批量删切片文件，下次读取按新参数惰性重建
            self._invalidate_chunk_caches()
        return dict(snapshot)

    def _invalidate_chunk_caches(self) -> None:
        """切片参数变更后作废全部切片缓存（内存 + chunks_*.json + BM25），惰性重建。"""
        with self._save_lock:  # 只护内存缓存桶的状态改写
            self._chunk_cache.clear()
            self._chunk_tokens_cache.clear()
            self._fulltext_cache.clear()
            try:
                self._bm25_cache.clear()
            except Exception:
                pass
        # 锁外批量 unlink（审计 #12）：慢 I/O 不占状态锁；文件已无内存引用，读路径按需重建
        for p in self.data_dir.glob("chunks_*.json"):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    # ---------- 动态配置读取（唯一来源：CONFIG_DEFAULTS + 实时 config） ----------
    def _cfg(self, key: str, default: Any = None) -> Any:
        try:
            if default is None:
                default = CONFIG_DEFAULTS.get(key)
            cfg = getattr(self, "config", None) or {}
            val = cfg.get(key, default) if hasattr(cfg, "get") else default
            return default if val is None else val
        except Exception:
            return CONFIG_DEFAULTS.get(key, default)


    def _cfg_int(self, key: str, default: Optional[int] = None) -> int:
        """读正整数配置：非法值/<=0 时回落（显式 default 优先，其次 CONFIG_DEFAULTS）。"""
        try:
            fallback = int(CONFIG_DEFAULTS.get(key, 0))
        except Exception:
            fallback = 0
        try:
            d = fallback if default is None else int(default)
            v = int(self._cfg(key, d))
            if v > 0:
                return v
            return d if d > 0 else fallback
        except Exception:
            return fallback if fallback > 0 else 0


    def _cfg_no_limit(self, key: str) -> int:
        """读取字符上限：<=0 表示不限制、保证完整注入（与 _cfg_int 强制正数不同）。"""
        try:
            return int(self._cfg(key, CONFIG_DEFAULTS.get(key, 0)))
        except Exception:
            return int(CONFIG_DEFAULTS.get(key, 0))
