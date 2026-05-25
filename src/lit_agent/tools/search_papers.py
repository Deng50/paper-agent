"""search_papers 工具：搜 + 去重 + 评分 + 持久化一体（M2 核心，附录 A.1）。

============================ 调用边界（硬约束）============================
本工具（经 sources.py）只调用 vendored 各 source 的 search() 取 metadata，
**绝不调用 download_pdf() / read_paper() / 任何 PDF 处理函数**。
v1 不解析 PDF；我们 grep + 冷启动 import 测试验证过依赖足够（见 VENDOR.md）。
=========================================================================

设计精神：去重/评分/落盘这些"逐项处理相同结构"的循环全在工具内由代码完成，
agent 调一次拿干净 Top N，不参与任何 for 循环。

流水线（A.1 / 02_architecture §4.2）：
  1. 每 query × 4 源抓取（强制日期降序；S2 串行限流，其余并行）
  2. 归一化 → 我方 Paper（已在 sources 内完成）
  3. 合并去重（doi > arxiv_id > normalized_title）
  4. 对照 ./memory/papers/ 历史丢弃命中
  5. Haiku 单次批量评分 → 过滤 < min_score → 按分降序
  6. 原子写 Top N → ./memory/papers/{date}/{paper_id}.md，返回
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import structlog

from lit_agent.core.config import Settings, get_settings
from lit_agent.tools import sources
from lit_agent.tools.paper_md import atomic_write, load_dedup_index, render_paper_md
from lit_agent.tools.schemas import Paper
from lit_agent.tools.scoring import score_papers

_log = structlog.get_logger("search_papers")

TOP_N_CAP = 10  # 每次精选上限（PRD「5–10 篇」）


def _dedup_in_batch(papers: list[Paper]) -> list[Paper]:
    """批内去重：doi > arxiv_id > normalized_title，保留首次出现。"""
    seen_doi: set[str] = set()
    seen_arxiv: set[str] = set()
    seen_title: set[str] = set()
    out: list[Paper] = []
    for p in papers:
        if p.doi and p.doi in seen_doi:
            continue
        if p.arxiv_id and p.arxiv_id in seen_arxiv:
            continue
        if p.normalized_title and p.normalized_title in seen_title:
            continue
        out.append(p)
        if p.doi:
            seen_doi.add(p.doi)
        if p.arxiv_id:
            seen_arxiv.add(p.arxiv_id)
        if p.normalized_title:
            seen_title.add(p.normalized_title)
    return out


def _read_profile_summary(memory_dir: Path) -> str:
    """读 profile.md 正文（frontmatter 之后）作为评分上下文。缺失返回空串。"""
    path = memory_dir / "profile" / "profile.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


async def search_papers(
    queries: list[str],
    sort: str = "date_desc",
    limit_per_query: int = 20,
    dedup_against_memory: bool = True,
    min_score: float = 6.0,
    *,
    settings: Settings | None = None,
    stats: dict[str, int] | None = None,
) -> list[Paper]:
    """搜 + 去重 + 评分 + 落盘，返回已去重已评分的 Top N（5–10）。

    `stats`（可选出参）：传入一个 dict，会被填入 raw/deduped/selected 计数，
    供 daily-push 的 pushes 审计用（默认 None，M2 调用方不受影响）。
    """
    if sort != "date_desc":
        raise ValueError("search_papers 仅支持 sort='date_desc'（v0.4 §8 强制日期排序）")
    settings = settings or get_settings()
    memory_dir = settings.memory_dir

    # 1+2. 抓取 + 归一化
    raw = await sources.fetch_all(queries, limit_per_query, settings)

    # 3. 批内去重
    deduped = _dedup_in_batch(raw)

    # 4. 对照历史记忆去重
    if dedup_against_memory:
        idx = load_dedup_index(memory_dir)
        deduped = [p for p in deduped if not idx.contains(p)]

    # 5. 批量评分 → 过滤 → 排序
    profile_summary = _read_profile_summary(memory_dir)
    scored = await score_papers(deduped, profile_summary, settings)
    selected = [p for p in scored if p.score is not None and p.score >= min_score]
    selected.sort(key=lambda p: p.score or 0.0, reverse=True)
    selected = selected[:TOP_N_CAP]

    # 6. 原子写（force_rerun 时若 paper.md 已存则 skip，方案 A 字面：不重写已存）
    now = dt.datetime.now().astimezone()
    day = now.date().isoformat()
    saved = 0
    skipped_existing = 0
    for p in selected:
        path = memory_dir / "papers" / day / f"{p.paper_id}.md"
        if path.exists():
            skipped_existing += 1
            _log.info("search_papers_skip_existing_md", paper_id=p.paper_id, path=str(path))
            continue
        atomic_write(path, render_paper_md(p, now))
        saved += 1
    if skipped_existing:
        _log.info("search_papers_save_summary", saved=saved, skipped_existing=skipped_existing)

    if stats is not None:
        stats["raw"] = len(raw)
        stats["deduped"] = len(deduped)
        stats["selected"] = len(selected)

    _log.info(
        "search_papers_done",
        queries=len(queries),
        raw=len(raw),
        deduped=len(deduped),
        selected=len(selected),
    )
    return selected
