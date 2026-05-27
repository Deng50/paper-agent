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


# M6 P0：反馈类型枚举（与后端 feedback.py 的 _POSITIVE_TYPES / _NEGATIVE_TYPES 同步）
_POSITIVE_TYPE_LABELS = {
    "topic_relevant": "主题相关",
    "useful_method": "方法有启发",
    "related_to_current_research": "和当前课题相关",
    "want_follow_up": "想继续追踪该方向",
    "high_quality": "论文质量较高",
    "other": "其他",
}
_NEGATIVE_TYPE_LABELS = {
    "topic_irrelevant": "主题不相关",
    "low_quality": "论文质量一般",
    "too_theoretical": "太偏理论",
    "too_experimental": "太偏实验",
    "too_engineering": "太偏工程应用",
    "duplicate": "重复 / 已读过",
    "not_current_focus": "不是当前阶段重点",
    "other": "其他",
}


def _render_feedback_form(paper_id: str, signal_type: str, run_date: str) -> None:
    """M6 P0 反馈表单（1-call 模型）：feedback_type dropdown + comment 输入 + 2 个提交按钮。

    「提交」带 feedback_type / comment；「仅保存点赞点踩」忽略表单内容，只发 signal_type。
    任一按钮 → 1 次 POST /api/v1/feedback。
    """
    labels_dict = _POSITIVE_TYPE_LABELS if signal_type == "up" else _NEGATIVE_TYPE_LABELS
    options = list(labels_dict.keys())
    chosen_label = st.selectbox(
        "反馈类型（可选）",
        options=options,
        format_func=lambda k: labels_dict.get(k, k),
        index=None,
        placeholder="不选 = 仅保存点赞点踩",
        key=f"fbtype_{signal_type}_{run_date}_{paper_id}",
    )
    comment = st.text_area(
        "原因（可选）",
        max_chars=2000,
        placeholder="自由文本，例如：与硫化物方向相关、量纲分析章节有启发……",
        key=f"fbcomment_{signal_type}_{run_date}_{paper_id}",
    )
    col_submit, col_skip = st.columns(2)
    with col_submit:
        if st.button(
            "✅ 提交", key=f"fbsub_{signal_type}_{run_date}_{paper_id}", use_container_width=True
        ):
            payload: dict[str, Any] = {"paper_id": paper_id, "signal_type": signal_type}
            if chosen_label:
                payload["feedback_type"] = chosen_label
            if comment.strip():
                payload["comment"] = comment.strip()
            payload["source"] = "daily_push"
            fc, _fd = api_post("/api/v1/feedback", payload)
            if fc == 201:
                tag = labels_dict.get(chosen_label or "", "")
                st.toast(f"已记录 {'👍' if signal_type == 'up' else '👎'} · {tag or '无原因'}")
            elif fc == 409:
                st.toast("5 分钟内重复，已忽略")
            else:
                st.toast(f"失败（HTTP {fc}）")
    with col_skip:
        if st.button(
            "⏭️ 仅保存点赞点踩",
            key=f"fbskip_{signal_type}_{run_date}_{paper_id}",
            use_container_width=True,
        ):
            fc, _fd = api_post(
                "/api/v1/feedback",
                {"paper_id": paper_id, "signal_type": signal_type, "source": "daily_push"},
            )
            if fc == 201:
                st.toast(f"已记录 {'👍' if signal_type == 'up' else '👎'}（无原因）")
            elif fc == 409:
                st.toast("5 分钟内重复，已忽略")
            else:
                st.toast(f"失败（HTTP {fc}）")


tab_push, tab_status = st.tabs(["📬 每日推送", "🩺 系统状态"])

# ---------------- 每日推送 ----------------
with tab_push:
    force_rerun = st.checkbox(
        "强制重跑（覆盖今日 success）",
        value=False,
        help="今日 pushes.status=success 时默认 already_done 跳过；勾选则强制重新搜+评分+发邮件。",
    )
    if st.button("▶️ 立即触发一次推送", type="primary"):
        code, data = api_post("/api/v1/admin/trigger/daily-push", payload={"force": force_rerun})
        if code == 202:
            label = "已触发（强制重跑）" if force_rerun else "已触发（后台执行）"
            st.success(f"{label}。稍后刷新查看会话，或查收邮件。")
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
                    # M6 P0 1-call 模型（owner Q1 a）：点 👍/👎 展开表单 → 表单提交才真存
                    # 默认 expander 收起；用户点 ▾ 展开后填 feedback_type/comment，再点
                    # 「提交」或「仅保存点赞点踩」（跳过原因）发 1 次 POST。
                    c1, c2 = st.columns([1, 1])
                    with c1.popover("👍 反馈"):
                        _render_feedback_form(pid, "up", run_date)
                    with c2.popover("👎 反馈"):
                        _render_feedback_form(pid, "down", run_date)
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
