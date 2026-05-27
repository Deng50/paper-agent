"""feedback extend: structured reason fields (M6 P0)

Revision ID: 0002_feedback_extend
Revises: 0001_initial
Create Date: 2026-05-26

加 4 个 nullable 列到 feedback 表，向后兼容（旧行 NULL，旧代码不感知新列）：
- feedback_type: 反馈类型枚举字符串（topic_relevant / low_quality / ...）
- comment: 用户自由文本原因（可空）
- source: daily_push / chat_rerun / manual_trigger（默认 daily_push）
- push_id: 关联 pushes.id（弱外键，便于聚合查询；NULL 表示未关联具体推送）
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_feedback_extend"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """向 feedback 表加 4 nullable 列。旧行 NULL，应用层兼容（M6 P0）。"""
    op.add_column(
        "feedback",
        sa.Column("feedback_type", sa.String(length=32), nullable=True),
    )
    op.add_column("feedback", sa.Column("comment", sa.Text(), nullable=True))
    op.add_column(
        "feedback",
        sa.Column("source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "feedback",
        sa.Column("push_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("idx_feedback_type", "feedback", ["feedback_type"], unique=False)
    op.create_index("idx_feedback_push_id", "feedback", ["push_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_feedback_push_id", table_name="feedback")
    op.drop_index("idx_feedback_type", table_name="feedback")
    op.drop_column("feedback", "push_id")
    op.drop_column("feedback", "source")
    op.drop_column("feedback", "comment")
    op.drop_column("feedback", "feedback_type")
