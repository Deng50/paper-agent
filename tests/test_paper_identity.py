from pathlib import Path

from lit_agent.tools.paper_md import extract_arxiv_id, load_dedup_index
from lit_agent.tools.schemas import Paper
from lit_agent.tools.search_papers import _dedup_in_batch


def _paper(pid: str, doi: str | None = None, arxiv: str | None = None) -> Paper:
    return Paper(paper_id=pid, external_id=pid, source="arxiv", title=pid, doi=doi, arxiv_id=arxiv)


def test_doi_case_urls_and_arxiv_revisions_do_not_repeat() -> None:
    first = _paper("one", "10.1000/ABC")
    same = _paper("two", "https://doi.org/10.1000/abc", "2605.01234v1")
    alias = _paper("three", arxiv="2605.01234v2")
    assert _dedup_in_batch([first, same, alias]) == [first]
    assert extract_arxiv_id("arxiv", "2605.01234v2", None) == "2605.01234"


def test_legacy_markdown_anchors_are_canonicalized(tmp_path: Path) -> None:
    directory = tmp_path / "papers"
    directory.mkdir()
    (directory / "old.md").write_text(
        '---\ndoi: "https://dx.doi.org/10.1000/ABC"\narxiv_id: "2605.01234v1"\n---\n',
        encoding="utf-8",
    )
    index = load_dedup_index(tmp_path)
    assert index.contains(_paper("new", "doi:10.1000/abc"))
    assert index.contains(_paper("revision", arxiv="2605.01234v3"))
