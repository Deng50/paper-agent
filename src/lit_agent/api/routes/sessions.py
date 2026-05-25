"""站内会话路由（M3 任务 5）：每日推送会话列表与详情。

每个 daily-push 即一个会话（thread_id=daily_push:DATE）。列表扫 `pushes` 表；
详情返回该 push 的精选论文卡片（selected_papers）+ 尽力从 LangGraph state 取导语。
对话历史的完整派生归档在 M4（session md）；M3 先让推送会话「呈现」出来。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from lit_agent.core.config import get_settings
from lit_agent.core.deps import AuthDep, DbDep
from lit_agent.db.models import Push
from lit_agent.tools.session_md import find_existing_by_thread, trigger_of

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


@router.delete("/sessions/{thread_id}", status_code=204)
async def delete_session(thread_id: str) -> Response:
    """硬删 chat 会话（M4 task / docs/04 §5.3）。

    Owner 拍板 Q8 最终一致：
    1. daily_push: 前缀 → 400 DAILY_PUSH_NOT_DELETABLE（PG pushes 审计需保留）
    2. 先删 md（用户感知层 = 列表立即不可见）
    3. 再删 LangGraph checkpoint（PG 三张自管表 by adelete_thread）
    4. PG 删失败仍返回 204 + log warning；orphan checkpoint state 由后续运维兜底
       （thread_id UUID 不复用 = 不影响功能）
    """
    if trigger_of(thread_id) == "daily-push":
        exc = HTTPException(status_code=400, detail="daily-push 会话不可删（PG pushes 审计需保留）")
        exc.code = "DAILY_PUSH_NOT_DELETABLE"  # type: ignore[attr-defined]
        raise exc

    settings = get_settings()
    md_path = find_existing_by_thread(thread_id, settings)
    if md_path is not None and md_path.exists():
        try:
            md_path.unlink()
            _log.info("session_md_deleted", thread_id=thread_id, path=str(md_path))
        except OSError as exc:
            _log.error("session_md_delete_failed", thread_id=thread_id, error=str(exc))
            raise HTTPException(status_code=500, detail="无法删除会话归档") from exc

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(settings.psycopg_dsn) as saver:
            await saver.adelete_thread(thread_id)
        _log.info("checkpoint_deleted", thread_id=thread_id)
    except Exception as exc:
        _log.warning(
            "checkpoint_delete_failed_orphan",
            thread_id=thread_id,
            md_path=str(md_path) if md_path else None,
            error=str(exc),
        )

    return Response(status_code=204)
