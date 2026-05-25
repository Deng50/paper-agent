"""POST /api/v1/chat SSE 路由（M4 task 1 / docs/04 §4.1 / §9）。

owner 拍板（§6 Q1-3 / Q2.1-4）：
- 路径 native StreamingResponse + 自建 SSE wire（不引入 sse-starlette，减法）
- Q3 复用 build_lit_agent，显式传 skills=("daily_search", "memory_recall")
- Q2.1 派生写放 try/finally + fire-and-forget asyncio.to_thread（sync derive
  在 thread pool 跑完不受 outer cancel 影响；module-level set 保 Task 引用
  防 Python doc verbatim 警告的 weak-ref GC）
- Q2.2/2.3 整文件 read-modify-write 走 derive_session_md（复用 atomic_write）
- Q2.4 prev_message_count 指针在 derive 内 slice

SSE event 类型（docs/04 §4.1 字面）：meta / tool / token / citation / done。
keepalive 注释行 15s（docs/04 §9）由独立 asyncio task 喂 queue。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
import yaml
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field

from lit_agent.agents.lit_agent import build_lit_agent
from lit_agent.api._sse import KEEPALIVE_INTERVAL_S, SSE_KEEPALIVE, format_sse_event
from lit_agent.core.config import Settings, get_settings
from lit_agent.core.deps import AuthDep
from lit_agent.tools.session_md import derive_session_md

router = APIRouter(prefix="/api/v1", tags=["chat"], dependencies=[AuthDep])
_log = structlog.get_logger("chat")

_DERIVE_TASKS: set[asyncio.Task[Any]] = set()  # Python doc：防 weak-ref GC
_PAPER_FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, description="LangGraph thread_id；不传则新建 UUID")
    content: str = Field(min_length=1, description="用户消息正文")


def _parse_paper_md_citation(content: str) -> dict[str, str] | None:
    """从 read_file_tool 返回的 paper.md 全文解析 frontmatter 拿 paper_id / url。"""
    m = _PAPER_FM_RE.match(content)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict) or "paper_id" not in fm:
        return None
    return {
        "paper_id": str(fm.get("paper_id", "")),
        "title": str(fm.get("title", "")),
        "url": str(fm.get("url", "")),
    }


async def _produce_events(
    agent: Any,
    config: dict[str, Any],
    user_msg: HumanMessage,
    session_id: str,
    trace_id: str,
    queue: asyncio.Queue[str | None],
) -> None:
    """跑 agent.astream + 解析 events 入队 SSE。完毕 / 异常时 put None 哨兵。"""
    try:
        await queue.put(format_sse_event("meta", {"session_id": session_id, "trace_id": trace_id}))

        seen_msg_ids: set[str] = set()
        token_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}

        async for mode, payload in agent.astream(
            {"messages": [user_msg]},
            config=config,
            stream_mode=["updates", "messages"],
        ):
            if mode == "messages":
                chunk, _meta = payload
                if isinstance(chunk, AIMessage):
                    text = chunk.content if isinstance(chunk.content, str) else ""
                    if text:
                        await queue.put(format_sse_event("token", {"delta": text}))
            elif mode == "updates":
                for _node, state_delta in payload.items():
                    if not isinstance(state_delta, dict):
                        continue
                    new_msgs = state_delta.get("messages") or []
                    for msg in new_msgs:
                        mid = str(getattr(msg, "id", None) or id(msg))
                        if mid in seen_msg_ids:
                            continue
                        seen_msg_ids.add(mid)

                        if isinstance(msg, AIMessage):
                            for tc in msg.tool_calls or []:
                                await queue.put(
                                    format_sse_event(
                                        "tool",
                                        {"name": tc.get("name"), "args": tc.get("args", {})},
                                    )
                                )
                            um: dict[str, Any] = dict(msg.usage_metadata or {})
                            token_usage["input"] += int(um.get("input_tokens", 0))
                            token_usage["output"] += int(um.get("output_tokens", 0))
                            details = um.get("input_token_details") or {}
                            token_usage["cache_read"] += int(details.get("cache_read", 0) or 0)
                            token_usage["cache_creation"] += int(
                                details.get("cache_creation", 0) or 0
                            )
                        elif isinstance(msg, ToolMessage) and msg.name == "read_file_tool":
                            content_text = msg.content if isinstance(msg.content, str) else ""
                            citation = _parse_paper_md_citation(content_text)
                            if citation:
                                await queue.put(
                                    format_sse_event("citation", {"papers": [citation]})
                                )

        await queue.put(
            format_sse_event("done", {"finish_reason": "stop", "token_usage": token_usage})
        )
    except Exception as exc:
        _log.exception("chat_stream_produce_failed", session_id=session_id)
        await queue.put(format_sse_event("error", {"code": "INTERNAL_ERROR", "detail": str(exc)}))
    finally:
        await queue.put(None)


async def _keepalive_loop(queue: asyncio.Queue[str | None]) -> None:
    """15s 注释行心跳防反代切断。被 cancel 即退出（docs/04 §9）。"""
    try:
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_S)
            await queue.put(SSE_KEEPALIVE)
    except asyncio.CancelledError:
        return


def _spawn_derive(
    session_id: str,
    messages: list[BaseMessage],
    settings: Settings,
) -> None:
    """fire-and-forget 派生写：asyncio.to_thread 给 sync derive，cancel 不影响。"""
    if not messages:
        return
    task = asyncio.create_task(asyncio.to_thread(derive_session_md, session_id, messages, settings))
    _DERIVE_TASKS.add(task)
    task.add_done_callback(_DERIVE_TASKS.discard)


async def _chat_event_stream(
    body: ChatRequest,
    request: Request,
) -> AsyncIterator[str]:
    settings = get_settings()
    session_id = body.session_id or str(uuid.uuid4())
    trace_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
    config: dict[str, Any] = {"configurable": {"thread_id": session_id}}

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    main_task: asyncio.Task[None] | None = None
    ka_task: asyncio.Task[None] | None = None

    try:
        async with AsyncPostgresSaver.from_conn_string(settings.psycopg_dsn) as saver:
            agent = build_lit_agent(
                checkpointer=saver,
                settings=settings,
                skills=("daily_search", "memory_recall"),
            )
            user_msg = HumanMessage(content=body.content)
            main_task = asyncio.create_task(
                _produce_events(agent, config, user_msg, session_id, trace_id, queue)
            )
            ka_task = asyncio.create_task(_keepalive_loop(queue))

            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield item
                snap = await agent.aget_state(config)
                messages_list: list[BaseMessage] = snap.values.get("messages", []) or []
            except (asyncio.CancelledError, GeneratorExit):
                _log.info("chat_stream_cancelled", session_id=session_id)
                messages_list = []
                raise
            finally:
                if messages_list:
                    _spawn_derive(session_id, messages_list, settings)
    finally:
        for t in (ka_task, main_task):
            if t is not None and not t.done():
                t.cancel()
        await asyncio.gather(
            *(t for t in (main_task, ka_task) if t is not None),
            return_exceptions=True,
        )


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    """SSE 流式 /chat 入口。session_id = LangGraph thread_id；不传则新建 UUID。"""
    return StreamingResponse(
        _chat_event_stream(body, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
