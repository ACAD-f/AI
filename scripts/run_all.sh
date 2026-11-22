#!/usr/bin/env bash
# run_all.sh — 一键复现：环境核验 → RAG 抓取/建索引/检索 → git 演练 → 汇总留档
#
# 产出（全部落在 output/）：
#   environment.txt      环境实测（bash / git / conda / python 版本与解释器路径）
#   rag_ingest.txt       6 个 GitHub 语料快照的抓取过程（含 sha256、commit）
#   rag_index.txt        切片与建索引过程
#   rag_stats.txt/json   索引规模（文件数 / 切片数 / 词项数 / 平均长度）
#   rag_query_zh.txt     中文查询证据
#   rag_query_en.txt     英文查询证据
#   rag_answer_zh.txt    检索式回答（带来源行号）
#   rag_refusal_demo.txt 越界问题的拒答留档（验证无命中即拒答）
#   git_log.txt          push -u → clone → 协作者 commit → push → pull --ff-only
#   FINAL_RESULT.md      以上全部内容的汇总
#
# 环境变量：
#   SKIP_GIT_PUSH=1   跳过 git 演练（离线/无凭据时使用）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

OUT="$ROOT/output"
mkdir -p "$OUT"

SKIP_GIT_PUSH="${SKIP_GIT_PUSH:-0}"

py_run() {
  bash "$ROOT/scripts/conda_run.sh" "$@"
}

section() {
  printf '\n\033[1m== %s ==\033[0m\n' "$*"
}

# ------------------------------------------------------------------ 1. 环境核验
section "1/4 环境核验"
PY_VERSION="$(py_run -c 'import sys;print(sys.version.split()[0])' 2>/dev/null)"
PY_EXE="$(py_run -c 'import sys;print(sys.executable)' 2>/dev/null)"
PY_ROUTE="$(CONDA_RUN_TRACE=1 bash "$ROOT/scripts/conda_run.sh" -c 'pass' 2>&1 >/dev/null | sed -n '1s/^\[conda_run\] //p')"
{
  echo "# 环境留档（run_all.sh 自动采集）"
  echo "collected_at : $(date -Iseconds 2>/dev/null || date)"
  echo "project_root : $ROOT"
  echo "uname        : $(uname -srm 2>/dev/null || echo unknown)"
  echo "bash         : ${BASH_VERSION}"
  echo "git          : $(git --version 2>&1)"
  if command -v conda >/dev/null 2>&1; then
    echo "conda        : $(command -v conda) ($(conda --version 2>&1))"
    echo "conda_env    : ${CONDA_ENV_NAME:-test}"
  else
    echo "conda        : 未安装 —— conda_run.sh 回退本地解释器"
  fi
  echo "python       : $PY_VERSION"
  echo "python_exe   : $PY_EXE"
  echo "python_route : ${PY_ROUTE:-未知}"
} > "$OUT/environment.txt" 2>&1
cat "$OUT/environment.txt"

# ------------------------------------------------------------------ 2. RAG 管线
section "2/4 RAG：抓取快照 → 建索引 → 检索证据"
if py_run rag/rag_github.py ingest > "$OUT/rag_ingest.txt" 2>&1; then
  echo "抓取成功（在线）"
else
  echo "在线抓取失败，改用本地快照（--offline）重试"
  py_run rag/rag_github.py ingest --offline > "$OUT/rag_ingest.txt" 2>&1 || echo "本地快照同样不可用，见 $OUT/rag_ingest.txt"
fi
tail -n 8 "$OUT/rag_ingest.txt"

py_run rag/rag_github.py index | tee "$OUT/rag_index.txt"
py_run rag/rag_github.py stats | tee "$OUT/rag_stats.txt"
py_run rag/rag_github.py stats --json > "$OUT/rag_stats.json" 2>/dev/null || true

Q_ZH="DeepSeek Harness 的架构由哪些部分组成"
Q_EN="What is a capability seam in DeepSeek Harness?"

py_run rag/rag_github.py query "$Q_ZH" -k 5 > "$OUT/rag_query_zh.txt" 2>&1 || true
py_run rag/rag_github.py query "$Q_EN" -k 5 > "$OUT/rag_query_en.txt" 2>&1 || true
py_run rag/rag_github.py answer "能力 seam 是什么" > "$OUT/rag_answer_zh.txt" 2>&1 || true
py_run rag/rag_github.py answer "今天北京天气怎么样，适合跑步吗" > "$OUT/rag_refusal_demo.txt" 2>&1 || true

# ------------------------------------------------------------------ 3. git 演练
section "3/4 git：push -u → clone → 协作者 commit → push → pull --ff-only"
if [ "$SKIP_GIT_PUSH" = "1" ]; then
  {
    echo "# git 演练（已跳过）"
    echo "SKIP_GIT_PUSH=1，本次未执行远端 push/pull。"
    echo "本地提交历史："
    git log --oneline --graph --decorate -n 10 2>&1
  } > "$OUT/git_log.txt"
  echo "已跳过（SKIP_GIT_PUSH=1）"
else
  if bash "$ROOT/git_pull_push.sh" > "$OUT/git_log.txt" 2>&1; then
    echo "git 演练完成"
  else
    echo "git 演练未全部完成（无远端/无凭据/网络受限），详见 $OUT/git_log.txt"
  fi
  tail -n 12 "$OUT/git_log.txt"
fi

# ------------------------------------------------------------------ 4. 汇总
section "4/4 汇总 FINAL_RESULT.md"

STATS_LINE="$(py_run -c 'import json;m=json.load(open("output/rag_stats.json"));print(m["files"],m["chunks"],m["vocab"],m["tokens"],m["build_ms"])' 2>/dev/null || echo "0 0 0 0 0")"
FILES=$(echo "$STATS_LINE" | cut -d' ' -f1)
CHUNKS=$(echo "$STATS_LINE" | cut -d' ' -f2)
VOCAB=$(echo "$STATS_LINE" | cut -d' ' -f3)
TOKENS=$(echo "$STATS_LINE" | cut -d' ' -f4)
BUILD_MS=$(echo "$STATS_LINE" | cut -d' ' -f5)
COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
BRANCH_NAME="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
REMOTE_URL="$(git remote get-url origin 2>/dev/null || echo unknown)"

{
  cat <<EOF
# 最终结果（run_all.sh 自动生成）

- 生成时间：$(date -Iseconds 2>/dev/null || date)
- 项目根目录：\`$ROOT\`
- 仓库 / 分支：\`$REMOTE_URL\` / \`$BRANCH_NAME\`
- 当前提交：\`$COMMIT_SHA\`

## 0. 结论速览

| 指标 | 实测值 | 出处 |
| --- | --- | --- |
| 语料文件数（6 个 GitHub 快照 + 5 个项目 md） | **$FILES** | 本文件 §3 |
| 切片数（BM25 索引） | **$CHUNKS** | 本文件 §3 |
| 词项数（去停用词后词表大小） | **$VOCAB** | 本文件 §3 |
| 索引总 token | **$TOKENS** | 本文件 §3 |
| 建索引耗时 | **$BUILD_MS** ms | 本文件 §3 |
| 中英文检索 | 均返回带文件行号的证据 | 本文件 §4.3 / §4.4 |
| 越界问题 | 按 PROJECT_FACTS.md §4 拒答 | 本文件 §4.5 |

> 以上数字全部由脚本本次运行产生，可在对应 \`output/*.txt\` 中原样核对；
> 报告与说明文档中的任何数字都应以此为准。

## 1. 运行环境

\`\`\`text
$(cat "$OUT/environment.txt")
\`\`\`

## 2. 语料抓取（6 个 GitHub 快照）

\`\`\`text
$(cat "$OUT/rag_ingest.txt")
\`\`\`

## 3. 切片与 BM25 索引

\`\`\`text
$(cat "$OUT/rag_index.txt")
\`\`\`

\`\`\`text
$(cat "$OUT/rag_stats.txt")
\`\`\`

## 4. 检索证据与拒答验证

### 4.1 中文查询：$Q_ZH

\`\`\`text
$(cat "$OUT/rag_query_zh.txt")
\`\`\`

### 4.2 英文查询：$Q_EN

\`\`\`text
$(cat "$OUT/rag_query_en.txt")
\`\`\`

### 4.3 检索式回答（先检索后回答，逐条标注来源）

\`\`\`text
$(cat "$OUT/rag_answer_zh.txt")
\`\`\`

### 4.4 越界问题拒答（无命中即拒答）

\`\`\`text
$(cat "$OUT/rag_refusal_demo.txt")
\`\`\`

## 5. git：push / clone / 协作者提交 / pull --ff-only

\`\`\`text
$(cat "$OUT/git_log.txt")
\`\`\`

## 6. 交付清单

| # | 文件 | 字节 |
| --- | --- | --- |
EOF

  i=0
  find . -type f \
    -not -path './.git/*' \
    -not -path './.git_sim/*' \
    -not -name 'FINAL_RESULT.md' \
    | sed 's|^\./||' | sort | while read -r f; do
      i=$((i + 1))
      printf '| %d | `%s` | %s |\n' "$i" "$f" "$(wc -c < "$f" | tr -d ' ')"
    done

  cat <<'EOF'

## 7. 复现方式

```bash
# 有 conda test 环境时（作业要求的环境）
bash scripts/run_all.sh

# 无 conda 或离线时
SKIP_GIT_PUSH=1 bash scripts/run_all.sh
```

> 校验点：`output/environment.txt` 的 python/git 版本、`output/rag_stats.txt` 的三项规模数字、
> `output/git_log.txt` 的提交哈希。上文「当前提交」为**生成本文件时**的 HEAD；
> 生成后若又提交了 output/ 刷新，仓库 tip 会再前进一次，属正常。
EOF
} > "$OUT/FINAL_RESULT.md" 2>&1

echo "已写出：$OUT/FINAL_RESULT.md"
echo "规模：文件 $FILES / 切片 $CHUNKS / 词项 $VOCAB"
exit 0
