"""/scanr: schema discovery, entity resolution, searches and aggregations against a mocked Elasticsearch."""

import json

import pytest

SCHEMA_YAML = """
_meta:
  description: Scientific publications
fields:
  id:
    type: keyword
    primary: true
  title.default:
    type: text
    has_keyword: true
    primary: true
    description: Publication title
  year:
    type: integer
    primary: true
  internal_hash:
    type: keyword
    exclude: true
resolve:
  search_fields: [title.default]
  source_fields: [id, title.default]
"""

SEARCH_RESPONSE = {
    "hits": {"total": {"value": 2}, "hits": [{"_source": {"id": "doi10.1/a"}}, {"_source": {"id": "doi10.1/b"}}]},
    "aggregations": {"values": {"buckets": [{"key": 2024, "doc_count": 2}], "sum_other_doc_count": 0}},
}


@pytest.fixture
def es(upstream):
    """Mock the schema file and the scanr-publications Elasticsearch index."""
    upstream.get("https://schemas.test/scanr-publications.yaml").respond(text=SCHEMA_YAML)
    upstream.post("https://es.test/scanr-publications/_validate/query").respond(json={"valid": True})
    return upstream.post("https://es.test/scanr-publications/_search").respond(json=SEARCH_RESPONSE)


def sent_body(route) -> dict:
    return json.loads(route.calls.last.request.content)


def test_lists_the_scanr_tools(connect):
    assert set(connect("/scanr").tool_names()) == {
        "scanr_search",
        "scanr_get_schema",
        "scanr_resolve",
        "scanr_index_search",
        "scanr_field_values",
    }


def test_get_schema_hides_excluded_fields_and_gives_aggregation_paths(connect, es):
    result = connect("/scanr").call("scanr_get_schema", {"index": "scanr_publications"}).data
    fields = result["fields"]
    assert "internal_hash" not in fields
    assert fields["title.default"]["aggregation_field"] == "title.default.keyword"
    assert fields["year"] == {"type": "integer", "aggregation_field": "year"}


def test_get_schema_secondary_filter_excludes_primary_fields(connect, es):
    result = connect("/scanr").call("scanr_get_schema", {"index": "scanr_publications", "schema_filter": "secondary"}).data
    assert result["fields"] == {}


def test_resolve_returns_candidates(connect, es):
    es.respond(json={"hits": {"hits": [{"_source": {"id": "p1", "title": {"default": "Open science"}}}]}})
    result = connect("/scanr").call("scanr_resolve", {"index": "scanr_publications", "resolve_query": "open science"}).data
    assert result["candidates"][0]["id"] == "p1"
    assert sent_body(es)["query"]["multi_match"] == {"query": "open science", "fields": ["title.default"]}


def test_index_search_returns_total_and_hits(connect, es):
    query = {"query": {"match": {"title.default": "climate"}}, "_source": ["id"]}
    result = connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": query}).data
    assert result["total"] == 2
    assert [hit["id"] for hit in result["hits"]] == ["doi10.1/a", "doi10.1/b"]
    assert es.calls.last.request.headers["authorization"] == "es-key"


def test_index_search_size_is_capped_at_20(connect, es):
    query = {"query": {"match_all": {}}, "size": 500}
    connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": query})
    assert sent_body(es)["size"] == 20


def test_field_values_uses_the_schema_aggregation_field(connect, es):
    result = connect("/scanr").call("scanr_field_values", {"index": "scanr_publications", "values_field": "title.default", "values_limit": 5}).data
    assert result["aggregation_field"] == "title.default.keyword"
    assert result["buckets"] == [{"key": 2024, "doc_count": 2}]
    assert sent_body(es)["aggs"]["values"]["terms"] == {"field": "title.default.keyword", "size": 5}


def test_field_values_rejects_a_field_outside_the_schema(connect, es):
    result = connect("/scanr").call("scanr_field_values", {"index": "scanr_publications", "values_field": "internal_hash"})
    assert result.is_error
    assert "not available" in result.text


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"operation": "schema"}, "fields"),
        ({"operation": "values", "values_field": "year"}, "buckets"),
        ({"operation": "search", "search_query": {"query": {"match_all": {}}, "size": 0}}, "hits"),
    ],
)
def test_scanr_search_dispatches_on_operation(connect, es, arguments, expected):
    result = connect("/scanr").call("scanr_search", {"index": "scanr_publications", **arguments}).data
    assert expected in result


def test_scanr_search_requires_the_operation_input(connect, es):
    result = connect("/scanr").call("scanr_search", {"index": "scanr_publications", "operation": "search"})
    assert result.is_error
    assert "search_query" in result.text


def test_elasticsearch_error_is_reported_with_a_hint(connect, es):
    es.respond(400, json={"error": {"type": "parsing_exception", "reason": "bad clause"}})
    result = connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": {"query": {"match_all": {}}}})
    assert result.is_error
    assert "parsing_exception" in result.text
    assert "Check the query structure" in result.text


def test_invalid_query_is_rejected_before_searching(connect, es, upstream):
    upstream.post("https://es.test/scanr-publications/_validate/query").respond(
        json={"valid": False, "explanations": [{"explanation": "unknown field"}]}
    )
    result = connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": {"query": {"term": {"nope": 1}}}})
    assert result.is_error
    assert "unknown field" in result.text
    assert not es.called


def test_unknown_index_is_rejected(connect, es):
    result = connect("/scanr").call("scanr_get_schema", {"index": "scanr_unknown"})
    assert result.is_error
