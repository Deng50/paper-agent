"""文件记忆工具测试（M2）：路径白名单安全 + grep 命中 + 原子写。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lit_agent.core.config import Settings
from lit_agent.tools import memory
from lit_agent.tools.memory import PathNotAllowed, PathNotWhitelistedError


def _settings(tmp_path: Path) -> Settings:
    mem = tmp_path / "memory"
    skills = tmp_path / "skills"
    mem.mkdir()
    skills.mkdir()
    return Settings(memory_dir=mem, skills_dir=skills)  # type: ignore[call-arg]


def test_write_profile_then_read(tmp_path: Path) -> None:
    """M5 P1 ⑤：agent 写白名单仅 profile.md。"""
    s = _settings(tmp_path)
    target = s.memory_dir / "profile" / "profile.md"
    target.parent.mkdir(parents=True)
    memory.write_file(target, "hello", settings=s)
    assert memory.read_file(target, settings=s) == "hello"


def test_write_outside_memory_rejected(tmp_path: Path) -> None:
    """越 memory 根 → PathNotAllowed（第 1 层 _resolve 兜底）。"""
    s = _settings(tmp_path)
    with pytest.raises(PathNotAllowed):
        memory.write_file(tmp_path / "evil.txt", "x", settings=s)
    # skills 只读：写入应被拒
    with pytest.raises(PathNotAllowed):
        memory.write_file(s.skills_dir / "x.md", "x", settings=s)


def test_write_inside_memory_but_not_profile_rejected(tmp_path: Path) -> None:
    """M5 P1 ⑤：memory 根内但非 profile.md → PathNotWhitelistedError。"""
    s = _settings(tmp_path)
    # papers 目录内的任何路径 / profile/ 下非 profile.md / 任意其他文件都该拒
    bad_paths = [
        s.memory_dir / "papers" / "2026-05-22" / "arxiv-1.md",
        s.memory_dir / "profile" / "other.md",
        s.memory_dir / "feedback" / "2026-05-26.log",
        s.memory_dir / "rogue.txt",
    ]
    for p in bad_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        with pytest.raises(PathNotWhitelistedError):
            memory.write_file(p, "x", settings=s)
    # 子类校验：PathNotWhitelistedError 继承自 PathNotAllowed，旧 except 仍 catch
    with pytest.raises(PathNotAllowed):
        memory.write_file(s.memory_dir / "feedback" / "x.log", "x", settings=s)


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


@pytest.mark.parametrize("scope", ["..", "../skills", "/", "papers/../../"])
def test_search_rejects_scope_traversal(tmp_path: Path, scope: str) -> None:
    s = _settings(tmp_path)
    (tmp_path / "secret.md").write_text("private key", encoding="utf-8")
    with pytest.raises(PathNotAllowed):
        memory.search_memory("private", scope=scope, settings=s)  # type: ignore[arg-type]


def test_search_feedback_logs_and_zero_limit(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    logs = s.memory_dir / "feedback"
    logs.mkdir()
    (logs / "2026-10-03.log").write_text("up | arxiv-123 | +1", encoding="utf-8")
    assert len(memory.search_memory("arxiv-123", scope="feedback", settings=s)) == 1
    assert len(memory.search_memory("arxiv-123", scope="all", settings=s)) == 1
    assert memory.search_memory("arxiv-123", scope="all", limit=0, settings=s) == []


def test_search_skips_symlink_outside_root(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    secret = tmp_path / "secret.md"
    secret.write_text("private key", encoding="utf-8")
    papers = s.memory_dir / "papers"
    papers.mkdir()
    try:
        (papers / "link.md").symlink_to(secret)
    except OSError:
        pytest.skip("创建 symlink 需要 Windows 开发者模式")
    assert memory.search_memory("private", settings=s) == []
