"""持久化基础设施：初始化、数据目录解析、JSON/字节原子写、seen 落盘。"""

import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections import Counter
from typing import Any, Dict, List, Optional

from astrbot.api import logger

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
    _HAS_DATA_PATH = True
except Exception:
    _HAS_DATA_PATH = False

from .common import PLUGIN_NAME

class StorePersistenceMixin:
    """持久化基础设施：初始化、数据目录解析、JSON/字节原子写、seen 落盘。"""

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
        _migrated_seen = False
        if isinstance(_raw_seen, dict):
            for _k, _v in _raw_seen.items():
                _ks = str(_k)
                if not self._is_sane_key(_ks):
                    _scrubbed += 1
                    continue
                if isinstance(_v, dict):
                    _raw_gid = str(_v.get("gid") or "").strip()
                    if "probe" in _raw_gid.lower() or str(_v.get("platform") or "").strip().lower() == "webchat":
                        _scrubbed += 1
                        continue
                    _raw_plat = _v.get("platform")
                    if _raw_plat:
                        _cleaned_plat = self._clean_platform(_raw_plat)
                        if not _cleaned_plat:
                            _kk, _kplat, _iid = self._split_session_key(_ks)
                            if _kplat:
                                _v["platform"] = ""
                                _scrubbed += 1
                            else:
                                _scrubbed += 1
                                continue
                        elif _cleaned_plat != _raw_plat:
                            _v["platform"] = _cleaned_plat
                            _migrated_seen = True
                    _ck = self._canonical_key_str(_ks) if ":" in _ks else _ks
                    _kk2, _kplat2, _iid2 = self._split_session_key(_ck)
                    if not _kk2 and _ck.isdigit():
                        _kk2, _iid2 = "group", _ck
                    if _kk2 in ("group", "private") and not _kplat2 and _iid2:
                        _vp = self._clean_platform(_v.get("platform", "")) or ("onebot" if _kk2 == "group" and _iid2.isdigit() else "")
                        if _vp:
                            _ck = f"{_kk2}:{_vp}:{_iid2}"
                            _v["platform"] = _vp
                    if not self._is_sane_key(_ck):
                        _scrubbed += 1
                        continue
                    if _ck != _ks:
                        _migrated_seen = True
                    if _ck in self._seen_groups:
                        _prev = self._seen_groups[_ck]
                        if not _prev.get("group_name") and _v.get("group_name"):
                            _prev["group_name"] = _v["group_name"]
                        if not _prev.get("platform") and _v.get("platform"):
                            _prev["platform"] = _v["platform"]
                        _prev["last_seen"] = max(int(_prev.get("last_seen", 0) or 0), int(_v.get("last_seen", 0) or 0))
                        _prev["msg_count"] = int(_prev.get("msg_count", 0) or 0) + int(_v.get("msg_count", 0) or 0)
                        _migrated_seen = True
                    else:
                        self._seen_groups[_ck] = _v
        if _scrubbed or _migrated_seen:
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
        with self._save_lock:
            items = list(self._seen_groups.items())
            if len(items) > 500:
                items = sorted(
                    items,
                    key=lambda kv: kv[1].get("last_seen", 0),
                    reverse=True,
                )[:500]
                self._seen_groups = dict(items)
            payload = dict(self._seen_groups)
        self._save_json(self.seen_path, payload)
