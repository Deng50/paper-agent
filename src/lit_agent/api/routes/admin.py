"""管理触发路由（M3 任务 5）：手动触发每日推送。

`POST /api/v1/admin/trigger/daily-push` 立即返回 202，后台 asyncio 任务跑 run_daily_push
（与 10:00 cron 同一函数、同一 thread_id 闸）。验收：202 → 3min 内 pushes.status=success。
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Request

from lit_agent.core.deps import AuthDep
from lit_agent.scheduler.jobs import run_daily_push

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[AuthDep])
_log = structlog.get_logger("admin")


@router.post("/trigger/daily-push", status_code=202)
async def trigger_daily_push(request: Request) -> dict[str, str]:
    """触发一次每日推送（异步后台执行，立即 202）。"""
    task = asyncio.create_task(run_daily_push(triggered_by="manual"))
    # 持引用防 GC；完成后从集合移除。
    tasks: set[asyncio.Task[str]] = getattr(request.app.state, "bg_tasks", set())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    request.app.state.bg_tasks = tasks
    _log.info("daily_push_triggered", by="manual")
    return {"status": "accepted", "detail": "daily-push 已触发，稍后查 /sessions 或邮箱"}
