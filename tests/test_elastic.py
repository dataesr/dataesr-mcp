"""Query auto-fixes applied before a query is sent to Elasticsearch."""

from helpers.elastic import es_fix_query


def test_size_is_capped():
    assert es_fix_query({"size": 500, "query": {"match_all": {}}})["size"] == 20


def test_size_misplaced_in_aggs_is_moved_to_the_root():
    fixed = es_fix_query({"query": {"match_all": {}}, "aggs": {"size": 0, "by_year": {"terms": {"field": "year"}}}})
    assert fixed["size"] == 0
    assert "size" not in fixed["aggs"]


def test_exact_clauses_in_must_are_moved_to_filter():
    query = {"query": {"bool": {"must": [{"term": {"year": 2024}}, {"match": {"title": "climate"}}]}}}
    bool_clause = es_fix_query(query)["query"]["bool"]
    assert bool_clause["filter"] == [{"term": {"year": 2024}}]
    assert bool_clause["must"] == [{"match": {"title": "climate"}}]


def test_empty_bool_arrays_are_removed():
    query = {"query": {"bool": {"must": [], "filter": [{"term": {"year": 2024}}]}}}
    assert es_fix_query(query)["query"]["bool"] == {"filter": [{"term": {"year": 2024}}]}


def test_source_is_dropped_for_aggregation_only_queries():
    assert "_source" not in es_fix_query({"size": 0, "_source": ["id"], "query": {"match_all": {}}})


def test_the_input_is_not_mutated():
    query = {"size": 500, "query": {"match_all": {}}}
    es_fix_query(query)
    assert query["size"] == 500
