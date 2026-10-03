import datetime as dt
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from lit_agent.core.config import get_settings
from lit_agent.tools.session_md import derive_session_md, find_existing_by_thread, set_session_title


def test_sessions_created_in_same_minute_remain_independent(tmp_path: Path) -> None:
    settings = get_settings().model_copy(update={"memory_dir": tmp_path})
    now = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.UTC)
    first = derive_session_md("first", [HumanMessage(content="first text")], settings, now)
    second = derive_session_md("second", [HumanMessage(content="second text")], settings, now)
    assert first != second
    assert first == find_existing_by_thread("first", settings)
    assert second == find_existing_by_thread("second", settings)
    assert "first text" in first.read_text(encoding="utf-8")
    assert "second text" in second.read_text(encoding="utf-8")


def test_rerun_replaces_archive_and_keeps_manual_title(tmp_path: Path) -> None:
    settings = get_settings().model_copy(update={"memory_dir": tmp_path})
    old = [HumanMessage(content="old query"), AIMessage(content="old answer")]
    path = derive_session_md("daily_push:2026-10-03", old, settings)
    assert path is not None
    set_session_title("daily_push:2026-10-03", "我的推送", settings)
    new = [AIMessage(content=[{"type": "text", "text": "新的块格式答案"}])]
    assert derive_session_md("daily_push:2026-10-03", new, settings) == path
    text = path.read_text(encoding="utf-8")
    assert "old answer" not in text
    assert "新的块格式答案" in text
    assert "我的推送" in text
    assert derive_session_md("daily_push:2026-10-03", new, settings) is None
