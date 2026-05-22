"""4 源抓取层（M2）。

调用边界（硬约束）：本模块只调 vendored 各 source 的 `search()`，
**绝不调用 download_pdf() / read_paper() / 任何 PDF 处理函数**。

并发策略：
- arXiv / Crossref / OpenAlex：跨 query 并行（asyncio + to_thread，各自独立 HTTP）。
- Semantic Scholar：限流 1 req/s 累计 → 全局**串行** + RateLimiter 间隔（默认 1.1s）。
错误隔离：任一 (源, query) 失败只记日志返回 []，不阻塞其余（PRD：单源关闭仍完成）。

日期排序映射（v0.4 §8 强制按发表日期降序）：
  arxiv→sort_by=submittedDate/sort_order=descending  crossref→sort=published/order=desc
  s2→sort=publicationDate:desc(经 patch 走 bulk)       openalex→sort=publication_date:desc
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import time

import structlog

from lit_agent.core.config import Settings
from lit_agent.tools.paper_md import extract_arxiv_id, make_paper_id, normalize_title
from lit_agent.tools.schemas import Paper, Source

_log = structlog.get_logger("sources")


class RateLimiter:
    """异步最小间隔节流器（S2 用）。保证相邻请求间隔 ≥ min_interval 秒。"""

    def __init__(self, min_interval_s: float) -> None:
        self._min = min_interval_s
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            delta = loop.time() - self._last
            if delta < self._min:
                await asyncio.sleep(self._min - delta)
            self._last = loop.time()


def _to_date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return None


def _normalize(source: Source, vp: object) -> Paper | None:
    """vendored Paper(dataclass) → 我方 Paper。失败返回 None。"""
    try:
        external_id = str(getattr(vp, "paper_id", "")).strip()
        title = str(getattr(vp, "title", "")).strip()
        if not external_id or not title:
            return None
        doi = (getattr(vp, "doi", "") or "").strip() or None
        return Paper(
            paper_id=make_paper_id(source, external_id),
            source=source,
            external_id=external_id,
            title=title,
            authors=list(getattr(vp, "authors", []) or []),
            abstract=str(getattr(vp, "abstract", "") or ""),
            url=str(getattr(vp, "url", "") or ""),
            pub_date=_to_date(getattr(vp, "published_date", None)),
            venue=None,
            doi=doi,
            arxiv_id=extract_arxiv_id(source, external_id, doi),
            normalized_title=normalize_title(title),
        )
    except Exception as exc:  # 单篇坏数据不该拖垮整批
        _log.warning("normalize_failed", source=source, error=str(exc))
        return None


def _search_sync(source: Source, query: str, limit: int) -> list[Paper]:
    """同步调 vendored search()（带日期排序），归一化。错误隔离。"""
    t0 = time.perf_counter()
    try:
        if source == "arxiv":
            from paper_search_mcp.academic_platforms.arxiv import ArxivSearcher

            raw = ArxivSearcher().search(
                query, max_results=limit, sort_by="submittedDate", sort_order="descending"
            )
        elif source == "crossref":
            from paper_search_mcp.academic_platforms.crossref import CrossRefSearcher

            raw = CrossRefSearcher().search(
                query, max_results=limit, sort="published", order="desc"
            )
        elif source == "openalex":
            from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher

            raw = OpenAlexSearcher().search(query, max_results=limit, sort="publication_date:desc")
        elif source == "s2":
            from paper_search_mcp.academic_platforms.semantic import SemanticSearcher

            raw = SemanticSearcher().search(query, max_results=limit, sort="publicationDate:desc")
        else:  # pragma: no cover - Source 已穷举
            return []
        papers = [p for vp in (raw or []) if (p := _normalize(source, vp)) is not None]
        _log.info(
            "source_ok",
            source=source,
            query=query,
            raw=len(raw or []),
            kept=len(papers),
            ms=int((time.perf_counter() - t0) * 1000),
        )
        return papers
    except Exception as exc:  # 单源失败不阻塞其余（PRD：单源关闭仍完成）
        _log.warning("source_failed", source=source, query=query, error=str(exc))
        return []


async def _fetch_concurrent(source: Source, queries: list[str], limit: int) -> list[Paper]:
    results = await asyncio.gather(
        *(asyncio.to_thread(_search_sync, source, q, limit) for q in queries)
    )
    return [p for batch in results for p in batch]


async def _fetch_s2_serial(queries: list[str], limit: int, limiter: RateLimiter) -> list[Paper]:
    out: list[Paper] = []
    for q in queries:
        await limiter.wait()  # 保证 S2 不在同一秒发第二个请求
        out.extend(await asyncio.to_thread(_search_sync, "s2", q, limit))
    return out


async def fetch_all(queries: list[str], limit_per_query: int, settings: Settings) -> list[Paper]:
    """对全部 query × 4 源抓取（已按日期降序）。S2 串行限流，其余并行。"""
    # 把 S2 key 桥接到 vendored 代码读的环境变量名（不打印 key）。
    os.environ["SEMANTIC_SCHOLAR_API_KEY"] = settings.semantic_scholar_api_key

    limiter = RateLimiter(settings.s2_min_interval_s)
    arxiv, crossref, openalex, s2 = await asyncio.gather(
        _fetch_concurrent("arxiv", queries, limit_per_query),
        _fetch_concurrent("crossref", queries, limit_per_query),
        _fetch_concurrent("openalex", queries, limit_per_query),
        _fetch_s2_serial(queries, limit_per_query, limiter),
    )
    return [*arxiv, *crossref, *openalex, *s2]
