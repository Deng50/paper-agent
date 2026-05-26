"""M5 C4：feedback PG → ./memory/feedback/{date}.log 派生测试。

owner 决策 A4：daily cron 03:00 PG → 文件批量派生。

测试策略：
- _format_feedback_log_lines 是纯函数 → 无 PG 直接测格式 + 分组 + 时区
- derive_feedback_logs 端到端 smoke 跑真 PG（dev DB 含历史数据，不 assert 全局
  计数；仅检查 test-specific paper_id 出现在正确日期文件 + 文件可读）
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from collections.abc import Coroutine
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lit_agent.core.config import get_settings
from lit_agent.db.base import Base
from lit_agent.db.models import Feedback, User
from lit_agent.scheduler.jobs import _format_feedback_log_lines, derive_feedback_logs

_PG_URL = "postgresql+psycopg://lit:lit@localhost:5432/lit_agent"
_TEST_PAPERS = ("arxiv-m5fbtest-1", "arxiv-m5fbtest-2", "arxiv-m5fbtest-3")


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Windows SelectorEventLoop 兜底（psycopg 异步不兼容 Proactor）。"""
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coro)
    return asyncio.run(coro)


# ────────────────────── 纯函数测试（无 PG） ──────────────────────


def _make_feedback(paper_id: str, signal: str, weight: float, created_utc: dt.datetime) -> Feedback:
    """构造一个 Feedback 实例用作纯函数输入（不进 PG）。"""
    fb = Feedback(
        paper_id=paper_id,
        signal_type=signal,
        weight=Decimal(f"{weight:.2f}"),
        created_at=created_utc,
    )
    return fb


def test_format_groups_by_local_date_across_tz_boundary() -> None:
    """UTC 凌晨的反馈对 Asia/Shanghai 已是当天上午 → 同 group 进 5-27.log。"""
    tz = ZoneInfo("Asia/Shanghai")
    rows = [
        _make_feedback("p1", "up", 1.0, dt.datetime(2026, 5, 27, 2, 23, 45, tzinfo=dt.UTC)),
        _make_feedback("p2", "down", -1.0, dt.datetime(2026, 5, 27, 3, 45, 12, tzinfo=dt.UTC)),
        _make_feedback("p3", "up", 1.0, dt.datetime(2026, 5, 28, 2, 0, 0, tzinfo=dt.UTC)),
    ]
    by_date = _format_feedback_log_lines(rows, tz)
    assert set(by_date.keys()) == {dt.date(2026, 5, 27), dt.date(2026, 5, 28)}
    assert len(by_date[dt.date(2026, 5, 27)]) == 2
    assert len(by_date[dt.date(2026, 5, 28)]) == 1


def test_format_line_format_match_skill_protocol() -> None:
    """每行格式 = ISO datetime | signal | paper_id | signed weight。"""
    tz = ZoneInfo("Asia/Shanghai")
    row = _make_feedback("s2-abc123", "up", 1.0, dt.datetime(2026, 5, 27, 2, 23, 45, tzinfo=dt.UTC))
    by_date = _format_feedback_log_lines([row], tz)
    line = by_date[dt.date(2026, 5, 27)][0]
    # 本地 Shanghai 10:23:45
    assert line.startswith("2026-05-27T10:23:45")
    assert "+08:00" in line
    assert " | up | s2-abc123 | +1.00" in line


def test_format_negative_weight_sign() -> None:
    """down + 负权重 → '-1.00' 带显式负号。"""
    tz = ZoneInfo("Asia/Shanghai")
    row = _make_feedback("p1", "down", -1.0, dt.datetime(2026, 5, 27, 2, 0, 0, tzinfo=dt.UTC))
    line = _format_feedback_log_lines([row], tz)[dt.date(2026, 5, 27)][0]
    assert " | down | p1 | -1.00" in line


def test_format_empty_input() -> None:
    """无 row → 空 dict。"""
    tz = ZoneInfo("Asia/Shanghai")
    assert _format_feedback_log_lines([], tz) == {}


# ────────────────────── 端到端 smoke 测试（真 PG） ──────────────────────


async def _make_factory_and_cleanup() -> tuple[Any, async_sessionmaker]:
    engine = create_async_engine(_PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PG 不可达，跳过真 PG 回归：{exc}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        if await s.get(User, 1) is None:
            s.add(User(id=1, email="test@local", timezone="Asia/Shanghai"))
            await s.commit()
        # 清掉本测试的 paper_id（不动 owner 真数据 / 其他测试的数据）
        await s.execute(delete(Feedback).where(Feedback.paper_id.in_(_TEST_PAPERS)))
        await s.commit()
    return engine, factory


def test_derive_writes_test_paper_to_correct_date_file(tmp_path: Path) -> None:
    """smoke 端到端：插入 2 条不同日期的 test feedback → 各自 .log 文件含正确行。

    不 assert 全局文件计数（dev PG 共存其他数据）。仅检查 test-specific 行存在。
    """

    async def _scenario() -> None:
        engine, factory = await _make_factory_and_cleanup()
        try:
            settings = get_settings().model_copy(update={"memory_dir": tmp_path / "memory"})
            d1_utc = dt.datetime(2026, 5, 27, 2, 23, 45, tzinfo=dt.UTC)  # Shanghai 5-27 10:23
            d2_utc = dt.datetime(2026, 5, 28, 2, 0, 0, tzinfo=dt.UTC)  # Shanghai 5-28 10:00
            async with factory() as s:
                s.add_all(
                    [
                        Feedback(
                            paper_id=_TEST_PAPERS[0],
                            signal_type="up",
                            weight=Decimal("1.00"),
                            created_at=d1_utc,
                        ),
                        Feedback(
                            paper_id=_TEST_PAPERS[1],
                            signal_type="down",
                            weight=Decimal("-1.00"),
                            created_at=d2_utc,
                        ),
                    ]
                )
                await s.commit()

            # days 设大让 cutoff 包含 2026 旧数据（默认 days=30 会让 2026-05 数据失效）
            await derive_feedback_logs(days=10000, settings=settings, session_factory=factory)

            log_5_27 = settings.memory_dir / "feedback" / "2026-05-27.log"
            log_5_28 = settings.memory_dir / "feedback" / "2026-05-28.log"
            assert log_5_27.is_file()
            assert log_5_28.is_file()

            content_27 = log_5_27.read_text(encoding="utf-8")
            content_28 = log_5_28.read_text(encoding="utf-8")
            # 测试 paper_id 在对应日期文件
            assert f"| up | {_TEST_PAPERS[0]} | +1.00" in content_27
            assert f"| down | {_TEST_PAPERS[1]} | -1.00" in content_28
            # 时间戳本地化到 +08:00
            assert "+08:00" in content_27
        finally:
            await engine.dispose()

    _run(_scenario())
