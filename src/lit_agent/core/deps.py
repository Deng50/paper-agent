"""FastAPI 依赖与 LangGraph checkpointer 接线（M1 任务 4）。

- verify_token：静态 Bearer 鉴权（04_api_design §1.1）。
- get_db：注入 AsyncSession。
- get_memory_dir：注入记忆目录 Path。
- setup_checkpointer：启动期创建 LangGraph 在 PG 内的 checkpoint 表。
  这些表由框架自管，我们只调用 setup()，不画不动其结构（CLAUDE.md §2）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException

from lit_agent.core.config import Settings, get_settings
from lit_agent.db.base import session_scope

_log = structlog.get_logger("deps")


async def verify_token(request: Request) -> None:
    """校验 Authorization: Bearer <API_TOKEN>。失败抛 401 → RFC7807。"""
    settings = get_settings()
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or token != settings.api_token:
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token.")


async def get_db() -> AsyncGenerator[AsyncSession]:
    """注入数据库会话。"""
    async for session in session_scope():
        yield session


def get_memory_dir() -> Path:
    """注入记忆目录（路径白名单的根）。"""
    return get_settings().memory_dir


# 类型别名，路由签名更干净
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
MemoryDirDep = Annotated[Path, Depends(get_memory_dir)]
AuthDep = Depends(verify_token)


async def setup_checkpointer() -> None:
    """启动期确保 LangGraph 的 PG checkpoint 表就绪（幂等）。

    实际 graph 使用 checkpointer 在 M3/M4；M1 只完成接线与建表，证明 PG 可承载。
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    dsn = get_settings().psycopg_dsn
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
    _log.info("checkpointer_ready")
