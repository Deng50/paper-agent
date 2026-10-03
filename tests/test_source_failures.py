import asyncio
from types import SimpleNamespace

import pytest

from lit_agent.core.config import get_settings
from lit_agent.tools import sources


def _failed_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    from paper_search_mcp.academic_platforms.arxiv import ArxivSearcher
    from paper_search_mcp.academic_platforms.crossref import CrossRefSearcher
    from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher
    from paper_search_mcp.academic_platforms.semantic import SemanticSearcher

    def fail(self, *args, **kwargs):
        self.last_error = "upstream failed"
        return []

    for cls in (ArxivSearcher, CrossRefSearcher, OpenAlexSearcher, SemanticSearcher):
        monkeypatch.setattr(cls, "search", fail)


def test_all_sources_failed_is_not_an_empty_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _failed_sources(monkeypatch)
    with pytest.raises(RuntimeError, match="全部学术源"):
        asyncio.run(sources.fetch_all(["battery"], 20, get_settings()))


def test_one_healthy_empty_source_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    from paper_search_mcp.academic_platforms.crossref import CrossRefSearcher

    _failed_sources(monkeypatch)
    monkeypatch.setattr(CrossRefSearcher, "search", lambda self, *args, **kwargs: [])
    assert asyncio.run(sources.fetch_all(["battery"], 20, get_settings())) == []


def test_vendored_failures_report_status_without_changing_list_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import requests
    from paper_search_mcp.academic_platforms.arxiv import ArxivSearcher
    from paper_search_mcp.academic_platforms.crossref import CrossRefSearcher
    from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher
    from paper_search_mcp.academic_platforms.semantic import SemanticSearcher

    def unavailable(*args, **kwargs):
        raise requests.RequestException("unavailable")

    monkeypatch.setattr("time.sleep", lambda _: None)
    for cls in (ArxivSearcher, CrossRefSearcher, OpenAlexSearcher, SemanticSearcher):
        searcher = cls()
        monkeypatch.setattr(searcher.session, "get", unavailable)
        assert searcher.search("battery") == []
        assert searcher.last_error
        searcher.session.close()


def test_source_wrapper_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from paper_search_mcp.academic_platforms import openalex

    session = MagicMock()
    searcher = SimpleNamespace(session=session, search=lambda *args, **kwargs: [], last_error=None)
    monkeypatch.setattr(openalex, "OpenAlexSearcher", lambda: searcher)
    assert sources._search_sync("openalex", "battery", 20) == []
    session.close.assert_called_once()
