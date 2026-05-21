"""Streamlit 占位前端（M1 任务 7）。

M1 只做一件事：调后端 /status，显示 "alive ✅" 与四项依赖健康。
后续单栏对话视图在 M3/M4 接入（st.chat_message）。
"""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_TOKEN = os.environ.get("API_TOKEN", "")

st.set_page_config(page_title="文献情报 Agent", page_icon="📚")
st.title("📚 文献情报 Agent")
st.caption("M1 · 地基与最小链路")


def fetch_status() -> tuple[int, dict[str, object] | None, str | None]:
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    try:
        resp = httpx.get(f"{API_BASE_URL}/api/v1/status", headers=headers, timeout=15.0)
        if resp.headers.get("content-type", "").startswith("application/json") or resp.is_success:
            return resp.status_code, resp.json(), None
        return resp.status_code, None, resp.text
    except Exception as exc:
        return 0, None, str(exc)


if st.button("刷新状态", type="primary") or True:
    code, data, err = fetch_status()

    if data and data.get("status") == "ok":
        st.success("alive ✅ — 所有依赖正常")
    elif data and data.get("status") == "degraded":
        st.warning("alive ⚠️ — 部分依赖未就绪（M1 阶段 paper_search_mcp 尚未接入属正常）")
    else:
        st.error(f"unhealthy ❌ — HTTP {code}")
        if err:
            st.code(err)

    if data:
        st.subheader(f"系统状态 · v{data.get('version', '?')}")
        checks = data.get("checks", {})
        if isinstance(checks, dict):
            cols = st.columns(len(checks) or 1)
            for col, (name, c) in zip(cols, checks.items(), strict=False):
                with col:
                    ok = bool(c.get("ok")) if isinstance(c, dict) else False
                    st.metric(name, "✅" if ok else "❌")
        with st.expander("原始 /status 响应"):
            st.json(data)
