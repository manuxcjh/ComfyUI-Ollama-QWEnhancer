"""G5 门控：命名空间冲突检查（NFR-03）。

用 AST 精确提取 ``NODE_CLASS_MAPPINGS`` 的键，而不是靠 grep 猜 ——
grep 会把 widget 名（``model`` / ``seed`` …）统统当成"冲突"。

检查项
------
1. Node ID：本包与 ``comfyui-ollama``、``ComfyUI-QwenVL`` 的键集合交集必须为空
2. HTTP 路由：本包注册的路径不得与上游重复
3. 数据类型：本包声明的类型必须 ``QWE_`` 前缀，且不与上游 ``OLLAMA_*`` 撞名
4. 显示名：仅告警（ComfyUI 允许重复），不判失败

用法::

    python tests/check_conflicts.py            # 在包根目录执行
    python tests/check_conflicts.py --help
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_DIRS = [
    PKG_ROOT.parent / "comfyui-ollama",
    PKG_ROOT.parent / "ComfyUI-QwenVL",
]

_ROUTE_HINT_RE = re.compile(
    r"""(?:add_(?:post|get)|routes\.(?:post|get)|ROUTE_PATH\s*=)\s*\(?\s*["']([^"']+)["']"""
)
_TYPE_LITERAL_RE = re.compile(r"""["'](OLLAMA_[A-Z0-9_]+|QWE_[A-Z0-9_]+)["']""")


def _py_files(root: Path):
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _mapping_keys(root: Path, variable: str) -> set[str]:
    """AST 提取 ``NODE_CLASS_MAPPINGS`` / ``NODE_DISPLAY_NAME_MAPPINGS`` 的键。"""
    keys: set[str] = set()
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if variable not in targets:
                continue
            # 字面量 dict，或被 update({...}) 合并的情况都覆盖
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Dict):
                    for key in sub.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            keys.add(key.value)
    return keys


def _routes(root: Path) -> set[str]:
    routes: set[str] = set()
    for path in _py_files(root):
        text = path.read_text(encoding="utf-8")
        for match in _ROUTE_HINT_RE.finditer(text):
            routes.add(match.group(1))
    return routes


def _type_literals(root: Path) -> set[str]:
    """提取 ``QWE_*`` / ``OLLAMA_*`` 形态的类型字面量。

    跳过 ``tests/`` 与 ``tools/``：那里出现的 ``"QWE_URL"`` 是环境变量名，
    不是 ComfyUI 数据类型，否则会产生假阳性。
    """
    types: set[str] = set()
    for path in _py_files(root):
        if {"tests", "tools"} & set(path.parts):
            continue
        for match in _TYPE_LITERAL_RE.finditer(path.read_text(encoding="utf-8")):
            types.add(match.group(1))
    return types


def main() -> int:
    parser = argparse.ArgumentParser(description="检查与上游插件的命名空间冲突")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    failures: list[str] = []

    # ---- 1. Node ID ----------------------------------------------------
    mine = _mapping_keys(PKG_ROOT, "NODE_CLASS_MAPPINGS")
    upstream: set[str] = set()
    for directory in UPSTREAM_DIRS:
        upstream |= _mapping_keys(directory, "NODE_CLASS_MAPPINGS")

    if not mine:
        failures.append("本包未提取到任何 NODE_CLASS_MAPPINGS 键")
    clash = sorted(mine & upstream)
    if clash:
        failures.append(f"Node ID 与上游冲突：{clash}")
    if not args.quiet:
        print(f"  本包 Node ID ({len(mine)}): {sorted(mine)}")
        print(f"  上游 Node ID ({len(upstream)}): {sorted(upstream)}")

    # ---- 2. HTTP 路由 --------------------------------------------------
    my_routes = _routes(PKG_ROOT)
    upstream_routes: set[str] = set()
    for directory in UPSTREAM_DIRS:
        upstream_routes |= _routes(directory)
    route_clash = sorted(my_routes & upstream_routes)
    if route_clash:
        failures.append(f"HTTP 路由与上游冲突（aiohttp 会因重复注册崩溃）：{route_clash}")
    if not my_routes:
        failures.append("本包未声明任何 HTTP 路由（P4 应注册模型列表路由）")
    for route in my_routes:
        if not route.startswith("/ollama_qwenhancer/"):
            failures.append(f"路由 {route!r} 未使用本包专属前缀 /ollama_qwenhancer/")
    if not args.quiet:
        print(f"  本包路由: {sorted(my_routes)}")
        print(f"  上游路由: {sorted(upstream_routes)}")

    # ---- 3. 数据类型 ---------------------------------------------------
    my_types = _type_literals(PKG_ROOT)
    upstream_types: set[str] = set()
    for directory in UPSTREAM_DIRS:
        upstream_types |= _type_literals(directory)
    bad_prefix = sorted(t for t in my_types if not t.startswith("QWE_"))
    if bad_prefix:
        failures.append(f"数据类型缺少 QWE_ 前缀：{bad_prefix}")
    type_clash = sorted(my_types & upstream_types)
    if type_clash:
        failures.append(f"数据类型与上游冲突：{type_clash}")
    if not args.quiet:
        print(f"  本包类型: {sorted(my_types)}")

    # ---- 4. 显示名（仅告警）--------------------------------------------
    my_display = _mapping_keys(PKG_ROOT, "NODE_DISPLAY_NAME_MAPPINGS")
    upstream_display: set[str] = set()
    for directory in UPSTREAM_DIRS:
        upstream_display |= _mapping_keys(directory, "NODE_DISPLAY_NAME_MAPPINGS")
    display_clash = sorted(my_display & upstream_display)
    if display_clash and not args.quiet:
        print(f"  [告警] 显示名与上游重复（不致命）：{display_clash}")

    if failures:
        print("\nFAIL  命名空间冲突检查")
        for item in failures:
            print(f"      - {item}")
        return 1

    print("\nPASS  命名空间冲突检查（Node ID / 路由 / 数据类型 均无冲突）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
