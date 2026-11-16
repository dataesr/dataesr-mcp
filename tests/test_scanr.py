"""/scanr: schema discovery, entity resolution, searches and aggregations against a mocked Elasticsearch."""

import json

import pytest

from tools.scanr import schema

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
    return upstream.post("https://es.test/scanr-publications/_search").respond(json=SEARCH_RESPONSE)


def sent_body(route) -> dict:
    return json.loads(route.calls.last.request.content)


def test_lists_the_scanr_tools(connect):
    assert set(connect("/scanr").tool_names()) == {
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
    result = connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": query}).data
    assert sent_body(es)["size"] == 20
    assert result["clamped"]["size_capped_from"] == 500


def test_index_search_defaults_source_to_primary_fields(connect, es):
    connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": {"query": {"match_all": {}}}})
    assert sent_body(es)["_source"] == ["id", "title.default", "year"]


def test_deep_paging_is_rejected_before_searching(connect, es):
    query = {"query": {"match_all": {}}, "from": 1000, "size": 20}
    result = connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": query})
    assert result.is_error
    assert not es.called


def test_scripts_are_rejected_before_searching(connect, es):
    query = {"query": {"match_all": {}}, "script_fields": {"x": {"script": {"source": "1"}}}}
    result = connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": query})
    assert result.is_error
    assert not es.called


def test_stale_schema_is_served_when_refresh_fails(connect, upstream, monkeypatch):
    monkeypatch.setattr(schema, "SCHEMA_TTL", 0)
    route = upstream.get("https://schemas.test/scanr-publications.yaml").respond(text=SCHEMA_YAML)
    session = connect("/scanr")
    assert not session.call("scanr_get_schema", {"index": "scanr_publications"}).is_error
    route.respond(500)
    result = session.call("scanr_get_schema", {"index": "scanr_publications"})
    assert not result.is_error
    assert "title.default" in result.data["fields"]


def test_field_values_uses_the_schema_aggregation_field(connect, es):
    result = connect("/scanr").call("scanr_field_values", {"index": "scanr_publications", "values_field": "title.default", "values_limit": 5}).data
    assert result["aggregation_field"] == "title.default.keyword"
    assert result["buckets"] == [{"key": 2024, "doc_count": 2}]
    assert sent_body(es)["aggs"]["values"]["terms"] == {"field": "title.default.keyword", "size": 5}


def test_field_values_rejects_a_field_outside_the_schema(connect, es):
    result = connect("/scanr").call("scanr_field_values", {"index": "scanr_publications", "values_field": "internal_hash"})
    assert result.is_error
    assert "not available" in result.text


def test_elasticsearch_error_is_reported_with_a_hint(connect, es):
    es.respond(400, json={"error": {"type": "parsing_exception", "reason": "bad clause"}})
    result = connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": {"query": {"match_all": {}}}})
    assert result.is_error
    assert "parsing_exception" in result.text
    assert "Check the query structure" in result.text


def test_unknown_field_is_rejected_locally_with_a_suggestion(connect, es):
    query = {"query": {"term": {"titel.default": "x"}}}
    result = connect("/scanr").call("scanr_index_search", {"index": "scanr_publications", "search_query": query})
    assert result.is_error
    assert "title.default" in result.text
    assert not es.called


def test_unknown_index_is_rejected(connect, es):
    result = connect("/scanr").call("scanr_get_schema", {"index": "scanr_unknown"})
    assert result.is_error
