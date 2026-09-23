"""节点层内部工具（非节点模块）。

文件名以 ``_`` 开头，因此不会被包级加载器当作节点模块扫描。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from ..core import ollama_client
from ..core.types import (
    DEFAULT_KEEP_ALIVE,
    DEFAULT_KEEP_ALIVE_UNIT,
    DEFAULT_MODEL,
    DEFAULT_URL,
    KEEP_ALIVE_UNITS,
    keep_alive_string,
)

__all__ = [
    "URL_INPUT",
    "model_input",
    "KEEP_ALIVE_INPUTS",
    "CONN_INPUT",
    "PROMPT_IN_INPUT",
    "ENABLED_INPUT",
    "model_choices",
    "resolve_target",
    "make_progress",
    "keep_alive_string",
]

# --------------------------------------------------------------------------
# 共用 widget 定义
# --------------------------------------------------------------------------
URL_INPUT = (
    "STRING",
    {
        "multiline": False,
        "default": DEFAULT_URL,
        "tooltip": "Ollama 服务地址。可写 http://127.0.0.1:11434，也可省略 http:// 直接写 127.0.0.1:11434。",
    },
)

_MODEL_TOOLTIP = (
    "选择 Ollama 模型。点下方「🔄 刷新模型」可重新从服务器拉取列表"
    "（VL 节点只列出具备 vision 能力的模型）。"
)

KEEP_ALIVE_INPUTS = {
    "keep_alive": (
        "INT",
        {
            "default": DEFAULT_KEEP_ALIVE,
            "min": -1,
            "max": 240,
            "step": 1,
            "tooltip": "模型在推理后于显存/内存中保留多久。-1 = 永久常驻，0 = 推理后立即卸载。",
        },
    ),
    "keep_alive_unit": (
        list(KEEP_ALIVE_UNITS),
        {"default": DEFAULT_KEEP_ALIVE_UNIT},
    ),
}

#: 可选文本输入。用 forceInput 使其成为**输入插槽**（而非 widget）——
#: 这既让 prompt 可由上游文本节点驱动，也让 ComfyUI 的 Bypass 有据可依：
#: 旁路时前端会为每个输出寻找类型匹配的输入（STRING→STRING）并直通。
PROMPT_IN_INPUT = (
    "STRING",
    {
        "forceInput": True,
        "tooltip": (
            "可选文本输入。接入后优先于本节点的 prompt 文本框。"
            "把本节点设为 Bypass 时，此输入会直通到文本输出（前端按类型匹配 STRING→STRING）。"
        ),
    },
)

#: 确定性直通开关。比 Bypass 更可靠：不依赖前端的类型匹配启发式。
ENABLED_INPUT = (
    "BOOLEAN",
    {
        "default": True,
        "tooltip": (
            "关闭后跳过模型推理，直接把提示文本原样送到输出。"
            "用于临时绕过 LLM：既能保持连线不变，也不受 Bypass 类型匹配限制。"
        ),
    },
)

CONN_INPUT = (
    "QWE_OLLAMA_CONN",
    {
        "forceInput": False,
        "tooltip": "可选：接入「Ollama QWE 连接」节点以共享地址与模型；接入后覆盖本节点上的 url/model。",
    },
)


# --------------------------------------------------------------------------
# 模型下拉框
# --------------------------------------------------------------------------
_choices_lock = threading.Lock()
_choices_cache: dict[tuple[str, bool], tuple[float, list[str]]] = {}
_CHOICES_TTL = 120.0


def model_choices(vision_only: bool, url: str = DEFAULT_URL) -> list[str]:
    """为 ``INPUT_TYPES`` 提供模型候选列表。

    策略：尝试向服务器查询（2 秒超时）→ 缓存 120 秒 → 失败则回退到
    ``[DEFAULT_MODEL]``。UI 侧的「🔄 刷新模型」按钮会覆盖此列表，
    因此这里失败不影响使用，只是初始候选较少。
    """
    key = (url, bool(vision_only))
    now = time.time()
    with _choices_lock:
        hit = _choices_cache.get(key)
        if hit and now - hit[0] < _CHOICES_TTL:
            return list(hit[1])

    names: list[str] = []
    try:
        entries = ollama_client.list_models(
            url, vision_only=vision_only, probe_vision=True, timeout=2.0
        )
        names = [e["name"] for e in entries]
    except Exception:
        names = []

    if not names:
        names = [DEFAULT_MODEL]

    with _choices_lock:
        _choices_cache[key] = (now, list(names))
    return names


def model_input(vision_only: bool = True):
    """构造 ``model`` widget 定义（候选列表来自服务器，失败则回退默认模型）。

    ``vision_only=True`` 时只列出具备 vision 能力的模型（FR-03）。
    注意：候选列表在 ``INPUT_TYPES()`` 调用时求值（带 120 秒缓存），
    因此最多只会在启动时探测一到两次网络；UI 侧的「🔄 刷新模型」可随时覆盖。
    """
    choices = model_choices(vision_only)
    default = DEFAULT_MODEL if DEFAULT_MODEL in choices else (choices[0] if choices else DEFAULT_MODEL)
    return (choices, {"default": default, "tooltip": _MODEL_TOOLTIP})


# --------------------------------------------------------------------------
# 连接解析
# --------------------------------------------------------------------------
def resolve_target(
    conn: Any,
    url: str,
    model: str,
    keep_alive: int = DEFAULT_KEEP_ALIVE,
    keep_alive_unit: str = "minutes",
) -> tuple[str, str, str]:
    """统一解析推理目标：``conn`` 输入优先于本节点的 widget。

    返回 ``(url, model, keep_alive 字符串)``。
    """
    if isinstance(conn, dict):
        url = conn.get("url") or url
        model = conn.get("model") or model
        if conn.get("keep_alive"):
            return url, model, str(conn["keep_alive"])

    return url, model, keep_alive_string(keep_alive, keep_alive_unit)


# --------------------------------------------------------------------------
# 进度上报
# --------------------------------------------------------------------------
class _NullProgress:
    def update(self, *_args, **_kwargs) -> None:  # pragma: no cover - 空实现
        pass


def make_progress(total: int):
    """返回 ComfyUI 进度条；不在 ComfyUI 中运行时返回空实现。"""
    try:
        from comfy.utils import ProgressBar

        return ProgressBar(total)
    except Exception:
        return _NullProgress()


def validate_model_or_raise(url: str, model: str, require_vision: bool) -> str:
    """执行期校验：模型存在（容错解析）+ 可选 vision 能力（FR-03 / NFR-04）。"""
    resolved = ollama_client.resolve_model(url, model)
    if require_vision:
        ollama_client.ensure_vision(url, resolved)
    return resolved
