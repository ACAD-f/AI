#!/usr/bin/env bash
# conda_run.sh — 业务 Python 统一路由
#
# 目标环境：conda 的 `test` 虚拟环境（Python 3.10+），等价于：
#     conda run -n test python "$@"
#
# 路由顺序（逐级回退，并在 stderr 说明用哪一级）：
#   1. PYTHON_BIN                显式指定的解释器（CI / 特殊机器用）
#   2. conda run -n test         有 conda 且存在 test 环境
#   3. python3 / python / py -3  本地解释器（含 Git Bash、Store 版 Python 的甄别）
#
# 为什么要「探测解释器能不能跑」：Windows 自带的
# C:\Users\<name>\AppData\Local\Microsoft\WindowsApps\python.exe 只是应用商店占位符，
# 一执行就退出 9009 且无输出，必须在探测阶段排除，否则整条管线会静默拿到空结果。
#
# 环境变量：
#   CONDA_ENV_NAME   环境名（默认 test）
#   PYTHON_BIN       强制指定解释器路径
#   CONDA_RUN_TRACE  设为 1 时把实际路由打印到 stderr，便于留档
set -uo pipefail

ENV_NAME="${CONDA_ENV_NAME:-test}"
TRACE="${CONDA_RUN_TRACE:-0}"

trace() {
  if [ "$TRACE" = "1" ]; then
    printf '[conda_run] %s\n' "$*" >&2
  fi
}

if [ "$#" -eq 0 ]; then
  echo "用法: conda_run.sh <python 参数...>" >&2
  exit 64
fi

# 解释器是否真的能执行（排除 WindowsApps 占位符与坏掉的 shim）
works() {
  local out
  out=$("$@" -c 'print("py-ok")' 2>/dev/null) || return 1
  [ "$out" = "py-ok" ]
}

# 定位 conda：PATH 优先，其次常见安装目录（未加入 PATH 时也能用）
find_conda() {
  if command -v conda >/dev/null 2>&1; then
    command -v conda
    return 0
  fi
  local candidate
  for candidate in \
    "$HOME/miniconda3/Scripts/conda.exe" \
    "$HOME/anaconda3/Scripts/conda.exe" \
    "$HOME/AppData/Local/miniconda3/Scripts/conda.exe" \
    "/c/ProgramData/miniconda3/Scripts/conda.exe" \
    "/c/ProgramData/anaconda3/Scripts/conda.exe" \
    "$HOME/miniconda3/bin/conda" \
    "$HOME/anaconda3/bin/conda" \
    "/opt/conda/bin/conda"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

# 1. 显式指定的解释器
if [ -n "${PYTHON_BIN:-}" ]; then
  if works "$PYTHON_BIN"; then
    trace "使用 PYTHON_BIN=$PYTHON_BIN"
    exec "$PYTHON_BIN" "$@"
  fi
  trace "PYTHON_BIN=$PYTHON_BIN 不可用，继续回退"
fi

# 2. conda test 环境
if CONDA_BIN="$(find_conda)"; then
  if "$CONDA_BIN" env list 2>/dev/null | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    trace "路由到 conda 环境 $ENV_NAME（$CONDA_BIN）"
    exec "$CONDA_BIN" run -n "$ENV_NAME" --no-capture-output python "$@"
  fi
  trace "找到 conda 但缺少环境 $ENV_NAME，回退本地解释器"
else
  trace "未找到 conda，回退本地解释器"
fi

# 3. 本地解释器
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && works "$candidate"; then
    trace "回退本地解释器 $candidate"
    exec "$candidate" "$@"
  fi
done

if command -v py >/dev/null 2>&1 && works py -3; then
  trace "回退 Windows py 启动器（py -3）"
  exec py -3 "$@"
fi

echo "错误：未找到可用的 Python（conda 环境 $ENV_NAME / python3 / python / py -3 均不可用）" >&2
exit 127
