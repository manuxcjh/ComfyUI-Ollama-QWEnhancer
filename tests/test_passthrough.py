"""G6 门控：禁用直通（passthrough）行为测试。

覆盖用户需求：「如果这个节点被禁用，如何把输入的 prompt 直通到输出？」

两条路径
--------
1. **``enabled=False``（确定性直通）** —— 节点跳过推理，原样输出提示文本。
   本文件用**不可达的 url** 证明它确实不发任何网络请求。
2. **ComfyUI 原生 Bypass** —— 前端 ``ExecutableNodeDTO.resolveOutput`` 在
   ``mode == BYPASS`` 时按「输入/输出类型匹配」直通；因此节点必须声明一个
   ``STRING`` 类型的**输入插槽**（``prompt_in``）。本文件断言该插槽存在且为
   ``forceInput``（插槽而非 widget）。

运行::

    <comfy-venv>/bin/python tests/test_passthrough.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pkgload import load_package  # noqa: E402

_pkg = load_package()

OllamaQWEVL = _pkg.NODE_CLASS_MAPPINGS["OllamaQWEVL"]
OllamaQWEVLAdvanced = _pkg.NODE_CLASS_MAPPINGS["OllamaQWEVLAdvanced"]
OllamaQWEEnhancer = _pkg.NODE_CLASS_MAPPINGS["OllamaQWEEnhancer"]

#: 故意不可达 —— 若禁用路径还去连服务器，测试会明显变慢或直接抛错
UNREACHABLE = "http://127.0.0.1:59998"


# --------------------------------------------------------------------------
# 节点声明：passthrough 的结构前提
# --------------------------------------------------------------------------
def test_prompt_in_is_a_string_input_slot():
    """``prompt_in`` 必须是 STRING 类型的输入插槽（forceInput），
    这样前端 Bypass 才能把上游 STRING 直通到 STRING 输出。"""
    for cls in (OllamaQWEVL, OllamaQWEVLAdvanced, OllamaQWEEnhancer):
        spec = cls.INPUT_TYPES()
        assert "prompt_in" in spec.get("optional", {}), f"{cls.__name__} 缺少 prompt_in"
        entry = spec["optional"]["prompt_in"]
        assert entry[0] == "STRING", f"{cls.__name__}.prompt_in 类型应为 STRING，实际 {entry[0]}"
        assert entry[1].get("forceInput") is True, (
            f"{cls.__name__}.prompt_in 需 forceInput=True 才是插槽而非文本框"
        )
        # 输出类型必须是 STRING，才能与 prompt_in 类型匹配
        assert "STRING" in cls.RETURN_TYPES, cls.RETURN_TYPES
        print(f"      {cls.__name__}: prompt_in(STRING, forceInput) -> {cls.RETURN_NAMES}")


def test_enabled_defaults_to_true_and_is_last_widget():
    """``enabled`` 默认 True，且追加在 required 末尾（不影响老工作流按位置取值）。"""
    for cls in (OllamaQWEVL, OllamaQWEVLAdvanced, OllamaQWEEnhancer):
        required = cls.INPUT_TYPES()["required"]
        assert "enabled" in required, f"{cls.__name__} 缺少 enabled"
        assert required["enabled"][0] == "BOOLEAN"
        assert required["enabled"][1].get("default") is True
        assert list(required)[-1] == "enabled", (
            f"{cls.__name__} 的 enabled 必须在 required 末尾，实际顺序：{list(required)}"
        )
        print(f"      {cls.__name__}: enabled 位于 required 末尾，默认 True")


# --------------------------------------------------------------------------
# Enhancer：禁用即直通
# --------------------------------------------------------------------------
def test_enhancer_disabled_passes_prompt_through():
    node = OllamaQWEEnhancer()
    (out,) = node.process(
        url=UNREACHABLE, model="any", prompt_text="a lonely lighthouse",
        enhancement_style="📝 Enhance", custom_system_prompt="",
        max_tokens=4096, temperature=0.3, top_p=0.9, seed=1,
        keep_alive=5, keep_alive_unit="minutes", clean_output=True, think=False,
        enabled=False,
    )
    assert out == "a lonely lighthouse", out
    print(f"      禁用后输出 = {out!r}（未发生任何网络请求）")


def test_enhancer_prompt_in_overrides_widget():
    """插槽 prompt_in 优先于文本框 prompt_text。"""
    node = OllamaQWEEnhancer()
    (out,) = node.process(
        url=UNREACHABLE, model="any", prompt_text="IGNORED",
        enhancement_style="📝 Enhance", custom_system_prompt="",
        max_tokens=4096, temperature=0.3, top_p=0.9, seed=1,
        keep_alive=5, keep_alive_unit="minutes", clean_output=True, think=False,
        enabled=False, prompt_in="from the socket",
    )
    assert out == "from the socket", out
    print(f"      prompt_in 覆盖成功 = {out!r}")


def test_enhancer_disabled_with_empty_input_falls_back():
    """禁用时若无任何输入，仍返回占位文本而不是空串（保证下游拿到字符串）。"""
    node = OllamaQWEEnhancer()
    (out,) = node.process(
        url=UNREACHABLE, model="any", prompt_text="", enhancement_style="📝 Enhance",
        custom_system_prompt="", max_tokens=4096, temperature=0.3, top_p=0.9, seed=1,
        keep_alive=5, keep_alive_unit="minutes", clean_output=True, think=False,
        enabled=False,
    )
    assert isinstance(out, str) and out, repr(out)
    print(f"      空输入回退 = {out!r}")


# --------------------------------------------------------------------------
# VL：禁用即直通（提示文本原样送出，跳过图像推理）
# --------------------------------------------------------------------------
def test_vl_disabled_passes_prompt_through():
    node = OllamaQWEVL()
    (out,) = node.process(
        url=UNREACHABLE, model="qwen2.5vl:7b",
        preset_prompt="🖼️ Detailed Description", custom_prompt="my custom instruction",
        system_prompt="", keep_alive=5, keep_alive_unit="minutes", max_tokens=512,
        frame_count=8, video_frame_size="auto", seed=1, clean_output=True,
        enabled=False,
    )
    assert out == "my custom instruction", out
    print(f"      VL 禁用后输出 = {out!r}（custom_prompt 直通）")


def test_vl_prompt_in_overrides_custom_prompt():
    node = OllamaQWEVL()
    (out,) = node.process(
        url=UNREACHABLE, model="any", preset_prompt="🖼️ Detailed Description",
        custom_prompt="IGNORED", system_prompt="", keep_alive=5,
        keep_alive_unit="minutes", max_tokens=512, frame_count=8,
        video_frame_size="auto", seed=1, clean_output=True,
        enabled=False, prompt_in="socket instruction",
    )
    assert out == "socket instruction", out


def test_vl_disabled_falls_back_to_preset():
    """禁用且未给自定义提示时，直通的是预设模板正文。"""
    node = OllamaQWEVL()
    (out,) = node.process(
        url=UNREACHABLE, model="any", preset_prompt="🖼️ Detailed Description",
        custom_prompt="", system_prompt="", keep_alive=5, keep_alive_unit="minutes",
        max_tokens=512, frame_count=8, video_frame_size="auto", seed=1,
        clean_output=True, enabled=False,
    )
    expected = _pkg.core.prompts.vl_prompt("🖼️ Detailed Description")
    assert out == expected, out
    print(f"      预设直通长度 = {len(out)} 字符")


def test_vl_advanced_disabled_returns_prompt_and_empty_thinking():
    node = OllamaQWEVLAdvanced()
    out = node.process(
        url=UNREACHABLE, model="any", preset_prompt="🖼️ Tags", custom_prompt="",
        system_prompt="", keep_alive=5, keep_alive_unit="minutes", max_tokens=512,
        temperature=0.6, top_p=0.9, repetition_penalty=1.1, num_ctx=8192,
        frame_count=8, video_frame_size="auto", seed=1, think=False,
        clean_output=True, enabled=False,
    )
    assert isinstance(out, tuple) and len(out) == 2, out
    prompt_text, thinking = out
    assert prompt_text == _pkg.core.prompts.vl_prompt("🖼️ Tags")
    assert thinking in ("", None), thinking
    print(f"      Advanced 禁用后 = (提示文本, {thinking!r})")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
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
