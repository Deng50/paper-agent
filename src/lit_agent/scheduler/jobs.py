"""每日推送 job + APScheduler 装配（M3 任务 4、7）。

§6.3 a：同进程 `AsyncIOScheduler` + 默认 memory jobstore（不上 PG jobstore，不建表）。
§6.4：10:00 用固定 `thread_id=daily_push:YYYY-MM-DD` 给 agent 发一条 kickoff HumanMessage。
§6.5：11:00 第二个独立 cron 打同 thread_id（不是 misfire_grace）。
§6.8：pushes 审计由本 app 层 job 写（agent 无 write_pushes 工具）。

并发自拒（铁律#3，无 locks 表）：用 `pushes` 表本身做闸——`UniqueConstraint(user_id, run_date)`
+ `status`。首个 job INSERT pushes(running) 占位；第二个 job 撞唯一约束/读到 running →
判 busy 自拒；读到 success → already_done；读到 failed/partial → 合法补跑。固定 thread_id
让 LangGraph 会话连贯。
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lit_agent.agents.lit_agent import build_lit_agent
from lit_agent.core.config import Settings, get_settings
from lit_agent.db.base import get_session_factory
from lit_agent.db.models import Push
from lit_agent.tools.mail import render_daily_push, send_email

_log = structlog.get_logger("daily_push")

# Haiku 4.5 官方价 $/MTok（claude.com/pricing 2026-05-22）——newapi 无缓存，作成本下限估。
_HAIKU_IN_PER_MTOK = 1.0
_HAIKU_OUT_PER_MTOK = 5.0


def _run_date(settings: Settings) -> dt.date:
    return dt.datetime.now(ZoneInfo(settings.timezone)).date()


def _extract(result: dict[str, Any]) -> dict[str, Any]:
    """从 agent 最终 state 解析 pushes 审计所需：queries / counts / papers / intro / tokens。"""
    messages = result.get("messages", [])
    counts: dict[str, int] = {}
    papers: list[dict[str, Any]] = []
    queries: list[str] = []
    intro = ""
    in_tok = 0
    out_tok = 0
    cache_read = 0
    cache_creation = 0
    for m in messages:
        if isinstance(m, ToolMessage) and m.name == "search_papers_tool":
            try:
                payload = json.loads(m.content if isinstance(m.content, str) else "")
                counts = payload.get("counts", {})
                papers = payload.get("papers", [])
            except (json.JSONDecodeError, AttributeError):
                pass
        elif isinstance(m, AIMessage):
            for tc in m.tool_calls or []:
                if tc.get("name") == "search_papers_tool":
                    queries = tc.get("args", {}).get("queries", []) or queries
            um: dict[str, Any] = dict(m.usage_metadata or {})
            in_tok += int(um.get("input_tokens", 0))
            out_tok += int(um.get("output_tokens", 0))
            # cache 字段：经 newapi 应恒为 0（handover §6.11 探针实证不透传）；记录以监控隐式缓存。
            details = um.get("input_token_details") or {}
            cache_read += int(details.get("cache_read", 0) or 0)
            cache_creation += int(details.get("cache_creation", 0) or 0)
            if isinstance(m.content, str) and m.content.strip():
                intro = m.content.strip()  # 最后一条非空 AI 文本 = 导语
    return {
        "counts": counts,
        "papers": papers,
        "queries": queries,
        "intro": intro,
        "tokens": {
            "input": in_tok,
            "output": out_tok,
            "cache_read": cache_read,
            "cache_creation": cache_creation,
        },
    }


def _log_token_budget(run_date: dt.date, tokens: dict[str, int]) -> None:
    """验收#8 token 预算护栏：每次推送打印 dry-run token 计数 + 官方价下限成本估。"""
    cost = tokens["input"] * _HAIKU_IN_PER_MTOK / 1e6 + tokens["output"] * _HAIKU_OUT_PER_MTOK / 1e6
    _log.info(
        "daily_push_token_budget",
        run_date=str(run_date),
        input_tokens=tokens["input"],
        output_tokens=tokens["output"],
        cache_read_input_tokens=tokens.get("cache_read", 0),
        cache_creation_input_tokens=tokens.get("cache_creation", 0),
        est_cost_usd=round(cost, 5),
        note="newapi 无缓存(handover §6.11)，按 Haiku4.5 官方价 $1/$5 per MTok 下限估",
    )


async def _claim_run(
    s: AsyncSession, run_date: dt.date, triggered_by: str
) -> tuple[int, str] | None:
    """占位/闸：返回 (push_id, "proceed") 表示可跑；返回 None 表示自拒（busy / already_done）。"""
    existing = (
        await s.execute(select(Push).where(Push.user_id == 1, Push.run_date == run_date))
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == "success":
            _log.info("daily_push_already_done", run_date=str(run_date))
            return None
        if existing.status == "running":
            _log.info("daily_push_busy_skip", run_date=str(run_date), reason="今日推送仍在跑")
            return None
        # failed / partial → 合法补跑
        existing.status = "running"
        existing.error = None
        existing.triggered_by = triggered_by
        existing.started_at = dt.datetime.now(dt.UTC)
        await s.commit()
        return existing.id, "retry"
    push = Push(user_id=1, run_date=run_date, triggered_by=triggered_by, status="running")
    s.add(push)
    try:
        await s.commit()
    except IntegrityError:
        # 与另一个 job 抢 INSERT 撞唯一约束 → 对方已占位 → 自拒
        await s.rollback()
        _log.info("daily_push_busy_skip", run_date=str(run_date), reason="并发 INSERT 撞唯一约束")
        return None
    return push.id, "new"


async def run_daily_push(
    triggered_by: str = "cron",
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> str:
    """执行一次每日推送。返回状态字符串：busy/already_done/success/partial/failed。"""
    settings = settings or get_settings()
    factory = session_factory or get_session_factory()
    run_date = _run_date(settings)
    thread_id = f"daily_push:{run_date.isoformat()}"

    async with factory() as s:
        claim = await _claim_run(s, run_date, triggered_by)
    if claim is None:
        return "busy"
    push_id, _ = claim

    status = "success"
    error: str | None = None
    email_sent = False
    extracted: dict[str, Any] = {
        "counts": {},
        "papers": [],
        "queries": [],
        "intro": "",
        "tokens": {"input": 0, "output": 0},
    }

    try:
        async with AsyncPostgresSaver.from_conn_string(settings.psycopg_dsn) as saver:
            agent = build_lit_agent(checkpointer=saver, settings=settings)
            result = await agent.ainvoke(
                {
                    "messages": [
                        HumanMessage(content=f"今天是 {run_date.isoformat()}，执行每日推送。")
                    ]
                },
                config={"configurable": {"thread_id": thread_id}},
            )
        extracted = _extract(result)
        papers = extracted["papers"]
        if papers:
            try:
                subject = f"每日文献推送 · {run_date.isoformat()} · {len(papers)} 篇"
                html = render_daily_push(extracted["intro"], papers, run_date.isoformat())
                await send_email(subject, html, settings=settings)
                email_sent = True
            except Exception as exc:  # SMTP/收件人失败 → partial，站内仍正常（验收第6条）
                status = "partial"
                error = f"email_failed: {exc}"
                _log.warning("daily_push_email_failed", error=str(exc))
    except Exception as exc:  # agent/检索失败 → failed
        status = "failed"
        error = str(exc)
        _log.exception("daily_push_failed", run_date=str(run_date))

    _log_token_budget(run_date, extracted["tokens"])

    async with factory() as s:
        push = await s.get(Push, push_id)
        if push is not None:
            push.status = status
            push.error = error
            push.queries = extracted["queries"]
            push.fetched_count = int(extracted["counts"].get("raw", 0))
            push.deduped_count = int(extracted["counts"].get("deduped", 0))
            push.selected_count = int(extracted["counts"].get("selected", len(extracted["papers"])))
            push.selected_papers = extracted["papers"]
            push.email_sent = email_sent
            push.finished_at = dt.datetime.now(dt.UTC)
            await s.commit()

    _log.info(
        "daily_push_done", run_date=str(run_date), status=status, selected=len(extracted["papers"])
    )
    return status


def create_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    """同进程 AsyncIOScheduler（memory jobstore）+ 10:00/11:00 双 cron。"""
    settings = settings or get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        run_daily_push,
        "cron",
        hour=settings.daily_push_hour,
        minute=0,
        kwargs={"triggered_by": "cron"},
        id="daily_push",
        replace_existing=True,
    )
    scheduler.add_job(
        run_daily_push,
        "cron",
        hour=settings.daily_push_retry_hour,
        minute=0,
        kwargs={"triggered_by": "retry"},
        id="daily_push_retry",
        replace_existing=True,
    )
    return scheduler
