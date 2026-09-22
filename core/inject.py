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

    replace=True：清空原人格，text 作为唯一系统词（含 contexts/messages 内联改写）。
    replace=False： text 为空时不动；否则追加到现有系统词之后。
    """
    text = str(text or "")
    if replace:
        try:
            req.system_prompt = text
        except Exception:
            pass
        for attr in ("contexts", "messages"):
            ctx = getattr(req, attr, None)
            if isinstance(ctx, list):
                has_sys = False
                for m in ctx:
                    r = m.get("role") if isinstance(m, dict) else getattr(m, "role", "")
                    if r == "system":
                        if isinstance(m, dict):
                            m["content"] = text
                        else:
                            try:
                                setattr(m, "content", text)
                            except Exception:
                                pass
                        has_sys = True
                if not has_sys and text:
                    ctx.insert(0, {"role": "system", "content": text})
    else:
        if not text:
            return
        try:
            cur = str(getattr(req, "system_prompt", "") or "").strip()
            req.system_prompt = f"{cur}\n\n{text}".strip() if cur else text
        except Exception:
            pass


def truncate_text(body: str, max_chars: int, min_remain: int = 200) -> str:
    """截断公共逻辑：max_chars <= 0 不限制；总长（含标记）严格 ≤ max_chars；专属提示词永不经此截断。"""
    body = body or ""
    if max_chars <= 0:
        return body
    if len(body) <= max_chars:
        return body
    mark = "\n…(截断)"
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


def build_workspace_text(
    files: List[Tuple[str, str]], custom_prompt: str, max_chars: int
) -> str:
    """工作区模式：挂载头计入预算；正文空白折叠；max_chars <= 0 时全量挂载。"""
    sections: List[str] = []
    total = 0
    for fname, body in files:
        header = f"/workspace/{fname}:\n"
        body = fold_ws(body or "")
        # 头 + 正文一起占预算，避免轻量超 max_chars
        if max_chars <= 0 or total + len(header) + len(body) <= max_chars:
            sections.append(header + body)
            total += len(header) + len(body)
        else:
            remain = max(0, max_chars - total - len(header))
            if remain > 200:
                cut = truncate_text(body, remain)
                sections.append(header + cut)
                total += len(header) + len(cut)
    content = fold_ws("\n\n".join(sections))
    custom_prompt = (custom_prompt or "").strip()
    if custom_prompt:
        return f"{content}\n\n{custom_prompt}" if content else custom_prompt
    return content
