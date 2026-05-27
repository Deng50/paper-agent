"""PostgreSQL 仅 3 张表：users / pushes / feedback（03_data_model §1）。

❌ 不建 messages / locks / sessions / job_logs / events —— 对话 state 与并发
交给 LangGraph 自管表（我们不画不动）。详见 CLAUDE.md §2。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lit_agent.db.base import Base


class User(Base):
    """单用户兜底（MVP id 恒为 1）。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Push(Base):
    """每日推送审计 + 可解释清单（吸收 job_logs 与 manifest）。"""

    __tablename__ = "pushes"
    __table_args__ = (
        UniqueConstraint("user_id", "run_date", name="uq_pushes_user_date"),
        Index("idx_pushes_run_date", "run_date"),
        Index("idx_pushes_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, default=1
    )
    run_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(16), nullable=False, default="cron")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    queries: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    source_status: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deduped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_papers: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    email_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Feedback(Base):
    """反馈事件（按 paper_id / signal_type 索引做统计）。

    M6 P0 起加 4 列（feedback_type / comment / source / push_id），均 nullable
    向后兼容（旧行全 NULL；旧 22:55 派生 log 与 profile_update agent 都能读）。
    """

    __tablename__ = "feedback"
    __table_args__ = (
        Index("idx_feedback_paper", "paper_id"),
        Index("idx_feedback_signal", "signal_type"),
        Index("idx_feedback_ts", "created_at"),
        Index("idx_feedback_type", "feedback_type"),
        Index("idx_feedback_push_id", "push_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, default=1
    )
    paper_id: Mapped[str] = mapped_column(String(128), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    # M6 P0 新增：结构化反馈原因（全 nullable，向后兼容老行）
    feedback_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    push_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
