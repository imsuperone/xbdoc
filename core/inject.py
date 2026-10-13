"""xbdoc 注入构造器：系统提示词改写 + system/workspace 模式文本组装。

无 AstrBot 依赖（req 按鸭子类型操作），可独立测试。
"""

from typing import List, Tuple


def fold_ws(text: str) -> str:
    """无损压缩空白：去行尾空白、折叠连续空行（省 token，不改语义）。"""
    if not text:
        return text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    out: List[str] = []
    blank = 0
    for ln in lines:
        if ln == "":
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(ln)
    return "\n".join(out)


def apply_system_prompt(req, text: str, replace: bool) -> None:
    """改写 LLM 请求的系统提示词。

    replace=True：清空原人格，text 作为唯一系统词，并清理 contexts/messages 中残留的 system 消息以免触发 Gemini 499/上下文错误。
    replace=False：text 为空时不动；否则追加到现有系统词之后。
    """
    text = str(text or "")
    # 始终清理 contexts/messages 中非法的 role=="system" 项（AstrBot v4 由 req.system_prompt 独立承载系统词，
    # 若 contexts 中混入 role=="system" 会导致 Gemini 等模型报 400/499 上下文错误以及空对话显示“上下文 1 条”）
    for attr in ("contexts", "messages"):
        ctx = getattr(req, attr, None)
        if isinstance(ctx, list) and ctx:
            ctx[:] = [
                m for m in ctx
                if (m.get("role") if isinstance(m, dict) else getattr(m, "role", "")) != "system"
            ]
    if replace:
        try:
            req.system_prompt = text
        except Exception:
            pass
    else:
        if not text:
            return
        try:
            cur = str(getattr(req, "system_prompt", "") or "").strip()
            req.system_prompt = f"{cur}\n\n{text}".strip() if cur else text
        except Exception:
            pass



def truncate_text(body: str, max_chars: int, mark: str = "\n…(截断)") -> str:
    """截断公共逻辑：max_chars <= 0 不限制；总长（含标记）严格 ≤ max_chars；专属提示词永不经此截断。"""
    body = body or ""
    if max_chars <= 0:
        return body
    if len(body) <= max_chars:
        return body
    if max_chars <= len(mark):
        return body[:max_chars]
    return body[: max_chars - len(mark)] + mark


def build_system_text(doc_texts: List[str], custom_prompt: str, max_chars: int) -> str:
    """强制遵守模式：文档全文空白折叠 + 拼接截断 + 专属提示词（永不截断）。"""
    combined = truncate_text(
        fold_ws("\n\n".join(t for t in doc_texts if t)), max_chars
    )
    custom_prompt = (custom_prompt or "").strip()
    if not combined:
        return custom_prompt
    return f"{combined}\n\n{custom_prompt}" if custom_prompt else combined


SAFE_WORKSPACE_MAX_CHARS = 32000


def build_workspace_text(
    files: List[Tuple[str, str]], custom_prompt: str, max_chars: int
) -> str:
    """工作区模式：
    1. 始终生成【工作区文件清单】目录，保证模型获知全部挂载文件与体量（防小文件被遮蔽饿死）；
    2. 多文件公平预算：小文件优先完整挂载，大文件均分剩余预算并标明截断；
    3. max_chars <= 0 时施加 SAFE_WORKSPACE_MAX_CHARS (32k 字) 安全兜底，防 100k+ token 导致网关 504 超时。
    """
    if not files:
        custom_prompt = (custom_prompt or "").strip()
        return custom_prompt

    # 1. 始终生成文件清单（目录索引），无论内容多长模型均能获知完整文件全貌
    manifest_lines = [f"【工作区文件清单】（共 {len(files)} 个文件）："]
    for fname, body in files:
        manifest_lines.append(f"- /workspace/{fname} ({len(body or '')} 字符)")
    manifest_text = "\n".join(manifest_lines)

    # 2. 安全预算上限（扣除目录清单及段间换行间距，确保组装后严格 ≤ max_chars）
    effective_max = SAFE_WORKSPACE_MAX_CHARS if max_chars <= 0 else max_chars
    sep_overhead = 4 + max(0, len(files) - 1) * 2
    body_budget = max(0, effective_max - len(manifest_text) - sep_overhead)

    # 3. 预处理各文件
    prepared: List[Tuple[str, str, str, int]] = []
    for fname, body in files:
        h = f"/workspace/{fname}:\n"
        b = fold_ws(body or "")
        prepared.append((fname, h, b, len(h) + len(b)))

    total_needed = sum(p[3] for p in prepared)
    sections: List[str] = []

    if total_needed <= body_budget:
        for fname, h, b, _ in prepared:
            sections.append(h + b)
    else:
        # 多文件公平分配预算：给小文件全额，大文件均分剩余预算
        unallocated_budget = body_budget
        remaining_files = list(range(len(prepared)))
        allocations = [0] * len(prepared)

        changed = True
        while changed and remaining_files:
            changed = False
            avg = unallocated_budget // len(remaining_files)
            for idx in list(remaining_files):
                req = prepared[idx][3]
                if req <= avg:
                    allocations[idx] = req
                    unallocated_budget -= req
                    remaining_files.remove(idx)
                    changed = True

        if remaining_files:
            per_file = max(0, unallocated_budget // len(remaining_files))
            for idx in remaining_files:
                allocations[idx] = per_file

        for i, (fname, h, b, _) in enumerate(prepared):
            alloc = allocations[i]
            avail_body = max(0, alloc - len(h))
            if len(b) <= avail_body:
                sections.append(h + b)
            elif avail_body > 20:
                cut_mark = f"\n[.../workspace/{fname} 内容已截断，可通过文档工具检索或查看...]"
                cut = truncate_text(b, avail_body, mark=cut_mark)
                sections.append(h + cut)
            else:
                sections.append(h.rstrip())

    body_content = fold_ws("\n\n".join(s for s in sections if s))
    full_workspace = f"{manifest_text}\n\n{body_content}" if body_content else manifest_text
    if max_chars > 0 and len(full_workspace) > max_chars:
        full_workspace = truncate_text(full_workspace, max_chars)
    custom_prompt = (custom_prompt or "").strip()
    if custom_prompt:
        return f"{full_workspace}\n\n{custom_prompt}"
    return full_workspace

