from xml.etree import ElementTree as ET

from paper_search_mcp.academic_platforms.oaipmh import OAIPMHSearcher


def test_oai_namespaced_leaf_elements_preserve_metadata() -> None:
    record = ET.fromstring(
        '<record xmlns="http://www.openarchives.org/OAI/2.0/">'
        '<header><identifier>https://example.org/paper/1</identifier></header>'
        '<metadata><oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:title>Battery research</dc:title><dc:creator>Alice</dc:creator>'
        '<dc:description>Solid state</dc:description><dc:date>2024-02-03</dc:date>'
        '<dc:publisher>Publisher</dc:publisher><dc:language>en</dc:language>'
        '<dc:type>article</dc:type></oai_dc:dc></metadata></record>'
    )
    searcher = OAIPMHSearcher("https://example.org/oai")
    paper = searcher._parse_oai_record(record)
    assert paper is not None
    assert paper.title == "Battery research"
    assert paper.abstract == "Solid state"
    assert paper.url == "https://example.org/paper/1"
    assert paper.to_dict()["published_date"] == "2024-02-03T00:00:00"
    assert paper.extra == {"publisher": "Publisher", "language": "en", "type": "article"}
    assert searcher._matches_query(paper, paper.paper_id)
