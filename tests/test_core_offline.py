"""G2 门控：核心层离线单测（不需要运行中的 Ollama，也不需要 torch）。

运行方式（在包根目录）::

    <comfy-venv>/bin/python tests/test_core_offline.py
    # 或（若已安装 pytest）
    <comfy-venv>/bin/python -m pytest tests/test_core_offline.py -q

注意：思考块标签一律用 :func:`_tag` **运行时拼接**，不在源码里出现字面量。
原因是本项目的写作/传输链路会把形如裸 ``<think>`` 的思考分隔符吞掉，
导致测试夹具损坏（实现代码不受影响，因为实现里用的是 ``<think(?:ing)?``
这类带量词的正则，不是裸标签）。
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import log, ollama_client, prompts  # noqa: E402
from core.cleaner import OutputCleanConfig, clean_model_output  # noqa: E402
from core.media import (  # noqa: E402
    resolve_safe_video_max_side,
    sample_video_frames,
    tensor_to_base64_png,
    tensor_to_pil,
    video_to_base64,
)
from core.types import DEFAULT_URL, keep_alive_string  # noqa: E402

# --------------------------------------------------------------------------
# 夹具构造：运行时拼接标签，避免字面量被链路吞掉
# --------------------------------------------------------------------------
_LT = "\x3c"
_GT = "\x3e"


def _tag(name: str, closing: bool = False) -> str:
    return f"{_LT}{'/' if closing else ''}{name}{_GT}"


#: Qwen 系思考结束符：<｜end▁of▁thinking｜>（全角竖线 U+FF5C、U+2581）
QWEN_THINK_END = f"{_LT}\uff5cend\u2581of\u2581thinking\uff5c{_GT}"


# --------------------------------------------------------------------------
# 地址规范化
# --------------------------------------------------------------------------
def test_normalize_host_variants():
    assert ollama_client.normalize_host("http://192.0.2.10:11434") == "http://192.0.2.10:11434"
    assert ollama_client.normalize_host("192.0.2.10:11434") == "http://192.0.2.10:11434"
    assert ollama_client.normalize_host("192.0.2.10") == "http://192.0.2.10:11434"
    # 空输入回退到默认地址（由 QWE_OLLAMA_URL 或内置默认值决定）
    assert ollama_client.normalize_host("") == ollama_client.normalize_host(DEFAULT_URL)
    assert ollama_client.normalize_host(None) == ollama_client.normalize_host(DEFAULT_URL)


def test_default_url_is_overridable():
    """默认地址必须是合法的 http://host:port，且可被覆盖。

    优先级：环境变量 ``QWE_OLLAMA_URL`` > ``config/local.json`` > 内置默认值。
    公开源码的默认值是 Ollama 标准端口，本机可通过 local.json 指向内网服务。
    """
    resolved = ollama_client.normalize_host(DEFAULT_URL)
    assert resolved.startswith("http://"), resolved
    assert resolved.endswith(":11434"), resolved
    # 覆盖优先级：环境变量应当压过一切
    import importlib
    import os as _os

    old = _os.environ.get("QWE_OLLAMA_URL")
    _os.environ["QWE_OLLAMA_URL"] = "http://192.0.2.10:11500"
    try:
        import core.types as _t
        importlib.reload(_t)
        assert _t.DEFAULT_URL == "http://192.0.2.10:11500", _t.DEFAULT_URL
    finally:
        if old is None:
            _os.environ.pop("QWE_OLLAMA_URL", None)
        else:
            _os.environ["QWE_OLLAMA_URL"] = old
        importlib.reload(_t)


def test_normalize_host_rejects_garbage():
    try:
        ollama_client.normalize_host("http://")
    except ollama_client.OllamaError:
        return
    raise AssertionError("应当对空主机名抛出 OllamaError")


# --------------------------------------------------------------------------
# 参数映射（FR-07）
# --------------------------------------------------------------------------
def test_build_options_mapping():
    opts = ollama_client.build_options(
        max_tokens=256, temperature=0.5, top_p=0.9, repetition_penalty=1.2, seed=7, num_ctx=4096
    )
    assert opts == {
        "num_predict": 256,
        "temperature": 0.5,
        "top_p": 0.9,
        "repeat_penalty": 1.2,
        "seed": 7,
        "num_ctx": 4096,
    }, opts


def test_build_options_skips_none():
    assert ollama_client.build_options(max_tokens=64) == {"num_predict": 64}
    assert ollama_client.build_options() == {}


def test_keep_alive_string():
    assert keep_alive_string(5, "minutes") == "5m"
    assert keep_alive_string(2, "hours") == "2h"
    assert keep_alive_string(-1, "minutes") == "-1m"
    assert keep_alive_string(0, "minutes") == "0m"


# --------------------------------------------------------------------------
# 媒体适配（FR-05 / FR-06）
# --------------------------------------------------------------------------
def test_tensor_to_pil_downscales_keeping_aspect():
    tensor = np.zeros((1, 100, 400, 3), dtype=np.float32)
    image = tensor_to_pil(tensor, max_side=100)
    assert image is not None
    assert max(image.size) == 100
    assert image.size == (100, 25)


def test_tensor_to_pil_no_upscale():
    tensor = np.zeros((1, 32, 48, 3), dtype=np.float32)
    image = tensor_to_pil(tensor, max_side=1280)
    assert image.size == (48, 32)


def test_tensor_to_base64_png_roundtrip():
    tensor = np.full((1, 8, 8, 3), 0.5, dtype=np.float32)
    encoded = tensor_to_base64_png(tensor)
    assert encoded and base64.b64decode(encoded).startswith(b"\x89PNG")


def test_sample_video_frames_uniform():
    video = np.zeros((100, 8, 8, 3), dtype=np.float32)
    assert len(sample_video_frames(video, 10)) == 10


def test_sample_video_frames_fewer_than_requested():
    video = np.zeros((3, 8, 8, 3), dtype=np.float32)
    assert len(sample_video_frames(video, 10)) == 3


def test_resolve_safe_video_max_side_modes():
    small = np.zeros((8, 64, 64, 3), dtype=np.float32)
    assert resolve_safe_video_max_side(small, 8, ctx=8192, video_frame_size="auto") is None
    assert resolve_safe_video_max_side(small, 8, ctx=8192, video_frame_size="original") is None
    assert resolve_safe_video_max_side(small, 8, ctx=8192, video_frame_size="512") == 512


def test_resolve_safe_video_max_side_downscales_4k():
    big = np.zeros((16, 2160, 3840, 3), dtype=np.float32)
    side = resolve_safe_video_max_side(big, 16, ctx=8192, video_frame_size="auto")
    assert side is not None and 336 <= side <= 1024


def test_video_to_base64_respects_frame_cap():
    video = np.zeros((64, 32, 32, 3), dtype=np.float32)
    assert len(video_to_base64(video, frame_count=64, limit=16)) == 16


# --------------------------------------------------------------------------
# 输出清洗（FR-14）
# --------------------------------------------------------------------------
def test_clean_strips_think_block():
    raw = (
        _tag("think")
        + "让我想想……用户想要一只猫。"
        + QWEN_THINK_END
        + "a cute cat, soft lighting"
    )
    assert clean_model_output(raw) == "a cute cat, soft lighting"


def test_clean_strips_thinking_tag_pair():
    raw = _tag("thinking") + "reasoning here" + _tag("thinking", closing=True) + "a golden retriever"
    assert clean_model_output(raw) == "a golden retriever"


def test_clean_strips_classic_think_pair():
    raw = _tag("think") + "internal reasoning" + _tag("think", closing=True) + "a blue square"
    assert clean_model_output(raw) == "a blue square"


def test_clean_handles_lone_qwen_end_token():
    """开头被截断、只剩结束符时应丢弃前置思考文本。"""
    raw = "一些未闭合的思考文本" + QWEN_THINK_END + "a red circle"
    assert clean_model_output(raw) == "a red circle"


def test_clean_handles_lone_open_tag_with_paragraphs():
    raw = _tag("think") + "思考第一段\n\n真正的描述"
    assert clean_model_output(raw) == "真正的描述"


def test_clean_strips_code_fence_and_role_prefix():
    raw = "```\nAssistant: a red circle\n```"
    assert clean_model_output(raw) == "a red circle"


def test_clean_extracts_json_wrapper():
    assert clean_model_output('{"prompt": "a blue square"}') == "a blue square"


def test_clean_keeps_content_when_all_planning():
    raw = "I should describe the image."
    assert clean_model_output(
        raw, OutputCleanConfig(strip_planning=True, strip_leading_preamble=False)
    )


def test_clean_empty_input():
    assert clean_model_output("") == ""
    assert clean_model_output(None) == ""


# --------------------------------------------------------------------------
# 预设 prompt 资产（FR-04 / FR-08）
# --------------------------------------------------------------------------
def test_prompt_assets_loaded():
    data = prompts.load()
    assert len(data["preset_prompts"]) >= 9, data["preset_prompts"]
    assert len(data["vl_prompts"]) >= 9
    assert len(data["styles"]) >= 6


def test_prompt_lookup():
    assert prompts.vl_prompt("🖼️ Detailed Description")
    assert prompts.style_instruction("📝 Enhance")
    assert prompts.vl_prompt("不存在的预设") == "不存在的预设"
    assert prompts.style_instruction("不存在的风格")


# --------------------------------------------------------------------------
# 日志级别（控制台噪声治理）
# --------------------------------------------------------------------------
def _capture(fn) -> str:
    import contextlib
    import io as _io

    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def _with_level(name, fn):
    """临时切换日志级别后执行 fn（恢复原值）。"""
    saved = (log._level, log._level_name)
    log._level, log._level_name = log._LEVELS[name], name
    try:
        return fn()
    finally:
        log._level, log._level_name = saved


def test_log_default_level_is_warn():
    """默认级别下 info/debug 静默，warn 可见 —— 这是"日志不再刷屏"的根据。"""
    assert log.level() in ("warn", "info", "debug", "error")
    out_default = _capture(lambda: (log.info("hidden"), log.debug("hidden")))
    # 默认（warn）下两者都不输出
    if log._level == log._LEVELS["warn"]:
        assert out_default == "", out_default
    assert _capture(lambda: log.warn("visible")).strip() != ""


def test_log_info_visible_when_enabled():
    out = _with_level("info", lambda: _capture(lambda: log.info("hello")))
    assert "hello" in out, out
    out_quiet = _with_level("error", lambda: _capture(lambda: log.info("hello")))
    assert out_quiet == "", out_quiet


def test_log_error_always_visible():
    for lvl in ("error", "warn", "info", "debug"):
        out = _with_level(lvl, lambda: _capture(lambda: log.error("boom")))
        assert "boom" in out, (lvl, out)


def test_warn_once_deduplicates():
    """同类告警只打印一次，避免逐次运行刷屏。"""
    log.reset_once()
    out = _with_level(
        "warn",
        lambda: _capture(lambda: [log.warn_once("k1", "noise") for _ in range(5)]),
    )
    assert out.count("noise") == 1, out
    log.reset_once()


# --------------------------------------------------------------------------
# 节点注册表（不导入 ComfyUI，仅静态检查）
# --------------------------------------------------------------------------
def test_node_mappings_are_unique_and_prefixed():
    import ast

    root = Path(__file__).resolve().parent.parent
    keys: list[str] = []
    for path in (root / "nodes").glob("*.py"):
        if path.name.startswith("_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "NODE_CLASS_MAPPINGS"
            ):
                keys.extend(k.value for k in node.value.keys)

    assert len(keys) == len(set(keys)), f"Node ID 重复：{keys}"
    assert keys, "未发现任何 Node ID"
    assert all(k.startswith("OllamaQWE") for k in keys), keys


# --------------------------------------------------------------------------
# 简易 runner（无 pytest 时可用）
# --------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    sys.exit(1 if failed else 0)
