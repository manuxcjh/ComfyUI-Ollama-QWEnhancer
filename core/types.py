"""节点数据类型、分类与全局默认值（P2 契约）。

命名规范（docs/02-新软件包创建流程.md §1）：
所有类型名统一 ``QWE_`` 前缀，与 `comfyui-ollama` 的 ``OLLAMA_*`` 类型、
`ComfyUI-QwenVL` 的节点完全隔离，保证三者同装时无映射冲突（NFR-03）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# --------------------------------------------------------------------------
# 数据类型
# --------------------------------------------------------------------------
CONN = "QWE_OLLAMA_CONN"
"""连接对象：{"url": str, "model": str, "keep_alive": str}"""

# --------------------------------------------------------------------------
# 注册信息
# --------------------------------------------------------------------------
CATEGORY = "Ollama/QWEnhancer"
NODE_PREFIX = "OllamaQWE"

# --------------------------------------------------------------------------
# 默认值
# --------------------------------------------------------------------------
#: 本地覆盖配置文件（可选，**已 gitignore**）。
#: 把「本机专用」的地址/模型与源码分离，公开仓库里就不必出现内网信息。
LOCAL_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "local.json"


def _local_config() -> dict:
    """读取 ``config/local.json``；不存在或损坏时返回空 dict（静默降级）。"""
    if not LOCAL_CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


_LOCAL = _local_config()


def _resolve(env_key: str, local_key: str, fallback):
    """取值优先级：环境变量 > ``config/local.json`` > 内置默认值。"""
    value = os.environ.get(env_key)
    if value not in (None, ""):
        return value
    value = _LOCAL.get(local_key)
    if value not in (None, ""):
        return value
    return fallback


#: 默认 Ollama 地址。公开默认值是 Ollama 标准端口；可按需覆盖：
#: ``QWE_OLLAMA_URL=http://<host>:11434``，或写入 ``config/local.json``。
DEFAULT_URL = str(_resolve("QWE_OLLAMA_URL", "url", "http://127.0.0.1:11434"))

#: 模型下拉框的兜底值：服务器不可达时至少还有这一项可用。
DEFAULT_MODEL = str(_resolve("QWE_OLLAMA_MODEL", "model", "qwen2.5vl:7b"))

#: ``keep_alive`` 默认时长与单位。可按机器/模型固定偏好而无需改代码
#: （例如 ``QWE_KEEP_ALIVE=-1`` 让模型常驻显存不再重载）。
DEFAULT_KEEP_ALIVE = int(_resolve("QWE_KEEP_ALIVE", "keep_alive", 5))
DEFAULT_KEEP_ALIVE_UNIT = str(_resolve("QWE_KEEP_ALIVE_UNIT", "keep_alive_unit", "minutes"))
if DEFAULT_KEEP_ALIVE_UNIT not in ("minutes", "hours"):
    DEFAULT_KEEP_ALIVE_UNIT = "minutes"

KEEP_ALIVE_UNITS = ("minutes", "hours")
KEEP_ALIVE_SUFFIX = {"minutes": "m", "hours": "h"}

#: 图像送入 Ollama 前的长边上限（沿用上游 QwenVL 的 1280）
IMAGE_MAX_SIDE = 1280

#: 单次请求送入的最大图像数（含视频抽帧），防止 payload 失控（NFR-10）
MAX_IMAGES_PER_REQUEST = 16


def keep_alive_string(value: int, unit: str) -> str:
    """把 ``keep_alive`` 数值 + 单位转成 Ollama 接受的字符串。

    ``-1`` → ``"-1"``（永久常驻）；``0`` → ``"0"``（推理后立即卸载）。
    """
    suffix = KEEP_ALIVE_SUFFIX.get(str(unit), "m")
    return f"{int(value)}{suffix}"
