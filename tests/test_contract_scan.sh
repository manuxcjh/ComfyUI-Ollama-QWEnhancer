#!/usr/bin/env bash
# G5 门控：契约与冲突扫描（对应 docs/02-新软件包创建流程.md §P5）
#
# 用法：bash tests/test_contract_scan.sh
set -uo pipefail

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${QWE_PYTHON:-python3}"
fail=0

check() { # check <名称> <命令...>
  local name="$1"; shift
  local out
  if out="$("$@" 2>&1)" && [[ -z "$out" ]]; then
    echo "PASS  $name"
  else
    echo "FAIL  $name"
    [[ -n "$out" ]] && echo "$out" | sed 's/^/        /'
    fail=1
  fi
}

echo "== G5 契约扫描 =="

# AC-6：本包不得引入本地推理 / 模型下载依赖
check "禁用依赖零命中 (AC-6)" \
  bash -c "! grep -rnE 'transformers|bitsandbytes|llama_cpp|huggingface_hub' --include=*.py '$PKG'"

# NFR-02：不得出现 CUDA 设备调用
check "无 CUDA 直接调用 (NFR-02)" \
  bash -c "! grep -rn 'torch\.cuda' --include=*.py '$PKG'"

# NFR-01：运行期依赖只允许 ollama（torch/numpy/PIL/aiohttp 由 ComfyUI 宿主提供）
check "requirements 仅含 ollama (NFR-01)" \
  bash -c "{ grep -vE '^\s*(#|\$)' '$PKG/requirements.txt' | grep -vE '^ollama' || true; }"

# NFR-03：Node ID / HTTP 路由 / 数据类型 与上游无冲突。
# 用 AST 精确提取映射键——早期的 grep 版本会把 widget 名（model/seed/…）
# 误判为冲突，已废弃。
echo "--- 命名空间冲突（AST 精确检查）---"
if "$PY" "$PKG/tests/check_conflicts.py" --quiet; then
  echo "PASS  Node ID / 路由 / 数据类型 无冲突 (NFR-03)"
else
  echo "FAIL  Node ID / 路由 / 数据类型 无冲突 (NFR-03)"
  fail=1
fi

echo
if [[ $fail -eq 0 ]]; then
  echo "G5 全部通过"
else
  echo "G5 存在失败项"
fi
exit $fail
