"""插件配置：默认值叠加、WebUI 读写、切片参数变更后的缓存作废。"""

from typing import Any, Dict, Optional

from .common import CONFIG_DEFAULTS, CONFIG_META

class StoreConfigMixin:
    """插件配置：默认值叠加、WebUI 读写、切片参数变更后的缓存作废。"""

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
