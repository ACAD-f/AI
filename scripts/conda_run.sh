#!/usr/bin/env bash
# conda_run.sh — 业务 Python 统一路由
#
# 目标环境：conda 的 `test` 虚拟环境（Python 3.10+），等价于：
#     conda run -n test python "$@"
#
# 兼容策略：
#   1. 有 conda 且存在 test 环境          → conda run -n test --no-capture-output python
#   2. 有 conda 但没有 test 环境          → 回退当前 python，并在 stderr 提示
#   3. 没有 conda（如纯 Windows/Git Bash）→ 回退 python3 / python
#
# 可用环境变量：
#   CONDA_ENV_NAME   指定环境名（默认 test）
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

if command -v conda >/dev/null 2>&1; then
  if conda env list 2>/dev/null | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    trace "路由到 conda 环境 $ENV_NAME"
    exec conda run -n "$ENV_NAME" --no-capture-output python "$@"
  fi
  trace "conda 存在但缺少环境 $ENV_NAME，回退本地 python"
fi

for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    trace "回退本地解释器 $candidate"
    exec "$candidate" "$@"
  fi
done

echo "错误：未找到 conda 环境 $ENV_NAME，也未找到 python3/python" >&2
exit 127
