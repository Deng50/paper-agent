import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lit_agent.core.config import get_settings
from lit_agent.tools import scoring
from lit_agent.tools.schemas import Paper


def paper() -> Paper:
    return Paper(paper_id="arxiv-1", source="arxiv", external_id="1", title="Battery")


def test_missing_paper_score_is_rejected() -> None:
    client = SimpleNamespace(
        messages=SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(
                    content=[
                        SimpleNamespace(type="tool_use", name="submit_scores", input={"scores": []})
                    ]
                )
            )
        )
    )
    with pytest.raises(ValueError, match="paper_id"):
        asyncio.run(scoring._score_batch(client, [paper()], ""))


def test_invalid_schema_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.__aenter__.return_value = client
    monkeypatch.setattr(scoring, "AsyncAnthropic", lambda **kw: client)
    batch = AsyncMock(side_effect=[ValueError("missing score"), {"arxiv-1": (8.0, "相关")}])
    monkeypatch.setattr(scoring, "_score_batch", batch)
    papers = asyncio.run(scoring.score_papers([paper()], "", get_settings()))
    assert papers[0].score == 8.0
    assert batch.await_count == 2
    client.__aexit__.assert_awaited_once()


def test_provider_failure_is_not_silent_empty_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    monkeypatch.setattr(scoring, "AsyncAnthropic", lambda **kw: client)
    monkeypatch.setattr(
        scoring, "_score_batch", AsyncMock(side_effect=RuntimeError("provider down"))
    )
    with pytest.raises(RuntimeError, match="provider down"):
        asyncio.run(scoring.score_papers([paper()], "", get_settings()))
    client.__aexit__.assert_awaited_once()
