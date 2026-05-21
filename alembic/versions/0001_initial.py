"""initial schema: users / pushes / feedback

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-21

3 张表（03_data_model §1）。LangGraph 自管的 checkpoint 表由 checkpointer.setup()
建立，不在此迁移内。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Shanghai"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pushes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("triggered_by", sa.String(length=16), nullable=False, server_default="cron"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("queries", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_status", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deduped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_papers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("email_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "run_date", name="uq_pushes_user_date"),
    )
    op.create_index("idx_pushes_run_date", "pushes", ["run_date"])
    op.create_index("idx_pushes_status", "pushes", ["status"])

    op.create_table(
        "feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("paper_id", sa.String(length=128), nullable=False),
        sa.Column("signal_type", sa.String(length=16), nullable=False),
        sa.Column("weight", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_feedback_paper", "feedback", ["paper_id"])
    op.create_index("idx_feedback_signal", "feedback", ["signal_type"])
    op.create_index("idx_feedback_ts", "feedback", ["created_at"])

    # 单用户兜底：插入 id=1（03_data_model §1.2）。邮箱占位，运行时由 .env 覆盖语义。
    op.execute("INSERT INTO users (id, email) VALUES (1, 'me@example.com') ON CONFLICT DO NOTHING")


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("pushes")
    op.drop_table("users")
