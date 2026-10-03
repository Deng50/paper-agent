"""session md 派生写 helper（M4 task 2 / docs/02 §4.3 / docs/05 §5）。

应用层 helper（不是 agent @tool）：在 /chat 的 SSE done 后由路由调用 +
scripts/rebuild_session_md.py（M4-4）共享。从 LangGraph state.values["messages"]
全量 messages 派生正文，整文件原子重写 session md。这样 checkpoint 被强制
重跑或消息替换时不会混入旧正文。复用 tools/paper_md.py::atomic_write。

session md 路径：./memory/sessions/{started_at.date()}/{HH-MM}-{trigger}-{thread_hash}.md
- started_at 首次写时 = datetime.now()，存入 frontmatter；后续读 frontmatter
- trigger：thread_id 前缀 "daily_push:" → daily-push；否则 chat（jobs.py:150 /
  sessions.py:43 既成规则；handover §3.5 字面）

老路径仍按 frontmatter.thread_id 查找并原位更新；新文件加 thread hash 防同分钟碰撞。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
    """计算含 thread hash 的唯一 session md 路径。

    日期 / HH-MM 用 `settings.timezone`（默认 Asia/Shanghai）；M5 修复前用 UTC
    导致北京 15:20 文件名变 07-20-chat.md（差 8 小时）。tz-aware 输入 → astimezone
    转本地；naive 输入 → 视作已是本地时间（向后兼容老 fixture）。
    """
    settings = settings or get_settings()
    if started_at.tzinfo is not None:
        local = started_at.astimezone(ZoneInfo(settings.timezone))
    else:
        local = started_at
    date_str = local.date().isoformat()
    hm_str = local.strftime("%H-%M")
    trig = trigger_of(thread_id)
    thread_suffix = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]
    return settings.memory_dir / "sessions" / date_str / f"{hm_str}-{trig}-{thread_suffix}.md"


def _generate_title(
    thread_id: str, messages: list[BaseMessage], started_at_local: dt.datetime
) -> str:
    """生成 session title（M6 P2 / Q3 owner 拍板：仅首次 derive 生成）。

    规则：
    - daily-push trigger → "每日文献推送 · YYYY-MM-DD"
    - 用户主动会话 → 首条 HumanMessage 前 30 字，太短 fallback 到 "chat · YYYY-MM-DD HH:mm"

    daily-push 的 kickoff 是系统消息「今天是 X，执行每日推送」，不能拿来作 title。
    """
    if trigger_of(thread_id) == "daily-push":
        return f"每日文献推送 · {started_at_local.date().isoformat()}"
    for m in messages:
        if isinstance(m, HumanMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            stripped = content.strip()
            if len(stripped) >= 10:
                return stripped[:30] + ("…" if len(stripped) > 30 else "")
            break
    return f"chat · {started_at_local.strftime('%Y-%m-%d %H:%M')}"


def set_session_title(
    thread_id: str, new_title: str, settings: Settings | None = None
) -> Path | None:
    """用户手动重命名（M6 P2 / PATCH /sessions/{tid}/title 调）。

    设 title_manually_edited=True，未来 derive_session_md 不会覆盖此 title。
    返回写入路径；未找到对应 session md 返回 None。
    """
    settings = settings or get_settings()
    md_path = find_existing_by_thread(thread_id, settings)
    if md_path is None:
        return None
    fm, body = _parse_existing(md_path)
    fm["title"] = new_title.strip() or fm.get("title") or f"chat · {thread_id[:8]}"
    fm["title_manually_edited"] = True
    atomic_write(md_path, _render_md(fm, body))
    _log.info("session_title_updated", thread_id=thread_id, title=fm["title"])
    return md_path


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


def list_all_sessions(settings: Settings | None = None) -> list[dict[str, Any]]:
    """扫 ./memory/sessions/ 返回所有 md 的 frontmatter 摘要，按 last_active_at desc。

    每项含 thread_id / trigger / started_at / last_active_at / message_count /
    topics / related_papers / md_path（相对 memory_dir 父目录的展示路径）。
    跳过 frontmatter 损坏或无 thread_id 的文件。
    """
    settings = settings or get_settings()
    sessions_root = settings.memory_dir / "sessions"
    if not sessions_root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for md in sessions_root.rglob("*.md"):
        try:
            fm, _body = _parse_existing(md)
        except (OSError, yaml.YAMLError):
            continue
        tid = fm.get("thread_id")
        if not tid:
            continue
        try:
            message_count = int(fm.get("message_count", 0) or 0)
        except (TypeError, ValueError):
            continue
        items.append(
            {
                "thread_id": tid,
                "trigger": fm.get("trigger") or trigger_of(str(tid)),
                "started_at": fm.get("started_at"),
                "last_active_at": fm.get("last_active_at"),
                "message_count": message_count,
                "topics": fm.get("topics") or [],
                "related_papers": fm.get("related_papers") or [],
                "md_path": str(md),
                # M6 P2 title 字段：老 session md 无此字段时返 None，前端 fallback 时间命名
                "title": fm.get("title"),
                "title_manually_edited": bool(fm.get("title_manually_edited", False)),
            }
        )
    items.sort(key=lambda x: str(x.get("last_active_at") or ""), reverse=True)
    return items


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
            path = str((tc.get("args") or {}).get("path", "")).replace("\\", "/")
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
            text = msg.text
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

    从完整 checkpoint 重建正文；保留 started_at 与手动标题。
    每轮同步 last_active_at / message_count / related_papers；无变化时不写。
    """
    settings = settings or get_settings()
    now = now or dt.datetime.now(dt.UTC)
    # M5 时区 fix：路径 + frontmatter 时间戳全用本地（Asia/Shanghai）。修前用 UTC
    # 直接 isoformat 出 '...+00:00'，与文件名 HH-MM 配合让北京 15:20 名为 07-20。
    now_local = now.astimezone(ZoneInfo(settings.timezone)) if now.tzinfo else now

    total = len(messages)
    if total == 0:
        return None

    existing_path = find_existing_by_thread(thread_id, settings)
    md_path = existing_path or session_md_path(thread_id, now_local, settings=settings)

    fm, body = _parse_existing(md_path)
    # checkpoint 是唯一事实来源；force rerun/消息替换可能保持甚至缩短消息数量。
    # 全量派生不会把新旧两轮混在一起，也能修复已有正文损坏。
    full_body = _render_messages(messages)
    if body.strip() == full_body.strip() and fm.get("message_count") == total:
        return None

    if not fm.get("started_at"):
        fm["thread_id"] = thread_id
        fm["trigger"] = trigger_of(thread_id)
        fm["started_at"] = now_local.isoformat()
        # M6 P2 / Q3：仅首次 derive 生成 title；用户手动重命名后 title_manually_edited=True 永锁
        fm["title"] = _generate_title(thread_id, messages, now_local)
        fm["title_manually_edited"] = False
    fm["last_active_at"] = now_local.isoformat()
    fm["message_count"] = total

    fm["related_papers"] = _extract_related_papers(messages)
    fm.setdefault("topics", [])

    md_content = _render_md(fm, full_body)
    atomic_write(md_path, md_content)
    _log.info(
        "session_md_derived",
        thread_id=thread_id,
        path=str(md_path),
        total=total,
    )
    return md_path
