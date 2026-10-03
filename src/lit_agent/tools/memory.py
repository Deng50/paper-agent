"""文件记忆工具（M2）：search_memory / read_file / write_file / list_dir。

设计精神：记忆是 markdown 文件 + grep，不是数据库/向量库。MVP 用 Python 扫描
（5 年 ≤ 2 万篇足够快；需要时再换 ripgrep / SQLite FTS5 派生索引）。

安全（硬边界，两层）：
- 读：路径白名单 `./memory/`（可读）、`skills/`（只读）。越权 → PathNotAllowed。
- 写（M5 起严收）：agent 写白名单仅 `^\\./memory/profile/profile\\.md$`（M5 P1 ⑤
  / 决策 A6）。越白名单但仍在 memory 内 → PathNotWhitelistedError；越 memory →
  PathNotAllowed。基础设施代码（paper.md 落盘 / session md 派生）仍走 paper_md
  .atomic_write 直接绕过此白名单 —— 白名单专管 agent。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, get_args

import structlog

from lit_agent.core.config import Settings, get_settings
from lit_agent.tools.paper_md import atomic_write

_log = structlog.get_logger("memory")

Scope = Literal["papers", "sessions", "profile", "feedback", "all"]

# agent 写白名单（M5 P1 ⑤ / 决策 A6 owner 字面拍板）。
# 三处字面同步：本常量 ↔ CLAUDE.md §5 ↔ docs/02 §3.4。
# 注：常量是 agent 标准输入的 relative-path 字面参考；write_file 内部用 canonical
# 绝对路径比对（更鲁棒），用 regex.pattern 仅作错误信息引用。
_WRITE_WHITELIST = re.compile(r"^\./memory/profile/profile\.md$")


class PathNotAllowed(Exception):
    """目标路径越出读写根（memory / skills 之外）。"""


class PathNotWhitelistedError(PathNotAllowed):
    """目标路径在 memory 根内但不在 agent 写白名单（M5 起仅 profile.md）。

    继承自 PathNotAllowed 以兼容现有 except 链；细分类便于 agent / 监控
    把"白名单收紧拒写"与"越权路径"两类失败区分开来。
    """


def _read_roots(settings: Settings) -> list[Path]:
    return [settings.memory_dir.resolve(), settings.skills_dir.resolve()]


def _resolve(path: str | Path, roots: list[Path]) -> Path:
    """把 path 解析为绝对路径并校验落在某个白名单根内，否则抛 PathNotAllowed。"""
    p = Path(path).resolve()
    for root in roots:
        if p == root or root in p.parents:
            return p
    raise PathNotAllowed(f"路径越权（不在白名单内）：{path}")


def read_file(path: str | Path, *, settings: Settings | None = None) -> str:
    """读 `./memory/` 或 `skills/` 内的文件全文。"""
    settings = settings or get_settings()
    p = _resolve(path, _read_roots(settings))
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在：{path}")
    return p.read_text(encoding="utf-8", errors="replace")


def write_file(path: str | Path, content: str, *, settings: Settings | None = None) -> Path:
    """agent 写文件入口（M5 起严收）：原子写仅限 `./memory/profile/profile.md`。

    两层校验：先 _resolve 校 memory root（PathNotAllowed），再校写白名单
    （PathNotWhitelistedError，PathNotAllowed 子类便于兼容现有 except）。
    白名单的「字面 regex」见 _WRITE_WHITELIST；本函数用 canonical 绝对路径比对，
    更鲁棒（允许测试传 tmp_path 下的 memory/profile/profile.md 绝对 Path 通过）。
    """
    settings = settings or get_settings()
    p = _resolve(path, [settings.memory_dir.resolve()])  # 第 1 层：memory root
    canonical_profile = (settings.memory_dir / "profile" / "profile.md").resolve()
    if p != canonical_profile:
        raise PathNotWhitelistedError(
            f"agent 写白名单仅 {_WRITE_WHITELIST.pattern}（canonical: {canonical_profile}）；"
            f"收到: {path} → resolved: {p}"
        )
    atomic_write(p, content)
    _log.info("write_file", path=str(p))
    return p


def list_dir(path: str | Path, *, settings: Settings | None = None) -> list[str]:
    """列目录内条目名（白名单内）。"""
    settings = settings or get_settings()
    p = _resolve(path, _read_roots(settings))
    if not p.is_dir():
        raise NotADirectoryError(f"不是目录：{path}")
    return sorted(entry.name for entry in p.iterdir())


def _scope_dirs(memory_dir: Path, scope: Scope) -> list[Path]:
    if scope not in get_args(Scope):
        raise PathNotAllowed(f"无效检索 scope：{scope}")
    if scope == "all":
        return [memory_dir / s for s in ("papers", "sessions", "profile", "feedback")]
    return [memory_dir / scope]


def search_memory(
    query: str,
    scope: Scope = "papers",
    limit: int = 20,
    *,
    settings: Settings | None = None,
) -> list[dict[str, str]]:
    """在 `./memory/{scope}/` 的 markdown 里检索（所有空格分词须全部命中，大小写不敏感）。

    返回命中列表：[{path, snippet}]，按文件路径倒序（新日期目录在前）。
    """
    settings = settings or get_settings()
    scope_dirs = _scope_dirs(settings.memory_dir, scope)
    if limit < 1:
        return []
    terms = [t for t in query.lower().split() if t]
    hits: list[dict[str, str]] = []
    if not terms:
        return hits

    files: list[Path] = []
    for d in scope_dirs:
        if d.is_dir():
            files.extend(d.rglob("*.md"))
            if d.name == "feedback":
                files.extend(d.rglob("*.log"))
    # 路径倒序 ≈ 日期新→旧（目录名是 YYYY-MM-DD）
    for md in sorted(files, reverse=True):
        try:
            resolved = _resolve(md, [settings.memory_dir.resolve()])
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except (PathNotAllowed, OSError):
            continue
        low = text.lower()
        if all(t in low for t in terms):
            hits.append({"path": str(md), "snippet": _snippet(text, terms)})
            if len(hits) >= limit:
                break
    return hits


def _snippet(text: str, terms: list[str], width: int = 160) -> str:
    """取第一处命中任一 term 的行作为片段。"""
    for line in text.splitlines():
        low = line.lower()
        if any(t in low for t in terms):
            s = line.strip()
            return s[:width] + ("…" if len(s) > width else "")
    return text.strip()[:width]
