"""媒体适配层（P2）——从 ``../ComfyUI-QwenVL/py/AILab_Utils.py`` 抽取。

保留（功能对等）：
  * :func:`tensor_to_pil`               —— ``IMAGE`` 张量 → PIL，支持长边降采样
  * :func:`tensor_to_base64_png`        —— 同上 + base64 编码
  * :func:`sample_video_frames`         —— 视频帧均匀采样
  * :func:`resolve_safe_video_max_side` —— 基于 token 预算的安全边长（上游算法原样）

丢弃（DR-07）：``resolve_hf_model_path`` / ``resolve_base_dir`` /
``find_local_gguf_file`` / ``get_comfyui_llm_paths`` 等本地模型路径逻辑。

设计约束
--------
* ``torch`` 只在函数内部惰性导入，保证本模块在**没有 torch** 的环境
  （例如纯 pytest）中也能被导入与测试。
* 本模块是全包唯一允许接触张量的位置；不得出现任何 CUDA 设备调用（NFR-02）。
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

import numpy as np

from .types import IMAGE_MAX_SIDE, MAX_IMAGES_PER_REQUEST
from . import log

__all__ = [
    "tensor_to_pil",
    "tensor_to_base64_png",
    "sample_video_frames",
    "resolve_safe_video_max_side",
    "images_to_base64",
    "video_to_base64",
]


def _pil():
    from PIL import Image

    return Image


def tensor_to_pil(tensor: Any, max_side: int | None = None):
    """``[C,H,W]`` / ``[1,H,W,C]`` / ``[H,W,C]`` 张量 → PIL Image（可选长边降采样）。

    与上游实现保持一致：数值按 0–1 浮点处理，乘以 255 后截断为 uint8。
    """
    if tensor is None:
        return None

    Image = _pil()

    if hasattr(tensor, "ndim") and not isinstance(tensor, np.ndarray):
        # torch.Tensor
        if tensor.ndim == 4:
            tensor = tensor[0]
        array = (tensor * 255).clamp(0, 255).to(_torch_uint8()).cpu().numpy()
    elif isinstance(tensor, np.ndarray):
        if tensor.ndim == 4:
            tensor = tensor[0]
        if tensor.dtype != np.uint8:
            array = np.clip(tensor * 255, 0, 255).astype(np.uint8)
        else:
            array = tensor
    else:
        return None

    if array.ndim != 3 or array.shape[-1] not in (1, 3, 4):
        return None

    image = Image.fromarray(array, mode="RGB")

    if max_side is not None and max_side > 0:
        width, height = image.size
        current = max(width, height)
        if current > max_side:
            scale = max_side / float(current)
            new_size = (
                max(int(round(width * scale)), 16),
                max(int(round(height * scale)), 16),
            )
            image = image.resize(new_size, Image.Resampling.BICUBIC)

    return image


def _torch_uint8():
    import torch

    return torch.uint8


def tensor_to_base64_png(tensor: Any, max_side: int | None = None) -> str | None:
    """张量 → base64 PNG 字符串（Ollama ``images`` 字段所需的格式）。"""
    image = tensor_to_pil(tensor, max_side=max_side)
    if image is None:
        return None
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def sample_video_frames(video: Any, frame_count: int) -> list:
    """从 ``[B,H,W,C]`` 视频张量中均匀采样 ``frame_count`` 帧（上游算法原样）。"""
    if video is None:
        return []
    if not hasattr(video, "shape") or video.ndim != 4:
        return [video]
    total = int(video.shape[0])
    frame_count = max(int(frame_count), 1)
    if total <= frame_count:
        return [video[i] for i in range(total)]
    indices = np.linspace(0, total - 1, frame_count, dtype=int)
    return [video[i] for i in indices]


def resolve_safe_video_max_side(
    video_tensor: Any,
    frame_count: int,
    ctx: int = 8192,
    video_frame_size: str = "auto",
) -> int | None:
    """按 token 预算计算视频帧的安全长边（上游算法原样）。

    ``auto`` 基于 ``ctx`` 与帧数估算每帧可用 token，再换算安全边长；
    尺寸已在预算内则返回 ``None``（保持原始分辨率）。
    """
    if video_tensor is None:
        return None

    mode = str(video_frame_size or "auto").strip().lower()
    if mode == "original":
        return None
    if mode.isdigit():
        return int(mode)

    ctx_val = max(int(ctx or 8192), 1024)
    f_count = max(int(frame_count or 1), 1)

    # 预留 1024 token 给 system prompt、用户 prompt 与生成
    text_reserve = 1024
    avail_tokens = max(ctx_val - text_reserve, 1024)
    budget_per_frame = avail_tokens / f_count

    # Qwen-VL: patch 14x14 经 2x2 merge → 28x28 = 784 像素/token
    # 安全系数 0.8 → 约 627 像素/token
    safe_pixels = budget_per_frame * 627
    safe_side = int(math.sqrt(safe_pixels))
    safe_side = max(min(safe_side, 1024), 336)

    shape = getattr(video_tensor, "shape", None)
    if shape is not None and len(shape) >= 3:
        if len(shape) == 4:
            orig_h, orig_w = int(shape[1]), int(shape[2])
        else:
            orig_h, orig_w = int(shape[0]), int(shape[1])
        if max(orig_h, orig_w) <= safe_side:
            return None

    return safe_side


def images_to_base64(
    images: Any,
    max_side: int | None = IMAGE_MAX_SIDE,
    limit: int = MAX_IMAGES_PER_REQUEST,
) -> list[str]:
    """把 ``IMAGE`` 批张量 ``[B,H,W,C]`` 转成 base64 列表（FR-05）。

    超过 ``limit`` 时截断并打印告警，避免 payload 过大（NFR-10）。
    """
    if images is None:
        return []

    if hasattr(images, "ndim") and images.ndim == 3:
        batch = [images]
    else:
        batch = [images[i] for i in range(int(images.shape[0]))]

    if len(batch) > limit:
        log.warn_once(
            f"image-limit:{limit}",
            f"输入图像 {len(batch)} 张，超过单次上限 {limit}，仅发送前 {limit} 张。",
        )
        batch = batch[:limit]

    out: list[str] = []
    for item in batch:
        encoded = tensor_to_base64_png(item, max_side=max_side)
        if encoded:
            out.append(encoded)
    return out


def video_to_base64(
    video: Any,
    frame_count: int = 8,
    ctx: int = 8192,
    video_frame_size: str = "auto",
    limit: int = MAX_IMAGES_PER_REQUEST,
) -> list[str]:
    """视频帧 → base64 图像列表（FR-06 的降级实现）。

    依据 Ollama 服务能力：**没有原生 video 输入**，因此按帧采样后
    作为多张图片送入（等价于图片批处理，无时序建模）。
    """
    if video is None:
        return []

    max_side = resolve_safe_video_max_side(
        video, frame_count=int(frame_count), ctx=int(ctx), video_frame_size=video_frame_size
    )
    frames = sample_video_frames(video, int(frame_count))
    if len(frames) > limit:
        log.warn_once(
            f"frame-limit:{limit}",
            f"采样帧数 {len(frames)} 超过单次上限 {limit}，仅发送前 {limit} 帧。",
        )
        frames = frames[:limit]

    out: list[str] = []
    for frame in frames:
        encoded = tensor_to_base64_png(frame, max_side=max_side)
        if encoded:
            out.append(encoded)
    return out
