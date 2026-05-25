"""Streamlit /chat 流式问答页（M4 task 4 / docs/05 §5）。

owner 拍板 Q7：streamlit st.chat_message + st.write_stream + 自建 30-LOC SSE
parser；同步 httpx.Client.stream() 省 asyncio wrapper（Q7 修订路径）。
不引入 sse-starlette 或 httpx-sse —— 减法 + 不动 uv.lock。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_TOKEN = os.environ.get("API_TOKEN", "")
_HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Accept": "text/event-stream",
}

st.set_page_config(page_title="💬 Chat · 文献情报 Agent", page_icon="💬")
st.title("💬 跨日召回对话")
st.caption("M4 · /chat SSE 流式问答")

if "chat_session_id" not in st.session_state:
    st.session_state["chat_session_id"] = None
if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"] = []


def _parse_sse_events(byte_stream: Iterator[bytes]) -> Iterator[tuple[str, dict[str, Any]]]:
    """SSE wire parser：按 `\\n\\n` 拆 event block 流式 yield (event_name, data)。

    跳过注释行（`: keepalive`）。data 多行按 SSE 规范用 `\\n` 拼接后 json.loads。
    """
    buffer = ""
    for chunk in byte_stream:
        buffer += chunk.decode("utf-8", errors="replace")
        while "\n\n" in buffer:
            block, _, buffer = buffer.partition("\n\n")
            event_name = ""
            data_lines: list[str] = []
            for raw_line in block.split("\n"):
                line = raw_line.rstrip("\r")
                if line.startswith(":") or not line:
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            if not event_name:
                continue
            data_raw = "\n".join(data_lines)
            try:
                data = json.loads(data_raw) if data_raw else {}
            except json.JSONDecodeError:
                data = {"raw": data_raw}
            yield event_name, data


def _stream_tokens_and_collect(
    user_content: str,
    session_id: str | None,
    tool_box: Any,
    citation_box: Any,
) -> Iterator[str]:
    """调 /chat SSE：token 事件 yield delta（喂 write_stream）；tool / citation
    渲染到侧 UI；done 时把 token_usage / tool_calls / citations 落 session_state
    供本轮 assistant message 渲染时取。"""
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
                            "请点左侧栏「🗑 新建会话（清当前对话）」按钮开新对话后重试。"
                        )
                    else:
                        yield f"\n\n⚠️ **[{code}]** {detail}"
    except httpx.HTTPError as exc:
        yield f"\n[network] {exc}"
    finally:
        st.session_state["chat_last_token_usage"] = token_usage
        st.session_state["chat_last_tool_calls"] = tool_calls
        st.session_state["chat_last_citations"] = citations


for m in st.session_state["chat_messages"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        for tc in m.get("tool_calls", []) or []:
            args_repr = json.dumps(tc.get("args", {}), ensure_ascii=False)
            st.caption(f"🔧 `{tc.get('name')}` {args_repr}")
        for c in m.get("citations", []) or []:
            label = c.get("title") or c.get("paper_id", "?")
            url = c.get("url", "")
            st.caption(f"📄 [{label}]({url})")

with st.sidebar:
    st.subheader("会话")
    sid = st.session_state.get("chat_session_id")
    if sid:
        st.code(sid, language=None)
    else:
        st.write("（未开始）")
    if st.button("🗑 新建会话（清当前对话）"):
        st.session_state["chat_session_id"] = None
        st.session_state["chat_messages"] = []
        st.rerun()

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
