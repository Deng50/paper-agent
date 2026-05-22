"""手动跑一次 search_papers（M2 Demo 入口）。

用法：
    uv run python -m scripts.fetch_once --queries "lithium battery solid electrolyte"
    uv run python -m scripts.fetch_once --queries "sulfide electrolyte" "battery thermal" --limit 10

会真实调用 4 源 + Haiku 评分，并把精选落盘到 ./memory/papers/{today}/。
INFO 日志会打印各源命中与 raw→deduped→selected 统计。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from lit_agent.core.config import get_settings
from lit_agent.core.logging import configure_logging
from lit_agent.tools.search_papers import search_papers


async def _run(args: argparse.Namespace) -> int:
    selected = await search_papers(
        queries=args.queries,
        limit_per_query=args.limit,
        dedup_against_memory=not args.no_dedup,
        min_score=args.min_score,
    )
    print("\n================ 精选结果 ================")
    print(f"共 {len(selected)} 篇（落盘 ./memory/papers/{{today}}/）：\n")
    for i, p in enumerate(selected, 1):
        score = f"{p.score:.1f}" if p.score is not None else "?"
        date = p.pub_date.isoformat() if p.pub_date else "—"
        print(f"{i:>2}. [{score}] [{p.source}] {p.title}")
        print(f"     {date} · {p.url}")
        if p.reason:
            print(f"     理由：{p.reason}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="跑一次 search_papers")
    parser.add_argument("--queries", nargs="+", required=True, help="一条或多条英文检索词")
    parser.add_argument("--limit", type=int, default=20, help="每条 query 每源召回上限")
    parser.add_argument("--min-score", type=float, default=6.0, dest="min_score")
    parser.add_argument("--no-dedup", action="store_true", help="不对照历史记忆去重")
    args = parser.parse_args()

    # Windows 控制台默认 gbk，论文标题常含 − / α 等字符 → 兜底转 utf-8。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    configure_logging(env=get_settings().env)
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
