"""节点包聚合。

``_`` 开头的模块（``__init__`` / ``_common``）不会被当作节点模块加载。
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from ..core import log

NODE_CLASS_MAPPINGS: dict[str, type] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}

_here = Path(__file__).parent


def load_nodes() -> None:
    """扫描本目录下的节点模块并合并映射表。"""
    for _, module_name, _ in pkgutil.iter_modules([str(_here)]):
        if module_name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f".{module_name}", package=__package__)
        except Exception as exc:  # 单节点失败不应阻断 ComfyUI 启动
            log.error(f"节点模块加载失败 {module_name}: {exc}")
            continue
        NODE_CLASS_MAPPINGS.update(getattr(module, "NODE_CLASS_MAPPINGS", {}))
        NODE_DISPLAY_NAME_MAPPINGS.update(getattr(module, "NODE_DISPLAY_NAME_MAPPINGS", {}))


load_nodes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
