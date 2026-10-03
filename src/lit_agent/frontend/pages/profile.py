"""只读画像页；画像仍由每晚反馈更新任务负责写入。"""

import httpx
import streamlit as st

from lit_agent.frontend.config import settings

st.set_page_config(page_title="偏好画像 · 文献情报 Agent", page_icon="👤")
st.title("👤 偏好画像")
st.caption("每天 22:55 汇总反馈，23:00 更新画像，供次日推送使用。")

try:
    response = httpx.get(
        f"{settings.api_base_url}/api/v1/memory/profile",
        headers={"Authorization": f"Bearer {settings.api_token}"},
        timeout=20,
    )
    if response.status_code == 404:
        st.info("画像尚未初始化，请先运行 scripts/init_memory.py。")
    else:
        response.raise_for_status()
        profile = response.json()
        st.caption(f"最近更新：{profile.get('updated_at') or '尚无反馈'}")
        st.markdown(profile.get("summary_markdown") or "暂无画像摘要。")
        st.subheader("关键词权重")
        st.json(profile.get("keyword_weights") or {})
        st.subheader("减少推荐的方向")
        st.write("、".join(profile.get("negative_keywords") or []) or "暂无")
        st.subheader("初始检索方向")
        for query in profile.get("seed_queries") or []:
            st.write(query)
except (httpx.HTTPError, ValueError) as exc:
    st.error(f"暂无法读取画像：{exc}")
