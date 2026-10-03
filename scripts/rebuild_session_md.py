"""从 LangGraph PG checkpoint 重建 session md（M4 task 6 / docs/05 §5 task 6）。

用法：
    uv run python -m scripts.rebuild_session_md --thread-id <uuid>
    uv run python -m scripts.rebuild_session_md --thread-id <uuid> --dry-run
    uv run python -m scripts.rebuild_session_md --thread-id <uuid> --force

owner 拍板 Q9：放 scripts/（CLI 惯例），不放 tools/（不是 agent @tool）。
默认无 --force 时若 md 已存在则 abort；--force 从 checkpoint 原子重建正文，
保留手工标题、原路径和开始时间，写入失败时原文件仍然可用。

--all 批量模式 M4 不实现：单用户故障恢复硬指标 = 单 thread 一致即可，批量
扫 PG distinct thread_id 留 M6 backup 运维脚本范畴。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from lit_agent.agents.lit_agent import build_lit_agent
from lit_agent.core.config import get_settings
from lit_agent.tools.session_md import derive_session_md, find_existing_by_thread


async def rebuild_one(thread_id: str, dry_run: bool = False, force: bool = False) -> int:
    """重建单 thread 的 session md。返回退出码（0 成功 / 1 abort）。"""
    settings = get_settings()
    existing = find_existing_by_thread(thread_id, settings)
    if existing is not None and not force:
        print(f"[abort] session md 已存在：{existing}")
        print("       加 --force 显式原子覆盖。")
        return 1

    async with AsyncPostgresSaver.from_conn_string(settings.psycopg_dsn) as saver:
        agent = build_lit_agent(checkpointer=saver, settings=settings)
        snap = await agent.aget_state({"configurable": {"thread_id": thread_id}})

    messages = snap.values.get("messages", []) or []
    if not messages:
        print(f"[abort] checkpoint 内无 messages（thread_id={thread_id}）。")
        return 1

    print(
        f"[plan] thread_id={thread_id} messages={len(messages)} "
        f"existing_md={existing if existing else '(none)'}"
    )
    if dry_run:
        print("[dry-run] 不写。")
        return 0

    path = derive_session_md(thread_id, messages, settings=settings, now=dt.datetime.now(dt.UTC))
    if path is None:
        print("[warn] derive_session_md 未生成可用归档。")
        return 1
    print(f"[done] session md 重建完成：{path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="重建 session md（M4 task 6 / docs/05 §5）")
    parser.add_argument(
        "--thread-id",
        required=True,
        help="LangGraph thread_id（UUID 或 daily_push:YYYY-MM-DD）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只列计划不写")
    parser.add_argument("--force", action="store_true", help="原子覆盖已有 md，保留标题和开始时间")
    args = parser.parse_args()
    return asyncio.run(rebuild_one(args.thread_id, args.dry_run, args.force))


if __name__ == "__main__":
    sys.exit(main())
