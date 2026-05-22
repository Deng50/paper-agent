"""文件记忆工具（M2）：search_memory / read_file / write_file / list_dir。

设计精神：记忆是 markdown 文件 + grep，不是数据库/向量库。MVP 用 Python 扫描
（5 年 ≤ 2 万篇足够快；需要时再换 ripgrep / SQLite FTS5 派生索引）。

安全（硬边界）：路径白名单 —— `./memory/`（读写）、`skills/`（只读）。
任何越权路径（如 `.env`、`..` 穿越）抛 PathNotAllowed，防止 agent 读写敏感文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import structlog

from lit_agent.core.config import Settings, get_settings
from lit_agent.tools.paper_md import atomic_write

_log = structlog.get_logger("memory")

Scope = Literal["papers", "sessions", "profile", "feedback", "all"]


class PathNotAllowed(Exception):
    """目标路径越出白名单。"""


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
    """原子写到 `./memory/` 内（skills/ 只读，不可写）。"""
    settings = settings or get_settings()
    p = _resolve(path, [settings.memory_dir.resolve()])  # 写仅限 memory
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
    terms = [t for t in query.lower().split() if t]
    hits: list[dict[str, str]] = []
    if not terms:
        return hits

    files: list[Path] = []
    for d in _scope_dirs(settings.memory_dir, scope):
        if d.is_dir():
            files.extend(d.rglob("*.md"))
    # 路径倒序 ≈ 日期新→旧（目录名是 YYYY-MM-DD）
    for md in sorted(files, reverse=True):
        text = md.read_text(encoding="utf-8", errors="replace")
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
