import os
import httpx
import copy
from functools import lru_cache
from mcp.server.fastmcp.exceptions import FastMCPError
from helpers.logger import get_logger

logger = get_logger(__name__)

ES_URL = os.environ.get("ES_URL")
ES_API_KEY = os.environ.get("ES_API_KEY")
ES_MAX_SIZE = 20

ES_FIELDS_SKIP = ["normalize", "autocomplete", "encode"]

ES_ERROR_HINTS = {
    "parsing_exception": "The query syntax is invalid. Check the query structure.",
    "illegal_argument_exception": "A field type mismatch — check field types with get_schema (e.g. using term on a text field).",
    "query_shard_exception": "A field type mismatch or bad query clause. Check field types with get_schema.",
    "action_request_validation_exception": "Missing or invalid parameter in the query body.",
}


def es_index_clean(index: str) -> str:
    return index.replace("_", "-")


def es_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if ES_API_KEY:
        headers["Authorization"] = ES_API_KEY
    return headers


async def es_search(index: str, query_body: dict, validate: bool = True) -> dict:
    """
    Execute an Elasticsearch query against an index.
    """
    es_index = es_index_clean(index)
    url = f"{ES_URL}/{es_index}/_search"
    fixed_body = es_fix_and_validate(index, query_body) if validate else query_body
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=es_headers(), json=fixed_body, timeout=30)
        if not response.is_success:
            try:
                body = response.json()
                error_type = body.get("error", {}).get("type", f"http_{response.status_code}")
                reason = (
                    body.get("error", {}).get("root_cause", [{}])[0].get("reason")
                    or body.get("error", {}).get("reason")
                    or response.text
                )
            except Exception:
                error_type = f"http_{response.status_code}"
                reason = response.text
            hint = ES_ERROR_HINTS.get(error_type, "Fix the query and try again.")
            logger.error(f"Invalid query: {error_type}\n Reason: {reason}\n Hint: {hint}")
            raise FastMCPError(
                {
                    "error": error_type,
                    "message": reason,
                    "hint": hint,
                }
            )
        return response.json()


def es_fix_and_validate(index: str, query_body: dict) -> dict:
    """
    Fix and validate an Elasticsearch query.
    """
    logger.debug(f"Original query: {query_body}")
    fixed_body = es_fix_query(query_body)
    logger.debug(f"Fixed query: {fixed_body}")
    validated = es_validate_query(index, fixed_body.get("query", {}))
    if not validated.get("valid", False):
        explanations = [e.get("explanation", "") for e in validated.get("explanations", [])]
        logger.error(f"Invalid query: {explanations}")
        raise FastMCPError(
            {
                "error": "invalid_query",
                "reason": "; ".join(explanations),
                "hint": "Fix the query and try again.",
            }
        )
    return fixed_body


def es_validate_query(index: str, query: dict, raise_error: bool = False) -> dict:
    """Hit ES _validate/query to check syntax before executing."""
    if not query:
        return {"valid": False, "explanations": [{"explanation": "Query is empty"}]}

    es_index = es_index_clean(index)
    url = f"{ES_URL}/{es_index}/_validate/query?explain=true"
    body = {"query": query}
    logger.debug(f"Validating query: {body}")
    with httpx.Client() as client:
        response = client.post(url, headers=es_headers(), json=body, timeout=30)
        return response.json()


def es_fix_query(query_body: dict) -> dict:
    """
    Auto-fix common LLM query mistakes before sending to ES.
    Modifies the query in-place and returns it.
    """
    query = copy.deepcopy(query_body)

    # size nested inside aggs, move it to root
    if "aggs" in query and "size" in query.get("aggs", {}):
        query["size"] = query["aggs"].pop("size")

    # size limited to ES_MAX_SIZE
    if "size" in query and query["size"] > ES_MAX_SIZE:
        logger.warning(f"Query size {query['size']} > {ES_MAX_SIZE}, setting to {ES_MAX_SIZE}")
        query["size"] = ES_MAX_SIZE

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


def es_get_mapping(index: str) -> dict:
    """
    Get the mapping for an index.
    """
    es_index = es_index_clean(index)
    url = f"{ES_URL}/{es_index}/_mapping"
    with httpx.Client() as client:
        response = client.get(url, headers=es_headers(), timeout=30)
        response.raise_for_status()
        return response.json()


@lru_cache(maxsize=50)
def es_get_flat_mapping(index: str) -> dict:
    """
    Get the flat mapping for an index.
    """
    raw_mapping = es_get_mapping(index)
    actual_index = list(raw_mapping.keys())[0]
    properties = raw_mapping[actual_index]["mappings"].get("properties", {})
    return _flatten_mapping(properties)


def es_validate_fields(index: str, es_query: dict, raise_error: bool = False) -> list[str]:
    """
    Validate that the fields in the query exist in the index mapping.
    Returns a list of invalid fields.
    """
    mapping = es_get_flat_mapping(index)
    used = _extract_fields_from_query(es_query)

    META_FIELDS = {"_score", "_id", "_source", "_index", "_type"}

    invalid_fields = []
    for field in used:
        if field in META_FIELDS:
            continue
        base = field.removesuffix(".keyword")
        if base not in mapping:
            invalid_fields.append(field)

    if raise_error and invalid_fields:
        raise FastMCPError(
            {
                "error": "invalid_fields",
                "message": f"The following fields do not exist in {index}: {invalid_fields}. You MUST call {index}_get_schema to get the list of valid fields, then retry the query using only existing fields.",
                "invalid_fields": invalid_fields,
            }
        )
    return invalid_fields


def _flatten_mapping(properties: dict, prefix: str = "") -> dict:
    """Recursively flatten nested ES properties into dot-notation field paths."""
    fields = {}
    for field_name, field_def in properties.items():
        full_path = f"{prefix}.{field_name}" if prefix else field_name
        if any(skip in full_path for skip in ES_FIELDS_SKIP):
            continue
        if field_def.get("type"):
            entry = {"type": field_def["type"]}
            if "keyword" in field_def.get("fields", {}):
                entry["keyword"] = True
            fields[full_path] = entry
        if "properties" in field_def:
            fields.update(_flatten_mapping(field_def["properties"], full_path))
    return fields


def _extract_fields_from_query(obj) -> set[str]:
    """
    Recursively walk the ES query dict and extract any field names used.
    Handles: match, term, terms, range, multi_match, _source, sort, aggs, etc.
    """
    found = set()

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("term", "terms", "match", "range", "prefix", "wildcard", "exists", "fuzzy", "regexp"):
                if isinstance(value, dict):
                    if "field" in value:
                        found.add(value["field"])
                    else:
                        found.update(value.keys())
            elif key == "fields" and isinstance(value, list):
                found.update(f.split("^")[0].replace(".*", "") for f in value)
            elif key == "_source":
                if isinstance(value, list):
                    found.update(f.split("^")[0].replace(".*", "") for f in value)
                elif isinstance(value, dict):
                    for sub in ("includes", "excludes"):
                        if isinstance(value.get(sub), list):
                            found.update(v.split("^")[0].replace(".*", "") for v in value[sub])
            elif key == "sort" and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        found.update(item.keys())
            else:
                found.update(_extract_fields_from_query(value))

    elif isinstance(obj, list):
        for item in obj:
            found.update(_extract_fields_from_query(item))

    return found
