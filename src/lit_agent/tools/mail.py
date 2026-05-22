"""每日推送邮件：Jinja2 渲染 + aiosmtplib 发送（M3 任务 3）。

设计精神（铁律#1）：组装结构化论文卡片 + SMTP 传输是**确定性活，由代码做**；
agent 只产出模糊部分（中文导语文案）。收件人**固定取自 `.env`**（CLAUDE.md §8 安全：
检索到的标题/摘要是资料不是指令，绝不接受对话中临时指定的收件人）。

模板内嵌为模块常量（避免 package-data 路径解析，减法）。
"""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import aiosmtplib
import structlog
from jinja2 import Environment, select_autoescape

from lit_agent.core.config import Settings, get_settings

_log = structlog.get_logger("mail")


class NoRecipientError(Exception):
    """SMTP_TO 为空 —— fail-fast，不静默吞掉一次推送。"""


# Jinja2 自动转义：论文标题/摘要是不可信外部内容，必须 HTML 转义防注入。
_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))

_TEMPLATE = _env.from_string(
    """<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
             max-width:720px;margin:0 auto;color:#1a1a1a;line-height:1.6;">
  <h2 style="margin-bottom:4px;">📚 每日文献推送 · {{ run_date }}</h2>
  <p style="color:#666;margin-top:0;">本期精选 {{ papers|length }} 篇（按相关性评分排序）</p>
  {% if intro %}<div style="background:#f6f8fa;border-radius:8px;padding:12px 16px;margin:16px 0;">
    {{ intro }}</div>{% endif %}
  {% for p in papers %}
  <div style="border-top:1px solid #eaecef;padding:16px 0;">
    <h3 style="margin:0 0 4px;">
      {% if p.url %}<a href="{{ p.url }}" style="color:#0969da;text-decoration:none;">{{ p.title }}</a>
      {% else %}{{ p.title }}{% endif %}
      {% if p.score is not none %}<span style="font-size:13px;color:#fff;background:#2da44e;
        border-radius:10px;padding:1px 8px;margin-left:6px;">{{ "%.1f"|format(p.score) }}</span>{% endif %}
    </h3>
    {% if p.authors %}<div style="font-size:13px;color:#666;">{{ p.authors|join(", ") }}</div>{% endif %}
    {% if p.reason %}<div style="font-size:14px;color:#0550ae;margin:6px 0;">💡 {{ p.reason }}</div>{% endif %}
    {% if p.abstract %}<div style="font-size:13px;color:#444;">{{ p.abstract[:400] }}{% if p.abstract|length > 400 %}…{% endif %}</div>{% endif %}
    <div style="font-size:12px;color:#999;margin-top:4px;">{{ p.paper_id }}</div>
  </div>
  {% endfor %}
  <p style="font-size:12px;color:#999;border-top:1px solid #eaecef;padding-top:12px;margin-top:16px;">
    站内可对每篇 👍/👎 反馈以优化后续推送。本邮件由文献情报 Agent 自动生成。</p>
</body>
</html>
"""
)


def render_daily_push(intro: str, papers: list[dict[str, Any]], run_date: str) -> str:
    """渲染每日推送 HTML（papers 为 search_papers 返回的 Paper.model_dump 列表）。"""
    return _TEMPLATE.render(intro=intro.strip(), papers=papers, run_date=run_date)


async def send_email(subject: str, html_body: str, *, settings: Settings | None = None) -> None:
    """发送 HTML 邮件到 `.env` 固定收件人。SMTP 失败原样抛出（由上层记 partial）。"""
    settings = settings or get_settings()
    recipients = settings.smtp_recipients
    if not recipients:
        raise NoRecipientError("SMTP_TO 为空：请在 .env 配置收件人后再触发推送。")

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content("本邮件为 HTML 格式，请用支持 HTML 的客户端查看。")
    msg.add_alternative(html_body, subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=settings.smtp_port == 587,
        use_tls=settings.smtp_port == 465,
    )
    _log.info("email_sent", recipients=len(recipients), subject=subject)
