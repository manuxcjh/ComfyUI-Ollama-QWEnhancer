"""预设 prompt 装载（P2）。

数据源：``config/system_prompts.json``（自 ``../ComfyUI-QwenVL/system_prompts.json``
原样复制，GPL-3.0）。结构：

* ``_preset_prompts``  —— 节点下拉框的预设名列表
* ``qwenvl``           —— VL 预设名 → 指令正文（9 条）
* ``qwen_text.styles`` —— Prompt 增强风格（6 种）
* ``qwen_text.translation_prompt``

与代码解耦：用户可直接编辑 JSON 增改预设，无需改 Python（NFR-09）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from . import log

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "system_prompts.json"

#: JSON 缺失或损坏时的兜底，保证节点永远可用
_FALLBACK_STYLES = {
    "📝 Enhance": "Expand and enrich this prompt with vivid visual context:",
    "📝 Refine": "Polish this prompt for clarity and precise AI interpretation:",
    "📝 Creative Rewrite": "Rewrite this prompt imaginatively while preserving intent:",
    "📝 Detailed Visual": "Turn this prompt into a highly detailed visual description:",
    "📝 Artistic Style": "Describe this prompt in artistic language suitable for image generation:",
    "📝 Technical Specs": "Convert this prompt into clear technical parameters:",
}
_FALLBACK_VL = {"🖼️ Detailed Description": "Describe this image in detail."}
_FALLBACK_PRESETS = ["🖼️ Detailed Description"]

_cached: dict[str, Any] | None = None


def load() -> dict[str, Any]:
    """读取并缓存配置；失败时返回兜底结构（不抛异常，避免阻断节点注册）。"""
    global _cached
    if _cached is not None:
        return _cached

    data: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            log.error(f"预设 prompt 读取失败（{CONFIG_PATH}）：{exc}")

    preset_prompts = data.get("_preset_prompts") or _FALLBACK_PRESETS
    vl_prompts = data.get("qwenvl") or _FALLBACK_VL
    qwen_text = data.get("qwen_text") or {}
    styles_raw = qwen_text.get("styles") or _FALLBACK_STYLES

    styles = {
        str(name): (entry.get("system_prompt", "") if isinstance(entry, dict) else str(entry))
        for name, entry in styles_raw.items()
    }
    if not styles:
        styles = dict(_FALLBACK_STYLES)

    _cached = {
        "preset_prompts": [str(p) for p in preset_prompts],
        "vl_prompts": {str(k): str(v) for k, v in vl_prompts.items()},
        "styles": styles,
        "translation_prompt": str(qwen_text.get("translation_prompt") or ""),
    }
    return _cached


def preset_prompt_names() -> list[str]:
    """VL 节点下拉框的预设名列表（来自 ``_preset_prompts``）。"""
    return list(load()["preset_prompts"])


def style_names() -> list[str]:
    """增强节点的风格名列表（来自 ``qwen_text.styles``）。"""
    return list(load()["styles"].keys())


def vl_prompt(name: str) -> str:
    """取 VL 预设的指令正文；未知名称时原样返回。"""
    prompts = load()["vl_prompts"]
    return prompts.get(name, name)


def style_instruction(name: str) -> str:
    """取增强风格的指令正文；未知名称时回退到第一条。"""
    styles = load()["styles"]
    if name in styles:
        return styles[name]
    return next(iter(styles.values()), "")


def translation_prompt() -> str:
    return load()["translation_prompt"]
