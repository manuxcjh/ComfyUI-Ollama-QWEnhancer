"""P3：``OllamaQWEConnect`` —— 共享 Ollama 连接。

把地址、模型与常驻时长封装成一个可复用的连接对象，
供 VL / 增强节点通过 ``conn`` 输入共享，避免每个节点重复填写。
"""

from __future__ import annotations

from ..core import ollama_client
from ..core import log
from ..core.types import CATEGORY, CONN, keep_alive_string
from ._common import KEEP_ALIVE_INPUTS, URL_INPUT, model_input


class OllamaQWEConnect:
    """Ollama 连接（地址 + 模型 + keep_alive）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "url": URL_INPUT,
                "model": model_input(vision_only=True),
                "vision_only": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "仅列出具备图像理解（vision）能力的模型。纯文本增强工作流可关闭。",
                    },
                ),
                **KEEP_ALIVE_INPUTS,
            }
        }

    RETURN_TYPES = (CONN,)
    RETURN_NAMES = ("conn",)
    FUNCTION = "connect"
    CATEGORY = CATEGORY
    DESCRIPTION = (
        "Ollama 连接设置。点击节点上的「🔄 刷新模型」从服务器拉取可用模型列表。"
        "输出可连接到 VL / Prompt 增强节点。"
    )

    def connect(self, url, model, vision_only, keep_alive, keep_alive_unit):
        # 连接节点只做展示与传递，不在此时强制校验：
        # 真正的存在性/vision 校验放在推理节点，避免工作流一加载就报错。
        conn = {
            "url": url,
            "model": model,
            "keep_alive": keep_alive_string(keep_alive, keep_alive_unit),
            "vision_only": bool(vision_only),
        }
        # 每次执行都会走到这里，默认级别下不打印，避免批量运行时刷屏
        log.info(
            f"连接目标 {ollama_client.normalize_host(url)} | "
            f"模型 {model} | keep_alive={conn['keep_alive']}"
        )
        return (conn,)


NODE_CLASS_MAPPINGS = {"OllamaQWEConnect": OllamaQWEConnect}
NODE_DISPLAY_NAME_MAPPINGS = {"OllamaQWEConnect": "Ollama QWE 连接 (QwenVL)"}

__all__ = ["OllamaQWEConnect", "NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
