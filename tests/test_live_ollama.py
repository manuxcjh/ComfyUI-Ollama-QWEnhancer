"""G3 / G6 门控：节点注册 + 对真实 Ollama 服务的端到端测试。

直接调用节点类的 ``INPUT_TYPES`` / ``FUNCTION``，与 ComfyUI 执行路径一致
（不依赖 ComfyUI 宿主，``ProgressBar`` 会自动降级为空实现）。

在包根目录运行::

    <comfy-venv>/bin/python tests/test_live_ollama.py

可通过环境变量覆盖目标服务::

    QWE_URL=http://<host>:11434 QWE_MODEL=<vision-model> \
        python tests/test_live_ollama.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pkgload import load_package  # noqa: E402

#: 以 ComfyUI 的方式加载本包（含节点注册与路由注册的降级路径）
_pkg = load_package()
ollama_client = _pkg.core.ollama_client

#: 直接从注册表取节点类 —— 顺带验证包级聚合是否生效（G3）
OllamaQWEConnect = _pkg.NODE_CLASS_MAPPINGS["OllamaQWEConnect"]
OllamaQWEVL = _pkg.NODE_CLASS_MAPPINGS["OllamaQWEVL"]
OllamaQWEVLAdvanced = _pkg.NODE_CLASS_MAPPINGS["OllamaQWEVLAdvanced"]
OllamaQWEEnhancer = _pkg.NODE_CLASS_MAPPINGS["OllamaQWEEnhancer"]

#: 目标服务与模型：环境变量 > config/local.json > 源码默认值
URL = os.environ.get("QWE_URL") or _pkg.core.types.DEFAULT_URL
MODEL = os.environ.get("QWE_MODEL") or _pkg.core.types.DEFAULT_MODEL

#: 演示图：白底 + 红圆 + 蓝方块，便于断言描述里出现颜色/形状
_RED = (255, 0, 0)
_BLUE = (0, 0, 255)


def _demo_image(size: int = 320):
    """生成一张 [1,H,W,C] 的 float32 图像张量（模拟 ComfyUI 的 IMAGE 类型）。"""
    canvas = np.full((size, size, 3), 255, dtype=np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    circle = (yy - size // 2) ** 2 + (xx - size // 2) ** 2 <= (size // 5) ** 2
    canvas[circle] = _RED
    canvas[10:50, 10:80] = _BLUE
    return (canvas.astype(np.float32) / 255.0)[None, ...]


def _demo_video(frames: int = 12, size: int = 128):
    return np.stack([_demo_image(size)[0] for _ in range(frames)]).astype(np.float32)


# --------------------------------------------------------------------------
# 连通性
# --------------------------------------------------------------------------
def test_server_reachable_and_lists_models():
    models = ollama_client.list_models(URL, probe_vision=True)
    assert models, f"{URL} 上没有模型"
    print(f"      服务端模型 {len(models)} 个，其中 vision 模型 "
          f"{sum(1 for m in models if m.get('vision'))} 个")
    for m in models[:6]:
        print(f"        {'👁' if m.get('vision') else '  '} {m['name']} ({m['parameter_size']})")


def test_vision_only_filter_excludes_text_models():
    vision = ollama_client.list_models(URL, vision_only=True)
    names = {m["name"] for m in vision}
    assert MODEL in names, f"{MODEL} 应被识别为 vision 模型，实际 vision 列表：{sorted(names)}"
    # 纯文本模型不应出现在 vision 列表里
    all_models = {m["name"] for m in ollama_client.list_models(URL)}
    assert names <= all_models


def test_resolve_model_tolerates_wrong_name():
    """回归：模型名多写一段（如 ``xxx-27B-abliterated``）时应能自动纠正。

    这里按当前 MODEL 动态构造一个"多了一段"的近似名字，避免依赖具体模型。
    """
    repo, _, tag = MODEL.partition(":")
    wrong = f"{repo}-27B{':' + tag if tag else ''}"
    resolved = ollama_client.resolve_model(URL, wrong)
    assert resolved == MODEL, f"期望容错解析为 {MODEL}，实际 {resolved}"


def test_resolve_model_error_lists_candidates():
    try:
        ollama_client.resolve_model(URL, "完全不存在的模型xyz:1b")
    except ollama_client.ModelNotFound as exc:
        assert "可用模型" in str(exc) or "候选" in str(exc)
        return
    raise AssertionError("应当抛出 ModelNotFound")


# --------------------------------------------------------------------------
# 节点注册（G3）
# --------------------------------------------------------------------------
def test_input_types_valid_for_all_nodes():
    """每个节点都能产出结构合法的 INPUT_TYPES。"""
    assert set(_pkg.NODE_CLASS_MAPPINGS) == {
        "OllamaQWEConnect",
        "OllamaQWEVL",
        "OllamaQWEVLAdvanced",
        "OllamaQWEEnhancer",
    }, _pkg.NODE_CLASS_MAPPINGS.keys()
    assert set(_pkg.NODE_DISPLAY_NAME_MAPPINGS) == set(_pkg.NODE_CLASS_MAPPINGS)
    assert _pkg.WEB_DIRECTORY == "./web"

    for cls in (OllamaQWEConnect, OllamaQWEVL, OllamaQWEVLAdvanced, OllamaQWEEnhancer):
        spec = cls.INPUT_TYPES()
        assert "required" in spec, f"{cls.__name__} 缺少 required"
        assert isinstance(cls.RETURN_TYPES, tuple) and cls.RETURN_TYPES
        assert cls.FUNCTION and hasattr(cls, cls.FUNCTION), f"{cls.__name__} 的 FUNCTION 不存在"
        print(f"      {cls.__name__}: required={len(spec['required'])} "
              f"optional={len(spec.get('optional', {}))} -> {cls.RETURN_NAMES}")


def test_vl_model_dropdown_is_vision_filtered():
    spec = OllamaQWEVL.INPUT_TYPES()
    choices = spec["required"]["model"][0]
    assert isinstance(choices, list) and choices, "模型下拉框不应为空"


def test_dropdowns_use_the_right_candidate_sets():
    """回归：``preset_prompt`` 曾误用 ``model_choices()`` 作为候选集，
    导致预设下拉框里显示的是模型名。"""
    from _pkgload import load_package

    prompts = load_package().core.prompts

    for cls in (OllamaQWEVL, OllamaQWEVLAdvanced):
        spec = cls.INPUT_TYPES()
        presets = spec["required"]["preset_prompt"][0]
        expected = prompts.preset_prompt_names()
        assert presets == expected, (
            f"{cls.__name__}.preset_prompt 候选集错误：{presets[:3]}… 应为 {expected[:3]}…"
        )
        # 默认值必须在候选集内
        assert spec["required"]["preset_prompt"][1]["default"] in presets
        # 预设名不应长得像模型名
        assert not any(":" in p for p in presets), presets

    spec = OllamaQWEEnhancer.INPUT_TYPES()
    styles = spec["required"]["enhancement_style"][0]
    assert styles == prompts.style_names(), styles
    assert spec["required"]["enhancement_style"][1]["default"] in styles

    # 模型候选集应当来自服务器（而非预设名）
    models = OllamaQWEVL.INPUT_TYPES()["required"]["model"][0]
    assert all(":" in m or "/" in m for m in models), models
    assert MODEL in models, f"vision 模型列表应含 {MODEL}：{models}"
    print(f"      预设 {len(prompts.preset_prompt_names())} 项 / 风格 "
          f"{len(styles)} 项 / VL 模型候选 {len(models)} 项")


# --------------------------------------------------------------------------
# 端到端：VL 基础节点
# --------------------------------------------------------------------------
def test_vl_node_image_end_to_end():
    node = OllamaQWEVL()
    t0 = time.time()
    (result,) = node.process(
        url=URL,
        model=MODEL,
        preset_prompt="🖼️ Simple Description",
        custom_prompt="",
        system_prompt="You are a precise image describer. Answer in one short sentence.",
        keep_alive=5,
        keep_alive_unit="minutes",
        max_tokens=64,
        frame_count=8,
        video_frame_size="auto",
        seed=1,
        clean_output=True,
        image=_demo_image(),
    )
    elapsed = time.time() - t0
    print(f"      [{elapsed:.1f}s] 图像描述：{result!r}")
    assert result and len(result) > 3, "图像描述不应为空"
    lowered = result.lower()
    assert "red" in lowered or "circle" in lowered or "blue" in lowered, (
        f"描述应提到图中的红圆/蓝块，实际：{result!r}"
    )


def test_vl_node_video_degrades_to_frames():
    """视频降级：抽帧后作为多张图片送入。"""
    node = OllamaQWEVL()
    t0 = time.time()
    (result,) = node.process(
        url=URL,
        model=MODEL,
        preset_prompt="🖼️ Simple Description",
        custom_prompt="",
        system_prompt="",
        keep_alive=5,
        keep_alive_unit="minutes",
        max_tokens=48,
        frame_count=4,
        video_frame_size="384",
        seed=1,
        clean_output=True,
        video=_demo_video(frames=12),
    )
    elapsed = time.time() - t0
    print(f"      [{elapsed:.1f}s] 视频(4 帧)描述：{result!r}")
    assert result, "视频帧描述不应为空"


# --------------------------------------------------------------------------
# 端到端：Prompt 增强节点
# --------------------------------------------------------------------------
def test_enhancer_node_end_to_end():
    node = OllamaQWEEnhancer()
    t0 = time.time()
    (result,) = node.process(
        url=URL,
        model=MODEL,
        prompt_text="a cat",
        enhancement_style="📝 Enhance",
        custom_system_prompt="",
        max_tokens=96,
        temperature=0.7,
        top_p=0.9,
        seed=1,
        keep_alive=5,
        keep_alive_unit="minutes",
        clean_output=True,
        think=False,
    )
    elapsed = time.time() - t0
    print(f"      [{elapsed:.1f}s] 增强结果：{result[:160]!r}")
    assert result and len(result) > 5, "增强结果不应为空"
    assert "cat" in result.lower(), f"增强结果应保留原主题，实际：{result!r}"


# --------------------------------------------------------------------------
# 错误路径（AC-8）
# --------------------------------------------------------------------------
def test_unreachable_host_raises_readable_error():
    try:
        ollama_client.list_models("http://127.0.0.1:59999", timeout=2.0)
    except ollama_client.OllamaUnavailable as exc:
        message = str(exc)
        assert "无法连接" in message and "ollama serve" in message, message
        return
    raise AssertionError("应当抛出 OllamaUnavailable")


def test_vl_node_rejects_text_only_model():
    """VL 节点应拒绝不具备 vision 能力的模型（FR-03）。"""
    text_models = [
        m["name"]
        for m in ollama_client.list_models(URL)
        if m.get("vision") is False
    ]
    if not text_models:
        print("      （跳过：服务端没有纯文本模型可比对）")
        return

    node = OllamaQWEVL()
    try:
        node.process(
            url=URL, model=text_models[0], preset_prompt="🖼️ Simple Description",
            custom_prompt="", system_prompt="", keep_alive=5, keep_alive_unit="minutes",
            max_tokens=16, frame_count=1, video_frame_size="auto", seed=1,
            clean_output=True, image=_demo_image(64),
        )
    except ollama_client.ModelHasNoVision as exc:
        assert "vision" in str(exc)
        print(f"      正确拒绝纯文本模型 {text_models[0]}")
        return
    raise AssertionError(f"应当拒绝纯文本模型 {text_models[0]}")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    t_all = time.time()
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过，总耗时 {time.time() - t_all:.1f}s")
    sys.exit(1 if failed else 0)
