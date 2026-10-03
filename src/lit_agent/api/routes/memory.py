"""Read-only views of the canonical paper and profile Markdown memory."""

from __future__ import annotations

import base64
import datetime as dt
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Query

from lit_agent.core.config import get_settings
from lit_agent.core.deps import AuthDep
from lit_agent.tools.memory import PathNotAllowed, read_file
from lit_agent.tools.schemas import Source
from lit_agent.tools.session_md import list_all_sessions

router = APIRouter(prefix="/api/v1/memory", tags=["memory"], dependencies=[AuthDep])


def _read_markdown(path: Path) -> tuple[dict[str, Any], str, str]:
    text = read_file(path)
    parts = text.split("\n---", 1) if text.startswith("---\n") else []
    if len(parts) != 2:
        return {}, text, text
    fm = yaml.safe_load(parts[0][4:])
    return fm if isinstance(fm, dict) else {}, parts[1].lstrip(), text


@router.get("/papers")
def list_papers(
    q: str = "",
    date: dt.date | None = None,
    source: Source | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    root = get_settings().memory_dir / "papers"
    after = None
    if cursor:
        try:
            after = base64.b64decode(cursor, altchars=b"-_", validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(422, "无效分页 cursor") from exc
    directory = root / date.isoformat() if date else root
    terms = q.lower().split()
    items: list[dict[str, Any]] = []
    keys: list[str] = []
    for path in sorted(directory.rglob("*.md"), reverse=True):
        key = path.relative_to(root).as_posix()
        if after is not None and key >= after:
            continue
        try:
            fm, _, text = _read_markdown(path)
        except (OSError, PathNotAllowed, yaml.YAMLError):
            continue
        if not fm.get("paper_id") or (source and fm.get("source") != source):
            continue
        if any(term not in text.lower() for term in terms):
            continue
        items.append({**fm, "md_path": str(path)})
        keys.append(key)
        if len(items) > limit:
            break
    more = len(items) > limit
    next_cursor = base64.urlsafe_b64encode(keys[limit - 1].encode()).decode() if more else ""
    return {"items": items[:limit], "next_cursor": next_cursor, "has_more": more, "limit": limit}


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str) -> dict[str, Any]:
    settings = get_settings()
    for path in sorted((settings.memory_dir / "papers").rglob("*.md"), reverse=True):
        if path.stem != paper_id:
            continue
        try:
            fm, body, _ = _read_markdown(path)
        except (OSError, PathNotAllowed, yaml.YAMLError):
            continue
        if fm.get("paper_id") != paper_id:
            continue
        cited = [
            {
                "session_id": s["thread_id"],
                "session_title": s.get("title"),
                "last_active_at": s.get("last_active_at"),
            }
            for s in list_all_sessions(settings)
            if paper_id in s.get("related_papers", [])
        ]
        return {"paper_id": paper_id, "frontmatter": fm, "body_markdown": body, "cited_in": cited}
    raise HTTPException(404, "未找到文献")


@router.get("/profile")
def get_profile() -> dict[str, Any]:
    try:
        fm, body, _ = _read_markdown(get_settings().memory_dir / "profile" / "profile.md")
    except (OSError, PathNotAllowed) as exc:
        raise HTTPException(404, "画像尚未初始化") from exc
    except yaml.YAMLError as exc:
        raise HTTPException(422, "画像 frontmatter 格式损坏") from exc
    return {**fm, "summary_markdown": body}
