"""P3：``OllamaQWEVL`` / ``OllamaQWEVLAdvanced`` —— Ollama 上的 QwenVL 推理。

功能对等基线：``../ComfyUI-QwenVL/py/AILab_QwenVL.py``（简易 ``:870``、高级 ``:908``）。

保留：预设 prompt / 自定义 prompt（非空则完全覆盖预设）/ system prompt、
图像与视频输入、``seed``、``temperature``、``top_p``、``repetition_penalty``、
``max_tokens``、``frame_count``、``video_frame_size``、输出清洗、进度条。

移除（DR-03~DR-06）：量化、注意力模式、``torch.compile``、设备选择、
``keep_model_loaded``（改由 ``keep_alive`` 表达）、``num_beams``（Ollama 无对应参数）。

视频说明：Ollama 无原生 video 输入，按 `docs/01-系统需求分析.md` 的 R1 与
用户确认，**降级为图片处理** —— 抽帧后作为多张图片送入，无时序建模。
"""

from __future__ import annotations

from ..core import log, ollama_client, prompts
from ..core.cleaner import OutputCleanConfig, clean_model_output
from ..core.media import images_to_base64, video_to_base64
from ..core.types import CATEGORY, IMAGE_MAX_SIDE, keep_alive_string
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

_VIDEO_FRAME_SIZES = ["auto", "384", "448", "512", "768", "original"]

_CLEAN_INPUT = (
    "BOOLEAN",
    {
        "default": True,
        "tooltip": "清洗模型输出：剥离  thinking 思考块、代码围栏、角色前缀与规划性文字，得到干净的描述文本。",
    },
)

_IMAGE_INPUT = ("IMAGE", {"tooltip": "输入图像（批）。参考图 / 待描述图。"})

_VIDEO_INPUT = (
    "IMAGE",
    {
        "tooltip": "输入视频帧序列。⚠️ Ollama 无原生视频输入，此处会按 frame_count 抽帧后"
        "当作多张图片发送（降级处理，无时序建模）。",
    },
)


def _build_prompt(preset_prompt: str, custom_prompt: str, prompt_in: str | None = None) -> str:
    """优先级：``prompt_in``（插槽）> ``custom_prompt``（文本框）> 预设。

    ``custom_prompt`` 覆盖预设是与上游一致的行为（AILab_QwenVL.py:833）。
    """
    if prompt_in and prompt_in.strip():
        return prompt_in.strip()
    if custom_prompt and custom_prompt.strip():
        return custom_prompt.strip()
    return prompts.vl_prompt(preset_prompt)


def _default_preset() -> str:
    """预设下拉框的默认项：优先 Detailed Description，否则取第一项。"""
    names = prompts.preset_prompt_names()
    preferred = "🖼️ Detailed Description"
    if preferred in names:
        return preferred
    return names[0] if names else preferred


def _collect_images(image, video, frame_count, video_frame_size, num_ctx) -> list[str]:
    """把 image/video 输入统一转成 base64 图像列表（FR-05 / FR-06）。"""
    encoded: list[str] = []
    if image is not None:
        encoded.extend(images_to_base64(image, max_side=IMAGE_MAX_SIDE))
    if video is not None:
        encoded.extend(
            video_to_base64(
                video,
                frame_count=frame_count,
                ctx=num_ctx,
                video_frame_size=video_frame_size,
            )
        )
    return encoded


def _clean(text: str, enabled: bool) -> str:
    if not enabled:
        return text.strip()
    return clean_model_output(text, OutputCleanConfig(mode="prompt"))


class _VLBase:
    """两个 VL 节点的公共实现。"""

    CATEGORY = CATEGORY

    @classmethod
    def _common_inputs(cls):
        return {
            "url": URL_INPUT,
            "model": model_input(vision_only=True),
            "preset_prompt": (
                prompts.preset_prompt_names(),
                {
                    "default": _default_preset(),
                    "tooltip": "内置的 Qwen-VL 指令模板，决定模型如何分析图像。",
                },
            ),
            "custom_prompt": (
                "STRING",
                {
                    "default": "",
                    "multiline": True,
                    "tooltip": "自定义指令。填写后**完全替换**上面的预设模板。",
                },
            ),
            "system_prompt": (
                "STRING",
                {
                    "default": "",
                    "multiline": True,
                    "tooltip": "可选的 system prompt，用于设定模型的角色与总体行为。留空则不发送。",
                },
            ),
            **KEEP_ALIVE_INPUTS,
        }

    def _infer(
        self,
        *,
        conn,
        url,
        model,
        preset_prompt,
        custom_prompt,
        system_prompt,
        image,
        video,
        frame_count,
        video_frame_size,
        max_tokens,
        seed,
        keep_alive,
        keep_alive_unit,
        clean_output,
        enabled=True,
        prompt_in=None,
        think=False,
        temperature=None,
        top_p=None,
        repetition_penalty=None,
        num_ctx=None,
    ):
        prompt_text = _build_prompt(preset_prompt, custom_prompt, prompt_in)

        # 直通：跳过推理，把提示文本原样送到 STRING 输出。
        # 不依赖前端 Bypass 的类型匹配，确定可用。
        if not enabled:
            log.info(f"VL 节点已禁用，直通输出 {prompt_text[:80]!r}")
            return prompt_text, None, 0

        url, model, keep_alive_str = resolve_target(
            conn, url, model, keep_alive, keep_alive_unit
        )
        model = validate_model_or_raise(url, model, require_vision=True)
        encoded = _collect_images(image, video, frame_count, video_frame_size, num_ctx or 8192)

        options = ollama_client.build_options(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            seed=seed,
            num_ctx=num_ctx,
        )

        progress = make_progress(3)
        progress.update(1)

        text, thinking = ollama_client.run(
            url=url,
            model=model,
            prompt=prompt_text,
            system=system_prompt.strip() or None,
            images=encoded,
            options=options,
            keep_alive=keep_alive_str,
            think=think,
        )
        progress.update(2)

        result = _clean(text, clean_output)
        progress.update(3)
        return result, thinking, len(encoded)


class OllamaQWEVL(_VLBase):
    """QwenVL on Ollama（基础）：预设/自定义 prompt + 图像/视频 + 种子。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **cls._common_inputs(),
                "max_tokens": ("INT", {"default": 512, "min": 16, "max": 8192, "step": 16}),
                "frame_count": (
                    "INT",
                    {"default": 8, "min": 1, "max": 16, "step": 1,
                     "tooltip": "视频输入时抽取的帧数。仅在接入 video 时生效。"},
                ),
                "video_frame_size": (
                    _VIDEO_FRAME_SIZES,
                    {"default": "auto",
                     "tooltip": "视频帧长边上限。auto 会按 token 预算自动降采样，original 保持原分辨率。"},
                ),
                "seed": ("INT", {"default": 1, "min": 1, "max": 2**32 - 1}),
                "clean_output": _CLEAN_INPUT,
                "enabled": ENABLED_INPUT,
            },
            "optional": {
                "conn": CONN_INPUT,
                "image": _IMAGE_INPUT,
                "video": _VIDEO_INPUT,
                "prompt_in": PROMPT_IN_INPUT,
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("RESPONSE",)
    FUNCTION = "process"
    DESCRIPTION = "用 Ollama 上的多模态模型分析图像/视频，支持预设与自定义 prompt。"

    def process(
        self, url, model, preset_prompt, custom_prompt, system_prompt,
        keep_alive, keep_alive_unit, max_tokens, frame_count, video_frame_size,
        seed, clean_output, enabled=True, conn=None, image=None, video=None,
        prompt_in=None,
    ):
        result, _thinking, _n = self._infer(
            conn=conn, url=url, model=model, preset_prompt=preset_prompt,
            custom_prompt=custom_prompt, system_prompt=system_prompt,
            image=image, video=video, frame_count=frame_count,
            video_frame_size=video_frame_size, max_tokens=max_tokens, seed=seed,
            keep_alive=keep_alive, keep_alive_unit=keep_alive_unit,
            clean_output=clean_output, enabled=enabled, prompt_in=prompt_in,
        )
        return (result,)


class OllamaQWEVLAdvanced(_VLBase):
    """QwenVL on Ollama（高级）：额外暴露采样参数、think 与 json 输出。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **cls._common_inputs(),
                "max_tokens": ("INT", {"default": 512, "min": 16, "max": 8192, "step": 16}),
                "temperature": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 2.0, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.05}),
                "repetition_penalty": (
                    "FLOAT",
                    {"default": 1.1, "min": 0.5, "max": 2.0, "step": 0.05,
                     "tooltip": "映射到 Ollama 的 repeat_penalty。"},
                ),
                "num_ctx": (
                    "INT",
                    {"default": 8192, "min": 1024, "max": 131072, "step": 1024,
                     "tooltip": "上下文窗口。也用于视频帧的 token 预算估算。"},
                ),
                "frame_count": (
                    "INT",
                    {"default": 8, "min": 1, "max": 16, "step": 1},
                ),
                "video_frame_size": (_VIDEO_FRAME_SIZES, {"default": "auto"}),
                "seed": ("INT", {"default": 1, "min": 1, "max": 2**32 - 1}),
                "think": (
                    "BOOLEAN",
                    {"default": False,
                     "tooltip": "启用思考过程。仅对支持 thinking 的模型有效，思考文本从第二个输出端口返回。"},
                ),
                "clean_output": _CLEAN_INPUT,
                "enabled": ENABLED_INPUT,
            },
            "optional": {
                "conn": CONN_INPUT,
                "image": _IMAGE_INPUT,
                "video": _VIDEO_INPUT,
                "prompt_in": PROMPT_IN_INPUT,
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("RESPONSE", "THINKING")
    FUNCTION = "process"
    DESCRIPTION = "用 Ollama 上的多模态模型分析图像/视频，暴露完整采样参数与思考输出。"

    def process(
        self, url, model, preset_prompt, custom_prompt, system_prompt,
        keep_alive, keep_alive_unit, max_tokens, temperature, top_p,
        repetition_penalty, num_ctx, frame_count, video_frame_size, seed,
        think, clean_output, enabled=True, conn=None, image=None, video=None,
        prompt_in=None,
    ):
        result, thinking, _n = self._infer(
            conn=conn, url=url, model=model, preset_prompt=preset_prompt,
            custom_prompt=custom_prompt, system_prompt=system_prompt,
            image=image, video=video, frame_count=frame_count,
            video_frame_size=video_frame_size, max_tokens=max_tokens, seed=seed,
            keep_alive=keep_alive, keep_alive_unit=keep_alive_unit,
            clean_output=clean_output, enabled=enabled, prompt_in=prompt_in,
            think=think, temperature=temperature,
            top_p=top_p, repetition_penalty=repetition_penalty, num_ctx=num_ctx,
        )
        return (result, _clean(thinking or "", clean_output))


NODE_CLASS_MAPPINGS = {
    "OllamaQWEVL": OllamaQWEVL,
    "OllamaQWEVLAdvanced": OllamaQWEVLAdvanced,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "OllamaQWEVL": "Ollama QwenVL",
    "OllamaQWEVLAdvanced": "Ollama QwenVL (Advanced)",
}

__all__ = ["OllamaQWEVL", "OllamaQWEVLAdvanced", "NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
