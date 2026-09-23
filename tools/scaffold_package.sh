#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ComfyUI-Ollama-QWEnhancer · P1 骨架生成器
#
# 对应流程文档 docs/02-新软件包创建流程.md 的 P1 阶段。
# 幂等：目录/文件已存在则跳过，不覆盖任何已写内容。
#
# 用法：
#   bash tools/scaffold_package.sh              # dry-run，只打印计划（默认）
#   bash tools/scaffold_package.sh --apply      # 实际创建
#   bash tools/scaffold_package.sh --apply --force   # 覆盖已存在文件
# ---------------------------------------------------------------------------
set -euo pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_QWENVL="$PKG_ROOT/../ComfyUI-QwenVL"

APPLY=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

run() { # run <描述> <命令...>
  local desc="$1"; shift
  if [[ $APPLY -eq 1 ]]; then
    "$@"
    echo "  [done] $desc"
  else
    echo "  [plan] $desc"
  fi
}

make_dirs() {
  local d
  for d in config core nodes server web/js example_workflows docs tests; do
    run "mkdir -p $d" mkdir -p "$PKG_ROOT/$d"
  done
}

make_file() { # make_file <相对路径> ; 内容从 stdin 读取
  local rel="$1"
  local abs="$PKG_ROOT/$rel"
  if [[ -e "$abs" && $FORCE -eq 0 ]]; then
    echo "  [skip] $rel 已存在"
    cat >/dev/null
    return 0
  fi
  if [[ $APPLY -eq 1 ]]; then
    mkdir -p "$(dirname "$abs")"
    cat > "$abs"
    echo "  [done] $rel"
  else
    cat >/dev/null
    echo "  [plan] $rel"
  fi
}

echo "== P1 骨架生成器 =="
echo "包根目录 : $PKG_ROOT"
echo "上游参考 : $UPSTREAM_QWENVL"
[[ $APPLY -eq 1 ]] || echo "模式     : DRY-RUN（加 --apply 实际执行）"
echo

echo "-- 目录 --"
make_dirs

echo "-- 包元数据 --"

make_file pyproject.toml <<'EOF'
# 规范依据：https://docs.comfy.org/registry/specifications
# TODO(P1)：把 <your-publisher-id> 替换为 Comfy Registry 上注册的 PublisherId
[project]
name = "comfyui-ollama-qwenhancer"
version = "0.1.0"
description = "Qwen-VL prompt enhancement and vision-language inference on the Ollama backend for ComfyUI"
license = { file = "LICENSE" }
requires-python = ">=3.9"
dependencies = ["ollama>=0.4,<1.0"]

[project.urls]
Repository = "https://github.com/<owner>/ComfyUI-Ollama-QWEnhancer"

[tool.comfy]
PublisherId = "<your-publisher-id>"
DisplayName = "ComfyUI Ollama QWEnhancer"
Icon = ""
requires-comfyui = ">=1.3.0"
EOF

make_file __init__.py <<'EOF'
"""ComfyUI-Ollama-QWEnhancer

在 Ollama 后端上复现 ComfyUI-QwenVL 的推理侧能力：
  * VL 图像 / 多帧视频理解
  * 预设 prompt 体系与 Prompt 增强
  * 服务器地址可选、模型列表可查询

命名空间与 comfyui-ollama / ComfyUI-QwenVL 完全隔离（NFR-03）。
"""

import importlib
import pkgutil
from pathlib import Path

__version__ = "0.1.0"
__repo_name__ = "ComfyUI-Ollama-QWEnhancer"

_here = Path(__file__).parent
_nodes_dir = _here / "nodes"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


def _load_nodes() -> None:
    """聚合 nodes/ 下各模块的映射（P3 阶段开始生效）。"""
    if not _nodes_dir.exists():
        return
    for _, module_name, _ in pkgutil.iter_modules([str(_nodes_dir)]):
        if module_name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f".nodes.{module_name}", package=__package__)
        except Exception as exc:  # 不因单节点失败阻断 ComfyUI 启动
            print(f"[{__repo_name__}] 节点加载失败 {module_name}: {exc}")
            continue
        NODE_CLASS_MAPPINGS.update(getattr(module, "NODE_CLASS_MAPPINGS", {}))
        NODE_DISPLAY_NAME_MAPPINGS.update(getattr(module, "NODE_DISPLAY_NAME_MAPPINGS", {}))


_load_nodes()

# P4 阶段启用：注册独立 HTTP 路由 /ollama_qwenhancer/list_models
try:
    from .server.routes import register_routes  # noqa: F401
except Exception:
    pass

print(
    f"\033[36m[{__repo_name__}]\033[0m v\033[93m{__version__}\033[0m | "
    f"\033[37m{len(NODE_CLASS_MAPPINGS)} nodes\033[0m \033[92mLoaded\033[0m"
)
EOF

make_file CHANGE_LOG.md <<'EOF'
# Change Log

## v0.1.0 (未发布)
- 初始骨架（流程 P1）
- 需求分析、创建流程、功能对等矩阵三份文档
EOF

make_file requirements.txt <<'EOF'
# ComfyUI-Ollama-QWEnhancer 运行期依赖
# torch / numpy / Pillow / aiohttp 由 ComfyUI 宿主提供，不在此声明（NFR-01）
ollama>=0.4,<1.0
EOF

make_file .comfyignore <<'EOF'
__pycache__/
*.pyc
docs/
tests/
tools/
.github/
.git/
*.md
!README.md
EOF

make_file .gitignore <<'EOF'
__pycache__/
*.pyc
.venv/
EOF

make_file server/__init__.py <<'EOF'
"""ComfyUI PromptServer 路由注册（P4 阶段实现）。"""
EOF

make_file server/routes.py <<'EOF'
"""P4：注册 POST /ollama_qwenhancer/list_models。

注意（风险 R2）：不得复用 /ollama/get_models —— aiohttp 对同一 path+method
重复注册会抛 RuntimeError: Added route will never be executed。
"""
ROUTE_PATH = "/ollama_qwenhancer/list_models"


def register_routes() -> bool:
    """在 ComfyUI PromptServer 上注册路由；失败时返回 False 而非中断加载。"""
    raise NotImplementedError("P4 阶段实现")
EOF

make_file core/__init__.py <<'EOF'
"""核心层：Ollama 客户端封装、媒体适配、prompt 装载、输出清洗（P2 阶段）。"""
EOF

make_file core/types.py <<'EOF'
"""节点数据类型常量（P2 契约冻结）。

命名规范见 docs/02-新软件包创建流程.md §1：统一 QWE_ 前缀，
与 comfyui-ollama 的 OLLAMA_* 类型隔离，避免同装时映射冲突（NFR-03）。
"""

CONN = "QWE_OLLAMA_CONN"
OPTS = "QWE_OLLAMA_OPTS"
META = "QWE_OLLAMA_META"

CATEGORY = "Ollama/QWEnhancer"
NODE_PREFIX = "OllamaQWE"
EOF

make_file core/ollama_client.py <<'EOF'
"""Ollama 访问封装（P2 阶段实现）。

职责：
  * list_models(url) -> [{name, vision}]      # /api/tags + /api/show 能力探测（FR-02/03）
  * generate(...) / chat(...)                 # 参数映射与统一异常（FR-07, NFR-04）
  * 统一异常 OllamaUnavailable / ModelNotFound / ModelHasNoVision
"""
EOF

make_file core/media.py <<'EOF'
"""媒体适配层（P2 阶段，从 ../ComfyUI-QwenVL/py/AILab_Utils.py 抽取）。

保留：tensor_to_pil / tensor_to_base64_png / sample_video_frames /
      resolve_safe_video_max_side
丢弃：resolve_hf_model_path / resolve_base_dir / find_local_gguf_file 等本地路径逻辑（DR-07）
注意：本文件是全包唯一允许 import torch 的位置（NFR-02）。
"""
EOF

make_file core/cleaner.py <<'EOF'
"""输出清洗（P2 阶段，移植自 ../ComfyUI-QwenVL/py/AILab_OutputCleaner.py）。

保留 OutputCleanConfig 与 clean_model_output，用于剥离思考型模型的
<think>...</think> 块、代码围栏与角色前缀（FR-14）。
"""
EOF

make_file core/prompts.py <<'EOF'
"""预设 prompt 装载（P2 阶段）。

从 config/system_prompts.json 读取：
  * _preset_prompts  (9)
  * qwenvl           (9 条 VL 预设)      -> FR-04
  * qwen_text.styles (6 种增强风格)      -> FR-08
"""
EOF

make_file nodes/__init__.py <<'EOF'
"""节点模块聚合（P3 阶段）。

__init__.py 负责把各模块的 NODE_CLASS_MAPPINGS 合并到包级映射。
"""
EOF

make_file nodes/ollama_connect.py <<'EOF'
"""P3：OllamaQWEConnect / OllamaQWEOptions 两个节点。"""
EOF

make_file nodes/qwe_vl.py <<'EOF'
"""P3：OllamaQWEVL / OllamaQWEVLAdvanced。

参考实现基线：
  ../ComfyUI-QwenVL/py/AILab_QwenVL.py:870  (简易 VL)
  ../ComfyUI-QwenVL/py/AILab_QwenVL.py:908  (Advanced)
参数映射表见 docs/03-功能对等矩阵.md §2。
"""
EOF

make_file nodes/qwe_enhancer.py <<'EOF'
"""P3：OllamaQWEEnhancer。

参考实现基线：../ComfyUI-QwenVL/py/AILab_QwenVL_PromptEnhancer.py:44
"""
EOF

make_file web/js/model_list.js <<'EOF'
// P4：在连接节点上注入「🔄 刷新模型」按钮。
// 调用 POST /ollama_qwenhancer/list_models（独立路由，禁止复用 /ollama/get_models）。
import { app } from "/scripts/app.js";

app.registerExtension({
  name: "Comfy.OllamaQWEnhancer.ModelList",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "OllamaQWEConnect") return;
    // P4 阶段实现：addWidget("button", "🔄 刷新模型") + 写回 model widget 候选值
  },
});
EOF

make_file web/js/appearance.js <<'EOF'
// P4：节点配色表（按新 Node ID 重写，参照上游 ComfyUI-QwenVL/web/js/appearance.js）。
import { app } from "/scripts/app.js";

const NODE_COLORS = {
  OllamaQWEConnect: "Ollama",
  OllamaQWEOptions: "Ollama",
  OllamaQWEVL: "QwenVL",
  OllamaQWEVLAdvanced: "QwenVL",
  OllamaQWEEnhancer: "Enhancer",
};
EOF

make_file tests/test_contract_scan.sh <<'EOF'
#!/usr/bin/env bash
# G5 门控：契约与冲突扫描（对应 docs/02-新软件包创建流程.md §P5）
set -uo pipefail
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UP1="$PKG/../comfyui-ollama"
UP2="$PKG/../ComfyUI-QwenVL"
fail=0
check() { # check <名称> <命令...>
  local name="$1"; shift
  if out="$("$@" 2>&1)" && [[ -z "$out" ]]; then
    echo "PASS  $name"
  else
    echo "FAIL  $name"; [[ -n "$out" ]] && echo "$out" | sed 's/^/        /'
    fail=1
  fi
}

check "禁用依赖零命中 (AC-6)" \
  bash -c "! grep -rnE 'transformers|bitsandbytes|llama_cpp|huggingface_hub' --include=*.py '$PKG'"
check "无 GPU 直接调用 (NFR-02)" \
  bash -c "! grep -rn 'torch\.cuda' --include=*.py '$PKG'"
check "无重复 HTTP 路由 (NFR-03)" \
  bash -c "grep -rhoE 'add_(post|get)\(\"[^\"]+\"' --include=*.py '$PKG' | sort | uniq -d"
# 启发式扫描：抓取所有 'Name":' 形态的字典键（含 CLASS 与 DISPLAY 映射），
# 属上游键集合的超集，用于发现潜在撞名。
check "Node ID 不与上游冲突 (NFR-03)" \
  bash -c "
    ids(){ grep -rhoE '^\s+\"[A-Za-z_]+\":' --include=*.py \"\$1\" | tr -d ' \":' | sort -u; }
    comm -12 <(ids '$PKG') <(cat <(ids '$UP1') <(ids '$UP2') | sort -u)"

exit $fail
EOF
run "chmod +x tests/test_contract_scan.sh" chmod +x "$PKG_ROOT/tests/test_contract_scan.sh"

make_file tests/test_ollama_client.py <<'EOF'
"""G2 门控：核心层单测（离线 mock，不依赖运行中的 Ollama）。"""
import pytest


@pytest.mark.skip(reason="P2 阶段实现")
def test_list_models_flags_vision():
    ...
EOF

make_file tests/test_acceptance.md <<'EOF'
# 验收记录表（P6 / G6）

对应 `docs/01-系统需求分析.md` §11。

| AC | 判据 | 结果 | 日期 | 备注 |
| --- | --- | --- | --- | --- |
| AC-1 | 连接刷新列出模型；VL 节点仅含 vision 模型 | 待测 | | |
| AC-2 | 图像 + 预设 prompt 出非空结果 | 待测 | | |
| AC-3 | 16 帧视频 / frame_count=8 → 请求含 8 张图 | 待测 | | |
| AC-4 | temperature=0.1, seed=42 两次输出一致 | 待测 | | |
| AC-5 | 增强节点输出增强后 prompt | 待测 | | |
| AC-6 | 禁用依赖零命中 | 待测 | | 由 test_contract_scan.sh 自动判定 |
| AC-7 | 三包同装正常启动 | 待测 | | |
| AC-8 | 关闭 Ollama 后报错可读 | 待测 | | |
EOF

echo "-- 复制上游配置资产 --"
if [[ -f "$UPSTREAM_QWENVL/system_prompts.json" ]]; then
  if [[ -f "$PKG_ROOT/config/system_prompts.json" && $FORCE -eq 0 ]]; then
    echo "  [skip] config/system_prompts.json 已存在"
  elif [[ $APPLY -eq 1 ]]; then
    cp "$UPSTREAM_QWENVL/system_prompts.json" "$PKG_ROOT/config/system_prompts.json"
    echo "  [done] config/system_prompts.json  <- $UPSTREAM_QWENVL/system_prompts.json"
  else
    echo "  [plan] cp system_prompts.json -> config/"
  fi
else
  echo "  [warn] 未找到上游 system_prompts.json：$UPSTREAM_QWENVL"
fi

if [[ -f "$UPSTREAM_QWENVL/LICENSE" ]]; then
  if [[ -f "$PKG_ROOT/LICENSE" && $FORCE -eq 0 ]]; then
    echo "  [skip] LICENSE 已存在"
  elif [[ $APPLY -eq 1 ]]; then
    cp "$UPSTREAM_QWENVL/LICENSE" "$PKG_ROOT/LICENSE"
    echo "  [done] LICENSE (GPL-3.0)  <- 上游"
  else
    echo "  [plan] cp LICENSE (GPL-3.0) -> 包根"
  fi
else
  echo "  [warn] 未找到上游 LICENSE，需手工添加 GPL-3.0 全文（NFR-07）"
fi

echo
echo "== P1 完成 =="
echo "下一步 G1 验证："
echo "  1) 语法检查：python3 -c \"import ast,pathlib;[ast.parse(p.read_text(encoding='utf-8')) for p in pathlib.Path('$PKG_ROOT').rglob('*.py')];print('ok')\""
echo "  2) 重启 ComfyUI，确认加载日志无异常"
echo "  3) 然后进入 P2：core/ 契约冻结（见 docs/02-新软件包创建流程.md）"
