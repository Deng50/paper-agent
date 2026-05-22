"""集中配置：Pydantic Settings 校验必填环境变量（M1 任务 1）。

设计精神：配置是结构化、确定性的事 —— 用 schema 校验闭环兜住，
缺失或非法即在启动期 fail-fast，不把错误拖到运行时。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从 `.env` / 环境变量加载并校验的全局配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 运行环境 ----
    env: Literal["dev", "prod"] = "dev"

    # ---- API 鉴权（必填）----
    api_token: str = Field(min_length=1)

    # ---- PostgreSQL（必填）----
    # 用 psycopg3：scheme 应为 postgresql+psycopg
    database_url: PostgresDsn

    # ---- Anthropic（必填，/status 廉价探针）----
    anthropic_api_key: str = Field(min_length=1)
    # 第三方中转网关（如 newapi）。留空 = 官方 https://api.anthropic.com。
    # 注意：填网关根域名，不要带 /v1（SDK 自己会拼 /v1/messages）。
    anthropic_base_url: str = ""

    # ---- Semantic Scholar（必填，无默认 = fail-fast；不留无 key 双模式）----
    # vendored S2 代码读环境变量 SEMANTIC_SCHOLAR_API_KEY；同时兼容 .env 里写成 S2_API_KEY。
    semantic_scholar_api_key: str = Field(
        min_length=1,
        validation_alias=AliasChoices("SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY"),
    )
    # S2 限流：1 req/s 累计跨所有端点。默认 1.1s 留余量；连踩 429 可调到 1.2。
    s2_min_interval_s: float = Field(default=1.1, ge=1.0)

    # ---- 记忆目录 ----
    memory_dir: Path = Path("./memory")

    # ---- 用户与时区 ----
    user_email: str = "me@example.com"
    timezone: str = "Asia/Shanghai"
    daily_push_hour: int = Field(default=10, ge=0, le=23)

    # ---- paper-search-mcp（M2 接入；M1 留空则 /status 该项 skipped）----
    paper_search_mcp_cmd: str = ""

    # ---- SMTP（M3 用，M1 可空）----
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_driver(cls, v: PostgresDsn) -> PostgresDsn:
        """统一 psycopg3 驱动，避免与 langgraph-checkpoint-postgres 的驱动分裂。"""
        if v.scheme not in ("postgresql+psycopg", "postgresql"):
            raise ValueError(
                f"DATABASE_URL scheme 必须是 postgresql+psycopg（psycopg3），当前为 {v.scheme!r}"
            )
        return v

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def database_url_str(self) -> str:
        """SQLAlchemy / psycopg 用的字符串形式（含 +psycopg 驱动）。"""
        return str(self.database_url)

    @property
    def psycopg_dsn(self) -> str:
        """libpq 风格 DSN（去掉 SQLAlchemy 的 +psycopg），供 LangGraph checkpointer 用。"""
        return self.database_url_str.replace("postgresql+psycopg://", "postgresql://")

    @property
    def smtp_recipients(self) -> list[str]:
        """收件人列表（固定取自 .env，PRD §5 安全）。"""
        return [addr.strip() for addr in self.smtp_to.split(",") if addr.strip()]


@lru_cache
def get_settings() -> Settings:
    """单例式读取配置（进程内缓存）。"""
    return Settings()  # 字段从 env / .env 注入
