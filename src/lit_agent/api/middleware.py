"""RFC 7807 错误响应 + trace_id 中间件（M1 任务 2）。

错误统一为 application/problem+json（见 04_api_design §0.4）。
trace_id 绑定到 structlog contextvars，使一次请求的所有日志可串联，
并回写到响应体与 X-Request-Id 头。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

PROBLEM_CONTENT_TYPE = "application/problem+json"

# HTTP status -> 业务 code（04_api_design §0.4）
_STATUS_CODE: dict[int, str] = {
    401: "UNAUTHORIZED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

_log = structlog.get_logger("api")


class Problem(BaseModel):
    """RFC 7807 problem detail。"""

    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str
    trace_id: str


def _problem_response(
    status: int, title: str, detail: str, trace_id: str, code: str | None = None
) -> JSONResponse:
    problem = Problem(
        title=title,
        status=status,
        code=code or _STATUS_CODE.get(status, "ERROR"),
        detail=detail,
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(),
        media_type=PROBLEM_CONTENT_TYPE,
    )


def _trace_id(request: Request) -> str:
    return structlog.contextvars.get_contextvars().get("trace_id") or request.headers.get(
        "X-Request-Id", str(uuid.uuid4())
    )


class TraceIDMiddleware(BaseHTTPMiddleware):
    """为每个请求生成 / 透传 trace_id，绑定 contextvars 并回写响应头。"""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id, method=request.method, path=request.url.path
        )
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars()
        response.headers["X-Request-Id"] = trace_id
        return response


def register_exception_handlers(app: FastAPI) -> None:
    """注册 RFC7807 异常处理器。"""

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = _STATUS_CODE.get(exc.status_code, "Error").replace("_", " ").title()
        return _problem_response(
            status=exc.status_code,
            title=title,
            detail=str(exc.detail),
            trace_id=_trace_id(request),
            code=getattr(exc, "code", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem_response(
            status=422,
            title="Validation Error",
            detail="; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            or "Request validation failed",
            trace_id=_trace_id(request),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
        _log.error("unhandled_exception", error=str(exc), exc_info=exc)
        return _problem_response(
            status=500,
            title="Internal Error",
            detail="An unexpected error occurred.",
            trace_id=_trace_id(request),
        )
