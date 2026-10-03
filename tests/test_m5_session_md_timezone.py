"""M5 时区 bug fix：session md 文件名 + frontmatter 用 Asia/Shanghai 而非 UTC。

修复前：北京 15:20 chat → UTC 07:20 → 文件名 `07-20-chat.md`（差 8 小时，文件名与
真实时间错位；mtime 排序 + owner 目视回溯都会被误导）。

修复后：北京 15:20 → 路径 `2026-05-26/15-20-chat.md`，frontmatter 时间戳带 `+08:00`。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage

from lit_agent.core.config import Settings
from lit_agent.tools.session_md import (
    derive_session_md,
    session_md_path,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        memory_dir=tmp_path / "memory",
        skills_dir=tmp_path / "skills",
    )


def test_session_md_path_utc_input_converts_to_shanghai() -> None:
    """tz-aware UTC datetime → 路径基于本地（Asia/Shanghai）日期 + HH-MM。"""
    # UTC 07:20 = Asia/Shanghai 15:20（owner bug 报告字面）
    utc_dt = dt.datetime(2026, 5, 26, 7, 20, 0, tzinfo=dt.UTC)
    s = _settings(Path("/tmp/fake"))
    path = session_md_path("chat-uuid-1", utc_dt, settings=s)
    assert path.name.startswith("15-20-chat-")
    assert path.parent.name == "2026-05-26"


def test_session_md_path_naive_input_used_as_is() -> None:
    """naive datetime → 视作已是本地时间，不再额外转换（向后兼容老测试 fixture）。"""
    naive = dt.datetime(2026, 5, 26, 15, 20, 0)
    s = _settings(Path("/tmp/fake"))
    path = session_md_path("chat-uuid-1", naive, settings=s)
    assert path.name.startswith("15-20-chat-")


def test_session_md_path_daily_push_trigger() -> None:
    """daily_push: 前缀的 thread_id → 文件名后缀 daily-push（trigger_of 协议）。"""
    utc_dt = dt.datetime(2026, 5, 26, 2, 0, 0, tzinfo=dt.UTC)  # Shanghai 10:00
    s = _settings(Path("/tmp/fake"))
    path = session_md_path("daily_push:2026-05-26", utc_dt, settings=s)
    assert path.name.startswith("10-00-daily-push-")


def test_derive_session_md_writes_local_tz_frontmatter(tmp_path: Path) -> None:
    """derive_session_md 写的 frontmatter 时间戳必须带 +08:00，路径用本地 HH-MM。"""
    s = _settings(tmp_path)
    (tmp_path / "memory" / "sessions").mkdir(parents=True)
    utc_now = dt.datetime(2026, 5, 26, 7, 20, 30, tzinfo=dt.UTC)  # Shanghai 15:20:30

    msgs = [HumanMessage(content="测试时区 fix")]
    path = derive_session_md("chat-tz-test", msgs, settings=s, now=utc_now)

    assert path is not None
    # 路径用本地时间命名
    assert path.name.startswith("15-20-chat-")
    assert path.parent.name == "2026-05-26"

    # frontmatter 含本地时区时间戳
    content = path.read_text(encoding="utf-8")
    assert "+08:00" in content
    assert "2026-05-26T15:20:30" in content
    # 不应该再有 +00:00 UTC 标记（除非别处其他字段，这里只测 derive 写的）
    assert "+00:00" not in content


def test_derive_session_md_handles_naive_now(tmp_path: Path) -> None:
    """naive now → 视作本地，路径 + frontmatter 一致（不抛 tzinfo None 错）。"""
    s = _settings(tmp_path)
    (tmp_path / "memory" / "sessions").mkdir(parents=True)
    naive_now = dt.datetime(2026, 5, 26, 15, 20, 30)

    msgs = [HumanMessage(content="naive 测试")]
    path = derive_session_md("chat-naive-test", msgs, settings=s, now=naive_now)

    assert path is not None
    assert path.name.startswith("15-20-chat-")


def test_real_world_owner_bug_scenario(tmp_path: Path) -> None:
    """owner 报告字面：北京 15:20 chat → 旧 bug 文件名 07-20；修复后 15-20。"""
    s = _settings(tmp_path)
    (tmp_path / "memory" / "sessions").mkdir(parents=True)

    # 模拟生产环境 datetime.now(UTC) 的真实行为
    beijing_1520 = dt.datetime(2026, 5, 26, 15, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    utc_equivalent = beijing_1520.astimezone(dt.UTC)
    assert utc_equivalent.hour == 7
    assert utc_equivalent.minute == 20

    msgs = [HumanMessage(content="bug 复现")]
    path = derive_session_md("owner-bug", msgs, settings=s, now=utc_equivalent)
    assert path is not None
    assert path.name.startswith("15-20-chat-")  # 修复后正确显示北京时间
    assert path.name != "07-20-chat.md"  # 不再被 UTC 误导
