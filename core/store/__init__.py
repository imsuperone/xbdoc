"""xbdoc 存储层包。

对外只暴露 XbdocStoreMixin；具体能力按持久化 / 文档 / 会话 / 配置 / 检索拆到同包模块。
"""

from .common import CONFIG_DEFAULTS, CONFIG_META, PLUGIN_NAME
from .config import StoreConfigMixin
from .documents import StoreDocumentsMixin
from .persistence import StorePersistenceMixin
from .search import StoreSearchMixin
from .sessions import StoreSessionsMixin


class XbdocStoreMixin(
    StorePersistenceMixin,
    StoreDocumentsMixin,
    StoreSearchMixin,
    StoreSessionsMixin,
    StoreConfigMixin,
):
    """聚合存储能力；保持插件侧单继承 XbdocStoreMixin 的用法不变。"""


__all__ = [
    "CONFIG_DEFAULTS",
    "CONFIG_META",
    "PLUGIN_NAME",
    "XbdocStoreMixin",
]
