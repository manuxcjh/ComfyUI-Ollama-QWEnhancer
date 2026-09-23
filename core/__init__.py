"""核心层：Ollama 客户端封装、媒体适配、prompt 装载、输出清洗（P2）。

导入本包**不会**触发 torch 导入或任何网络请求，因此可以脱离 ComfyUI
在普通 Python 环境（含 pytest）中导入与测试（NFR-08）。
"""

from __future__ import annotations

from . import cleaner, media, ollama_client, prompts, types

__all__ = ["cleaner", "media", "ollama_client", "prompts", "types"]
