"""M1 验收相关单测：健康检查、RFC7807 鉴权、记忆初始化、配置校验。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from scripts.init_memory import MEMORY_SUBDIRS, SKILL_PLACEHOLDERS, init_memory


def test_health_no_auth(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_status_requires_auth_rfc7807(client: TestClient) -> None:
    resp = client.get("/api/v1/status")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "UNAUTHORIZED"
    assert body["status"] == 401
    assert body["trace_id"]


def test_status_bad_token_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/status", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_status_shape_with_auth(client: TestClient) -> None:
    # 不依赖真实 PG/Anthropic：仅校验响应结构与四项检查存在。
    resp = client.get("/api/v1/status", headers={"Authorization": "Bearer test-token-123"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["checks"]) == {"postgres", "memory_dir", "paper_search_mcp", "anthropic"}
    assert body["status"] in {"ok", "degraded", "error"}


def test_request_id_echoed(client: TestClient) -> None:
    resp = client.get("/health", headers={"X-Request-Id": "abc-123"})
    assert resp.headers["X-Request-Id"] == "abc-123"


def test_init_memory_idempotent(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    skills_dir = tmp_path / "skills"
    init_memory(memory_dir, skills_dir)
    # 再跑一次应不报错（幂等）
    init_memory(memory_dir, skills_dir)

    for sub in MEMORY_SUBDIRS:
        assert (memory_dir / sub).is_dir()
    assert (memory_dir / "profile" / "profile.md").is_file()
    for name in SKILL_PLACEHOLDERS:
        assert (skills_dir / name).is_file()


def test_config_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from lit_agent.core.config import Settings

    for var in ("API_TOKEN", "DATABASE_URL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_config_rejects_non_psycopg_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    from lit_agent.core.config import Settings

    monkeypatch.setenv("API_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("DATABASE_URL", "mysql://u:p@localhost/db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_plain_postgres_url_uses_installed_psycopg_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    from lit_agent.core.config import Settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.database_url_str == "postgresql+psycopg://u:p@localhost/db"
    assert settings.psycopg_dsn == "postgresql://u:p@localhost/db"


def test_invalid_timezone_fails_during_configuration() -> None:
    from lit_agent.core.config import Settings

    with pytest.raises(ValidationError, match="IANA"):
        Settings(timezone="invalid-zone")  # type: ignore[call-arg]
