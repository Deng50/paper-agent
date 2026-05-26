"""M5 chat-rerun 通路（反转 M4 §3.11，owner 拍板 Path B 正确方向）。

测试矩阵（owner 5 条要求映射）：
1. 「今天推送的不满意，帮我搜固态电池」→ chat_rerun + topic_override="固态电池" → trigger_push_pipeline
2. 「重新检索一批」→ chat_rerun + topic_override=None → trigger_push_pipeline
3. 「找几篇钠离子电池界面的新论文」→ search_papers（不触发 pipeline）
4. chat_rerun 成功后 → pushes 行/status/count/trigger/email/memory/frontend 同步
5. 当天已 success + force=True → 不复用旧结果

agent 行为（1/2/3）依赖 LLM 决策，**自动化测试只能验 skill 提示词包含必要启发式**
（grep 风），真 agent 验证由 owner 手测。

pipeline 行为（4/5）走机制层测试：mock run_daily_push 验工具传参；端到端走 mocked
PG smoke 验返回 shape。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

import lit_agent.scheduler.jobs as jobs
from lit_agent.agents.lit_agent import _make_trigger_push_pipeline_tool, build_lit_agent
from lit_agent.core.config import get_settings


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coro)
    return asyncio.run(coro)


# ────────────────────── tool 注册：chat_session_id 才解锁 ──────────────────────


def _extract_tool_names(skills: tuple[str, ...], chat_session_id: str | None) -> list[str]:
    with patch("lit_agent.agents.lit_agent.ChatAnthropic") as mock_model:
        mock_model.return_value = object()
        with patch("lit_agent.agents.lit_agent.create_react_agent") as mock_create:
            mock_create.return_value = object()
            build_lit_agent(skills=skills, chat_session_id=chat_session_id)
            return [t.name for t in mock_create.call_args.kwargs["tools"]]


def test_chat_session_id_unlocks_trigger_push_pipeline_tool() -> None:
    """chat 路由传 chat_session_id → tool 入 tools，agent 可发起 chat-rerun。"""
    names = _extract_tool_names(("daily_search", "memory_recall"), chat_session_id="uuid-chat-1")
    assert "trigger_push_pipeline_tool" in names


def test_default_no_chat_session_no_trigger_tool() -> None:
    """daily-push cron / sessions 路径不传 chat_session_id → 不解锁（向后兼容）。"""
    names = _extract_tool_names(("daily_search",), chat_session_id=None)
    assert "trigger_push_pipeline_tool" not in names
    # M3/M4 兼容：4 只读件套
    assert set(names) == {
        "search_papers_tool",
        "read_file_tool",
        "search_memory_tool",
        "list_dir_tool",
    }


def test_chat_session_id_does_not_unlock_write_file_tool() -> None:
    """chat-rerun 通路不应顺带解锁 write_file（仅 profile_update skill 解锁）。"""
    names = _extract_tool_names(("daily_search", "memory_recall"), chat_session_id="uuid-chat-2")
    assert "write_file_tool" not in names


# ────────────────────── skill 启发式 grep 测试 ──────────────────────


def _skill(name: str) -> str:
    return (Path(__file__).resolve().parent.parent / "skills" / f"{name}.skill.md").read_text(
        encoding="utf-8"
    )


def test_memory_recall_skill_has_chat_rerun_heuristic() -> None:
    """skill 含 trigger_push_pipeline 路由 + 关键判定信号 + 3-way 冲突判定。"""
    s = _skill("memory_recall")
    # 工具语义边界声明
    assert "trigger_push_pipeline" in s
    # 关键判定信号词必须在 skill 文本里（agent 才能识别 chat-rerun 意图）
    for phrase in ["重新检索", "重新搜", "重跑", "再找一批", "换一批", "这批", "今天推的"]:
        assert phrase in s, f"chat-rerun 判定信号词缺失: {phrase}"
    # 3-way 路由表必须在（chat-rerun / search_papers / search_memory）
    assert "3-way 路由树" in s or "3-way" in s
    # 防回归：不应再有「不能在对话里推送」的拒绝引导（M4 §3.11 已被反转）
    assert "我不能在对话里推送" not in s, "M4 §3.11 拒绝段必须已删（已反转）"


def test_memory_recall_skill_distinguishes_rerun_vs_new_topic() -> None:
    """skill 必须明示「重新/这批/今天推」走 trigger_push_pipeline，纯新方向走 search_papers。"""
    s = _skill("memory_recall")
    # chat-rerun 触发短语 + 工具名共存
    assert "chat-rerun" in s
    # search_papers 仍然是合法分支（不能误伤"找新方向"用法）
    assert "search_papers" in s
    assert "找新方向" in s or "新方向 / 主动浏览" in s


def test_daily_search_skill_has_topic_override_handling() -> None:
    """daily_search 收 chat-rerun 注入的「本次重新检索主题：{topic}」时优先用此方向。"""
    s = _skill("daily_search")
    assert "本次重新检索主题" in s
    assert "topic 是第一信号" in s or "优先于 profile" in s


# ────────────────────── run_daily_push topic_override 注入 ──────────────────────


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


def _patch_jobs_for_kickoff_capture(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
) -> None:
    """通用：mock 掉 agent / saver / PG factory，捕获 agent 收到的 HumanMessage。"""

    class _FakeAgent:
        async def ainvoke(self, inp: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            captured["kickoff"] = inp["messages"][0].content
            captured["thread_id"] = config["configurable"]["thread_id"]
            return {"messages": [AIMessage(content="ok-intro")]}

    monkeypatch.setattr(jobs, "build_lit_agent", lambda **kw: _FakeAgent())
    monkeypatch.setattr(jobs, "AsyncPostgresSaver", _FakeSaver)
    monkeypatch.setattr(jobs, "send_email", AsyncMock())
    monkeypatch.setattr(jobs, "render_daily_push", lambda *a, **k: "<html></html>")
    monkeypatch.setattr(jobs, "_run_date", lambda settings: dt.date(2099, 5, 27))

    async def _fake_claim(
        s: Any, run_date: Any, triggered_by: str, force: bool = False
    ) -> tuple[int, str]:
        captured["triggered_by"] = triggered_by
        captured["force"] = force
        return 1, "new"

    monkeypatch.setattr(jobs, "_claim_run", _fake_claim)

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def get(self, *a: object) -> None:
            return None

        async def commit(self) -> None:
            pass

    monkeypatch.setattr(jobs, "get_session_factory", lambda: lambda: _FakeSession())


def test_run_daily_push_topic_override_injects_into_kickoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """topic_override 非 None → HumanMessage 含「本次重新检索主题：{topic}」字面。"""
    captured: dict[str, Any] = {}
    _patch_jobs_for_kickoff_capture(monkeypatch, captured)
    settings = get_settings()
    status = _run(
        jobs.run_daily_push(
            triggered_by="chat_rerun",
            force=True,
            topic_override="固态电池",
            settings=settings,
        )
    )
    assert status == "success"
    assert "今天是 2099-05-27" in captured["kickoff"]
    assert "本次重新检索主题" in captured["kickoff"]
    assert "固态电池" in captured["kickoff"]
    assert captured["triggered_by"] == "chat_rerun"
    assert captured["force"] is True


def test_run_daily_push_no_topic_override_kickoff_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """topic_override=None → kickoff 是原始 cron 字面（向后兼容 cron / manual / retry 3 路径）。"""
    captured: dict[str, Any] = {}
    _patch_jobs_for_kickoff_capture(monkeypatch, captured)
    settings = get_settings()
    _run(jobs.run_daily_push(triggered_by="cron", settings=settings))
    assert captured["kickoff"] == "今天是 2099-05-27，执行每日推送。"
    assert "本次重新检索主题" not in captured["kickoff"]


# ────────────────────── trigger_push_pipeline_tool 端到端 ──────────────────────


def test_trigger_push_pipeline_tool_calls_run_daily_push_with_chat_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工具调用 → run_daily_push 收到 triggered_by="chat_rerun" + force=True + topic_override。"""
    captured: dict[str, Any] = {}

    async def _fake_run_daily_push(
        triggered_by: str = "cron",
        **kwargs: Any,
    ) -> str:
        captured["triggered_by"] = triggered_by
        captured["kwargs"] = kwargs
        return "success"

    monkeypatch.setattr("lit_agent.scheduler.jobs.run_daily_push", _fake_run_daily_push)
    monkeypatch.setattr("lit_agent.scheduler.jobs._run_date", lambda s: dt.date(2099, 5, 27))

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def execute(self, *a: object) -> Any:
            m = MagicMock()
            push = MagicMock()
            push.id = 42
            push.triggered_by = "chat_rerun"
            push.selected_count = 10
            push.email_sent = True
            push.selected_papers = [
                {"paper_id": "p1", "title": "T1", "url": "u1", "score": 8.5},
            ]
            push.error = None
            m.scalar_one_or_none.return_value = push
            return m

    monkeypatch.setattr("lit_agent.db.base.get_session_factory", lambda: lambda: _FakeSession())

    settings = get_settings()
    tool = _make_trigger_push_pipeline_tool(settings, "chat-uuid-abc")
    raw = _run(tool.ainvoke({"topic_override": "固态电池"}))
    payload = json.loads(raw)

    assert captured["triggered_by"] == "chat_rerun"
    assert captured["kwargs"]["force"] is True
    assert captured["kwargs"]["topic_override"] == "固态电池"
    assert payload["status"] == "success"
    assert payload["push_id"] == 42
    assert payload["selected_count"] == 10
    assert payload["email_sent"] is True
    assert payload["trigger"] == "chat_rerun"
    assert payload["chat_session_id"] == "chat-uuid-abc"
    assert len(payload["papers"]) == 1
    assert payload["papers"][0]["paper_id"] == "p1"


def test_trigger_push_pipeline_tool_topic_override_none_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """topic_override=None 时透传 None 给 run_daily_push（profile 默认偏好）。"""
    captured: dict[str, Any] = {}

    async def _fake_run_daily_push(triggered_by: str = "cron", **kwargs: Any) -> str:
        captured["kwargs"] = kwargs
        return "success"

    monkeypatch.setattr("lit_agent.scheduler.jobs.run_daily_push", _fake_run_daily_push)
    monkeypatch.setattr("lit_agent.scheduler.jobs._run_date", lambda s: dt.date(2099, 5, 27))

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def execute(self, *a: object) -> Any:
            m = MagicMock()
            m.scalar_one_or_none.return_value = None  # push 行未找到
            return m

    monkeypatch.setattr("lit_agent.db.base.get_session_factory", lambda: lambda: _FakeSession())

    settings = get_settings()
    tool = _make_trigger_push_pipeline_tool(settings, "chat-uuid-2")
    raw = _run(tool.ainvoke({"topic_override": None}))
    payload = json.loads(raw)

    assert captured["kwargs"]["topic_override"] is None
    # push 行不存在仍返回 status + error，不抛崩 chat
    assert payload["status"] == "success"
    assert "push row not found" in payload["error"]


def test_trigger_push_pipeline_tool_exception_returns_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_daily_push 抛 → 工具返回 failed JSON，不向上抛崩 chat agent。"""

    async def _broken(**kwargs: Any) -> str:
        raise RuntimeError("pipeline boom")

    monkeypatch.setattr("lit_agent.scheduler.jobs.run_daily_push", _broken)

    settings = get_settings()
    tool = _make_trigger_push_pipeline_tool(settings, "chat-uuid-3")
    raw = _run(tool.ainvoke({"topic_override": "钠离子电池"}))
    payload = json.loads(raw)
    assert payload["status"] == "failed"
    assert "pipeline boom" in payload["error"]
