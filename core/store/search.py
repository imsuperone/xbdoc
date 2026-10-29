"""检索编排：BM25 全局量缓存、绑定文档切片召回、注入文本拼装。

计分/分词/切片等纯函数在 core/retrieval.py；本模块只做「带状态的检索服务」。
"""

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..inject import fold_ws, truncate_text
from ..retrieval import score_chunk_bm25, tokenize

# BM25 全局量缓存槽数：按「绑定集合 + 各文档切片数」做多槽缓存，
# 多会话交替提问不互相驱逐
_BM25_CACHE_SLOTS = 8


class StoreSearchMixin:
    """检索编排：retrieve 唯一实现，聊天 search / LLM 工具 / 注入共用。"""

    def _bm25_globals(self, doc_ids: List[str]) -> Dict[str, Any]:
        """绑定文档全量切片上的 BM25 全局量（N/avg_len/idf），按绑定集合多槽缓存。"""
        key = tuple((d, int(self._index[d].get("chunks", 0))) for d in sorted(set(doc_ids)) if d in self._index)
        hit = self._bm25_cache.get(key)
        if hit is not None:
            self._bm25_cache[key] = self._bm25_cache.pop(key)  # LRU：命中移到队尾
            return hit
        counters: List[Counter] = []
        for d, _ in key:
            counters.extend(self._get_chunk_counters(d))
        n = len(counters)
        avg_len = sum(sum(c.values()) for c in counters) / n if n else 0.0
        df: Counter = Counter()
        for c in counters:
            for t in c.keys():
                df[t] += 1
        hit = {
            "n": n, "avg": avg_len,
            "idf": {t: math.log((n - f + 0.5) / (f + 0.5) + 1.0) for t, f in df.items()},
        }
        if len(self._bm25_cache) >= _BM25_CACHE_SLOTS:
            self._bm25_cache.pop(next(iter(self._bm25_cache)))
        self._bm25_cache[key] = hit
        return hit

    def retrieve(self, query: str, doc_ids: List[str], top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """在绑定文档中检索与 query 相关的切片，按相关度降序返回 top_k 条。"""
        top_k = top_k or self._cfg_int("top_k")
        clean_q = re.sub(r"@\S+", "", query or "").strip()
        qtokens = tokenize(clean_q)
        if not doc_ids:
            return []

        _g = self._bm25_globals(doc_ids)
        _avg_len, _idf = _g["avg"], _g["idf"]
        q_lower = clean_q.lower()

        scored: List[Dict[str, Any]] = []
        for did in doc_ids:
            meta = self._index.get(did)
            if not meta:
                continue
            fname = str(meta.get("filename", "")).lower()
            fstem = Path(fname).stem.lower()
            # 短文件名（如单字/数字）用 in 判断必误伤全量切片，需设长度门限
            fname_hit = bool(
                (len(fstem) >= 2 and fstem in q_lower)
                or (len(fname) >= 4 and fname in q_lower)
            )

            chunks = self._load_chunks(did)
            counters = self._get_chunk_counters(did)
            lengths = [sum(c.values()) for c in counters]
            for idx, ch in enumerate(chunks):
                tf = counters[idx] if idx < len(counters) else Counter()
                doc_len = lengths[idx] if idx < len(lengths) else 0
                s = score_chunk_bm25(qtokens, tf, doc_len, _avg_len, _idf) if qtokens else 0.0
                if fname_hit and (idx == 0 or s > 0):
                    # 文件名命中对首片（文档概览/标题）或已有关键词命中的切片做加权，
                    # 避免完全无关的切片被全量塞入导致挤占精准内容
                    s += 3.0
                if s > 0:
                    scored.append({
                        "doc_id": did, "filename": meta.get("filename", did),
                        "chunk_idx": idx, "text": ch, "score": s,
                    })

        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:max(1, top_k)]

        # 保底策略：未命中具体切片关键词但确有绑定文档时，保底载入首切片，确保模型拥有文档认知
        # （fallback_inject 可在 WebUI 关闭）
        if not results and doc_ids and bool(self._cfg("fallback_inject")):
            for did in doc_ids[:2]:
                chunks = self._load_chunks(did)
                if chunks:
                    meta = self._index.get(did, {})
                    results.append({
                        "doc_id": did, "filename": meta.get("filename", did),
                        "chunk_idx": 0, "text": chunks[0], "score": 0.5,
                    })

        return results

    def build_inject_text(self, query: str, doc_ids: List[str]) -> str:
        """参考资料模式注入文本：检索 → 拼接 → 统一截断（省 token）。"""
        max_chars = self._cfg_no_limit("max_inject_chars")
        hits = self.retrieve(query, doc_ids)
        if not hits:
            return ""
        body = fold_ws(
            "\n\n".join(
                f"{h['filename']} (片段{h['chunk_idx']+1}):\n{h['text']}" for h in hits
            )
        )
        return truncate_text(body, max_chars)
