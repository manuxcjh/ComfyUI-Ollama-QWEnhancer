#!/usr/bin/env bash
# 一键跑通全部门控（G1 / G2 / G3 / G4 / G5 / G6）
#
# 用法：
#   bash tests/run_all.sh               # 全部（含对真实 Ollama 的实网测试）
#   QWE_OFFLINE=1 bash tests/run_all.sh # 只跑离线部分（不需要 Ollama 服务）
#
# 解释器：本包运行期依赖 ComfyUI 宿主提供的 numpy / Pillow / torch，
# 因此**必须用 ComfyUI 的那个 Python**。选择顺序：
#   1) QWE_PYTHON 环境变量
#   2) COMFY_VENV 环境变量（指向 venv 根目录）
#   3) config/local.json 的 "python" 字段
#   4) python3（通常不带上述依赖，会在预检处被拦下并给出提示）
#
# 其它环境变量：
#   QWE_URL     Ollama 地址（留空则由 core/types.py 解析）
#   QWE_MODEL   模型名（留空则由 core/types.py 解析）
set -uo pipefail

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PKG"

# 从 config/local.json 读取本机专用配置（该文件已 gitignore）
_lc() {
  local cfg="$PKG/config/local.json"
  [[ -f "$cfg" ]] || return 0
  python3 -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get(sys.argv[2]) or '')" "$cfg" "$1" 2>/dev/null || true
}

PY="${QWE_PYTHON:-}"
if [[ -z "$PY" && -n "${COMFY_VENV:-}" && -x "${COMFY_VENV}/bin/python" ]]; then
  PY="${COMFY_VENV}/bin/python"
fi
[[ -z "$PY" ]] && PY="$(_lc python)"
if [[ -z "$PY" || ! -x "$PY" ]]; then
  PY="$(command -v python3 || true)"
fi

# --- 预检：缺依赖时给出可操作的提示，而不是让 4 个测试报 "No module named 'PIL'" ---
if [[ -z "$PY" ]]; then
  echo "❌ 找不到可用的 Python 解释器。"
  exit 1
fi
_missing="$("$PY" - <<'PYEOF' 2>/dev/null || echo "python"
mods = []
for m in ("numpy", "PIL"):
    try:
        __import__(m)
    except Exception:
        mods.append(m)
print(",".join(mods))
PYEOF
)"
if [[ -n "$_missing" ]]; then
  cat <<EOF
❌ 选中的 Python 缺少依赖：$_missing
   解释器：$PY

   本包运行期依赖 ComfyUI 宿主提供的 numpy / Pillow / torch，
   请指定 ComfyUI 所使用的 Python，例如：

     QWE_PYTHON=/path/to/ComfyUI/venv/bin/python bash tests/run_all.sh
     # 或
     COMFY_VENV=/path/to/ComfyUI/venv bash tests/run_all.sh

   也可以把它写进本机配置，之后就不用每次带参数：

     cp config/local.json.example config/local.json
     # 编辑其中的 "python": "/path/to/ComfyUI/venv/bin/python"
EOF
  exit 1
fi

# 不硬编码地址/模型：留空时由 core/types.py 解析（环境变量 > config/local.json > 默认）
export QWE_URL="${QWE_URL:-}"
export QWE_MODEL="${QWE_MODEL:-}"

fail=0
step() { # step <门控标题> <命令...>
  local title="$1"; shift
  echo
  echo "════════ $title ════════"
  if "$@"; then
    echo "---- $title 通过"
  else
    echo "---- $title 失败"
    fail=1
  fi
}

echo "python : $PY"
echo "ollama : $QWE_URL"
echo "model  : $QWE_MODEL"

# G1：语法与结构
step "G1 语法与包结构" "$PY" -c "
import ast, pathlib, sys
files = sorted(pathlib.Path('.').rglob('*.py'))
for p in files:
    ast.parse(p.read_text(encoding='utf-8'))
print(f'  {len(files)} 个 .py 文件语法正确')
"

# G1：包可加载 + 节点注册
step "G3 包加载与节点注册" "$PY" -c "
import sys, pathlib
sys.path.insert(0, 'tests')
from _pkgload import load_package
pkg = load_package()
expected = {'OllamaQWEConnect','OllamaQWEVL','OllamaQWEVLAdvanced','OllamaQWEEnhancer'}
got = set(pkg.NODE_CLASS_MAPPINGS)
assert got == expected, f'节点注册不符：{got}'
assert pkg.WEB_DIRECTORY == './web'
print(f'  节点注册正确：{sorted(got)}')
"

# G2：离线单测
step "G2 核心层离线单测" "$PY" tests/test_core_offline.py

# G6：示例工作流结构校验（离线）
step "G6 示例工作流校验" "$PY" tests/test_example_workflows.py

# G6：禁用直通行为（离线，用不可达地址证明不发网络请求）
step "G6 禁用直通行为" "$PY" tests/test_passthrough.py

# G4：路由注册
if [[ -z "${QWE_OFFLINE:-}" ]]; then
  step "G4 路由注册与接口契约" "$PY" tests/test_route_registration.py
else
  echo; echo "（QWE_OFFLINE=1：跳过 G4 实网部分）"
fi

# G5：契约扫描
step "G5 契约与冲突扫描" bash tests/test_contract_scan.sh

# G6：实网端到端
if [[ -z "${QWE_OFFLINE:-}" ]]; then
  step "G6 对真实 Ollama 的端到端测试" "$PY" tests/test_live_ollama.py
else
  echo; echo "（QWE_OFFLINE=1：跳过 G6）"
fi

# G6：对等矩阵待决项
step "G6 对等矩阵待决项" "$PY" -c "
import pathlib, sys
rows = [l for l in pathlib.Path('docs/03-功能对等矩阵.md').read_text(encoding='utf-8').splitlines()
        if l.startswith('|') and '**待定**' in l]
if rows:
    print('  未裁定决策项：')
    for r in rows:
        print('   -', r.split('|')[1].strip(), '->', r.split('|')[2].strip())
    sys.exit(1)
print('  无未裁定项')
"

echo
echo "════════════════════════════════"
if [[ $fail -eq 0 ]]; then
  echo "全部门控通过 ✅"
else
  echo "存在失败门控 ❌"
fi
exit $fail
