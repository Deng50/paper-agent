from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lit_agent.core.config import get_settings

AUTH = {"Authorization": "Bearer test-token-123"}


def test_memory_pagination_filters_details_and_auth(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "memory_dir", tmp_path)
    directory = tmp_path / "papers" / "2026-10-03"
    directory.mkdir(parents=True)
    for i in range(3):
        (directory / f"arxiv-{i}.md").write_text(
            f"---\npaper_id: arxiv-{i}\nsource: arxiv\ntitle: Sulfide {i}\n---\n\nabstract\n",
            encoding="utf-8",
        )
    assert client.get("/api/v1/memory/papers").status_code == 401
    first = client.get(
        "/api/v1/memory/papers",
        params={"limit": 2, "q": "sulfide", "source": "arxiv", "date": "2026-10-03"},
        headers=AUTH,
    ).json()
    assert [p["paper_id"] for p in first["items"]] == ["arxiv-2", "arxiv-1"]
    assert first["has_more"]
    second = client.get(
        "/api/v1/memory/papers", params={"limit": 2, "cursor": first["next_cursor"]}, headers=AUTH
    ).json()
    assert [p["paper_id"] for p in second["items"]] == ["arxiv-0"]
    assert not second["has_more"]
    detail = client.get("/api/v1/memory/papers/arxiv-1", headers=AUTH).json()
    assert detail["body_markdown"].strip() == "abstract"
    assert client.get("/api/v1/memory/papers/absent", headers=AUTH).status_code == 404
    assert client.get("/api/v1/memory/papers?limit=-1", headers=AUTH).status_code == 422
    assert client.get("/api/v1/memory/papers?cursor=???", headers=AUTH).status_code == 422


def test_profile_endpoint_reads_canonical_file(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "memory_dir", tmp_path)
    assert client.get("/api/v1/memory/profile", headers=AUTH).status_code == 404
    profile = tmp_path / "profile" / "profile.md"
    profile.parent.mkdir()
    profile.write_text(
        "---\nkeyword_weights: {sulfide: 0.8}\nnegative_keywords: []\n---\n\n偏好固态电解质\n",
        encoding="utf-8",
    )
    data = client.get("/api/v1/memory/profile", headers=AUTH).json()
    assert data["keyword_weights"] == {"sulfide": 0.8}
    assert "偏好固态电解质" in data["summary_markdown"]


def test_frontend_loads_dotenv_without_backend_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lit_agent.frontend.config import FrontendSettings

    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("API_BASE_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "API_TOKEN=local-token\nAPI_BASE_URL=http://localhost:9000\nUNRELATED=value\n",
        encoding="utf-8",
    )
    settings = FrontendSettings(_env_file=env)
    assert settings.api_token == "local-token"
    assert settings.api_base_url == "http://localhost:9000"
