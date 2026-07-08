"""适配器注册：新增平台时在此 import 即完成注册。"""

from app.crawler.adapters.ccgp import CcgpAdapter
from app.crawler.adapters.generic import GenericAdapter
from app.crawler.adapters.generic_browser import GenericBrowserAdapter
from app.crawler.adapters.jsggzy import JsggzyAdapter

__all__ = ["CcgpAdapter", "GenericAdapter", "GenericBrowserAdapter", "JsggzyAdapter"]
