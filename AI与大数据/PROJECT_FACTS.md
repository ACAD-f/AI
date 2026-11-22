# PROJECT_FACTS.md — 项目唯一事实基线（第二层反幻觉约束）

> **本文件是本项目唯一的事实基线。** 任何文档、脚本、AI 回答与它有冲突，一律以本文件为准。
> 本文件之外的事实（版本号、索引规模、检索得分、git 日志）只以 `output/` 下实测留档为准。

## 0. 使用方式

1. 回答前先读本文件，确认问题是否落在 §2「范围白名单」内；
2. 在范围内的问题，走 `python rag/rag_github.py answer "<问题>"` 检索取证；
3. 检索无命中时，使用 §4 的拒答模板，**逐字**输出，不得改写、不得补猜测；
4. 需要新增事实时，只改本文件并提交，然后重跑 `bash scripts/run_all.sh` 让留档同步。

## 1. 事实基线

| 项 | 值 |
| --- | --- |
| 项目名 | `ai_bigdata_rag_agent`（课程作业：AI 与大数据 RAG Agent） |
| 仓库 | `ACAD-f/AI`（GitHub 公开仓库，默认分支 `main`） |
| 本地根目录 | `ai_bigdata_rag_agent/` |
| 语料源 | `deepseek-ai/deepseek-harness`，ref = `master`（只取文档，不取源码） |
| 语料快照 | `rag/corpus/github_snapshot/`（6 个文件）+ `rag/corpus/manifest.json` |
| 检索引擎 | 纯标准库 BM25（k1=1.5, b=0.75），索引落盘 `rag/corpus/index.json` |
| 业务入口 | `rag/rag_github.py`（子命令：`ingest` / `index` / `query` / `answer` / `stats`） |
| Python 路由 | `scripts/conda_run.sh` → `conda run -n test python`（无 conda 时回退本地 `python3`/`python`） |
| 一键复现 | `bash scripts/run_all.sh` → `output/FINAL_RESULT.md` |
| 版本管理演练 | `git_pull_push.sh`（push -u → clone → 协作者 commit → push → pull --ff-only） |
| 许可证 | MIT（见仓库根 `LICENSE`，版权人 `ACAD-f`） |
| 环境最低要求 | Python ≥ 3.10、git ≥ 2.34、可访问 `raw.githubusercontent.com` |

> 实测版本、索引文件数 / 切片数 / 词项数、检索得分、提交哈希等**易变事实**，
> 一律记录在 `output/environment.txt`、`output/rag_stats.txt`、`output/git_log.txt`，
> 汇总于 `output/FINAL_RESULT.md`。引用这些数字时必须同时给出对应文件。

## 2. 范围白名单（可以回答的主题）

只有下列主题在回答范围内，且必须有语料证据支撑：

| 编号 | 主题 | 主要证据来源 |
| --- | --- | --- |
| W1 | DeepSeek Harness 是什么、整体目标与定位 | `github_snapshot/README.md`、`README.zh.md` |
| W2 | 总体架构：微内核、服务、插件、分层 | `docs__architecture.md`、`docs__architecture.zh.md` |
| W3 | 术语含义（service / plugin / fiber / effect / tool 等） | `docs__glossary.md`、`docs__glossary.zh.md` |
| W4 | 本项目自身的结构、命令、约束、许可证 | `agent.md`、本文件、`README.md`、`docs/GITHUB_ACCOUNT.md` |
| W5 | RAG 管线如何抓取、切片、建索引、检索、拒答 | 本文件 §1、`README.md`、`rag/rag_github.py` 的 docstring |

**范围外**（不在白名单 → 必须拒答）：与本项目无关的通用知识、时事、其他代码库的内部实现、
deepseek-harness 未在快照中出现的细节、对未来行为的预测、对个人信息的推断。

## 3. 禁止事项

1. 禁止脱离语料与 `output/` 留档，凭模型记忆陈述项目事实；
2. 禁止编造文件路径、行号、commit 哈希、命令行参数、API 字段；
3. 禁止把「未收录进快照的内容」说成「文档里写了」；
4. 禁止在拒答场景下给「可能 / 大概 / 一般情况」式兜底答案；
5. 禁止用 `README.md` 或其他 md 覆盖本文件的事实优先级；
6. 禁止把索引统计、检索得分等易变数字写死在本文件里（它们属于 §1 表格下方的「易变事实」）。

## 4. 拒答模板

检索无命中、得分低于阈值或问题超出 §2 白名单时，逐字输出下列模板（脚本 `answer`
子命令会直接读取这里的文本，保证与事实基线同源）：

<!-- REFUSAL_TEMPLATE_START -->
【拒绝回答】该问题不在本项目的事实基线与语料范围内。

- 事实基线：`AI与大数据/PROJECT_FACTS.md`（范围白名单 §2）
- 语料范围：`deepseek-ai/deepseek-harness` 的 6 个文档快照（见 `rag/corpus/manifest.json`）
- 检索结果：无命中，或最高得分低于阈值

为避免编造，我不提供推测性答案。你可以：
1. 换用与 DeepSeek Harness 架构 / 术语 / 本项目命令相关的问法；
2. 先执行 `python rag/rag_github.py query "<关键词>"` 查看是否有可引用的证据；
3. 若要新增该主题，请先在 `PROJECT_FACTS.md` §2 扩充白名单并提交。
<!-- REFUSAL_TEMPLATE_END -->

## 5. 事实更新流程

```text
发现需要新增/修正的事实
  → 只改本文件（PROJECT_FACTS.md）对应条目并写明依据
  → 若涉及语料：改 rag/rag_github.py 的 SOURCES 并执行 ingest
  → bash scripts/run_all.sh 重跑，刷新 output/ 留档
  → git commit（提交信息说明改了什么事实、依据是什么）
```
