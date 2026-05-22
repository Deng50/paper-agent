"""反馈路由（M3 任务 6）：对推送论文 👍/👎。

`POST /api/v1/feedback` 写 PG `feedback` 表。5 分钟幂等：同 (paper_id, signal_type)
5 分钟内重复 → 409（防误连点 / 重复提交）。M5 的画像自更新会读这张表的派生日志。
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


class FeedbackIn(BaseModel):
    paper_id: str = Field(min_length=1, max_length=128)
    signal_type: Literal["up", "down"]


@router.post("/feedback", status_code=201)
async def post_feedback(body: FeedbackIn, db: DbDep) -> dict[str, str]:
    """记录一条反馈。5 分钟内同 paper+signal 重复 → 409。"""
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
        )
    )
    _log.info("feedback_recorded", paper_id=body.paper_id, signal=body.signal_type)
    return {"status": "recorded", "paper_id": body.paper_id, "signal_type": body.signal_type}
