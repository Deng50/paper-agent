"""Streamlit 前端（M1 状态页 + M3 每日推送会话）。

M3：触发每日推送、列出 daily-push 会话、展示精选论文卡片并对每篇 👍/👎。
对话式问答（st.chat_message 单栏视图）在 M4 接入。
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_TOKEN = os.environ.get("API_TOKEN", "")
_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

st.set_page_config(page_title="文献情报 Agent", page_icon="📚")
st.title("📚 文献情报 Agent")
st.caption("M3 · 每日推送闭环")


def api_get(path: str) -> tuple[int, Any]:
    try:
        r = httpx.get(f"{API_BASE_URL}{path}", headers=_HEADERS, timeout=20.0)
        return r.status_code, (r.json() if r.content else None)
    except Exception as exc:
        return 0, str(exc)


def api_post(path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    try:
        r = httpx.post(f"{API_BASE_URL}{path}", headers=_HEADERS, json=payload, timeout=20.0)
        return r.status_code, (r.json() if r.content else None)
    except Exception as exc:
        return 0, str(exc)


tab_push, tab_status = st.tabs(["📬 每日推送", "🩺 系统状态"])

# ---------------- 每日推送 ----------------
with tab_push:
    if st.button("▶️ 立即触发一次推送", type="primary"):
        code, data = api_post("/api/v1/admin/trigger/daily-push")
        if code == 202:
            st.success("已触发（后台执行）。稍后刷新查看会话，或查收邮件。")
        else:
            st.error(f"触发失败 HTTP {code}：{data}")

    code, sessions = api_get("/api/v1/sessions")
    if code != 200 or not isinstance(sessions, list):
        st.info(f"暂无法读取会话（HTTP {code}）。后端是否已起？")
        sessions = []

    if not sessions:
        st.write("还没有推送会话。点上面的按钮触发一次。")
    else:
        labels = {
            f"{s['run_date']} · {s['status']} · {s['selected_count']} 篇": s["run_date"]
            for s in sessions
        }
        chosen = st.selectbox("选择推送会话", list(labels.keys()))
        run_date = labels[chosen]

        dcode, detail = api_get(f"/api/v1/sessions/{run_date}")
        if dcode == 200 and isinstance(detail, dict):
            if detail.get("status") != "success":
                st.warning(f"该次推送状态：{detail.get('status')}（{detail.get('error') or '—'}）")
            if detail.get("intro"):
                st.markdown(f"> {detail['intro']}")
            papers = detail.get("selected_papers") or []
            st.caption(f"精选 {len(papers)} 篇")
            for p in papers:
                with st.container(border=True):
                    title = p.get("title", "(无标题)")
                    url = p.get("url")
                    st.markdown(f"**[{title}]({url})**" if url else f"**{title}**")
                    if p.get("authors"):
                        st.caption(", ".join(p["authors"]))
                    if p.get("score") is not None:
                        st.caption(f"评分 {p['score']} · {p.get('reason', '')}")
                    if p.get("abstract"):
                        st.write(p["abstract"][:400] + ("…" if len(p["abstract"]) > 400 else ""))
                    pid = p.get("paper_id", "")
                    c1, c2, _ = st.columns([1, 1, 6])
                    if c1.button("👍", key=f"up_{run_date}_{pid}"):
                        fc, _fd = api_post(
                            "/api/v1/feedback", {"paper_id": pid, "signal_type": "up"}
                        )
                        st.toast("已记录 👍" if fc == 201 else f"重复/失败（HTTP {fc}）")
                    if c2.button("👎", key=f"down_{run_date}_{pid}"):
                        fc, _fd = api_post(
                            "/api/v1/feedback", {"paper_id": pid, "signal_type": "down"}
                        )
                        st.toast("已记录 👎" if fc == 201 else f"重复/失败（HTTP {fc}）")
        else:
            st.error(f"读取详情失败 HTTP {dcode}：{detail}")

# ---------------- 系统状态 ----------------
with tab_status:
    code, data = api_get("/api/v1/status")
    if isinstance(data, dict) and data.get("status") == "ok":
        st.success("alive ✅ — 所有依赖正常")
    elif isinstance(data, dict) and data.get("status") == "degraded":
        st.warning("alive ⚠️ — 部分依赖未就绪")
    else:
        st.error(f"unhealthy ❌ — HTTP {code}")

    if isinstance(data, dict):
        sched = data.get("scheduler", {})
        if isinstance(sched, dict):
            st.metric("调度器", "运行中 ✅" if sched.get("running") else "未运行")
            if sched.get("next_daily_push_at"):
                st.caption(f"下次推送：{sched['next_daily_push_at']}")
        checks = data.get("checks", {})
        if isinstance(checks, dict):
            cols = st.columns(len(checks) or 1)
            for col, (name, c) in zip(cols, checks.items(), strict=False):
                ok = bool(c.get("ok")) if isinstance(c, dict) else False
                col.metric(name, "✅" if ok else "❌")
        with st.expander("原始 /status 响应"):
            st.json(data)
