"""DELETE /api/v1/sessions/{thread_id} 测试（M4 task / docs/04 §5.3 / Q8）。

owner 拍板路径：daily_push: 拒删；先 md 后 PG；PG 失败 log warning 仍 204。
mock AsyncPostgresSaver 避免测试时真连 PG。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_HEADERS = {"Authorization": "Bearer test-token-123"}


class _FakeCheckpointCM:
    """async context manager 模拟 AsyncPostgresSaver.from_conn_string。"""

    def __init__(self, saver: Any) -> None:
        self._saver = saver

    async def __aenter__(self) -> Any:
        return self._saver

    async def __aexit__(self, *args: Any) -> None:
        return None


class _FakeSaver:
    """saver 模拟：记录 adelete_thread 调用 + 可选注入异常。"""

    def __init__(self, raise_on_delete: Exception | None = None) -> None:
        self.deleted_thread_ids: list[str] = []
        self.raise_on_delete = raise_on_delete

    async def adelete_thread(self, thread_id: str) -> None:
        if self.raise_on_delete is not None:
            raise self.raise_on_delete
        self.deleted_thread_ids.append(thread_id)


def _patch_saver(monkeypatch: pytest.MonkeyPatch, fake_saver: _FakeSaver) -> None:
    """统一 monkeypatch AsyncPostgresSaver.from_conn_string → _FakeCheckpointCM。"""
    import langgraph.checkpoint.postgres.aio as aio_mod

    def _fake_from_conn_string(*_args: Any, **_kwargs: Any) -> _FakeCheckpointCM:
        return _FakeCheckpointCM(fake_saver)

    monkeypatch.setattr(aio_mod.AsyncPostgresSaver, "from_conn_string", _fake_from_conn_string)


def test_delete_daily_push_rejected(client: TestClient) -> None:
    """daily_push: 前缀 → 400 + DAILY_PUSH_NOT_DELETABLE（PG pushes 审计需保留）。"""
    resp = client.delete("/api/v1/sessions/daily_push:2026-05-22", headers=_HEADERS)
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("code") == "DAILY_PUSH_NOT_DELETABLE"
    assert body.get("status") == 400


def test_delete_chat_session_md_and_pg(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """chat thread → md 删 + saver.adelete_thread 调 + 204。"""
    from lit_agent.api.routes import sessions as sessions_module

    fake_md = tmp_path / "2026-05-25" / "10-00-chat.md"
    fake_md.parent.mkdir(parents=True)
    fake_md.write_text(
        "---\nthread_id: abc-uuid-test\ntrigger: chat\nmessage_count: 0\n---\n\nbody\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sessions_module, "find_existing_by_thread", lambda _tid, _settings: fake_md)
    fake_saver = _FakeSaver()
    _patch_saver(monkeypatch, fake_saver)

    resp = client.delete("/api/v1/sessions/abc-uuid-test", headers=_HEADERS)
    assert resp.status_code == 204
    assert not fake_md.exists()
    assert fake_saver.deleted_thread_ids == ["abc-uuid-test"]


def test_delete_chat_session_pg_fail_final_consistency(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """md 删成功 + PG 删失败 → 仍 204（log warning 最终一致；orphan PG 待运维清）。"""
    from lit_agent.api.routes import sessions as sessions_module

    fake_md = tmp_path / "2026-05-25" / "11-00-chat.md"
    fake_md.parent.mkdir(parents=True)
    fake_md.write_text("---\nthread_id: xyz\n---\n", encoding="utf-8")

    monkeypatch.setattr(sessions_module, "find_existing_by_thread", lambda _tid, _settings: fake_md)
    fake_saver = _FakeSaver(raise_on_delete=RuntimeError("pg down"))
    _patch_saver(monkeypatch, fake_saver)

    resp = client.delete("/api/v1/sessions/xyz-uuid-test", headers=_HEADERS)
    assert resp.status_code == 204
    assert not fake_md.exists()


def test_delete_chat_session_no_md(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """md 不存在 → 仍走 PG 删，返回 204。"""
    from lit_agent.api.routes import sessions as sessions_module

    monkeypatch.setattr(sessions_module, "find_existing_by_thread", lambda _tid, _settings: None)
    fake_saver = _FakeSaver()
    _patch_saver(monkeypatch, fake_saver)

    resp = client.delete("/api/v1/sessions/no-md-uuid", headers=_HEADERS)
    assert resp.status_code == 204
    assert fake_saver.deleted_thread_ids == ["no-md-uuid"]


def test_delete_unauthorized() -> None:
    """无 Auth → 401（与 M3 既有鉴权路径一致）。"""
    from fastapi.testclient import TestClient

    from lit_agent.api.main import create_app

    c = TestClient(create_app())
    resp = c.delete("/api/v1/sessions/some-thread")
    assert resp.status_code == 401
