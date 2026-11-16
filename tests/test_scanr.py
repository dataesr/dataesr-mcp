"""/scanr: schema discovery, entity resolution, searches and aggregations against a mocked Elasticsearch."""

import json

import pytest

from tools.scanr import schema
from tools.scanr.search import MAX_RESPONSE_CHARS
from tools.scanr.registry import INDEXES

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
    cross_index: scanr_projects.title.default
    ai_suggestion:
      notes: Use the title for free-text matching.
      examples: [Climate change]
  year:
    type: integer
    primary: true
    description: Publication year
  authors.name:
    type: keyword
    description: Author name
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
        "scanr_list_indexes",
        "scanr_get_schema",
        "scanr_describe_field",
        "scanr_resolve",
        "scanr_index_search",
        "scanr_query",
        "scanr_field_values",
    }


def test_list_indexes_includes_primary_fields_and_counts(connect, upstream):
    for spec in INDEXES.values():
        upstream.get(f"https://schemas.test/{spec.es_index}.yaml").respond(text=SCHEMA_YAML)
        upstream.post(f"https://es.test/{spec.es_index}/_search").respond(
            json={"hits": {"total": {"value": 42}, "hits": []}}
        )
    result = connect("/scanr").call("scanr_list_indexes", {}).data
    assert len(result["indexes"]) == len(INDEXES)
    publication = next(item for item in result["indexes"] if item["index"] == "scanr_publications")
    assert publication["doc_count"] == 42
    assert "title.default" in publication["primary_fields"]


def test_get_schema_hides_excluded_fields_and_gives_aggregation_paths(connect, es):
    result = connect("/scanr").call("scanr_get_schema", {"index": "scanr_publications"}).data
    fields = result["fields"]
    assert "internal_hash" not in fields
    assert fields["title.default"]["aggregation_field"] == "title.default.keyword"
    assert fields["year"] == {
        "type": "integer",
        "aggregation_field": "year",
        "description": "Publication year",
    }


def test_get_schema_secondary_filter_excludes_primary_fields(connect, es):
    result = connect("/scanr").call("scanr_get_schema", {"index": "scanr_publications", "schema_filter": "secondary"}).data
    assert set(result["fields"]) == {"authors.name"}


def test_get_schema_can_search_prefix_and_paginate(connect, es):
    first = connect("/scanr").call(
        "scanr_get_schema",
        {"index": "scanr_publications", "schema_filter": "all", "search": "author", "prefix": "authors.*", "limit": 1},
    ).data
    assert list(first["fields"]) == ["authors.name"]
    assert first["fields"]["authors.name"]["description"] == "Author name"
    second = connect("/scanr").call(
        "scanr_get_schema",
        {"index": "scanr_publications", "schema_filter": "all", "prefix": "authors.*", "limit": 1, "offset": 1},
    ).data
    assert second["fields"] == {}


def test_describe_field_returns_full_metadata_and_suggests_unknown(connect, es):
    described = connect("/scanr").call("scanr_describe_field", {"index": "scanr_publications", "field": "title.default"}).data
    assert described["description"] == "Publication title"
    assert described["aggregation_field"] == "title.default.keyword"
    assert described["notes"] == "Use the title for free-text matching."
    assert described["cross_index"] == "scanr_projects.title.default"
    assert described["examples"] == ["Climate change"]
    missing = connect("/scanr").call("scanr_describe_field", {"index": "scanr_publications", "field": "titel.default"})
    assert missing.is_error
    assert "title.default" in missing.text


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


def test_field_values_contains_and_prefix_are_applied_to_buckets(connect, es):
    connect("/scanr").call(
        "scanr_field_values",
        {"index": "scanr_publications", "values_field": "title.default", "contains": "a.b"},
    )
    assert sent_body(es)["aggs"]["values"]["terms"]["include"] == ".*a\\.b.*"


def test_field_values_supports_numeric_stats(connect, es):
    es.respond(json={"aggregations": {"stats": {"count": 2, "min": 2023, "max": 2024, "avg": 2023.5, "sum": 4047}}})
    result = connect("/scanr").call(
        "scanr_field_values",
        {"index": "scanr_publications", "values_field": "year", "mode": "stats"},
    ).data
    assert result["stats"]["avg"] == 2023.5
    assert sent_body(es)["aggs"]["stats"]["stats"]["field"] == "year"


def test_query_builds_text_exact_range_sort_and_cursor(connect, es):
    query = {
        "index": "scanr_publications",
        "text": "climate",
        "filters": {"title.default": ["climate change"], "year": {"gte": 2020}},
        "fields": ["id", "year"],
        "sort": {"year": "desc"},
        "cursor": [2024],
        "limit": 5,
    }
    connect("/scanr").call("scanr_query", query)
    body = sent_body(es)
    assert body["query"]["bool"]["must"][0]["multi_match"]["query"] == "climate"
    assert body["query"]["bool"]["filter"] == [
        {"terms": {"title.default.keyword": ["climate change"]}},
        {"range": {"year": {"gte": 2020}}},
    ]
    assert body["sort"] == [{"year": {"order": "desc"}}]
    assert body["search_after"] == [2024]
    assert body["_source"] == ["id", "year"]


def test_query_returns_search_after_cursor(connect, es):
    es.respond(
        json={
            "hits": {
                "total": {"value": 2},
                "hits": [{"_id": "p1", "_source": {"id": "p1"}, "sort": [2024]}],
            }
        }
    )
    result = connect("/scanr").call(
        "scanr_query",
        {"index": "scanr_publications", "sort": {"year": "desc"}, "limit": 1},
    ).data
    assert result["next_cursor"] == [2024]


def test_large_aggregations_are_truncated_to_the_response_budget(connect, es):
    es.respond(
        json={
            "hits": {"total": {"value": 0}, "hits": []},
            "aggregations": {"values": {"buckets": [{"key": "x" * 1000, "doc_count": 1} for _ in range(300)]}},
        }
    )
    result = connect("/scanr").call(
        "scanr_index_search",
        {"index": "scanr_publications", "search_query": {"size": 0, "query": {"match_all": {}}}},
    ).data
    assert result["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False)) <= MAX_RESPONSE_CHARS


def test_large_field_values_are_truncated_to_the_response_budget(connect, es):
    es.respond(
        json={
            "aggregations": {
                "values": {
                    "buckets": [{"key": "x" * 1000, "doc_count": 1} for _ in range(300)],
                    "sum_other_doc_count": 0,
                }
            }
        }
    )
    result = connect("/scanr").call(
        "scanr_field_values",
        {"index": "scanr_publications", "values_field": "title.default"},
    ).data
    assert result["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False)) <= MAX_RESPONSE_CHARS


def test_query_rejects_cursor_without_sort(connect, es):
    result = connect("/scanr").call(
        "scanr_query",
        {"index": "scanr_publications", "cursor": [2024]},
    )
    assert result.is_error
    assert "sort" in result.text
    assert not es.called


def test_query_builds_grouped_metric_aggregation(connect, es):
    connect("/scanr").call(
        "scanr_query",
        {
            "index": "scanr_publications",
            "filters": {"year": {"gte": 2020}},
            "aggregate": {"group_by": "year", "metric": {"type": "avg", "field": "year"}},
        },
    )
    body = sent_body(es)
    assert body["size"] == 0
    assert body["aggs"]["group_by"]["terms"]["field"] == "year"
    assert body["aggs"]["group_by"]["aggs"]["metric"]["avg"]["field"] == "year"


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
