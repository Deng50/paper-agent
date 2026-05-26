"""M3 邮件单测：渲染 HTML 转义 + 收件人 fail-fast + aiosmtplib 调用（无需 PG）。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from lit_agent.core.config import get_settings
from lit_agent.tools.mail import NoRecipientError, render_daily_push, send_email

_PAPERS = [
    {
        "paper_id": "arxiv-1",
        "title": "A <script>alert(1)</script> Paper",
        "authors": ["Alice", "Bob"],
        "abstract": "abc " * 200,
        "url": "https://x/1",
        "score": 8.5,
        "reason": "与画像相关",
    }
]


def test_render_escapes_untrusted_title() -> None:
    """论文标题是不可信内容 —— 必须 HTML 转义防注入。"""
    html = render_daily_push("测试导语", _PAPERS, "2026-05-22")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "测试导语" in html
    assert "2026-05-22" in html


def test_send_email_no_recipient_fail_fast() -> None:
    """SMTP_TO 显式置空 → NoRecipientError，不静默吞推送。

    用 `model_copy` 而非 `get_settings()`：避免读到 `.env` 真 SMTP_TO 导致 fail-fast 失效
    （get_settings() 是 lru_cache 单例，由 pydantic-settings 在测试进程里加载 .env）。
    """
    settings = get_settings().model_copy(update={"smtp_to": ""})

    async def _run() -> None:
        with pytest.raises(NoRecipientError):
            await send_email("subj", "<p>body</p>", settings=settings)

    asyncio.run(_run())


def test_send_email_calls_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """配了收件人 → 调 aiosmtplib.send，且收件人取自 settings（不来自参数注入）。"""
    mock_send = AsyncMock()
    monkeypatch.setattr("aiosmtplib.send", mock_send)
    settings = get_settings().model_copy(
        update={
            "smtp_to": "me@example.com",
            "smtp_host": "localhost",
            "smtp_from": "agent@example.com",
            "smtp_port": 587,
        }
    )

    async def _run() -> None:
        await send_email("每日推送", "<p>hi</p>", settings=settings)

    asyncio.run(_run())
    assert mock_send.await_count == 1
    sent_msg = mock_send.await_args.args[0]
    assert sent_msg["To"] == "me@example.com"
    assert sent_msg["Subject"] == "每日推送"
