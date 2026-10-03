from pathlib import Path
from types import SimpleNamespace

import pytest
from paper_search_mcp.academic_platforms.citeseerx import CiteSeerXSearcher


def test_citeseerx_download_writes_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    searcher = CiteSeerXSearcher()
    monkeypatch.setattr(
        searcher,
        "get_paper_details",
        lambda _: SimpleNamespace(pdf_url="https://example.org/paper.pdf", doi="10.1234/a"),
    )
    monkeypatch.setattr(
        searcher,
        "_get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            iter_content=lambda **kwargs: iter([b"%PDF-", b"test"]),
        ),
    )
    path = Path(searcher.download_pdf("record", str(tmp_path / "downloads")))
    assert path.parent == tmp_path / "downloads"
    assert path.read_bytes() == b"%PDF-test"
