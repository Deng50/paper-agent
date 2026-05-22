"""M3 必跑回归（铁律#3 字面验收）：10:00 触发 + 模拟 agent 长 I/O + 11:00 同 thread_id
撞 running → busy 自拒、不二次发邮件、pushes 仅一行。+ feedback 5min 幂等。

机制说明：用 asyncio.Event 门控 fake agent（task1 占住 running 期间 task2 触发），
比 sleep(30s) 更确定，语义等价于「11:00 在 10:00 仍在跑时触发」。需真 PG（pushes 的
UniqueConstraint+status 闸是 DB 特性）；Windows 下 psycopg 异步需 SelectorEventLoop。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import lit_agent.scheduler.jobs as jobs
from lit_agent.core.config import get_settings
from lit_agent.db.base import Base
from lit_agent.db.models import Feedback, Push, User


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """跑协程；Windows 下用 SelectorEventLoop（psycopg 异步不兼容 ProactorEventLoop），
    经 asyncio.Runner 局部生效，不污染全局 event loop policy（不影响 M1 的 TestClient 测试）。"""
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coro)
    return asyncio.run(coro)


_PG_URL = "postgresql+psycopg://lit:lit@localhost:5432/lit_agent"
_TEST_DATE = dt.date(2099, 1, 1)
_TEST_PAPER = "arxiv-test-9999"

_FAKE_MESSAGES = [
    AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_papers_tool",
                "args": {"queries": ["q1"]},
                "id": "t1",
                "type": "tool_call",
            }
        ],
    ),
    ToolMessage(
        content=json.dumps(
            {
                "counts": {"raw": 4, "deduped": 3, "selected": 1},
                "papers": [
                    {
                        "paper_id": "arxiv-x",
                        "title": "T",
                        "authors": ["A"],
                        "abstract": "ab",
                        "url": "u",
                        "score": 9.0,
                        "reason": "r",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        tool_call_id="t1",
        name="search_papers_tool",
    ),
    AIMessage(content="今日导语"),
]


class _FakeSaverCM:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSaver:
    @staticmethod
    def from_conn_string(dsn: str) -> _FakeSaverCM:
        return _FakeSaverCM()


async def _make_factory() -> tuple[object, async_sessionmaker]:
    """连 docker PG，确保 schema + user(id=1)，返回 (engine, factory)。不可达则跳过。"""
    engine = create_async_engine(_PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # PG 不可达 → 跳过（非代码缺陷）
        await engine.dispose()
        pytest.skip(f"PG 不可达，跳过真 PG 回归：{exc}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        if await s.get(User, 1) is None:
            s.add(User(id=1, email="test@local", timezone="Asia/Shanghai"))
            await s.commit()
        await s.execute(delete(Push).where(Push.run_date == _TEST_DATE))
        await s.commit()
    return engine, factory


def test_daily_push_thread_busy_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    """task1 占住 running，task2(11:00) 触发 → busy 自拒；只发一次邮件；pushes 仅一行 success。"""

    async def _scenario() -> None:
        engine, factory = await _make_factory()
        try:
            started = asyncio.Event()
            release = asyncio.Event()

            class _FakeAgent:
                async def ainvoke(self, inp: object, config: object) -> dict:
                    started.set()
                    await release.wait()
                    return {"messages": _FAKE_MESSAGES}

            mock_send = AsyncMock()
            monkeypatch.setattr(jobs, "build_lit_agent", lambda **kw: _FakeAgent())
            monkeypatch.setattr(jobs, "AsyncPostgresSaver", _FakeSaver)
            monkeypatch.setattr(jobs, "send_email", mock_send)
            monkeypatch.setattr(jobs, "render_daily_push", lambda *a, **k: "<html></html>")
            monkeypatch.setattr(jobs, "_run_date", lambda settings: _TEST_DATE)
            settings = get_settings()

            t1 = asyncio.create_task(
                jobs.run_daily_push("cron", settings=settings, session_factory=factory)
            )
            await asyncio.wait_for(
                started.wait(), timeout=10
            )  # task1 已占位 running 并进入 ainvoke

            # 11:00 在 10:00 仍在跑时触发 → 同 thread_id 撞 running → 自拒
            res2 = await jobs.run_daily_push("retry", settings=settings, session_factory=factory)
            assert res2 == "busy"
            async with factory() as s:
                rows = (
                    (await s.execute(select(Push).where(Push.run_date == _TEST_DATE)))
                    .scalars()
                    .all()
                )
                assert len(rows) == 1 and rows[0].status == "running"

            release.set()
            res1 = await asyncio.wait_for(t1, timeout=10)
            assert res1 == "success"
            assert mock_send.await_count == 1  # 只发一次（task2 未发）

            async with factory() as s:
                rows = (
                    (await s.execute(select(Push).where(Push.run_date == _TEST_DATE)))
                    .scalars()
                    .all()
                )
                assert len(rows) == 1
                p = rows[0]
                assert p.status == "success"
                assert p.selected_count == 1 and p.email_sent is True
                assert p.fetched_count == 4 and p.deduped_count == 3
                await s.execute(delete(Push).where(Push.run_date == _TEST_DATE))
                await s.commit()
        finally:
            await engine.dispose()

    _run(_scenario())


def test_feedback_5min_idempotency() -> None:
    """同 (paper_id, signal) 5 分钟内重复 → 409。"""
    from fastapi import HTTPException

    from lit_agent.api.routes.feedback import FeedbackIn, post_feedback

    async def _scenario() -> None:
        engine, factory = await _make_factory()
        try:
            async with factory() as s:
                await s.execute(delete(Feedback).where(Feedback.paper_id == _TEST_PAPER))
                await s.commit()
            async with factory() as s:
                r1 = await post_feedback(FeedbackIn(paper_id=_TEST_PAPER, signal_type="up"), s)
                await s.commit()
                assert r1["status"] == "recorded"
            async with factory() as s:
                with pytest.raises(HTTPException) as ei:
                    await post_feedback(FeedbackIn(paper_id=_TEST_PAPER, signal_type="up"), s)
                assert ei.value.status_code == 409
            async with factory() as s:
                await s.execute(delete(Feedback).where(Feedback.paper_id == _TEST_PAPER))
                await s.commit()
        finally:
            await engine.dispose()

    _run(_scenario())
