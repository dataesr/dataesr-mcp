"""/match: affiliation matching against a mocked matcher service."""

import json

MATCHER_RESPONSE = {
    "results": ["02feahw73"],
    "enriched_results": [
        {"id": "02feahw73", "name": ["Centre national de la recherche scientifique"], "acronyms": ["CNRS"], "countries": ["fr"]}
    ],
}


def test_lists_the_matcher_tool(connect):
    assert connect("/match").tool_names() == ["get_affiliation_match"]


def test_matches_an_affiliation_against_ror(connect, upstream):
    matcher = upstream.post("https://matcher.test/match").respond(json=MATCHER_RESPONSE)
    result = connect("/match").call("get_affiliation_match", {"affiliation": "CNRS, Paris", "reference": "ror"}).data
    assert result["results"] == ["02feahw73"]
    assert result["enriched_results"][0]["acronyms"] == ["CNRS"]
    assert json.loads(matcher.calls.last.request.content) == {"query": "CNRS, Paris", "type": "ror"}


def test_reference_defaults_to_ror(connect, upstream):
    matcher = upstream.post("https://matcher.test/match").respond(json=MATCHER_RESPONSE)
    connect("/match").call("get_affiliation_match", {"affiliation": "CNRS"})
    assert json.loads(matcher.calls.last.request.content)["type"] == "ror"


def test_unknown_reference_is_rejected(connect, upstream):
    matcher = upstream.post("https://matcher.test/match").respond(json=MATCHER_RESPONSE)
    result = connect("/match").call("get_affiliation_match", {"affiliation": "CNRS", "reference": "orcid"})
    assert result.is_error
    assert not matcher.called


def test_matcher_failure_is_reported_as_a_tool_error(connect, upstream):
    upstream.post("https://matcher.test/match").respond(500)
    assert connect("/match").call("get_affiliation_match", {"affiliation": "CNRS"}).is_error
