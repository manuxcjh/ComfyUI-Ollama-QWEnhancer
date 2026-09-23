"""P3：``OllamaQWEEnhancer`` —— Prompt 增强（纯文本，走 Ollama）。

功能对等基线：``../ComfyUI-QwenVL/py/AILab_QwenVL_PromptEnhancer.py``。

保留：6 种增强风格（``qwen_text.styles``）、自定义 system prompt、
「风格指令 + 用户文本」的拼接语义（上游为 ``f"{base_instruction}\\n\\n{user_prompt}"``）。
移除：本地文本模型加载与 ``_load_text_model``（DR-03~DR-06）。
"""

from __future__ import annotations

from ..core import log, ollama_client, prompts
from ..core.cleaner import OutputCleanConfig, clean_model_output
from ..core.types import CATEGORY
from ._common import (
    CONN_INPUT,
    ENABLED_INPUT,
    KEEP_ALIVE_INPUTS,
    PROMPT_IN_INPUT,
    URL_INPUT,
    make_progress,
    model_input,
    resolve_target,
    validate_model_or_raise,
)

_DEFAULT_USER_TEXT = "Describe a scene vividly."


class OllamaQWEEnhancer:
    """用 Ollama 模型扩写 / 润色 prompt。"""

    @classmethod
    def INPUT_TYPES(cls):
        styles = prompts.style_names()
        preferred = "📝 Enhance"
        default_style = preferred if preferred in styles else (styles[0] if styles else preferred)
        return {
            "required": {
                "url": URL_INPUT,
                "model": model_input(vision_only=False),
                "prompt_text": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "要增强的 prompt 文本。留空时使用一句默认占位文本。",
                    },
                ),
                "enhancement_style": (
                    styles,
                    {"default": default_style, "tooltip": "内置的增强风格，决定扩写方向。"},
                ),
                "custom_system_prompt": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "自定义风格指令。填写后覆盖上面选择的增强风格。",
                    },
                ),
                "max_tokens": ("INT", {"default": 4096, "min": 256, "max": 16384, "step": 256}),
                "temperature": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 2.0, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.05}),
                "seed": ("INT", {"default": 1, "min": 1, "max": 2**32 - 1}),
                "keep_alive": KEEP_ALIVE_INPUTS["keep_alive"],
                "keep_alive_unit": KEEP_ALIVE_INPUTS["keep_alive_unit"],
                "clean_output": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "清洗输出：剥离思考块、代码围栏、角色前缀与规划性文字。",
                    },
                ),
                "think": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "启用思考过程（仅对思考型模型有效）。"},
                ),
                "enabled": ENABLED_INPUT,
            },
            "optional": {"conn": CONN_INPUT, "prompt_in": PROMPT_IN_INPUT},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("ENHANCED_OUTPUT",)
    FUNCTION = "process"
    CATEGORY = CATEGORY
    DESCRIPTION = "用 Ollama 模型把简短 prompt 扩写/润色成更丰富的描述。"

    def process(
        self, url, model, prompt_text, enhancement_style, custom_system_prompt,
        max_tokens, temperature, top_p, seed, keep_alive, keep_alive_unit,
        clean_output, think, enabled=True, conn=None, prompt_in=None,
    ):
        # prompt_in（插槽）优先于 prompt_text（文本框）
        user_prompt = (prompt_in or "").strip() or (prompt_text or "").strip() or _DEFAULT_USER_TEXT

        # 直通：跳过推理，原样输出提示文本。
        # 这条路径不依赖前端 Bypass 的类型匹配，是确定性的"禁用即直通"。
        if not enabled:
            log.info(f"enhancer 已禁用，直通输出 {user_prompt[:80]!r}")
            return (user_prompt,)

        url, model, keep_alive_str = resolve_target(
            conn, url, model, keep_alive, keep_alive_unit
        )
        # 增强是纯文本任务，不要求模型具备 vision 能力
        model = validate_model_or_raise(url, model, require_vision=False)

        # 与上游一致：自定义 system prompt 优先于预设风格
        base_instruction = (
            custom_system_prompt.strip() or prompts.style_instruction(enhancement_style)
        )

        progress = make_progress(3)
        progress.update(1)

        text, _thinking = ollama_client.run(
            url=url,
            model=model,
            prompt=user_prompt,
            system=base_instruction or None,
            options=ollama_client.build_options(
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                seed=seed,
            ),
            keep_alive=keep_alive_str,
            think=think,
        )
        progress.update(2)

        result = text.strip()
        if clean_output:
            result = clean_model_output(result, OutputCleanConfig(mode="prompt"))

        progress.update(3)
        return (result,)


NODE_CLASS_MAPPINGS = {"OllamaQWEEnhancer": OllamaQWEEnhancer}
NODE_DISPLAY_NAME_MAPPINGS = {"OllamaQWEEnhancer": "Ollama QwenVL Prompt 增强"}

__all__ = ["OllamaQWEEnhancer", "NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
