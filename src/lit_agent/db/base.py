"""数据库引擎 / 会话 / 声明基类（M1 任务 3）。

用 psycopg3 异步驱动（postgresql+psycopg），与 langgraph-checkpoint-postgres
默认驱动统一，避免双连接栈。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from lit_agent.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。"""


@lru_cache
def get_engine() -> AsyncEngine:
    """进程内共享的异步引擎。"""
    settings = get_settings()
    return create_async_engine(
        settings.database_url_str,
        pool_pre_ping=True,
        echo=False,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)


async def session_scope() -> AsyncGenerator[AsyncSession]:
    """提供一个自动提交 / 回滚的会话（用于 FastAPI Depends）。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
