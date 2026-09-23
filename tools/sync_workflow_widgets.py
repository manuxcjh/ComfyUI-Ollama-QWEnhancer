#!/usr/bin/env python3
"""把示例工作流的 ``widgets_values`` 与本包 ``INPUT_TYPES`` 对齐。

节点新增/删除 widget 后，已保存的工作流会缺少或多出末尾的取值。
本工具按 ``INPUT_TYPES.required`` 的**声明顺序**补齐/裁剪，使二者一致：

* 缺项 → 用 ``INPUT_TYPES`` 里的 ``default`` 补齐
* 多项 → 从末尾裁剪，并打印告警

用法（在包根目录）::

    python tools/sync_workflow_widgets.py            # 只报告差异
    python tools/sync_workflow_widgets.py --apply    # 写回文件
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT / "tests"))

from _pkgload import load_package  # noqa: E402

_pkg = load_package()
MY_NODES = _pkg.NODE_CLASS_MAPPINGS

_SLOT_TYPES = {
    "IMAGE", "MASK", "VIDEO", "AUDIO", "LATENT", "MODEL", "CLIP", "VAE",
    "CONDITIONING", "QWE_OLLAMA_CONN", "*", "ANY",
}


def _is_widget(spec_type) -> bool:
    if isinstance(spec_type, list):
        return True
    return isinstance(spec_type, str) and spec_type.upper() not in _SLOT_TYPES


def _widget_specs(node_type: str) -> list[tuple[str, dict]]:
    spec = MY_NODES[node_type].INPUT_TYPES().get("required", {})
    return [(n, e[1] if len(e) > 1 else {}) for n, e in spec.items() if _is_widget(e[0])]


def _default_for(opts: dict, spec_type) -> object:
    if "default" in opts:
        return opts["default"]
    if isinstance(spec_type, list):
        return spec_type[0] if spec_type else ""
    if spec_type == "STRING":
        return ""
    if spec_type == "INT":
        return int(opts.get("min", 0))
    if spec_type == "FLOAT":
        return float(opts.get("min", 0.0))
    if spec_type == "BOOLEAN":
        return False
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回文件")
    args = parser.parse_args()

    changed = 0
    for path in sorted((PKG_ROOT / "example_workflows").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        touched = False

        for node in data.get("nodes", []):
            ntype = node.get("type")
            if ntype not in MY_NODES:
                continue

            specs = _widget_specs(ntype)
            actual = list(node.get("widgets_values") or [])

            if len(actual) == len(specs):
                continue

            if len(actual) < len(specs):
                for i in range(len(actual), len(specs)):
                    name, opts = specs[i]
                    spec_type = MY_NODES[ntype].INPUT_TYPES()["required"][name][0]
                    value = _default_for(opts, spec_type)
                    actual.append(value)
                    print(f"  {path.name}::{ntype} 补 {name}={value!r}")
            else:
                print(f"  {path.name}::{ntype} 多出 {len(actual) - len(specs)} 项，已裁剪")
                actual = actual[: len(specs)]

            node["widgets_values"] = actual
            touched = True

        if touched:
            changed += 1
            if args.apply:
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                print(f"  已写回 {path.name}")

    if not changed:
        print("所有示例工作流的 widgets_values 均已对齐")
    elif not args.apply:
        print(f"\n{changed} 个文件需更新；加 --apply 写回")
    return 0


if __name__ == "__main__":
    sys.exit(main())
