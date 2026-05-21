"""测试夹具：在导入应用前注入最小必填环境变量。

这些值仅满足 Settings 校验；/health 与鉴权测试不真正连 PG / Anthropic。
"""

from __future__ import annotations

import os

os.environ.setdefault("ENV", "dev")
os.environ.setdefault("API_TOKEN", "test-token-123")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://lit:lit@localhost:5432/lit_agent_test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
os.environ.setdefault("MEMORY_DIR", "./memory")

import pytest
from fastapi.testclient import TestClient

from lit_agent.api.main import create_app


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())
