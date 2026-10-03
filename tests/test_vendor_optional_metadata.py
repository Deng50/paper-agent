"""Offline contracts for optional upstream connectors; no MCP/PDF dependencies."""

from paper_search_mcp.academic_platforms.hal import HALSearcher
from paper_search_mcp.academic_platforms.ssrn import SSRNSearcher
from paper_search_mcp.academic_platforms.zenodo import ZenodoSearcher


def test_hal_metadata_serializes_with_author_names_and_year() -> None:
    paper = HALSearcher()._parse_doc(
        {
            "halId_s": "hal-123",
            "title_s": ["Test"],
            "authFullName_s": ["Alice Example", "Bob Example"],
            "publicationDateY_i": 2024,
        }
    )
    assert paper is not None
    assert paper.to_dict()["authors"] == "Alice Example; Bob Example"
    assert paper.to_dict()["published_date"] == "2024-01-01T00:00:00"


def test_zenodo_metadata_serializes() -> None:
    paper = ZenodoSearcher()._parse_record(
        {
            "id": 123,
            "metadata": {
                "title": "Test",
                "creators": [{"name": "Doe, Jane"}],
                "publication_date": "2024-01-15",
            },
        }
    )
    assert paper is not None
    assert paper.to_dict()["authors"] == "Doe, Jane"
    assert paper.to_dict()["published_date"] == "2024-01-15T00:00:00"


def test_ssrn_metadata_keeps_downloadable_id_and_serializes() -> None:
    papers = SSRNSearcher()._parse_results(
        '<div class="result-item"><h3><a href="/sol3/papers.cfm?abstract_id=123">Test</a>'
        '</h3><div class="authors">Alice Example, Bob Example</div>'
        '<span class="date">2024-01-15</span></div>'
    )
    assert papers[0].paper_id == "ssrn:123"
    assert papers[0].to_dict()["authors"] == "Alice Example; Bob Example"
    assert papers[0].to_dict()["published_date"] == "2024-01-15T00:00:00"


def test_unrecognized_optional_date_does_not_break_serialization() -> None:
    paper = HALSearcher()._parse_doc(
        {"halId_s": "hal-123", "title_s": ["Test"], "submittedDate_s": "unknown"}
    )
    assert paper is not None
    assert paper.to_dict()["published_date"] == ""
