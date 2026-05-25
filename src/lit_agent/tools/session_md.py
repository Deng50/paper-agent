"""session md 派生写 helper（M4 task 2 / docs/02 §4.3 / docs/05 §5）。

应用层 helper（不是 agent @tool）：在 /chat 的 SSE done 后由路由调用 +
scripts/rebuild_session_md.py（M4-4）共享。从 LangGraph state.values["messages"]
取 message_count 之后的新增 messages，整文件原子重写 session md（frontmatter
+ 历史正文 + 新追加轮）。复用 tools/paper_md.py::atomic_write。

session md 路径：./memory/sessions/{started_at.date()}/{HH-MM}-{trigger}.md
- started_at 首次写时 = datetime.now()，存入 frontmatter；后续读 frontmatter
- trigger：thread_id 前缀 "daily_push:" → daily-push；否则 chat（jobs.py:150 /
  sessions.py:43 既成规则；handover §3.5 字面）

新轮边界：frontmatter `message_count` 作 prev_count 指针，
snap.values["messages"][prev_count:] = 新增（Q2.4 owner 拍板，独立于 LangGraph
checkpoint 内部 API）。
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import structlog
import yaml
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from lit_agent.core.config import Settings, get_settings
from lit_agent.tools.paper_md import atomic_write

_log = structlog.get_logger("session_md")
_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def trigger_of(thread_id: str) -> str:
    """daily_push: 前缀 → daily-push；否则 chat（命名规则见 handover §3.5）。"""
    return "daily-push" if thread_id.startswith("daily_push:") else "chat"


def session_md_path(
    thread_id: str,
    started_at: dt.datetime,
    settings: Settings | None = None,
) -> Path:
    """计算 session md 路径：./memory/sessions/{date}/{HH-MM}-{trigger}.md。"""
    settings = settings or get_settings()
    date_str = started_at.date().isoformat()
    hm_str = started_at.strftime("%H-%M")
    trig = trigger_of(thread_id)
    return settings.memory_dir / "sessions" / date_str / f"{hm_str}-{trig}.md"


def find_existing_by_thread(thread_id: str, settings: Settings | None = None) -> Path | None:
    """扫 ./memory/sessions/ 找首个 frontmatter.thread_id == thread_id 的 md。

    单用户场景 N 上限几百，rglob O(N) 可接受；M6 可改维护派生索引。
    """
    settings = settings or get_settings()
    sessions_root = settings.memory_dir / "sessions"
    if not sessions_root.is_dir():
        return None
    for md in sessions_root.rglob("*.md"):
        try:
            fm, _body = _parse_existing(md)
        except (OSError, yaml.YAMLError):
            continue
        if fm.get("thread_id") == thread_id:
            return md
    return None


def _parse_existing(md_path: Path) -> tuple[dict[str, Any], str]:
    """读旧 md 解析 (frontmatter_dict, body_str)；不存在返回 ({}, "")。"""
    if not md_path.exists():
        return {}, ""
    text = md_path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm if isinstance(fm, dict) else {}, m.group(2)


def _extract_related_papers(messages: list[BaseMessage]) -> list[str]:
    """从 AIMessage.tool_calls 提取 read_file_tool 命中的 paper_id（去重保序）。"""
    paper_ids: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        for tc in msg.tool_calls or []:
            if tc.get("name") != "read_file_tool":
                continue
            path = (tc.get("args") or {}).get("path", "")
            if "/papers/" not in path:
                continue
            pid = Path(path).stem
            if pid and pid not in seen:
                seen.add(pid)
                paper_ids.append(pid)
    return paper_ids


def _render_messages(messages: list[BaseMessage]) -> str:
    """新增 messages 渲染为 markdown 段（grep 友好；docs/04 §5.2 cited_in 兼容）。"""
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = (
                msg.content
                if isinstance(msg.content, str)
                else json.dumps(msg.content, ensure_ascii=False)
            )
            parts.append("### 用户")
            parts.append(content.strip())
        elif isinstance(msg, AIMessage):
            parts.append("### 助手")
            text = msg.content if isinstance(msg.content, str) else ""
            if text.strip():
                parts.append(text.strip())
            for tc in msg.tool_calls or []:
                args_repr = json.dumps(tc.get("args", {}), ensure_ascii=False)
                parts.append(f"- **工具调用** `{tc.get('name', '?')}` 参数：`{args_repr}`")
        elif isinstance(msg, ToolMessage):
            content = (
                msg.content
                if isinstance(msg.content, str)
                else json.dumps(msg.content, ensure_ascii=False)
            )
            preview = content.strip()
            if len(preview) > 500:
                preview = preview[:500] + "…"
            parts.append(f"- **工具返回** `{msg.name or '?'}`：{preview}")
        parts.append("")
    return "\n".join(parts)


def _render_md(fm: dict[str, Any], body: str) -> str:
    """frontmatter YAML + body 拼整 md。"""
    fm_str = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm_str}\n---\n\n{body.rstrip()}\n"


def derive_session_md(
    thread_id: str,
    messages: list[BaseMessage],
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> Path | None:
    """每轮 done 后从 messages 派生写 session md。返回写入路径；无新增返回 None。

    新轮边界 = 旧 frontmatter.message_count 作 prev_count；slice messages[prev:]。
    frontmatter 同步：last_active_at / message_count 每轮；related_papers 每 5 轮
    或首次写时同步；topics 占位 [] 留 M5/M6 关键词提取。
    """
    settings = settings or get_settings()
    now = now or dt.datetime.now(dt.UTC)

    total = len(messages)
    if total == 0:
        return None

    existing_path = find_existing_by_thread(thread_id, settings)
    md_path = existing_path or session_md_path(thread_id, now, settings=settings)

    fm, body = _parse_existing(md_path)
    prev_count = int(fm.get("message_count", 0) or 0)
    if total <= prev_count:
        return None

    new_msgs = messages[prev_count:]

    if not fm.get("started_at"):
        fm["thread_id"] = thread_id
        fm["trigger"] = trigger_of(thread_id)
        fm["started_at"] = now.isoformat()
    fm["last_active_at"] = now.isoformat()
    fm["message_count"] = total

    if total % 5 == 0 or "related_papers" not in fm:
        fm["related_papers"] = _extract_related_papers(messages)
    fm.setdefault("topics", [])

    new_seg = _render_messages(new_msgs)
    full_body = (body.rstrip() + "\n\n" + new_seg).strip() if body.strip() else new_seg
    md_content = _render_md(fm, full_body)
    atomic_write(md_path, md_content)
    _log.info(
        "session_md_derived",
        thread_id=thread_id,
        path=str(md_path),
        prev_count=prev_count,
        new_count=len(new_msgs),
        total=total,
    )
    return md_path
