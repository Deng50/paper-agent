"""中文召回率评估（M4 task 7 / docs/05 §5）。

用法：
    uv run python -m scripts.eval_cn_recall
    uv run python -m scripts.eval_cn_recall --gold tests/eval/cn_recall_gold.yaml --report report.md

读取黄金集 yaml → 对每题跑 search_memory(question, scope) → 计算 Top-1/3/5 命中率
→ 主集 + per-theme + F 警示项分别输出。

评分口径（Q5 owner 拍板）：
- 验收主口径 = Top-3（yaml verdict_threshold）；Top-1 / Top-5 同时输出供口径敏感性分析
- 单题命中 = search_memory 返回前 K 个文件路径中至少 1 个 paper_id 落入 expected
- 主集判定 = paper / session 双双在 verdict_threshold 档 ≥ verdict_pass_ratio
- F 警示项（电池热管理 corpus 稀缺）单独算分，不计入主验收
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from lit_agent.core.config import Settings, get_settings
from lit_agent.tools.memory import search_memory


def _paper_id_of(path: str) -> str:
    """从 ./memory/papers/{date}/{paper_id}.md 提取 paper_id（file stem）。"""
    return Path(path).stem


def _hit_at_k(hit_paths: list[str], expected_ids: list[str], k: int) -> int:
    """前 k 个命中路径里若任一 paper_id / session basename 落入 expected → 1。"""
    if not expected_ids:
        return 0  # 黄金集未填 → 0 不算命中
    top_k_ids = {_paper_id_of(p) for p in hit_paths[:k]}
    return 1 if top_k_ids & set(expected_ids) else 0


def _eval_questions(
    questions: list[dict[str, Any]],
    expected_field: str,
    settings: Settings,
) -> dict[str, Any]:
    """跑一组题（paper 或 session），返回 {n, totals, ratios, per_theme, details}。"""
    ks = (1, 3, 5)
    totals = {f"top_{k}": 0 for k in ks}
    per_theme: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, **{f"top_{k}": 0 for k in ks}}
    )
    details: list[dict[str, Any]] = []
    n = len(questions)

    for q in questions:
        query = q.get("question", "") or ""
        scope_str = q.get("scope", "papers")
        expected = q.get(expected_field, []) or []
        theme = q.get("theme", "untagged")

        hits = search_memory(query, scope=scope_str, limit=10, settings=settings) if query else []
        paths = [h["path"] for h in hits]

        row: dict[str, Any] = {
            "id": q.get("id", "?"),
            "theme": theme,
            "question": query,
            "expected": expected,
            "n_hits": len(paths),
        }
        per_theme[theme]["n"] += 1
        for k in ks:
            hit = _hit_at_k(paths, expected, k)
            totals[f"top_{k}"] += hit
            per_theme[theme][f"top_{k}"] += hit
            row[f"top_{k}"] = hit
        details.append(row)

    ratios = {f"top_{k}": (totals[f"top_{k}"] / n if n else 0.0) for k in ks}
    return {
        "n": n,
        "totals": totals,
        "ratios": ratios,
        "per_theme": dict(per_theme),
        "details": details,
    }


def _format_section(title: str, result: dict[str, Any]) -> str:
    """生成 markdown 子节。"""
    n: int = result["n"]
    lines = [f"### {title}（{n} 题）", ""]
    if n == 0:
        lines.append("（无题目）")
        return "\n".join(lines) + "\n"
    r = result["ratios"]
    t = result["totals"]
    lines.append(
        f"- 总分：Top-1 {t['top_1']}/{n}={r['top_1']:.0%}　"
        f"Top-3 {t['top_3']}/{n}={r['top_3']:.0%}　"
        f"Top-5 {t['top_5']}/{n}={r['top_5']:.0%}"
    )
    if result["per_theme"]:
        lines.append("- 按主题：")
        for theme, agg in sorted(result["per_theme"].items()):
            tn = agg["n"]
            if not tn:
                continue
            lines.append(
                f"  - {theme}（{tn} 题）：Top-1 {agg['top_1']}/{tn}　"
                f"Top-3 {agg['top_3']}/{tn}　Top-5 {agg['top_5']}/{tn}"
            )
    return "\n".join(lines) + "\n"


def _run(gold_path: Path, report_path: Path | None) -> int:
    settings = get_settings()
    with gold_path.open(encoding="utf-8") as f:
        gold = yaml.safe_load(f)

    threshold = gold.get("verdict_threshold", "top_3")
    pass_ratio = float(gold.get("verdict_pass_ratio", 0.8))

    paper_q = gold.get("paper_questions", []) or []
    session_q = gold.get("session_questions", []) or []
    paper_result = _eval_questions(paper_q, "expected_paper_ids", settings)
    session_result = _eval_questions(session_q, "expected_session_ids", settings)

    paper_pass = paper_result["ratios"].get(threshold, 0.0) >= pass_ratio
    session_pass = session_result["ratios"].get(threshold, 0.0) >= pass_ratio
    main_pass = paper_pass and session_pass

    f_warn = gold.get("f_corpus_warning") or {}
    f_paper_result = _eval_questions(
        f_warn.get("paper_questions", []) or [], "expected_paper_ids", settings
    )
    f_session_result = _eval_questions(
        f_warn.get("session_questions", []) or [], "expected_session_ids", settings
    )

    out: list[str] = []
    out.append("# 中文召回率评估报告（M4 task 7）\n\n")
    out.append(f"- 黄金集：`{gold_path}`\n")
    out.append(f"- 验收口径：{threshold} ≥ {pass_ratio:.0%}\n")
    out.append(
        f"- 主集判定：{'[PASS]' if main_pass else '[FAIL]'}"
        f"（paper {paper_result['ratios'].get(threshold, 0.0):.0%}"
        f" / session {session_result['ratios'].get(threshold, 0.0):.0%}）\n\n"
    )
    out.append("## 主集（不含 F 警示项）\n\n")
    out.append(_format_section("文献题（scope=papers）", paper_result))
    out.append("\n")
    out.append(_format_section("对话题（scope=sessions）", session_result))
    out.append("\n## F 警示项（电池热管理，corpus 稀缺，单独算分不计主验收）\n\n")
    out.append(
        f"- corpus_count = {f_warn.get('corpus_count', 'N/A')}\n"
        f"- expected_recall = {f_warn.get('expected_recall', 'N/A')}\n\n"
    )
    out.append(_format_section("F 文献题", f_paper_result))
    out.append("\n")
    out.append(_format_section("F 对话题", f_session_result))

    report = "".join(out)
    print(report)
    if report_path:
        report_path.write_text(report, encoding="utf-8")
        print(f"\n报告已写入 {report_path}")

    return 0 if main_pass else 1


def main() -> int:
    # Windows console 默认 gbk，强制 utf-8 让中文输出不乱码（Python 3.7+）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="中文召回率评估（M4 / docs/05 §5）")
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("tests/eval/cn_recall_gold.yaml"),
        help="黄金集 yaml 路径",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：将 markdown 报告写入该路径（不传只打印）",
    )
    args = parser.parse_args()
    return _run(args.gold, args.report)


if __name__ == "__main__":
    sys.exit(main())
