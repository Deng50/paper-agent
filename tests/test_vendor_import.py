"""M2 防御性测试（owner 约束 #2）：

- 冷启动 import：4 源类 import + 实例化成功；且裁掉的包确实未安装。
  一旦 vendored 内部有漏检的动态/惰性 import，这里立即失败，不等线上。
- 源归一化：mock vendored searcher，验证 _search_sync 归一化 + 接受日期排序参数。
- search_papers 全流程（mock 抓取 + mock 评分，不联网）：去重 / 过滤 / 排序 / 落盘。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

from lit_agent.core.config import Settings
from lit_agent.tools import search_papers as sp_mod
from lit_agent.tools import sources
from lit_agent.tools.schemas import Paper


def _settings(tmp_path: Path) -> Settings:
    # 必填字段由 conftest 的环境变量提供；这里只覆盖 memory_dir。
    return Settings(memory_dir=tmp_path)  # type: ignore[call-arg]


def test_cold_start_imports_and_trimmed_deps() -> None:
    from paper_search_mcp.academic_platforms.arxiv import ArxivSearcher
    from paper_search_mcp.academic_platforms.crossref import CrossRefSearcher
    from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher
    from paper_search_mcp.academic_platforms.semantic import SemanticSearcher

    for cls in (ArxivSearcher, SemanticSearcher, CrossRefSearcher, OpenAlexSearcher):
        assert cls() is not None

    # 裁掉的 5 个包必须未安装（证明直接 import 不依赖 MCP/PDF 栈）。
    for pkg in ("fastmcp", "mcp", "pypdf", "lxml"):
        assert importlib.util.find_spec(pkg) is None, f"{pkg} 不应被安装"


def test_source_normalization_and_sort_args(monkeypatch: pytest.MonkeyPatch) -> None:
    from paper_search_mcp.academic_platforms import arxiv as arxiv_mod
    from paper_search_mcp.paper import Paper as VPaper

    captured: dict[str, object] = {}

    def fake_search(self: object, query: str, **kwargs: object) -> list[VPaper]:
        captured.update(kwargs)
        return [
            VPaper(
                paper_id="2405.01234",
                title="Interface Engineering of Sulfide Solid Electrolytes",
                authors=["Doe, J."],
                abstract="We report ...",
                doi="",
                published_date=dt.datetime(2026, 5, 12),
                pdf_url="",
                url="https://arxiv.org/abs/2405.01234",
                source="arxiv",
            )
        ]

    monkeypatch.setattr(arxiv_mod.ArxivSearcher, "search", fake_search)
    papers = sources._search_sync("arxiv", "solid electrolyte", 20)

    # 关键：日期排序参数被正确传给 arxiv（max_results 等其它参数也在 captured 里）
    assert captured["sort_by"] == "submittedDate"
    assert captured["sort_order"] == "descending"
    assert len(papers) == 1
    p = papers[0]
    assert p.paper_id == "arxiv-2405.01234"
    assert p.source == "arxiv"
    assert p.arxiv_id == "2405.01234"
    assert "sulfide solid electrolyte" in p.normalized_title  # 去停用词后


def test_search_papers_pipeline_mockflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 4 篇：p1/p2 同 DOI（批内去重）、p3 低分（过滤）、p4 高分。
    p1 = Paper(
        paper_id="arxiv-1",
        source="arxiv",
        external_id="1",
        title="Sulfide A",
        doi="10.1/a",
        normalized_title="sulfide a",
    )
    p2 = Paper(
        paper_id="s2-2",
        source="s2",
        external_id="2",
        title="Sulfide A dup",
        doi="10.1/a",
        normalized_title="sulfide a dup",
    )
    p3 = Paper(
        paper_id="crossref-3",
        source="crossref",
        external_id="3",
        title="Liquid C",
        normalized_title="liquid c",
    )
    p4 = Paper(
        paper_id="openalex-4",
        source="openalex",
        external_id="4",
        title="Sulfide D",
        normalized_title="sulfide d",
    )

    async def fake_fetch_all(queries, limit, settings):  # type: ignore[no-untyped-def]
        return [p1, p2, p3, p4]

    async def fake_score(papers, profile_summary, settings):  # type: ignore[no-untyped-def]
        scores = {"arxiv-1": 9.0, "crossref-3": 5.0, "openalex-4": 8.0}
        for p in papers:
            if p.paper_id in scores:
                p.score = scores[p.paper_id]
                p.reason = "理由"
        return papers

    monkeypatch.setattr(sp_mod.sources, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(sp_mod, "score_papers", fake_score)

    result = asyncio.run(sp_mod.search_papers(["q"], settings=_settings(tmp_path), min_score=6.0))

    ids = [p.paper_id for p in result]
    assert ids == ["arxiv-1", "openalex-4"]  # p2 去重、p3 过滤；按分降序
    # 落盘验证
    day = dt.date.today().isoformat()
    written = list((tmp_path / "papers" / day).glob("*.md"))
    assert {f.name for f in written} == {"arxiv-1.md", "openalex-4.md"}
    body = (tmp_path / "papers" / day / "arxiv-1.md").read_text(encoding="utf-8")
    assert "score: 9.0" in body and 'doi: "10.1/a"' in body


def test_memory_dedup_drops_known(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 预置一篇历史 paper.md（同 DOI），新结果应被记忆去重丢弃。
    day = dt.date.today().isoformat()
    hist = tmp_path / "papers" / day
    hist.mkdir(parents=True)
    (hist / "arxiv-1.md").write_text(
        '---\ndoi: "10.1/a"\narxiv_id: ""\nnormalized_title: "old"\n---\n', encoding="utf-8"
    )
    p1 = Paper(
        paper_id="s2-9",
        source="s2",
        external_id="9",
        title="Same DOI",
        doi="10.1/a",
        normalized_title="same doi",
    )

    async def fake_fetch_all(queries, limit, settings):  # type: ignore[no-untyped-def]
        return [p1]

    async def fake_score(papers, profile_summary, settings):  # type: ignore[no-untyped-def]
        for p in papers:
            p.score = 9.0
        return papers

    monkeypatch.setattr(sp_mod.sources, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(sp_mod, "score_papers", fake_score)

    result = asyncio.run(sp_mod.search_papers(["q"], settings=_settings(tmp_path)))
    assert result == []  # 同 DOI 被记忆去重
