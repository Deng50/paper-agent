"""从 LangGraph PG checkpoint 重建 session md（M4 task 6 / docs/05 §5 task 6）。

用法：
    uv run python -m scripts.rebuild_session_md --thread-id <uuid>
    uv run python -m scripts.rebuild_session_md --thread-id <uuid> --dry-run
    uv run python -m scripts.rebuild_session_md --thread-id <uuid> --force

owner 拍板 Q9：放 scripts/（CLI 惯例），不放 tools/（不是 agent @tool）。
默认无 --force 时若 md 已存在则 abort，要求 owner 先 rm 旧 md 再跑；
故障恢复场景 = 「删损坏 session md → 重建一致」（docs/05 §5 验收第 6 条字面），
通常 owner 已手动 rm，--force 仅在调试 / 覆盖正常 md 时用作护栏。

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
        print("       加 --force 显式覆盖；或先 rm 旧 md 后再跑。")
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

    if existing is not None:
        existing.unlink()
        print(f"[clean] 旧 md 已删：{existing}")

    path = derive_session_md(thread_id, messages, settings=settings, now=dt.datetime.now(dt.UTC))
    if path is None:
        print("[warn] derive_session_md 返回 None（messages 全在 prev_count 之前？）")
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
    parser.add_argument("--force", action="store_true", help="覆盖已有 md（先 unlink 再重建）")
    args = parser.parse_args()
    return asyncio.run(rebuild_one(args.thread_id, args.dry_run, args.force))


if __name__ == "__main__":
    sys.exit(main())
