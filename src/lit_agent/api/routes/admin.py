"""管理触发路由（M3 任务 5）：手动触发每日推送。

`POST /api/v1/admin/trigger/daily-push` 立即返回 202，后台 asyncio 任务跑 run_daily_push
（与 10:00 cron 同一函数、同一 thread_id 闸）。验收：202 → 3min 内 pushes.status=success。
"""

from __future__ import annotations

import asyncio
import datetime as dt

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from lit_agent.core.deps import AuthDep
from lit_agent.scheduler.jobs import run_daily_push

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[AuthDep])
_log = structlog.get_logger("admin")


class TriggerRequest(BaseModel):
    """daily-push 触发参数（docs/04 §8.1 字面 schema）。"""

    run_date: dt.date | None = Field(default=None, description="推送日期；缺省 = 今天")
    force: bool = Field(default=False, description="今日已 success 时仍强制重跑（覆盖）")


@router.post("/trigger/daily-push", status_code=202)
async def trigger_daily_push(
    request: Request, body: TriggerRequest | None = None
) -> dict[str, str]:
    """触发一次每日推送（异步后台执行，立即 202）。

    body 缺省时按今天 + force=False 跑（M3 既有 idempotent 行为）；force=True 时
    覆盖今日 success 状态（docs/04 §8.1 字面 / handover §3.9 同 thread checkpoint
    复用语义保留）。
    """
    body = body or TriggerRequest()
    task = asyncio.create_task(
        run_daily_push(
            triggered_by="manual",
            force=body.force,
            run_date_override=body.run_date,
        )
    )
    tasks: set[asyncio.Task[str]] = getattr(request.app.state, "bg_tasks", set())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    request.app.state.bg_tasks = tasks
    _log.info("daily_push_triggered", by="manual", force=body.force, run_date=str(body.run_date))
    return {
        "status": "accepted",
        "detail": (
            "daily-push 已触发（强制重跑）"
            if body.force
            else "daily-push 已触发，稍后查 /sessions 或邮箱"
        ),
    }
