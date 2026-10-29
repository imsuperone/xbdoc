"""文档管理：入库、删除、列举，以及切片/词频/全文三级缓存。"""

import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from astrbot.api import logger

from ..retrieval import (
    ALLOWED_SUFFIXES,
    chunk_text,
    extract_text_from_bytes,
    tokenize,
)
from .common import PLUGIN_NAME

class StoreDocumentsMixin:
    """文档管理：入库、删除、列举，以及切片/词频/全文三级缓存。"""

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
            self._bm25_cache.clear()
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
            self._bm25_cache.clear()

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

    def _cache_put(self, cache: Dict[str, Any], doc_id: str, value: Any, cap: int) -> None:
        """LRU 回填（全缓存唯一实现）：超限驱逐最旧条目，写后复验防复活已删文档。"""
        with self._cache_lock:
            if len(cache) >= cap:
                cache.pop(next(iter(cache)), None)
            cache[doc_id] = value
            if doc_id not in self._index:  # 写后复验：文档已删则回滚，防删除后复活缓存
                cache.pop(doc_id, None)

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
        """缓存切片，防止文档过多时内存无限增长。"""
        self._cache_put(self._chunk_cache, doc_id, chunks, 200)

    def _get_chunk_counters(self, doc_id: str) -> List[Counter]:
        """获取每切片词频（缓存），避免每次提问重复分词全量切片。"""
        cached = self._cache_touch(self._chunk_tokens_cache, doc_id)
        if cached is not None:
            return cached
        chunks = self._load_chunks(doc_id)
        counters = [Counter(tokenize(ch)) for ch in chunks]
        self._cache_put(self._chunk_tokens_cache, doc_id, counters, 200)
        return counters

    def _get_full_text(self, doc_id: str) -> str:
        """获取文档全文（缓存）：system/workspace 模式每消息复用，入库/删除时失效。"""
        cached = self._cache_touch(self._fulltext_cache, doc_id)
        if cached is not None:
            return cached
        text = "\n".join(self._load_chunks(doc_id))
        self._cache_put(self._fulltext_cache, doc_id, text, 50)
        return text
