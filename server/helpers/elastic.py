import os
import copy
import difflib
from mcp.server.fastmcp.exceptions import FastMCPError
from helpers.http import request
from helpers.logger import get_logger

logger = get_logger(__name__)

ES_URL = os.environ.get("ES_URL")
ES_API_KEY = os.environ.get("ES_API_KEY")
ES_REQUEST_TIMEOUT = 15
ES_QUERY_TIMEOUT = "10s"
ES_MAX_SIZE = 20
ES_MAX_FROM_PLUS_SIZE = 1000
ES_MAX_AGG_SIZE = 100
ES_MAX_AGG_DEPTH = 3
ES_ALLOWED_KEYS = {
    "query", "size", "from", "_source", "sort", "search_after",
    "aggs", "aggregations", "track_total_hits",
}
ES_BANNED_KEYS = {"runtime_mappings", "scroll", "pit"}
ES_BANNED_PREFIXES = ("script",)
ES_TERMS_AGGS = ("terms", "significant_terms", "multi_terms")
ES_FIELD_CLAUSES = {
    "term",
    "terms",
    "match",
    "match_phrase",
    "match_bool_prefix",
    "range",
    "prefix",
    "wildcard",
    "regexp",
    "fuzzy",
    "exists",
}
ES_CLAUSE_OPTIONS = {"field", "boost", "_name"}

ES_ERROR_HINTS = {
    "parsing_exception": "The query syntax is invalid. Check the query structure.",
    "illegal_argument_exception": "A field type mismatch — check field types with get_schema (e.g. using term on a text field).",
    "query_shard_exception": "A field type mismatch or bad query clause. Check field types with get_schema.",
    "action_request_validation_exception": "Missing or invalid parameter in the query body.",
}


def es_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if ES_API_KEY:
        headers["Authorization"] = ES_API_KEY
    return headers


async def es_search(es_index: str, query_body: dict, known_fields: set[str] | None = None) -> tuple[dict, dict]:
    """
    Run a guarded search on an Elasticsearch index.
    Returns the response and the limits that were clamped to run the query.
    """

    body, clamps = es_guard(query_body, known_fields)
    body["timeout"] = ES_QUERY_TIMEOUT
    url = f"{ES_URL}/{es_index}/_search"
    response = await request(
        "POST", url, service="elasticsearch", headers=es_headers(), json=body, timeout=ES_REQUEST_TIMEOUT
    )
    if not response.is_success:
        try:
            error = response.json().get("error", {})
            error_type = error.get("type", f"http_{response.status_code}")
            reason = error.get("root_cause", [{}])[0].get("reason") or error.get("reason") or response.text
        except Exception:
            error_type = f"http_{response.status_code}"
            reason = response.text
        hint = ES_ERROR_HINTS.get(error_type, "Fix the query and try again.")
        logger.error(f"Invalid query: {error_type}\n Reason: {reason}\n Hint: {hint}")
        raise FastMCPError({"error": error_type, "message": reason, "hint": hint})
    return response.json(), clamps


def es_guard(query_body: dict, known_fields: set[str] | None = None) -> tuple[dict, dict]:
    """
    Reject unsafe or unsupported request bodies, clamp limits, and check field names when the schema is known.
    Returns the body to send and the clamped limits.
    """

    unknown_keys = sorted(set(query_body) - ES_ALLOWED_KEYS)
    if unknown_keys:
        raise _rejected(
            "unsupported_key",
            f"Unsupported top-level keys: {unknown_keys}.",
            f"Only these keys are allowed: {sorted(ES_ALLOWED_KEYS)}.",
        )
    if "search_after" in query_body:
        if not isinstance(query_body["search_after"], list) or not query_body["search_after"]:
            raise _rejected(
                "invalid_cursor",
                "search_after must be a non-empty list of sort values.",
                "Use the next_cursor returned by a previous search with the same sort.",
            )
        if not query_body.get("sort"):
            raise _rejected(
                "invalid_cursor",
                "search_after requires sort.",
                "Add a stable sort and use the next_cursor returned by a previous search.",
            )
    banned = _banned_keys(query_body)
    if banned:
        raise _rejected(
            "banned_key",
            f"Unsupported keys: {sorted(set(banned))}.",
            "Scripts, runtime mappings, scroll and point-in-time are not available. Use filters and aggregations instead.",
        )

    clamps: dict = {}
    body = es_fix_query(query_body, clamps)

    from_size = body.get("from", 0) + body.get("size", 10)
    if from_size > ES_MAX_FROM_PLUS_SIZE:
        raise _rejected(
            "deep_paging",
            f"from + size = {from_size} exceeds the limit of {ES_MAX_FROM_PLUS_SIZE}.",
            "Narrow the query with filters instead of paging deeper.",
        )
    depth = _agg_depth(body.get("aggs") or body.get("aggregations") or {})
    if depth > ES_MAX_AGG_DEPTH:
        raise _rejected(
            "aggregation_too_deep",
            f"Aggregations are nested {depth} levels deep; the limit is {ES_MAX_AGG_DEPTH}.",
            "Flatten the aggregation or aggregate in several requests.",
        )
    if known_fields is not None:
        es_validate_fields(body, known_fields)
    return body, clamps


def _rejected(error: str, message: str, hint: str) -> FastMCPError:
    return FastMCPError({"error": error, "message": message, "hint": hint})


def _banned_keys(obj) -> list[str]:
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ES_BANNED_KEYS or key.startswith(ES_BANNED_PREFIXES):
                found.append(key)
            found.extend(_banned_keys(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_banned_keys(item))
    return found


def _agg_depth(aggs) -> int:
    if not isinstance(aggs, dict):
        return 0
    return max(
        (1 + _agg_depth(agg.get("aggs") or agg.get("aggregations")) for agg in aggs.values() if isinstance(agg, dict)),
        default=0,
    )


def es_fix_query(query_body: dict, clamps: dict | None = None) -> dict:
    """
    Auto-fix common LLM query mistakes before sending to ES.
    Clamped limits are recorded in clamps when it is given. The input is not modified.
    """

    query = copy.deepcopy(query_body)
    report = clamps if clamps is not None else {}

    # size nested inside aggs, move it to root
    if "aggs" in query and "size" in query.get("aggs", {}):
        query["size"] = query["aggs"].pop("size")

    # size limited to ES_MAX_SIZE
    if "size" in query and query["size"] > ES_MAX_SIZE:
        logger.warning(f"Query size {query['size']} > {ES_MAX_SIZE}, setting to {ES_MAX_SIZE}")
        report["size_capped_from"] = query["size"]
        query["size"] = ES_MAX_SIZE

    _cap_agg_sizes(query.get("aggs") or query.get("aggregations"), report)

    # must with only term/range/bool clauses → move to filter
    if "query" in query and "bool" in query["query"]:
        bool_clause = query["query"]["bool"]
        if "must" in bool_clause:
            non_text = []
            text = []
            for clause in bool_clause["must"]:
                if any(k in clause for k in ("term", "terms", "range", "exists")):
                    non_text.append(clause)
                else:
                    text.append(clause)
            if non_text:
                bool_clause.setdefault("filter", []).extend(non_text)
                if text:
                    bool_clause["must"] = text
                else:
                    del bool_clause["must"]

    # remove empty must/should/filter arrays from bool clauses
    if "query" in query and "bool" in query["query"]:
        bool_clause = query["query"]["bool"]
        for key in ("must", "should", "filter", "must_not"):
            if key in bool_clause and bool_clause[key] == []:
                del bool_clause[key]

    # remove _source when size is 0 (aggregation-only query)
    if query.get("size") == 0 and "_source" in query:
        del query["_source"]

    return query


def _cap_agg_sizes(aggs, report: dict) -> None:
    if not isinstance(aggs, dict):
        return
    for name, agg in aggs.items():
        if not isinstance(agg, dict):
            continue
        for kind in ES_TERMS_AGGS:
            spec = agg.get(kind)
            if isinstance(spec, dict) and isinstance(spec.get("size"), int) and spec["size"] > ES_MAX_AGG_SIZE:
                report.setdefault("agg_size_capped_from", {})[name] = spec["size"]
                spec["size"] = ES_MAX_AGG_SIZE
        _cap_agg_sizes(agg.get("aggs") or agg.get("aggregations"), report)


def es_validate_fields(query_body: dict, known_fields: set[str]) -> None:
    """Reject field names that are not in the index schema, with the closest valid names as suggestions."""
    allowed = set(known_fields)
    for field in known_fields:
        parts = field.split(".")
        allowed.update(".".join(parts[:i]) for i in range(1, len(parts)))

    unknown = sorted(f for f in _query_fields(query_body) if f not in allowed)
    if unknown:
        candidates = sorted(known_fields)
        raise FastMCPError(
            {
                "error": "unknown_field",
                "message": f"Unknown field(s): {unknown}.",
                "did_you_mean": {field: difflib.get_close_matches(field, candidates, n=3, cutoff=0.6) for field in unknown},
                "hint": "Use only fields returned by scanr_get_schema, and retry with the suggested names where they fit.",
            }
        )


def _query_fields(obj) -> set[str]:
    """Collect the field names a query body reads: clause fields, sort, _source, field lists and aggregation fields."""
    found: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ES_FIELD_CLAUSES and isinstance(value, dict):
                names = [value["field"]] if isinstance(value.get("field"), str) else value.keys()
                found.update(_normalize_field(n) for n in names if n not in ES_CLAUSE_OPTIONS)
            elif key == "field" and isinstance(value, str):
                found.add(_normalize_field(value))
            elif key == "fields" and isinstance(value, list):
                found.update(_normalize_field(f) for f in value if isinstance(f, str))
            elif key == "_source":
                if isinstance(value, list):
                    found.update(_normalize_field(f) for f in value if isinstance(f, str))
                elif isinstance(value, dict):
                    for sub in ("includes", "excludes"):
                        found.update(_normalize_field(f) for f in value.get(sub, []) if isinstance(f, str))
            elif key == "sort" and isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        found.add(_normalize_field(item))
                    elif isinstance(item, dict):
                        found.update(_normalize_field(k) for k in item)
            else:
                found.update(_query_fields(value))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_query_fields(item))
    return {f for f in found if f}


def _normalize_field(name: str) -> str:
    """Map a query field reference to the schema field name ("" for meta fields and wildcards)."""
    name = name.split("^")[0].removesuffix(".*").removesuffix(".keyword")
    if not name or name.startswith("_") or "*" in name:
        return ""
    return name
