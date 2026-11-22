#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rag_github.py — GitHub 语料 → Python RAG 管线（BM25，零第三方依赖）

职责
----
1. ``ingest``：从 GitHub 抓取 ``deepseek-ai/deepseek-harness`` 的 6 个文档快照，
   落盘到 ``rag/corpus/github_snapshot/``，并写入 ``rag/corpus/manifest.json``
   （仓库、ref、commit、sha256、字节数、行号、抓取时间），保证语料可复现、可核对。
2. ``index``：把「6 个 GitHub 快照 + 5 个项目内 md」切分为切片（chunk），构建 BM25
   倒排索引，落盘 ``rag/corpus/index.json``。
3. ``query``：中英文检索，返回 Top-K 证据，每条带 ``文件#L起-L止`` 的真实行号与得分。
4. ``answer``：先检索后回答；命中不足或越界时，原样输出
   ``AI与大数据/PROJECT_FACTS.md`` 里的拒答模板（单一事实源，避免脚本另写一份文案）。
5. ``stats``：输出索引规模（文件数 / 切片数 / 词项数 / 平均长度），供 ``output/`` 留档。

设计约束（与 agent.md 对应）
--------------------------
- 只用标准库，``conda run -n test python`` 与本地 python 均可直接运行；
- 检索结果必须带源文件与行号，禁止只回一段「看起来对」的文字；
- 拒答模板只从 PROJECT_FACTS.md 读取，脚本内不保留第二份副本。

用法
----
    python rag/rag_github.py ingest            # 抓取 6 个快照（--offline 跳过网络）
    python rag/rag_github.py index             # 建 BM25 索引
    python rag/rag_github.py build             # ingest + index
    python rag/rag_github.py query "架构 分层"  # 检索证据
    python rag/rag_github.py answer "..."      # 检索 + 引用 + 拒答
    python rag/rag_github.py stats --json      # 索引统计
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------- 路径与常量

BASE_DIR = Path(__file__).resolve().parents[1]
CORPUS_DIR = BASE_DIR / "rag" / "corpus"
SNAP_DIR = CORPUS_DIR / "github_snapshot"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
INDEX_PATH = CORPUS_DIR / "index.json"
FACTS_PATH = BASE_DIR / "AI与大数据" / "PROJECT_FACTS.md"

REPO = "deepseek-ai/deepseek-harness"
REF = "master"
RAW_URL = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"
API_CONTENTS_URL = "https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
API_COMMIT_URL = "https://api.github.com/repos/{repo}/commits/{ref}"

# 6 个 GitHub 语料快照：英文 / 中文成对，保证中英文查询都有可引用的证据。
SOURCES = [
    {"path": "README.md", "title": "DeepSeek Harness README (en)", "lang": "en"},
    {"path": "README.zh.md", "title": "DeepSeek Harness README (zh)", "lang": "zh"},
    {"path": "docs/architecture.md", "title": "Architecture (en)", "lang": "en"},
    {"path": "docs/architecture.zh.md", "title": "Architecture (zh)", "lang": "zh"},
    {"path": "docs/glossary.md", "title": "Glossary (en)", "lang": "en"},
    {"path": "docs/glossary.zh.md", "title": "Glossary (zh)", "lang": "zh"},
]

# 5 个项目内 md：项目自身的事实与流程也必须可检索，才能回答「本项目怎么用」。
LOCAL_DOCS = [
    "agent.md",
    "AI与大数据/PROJECT_FACTS.md",
    "AI与大数据/README.md",
    "README.md",
    "docs/GITHUB_ACCOUNT.md",
]

# 切片参数：按小节聚合段落，控制在 1200 字符左右，上限 1800，避免证据过碎或过长。
CHUNK_TARGET = 1200
CHUNK_MAX = 1800
CHUNK_MIN = 60

BM25_K1 = 1.5
BM25_B = 0.75
DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 1.5
RELATIVE_CUTOFF = 0.4  # answer 模式：低于 Top-1 得分 40% 的切片不列为证据

RE_ASCII_TOKEN = re.compile(r"[a-z0-9][a-z0-9_\-.]*")
RE_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
RE_PARAGRAPH = re.compile(r"\n\s*\n")

# 停用词：查询里的「是什么 / 如何 / the / is」等虚词若参与打分，会因 IDF 高而把
# 「恰好出现某个虚词」的无关切片顶到第一位。索引与查询两侧同时过滤，保证一致。
STOPWORDS = {
    # 中文单字
    "的", "了", "是", "在", "和", "与", "及", "或", "也", "都", "而", "其", "之", "这", "那",
    "有", "无", "不", "我", "你", "他", "个", "就", "又", "很", "更", "最", "也", "把", "被",
    "对", "从", "到", "为", "以", "于", "则", "等", "让", "使", "会", "要", "可", "能", "中",
    # 中文常见词 / 二元组
    "是什", "什么", "怎么", "如何", "哪些", "哪个", "为何", "是否", "这个", "那个", "这些",
    "那些", "这样", "那样", "可以", "能够", "需要", "以及", "或者", "但是", "因为", "所以",
    "如果", "就是", "我们", "你们", "他们", "一个", "一种", "进行", "用于", "关于", "对于",
    "中的", "的话", "了吗", "以及", "并且", "而且", "还是", "只是", "已经", "通过", "根据",
    "之间", "其中", "从而", "因此", "比如", "例如", "包括", "主要", "如何", "怎样",
    # 英文虚词
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being", "of", "to", "in",
    "on", "at", "for", "with", "and", "or", "not", "no", "do", "does", "did", "how", "what",
    "which", "who", "whom", "why", "when", "where", "this", "that", "these", "those", "it",
    "its", "as", "by", "from", "into", "than", "then", "so", "such", "can", "could", "should",
    "would", "may", "might", "must", "will", "i", "we", "you", "they", "he", "she", "but",
    "if", "because", "about", "there", "here", "one", "two", "use", "used", "using", "all",
    "any", "some", "more", "most", "other", "also", "only", "just", "very", "each", "per",
}


# ---------------------------------------------------------------- 基础工具


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    """返回相对项目根目录的 POSIX 风格路径，用于引用展示。"""
    try:
        return path.resolve().relative_to(BASE_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def _snapshot_name(github_path: str) -> str:
    return github_path.replace("/", "__")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tokenize(text: str) -> list[str]:
    """中英文混合分词：英文按词、中文按二元组（bigram），并过滤虚词停用词。"""
    lowered = text.lower()
    tokens = [t for t in RE_ASCII_TOKEN.findall(lowered) if t not in STOPWORDS]
    for run in RE_CJK_RUN.findall(lowered):
        if len(run) == 1:
            if run not in STOPWORDS:
                tokens.append(run)
        else:
            tokens.extend(
                run[i : i + 2]
                for i in range(len(run) - 1)
                if run[i : i + 2] not in STOPWORDS
            )
    return tokens


def _http_get(url: str, timeout: int = 30) -> bytes:
    headers = {
        "User-Agent": "ai-bigdata-rag-agent/1.0 (+coursework)",
        "Accept": "*/*",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"

    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_err = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404):
                break
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"抓取失败：{url}（{last_err}）")


def _fetch_commit_sha() -> str:
    try:
        payload = json.loads(_http_get(API_COMMIT_URL.format(repo=REPO, ref=REF)).decode("utf-8"))
        return str(payload.get("sha", "")) or "unknown"
    except Exception:  # 网络或限流失败不应阻断语料抓取
        return "unknown"


def _fetch_doc(path: str) -> tuple[bytes, str]:
    """抓取单个文档快照，返回 (内容, 使用的通道)。

    优先走 GitHub Contents API（api.github.com 返回 base64，国内网络通常可直连），
    失败再退回 raw.githubusercontent.com。两条通道内容一致，均以 commit + sha256 固定。
    """
    api_url = API_CONTENTS_URL.format(repo=REPO, path=path, ref=REF)
    try:
        payload = json.loads(_http_get(api_url).decode("utf-8"))
        if payload.get("encoding") == "base64" and payload.get("content"):
            raw = base64.b64decode(payload["content"])
            if raw:
                return raw, "api"
    except Exception as exc:
        print(f"[ingest] API 通道失败（{path}）：{exc}", file=sys.stderr)

    raw_url = RAW_URL.format(repo=REPO, ref=REF, path=path)
    return _http_get(raw_url), "raw"


# ---------------------------------------------------------------- ingest


def cmd_ingest(args: argparse.Namespace) -> int:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    previous: dict[str, dict] = {}
    if MANIFEST_PATH.exists():
        try:
            old = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            previous = {item["path"]: item for item in old.get("sources", [])}
        except Exception:
            previous = {}

    commit = "unknown" if args.offline else _fetch_commit_sha()
    sources: list[dict] = []
    for src in SOURCES:
        target = SNAP_DIR / _snapshot_name(src["path"])
        if args.offline:
            if not target.exists():
                print(f"[ingest] 缺少本地快照：{_rel(target)}（--offline 无法补齐）", file=sys.stderr)
                return 2
            raw = target.read_bytes()
            fetched_at = previous.get(src["path"], {}).get("fetched_at", "unknown")
            via = previous.get(src["path"], {}).get("fetched_via", "offline")
        else:
            raw, via = _fetch_doc(src["path"])
            fetched_at = _now_iso()
            target.write_bytes(raw)

        text = raw.decode("utf-8", errors="replace")
        sources.append(
            {
                "path": src["path"],
                "snapshot": _rel(target),
                "title": src["title"],
                "lang": src["lang"],
                "source_url": RAW_URL.format(repo=REPO, ref=REF, path=src["path"]),
                "fetched_via": via,
                "commit": commit,
                "bytes": len(raw),
                "lines": text.count("\n") + 1,
                "sha256": _sha256(raw),
                "fetched_at": fetched_at,
            }
        )
        print(f"[ingest] {src['path']} -> {_rel(target)} ({len(raw)} bytes, via {via})")

    manifest = {
        "repo": REPO,
        "ref": REF,
        "commit": commit,
        "generated_at": _now_iso(),
        "mode": "offline" if args.offline else "online",
        "source_count": len(sources),
        "sources": sources,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ingest] 写出 {_rel(MANIFEST_PATH)}：{len(sources)} 个快照，commit={commit[:12]}")
    return 0


# ---------------------------------------------------------------- 切片


def _sections(text: str) -> list[dict]:
    """按 Markdown 标题切小节，返回 [(heading_path, start_line, end_line)]（1-based）。"""
    lines = text.splitlines()
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []
    current = {"heading": "", "start": 1, "lines": []}

    def flush() -> None:
        if any(line.strip() for line in current["lines"]):
            sections.append(
                {
                    "heading": current["heading"],
                    "start": current["start"],
                    "end": current["start"] + len(current["lines"]) - 1,
                    "lines": list(current["lines"]),
                }
            )

    for idx, line in enumerate(lines, start=1):
        m = RE_HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            stack = [(lv, t) for lv, t in stack if lv < level]
            stack.append((level, title))
            current = {"heading": " > ".join(t for _, t in stack), "start": idx, "lines": [line]}
        else:
            current["lines"].append(line)
    flush()
    return sections


def _pack_section(section: dict, file_label: str) -> list[dict]:
    """把一个页面小节按段落打包成 1..n 个切片，尽量贴近 CHUNK_TARGET。"""
    start = section["start"]
    buffer: list[str] = []
    buffer_start = start + 1  # 标题行之后
    chunks: list[dict] = []

    def emit(buf: list[str], line_start: int, line_end: int) -> None:
        body = "\n".join(buf).strip()
        if len(body) < CHUNK_MIN:
            return
        chunks.append(
            {
                "file": file_label,
                "heading": section["heading"],
                "start": line_start,
                "end": line_end,
                "text": body,
            }
        )

    cursor = start + 1
    for raw_line in section["lines"][1:]:
        line_no = cursor
        cursor += 1
        if not raw_line.strip():
            continue
        buffer.append(raw_line)
        joined = "\n".join(buffer)
        if len(joined) >= CHUNK_TARGET:
            emit(buffer, buffer_start, line_no)
            buffer = []
            buffer_start = cursor
        elif len(joined) >= CHUNK_MAX:
            emit(buffer, buffer_start, line_no)
            buffer = []
            buffer_start = cursor
    if buffer:
        emit(buffer, buffer_start, cursor - 1)
    return chunks


def chunk_file(path: Path, label: str) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks: list[dict] = []
    for section in _sections(text):
        chunks.extend(_pack_section(section, label))
    return chunks


# ---------------------------------------------------------------- index


def _iter_documents() -> list[tuple[str, Path]]:
    docs: list[tuple[str, Path]] = []
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for item in manifest.get("sources", []):
            docs.append((item["snapshot"], BASE_DIR / item["snapshot"]))
    for rel in LOCAL_DOCS:
        p = BASE_DIR / rel
        if p.exists():
            docs.append((rel, p))
        else:
            print(f"[index] 跳过不存在的项目文档：{rel}", file=sys.stderr)
    return docs


def cmd_index(args: argparse.Namespace) -> int:
    docs = _iter_documents()
    if not docs:
        print("[index] 没有可用文档，请先执行 ingest", file=sys.stderr)
        return 2

    started = time.perf_counter()
    chunks: list[dict] = []
    for label, path in docs:
        got = chunk_file(path, label)
        chunks.extend(got)
        print(f"[index] {label}: {len(got)} 切片")

    postings: dict[str, list[list[int]]] = defaultdict(list)
    dl: list[int] = []
    df: Counter[str] = Counter()

    for idx, chunk in enumerate(chunks):
        toks = tokenize(chunk["text"])
        chunk["tokens"] = len(toks)
        dl.append(len(toks))
        tf = Counter(toks)
        for term, freq in tf.items():
            postings[term].append([idx, freq])
            df[term] += 1

    n = len(chunks)
    avgdl = (sum(dl) / n) if n else 0.0
    idf = {term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()}
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    index = {
        "meta": {
            "built_at": _now_iso(),
            "repo": REPO,
            "ref": REF,
            "files": len(docs),
            "chunks": n,
            "vocab": len(postings),
            "avgdl": round(avgdl, 3),
            "tokens": sum(dl),
            "k1": BM25_K1,
            "b": BM25_B,
            "chunk_target": CHUNK_TARGET,
            "chunk_max": CHUNK_MAX,
            "build_ms": elapsed_ms,
        },
        "files": [label for label, _ in docs],
        "chunks": [{k: v for k, v in c.items() if k != "tokens"} | {"len": c["tokens"]} for c in chunks],
        "dl": dl,
        "idf": idf,
        "postings": dict(postings),
    }
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"[index] {len(docs)} 文件 / {n} 切片 / {len(postings)} 词项 / 平均 {avgdl:.1f} tokens"
        f" / {elapsed_ms} ms -> {_rel(INDEX_PATH)}"
    )
    return 0


# ---------------------------------------------------------------- query / answer


def _load_index() -> dict:
    if not INDEX_PATH.exists():
        raise SystemExit(f"缺少索引 {_rel(INDEX_PATH)}，请先执行：python rag/rag_github.py build")
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def bm25_search(index: dict, question: str, top_k: int) -> list[dict]:
    q_tokens = tokenize(question)
    if not q_tokens:
        return []
    meta = index["meta"]
    k1, b = meta["k1"], meta["b"]
    avgdl = meta["avgdl"] or 1.0
    dl = index["dl"]
    idf = index["idf"]
    postings = index["postings"]

    scores: dict[int, float] = defaultdict(float)
    matched: dict[int, set[str]] = defaultdict(set)
    for term in sorted(set(q_tokens)):
        if term not in postings:
            continue
        w = idf[term]
        for chunk_id, tf in postings[term]:
            denom = tf + k1 * (1 - b + b * dl[chunk_id] / avgdl)
            scores[chunk_id] += w * (tf * (k1 + 1)) / denom
            matched[chunk_id].add(term)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    unique_terms = len(set(q_tokens))
    results = []
    for chunk_id, score in ranked:
        chunk = index["chunks"][chunk_id]
        results.append(
            {
                "chunk_id": chunk_id,
                "score": round(score, 3),
                "file": chunk["file"],
                "heading": chunk["heading"],
                "lines": f"L{chunk['start']}-L{chunk['end']}",
                "coverage": round(len(matched[chunk_id]) / unique_terms, 3),
                "text": chunk["text"],
            }
        )
    return results


def _best_snippet(text: str, question: str, limit: int = 320) -> str:
    """从切片中挑「查询词密度最高」的段落作为摘录，尽量保留完整语义单元。"""
    q_terms = set(tokenize(question))
    paragraphs = [p.strip() for p in RE_PARAGRAPH.split(text) if p.strip()]
    if not paragraphs:
        return text[:limit]

    def density(paragraph: str) -> int:
        return sum(1 for t in tokenize(paragraph) if t in q_terms)

    ranked = sorted(paragraphs, key=density, reverse=True)
    picked = ranked[0]
    if len(picked) < 120:
        for extra in ranked[1:]:
            if len(picked) + len(extra) > limit:
                break
            picked = f"{picked} {extra}"
    if len(picked) > limit:
        cut = picked[:limit]
        # 尽量在句末截断，避免半个句子
        boundary = max(cut.rfind("。"), cut.rfind("."), cut.rfind("\n"))
        picked = cut[: boundary + 1] if boundary > limit * 0.5 else cut.rstrip() + "…"
    return " ".join(picked.split())


def _refusal_template() -> str:
    """从 PROJECT_FACTS.md 读取拒答模板，保证与事实基线同源。"""
    fallback = "【拒绝回答】该问题不在本项目的语料与事实基线范围内，为避免编造不予作答。"
    if not FACTS_PATH.exists():
        return fallback
    text = FACTS_PATH.read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"<!--\s*REFUSAL_TEMPLATE_START\s*-->(.*?)<!--\s*REFUSAL_TEMPLATE_END\s*-->",
        text,
        re.S,
    )
    return m.group(1).strip() if m else fallback


def _print_results(results: list[dict], as_json: bool) -> None:
    if as_json:
        payload = [{k: v for k, v in r.items() if k != "text"} for r in results]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not results:
        print("（无命中）")
        return
    for rank, r in enumerate(results, start=1):
        print(f"#{rank} 得分 {r['score']:.3f}  覆盖 {r['coverage']:.0%}")
        print(f"[来源] {r['file']}#{r['lines']}")
        print(f"[标题] {r['heading']}")
        print(f"[摘录] {_best_snippet(r['text'], r['heading'])}")
        print()


def cmd_query(args: argparse.Namespace) -> int:
    index = _load_index()
    results = bm25_search(index, args.question, args.top_k)
    _print_results(results, args.json)
    return 0 if results else 1


def cmd_answer(args: argparse.Namespace) -> int:
    index = _load_index()
    results = bm25_search(index, args.question, args.top_k)
    top = results[0]["score"] if results else 0.0

    if not results or top < args.min_score:
        print(_refusal_template())
        print()
        print(f"[判定] 最高得分 {top:.3f} < 阈值 {args.min_score}，按 PROJECT_FACTS.md §4 拒答。")
        return 3

    # 相对截断：与 Top-1 差距过大的切片不当作「证据」，避免把无关段落硬塞进答案。
    evidence = [r for r in results if r["score"] >= top * RELATIVE_CUTOFF]

    print("【检索结论】以下内容全部来自语料证据，未使用模型记忆补全。")
    print(f"[判据] Top-1 得分 {top:.3f} ≥ 阈值 {args.min_score}；证据 {len(evidence)} 条"
          f"（相对截断：得分 ≥ Top-1 的 {int(RELATIVE_CUTOFF * 100)}%）。")
    print()
    for rank, r in enumerate(evidence, start=1):
        print(f"{rank}. {_best_snippet(r['text'], args.question)}")
        print(f"   [来源] {r['file']}#{r['lines']}（得分 {r['score']:.3f}）")
    print()
    print("[说明] 上述为抽取式回答：只摘录命中切片原句并标注行号，不做自由生成，故不会引入语料外内容。")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    index = _load_index()
    meta = index["meta"]
    if args.json:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        print(f"语料文件数 : {meta['files']}")
        print(f"切片数     : {meta['chunks']}")
        print(f"词项数     : {meta['vocab']}")
        print(f"总 token   : {meta['tokens']}")
        print(f"平均长度   : {meta['avgdl']} tokens/切片")
        print(f"构建耗时   : {meta['build_ms']} ms")
        print(f"构建时间   : {meta['built_at']}")
        print(f"语料源     : {meta['repo']}@{meta['ref']}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    rc = cmd_ingest(args)
    if rc != 0:
        return rc
    return cmd_index(args)


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag_github.py",
        description="GitHub 语料 RAG 管线：抓取快照 → BM25 索引 → 中英文检索 → 带引用的抽取式回答",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="抓取 6 个 GitHub 文档快照并写 manifest")
    p_ingest.add_argument("--offline", action="store_true", help="不联网，仅基于已有快照重建 manifest")
    p_ingest.set_defaults(func=cmd_ingest)

    p_index = sub.add_parser("index", help="切分并构建 BM25 索引")
    p_index.set_defaults(func=cmd_index)

    p_build = sub.add_parser("build", help="ingest + index")
    p_build.add_argument("--offline", action="store_true", help="不联网，仅基于已有快照重建")
    p_build.set_defaults(func=cmd_build)

    p_query = sub.add_parser("query", help="检索证据（Top-K，带来源行号）")
    p_query.add_argument("question", help="查询文本，中英文均可")
    p_query.add_argument("-k", "--top-k", type=int, default=DEFAULT_TOP_K, help="返回条数，默认 5")
    p_query.add_argument("--json", action="store_true", help="以 JSON 输出，便于留档")
    p_query.set_defaults(func=cmd_query)

    p_answer = sub.add_parser("answer", help="先检索后回答；无命中则按事实基线拒答")
    p_answer.add_argument("question", help="问题文本，中英文均可")
    p_answer.add_argument("-k", "--top-k", type=int, default=3, help="引用条数，默认 3")
    p_answer.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE, help="拒答阈值，默认 1.5")
    p_answer.set_defaults(func=cmd_answer)

    p_stats = sub.add_parser("stats", help="输出索引统计")
    p_stats.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_stats.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
