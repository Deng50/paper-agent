"""M5 C6：run_profile_update 调用 build_lit_agent 传对 skills + 正确 thread_id。

mock build_lit_agent + AsyncPostgresSaver，不连真 PG / 真 Anthropic；只验证 cron 入口
按 A1 决策传 skills=("profile_update",) + thread_id 形如 "profile_update:{date}"。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

import lit_agent.scheduler.jobs as jobs
from lit_agent.core.config import get_settings


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coro)
    return asyncio.run(coro)


class _FakeSaverCM:
    async def __aenter__(self) -> Any:
        m = MagicMock()
        m.adelete_thread = AsyncMock(return_value=None)
        return m

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSaver:
    @staticmethod
    def from_conn_string(dsn: str) -> _FakeSaverCM:
        return _FakeSaverCM()


_TEST_DATE = dt.date(2099, 5, 27)


def test_run_profile_update_calls_build_with_profile_update_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1：cron 入口必须传 skills=("profile_update",)，否则 write_file_tool 不会被注册。"""
    captured: dict[str, Any] = {}

    class _FakeAgent:
        async def ainvoke(self, inp: object, config: dict[str, Any]) -> dict[str, Any]:
            captured["config"] = config
            return {"messages": [AIMessage(content="ok")]}

    def _fake_build(**kwargs: Any) -> _FakeAgent:
        captured["build_kwargs"] = kwargs
        return _FakeAgent()

    monkeypatch.setattr(jobs, "build_lit_agent", _fake_build)
    monkeypatch.setattr(jobs, "AsyncPostgresSaver", _FakeSaver)
    monkeypatch.setattr(jobs, "_run_date", lambda settings: _TEST_DATE)

    settings = get_settings()
    result = _run(jobs.run_profile_update(settings=settings))

    assert result == "success"
    assert captured["build_kwargs"]["skills"] == ("profile_update",)
    assert captured["config"]["configurable"]["thread_id"] == "profile_update:2099-05-27"


def test_run_profile_update_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent 抛错 → 返回 'failed: {exc}'，不再次崩 scheduler。"""

    class _BrokenAgent:
        async def ainvoke(self, inp: object, config: object) -> dict:
            raise RuntimeError("agent boom")

    monkeypatch.setattr(jobs, "build_lit_agent", lambda **_kw: _BrokenAgent())
    monkeypatch.setattr(jobs, "AsyncPostgresSaver", _FakeSaver)
    monkeypatch.setattr(jobs, "_run_date", lambda settings: _TEST_DATE)

    settings = get_settings()
    result = _run(jobs.run_profile_update(settings=settings))

    assert result.startswith("failed:")
    assert "agent boom" in result


def test_scheduler_registers_profile_update_cron() -> None:
    """A1：create_scheduler 在 11:30 hour=11/minute=30 注册 profile_update job。"""
    scheduler = jobs.create_scheduler()
    try:
        job = scheduler.get_job("profile_update")
        assert job is not None
        # APScheduler CronTrigger 字段
        trigger = job.trigger
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "11"
        assert fields.get("minute") == "30"
    finally:
        scheduler.shutdown(wait=False) if scheduler.running else None
