import asyncio
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from lit_agent.scheduler import jobs


def test_partial_email_failure_still_archives_session(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [
        ToolMessage(
            content=json.dumps(
                {
                    "counts": {"raw": 1, "selected": 1},
                    "papers": [{"paper_id": "p1", "title": "Battery"}],
                }
            ),
            name="search_papers_tool",
            tool_call_id="t1",
        ),
        AIMessage(content=[{"type": "text", "text": "今日导语"}]),
    ]
    agent = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"messages": messages}),
        aupdate_state=AsyncMock(),
        aget_state=AsyncMock(return_value=SimpleNamespace(values={"messages": messages})),
    )
    monkeypatch.setattr(jobs, "build_lit_agent", lambda **kwargs: agent)
    saver_cm = AsyncMock()
    monkeypatch.setattr(jobs.AsyncPostgresSaver, "from_conn_string", lambda *args: saver_cm)
    session = AsyncMock()
    session.__aenter__.return_value = session
    push = SimpleNamespace()
    session.get.return_value = push
    monkeypatch.setattr(jobs, "_claim_run", AsyncMock(return_value=(1, "new")))
    monkeypatch.setattr(jobs, "send_email", AsyncMock(side_effect=RuntimeError("smtp unavailable")))
    monkeypatch.setattr(jobs, "render_daily_push", lambda *args: "html")
    derive = MagicMock()
    monkeypatch.setattr(jobs, "derive_session_md", derive)
    status = asyncio.run(jobs.run_daily_push(session_factory=lambda: session))
    assert status == "partial"
    assert push.status == "partial" and not push.email_sent
    assert push.selected_count == 1
    derive.assert_called_once()
    assert jobs._extract({"messages": messages})["intro"] == "今日导语"


def test_missing_search_result_marks_push_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="done")]})
    )
    monkeypatch.setattr(jobs, "build_lit_agent", lambda **kwargs: agent)
    monkeypatch.setattr(jobs.AsyncPostgresSaver, "from_conn_string", lambda *args: AsyncMock())
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.get.return_value = SimpleNamespace()
    monkeypatch.setattr(jobs, "_claim_run", AsyncMock(return_value=(1, "new")))
    assert asyncio.run(jobs.run_daily_push(session_factory=lambda: session)) == "failed"


def test_atomic_claim_rejects_lost_retry_race() -> None:
    existing = SimpleNamespace(id=1, status="failed")
    first = MagicMock()
    first.scalar_one_or_none.return_value = existing
    lost_race = MagicMock()
    lost_race.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute.side_effect = [first, lost_race]
    assert asyncio.run(jobs._claim_run(session, dt.date(2026, 10, 3), "retry")) is None
    sql = str(session.execute.await_args_list[1].args[0])
    assert "pushes.status =" in sql and "RETURNING pushes.id" in sql
