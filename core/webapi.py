"""xbdoc WebAPI 层：管理台后端接口 + 群组拉取/合并。

被主插件多继承（Mixin），无 @filter 装饰方法。
"""

import time
from typing import Any, Dict, List

from astrbot.api import logger

try:
    from astrbot.api.web import (
        error_response,
        file_response,
        json_response,
        request,
    )
    _HAS_WEB_API = True
except Exception:
    _HAS_WEB_API = False

try:
    from .store import PLUGIN_NAME
except ImportError:
    from store import PLUGIN_NAME


# ======================================================================
# WebAPI Mixin
# ======================================================================

class XbdocWebAPIMixin:

    # ---------- WebUI 后端 API ----------
    def _register_web_apis(self) -> None:
        if not _HAS_WEB_API:
            return
        reg = self.context.register_web_api
        reg(f"/{PLUGIN_NAME}/docs", self._api_list_docs, ["GET"], "列出文档")
        reg(f"/{PLUGIN_NAME}/docs/upload", self._api_upload_doc, ["POST"], "上传文档")
        reg(f"/{PLUGIN_NAME}/docs/delete", self._api_delete_doc, ["POST"], "删除文档")
        reg(f"/{PLUGIN_NAME}/docs/content", self._api_doc_content, ["GET"], "预览文档")
        reg(f"/{PLUGIN_NAME}/docs/download", self._api_doc_download, ["GET"], "下载文档")
        reg(f"/{PLUGIN_NAME}/groups", self._api_list_groups, ["GET"], "列出已见群聊（只读搜索）")
        reg(f"/{PLUGIN_NAME}/groups/fetch", self._api_fetch_groups, ["POST"], "主动拉取机器人所在群")
        reg(f"/{PLUGIN_NAME}/bindings", self._api_list_bindings, ["GET"], "列出绑定")
        reg(f"/{PLUGIN_NAME}/bindings/save", self._api_save_binding, ["POST"], "保存绑定")
        reg(f"/{PLUGIN_NAME}/bindings/export", self._api_export_bindings, ["GET"], "导出绑定备份")
        reg(f"/{PLUGIN_NAME}/bindings/import", self._api_import_bindings, ["POST"], "导入绑定备份")
        reg(f"/{PLUGIN_NAME}/settings", self._api_get_settings, ["GET"], "读取插件设置")
        reg(f"/{PLUGIN_NAME}/settings/save", self._api_save_settings, ["POST"], "保存插件设置")

    async def _api_get_settings(self):
        return json_response({
            "config": self.get_plugin_config(),
            "meta": self.get_config_meta(),
        })

    async def _api_save_settings(self):
        payload = await request.json(default={})
        incoming = payload.get("config", payload) if isinstance(payload, dict) else None
        try:
            saved = self.save_plugin_config(incoming)
        except ValueError as e:
            return error_response(str(e), status_code=400)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 保存设置异常: {e}")
            return error_response(f"保存失败: {e}", status_code=500)
        return json_response({"ok": True, "config": saved, "meta": self.get_config_meta()})


    async def _api_list_docs(self):
        return json_response({"docs": self.list_documents()})


    async def _api_upload_doc(self):
        import asyncio
        import base64

        # 上传唯一链路：base64 JSON 直传（与 api.js 的 api.upload 一一对应，
        # iframe 桥接 apiPost / 直连 fetch 共用同一条 post 通道，不再保留 multipart/form 第二套）
        try:
            payload = await request.json(default={})
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            return error_response("请求格式错误", status_code=400)
        b64 = str(payload.get("file_base64") or "").strip()
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        if not b64:
            return error_response("缺少 file_base64", status_code=400)
        # base64 膨胀约 1/3：先卡字符串体积，避免超大包解码时吃爆内存（50MB 源文件约 68MB）
        if len(b64) > 70 * 1024 * 1024:
            return error_response("文件过大（解码后超出 50MB 上限）", status_code=400)
        try:
            data = base64.b64decode(b64)
        except Exception:
            return error_response("file_base64 解码失败", status_code=400)
        filename = str(payload.get("filename") or "unnamed").strip()
        if not data:
            return error_response("未读取到上传文件内容，请重试", status_code=400)

        try:
            # 入库含解码/切片等 CPU 与磁盘 IO，扔到插件专用线程池（启动已预热）避免阻塞事件循环
            meta = await asyncio.get_running_loop().run_in_executor(
                self._executor, self.add_document, filename, data
            )
            return json_response({"ok": True, "doc": meta})
        except RuntimeError as e:
            return error_response(str(e), status_code=400)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 上传入库异常: {e}")
            return error_response(f"入库失败: {e}", status_code=500)


    async def _api_delete_doc(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求格式错误", status_code=400)
        doc_id = str(payload.get("doc_id", "")).strip()
        if not doc_id:
            return error_response("缺少 doc_id", status_code=400)
        if not self.delete_document(doc_id):
            return error_response("文档不存在", status_code=404)
        return json_response({"ok": True})


    async def _api_doc_content(self):
        doc_id = request.query.get("doc_id", "", type=str)
        try:
            chunk = int(request.query.get("chunk", 1, type=int) or 1)
        except Exception:
            chunk = 1
        meta = self._index.get(doc_id)
        if not meta:
            return error_response("文档不存在", status_code=404)
        chunks = self._load_chunks(doc_id)
        n = max(1, min(int(chunk or 1), max(1, len(chunks))))
        preview = chunks[n - 1][:3000] if chunks else ""
        return json_response({"meta": meta, "chunk": n, "total": len(chunks), "preview": preview})


    async def _api_doc_download(self):
        doc_id = request.query.get("doc_id", "", type=str)
        meta = self._index.get(doc_id)
        if not meta:
            return error_response("文档不存在", status_code=404)
        path = self.docs_dir / str(meta.get("stored_name", ""))
        if not path.exists():
            return error_response("原文件丢失", status_code=404)
        return file_response(path, filename=str(meta.get("filename", "file")))


    def _binding_entry_view(self, key: str, ent: Dict[str, Any]) -> Dict[str, Any]:
        """绑定条目回包视图：GET /bindings 与 bindings/save 回包共用同一份构造（审计 #2）。

        字段只留前端在消费的（docs 带文件名：列表与载入编辑都用它）；seen 查找：
        完整键 -> 老格式键 -> 群裸 gid 键，逐级回落。
        """
        ids = ent.get("doc_ids", [])
        kind, _plat, ident = self._split_session_key(str(key))
        if not kind:
            kind, _plat, ident = "group", None, str(key).strip().split(":")[-1]
        gid = ident
        _seen = self._seen_groups.get(str(key)) or {}
        if not _seen:
            _seen = self._seen_groups.get(f"{kind}:{gid}") or {}
        if not _seen and kind == "group":
            _seen = self._seen_groups.get(gid) or {}
        gname = str(_seen.get("group_name") or "").strip()
        return {
            "gid": gid,
            "group_name": gname,
            "kind": kind,
            "docs": [{"doc_id": d, "filename": self._index.get(d, {}).get("filename", d)} for d in ids],
            "prompt": ent.get("prompt", ""),
            "shield": bool(ent.get("shield", False)),
            "force_system_prompt": bool(ent.get("force_system_prompt", False)),
            "mode": str(ent.get("mode") or "reference"),
        }


    async def _api_list_bindings(self):
        # 只读接口：用规范化副本展示，不回写（回写只发生在启动加载与保存入口，避免 GET/POST 竞态）
        _view = self._normalize_bindings(self._bindings)
        # 无人消费的字段已删：顶层 docs（list_documents 全量加锁排序）、条目 platform
        return json_response({
            "bindings": {k: self._binding_entry_view(k, ent) for k, ent in _view.items()},
        })


    async def _api_save_binding(self):
        payload = await request.json(default={})
        raw_key = str(payload.get("session_key", "")).strip()
        if not raw_key:
            return error_response("缺少 session_key（例如 group:123456）", status_code=400)
        ids = payload.get("doc_ids", [])
        if not isinstance(ids, list):
            return error_response("doc_ids 须为列表", status_code=400)

        ids = [str(i).strip() for i in ids if str(i).strip()]
        bad = [i for i in ids if i not in self._index]
        if bad:
            return error_response(f"文档不存在: {', '.join(bad)}", status_code=400)

        # mode 校验前移到任何内存改动之前：校验不过直接 400，绝不留下半提交状态
        fields: Dict[str, Any] = {}
        if "mode" in payload:
            new_mode = self._normalize_mode(payload.get("mode"))
            if not new_mode:
                return error_response("未知模式，可用：workspace / system / reference / none", status_code=400)
            fields["mode"] = new_mode
        if "prompt" in payload:
            fields["prompt"] = str(payload.get("prompt") or "").strip()
        if "shield" in payload:
            sh = payload.get("shield")
            fields["shield"] = bool(sh) if sh is not None else False
        if "force_system_prompt" in payload:
            fields["force_system_prompt"] = bool(payload.get("force_system_prompt"))
        if "ignore_history" in payload:
            # 断史开关是解绑语义的一部分：WebUI 解绑显式传 false 才能过 prune（与聊天解绑一致）
            fields["ignore_history"] = bool(payload.get("ignore_history"))

        # 写口在 store（锁内改内存 + 落盘一体）；回包在锁外拼
        key, ent, valid = self.save_binding_payload(raw_key, ids, fields)
        # save 响应即渲染（审计 #2）：回包带与 GET /bindings 同源的 entry 视图，
        # 前端直接更新本地映射，不再保存后整表重拉；空壳被 prune 时 entry 为 null（前端据此删键）
        resp = {
            "ok": True,
            "session_key": key,
            "doc_ids": valid,
            "ignore_history": bool(ent.get("ignore_history", False)),
            "entry": self._binding_entry_view(key, ent) if ent else None,
        }
        return json_response(resp)


    async def _api_export_bindings(self):
        """导出全部会话绑定：即 bindings 原样 map，前端存文件，回导时原样吃，无额外格式。"""
        return json_response(dict(self._bindings or {}))


    async def _api_import_bindings(self):
        """导入绑定备份：body 即导出的原样 map；?mode=merge（默认，合并）或 replace（整体覆盖）。"""
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("备份格式错误", status_code=400)
        mode = str(request.query.get("mode", "merge") or "merge").strip().lower()
        if mode not in ("merge", "replace"):
            return error_response("mode 须为 merge 或 replace", status_code=400)
        if len(payload) > 2000:
            return error_response("备份会话过多（>2000），请分批导入", status_code=400)
        # 校验在 Web 层，合并/回落/prune/落盘统一走 store 写口
        return json_response(self.import_bindings(payload, mode))


    def _find_all_bots(self) -> List[Any]:
        """定位平台适配器：优先走官方 platform_manager.platform_insts，其次事件缓存，最后有界泛遍历。"""
        try:  # 定位结果缓存 5 分钟：fallback 遍历较重，实例列表极少变化
            _cached = getattr(self, "_bots_cache", None) or {}
            if _cached.get("targets") and (time.time() - float(_cached.get("ts", 0))) < 300:
                return list(_cached["targets"])
        except Exception:
            pass
        targets: List[Any] = []
        added: set = set()

        def _add(obj) -> None:
            if obj is None or id(obj) in added:
                return
            if any(callable(getattr(obj, m, None)) for m in ("call_action", "call_api", "get_group_list")):
                added.add(id(obj))
                targets.append(obj)

        # 1. 官方通道：Context.platform_manager.platform_insts / get_insts()
        try:
            pm = getattr(self.context, "platform_manager", None)
            if pm is not None:
                insts = list(getattr(pm, "platform_insts", None) or [])
                if not insts:
                    try:
                        gi = getattr(pm, "get_insts", None)
                        if callable(gi):
                            insts = list(gi() or [])
                    except Exception:
                        pass
                for inst in insts:
                    _add(inst)
        except Exception:
            pass
        if targets:
            self._bots_cache = {"targets": list(targets), "ts": time.time()}
            return targets

        # 2. 消息事件里缓存的 bot（适配器实例）
        try:
            if getattr(self, "_latest_bot", None) is not None:
                _add(self._latest_bot)
        except Exception:
            pass
        if targets:
            self._bots_cache = {"targets": list(targets), "ts": time.time()}
            return targets

        # 3. 兜底：有界泛遍历（官方通道与事件缓存都 miss 才走；预算给足，宁可慢一次也不漏适配器）
        import inspect
        visited: set = set()
        budget = [800]

        def _traverse(obj, depth=0):
            if depth > 4 or obj is None or budget[0] <= 0:
                return
            oid = id(obj)
            if oid in visited:
                return
            visited.add(oid)
            budget[0] -= 1
            _add(obj)
            try:
                attrs = dir(obj)
            except Exception:
                return
            for attr in attrs:
                if attr.startswith("__"):
                    continue
                lower = attr.lower()
                if not any(k in lower for k in ("platform", "adapter", "bot", "client", "connection", "ws", "manager", "inst")):
                    continue
                try:
                    val = getattr(obj, attr, None)
                except Exception:
                    continue
                if val is None or callable(val) or inspect.isclass(val):
                    continue
                if isinstance(val, (list, tuple, set)):
                    for item in val:
                        _traverse(item, depth + 1)
                elif isinstance(val, dict):
                    for item in val.values():
                        _traverse(item, depth + 1)
                else:
                    _traverse(val, depth + 1)

        try:
            _traverse(self.context, 0)
        except Exception:
            pass
        self._bots_cache = {"targets": list(targets), "ts": time.time()}
        return targets


    async def _fetch_platform_groups(self):
        """主动向平台适配器拉取群组（多适配器并发、整体超时熔断）。

        返回 (groups, diag)：diag 记录适配器个数与每个动作的结果摘要，
        拉不到群时看日志/回包 debug 即可定位（0 适配器/超时/空返回/异常原文）。
        """
        import asyncio
        found_groups: Dict[str, Dict[str, Any]] = {}
        bots = self._find_all_bots()
        diag: List[str] = [f"adapters={len(bots)}"] + [
            f"bot[{i}]={type(b).__name__}" for i, b in enumerate(bots[:5])
        ]

        actions = ["get_group_list", "getGroupList", "get_groups", "list_groups", "get_joined_groups"]

        async def _call(cand, act):
            pname = str(getattr(cand, "platform_name", "") or getattr(cand, "name", "") or "?")
            try:
                if callable(getattr(cand, "call_action", None)):
                    r = await asyncio.wait_for(cand.call_action(act), timeout=5)
                elif callable(getattr(cand, "call_api", None)):
                    r = await asyncio.wait_for(cand.call_api(act), timeout=5)
                else:
                    fn = getattr(cand, act, None)
                    if not callable(fn):
                        return None
                    r = await asyncio.wait_for(fn(), timeout=5)
                n = -1
                if isinstance(r, dict):
                    d = r.get("data", r)
                    n = len(d) if isinstance(d, list) else -1
                elif isinstance(r, list):
                    n = len(r)
                diag.append(f"{pname}.{act}: ok(n={n})")
                return r
            except Exception as e:
                diag.append(f"{pname}.{act}: {type(e).__name__}: {str(e)[:120]}")
                return None

        async def _try_bot(cand):
            try:
                results = await asyncio.gather(*[_call(cand, act) for act in actions], return_exceptions=True)
            except Exception:
                results = []
            return (cand, results)

        # 全体并发 + 整体 18 秒熔断（超时自动取消子任务）；多适配器结果合并，不再首个成功即停
        per_bot: List[Any] = []
        try:
            per_bot = await asyncio.wait_for(
                asyncio.gather(*[_try_bot(b) for b in bots[:5]], return_exceptions=True),
                timeout=18,
            )
        except Exception:
            per_bot = []

        for item in per_bot:
            if not (isinstance(item, tuple) and len(item) == 2):
                continue
            cand, results = item
            if not isinstance(results, list):
                continue
            # 平台名同样走清洗：适配器对象上的 platform_name 可能是 partial 之类非字符串，
            # 直接 str() 会产生垃圾并污染 seen（历史教训），非法则回落 onebot
            try:
                p_name = self._clean_platform(
                    getattr(cand, "platform_name", "") or getattr(cand, "name", "")) or "onebot"
            except Exception:
                p_name = "onebot"
            for info in results:
                if not isinstance(info, (dict, list)):
                    continue
                data = (info.get("data") if isinstance(info, dict) else None) or info or []
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    for g in data:
                        if not isinstance(g, dict):
                            continue
                        gid = str(g.get("group_id") or g.get("gid") or g.get("id") or "").strip()
                        if not gid:
                            continue
                        gname = str(g.get("group_name") or g.get("name") or g.get("title") or "").strip()
                        try:
                            m_count = int(g.get("member_count") or g.get("members_count") or 0)
                        except Exception:
                            m_count = 0
                        # 平台+群号双键：跨平台同号群各自保留，不再互相覆盖
                        fkey = f"{p_name}:{gid}"
                        if fkey in found_groups:
                            continue
                        found_groups[fkey] = {
                            "gid": gid,
                            "group_name": gname,
                            "member_count": m_count,
                            "platform": p_name,
                            "last_seen": int(time.time()),
                            "msg_count": 0,
                        }

        now = int(time.time())
        for _fkey, item in found_groups.items():
            gid = str(item.get("gid") or "").strip()
            if not gid:
                continue
            seen_key = f"group:{item['platform']}:{gid}" if item.get("platform") else gid
            ent = self._seen_groups.setdefault(seen_key, {
                "gid": gid, "group_name": item["group_name"], "platform": item["platform"],
                "last_seen": now, "msg_count": 0,
            })
            if item["group_name"]:
                ent["group_name"] = item["group_name"]
            if item["platform"] and not ent.get("platform"):
                ent["platform"] = item["platform"]
            ent["last_seen"] = now

        if found_groups:
            self._save_seen()

        logger.info(f"[{PLUGIN_NAME}] 拉群诊断: " + "; ".join(diag[:25]))
        return list(found_groups.values()), {"bots": len(bots), "details": diag}


    def _get_all_merged_groups(self, q: str = "", limit: int = 60) -> List[Dict[str, Any]]:
        """seen + bindings 合并列表：字典键即 session_key（新老格式共存），bound 按完整 key 精确判定。"""
        merged: Dict[str, Dict[str, Any]] = {}

        for raw_key, meta in (self._seen_groups or {}).items():
            raw_key = str(raw_key).strip()
            if not raw_key or not isinstance(meta, dict):
                continue
            kind = str(meta.get("kind") or "").strip()
            if raw_key.startswith("private:") or kind == "private":
                _k, _p, uid = self._split_session_key(raw_key)
                uid = uid or (raw_key.split(":", 1)[1] if ":" in raw_key else raw_key)
                name = str(meta.get("group_name") or "").strip()
                merged[raw_key] = {
                    "gid": uid, "group_name": name,
                    "platform": str(meta.get("platform") or ""),
                    "msg_count": int(meta.get("msg_count") or 0),
                    "last_seen": int(meta.get("last_seen") or 0),
                    "bound": False, "kind": "private",
                    "session_key": raw_key,
                    "display": name or f"私聊 {uid}",
                }
                continue
            _k, _p, gid = self._split_session_key(raw_key)
            gid = gid or raw_key  # 老裸 gid 键
            sk = raw_key if _k == "group" else f"group:{gid}"
            merged[sk] = {
                "gid": gid, "group_name": str(meta.get("group_name") or ""),
                "platform": str(meta.get("platform") or ""),
                "msg_count": int(meta.get("msg_count") or 0),
                "last_seen": int(meta.get("last_seen") or 0),
                "bound": False, "kind": "group",
                "session_key": sk,
                "display": str(meta.get("group_name") or "").strip(),
            }

        bound_keys = {self._canonical_key_str(str(k)) for k in (self._bindings or {}).keys()}
        for k in list(bound_keys):
            if not k:
                continue
            if k in merged:
                merged[k]["bound"] = True
                continue
            # 无 seen 记录的绑定：空壳卡片（bound=True，保证配过的一定能选到）
            kind, _p, ident = self._split_session_key(k)
            if kind == "private":
                merged[k] = {
                    "gid": ident, "group_name": "", "platform": _p or "",
                    "msg_count": 0, "last_seen": 0, "bound": True,
                    "kind": "private", "session_key": k,
                    "display": f"私聊 {ident}",
                }
            else:
                gid = ident.split(":")[-1] if ident else k
                merged[k] = {
                    "gid": gid, "group_name": "", "platform": _p or "",
                    "msg_count": 0, "last_seen": 0, "bound": True,
                    "kind": "group", "session_key": k,
                    "display": "",
                }

        for g in merged.values():
            if not g.get("session_key"):
                g["session_key"] = f"group:{g['gid']}"
            if not g.get("display"):
                g["display"] = (g["group_name"] or "").strip()

        items = list(merged.values())
        if q:
            items = [g for g in items if q in g["gid"].lower() or q in g["group_name"].lower()
                     or q in g["platform"].lower() or q in str(g.get("display") or "").lower()]
        items.sort(key=lambda g: (not g["bound"], -g["last_seen"], -g["msg_count"], g["gid"]))
        return items[:limit]


    async def _api_fetch_groups(self):
        """主动拉取群（群列表的唯一刷新入口，前端只发这一枪）。"""
        try:
            fetched, diag = await self._fetch_platform_groups()
            return json_response({
                "ok": True,
                "new_fetched": len(fetched),
                "groups": self._get_all_merged_groups("", 200),
                "debug": diag,
            })
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] 主动拉取机器人群列表失败: {e}")
            # 失败原因已进 debug（fetch crashed + 类型/原文），无人消费的 count/warning 已删
            return json_response({
                "ok": True,
                "new_fetched": 0,
                "groups": self._get_all_merged_groups("", 200),
                "debug": {"bots": -1, "details": [f"fetch crashed: {type(e).__name__}: {e}"]},
            })


    async def _api_list_groups(self):
        """群列表只读搜索（刷新统一走 POST /groups/fetch，原 refresh 查询参数双路已删）。"""
        q = (request.query.get("q", "") or "").strip().lower()
        limit = max(1, min(request.query.get("limit", 60, type=int), 300))
        items = self._get_all_merged_groups(q, limit)
        return json_response({"groups": items})
