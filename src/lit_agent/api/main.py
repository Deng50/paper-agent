"""FastAPI 应用装配（M1 任务 7）。

把 config / logging / RFC7807 / trace_id / 路由 / checkpointer 接线串起来。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from lit_agent.api.middleware import TraceIDMiddleware, register_exception_handlers
from lit_agent.api.routes import admin, chat, feedback, sessions, system
from lit_agent.core.config import get_settings
from lit_agent.core.deps import setup_checkpointer
from lit_agent.core.logging import configure_logging

_log = structlog.get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    configure_logging(env=settings.env)
    _log.info("startup", env=settings.env, version=app.version)
    try:
        await setup_checkpointer()
    except Exception as exc:
        _log.warning("checkpointer_setup_failed", error=str(exc))

    # M3：同进程 AsyncIOScheduler（10:00/11:00 双 cron）。失败不阻塞启动。
    app.state.scheduler = None
    try:
        from lit_agent.scheduler.jobs import create_scheduler

        scheduler = create_scheduler(settings)
        scheduler.start()
        app.state.scheduler = scheduler
        _log.info(
            "scheduler_started", hour=settings.daily_push_hour, retry=settings.daily_push_retry_hour
        )
    except Exception as exc:
        _log.warning("scheduler_start_failed", error=str(exc))

    yield

    if app.state.scheduler is not None:
        app.state.scheduler.shutdown(wait=False)
    _log.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(env=settings.env)

    app = FastAPI(
        title="文献情报 Agent",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.is_dev else None,
        redoc_url="/redoc" if settings.is_dev else None,
        openapi_url="/openapi.json" if settings.is_dev else None,
    )

    app.add_middleware(TraceIDMiddleware)
    register_exception_handlers(app)
    app.include_router(system.router)
    app.include_router(admin.router)
    app.include_router(sessions.router)
    app.include_router(feedback.router)
    app.include_router(chat.router)
    return app


app = create_app()
