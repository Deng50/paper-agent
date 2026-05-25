"""SSE wire format helper（M4 task 1，docs/04 §9）。

native StreamingResponse 路径（Q1 owner 拍）：format_sse_event 序列化标准
`event: <name>\\ndata: <json>\\n\\n`；KEEPALIVE_INTERVAL_S 15s 注释心跳由
chat 路由自己 asyncio.Queue 双 task 调度（不引入 sse-starlette）。
"""

from __future__ import annotations

import json
from typing import Any

KEEPALIVE_INTERVAL_S = 15.0
SSE_KEEPALIVE = ": keepalive\n\n"


def format_sse_event(name: str, data: Any) -> str:
    """SSE wire format: `event: <name>\\ndata: <json>\\n\\n`。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {name}\ndata: {payload}\n\n"
