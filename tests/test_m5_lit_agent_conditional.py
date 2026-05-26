"""M5 C2：build_lit_agent 条件性注册 write_file_tool + 条件性 prompt 测试。

owner 决策 A6（条件性 prompt）+ A7（chat 默认不加 profile_update）的代码层验证：
- skills 不含 profile_update → tools = 4 只读件套，prompt 不含 _PROFILE_UPDATE_WRITE_OVERRIDE
- skills 含 profile_update → tools = 4 + write_file_tool，prompt 末尾追加 override 段
"""

from __future__ import annotations

from unittest.mock import patch

from lit_agent.agents.lit_agent import (
    _PROFILE_UPDATE_WRITE_OVERRIDE,
    build_lit_agent,
)


def _extract_tools_and_prompt(skills: tuple[str, ...]) -> tuple[list[str], str]:
    """构造 agent，把它的 tools 名 + system prompt 抽出来便于断言。"""
    # ChatAnthropic 实例化会校验 API key；用 mock 跳过实际 HTTP / 密钥要求
    with patch("lit_agent.agents.lit_agent.ChatAnthropic") as mock_model_cls:
        mock_model_cls.return_value = object()  # create_react_agent 不真调它
        with patch("lit_agent.agents.lit_agent.create_react_agent") as mock_create:
            mock_create.return_value = object()
            build_lit_agent(skills=skills)
            call_kwargs = mock_create.call_args.kwargs
            tools = call_kwargs["tools"]
            prompt = call_kwargs["prompt"]
    tool_names = [t.name for t in tools]
    return tool_names, prompt


def test_default_skills_no_write_tool() -> None:
    """M3/M4 兼容：默认 skills 不含 profile_update → 无写权。"""
    tool_names, prompt = _extract_tools_and_prompt(skills=("daily_search",))
    assert "write_file_tool" not in tool_names
    assert _PROFILE_UPDATE_WRITE_OVERRIDE not in prompt
    # 4 件套只读
    assert set(tool_names) == {
        "search_papers_tool",
        "read_file_tool",
        "search_memory_tool",
        "list_dir_tool",
    }


def test_chat_skills_no_write_tool() -> None:
    """A7 决策：chat 默认 skills 不加 profile_update → 仍无写权。"""
    tool_names, prompt = _extract_tools_and_prompt(
        skills=("daily_search", "memory_recall"),
    )
    assert "write_file_tool" not in tool_names
    assert _PROFILE_UPDATE_WRITE_OVERRIDE not in prompt


def test_profile_update_skill_unlocks_write() -> None:
    """A6 决策：profile_update skill 激活 → write_file_tool 入 tools，prompt 拼 override。"""
    tool_names, prompt = _extract_tools_and_prompt(
        skills=("profile_update",),
    )
    assert "write_file_tool" in tool_names
    assert _PROFILE_UPDATE_WRITE_OVERRIDE in prompt
    # override 段拼在 prompt 末尾
    assert prompt.endswith(_PROFILE_UPDATE_WRITE_OVERRIDE)


def test_profile_update_combined_with_other_skills() -> None:
    """profile_update 跟其他 skill 一起传 → 写权仍解锁。"""
    tool_names, prompt = _extract_tools_and_prompt(
        skills=("daily_search", "profile_update"),
    )
    assert "write_file_tool" in tool_names
    assert _PROFILE_UPDATE_WRITE_OVERRIDE in prompt
