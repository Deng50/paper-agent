"""SSE decoder independent of Streamlit, preserving UTF-8 across network chunks."""

from __future__ import annotations

import codecs
import json
import re
from collections.abc import Iterator
from typing import Any

_EVENT_END = re.compile(r"\r?\n\r?\n")


def parse_sse_events(byte_stream: Iterator[bytes]) -> Iterator[tuple[str, dict[str, Any]]]:
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    for chunk in byte_stream:
        buffer += decoder.decode(chunk)
        while match := _EVENT_END.search(buffer):
            block, buffer = buffer[: match.start()], buffer[match.end() :]
            event_name = "message"
            data_lines: list[str] = []
            for line in block.splitlines():
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    value = line[5:]
                    data_lines.append(value[1:] if value.startswith(" ") else value)
            if not data_lines:
                continue
            data_raw = "\n".join(data_lines)
            try:
                data = json.loads(data_raw)
            except json.JSONDecodeError:
                data = {"raw": data_raw}
            if isinstance(data, dict):
                yield event_name, data
    decoder.decode(b"", final=True)
