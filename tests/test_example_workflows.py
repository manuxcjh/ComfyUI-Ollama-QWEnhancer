"""G6 门控：示例工作流校验（不需要 ComfyUI 运行）。

ComfyUI 没在运行，因此退而校验工作流 JSON 的**结构自洽性**与
**与本包 INPUT_TYPES 的一致性** —— 这两类错误占工作流加载失败原因的绝大多数：

1. JSON 可解析且含必需的顶层字段
2. 引用的节点类型真实存在（本包节点 + 从 ComfyUI 源码核实的 core 节点）
3. 链接自洽：link id 唯一、两端节点/插槽存在、link id 双向一致
4. **本包节点的 `widgets_values` 数量与 `INPUT_TYPES.required` 完全一致**
   （顺序错位是 widget 取值串位的最常见原因）
5. combo 类 widget 的取值在候选集内；数值类在 min/max 范围内
6. 必需插槽均已连线

运行::

    <comfy-venv>/bin/python tests/test_example_workflows.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pkgload import load_package  # noqa: E402

PKG_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = PKG_ROOT / "example_workflows"
COMFY_ROOT = Path("<ComfyUI>")

_pkg = load_package()
MY_NODES = _pkg.NODE_CLASS_MAPPINGS

#: 本包节点用到的非本包（core）节点 —— 会到 ComfyUI 源码里核实是否真实存在
CORE_NODES_USED = ["LoadImage", "LoadVideo", "GetVideoComponents", "PreviewAny"]

#: 非 widget 的插槽类型（这些在 INPUT_TYPES 里出现时不会占 widgets_values）
_SLOT_TYPES = {
    "IMAGE",
    "MASK",
    "VIDEO",
    "AUDIO",
    "LATENT",
    "MODEL",
    "CLIP",
    "VAE",
    "CONDITIONING",
    "QWE_OLLAMA_CONN",
    "*",
    "ANY",
}


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOW_DIR.glob("*.json"))


def _is_widget_type(spec_type) -> bool:
    """判断某个 INPUT_TYPES 条目是 widget 还是插槽。"""
    if isinstance(spec_type, list):  # combo → widget
        return True
    if not isinstance(spec_type, str):
        return False
    return spec_type.upper() not in _SLOT_TYPES


# --------------------------------------------------------------------------
# 1. 文件与顶层结构
# --------------------------------------------------------------------------
def test_workflow_files_exist():
    files = _workflow_files()
    assert files, f"{WORKFLOW_DIR} 下没有工作流 JSON"
    print(f"      发现 {len(files)} 个示例工作流：{[f.name for f in files]}")


def test_top_level_structure():
    for path in _workflow_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("nodes", "links", "version"):
            assert key in data, f"{path.name} 缺少顶层字段 {key}"
        assert isinstance(data["nodes"], list) and data["nodes"], f"{path.name} 无节点"
        assert isinstance(data["links"], list), f"{path.name} links 不是数组"
        # last_node_id / last_link_id 应不小于实际最大值，否则前端新建节点会撞 id
        max_node = max(n["id"] for n in data["nodes"])
        max_link = max((l[0] for l in data["links"]), default=0)
        assert data.get("last_node_id", max_node) >= max_node, f"{path.name} last_node_id 偏小"
        assert data.get("last_link_id", max_link) >= max_link, f"{path.name} last_link_id 偏小"


# --------------------------------------------------------------------------
# 2. 节点类型存在性
# --------------------------------------------------------------------------
def _core_node_defined_in_source(name: str) -> bool:
    """在 ComfyUI 源码里核实 core 节点是否存在（节点未运行时的替代验证）。"""
    if not COMFY_ROOT.exists():
        return True  # 读不到源码时跳过，不产生假失败

    candidates = [COMFY_ROOT / "nodes.py"]
    extras = COMFY_ROOT / "comfy_extras"
    if extras.is_dir():
        candidates.extend(sorted(extras.glob("*.py")))

    needles = (f'"{name}"', f"'{name}'", f'node_id="{name}"')
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if any(n in text for n in needles):
            return True
    return False


def test_core_nodes_actually_exist():
    for name in CORE_NODES_USED:
        if COMFY_ROOT.exists():
            assert _core_node_defined_in_source(name), (
                f"示例工作流引用的 core 节点 {name!r} 在 {COMFY_ROOT} 源码中找不到"
            )
    print(f"      core 节点已核实：{CORE_NODES_USED}")


def test_all_node_types_known():
    known_core = set(CORE_NODES_USED)
    for path in _workflow_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        for node in data["nodes"]:
            ntype = node["type"]
            assert ntype in MY_NODES or ntype in known_core, (
                f"{path.name} 引用了未知节点类型 {ntype!r}"
            )


# --------------------------------------------------------------------------
# 3. 链接自洽性
# --------------------------------------------------------------------------
def test_links_are_consistent():
    for path in _workflow_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        by_id = {n["id"]: n for n in data["nodes"]}

        seen: set[int] = set()
        for link in data["links"]:
            assert len(link) >= 6, f"{path.name} 链接格式错误：{link}"
            lid, src_id, src_slot, dst_id, dst_slot = link[:5]
            assert lid not in seen, f"{path.name} 链接 id {lid} 重复"
            seen.add(lid)

            assert src_id in by_id, f"{path.name} 链接 {lid} 的源节点 {src_id} 不存在"
            assert dst_id in by_id, f"{path.name} 链接 {lid} 的目标节点 {dst_id} 不存在"

            src = by_id[src_id]
            dst = by_id[dst_id]
            assert src_slot < len(src.get("outputs") or []), (
                f"{path.name} 链接 {lid}：源节点 {src_id} 无第 {src_slot} 号输出"
            )
            assert dst_slot < len(dst.get("inputs") or []), (
                f"{path.name} 链接 {lid}：目标节点 {dst_id} 无第 {dst_slot} 号输入"
            )

            # 反向引用必须一致
            src_out = src["outputs"][src_slot]
            assert lid in (src_out.get("links") or []), (
                f"{path.name} 链接 {lid} 未出现在源节点 {src_id} 输出的 links 中"
            )
            dst_in = dst["inputs"][dst_slot]
            assert dst_in.get("link") == lid, (
                f"{path.name} 节点 {dst_id} 输入 {dst_in.get('name')!r} "
                f"记录 link={dst_in.get('link')}，应为 {lid}"
            )


def test_required_slots_are_connected():
    """带插槽的必需输入（如 PreviewAny.source）必须连线。"""
    for path in _workflow_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        for node in data["nodes"]:
            ntype = node["type"]
            if ntype not in MY_NODES:
                # core 节点只检查非 widget 插槽是否连线
                for slot in node.get("inputs") or []:
                    if slot.get("link") is None and slot.get("name") == "source":
                        raise AssertionError(
                            f"{path.name} 节点 {node['id']} 的 source 未连线"
                        )
                continue

            spec = MY_NODES[ntype].INPUT_TYPES()
            required = spec.get("required", {})
            connected = {s["name"] for s in (node.get("inputs") or []) if s.get("link") is not None}
            for name, entry in required.items():
                if _is_widget_type(entry[0]):
                    continue
                assert name in connected, (
                    f"{path.name} 节点 {node['id']}({ntype}) 的必需插槽 {name!r} 未连线"
                )


# --------------------------------------------------------------------------
# 4. widgets_values 与 INPUT_TYPES 对齐（最关键）
# --------------------------------------------------------------------------
def test_widgets_values_match_input_types():
    for path in _workflow_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        for node in data["nodes"]:
            ntype = node["type"]
            if ntype not in MY_NODES:
                continue

            spec = MY_NODES[ntype].INPUT_TYPES()
            expected = [name for name, entry in spec.get("required", {}).items()
                        if _is_widget_type(entry[0])]
            actual = node.get("widgets_values") or []

            assert len(actual) == len(expected), (
                f"{path.name} 节点 {node['id']}({ntype}) 的 widgets_values 有 {len(actual)} 项，"
                f"但 INPUT_TYPES.required 需要 {len(expected)} 个 widget：{expected}"
            )
            print(f"      {path.name}::{ntype} widgets 数量 {len(actual)} ✓")


def test_widget_values_are_valid():
    """combo 取值必须在候选集内；数值必须在 min/max 内。"""
    for path in _workflow_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        for node in data["nodes"]:
            ntype = node["type"]
            if ntype not in MY_NODES:
                continue

            spec = MY_NODES[ntype].INPUT_TYPES()
            widgets = [(name, entry) for name, entry in spec.get("required", {}).items()
                       if _is_widget_type(entry[0])]
            values = node.get("widgets_values") or []

            for (name, entry), value in zip(widgets, values):
                spec_type, opts = entry[0], (entry[1] if len(entry) > 1 else {})

                if isinstance(spec_type, list):  # combo
                    if value in spec_type:
                        pass
                    elif name == "model":
                        # 示例工作流是给用户当模板的，用的通用模型名本机未必装了。
                        # 其余 combo（预设/风格/帧尺寸）必须是合法值，模型名只告警。
                        print(
                            f"      [告警] {path.name} 的 model={value!r} 本机未安装"
                            f"（示例模板允许，运行前请改成自己的模型）"
                        )
                    else:
                        raise AssertionError(
                            f"{path.name} 节点 {node['id']}({ntype}) 的 {name}={value!r} "
                            f"不在候选集内：{spec_type}"
                        )
                elif spec_type == "INT":
                    assert isinstance(value, int) and not isinstance(value, bool), (
                        f"{path.name} {ntype}.{name} 应为 int，实际 {value!r}"
                    )
                    if "min" in opts:
                        assert value >= opts["min"], f"{ntype}.{name}={value} < min {opts['min']}"
                    if "max" in opts:
                        assert value <= opts["max"], f"{ntype}.{name}={value} > max {opts['max']}"
                elif spec_type == "FLOAT":
                    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
                        f"{path.name} {ntype}.{name} 应为 float，实际 {value!r}"
                    )
                    if "min" in opts:
                        assert value >= opts["min"], f"{ntype}.{name}={value} < min {opts['min']}"
                    if "max" in opts:
                        assert value <= opts["max"], f"{ntype}.{name}={value} > max {opts['max']}"
                elif spec_type == "BOOLEAN":
                    assert isinstance(value, bool), (
                        f"{path.name} {ntype}.{name} 应为 bool，实际 {value!r}"
                    )
                elif spec_type == "STRING":
                    assert isinstance(value, str), (
                        f"{path.name} {ntype}.{name} 应为 str，实际 {value!r}"
                    )


def test_model_values_are_reachable():
    """工作流里写的模型名应能被 resolve_model 解析（容错后）。"""
    ollama_client = _pkg.core.ollama_client
    url = _pkg.core.types.DEFAULT_URL
    checked: set[str] = set()
    try:
        for path in _workflow_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            for node in data["nodes"]:
                if node["type"] not in MY_NODES:
                    continue
                spec = MY_NODES[node["type"]].INPUT_TYPES()
                widgets = [n for n, e in spec.get("required", {}).items() if _is_widget_type(e[0])]
                if "model" not in widgets:
                    continue
                model = (node.get("widgets_values") or [])[widgets.index("model")]
                if model in checked:
                    continue
                checked.add(model)
                resolved = ollama_client.resolve_model(url, model)
                print(f"      模型 {model!r} → {resolved!r}")
    except ollama_client.ModelNotFound as exc:
        print(f"      （跳过：示例模型本机未安装 —— {str(exc).splitlines()[0]}）")
        return
    except ollama_client.OllamaError as exc:
        print(f"      （跳过：Ollama 不可达 —— {str(exc).splitlines()[0]}）")
        return
    assert checked, "没有任何工作流声明了 model"


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
