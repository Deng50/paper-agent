"""chat sessions 列表 / 历史 messages 端点测试（M4 PR-2 Bug 2 / docs/04 §5.4-5.5）。

不连真 PG：monkeypatch AsyncPostgresSaver.from_conn_string + build_lit_agent。
不真扫 ./memory：monkeypatch settings.memory_dir → tmp_path。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

_HEADERS = {"Authorization": "Bearer test-token-123"}


class _FakeCheckpointCM:
    def __init__(self, saver: Any) -> None:
        self._saver = saver

    async def __aenter__(self) -> Any:
        return self._saver

    async def __aexit__(self, *args: Any) -> None:
        return None


class _FakeSnapshot:
    def __init__(self, messages: list[Any]) -> None:
        self.values = {"messages": messages}


class _FakeAgent:
    def __init__(self, messages: list[Any]) -> None:
        self._messages = messages

    async def aget_state(self, _config: dict[str, Any]) -> _FakeSnapshot:
        return _FakeSnapshot(self._messages)


def _make_md(path: Path, fm_lines: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm_lines}\n---\n\nbody\n", encoding="utf-8")


def test_list_chat_sessions_sorted_desc(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """3 个 md 按 last_active_at desc 排序返回。"""
    from lit_agent.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_dir", tmp_path)

    sessions_dir = tmp_path / "sessions"
    _make_md(
        sessions_dir / "2026-05-25" / "10-00-chat.md",
        "thread_id: uuid-A\ntrigger: chat\nstarted_at: '2026-05-25T10:00:00+00:00'\n"
        "last_active_at: '2026-05-25T10:30:00+00:00'\nmessage_count: 4\ntopics: []",
    )
    _make_md(
        sessions_dir / "2026-05-25" / "14-00-chat.md",
        "thread_id: uuid-B\ntrigger: chat\nstarted_at: '2026-05-25T14:00:00+00:00'\n"
        "last_active_at: '2026-05-25T15:42:11+00:00'\nmessage_count: 8\ntopics: []",
    )
    _make_md(
        sessions_dir / "2026-05-22" / "10-00-daily-push.md",
        "thread_id: daily_push:2026-05-22\ntrigger: daily-push\n"
        "started_at: '2026-05-22T10:00:00+00:00'\n"
        "last_active_at: '2026-05-22T10:05:00+00:00'\nmessage_count: 3\ntopics: []",
    )

    resp = client.get("/api/v1/chat/sessions", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    items = body["items"]
    assert items[0]["thread_id"] == "uuid-B"  # latest
    assert items[1]["thread_id"] == "uuid-A"
    assert items[2]["thread_id"] == "daily_push:2026-05-22"
    assert items[0]["message_count"] == 8


def test_list_chat_sessions_skip_corrupt_md(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """frontmatter 坏或无 thread_id 的 md 跳过，不抛错。"""
    from lit_agent.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_dir", tmp_path)

    sessions_dir = tmp_path / "sessions" / "2026-05-25"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "broken.md").write_text("not yaml content", encoding="utf-8")
    _make_md(sessions_dir / "no_tid.md", "trigger: chat\nlast_active_at: '2026-05-25T10:00:00'")
    _make_md(
        sessions_dir / "good.md",
        "thread_id: uuid-good\ntrigger: chat\nlast_active_at: '2026-05-25T11:00:00'",
    )

    resp = client.get("/api/v1/chat/sessions", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["thread_id"] == "uuid-good"


def test_list_chat_sessions_empty_dir(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """./memory/sessions 不存在 / 空 → items=[]，total=0。"""
    from lit_agent.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_dir", tmp_path)

    resp = client.get("/api/v1/chat/sessions", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0}


def _patch_saver(monkeypatch: pytest.MonkeyPatch, messages: list[Any]) -> None:
    import langgraph.checkpoint.postgres.aio as aio_mod

    from lit_agent.api.routes import chat as chat_module

    def _fake_from_conn_string(*_a: Any, **_kw: Any) -> _FakeCheckpointCM:
        return _FakeCheckpointCM(saver=object())

    monkeypatch.setattr(aio_mod.AsyncPostgresSaver, "from_conn_string", _fake_from_conn_string)
    monkeypatch.setattr(chat_module, "build_lit_agent", lambda **_kw: _FakeAgent(messages))


def test_get_chat_messages_preserve_tool_calls(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """保留 AIMessage.tool_calls + ToolMessage 全部（Bug 2 字面要求）。"""
    msgs = [
        HumanMessage(content="问硫化物", id="m1"),
        AIMessage(
            content="我搜一下",
            id="m2",
            tool_calls=[{"name": "search_memory_tool", "args": {"query": "sulfide"}, "id": "tc1"}],
        ),
        ToolMessage(content="[hits]", name="search_memory_tool", tool_call_id="tc1", id="m3"),
        AIMessage(content="找到 3 篇", id="m4"),
    ]
    _patch_saver(monkeypatch, msgs)

    resp = client.get("/api/v1/chat/sessions/uuid-test/messages", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["thread_id"] == "uuid-test"
    assert body["total"] == 4
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant"]
    # tool_calls 保留
    assert body["messages"][1]["tool_calls"][0]["name"] == "search_memory_tool"
    assert body["messages"][1]["tool_calls"][0]["args"]["query"] == "sulfide"
    # ToolMessage 保留 + name + tool_call_id
    assert body["messages"][2]["name"] == "search_memory_tool"
    assert body["messages"][2]["tool_call_id"] == "tc1"


def test_get_chat_messages_empty_thread(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """thread 无 checkpoint → messages=[] total=0（不抛错）。"""
    _patch_saver(monkeypatch, [])

    resp = client.get("/api/v1/chat/sessions/non-existent/messages", headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"thread_id": "non-existent", "messages": [], "total": 0}


def test_get_chat_messages_unauthorized() -> None:
    """无 Auth → 401（鉴权回归）。"""
    from fastapi.testclient import TestClient

    from lit_agent.api.main import create_app

    c = TestClient(create_app())
    resp = c.get("/api/v1/chat/sessions/any/messages")
    assert resp.status_code == 401
