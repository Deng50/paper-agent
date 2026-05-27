"""反馈路由（M3 任务 6 / M6 P0 扩 4 字段）：对推送论文 👍/👎 + 可选原因。

`POST /api/v1/feedback` 写 PG `feedback` 表。5 分钟幂等：同 (paper_id, signal_type)
5 分钟内重复 → 409（防误连点 / 重复提交）。M5 的画像自更新会读这张表的派生日志。

M6 P0：1-call 模型（owner Q1 a）—— 前端「点 👍 展开表单 → 提交」一次 POST 带：
- signal_type: up / down（必填）
- feedback_type: 8 个正向/负向类型 + other（可空）
- comment: 自由文本（可空）
- source: daily_push / chat_rerun / manual_trigger（可空，默认 daily_push）
- push_id: 关联 pushes.id（可空）
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from lit_agent.core.deps import AuthDep, DbDep
from lit_agent.db.models import Feedback

router = APIRouter(prefix="/api/v1", tags=["feedback"], dependencies=[AuthDep])
_log = structlog.get_logger("feedback")

_IDEMPOTENCY_WINDOW = dt.timedelta(minutes=5)
_WEIGHTS: dict[str, Decimal] = {"up": Decimal("1.00"), "down": Decimal("-1.00")}

# M6 P0 正向反馈类型（owner spec 字面）
_POSITIVE_TYPES = {
    "topic_relevant",
    "useful_method",
    "related_to_current_research",
    "want_follow_up",
    "high_quality",
    "other",
}
# M6 P0 负向反馈类型
_NEGATIVE_TYPES = {
    "topic_irrelevant",
    "low_quality",
    "too_theoretical",
    "too_experimental",
    "too_engineering",
    "duplicate",
    "not_current_focus",
    "other",
}
_ALL_TYPES = _POSITIVE_TYPES | _NEGATIVE_TYPES


class FeedbackIn(BaseModel):
    paper_id: str = Field(min_length=1, max_length=128)
    signal_type: Literal["up", "down"]
    # M6 P0 新增（全可选向后兼容）：
    feedback_type: str | None = Field(
        default=None, max_length=32, description="结构化反馈类型枚举字符串"
    )
    comment: str | None = Field(default=None, max_length=2000, description="自由文本原因")
    source: str | None = Field(
        default=None, max_length=32, description="daily_push / chat_rerun / manual_trigger"
    )
    push_id: int | None = Field(default=None, description="关联 pushes.id")


@router.post("/feedback", status_code=201)
async def post_feedback(body: FeedbackIn, db: DbDep) -> dict[str, str | int | None]:
    """记录一条反馈。5 分钟内同 paper+signal 重复 → 409。

    M6 P0 扩字段全 nullable，旧客户端只传 paper_id+signal_type 也正常工作。
    feedback_type 不在枚举内 → 400（防 prompt injection 进 profile）。
    """
    # M6 P0：feedback_type 枚举校验（防 free-form 污染 profile_update agent 输入）
    if body.feedback_type is not None and body.feedback_type not in _ALL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"feedback_type 必须在枚举内（or None）：{sorted(_ALL_TYPES)}",
        )

    cutoff = dt.datetime.now(dt.UTC) - _IDEMPOTENCY_WINDOW
    dup = (
        await db.execute(
            select(Feedback.id).where(
                Feedback.user_id == 1,
                Feedback.paper_id == body.paper_id,
                Feedback.signal_type == body.signal_type,
                Feedback.created_at >= cutoff,
            )
        )
    ).first()
    if dup is not None:
        raise HTTPException(status_code=409, detail="5 分钟内已提交过相同反馈。")

    db.add(
        Feedback(
            user_id=1,
            paper_id=body.paper_id,
            signal_type=body.signal_type,
            weight=_WEIGHTS[body.signal_type],
            feedback_type=body.feedback_type,
            comment=body.comment,
            source=body.source or "daily_push",
            push_id=body.push_id,
        )
    )
    _log.info(
        "feedback_recorded",
        paper_id=body.paper_id,
        signal=body.signal_type,
        feedback_type=body.feedback_type,
        has_comment=bool(body.comment),
        source=body.source,
        push_id=body.push_id,
    )
    return {
        "status": "recorded",
        "paper_id": body.paper_id,
        "signal_type": body.signal_type,
        "feedback_type": body.feedback_type,
        "push_id": body.push_id,
    }
