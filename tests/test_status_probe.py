import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest

from lit_agent.api.routes.system import _check_anthropic


@pytest.mark.parametrize("failed", [False, True])
def test_status_probe_closes_client_without_retrying(
    monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    client = SimpleNamespace(
        models=SimpleNamespace(list=AsyncMock(side_effect=OSError("offline") if failed else None)),
        close=AsyncMock(),
    )
    options = {}

    def fake_client(**kwargs):  # type: ignore[no-untyped-def]
        options.update(kwargs)
        return client

    monkeypatch.setattr(anthropic, "AsyncAnthropic", fake_client)
    result = asyncio.run(_check_anthropic("test-key"))
    assert result.ok is not failed
    assert options["max_retries"] == 0
    client.close.assert_awaited_once()
