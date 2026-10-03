import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from lit_agent.api.routes.chat import _last_msg_has_dangling_tool_calls, _produce_events
from lit_agent.frontend.sse import parse_sse_events


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_sse_preserves_split_chinese_and_emoji(line_ending: str) -> None:
    wire = 'event: token\ndata: {"delta":"中文📚"}\n\n: keepalive\n\n'
    encoded = wire.replace("\n", line_ending).encode("utf-8")
    assert list(parse_sse_events(iter(bytes([byte]) for byte in encoded))) == [
        ("token", {"delta": "中文📚"})
    ]


def test_stream_emits_token_before_model_finishes_without_duplicate_text() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        finish = asyncio.Event()

        class Agent:
            async def aget_state(self, config):
                return SimpleNamespace(values={"messages": []})

            async def astream(self, inp, config, stream_mode):
                assert stream_mode == ["messages", "updates"]
                yield (
                    "messages",
                    (AIMessageChunk(content="第一", id="a1"), {"langgraph_node": "agent"}),
                )
                await finish.wait()
                yield (
                    "messages",
                    (AIMessageChunk(content="段", id="a1"), {"langgraph_node": "agent"}),
                )
                yield "updates", {"agent": {"messages": [AIMessage(content="第一段", id="a1")]}}

        task = asyncio.create_task(
            _produce_events(Agent(), {}, HumanMessage(content="hi"), "thread", "trace", queue)
        )
        meta = await asyncio.wait_for(queue.get(), 2)
        first = await asyncio.wait_for(queue.get(), 2)
        assert meta.startswith("event: meta")
        assert "第一" in first
        assert not task.done()
        finish.set()
        await task
        remaining = []
        while (event := queue.get_nowait()) is not None:
            remaining.append(event)
        tokens = [
            json.loads(e.split("data: ", 1)[1])["delta"]
            for e in [first, *remaining]
            if e.startswith("event: token")
        ]
        assert tokens == ["第一", "段"]
        assert remaining[-1].startswith("event: done")

    asyncio.run(scenario())


def test_partial_parallel_tool_results_are_detected() -> None:
    call = AIMessage(
        content="",
        tool_calls=[
            {"name": "read", "args": {}, "id": "one"},
            {"name": "read", "args": {}, "id": "two"},
        ],
    )
    first = ToolMessage(content="ok", tool_call_id="one")
    assert _last_msg_has_dangling_tool_calls([call, first])
    assert not _last_msg_has_dangling_tool_calls(
        [call, first, ToolMessage(content="ok", tool_call_id="two")]
    )
