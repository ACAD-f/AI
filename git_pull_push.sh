#!/usr/bin/env bash
# git_pull_push.sh — GitHub 版本管理全流程演练
#
# 覆盖作业要求的五个动作，全过程输出真实 git 命令与返回：
#   1. push -u            首次推送并建立上游跟踪（origin/main）
#   2. clone              克隆一个「协作者」工作副本，模拟第二位开发者
#   3. 协作者 commit      在副本里新增演练文档并提交
#   4. push               协作者把自己的提交推回远端
#   5. pull --ff-only     主仓库以快进方式拉取，验证远端/本地一致
#
# 说明：真正的「协作者」需要另一个 GitHub 账号被邀请进仓库，本机无法自动化该邀请，
# 因此用同一账号的第二个 clone + 独立作者身份来演练全流程；提交信息里会写明这是演练。
#
# 环境变量：GIT_REMOTE（默认 origin）、GIT_BRANCH（默认 main）、
#           COLLAB_NAME / COLLAB_EMAIL（协作者身份）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

REMOTE="${GIT_REMOTE:-origin}"
BRANCH="${GIT_BRANCH:-main}"
SIM_DIR="$ROOT/.git_sim/collaborator"
COLLAB_NAME="${COLLAB_NAME:-RAG Collaborator}"
COLLAB_EMAIL="${COLLAB_EMAIL:-collaborator@users.noreply.github.com}"

GIT_TERMINAL_PROMPT=0
export GIT_TERMINAL_PROMPT

step() { printf '\n== %s ==\n' "$*"; }
fail() { printf '[失败] %s\n' "$*"; exit 1; }

step "0. 前置检查"
git --version || fail "未找到 git"
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  fail "当前目录不是 git 仓库"
fi
if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  fail "未配置远端 $REMOTE（先执行 git remote add origin <url>）"
fi
URL="$(git remote get-url "$REMOTE")"
echo "远端      : $URL"
echo "分支      : $BRANCH"
echo "当前提交  : $(git rev-parse --short HEAD)"

if [ -n "$(git status --porcelain)" ]; then
  echo "[提示] 工作区存在未提交改动，push 只推送已提交内容。"
fi

step "1. push -u $REMOTE $BRANCH（建立上游跟踪）"
git push -u "$REMOTE" "$BRANCH" || fail "push 失败：检查凭据（gh auth login）或网络"
git rev-parse --abbrev-ref --symbolic-full-name "@{u}" || true

step "2. clone 协作者工作副本 → ${SIM_DIR#$ROOT/}"
rm -rf "$SIM_DIR"
mkdir -p "$(dirname "$SIM_DIR")"
git clone "$URL" "$SIM_DIR" || fail "clone 失败"

step "3. 协作者提交"
cd "$SIM_DIR" || fail "无法进入协作者副本"
mkdir -p docs
{
  echo "# 协作者演练记录"
  echo
  echo "本文件由 \`git_pull_push.sh\` 自动生成，用于演示「第二位开发者提交 → push → 主仓库 pull」流程。"
  echo
  echo "- 生成时间：$(date -Iseconds 2>/dev/null || date)"
  echo "- 协作者身份：$COLLAB_NAME <$COLLAB_EMAIL>"
  echo "- 演练内容：新增文档 → commit → push → 主仓库 pull --ff-only"
  echo "- 说明：真实协作者需在仓库 Settings → Collaborators 中邀请；此处用独立 clone 模拟。"
} > docs/COLLABORATOR_NOTE.md
git add docs/COLLABORATOR_NOTE.md
git -c user.name="$COLLAB_NAME" -c user.email="$COLLAB_EMAIL" \
  commit -m "collab: 新增协作者演练记录（git_pull_push.sh 自动提交）" || fail "协作者 commit 失败"

step "4. 协作者 push"
git -c user.name="$COLLAB_NAME" -c user.email="$COLLAB_EMAIL" push origin "$BRANCH" || fail "协作者 push 失败"

step "5. 主仓库 pull --ff-only"
cd "$ROOT" || fail "无法返回主仓库"
git pull --ff-only "$REMOTE" "$BRANCH" || fail "pull --ff-only 失败：本地与远端分叉"

step "6. 提交历史"
git log --oneline --graph --decorate -n 10
echo
echo "--- 最近提交明细（作者 / 时间 / 主题）---"
git log --pretty='%h  %ad  %an  %s' --date=iso -n 5

step "完成：push / clone / 协作者提交 / push / pull --ff-only 全流程通过"
