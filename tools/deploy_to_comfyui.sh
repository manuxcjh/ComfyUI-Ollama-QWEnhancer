#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 部署本包到 ComfyUI 的 custom_nodes 目录
#
# 背景：<ComfyUI> 所在文件系统当前以 **只读** 方式挂载
#       （findmnt: /dev/nvme0n1p3 xfs ro,nosuid,nodev），
#       因此本脚本无法直接写入，会给出明确的处理指引。
#
# 用法：
#   bash tools/deploy_to_comfyui.sh                 # 检查并给出指引（默认）
#   bash tools/deploy_to_comfyui.sh --copy          # 可写时执行复制
#   bash tools/deploy_to_comfyui.sh --link          # 可写时建立符号链接
#   COMFY_CUSTOM_NODES=/path/to/custom_nodes bash tools/deploy_to_comfyui.sh --copy
# ---------------------------------------------------------------------------
set -uo pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_NAME="$(basename "$PKG_ROOT")"
# ComfyUI 根目录：COMFY_ROOT 环境变量 > config/local.json 的 "comfyui_root"
_local_cfg="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/config/local.json"
_cfg_get() {
  [[ -f "$_local_cfg" ]] || return 0
  python3 -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get(sys.argv[2]) or '')" "$_local_cfg" "$1" 2>/dev/null || true
}
COMFY_ROOT="${COMFY_ROOT:-$(_cfg_get comfyui_root)}"
COMFY_ROOT="${COMFY_ROOT:-/path/to/ComfyUI}"
TARGET_DIR="${COMFY_CUSTOM_NODES:-$COMFY_ROOT/custom_nodes}"
DEST="$TARGET_DIR/$PKG_NAME"

MODE="check"
for arg in "$@"; do
  case "$arg" in
    --copy) MODE="copy" ;;
    --link) MODE="link" ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

echo "== 部署 $PKG_NAME =="
echo "源目录  : $PKG_ROOT"
echo "目标    : $DEST"
echo

# --- 1. 目标目录是否存在 -----------------------------------------------------
if [[ ! -d "$TARGET_DIR" ]]; then
  echo "❌ 未找到 custom_nodes 目录：$TARGET_DIR"
  echo "   请用 COMFY_CUSTOM_NODES=<路径> 指定，或确认 ComfyUI 安装位置。"
  exit 1
fi

# --- 2. 可写性检查 ----------------------------------------------------------
if touch "$TARGET_DIR/.qwe_write_test" 2>/dev/null; then
  rm -f "$TARGET_DIR/.qwe_write_test"
  WRITABLE=1
  echo "✅ custom_nodes 可写"
else
  WRITABLE=0
  echo "❌ custom_nodes 不可写"
fi

if [[ $WRITABLE -eq 0 ]]; then
  echo
  echo "---- 原因与处理办法 ----"
  findmnt -T "$TARGET_DIR" 2>/dev/null | sed 's/^/  /' || true
  cat <<'EOF'

  若上面显示挂载选项含 `ro`，说明文件系统是只读挂载。三选一：

  1) 临时改为读写（需 sudo，重启后失效）
       sudo mount -o remount,rw /NVME

  2) 直接复制到可写位置后软链（若 ComfyUI 支持在别处放插件）
       cp -r <本包> <workdir>/custom_nodes/
       ln -s <本包路径> <ComfyUI>/custom_nodes/
     —— 仍需目标可写，故仅在第 1 步之后可行。

  3) 由有权限的用户手工复制：
       cp -r <本包路径> <ComfyUI>/custom_nodes/

  复制完成后重启 ComfyUI，日志中应出现：
     [ComfyUI-Ollama-QWEnhancer] v0.1.0 | 4 nodes Loaded
     [OllamaQWEnhancer] 已注册模型列表路由 POST /ollama_qwenhancer/list_models
EOF
  exit 1
fi

# --- 3. 执行部署 ------------------------------------------------------------
# 排除开发期产物，避免污染运行环境
EXCLUDES=(--exclude='__pycache__' --exclude='*.pyc' --exclude='.git')

case "$MODE" in
  check)
    echo
    echo "（默认 check 模式，未做改动）"
    echo "如需部署，请加 --copy 或 --link 重新执行。"
    ;;
  copy)
    mkdir -p "$DEST"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --delete "${EXCLUDES[@]}" "$PKG_ROOT/" "$DEST/"
    else
      rm -rf "$DEST"; mkdir -p "$DEST"
      cp -r "$PKG_ROOT/." "$DEST/"
      find "$DEST" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    fi
    echo "✅ 已复制到 $DEST"
    ;;
  link)
    if [[ -e "$DEST" || -L "$DEST" ]]; then
      echo "⚠️  目标已存在，先移除：$DEST"
      rm -rf "$DEST"
    fi
    ln -s "$PKG_ROOT" "$DEST"
    echo "✅ 已建立符号链接：$DEST -> $PKG_ROOT"
    ;;
esac

# --- 4. 依赖与重启提示 ------------------------------------------------------
echo
echo "---- 后续步骤 ----"
VENV_PY="${QWE_PYTHON:-$(_cfg_get python)}"
if [[ -x "$VENV_PY" ]]; then
  echo "1) 安装运行期依赖（本包只需 ollama 客户端）："
  echo "     $VENV_PY -m pip install -r '$DEST/requirements.txt'"
else
  echo "1) 在 ComfyUI 的 venv 中执行： pip install -r requirements.txt"
fi
echo "2) 重启 ComfyUI"
echo "3) 检查启动日志是否出现 '[ComfyUI-Ollama-QWEnhancer] ... 4 nodes Loaded'"
echo "4) 在画布中右键 → Ollama/QWEnhancer，可看到 4 个节点"
