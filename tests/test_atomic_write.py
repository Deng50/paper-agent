from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from lit_agent.tools import paper_md


def test_concurrent_writers_use_independent_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "profile.md"
    barrier = Barrier(2)
    replace = paper_md.os.replace

    def simultaneous_replace(src: Path, dst: Path) -> None:
        barrier.wait(timeout=5)
        replace(src, dst)

    monkeypatch.setattr(paper_md.os, "replace", simultaneous_replace)
    contents = ["甲" * 1000, "乙" * 1000]
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda body: paper_md.atomic_write(target, body), contents))
    assert target.read_text(encoding="utf-8") in contents
    assert list(tmp_path.iterdir()) == [target]


def test_failed_replace_preserves_original_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "profile.md"
    target.write_text("original", encoding="utf-8")

    def fail(*args: object) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr(paper_md.os, "replace", fail)
    with pytest.raises(OSError):
        paper_md.atomic_write(target, "new")
    assert target.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.iterdir()) == [target]
