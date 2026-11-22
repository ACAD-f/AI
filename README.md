# AI与大数据 · RAG Agent（GitHub 语料 → BM25 检索 → 带引用的回答）

> 课程作业：在 `conda test` 环境与 DeepSeek Harness 驱动下，用 Python 实现一个**以 GitHub 为语料源**
> 的 RAG Agent，并用「双层反幻觉约束」把「不许编造」落成可检查的文件、脚本与日志。

[![repo](https://img.shields.io/badge/GitHub-ACAD--f%2FAI-181717?logo=github)](https://github.com/ACAD-f/AI)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![python](https://img.shields.io/badge/python-%E2%89%A53.10-3776AB?logo=python)](requirements.txt)

---

## 1. 这个仓库做了什么

| 作业要求 | 本仓库的落点 | 怎么核验 |
| --- | --- | --- |
| ① 根目录 `agent.md` + 「AI与大数据」文件夹 + `*.md` 限定项目信息 | [`agent.md`](agent.md)、[`AI与大数据/PROJECT_FACTS.md`](AI与大数据/PROJECT_FACTS.md)、[`AI与大数据/README.md`](AI与大数据/README.md) | 阅读两份约束文件；`agent.md` 管行为，`PROJECT_FACTS.md` 管内容 |
| ② 以 GitHub 为语料源，Python 脚本实现 RAG（`*.py`） | [`rag/rag_github.py`](rag/rag_github.py)：抓取 6 个 `deepseek-ai/deepseek-harness` 文档快照 → BM25 索引 → 中英文检索 → 抽取式回答 | `output/rag_ingest.txt`、`output/rag_stats.txt`、`output/rag_query_*.txt` |
| ③ GitHub 账号说明、git 安装配置、pull/push、LICENSE | [`docs/GITHUB_ACCOUNT.md`](docs/GITHUB_ACCOUNT.md)、[`git_pull_push.sh`](git_pull_push.sh)、[`LICENSE`](LICENSE) | `output/git_log.txt` 里的真实提交历史 |
| 输出最终结果 | [`output/FINAL_RESULT.md`](output/FINAL_RESULT.md) | 环境、索引规模、检索证据、git 日志、交付清单全在一个文件里 |

## 2. 目录结构

```text
ai_bigdata_rag_agent/
├── agent.md                     # 第一层约束：AI 行为契约（先检索后回答 / 单一事实源 / 无命中即拒答）
├── AI与大数据/
│   ├── PROJECT_FACTS.md         # 第二层约束：唯一事实基线（范围白名单 / 禁止事项 / 拒答模板）
│   └── README.md                # 知识边界说明：两层约束如何落地
├── rag/
│   ├── rag_github.py            # RAG 主程序：ingest / index / query / answer / stats
│   └── corpus/
│       ├── github_snapshot/     # 6 个 GitHub 文档快照（原文落盘，可 diff）
│       ├── manifest.json        # 仓库、ref、commit、sha256、字节数、抓取通道与时间
│       └── index.json           # BM25 倒排索引（词项 → 切片 tf，含 idf）
├── scripts/
│   ├── conda_run.sh             # 业务 Python 路由：conda run -n test python（无 conda 时回退）
│   └── run_all.sh               # 一键复现 → output/FINAL_RESULT.md
├── docs/
│   └── GITHUB_ACCOUNT.md        # 账号注册、2FA、远端配置、凭据、协作者邀请
├── git_pull_push.sh             # push -u → clone → 协作者 commit → push → pull --ff-only
├── output/                      # 每次运行的真实留档（随提交入库，便于核对）
├── LICENSE                      # MIT
└── requirements.txt             # 仅标准库，无第三方依赖
```

## 3. 快速开始

```bash
# 推荐：作业要求的 conda test 环境（Python 3.10+）
bash scripts/run_all.sh

# 没有 conda / 离线（使用仓库内已有快照，跳过远端 push）
SKIP_GIT_PUSH=1 bash scripts/run_all.sh
```

单步使用：

```bash
python rag/rag_github.py ingest            # 抓取 6 个快照（api.github.com 优先，raw 兜底）
python rag/rag_github.py index             # 切片 + BM25 索引
python rag/rag_github.py query "能力 seam 是什么" -k 5
python rag/rag_github.py answer "What is a capability seam?"   # 无命中自动拒答
python rag/rag_github.py stats --json
```

> 业务 Python 一律经 `scripts/conda_run.sh` 路由，脚本内部会优先
> `conda run -n test --no-capture-output python`，找不到 conda 时回退本地 `python3`/`python`，
> 便于在纯 Windows / Git Bash 环境复现。实际走了哪条路由记录在 `output/environment.txt`。

## 4. 双层反幻觉约束

```text
第一层（行为）agent.md
  ├─ 先检索后回答：事实必须来自 query/answer 的证据
  ├─ 单一事实源：项目事实只认 PROJECT_FACTS.md
  ├─ 无命中即拒答：低分/越界 → 原样输出拒答模板
  └─ 禁止编造清单：路径、行号、哈希、参数、数字、引用

第二层（内容）AI与大数据/PROJECT_FACTS.md
  ├─ 范围白名单 §2：W1–W5 五个可回答主题，各自绑定证据文件
  ├─ 事实基线 §1：仓库、语料源、命令、许可证
  ├─ 禁止事项 §3：六条硬性禁止
  └─ 拒答模板 §4：脚本直接读取该段落，保证文案与基线同源
```

工程上的关键点：**拒答模板不在脚本里另写一份**，`rag_github.py` 的 `answer` 子命令会解析
`PROJECT_FACTS.md` 中 `REFUSAL_TEMPLATE_START/END` 之间的文本并逐字输出——改基线即改行为。

## 5. RAG 管线（GitHub → Python）

```text
ingest  →  GitHub Contents API（base64）/ raw 兜底
           ↓  6 个文档：README(en/zh)、architecture(en/zh)、glossary(en/zh)
           ↓  落盘 rag/corpus/github_snapshot/ + manifest.json(commit, sha256, bytes, lines)
index   →  按 Markdown 标题切小节 → 段落打包成 ~1200 字切片
           ↓  中英文混合分词：英文按词、中文按二元组，过滤虚词停用词
           ↓  BM25(k1=1.5, b=0.75) 倒排索引 → rag/corpus/index.json
query   →  打分排序 → Top-K 证据，每条带 文件#L起-L止、得分、词项覆盖率
answer  →  Top-1 < 阈值(1.5) 或相对得分不足 → 逐字拒答
           否则输出「摘录 + 来源行号」的抽取式回答（不自由生成，故不会引入语料外内容）
```

为什么不接大模型自由生成：作业的核心是**消除幻觉**。抽取式回答的每个字都能在
`github_snapshot/` 里定位到行号，代价是表达不如生成式流畅——这是刻意取舍。

## 6. 输出与核验

`bash scripts/run_all.sh` 会在 `output/` 生成：

| 文件 | 内容 |
| --- | --- |
| `environment.txt` | bash / git / conda / python 实测版本与解释器路径 |
| `rag_ingest.txt` | 6 个快照的抓取过程（commit、字节数、sha256） |
| `rag_index.txt` / `rag_stats.txt` / `rag_stats.json` | 切片数、词项数、平均长度、构建耗时 |
| `rag_query_zh.txt` / `rag_query_en.txt` | 中英文查询的带来源证据 |
| `rag_answer_zh.txt` | 检索式回答（每条挂 `文件#Lx-Ly`） |
| `rag_refusal_demo.txt` | 越界问题（天气）的拒答留档 |
| `git_log.txt` | push / clone / 协作者提交 / pull --ff-only 的真实 git 输出 |
| `FINAL_RESULT.md` | 以上全部汇总 + 交付清单 |

**报告、PPT 或任何说明中的数字，都应从 `output/FINAL_RESULT.md` 抄，而不是凭记忆写。**

## 7. 环境与许可证

- Python ≥ 3.10（作业环境为 conda `test`），仅标准库；git ≥ 2.34
- 网络：优先 `api.github.com`（国内可直连），`raw.githubusercontent.com` 作兜底
- 许可证：[MIT](LICENSE)，版权人 `ACAD-f`
- 语料版权归 `deepseek-ai/deepseek-harness` 原作者，本仓库仅作课程检索实验使用
