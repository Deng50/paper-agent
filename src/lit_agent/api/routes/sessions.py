"""站内会话路由（M3 任务 5）：每日推送会话列表与详情。

每个 daily-push 即一个会话（thread_id=daily_push:DATE）。列表扫 `pushes` 表；
详情返回该 push 的精选论文卡片（selected_papers）+ 尽力从 LangGraph state 取导语。
对话历史的完整派生归档在 M4（session md）；M3 先让推送会话「呈现」出来。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from lit_agent.core.config import get_settings
from lit_agent.core.deps import AuthDep, DbDep
from lit_agent.db.models import Push

router = APIRouter(prefix="/api/v1", tags=["sessions"], dependencies=[AuthDep])
_log = structlog.get_logger("sessions")


class SessionSummary(BaseModel):
    run_date: dt.date
    thread_id: str
    status: str
    selected_count: int
    email_sent: bool
    triggered_by: str


class SessionDetail(SessionSummary):
    intro: str
    selected_papers: list[dict[str, Any]]
    queries: list[Any]
    error: str | None = None


def _thread_id(run_date: dt.date) -> str:
    return f"daily_push:{run_date.isoformat()}"


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(db: DbDep, limit: int = 30) -> list[SessionSummary]:
    """最近的每日推送会话（按日期倒序）。"""
    rows = (
        (await db.execute(select(Push).order_by(Push.run_date.desc()).limit(limit))).scalars().all()
    )
    return [
        SessionSummary(
            run_date=p.run_date,
            thread_id=_thread_id(p.run_date),
            status=p.status,
            selected_count=p.selected_count,
            email_sent=p.email_sent,
            triggered_by=p.triggered_by,
        )
        for p in rows
    ]


async def _read_intro(run_date: dt.date) -> str:
    """尽力从 LangGraph state 取该 thread 最后一条 AI 文本作导语。失败返回空串。"""
    try:
        from langchain_core.messages import AIMessage
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        from lit_agent.agents.lit_agent import build_lit_agent

        settings = get_settings()
        async with AsyncPostgresSaver.from_conn_string(settings.psycopg_dsn) as saver:
            agent = build_lit_agent(checkpointer=saver, settings=settings)
            snap = await agent.aget_state({"configurable": {"thread_id": _thread_id(run_date)}})
        for m in reversed(snap.values.get("messages", [])):
            if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
                return m.content.strip()
    except Exception as exc:  # state 读不到不致命
        _log.warning("read_intro_failed", error=str(exc))
    return ""


@router.get("/sessions/{run_date}", response_model=SessionDetail)
async def get_session(run_date: dt.date, db: DbDep) -> SessionDetail:
    """某天推送会话详情：精选卡片 + 导语。"""
    push = (
        await db.execute(select(Push).where(Push.user_id == 1, Push.run_date == run_date))
    ).scalar_one_or_none()
    if push is None:
        raise HTTPException(status_code=404, detail=f"无 {run_date} 的推送会话。")
    return SessionDetail(
        run_date=push.run_date,
        thread_id=_thread_id(push.run_date),
        status=push.status,
        selected_count=push.selected_count,
        email_sent=push.email_sent,
        triggered_by=push.triggered_by,
        intro=await _read_intro(push.run_date),
        selected_papers=push.selected_papers or [],
        queries=push.queries or [],
        error=push.error,
    )
