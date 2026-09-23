"""测试辅助：以 ComfyUI 的方式加载本包。

包目录名 ``ComfyUI-Ollama-QWEnhancer`` 含连字符，不能直接 ``import``。
ComfyUI 是通过 ``importlib`` + ``submodule_search_locations`` 加载的，
本模块复刻同一机制，并注册成一个合法模块名（``ollama_qwe``），
这样节点模块里的相对导入（``from ..core import ...``）才能正常解析。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent
PKG_NAME = "ollama_qwe"


def load_package():
    """加载并返回本包模块对象（幂等，可重复调用）。"""
    if PKG_NAME in sys.modules:
        return sys.modules[PKG_NAME]

    spec = importlib.util.spec_from_file_location(
        PKG_NAME,
        PKG_DIR / "__init__.py",
        submodule_search_locations=[str(PKG_DIR)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"无法为 {PKG_DIR} 构造 import spec")

    module = importlib.util.module_from_spec(spec)
    sys.modules[PKG_NAME] = module
    spec.loader.exec_module(module)
    return module
