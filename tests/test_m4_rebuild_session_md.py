"""scripts/rebuild_session_md.py 单测（M4 task 6 / Q9）。

不连 PG：monkeypatch AsyncPostgresSaver.from_conn_string + build_lit_agent。
覆盖关键路径：abort-on-existing / no-force / dry-run / 实写 / 空 messages。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage


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


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    messages: list[Any],
) -> None:
    """mock 掉 PG saver / build_lit_agent，让 rebuild_one 不真连数据库。"""
    from scripts import rebuild_session_md as mod

    class _Saver:
        pass

    monkeypatch.setattr(
        mod.AsyncPostgresSaver, "from_conn_string", lambda *_a, **_k: _FakeCheckpointCM(_Saver())
    )
    monkeypatch.setattr(mod, "build_lit_agent", lambda **_kw: _FakeAgent(messages))


def test_rebuild_dry_run_with_messages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """有 messages + --dry-run → 0；不创建 md。"""
    from scripts.rebuild_session_md import rebuild_one

    # 重定向 memory_dir 防写真目录
    from lit_agent.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_dir", tmp_path)

    _patch_common(
        monkeypatch,
        [HumanMessage(content="hi"), AIMessage(content="hello")],
    )
    rc = asyncio.run(rebuild_one("test-thread-uuid", dry_run=True))
    assert rc == 0
    captured = capsys.readouterr().out
    assert "[plan]" in captured and "[dry-run]" in captured
    assert (
        not any((tmp_path / "sessions").rglob("*.md")) if (tmp_path / "sessions").exists() else True
    )


def test_rebuild_no_messages_abort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """checkpoint 内无 messages → abort 退出码 1。"""
    from scripts.rebuild_session_md import rebuild_one

    from lit_agent.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_dir", tmp_path)

    _patch_common(monkeypatch, [])
    rc = asyncio.run(rebuild_one("empty-thread"))
    assert rc == 1
    assert "无 messages" in capsys.readouterr().out


def test_rebuild_existing_md_no_force_abort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """已有 md + 无 --force → abort 退出码 1，不调 saver。"""
    from scripts.rebuild_session_md import rebuild_one

    from lit_agent.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_dir", tmp_path)

    fake_md = tmp_path / "sessions" / "2026-05-25" / "12-00-chat.md"
    fake_md.parent.mkdir(parents=True)
    fake_md.write_text("---\nthread_id: existing-uuid\ntrigger: chat\n---\n", encoding="utf-8")

    _patch_common(monkeypatch, [HumanMessage(content="x")])
    rc = asyncio.run(rebuild_one("existing-uuid"))
    assert rc == 1
    assert "已存在" in capsys.readouterr().out
    assert fake_md.exists()


def test_rebuild_force_overwrites(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """已有 md + --force → 在原路径原子重建，返回 0。"""
    from scripts.rebuild_session_md import rebuild_one

    from lit_agent.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "memory_dir", tmp_path)

    fake_md = tmp_path / "sessions" / "2026-05-25" / "13-00-chat.md"
    fake_md.parent.mkdir(parents=True)
    fake_md.write_text("---\nthread_id: force-uuid\n---\nold body\n", encoding="utf-8")

    _patch_common(
        monkeypatch,
        [HumanMessage(content="new q"), AIMessage(content="new a")],
    )
    rc = asyncio.run(rebuild_one("force-uuid", force=True))
    assert rc == 0
    captured = capsys.readouterr().out
    assert "[done]" in captured
    new_mds = list((tmp_path / "sessions").rglob("*.md"))
    assert new_mds == [fake_md]
    assert all("new" in m.read_text(encoding="utf-8") for m in new_mds)


def test_rebuild_force_preserves_archive_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import rebuild_session_md as mod

    from lit_agent.core.config import get_settings

    monkeypatch.setattr(get_settings(), "memory_dir", tmp_path)
    archive = tmp_path / "sessions" / "2026-05-25" / "13-00-chat.md"
    archive.parent.mkdir(parents=True)
    original = "---\nthread_id: recover-me\ntitle: My research\n---\nold body\n"
    archive.write_text(original, encoding="utf-8")
    _patch_common(monkeypatch, [HumanMessage(content="new question")])

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(mod, "derive_session_md", fail)
    with pytest.raises(OSError, match="disk full"):
        asyncio.run(mod.rebuild_one("recover-me", force=True))
    assert archive.read_text(encoding="utf-8") == original
