"""文件记忆工具测试（M2）：路径白名单安全 + grep 命中 + 原子写。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lit_agent.core.config import Settings
from lit_agent.tools import memory
from lit_agent.tools.memory import PathNotAllowed


def _settings(tmp_path: Path) -> Settings:
    mem = tmp_path / "memory"
    skills = tmp_path / "skills"
    mem.mkdir()
    skills.mkdir()
    return Settings(memory_dir=mem, skills_dir=skills)  # type: ignore[call-arg]


def test_write_then_read_within_memory(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    target = s.memory_dir / "papers" / "2026-05-22" / "arxiv-1.md"
    memory.write_file(target, "hello", settings=s)
    assert memory.read_file(target, settings=s) == "hello"


def test_write_outside_memory_rejected(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    with pytest.raises(PathNotAllowed):
        memory.write_file(tmp_path / "evil.txt", "x", settings=s)
    # skills 只读：写入应被拒
    with pytest.raises(PathNotAllowed):
        memory.write_file(s.skills_dir / "x.md", "x", settings=s)


def test_path_traversal_blocked(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    with pytest.raises(PathNotAllowed):
        memory.read_file(s.memory_dir / ".." / ".env", settings=s)


def test_skills_readable(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    (s.skills_dir / "daily.md").write_text("skill body", encoding="utf-8")
    assert memory.read_file(s.skills_dir / "daily.md", settings=s) == "skill body"


def test_search_memory_grep_hit_and_scope(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    papers = s.memory_dir / "papers" / "2026-05-22"
    papers.mkdir(parents=True)
    (papers / "arxiv-1.md").write_text(
        "---\ntitle: Sulfide solid electrolyte interface\n---\n## Abstract\nWe study interfaces.",
        encoding="utf-8",
    )
    (papers / "arxiv-2.md").write_text("title: Liquid additive\nunrelated", encoding="utf-8")

    hits = memory.search_memory("sulfide interface", scope="papers", settings=s)
    assert len(hits) == 1
    assert hits[0]["path"].endswith("arxiv-1.md")
    assert hits[0]["snippet"]

    # 不匹配的词组 → 空
    assert memory.search_memory("graphene battery", scope="papers", settings=s) == []
    # 错误 scope 目录不存在 → 空，不报错
    assert memory.search_memory("sulfide", scope="sessions", settings=s) == []
