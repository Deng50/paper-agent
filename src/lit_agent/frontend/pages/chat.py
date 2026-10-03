"""Streamlit /chat 流式问答页（M4 task 4 + PR-2 Bug 2 历史会话管理）。

owner 拍板 Q7：streamlit st.chat_message + st.write_stream + 自建 30-LOC SSE
parser；同步 httpx.Client.stream() 省 asyncio wrapper。不引入 sse-starlette。

PR-2 Bug 2 改造（owner 8 条能力清单 + 我之前 plan 细节 1/2）：
- 启动 / 刷新自动拉 GET /api/v1/chat/sessions 填左侧栏历史列表
- 点击历史会话 → 拉 GET /api/v1/chat/sessions/{tid}/messages → 渲染（保留
  tool_calls / ToolMessage 全部，与流式时一致）
- 🆕 新建会话只清当前 session_state（thread_id + messages），不删历史 md
- 🗑 删除按钮二次确认（红色二态机）：点 1 次 → ⚠️ 再点确认 → 点 2 次真删
- 首次 load 且无 session_id 时自动恢复最近一个历史会话（owner 第 8 条）
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import httpx
import streamlit as st

from lit_agent.frontend.sse import parse_sse_events as _parse_sse_events

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_TOKEN = os.environ.get("API_TOKEN", "")
_HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Accept": "text/event-stream",
}
_JSON_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

st.set_page_config(page_title="💬 Chat · 文献情报 Agent", page_icon="💬")
st.title("💬 跨日召回对话")
st.caption("M4 · /chat SSE 流式问答 + 历史会话管理")


def _api_get(path: str) -> tuple[int, Any]:
    try:
        r = httpx.get(f"{API_BASE_URL}{path}", headers=_JSON_HEADERS, timeout=20.0)
        return r.status_code, (r.json() if r.content else None)
    except Exception as exc:
        return 0, str(exc)


def _api_delete(path: str) -> tuple[int, Any]:
    try:
        r = httpx.delete(f"{API_BASE_URL}{path}", headers=_JSON_HEADERS, timeout=20.0)
        return r.status_code, (r.json() if r.content else None)
    except Exception as exc:
        return 0, str(exc)


def _api_patch(path: str, payload: dict[str, Any]) -> tuple[int, Any]:
    try:
        r = httpx.patch(f"{API_BASE_URL}{path}", headers=_JSON_HEADERS, json=payload, timeout=20.0)
        return r.status_code, (r.json() if r.content else None)
    except Exception as exc:
        return 0, str(exc)


def _display_title(s: dict[str, Any]) -> str:
    """会话显示名：优先 title 字段（M6 P2 新增），fallback 老的「trigger · time (n)」。"""
    title = s.get("title")
    if title and isinstance(title, str) and title.strip():
        return title.strip()
    # fallback：老 session md 无 title 字段
    trigger = s.get("trigger", "chat")
    last_active = str(s.get("last_active_at") or "")[:16].replace("T", " ")
    return f"{trigger} · {last_active}"


for _key, _default in (
    ("chat_session_id", None),
    ("chat_messages", []),
    ("delete_confirm_tid", None),
    ("history_loaded_once", False),
    ("rename_active_tid", None),  # M6 P2：哪个 session 正在被重命名（None = 没在改）
):
    if _key not in st.session_state:
        st.session_state[_key] = _default


def _load_session_messages(thread_id: str) -> None:
    """切到历史 thread_id，拉 /messages 填 chat_messages（保留 tool/tool_result）。"""
    st.session_state["chat_session_id"] = thread_id
    st.session_state["delete_confirm_tid"] = None  # 清掉删除二次确认状态
    code, data = _api_get(f"/api/v1/chat/sessions/{thread_id}/messages")
    if code != 200 or not isinstance(data, dict):
        st.session_state["chat_messages"] = []
        return
    msgs: list[dict[str, Any]] = []
    for m in data.get("messages", []) or []:
        msgs.append(
            {
                "role": m.get("role"),
                "content": m.get("content"),
                "tool_calls": m.get("tool_calls") or [],
                "name": m.get("name"),
                "tool_call_id": m.get("tool_call_id"),
            }
        )
    st.session_state["chat_messages"] = msgs


def _stream_tokens_and_collect(
    user_content: str,
    session_id: str | None,
    tool_box: Any,
    citation_box: Any,
) -> Iterator[str]:
    """调 /chat SSE：token 事件 yield delta（喂 write_stream）；tool / citation
    渲染到侧 UI；done 时把 token_usage / tool_calls / citations 落 session_state。"""
    payload: dict[str, Any] = {"content": user_content}
    if session_id:
        payload["session_id"] = session_id

    tool_calls: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    token_usage: dict[str, Any] = {}

    try:
        with (
            httpx.Client(timeout=httpx.Timeout(60.0, read=300.0)) as client,
            client.stream(
                "POST",
                f"{API_BASE_URL}/api/v1/chat",
                headers=_HEADERS,
                json=payload,
            ) as resp,
        ):
            if resp.status_code != 200:
                resp.read()
                yield f"\n[HTTP {resp.status_code}] {resp.text[:300]}"
                return
            for event, data in _parse_sse_events(resp.iter_bytes()):
                if event == "meta":
                    st.session_state["chat_session_id"] = data.get("session_id")
                elif event == "tool":
                    tool_calls.append(data)
                    with tool_box:
                        args_repr = json.dumps(data.get("args", {}), ensure_ascii=False)
                        st.markdown(f"🔧 `{data.get('name')}` `{args_repr}`")
                elif event == "citation":
                    for p in data.get("papers", []) or []:
                        citations.append(p)
                        with citation_box:
                            label = p.get("title") or p.get("paper_id", "?")
                            url = p.get("url", "")
                            st.markdown(f"📄 [{label}]({url})")
                elif event == "token":
                    delta = data.get("delta", "")
                    if delta:
                        yield delta
                elif event == "done":
                    token_usage = data.get("token_usage", {}) or {}
                elif event == "error":
                    code = str(data.get("code") or "ERROR")
                    detail = str(data.get("detail") or "?")
                    if code == "DANGLING_TOOL_CALL":
                        yield (
                            "\n\n⚠️ **会话历史中断**：上一轮工具调用未完成。\n\n"
                            "请点左侧栏「🆕 新建会话」按钮开新对话后重试。"
                        )
                    else:
                        yield f"\n\n⚠️ **[{code}]** {detail}"
    except httpx.HTTPError as exc:
        yield f"\n[network] {exc}"
    finally:
        st.session_state["chat_last_token_usage"] = token_usage
        st.session_state["chat_last_tool_calls"] = tool_calls
        st.session_state["chat_last_citations"] = citations


# ---- Sidebar: 历史会话列表 + 当前会话 ----
with st.sidebar:
    st.subheader("📚 历史会话")
    code, sess_data = _api_get("/api/v1/chat/sessions")
    items: list[dict[str, Any]] = sess_data.get("items", []) if isinstance(sess_data, dict) else []
    if not items:
        st.caption("（无历史会话）")
    else:
        st.caption(f"共 {len(items)} 条")
        for s in items:
            tid = str(s.get("thread_id") or "")
            if not tid:
                continue
            msg_count = s.get("message_count", 0)
            # M6 P2：用 title 显示（fallback 老格式）
            display_label = f"{_display_title(s)} ({msg_count})"
            current = st.session_state.get("chat_session_id") == tid
            btn_label = f"▶ {display_label}" if current else display_label

            # M6 P2：3-dot menu via st.popover（streamlit 1.32+ 支持，pyproject 锁 1.57）
            cols = st.columns([5, 1])
            if cols[0].button(btn_label, key=f"sess_{tid}", use_container_width=True):
                _load_session_messages(tid)
                st.rerun()

            with cols[1].popover("⋯", help="重命名 / 删除"):
                # 重命名表单
                rename_default = (
                    s.get("title")
                    if s.get("title")
                    else f"chat · {str(s.get('last_active_at') or '')[:16].replace('T', ' ')}"
                )
                new_title = st.text_input(
                    "新标题",
                    value=rename_default,
                    key=f"rename_input_{tid}",
                    max_chars=120,
                )
                if st.button("✏️ 重命名", key=f"rename_btn_{tid}", use_container_width=True):
                    title_value = (new_title or "").strip()
                    if not title_value:
                        st.toast("标题不能为空")
                    else:
                        rcode, _ = _api_patch(
                            f"/api/v1/sessions/{tid}/title", {"title": title_value}
                        )
                        if rcode == 200:
                            preview = (
                                f"{title_value[:20]}…" if len(title_value) > 20 else title_value
                            )
                            st.toast(f"已重命名为「{preview}」")
                            st.rerun()
                        else:
                            st.toast(f"重命名失败 HTTP {rcode}")
                st.divider()
                # 删除（二次确认）
                confirm_tid = st.session_state.get("delete_confirm_tid")
                if confirm_tid == tid:
                    if st.button(
                        "⚠️ 再点确认删除", key=f"del_confirm_{tid}", use_container_width=True
                    ):
                        dcode, _ = _api_delete(f"/api/v1/sessions/{tid}")
                        if dcode in (200, 204):
                            if st.session_state.get("chat_session_id") == tid:
                                st.session_state["chat_session_id"] = None
                                st.session_state["chat_messages"] = []
                            st.toast(f"已删除 {tid[:12]}…")
                        else:
                            st.toast(f"删除失败 HTTP {dcode}")
                        st.session_state["delete_confirm_tid"] = None
                        st.rerun()
                else:
                    if st.button("🗑 删除", key=f"del_{tid}", use_container_width=True):
                        st.session_state["delete_confirm_tid"] = tid
                        st.rerun()

    st.divider()
    st.subheader("当前会话")
    sid = st.session_state.get("chat_session_id")
    if sid:
        st.code(sid, language=None)
    else:
        st.caption("（新会话；发消息后自动分配 thread_id）")
    if st.button("🆕 新建会话", use_container_width=True):
        st.session_state["chat_session_id"] = None
        st.session_state["chat_messages"] = []
        st.session_state["delete_confirm_tid"] = None
        st.rerun()


# ---- 首次 load 自动恢复最近一个历史会话（owner 第 8 条字面要求） ----
if (
    not st.session_state["history_loaded_once"]
    and st.session_state.get("chat_session_id") is None
    and items
):
    _load_session_messages(items[0]["thread_id"])
    st.session_state["history_loaded_once"] = True
    st.rerun()


def _render_message_blocks(content: Any) -> None:
    """统一渲染 str / list of Anthropic content blocks。"""
    if isinstance(content, str) and content.strip():
        st.markdown(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                txt = str(block.get("text", "") or "")
                if txt:
                    st.markdown(txt)


# ---- 渲染当前会话所有 messages（含 historical user/assistant/tool） ----
for m in st.session_state["chat_messages"]:
    role = m.get("role")
    if role == "user":
        with st.chat_message("user"):
            _render_message_blocks(m.get("content"))
    elif role == "assistant":
        with st.chat_message("assistant"):
            _render_message_blocks(m.get("content"))
            for tc in m.get("tool_calls") or []:
                args_repr = json.dumps(tc.get("args", {}), ensure_ascii=False)
                st.caption(f"🔧 `{tc.get('name')}` {args_repr}")
            for c in m.get("citations") or []:
                label = c.get("title") or c.get("paper_id", "?")
                url = c.get("url", "")
                st.caption(f"📄 [{label}]({url})")
    elif role == "tool":
        with (
            st.chat_message("assistant"),
            st.expander(f"🛠 工具返回 `{m.get('name', '?')}`", expanded=False),
        ):
            content = m.get("content")
            if isinstance(content, str):
                preview = content[:1500] + ("…" if len(content) > 1500 else "")
                st.code(preview, language="json")
            else:
                st.json(content)


# ---- 用户输入 + 流式回复 ----
prompt = st.chat_input("发消息……")
if prompt:
    st.session_state["chat_messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        tool_box = st.expander("🔧 工具调用", expanded=False)
        citation_box = st.expander("📄 引用文献", expanded=True)
        token_stream = _stream_tokens_and_collect(
            prompt,
            st.session_state.get("chat_session_id"),
            tool_box,
            citation_box,
        )
        full_text = st.write_stream(token_stream)

    st.session_state["chat_messages"].append(
        {
            "role": "assistant",
            "content": full_text if isinstance(full_text, str) else "",
            "tool_calls": st.session_state.get("chat_last_tool_calls", []),
            "citations": st.session_state.get("chat_last_citations", []),
        }
    )
