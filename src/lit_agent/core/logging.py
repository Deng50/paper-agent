"""结构化日志（M1 任务 2）。

观测走 structlog（PRD：不建 events 表）。dev 用彩色控制台，prod 用 JSON。
trace_id 通过 contextvars 绑定，使一次请求的所有日志可串联。
"""

from __future__ import annotations

import logging
import sys

import structlog

_configured = False


def configure_logging(*, env: str = "dev") -> None:
    """进程级配置 structlog + 标准库 logging。幂等。"""
    global _configured
    if _configured:
        return

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if env == "dev":
        renderer: structlog.typing.Processor = structlog.dev.ConsoleRenderer()
    else:
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # 让标准库 logging（uvicorn 等）也走同一个 INFO 级别。
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取一个绑定 logger。"""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
