"""跨 Mixin 共享的常量、配置元数据与锁装饰器。"""

from functools import wraps
from typing import Any, Dict

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
    "enable_private": True,
    "platform_preset": "onebot",
    "allowed_platforms": "onebot, aiocqhttp",
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
    "enable_private": {
        "description": "私聊独立开关",
        "hint": "开启后私聊支持文档注入与独立绑定；关闭后仅群聊生效。",
        "type": "bool",
    },
    "platform_preset": {
        "description": "生效平台快速选择",
        "hint": "下拉快速选择生效平台组合。若选择「自定义」，则由下方「允许生效的平台」自定义设置生效。默认仅 OneBot / QQ 平台。",
        "type": "string",
    },
    "allowed_platforms": {
        "description": "允许生效的平台（自定义/高级）",
        "hint": "当平台选择为「自定义」时生效。以逗号分隔允许生效的平台标识（如 onebot, matrix, telegram 等）。留空或填 all 表示允许所有平台。默认 onebot, aiocqhttp。",
        "type": "string",
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
