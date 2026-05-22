"""系统路由：/health 与 /status（M1 任务 6）。

/status 真 ping 四项依赖（PG / memory_dir / paper_search_mcp / anthropic），
每项独立 try/except —— /status 自身永不 500，只如实汇报各依赖健康。
"""

from __future__ import annotations

import time
from pathlib import Path

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from lit_agent import __version__
from lit_agent.core.config import get_settings
from lit_agent.core.deps import AuthDep
from lit_agent.db.base import get_engine

router = APIRouter()
_log = structlog.get_logger("system")


class Check(BaseModel):
    ok: bool
    latency_ms: int | None = None
    detail: str | None = None
    paper_count: int | None = None
    session_count: int | None = None


class SchedulerInfo(BaseModel):
    running: bool
    next_daily_push_at: str | None = None


class StatusResponse(BaseModel):
    status: str  # ok | degraded | error
    version: str
    checks: dict[str, Check]
    scheduler: SchedulerInfo


@router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """无需鉴权的探活。"""
    return {"status": "ok"}


async def _check_postgres() -> Check:
    t0 = time.perf_counter()
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return Check(ok=True, latency_ms=_ms(t0))
    except Exception as exc:
        return Check(ok=False, latency_ms=_ms(t0), detail=str(exc))


def _check_memory_dir(memory_dir: Path) -> Check:
    try:
        if not memory_dir.is_dir():
            return Check(ok=False, detail=f"memory dir not found: {memory_dir}")
        papers = memory_dir / "papers"
        sessions = memory_dir / "sessions"
        paper_count = sum(1 for _ in papers.rglob("*.md")) if papers.is_dir() else 0
        session_count = sum(1 for _ in sessions.rglob("*.md")) if sessions.is_dir() else 0
        return Check(ok=True, paper_count=paper_count, session_count=session_count)
    except Exception as exc:
        return Check(ok=False, detail=str(exc))


def _check_paper_search_mcp(cmd: str) -> Check:
    # M2 才接入 paper-search-mcp。M1 未配置时如实标记，不伪装健康。
    if not cmd.strip():
        return Check(ok=False, detail="not configured (wired in M2)")
    return Check(ok=True, detail=f"configured: {cmd}")


async def _check_anthropic(api_key: str, base_url: str = "") -> Check:
    t0 = time.perf_counter()
    try:
        from anthropic import AsyncAnthropic

        # base_url 留空走官方；填了走中转网关（注意填根域名，SDK 自拼 /v1/messages）。
        client = AsyncAnthropic(api_key=api_key, base_url=base_url or None, timeout=15.0)
        try:
            # 首选廉价探针：列模型，验连通 + 鉴权，不烧 token。
            await client.models.list(limit=1)
            return Check(ok=True, latency_ms=_ms(t0), detail="models.list ok")
        except Exception as list_exc:
            # 官方 API 直接抛出失败；中转网关常不实现 /v1/models，
            # 退化为 1-token messages 探针（顺带验证目标模型可用），近乎零成本。
            if not base_url:
                raise
            await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return Check(
                ok=True,
                latency_ms=_ms(t0),
                detail=f"messages probe ok (models.list unsupported by gateway: {list_exc})",
            )
    except Exception as exc:
        return Check(ok=False, latency_ms=_ms(t0), detail=str(exc))


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _scheduler_info(request: Request) -> SchedulerInfo:
    """从 app.state.scheduler（M3 起用）读运行态与下次推送时间。"""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None or not scheduler.running:
        return SchedulerInfo(running=False, next_daily_push_at=None)
    job = scheduler.get_job("daily_push")
    nxt = getattr(job, "next_run_time", None) if job else None
    return SchedulerInfo(running=True, next_daily_push_at=nxt.isoformat() if nxt else None)


@router.get(
    "/api/v1/status", response_model=StatusResponse, tags=["system"], dependencies=[AuthDep]
)
async def status(request: Request) -> StatusResponse:
    settings = get_settings()
    checks: dict[str, Check] = {
        "postgres": await _check_postgres(),
        "memory_dir": _check_memory_dir(settings.memory_dir),
        "paper_search_mcp": _check_paper_search_mcp(settings.paper_search_mcp_cmd),
        "anthropic": await _check_anthropic(
            settings.anthropic_api_key, settings.anthropic_base_url
        ),
    }

    # paper_search_mcp 未配置（M1）记为 degraded，不算 error。
    required_ok = all(checks[k].ok for k in ("postgres", "memory_dir", "anthropic"))
    if required_ok and checks["paper_search_mcp"].ok:
        overall = "ok"
    elif required_ok:
        overall = "degraded"
    else:
        overall = "error"

    return StatusResponse(
        status=overall,
        version=__version__,
        checks=checks,
        scheduler=_scheduler_info(request),
    )
