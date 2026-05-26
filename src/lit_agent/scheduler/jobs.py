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
from collections import defaultdict
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
from lit_agent.db.models import Feedback, Push
from lit_agent.tools.mail import render_daily_push, send_email
from lit_agent.tools.paper_md import atomic_write

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
    s: AsyncSession, run_date: dt.date, triggered_by: str, *, force: bool = False
) -> tuple[int, str] | None:
    """占位/闸：返回 (push_id, "proceed") 表示可跑；返回 None 表示自拒（busy / already_done）。

    force=True：success 也强制重跑（docs/04 §8.1 字面），不绕开 running busy 闸。
    """
    existing = (
        await s.execute(select(Push).where(Push.user_id == 1, Push.run_date == run_date))
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == "running":
            _log.info("daily_push_busy_skip", run_date=str(run_date), reason="今日推送仍在跑")
            return None
        if existing.status == "success" and not force:
            _log.info("daily_push_already_done", run_date=str(run_date))
            return None
        # success+force / failed / partial → 重跑（覆盖既有行）
        existing.status = "running"
        existing.error = None
        existing.triggered_by = triggered_by
        existing.started_at = dt.datetime.now(dt.UTC)
        await s.commit()
        _log.info("daily_push_force_rerun" if force else "daily_push_retry", run_date=str(run_date))
        return existing.id, "force" if force else "retry"
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
    force: bool = False,
    run_date_override: dt.date | None = None,
    topic_override: str | None = None,
) -> str:
    """执行一次每日推送。返回状态字符串：busy/already_done/success/partial/failed。

    force=True：今日 status=success 时仍强制重跑（owner 手动触发覆盖；docs/04 §8.1
    字面）；同一 thread_id checkpoint 复用（handover §3.9 行为提醒）。
    run_date_override：补跑历史某天用；缺省取 settings._run_date（今天）。
    topic_override：chat-rerun 路径用 —— 把用户在 chat 里指定的方向作为 HumanMessage
    注入提示，agent 按 daily_search.skill.md 步骤 2 把 topic 翻译/扩展成英文检索词
    （优先于 profile）。普通 cron / manual 路径填 None。
    """
    settings = settings or get_settings()
    factory = session_factory or get_session_factory()
    run_date = run_date_override or _run_date(settings)
    thread_id = f"daily_push:{run_date.isoformat()}"

    async with factory() as s:
        claim = await _claim_run(s, run_date, triggered_by, force=force)
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
            # force=True 时清同 thread_id checkpoint，破 handover §3.9 复用屏障，
            # 让 agent 重新调 search_papers（保留 dedup_against_memory=True 历史去重，
            # 让 search 只返回真正未推过的新候选；docs/04 §8.1 方案 B 字面）。
            if force:
                await saver.adelete_thread(thread_id)
                _log.info("daily_push_force_clear_checkpoint", thread_id=thread_id)
            agent = build_lit_agent(checkpointer=saver, settings=settings)
            kickoff = f"今天是 {run_date.isoformat()}，执行每日推送。"
            if topic_override:
                # chat-rerun 路径：把用户指定主题字面注入；daily_search.skill.md 步骤 2 接住
                kickoff += (
                    f"\n本次重新检索主题（chat 用户指定，优先用此方向生成英文检索词）："
                    f"{topic_override}"
                )
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=kickoff)]},
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


async def run_profile_update(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> str:
    """每日 23:00 cron 触发 lit_agent 按 profile_update.skill.md 增量改写画像（M5 A1）。

    流程（不在本函数；本函数只发动）：
    - build_lit_agent(skills=("profile_update",)) → 拼写权 override prompt + 加 write_file_tool
    - HumanMessage 发动 → agent 按 skill 7 步流程 read profile.md → list feedback/ →
      读 30 天反馈 + 对照 paper.md 抽关键词 → 增量改写 → write_file 1 次原子写

    时机：22:55 feedback derive 落今天全天反馈 → 23:00 进画像 → 明早 10:00 push
    用新画像。延迟约 11 小时（旧 11:30 设计 25 小时），且 23:00 服务器空闲、
    Anthropic API 便宜稳定（owner 调整理由）。

    thread_id：每次新会话（profile_update:{date}），用 adelete_thread 强清，
    不复用上次 state。返回 success / "failed: {err}"。
    """
    settings = settings or get_settings()
    run_date = _run_date(settings)
    thread_id = f"profile_update:{run_date.isoformat()}"

    try:
        async with AsyncPostgresSaver.from_conn_string(settings.psycopg_dsn) as saver:
            await saver.adelete_thread(thread_id)
            agent = build_lit_agent(
                checkpointer=saver,
                settings=settings,
                skills=("profile_update",),
            )
            await agent.ainvoke(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                f"今天是 {run_date.isoformat()}，执行画像增量更新："
                                "按 profile_update SKILL 7 步流程跑一次。"
                            )
                        )
                    ]
                },
                config={"configurable": {"thread_id": thread_id}},
            )
        _log.info("profile_update_done", run_date=str(run_date))
        return "success"
    except Exception as exc:
        _log.exception("profile_update_failed", run_date=str(run_date))
        return f"failed: {exc}"


def _format_feedback_log_lines(rows: list[Feedback], tz: ZoneInfo) -> dict[dt.date, list[str]]:
    """纯函数：feedback 行按本地日期 group + 格式化成 log 行。便于无 PG 单测。

    每行格式（profile_update.skill.md 解析依据）：
        2026-05-27T10:23:45+08:00 | up | s2-abc123 | +1.00
    """
    by_date: dict[dt.date, list[str]] = defaultdict(list)
    for r in rows:
        local_dt = r.created_at.astimezone(tz)
        line = f"{local_dt.isoformat()} | {r.signal_type} | {r.paper_id} | {float(r.weight):+.2f}"
        by_date[local_dt.date()].append(line)
    return by_date


async def derive_feedback_logs(
    days: int = 30,
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """PG feedback → 文件派生（M5 决策 A4 / cron 03:00 主路径）。

    读近 `days` 天的 feedback 行 → `_format_feedback_log_lines` 按本地日期 group →
    每个日期 atomic_write 到 `./memory/feedback/{YYYY-MM-DD}.log`，
    **全量覆盖单日文件**（每行 1 条反馈）。

    返回写入文件数（无 feedback 返回 0；不删除窗口外旧文件，由 skill 自截 30 天）。
    """
    settings = settings or get_settings()
    factory = session_factory or get_session_factory()
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    tz = ZoneInfo(settings.timezone)

    async with factory() as s:
        result = await s.execute(
            select(Feedback).where(Feedback.created_at >= cutoff).order_by(Feedback.created_at)
        )
        rows = list(result.scalars().all())

    by_date = _format_feedback_log_lines(rows, tz)

    feedback_dir = settings.memory_dir / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    for date, lines in by_date.items():
        path = feedback_dir / f"{date.isoformat()}.log"
        atomic_write(path, "\n".join(lines) + "\n")

    _log.info("feedback_derived", days=days, rows=len(rows), files=len(by_date))
    return len(by_date)


def create_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    """同进程 AsyncIOScheduler（memory jobstore）+ daily-push 双 cron + M5 feedback 派生 cron。"""
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
    # M5 决策 A4：22:55 cron 派生 PG feedback → ./memory/feedback/{date}.log。
    # owner 调整：profile-update 从 11:30 挪到 23:00（见下方），feedback derive 必须
    # 在 23:00 之前跑才能让「今天全天反馈进当晚画像」成立；故 22:55（紧邻 23:00 之前）。
    scheduler.add_job(
        derive_feedback_logs,
        "cron",
        hour=22,
        minute=55,
        id="feedback_derive",
        replace_existing=True,
    )
    # M5 决策 A1（owner 调整后）：23:00 cron 触发 lit_agent(skills=("profile_update",))
    # 按 skill 增量改写 profile.md。
    # 时机选择理由：
    #   - 11:30 旧设计：今天 10:00 push 用昨天画像；今天反馈要等明天 11:30 才进画像
    #     → 反馈到生效 25 小时延迟
    #   - 23:00 新设计：今天全天反馈 22:55 落 log → 23:00 进画像 → 明早 10:00 push
    #     直接用新画像 → 延迟缩到 11 小时
    #   - 23:00 服务器空闲、Anthropic API 便宜稳定
    scheduler.add_job(
        run_profile_update,
        "cron",
        hour=23,
        minute=0,
        id="profile_update",
        replace_existing=True,
    )
    return scheduler
