# GITHUB_ACCOUNT.md — GitHub 账号申请、git 安装配置与远端协作

本文件是作业第 ③ 项（账号 / git / pull-push / LICENSE）的操作说明，共 8 节。
文中涉及「本机实际状态」的部分，以本机实测为准（见 `output/environment.txt`、`output/git_log.txt`）。

---

## 1. 注册 GitHub 账号

1. 打开 <https://github.com/signup>；
2. 依次填写：邮箱 → 密码（≥ 15 位或 ≥ 8 位含数字与字母）→ 用户名 → 邮箱验证码；
3. 用户名一旦确定会进入所有仓库 URL（本仓库使用的是 `ACAD-f`），建议用「姓名单词 + 数字」；
4. 注册完成后在 <https://github.com/settings/profile> 填写 Name（会出现在提交记录里）。

## 2. 开启两步验证（2FA，强制）

GitHub 自 2023 年起要求所有贡献代码的账号启用 2FA，未开启会在 push 时被拒绝。

1. <https://github.com/settings/security> → **Two-factor authentication** → Enable；
2. 推荐 Authenticator app（Microsoft Authenticator / Google Authenticator / 1Password）；
3. 保存 10 个恢复码（Recovery codes）到离线位置，丢失将无法登录；
4. 开启后，HTTPS push 需要 **Personal Access Token** 或 **GitHub CLI 登录**，不能用账号密码。

## 3. 创建远程仓库

1. <https://github.com/new>；
2. Repository name：`AI`；Visibility：**Public**（作业要求公开仓库）；
3. **不要**勾选 "Add a README file"（本地已有内容，避免首次 push 冲突）；
4. Create repository 后记下地址：`https://github.com/ACAD-f/AI.git`。

## 4. 安装并配置 git

### 4.1 安装

- Windows：<https://git-scm.com/download/win>（安装时选 "Git from the command line and also from 3rd-party software"）；
- 安装后把 `C:\Program Files\Git\cmd` 加入 PATH，或直接用 "Git Bash"；
- 验证：`git --version`（作业环境要求 ≥ 2.34）。

### 4.2 身份配置（写进提交记录，必须与 GitHub 账号邮箱一致）

```bash
git config --global user.name  "ACAD-f"
git config --global user.email "3514615196@qq.com"
git config --global init.defaultBranch main
git config --global core.quotepath false     # 中文文件名不被转义
```

### 4.3 凭据配置（HTTPS 方式，二选一）

**方式 A：GitHub CLI（推荐，省去手工填 token）**

```bash
winget install --id GitHub.cli          # 或 https://cli.github.com/
gh auth login                           # 选 GitHub.com → HTTPS → Login with a web browser
gh auth status                          # 应显示 Logged in to github.com account ACAD-f
git config --global credential.https://github.com.helper ""
git config --global --add credential.https://github.com.helper "!gh auth git-credential"
```

**方式 B：Personal Access Token**

1. <https://github.com/settings/tokens> → Generate new token (classic) → 勾选 `repo`、`read:org`；
2. 复制 token（只显示一次），push 时用户名填 GitHub 用户名、密码填 token；
3. 或用凭据管理器缓存：`git config --global credential.helper manager`。

> 本机实际采用方式 A：`gh auth status` 显示 keyring 登录，token scopes 为 `gist, read:org, repo`。

## 5. 关联远端并完成 pull / push

```bash
git init                                   # 若目录尚未初始化
git add -A
git commit -m "feat: RAG Agent 初始提交"
git remote add origin https://github.com/ACAD-f/AI.git
git branch -M main
git push -u origin main                    # 首次推送：-u 建立上游跟踪
git remote -v                              # 核验 origin 指向
```

日常协作：

```bash
git pull --ff-only origin main             # 只允许快进，避免产生意外合并提交
git status                                 # 提交前确认改动范围
git log --oneline --graph -n 10            # 查看历史
```

## 6. 邀请协作者（作业中的「协作者 commit」环节）

1. 仓库 → **Settings → Collaborators → Add people**；
2. 输入对方 GitHub 用户名或邮箱，选择权限（Write 即可 push）；
3. 对方接受邀请邮件后即可 `git clone` 并 push。

> 本机无法自动完成「邀请另一个真实账号」，因此 `git_pull_push.sh` 用**同一账号的第二个 clone**
> 加独立作者身份（`RAG Collaborator <collaborator@users.noreply.github.com>`）来演练
> clone → commit → push → 主仓库 `pull --ff-only` 的完整链路，提交信息中已注明这是演练。

## 7. 本次演练涉及的 git 命令清单

| 步骤 | 命令 | 作用 |
| --- | --- | --- |
| 1 | `git push -u origin main` | 首次推送并建立上游跟踪 |
| 2 | `git clone <url> .git_sim/collaborator` | 模拟第二位开发者克隆 |
| 3 | `git add` + `git commit -m ...` | 协作者提交新增文档 |
| 4 | `git push origin main` | 协作者推送 |
| 5 | `git pull --ff-only origin main` | 主仓库快进拉取，验证一致 |
| 6 | `git log --oneline --graph --decorate` | 留存提交历史 |

以上命令的真实输出保存在 `output/git_log.txt`。

## 8. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Support for password authentication was removed` | 用了账号密码 | 改用 PAT 或 `gh auth login` |
| `remote: Permission to ... denied to ...` | 无写权限 / 未接受邀请 | 检查 Collaborators 与 `gh auth status` |
| `! [rejected] main -> main (fetch first)` | 远端有新提交 | 先 `git pull --ff-only`，再 push |
| `fatal: not a git repository` | 目录未初始化 | `git init` 或切到仓库根目录 |
| `schannel: AcquireCredentialsHandle failed` | 受限环境里 TLS 后端异常 | `git -c http.sslBackend=openssl <cmd>` |
| 中文文件名显示为 `\344\270\255` | 未关闭 quotepath | `git config --global core.quotepath false` |

## 9. 许可证

仓库采用 **MIT**（见根目录 [`LICENSE`](../LICENSE)），版权人 `ACAD-f`，年份 2026。
选择 MIT 的理由：允许他人自由使用、修改、分发，只需保留版权声明，最贴合课程作业的分享场景。
