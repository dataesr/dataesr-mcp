"""/rag: flash_rag against a mocked catalogue API."""

from urllib.parse import parse_qs

RAG_RESPONSE = {
    "sources": [
        {
            "distance": 0.12,
            "document": "En 2023, la DIRD s'élève à 60 milliards d'euros.",
            "metadata": {
                "title": "L'état de l'Enseignement supérieur, de la Recherche et de l'Innovation",
                "publication_date": "2024-06-01",
                "file_url": "https://example.org/eesri.pdf",
                "internal_field": "not exposed",
            },
        }
    ]
}


def test_lists_the_rag_tool(connect):
    assert connect("/rag").tool_names() == ["flash_rag"]


def test_returns_sources_with_selected_metadata(connect, upstream):
    catalogue = upstream.get("https://catalogue.test/api/rag").respond(json=RAG_RESPONSE)
    result = connect("/rag").call("flash_rag", {"query": "dépense de R&D", "top_k": 3}).data
    assert result[0]["distance"] == 0.12
    assert result[0]["metadata"]["publication_date"] == "2024-06-01"
    assert "internal_field" not in result[0]["metadata"]

    request = catalogue.calls.last.request
    assert request.headers["authorization"] == "catalogue-key"
    assert parse_qs(request.url.query.decode()) == {"q": ["dépense de R&D"], "topK": ["3"], "useRerank": ["true"], "useHybrid": ["true"]}


def test_hybrid_search_and_reranking_can_be_disabled(connect, upstream):
    catalogue = upstream.get("https://catalogue.test/api/rag").respond(json={"sources": []})
    connect("/rag").call("flash_rag", {"query": "x", "use_hybrid_search": False, "use_reranker": False})
    query = parse_qs(catalogue.calls.last.request.url.query.decode())
    assert "useRerank" not in query
    assert "useHybrid" not in query


def test_catalogue_failure_is_reported_as_a_tool_error(connect, upstream):
    upstream.get("https://catalogue.test/api/rag").respond(502)
    assert connect("/rag").call("flash_rag", {"query": "x"}).is_error
