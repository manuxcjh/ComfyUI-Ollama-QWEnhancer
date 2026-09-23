"""ComfyUI-Ollama-QWEnhancer

在 **Ollama** 后端上复现 `ComfyUI-QwenVL` 的推理侧能力：

* Qwen-VL 风格的图像 / 多帧视频理解（``OllamaQWEVL`` / ``OllamaQWEVLAdvanced``）
* 预设 prompt 体系与 Prompt 增强（``OllamaQWEEnhancer``）
* 可配置的 Ollama 服务器地址与动态模型列表（``OllamaQWEConnect``）

与上游的关系
------------
* 参考实现：``../ComfyUI-QwenVL``（GPL-3.0）与 ``../comfyui-ollama``（MIT）
* **不依赖**二者：Node ID（``OllamaQWE*``）、数据类型（``QWE_*``）、
  HTTP 路由（``/ollama_qwenhancer/*``）全部独立，可与之同装（NFR-03）
* 已按需求移除：本地 llama-server、HuggingFace 下载、GGUF/llama.cpp、
  量化、注意力后端、``torch.compile``、设备选择

运行期只需 ``ollama`` 客户端；``torch`` / ``numpy`` / ``Pillow`` / ``aiohttp``
由 ComfyUI 宿主提供。
"""

from __future__ import annotations

__version__ = "0.1.1"
__repo_name__ = "ComfyUI-Ollama-QWEnhancer"

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS  # noqa: E402
from .core import log  # noqa: E402

WEB_DIRECTORY = "./web"

# 注册独立的模型列表路由（P4）。失败只告警，不影响节点可用性。
try:
    from .server import register_routes

    register_routes()
except Exception as exc:  # pragma: no cover
    log.info(f"路由注册跳过：{exc}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

print(
    f"\033[36m[{__repo_name__}]\033[0m v\033[93m{__version__}\033[0m | "
    f"\033[37m{len(NODE_CLASS_MAPPINGS)} nodes\033[0m \033[92mLoaded\033[0m"
)
