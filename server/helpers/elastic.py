import os
import httpx
from functools import lru_cache
from mcp.server.fastmcp.exceptions import FastMCPError

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


async def es_search(index: str, query: dict) -> dict:
    """
    Execute an Elasticsearch query against an index.
    """
    es_index = es_index_clean(index)
    url = f"{ES_URL}/{es_index}/_search"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=es_headers(), json=query, timeout=30)
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
            raise FastMCPError(
                {
                    "error": error_type,
                    "message": reason,
                    "hint": hint,
                }
            )
        return response.json()


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


def es_validate_fields(es_query: dict, index: str, raise_error: bool = False) -> list[str]:
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


def es_validate_size(es_query: dict, index: str, raise_error: bool = False) -> None:
    """
    Validate that the size parameter in the query is less than or equal to ES_MAX_SIZE.
    """
    if "size" in es_query and es_query["size"] > ES_MAX_SIZE:
        raise FastMCPError(
            {
                "error": "invalid_query",
                "message": f"The size parameter must be less than or equal to {ES_MAX_SIZE}. For more results, consider using aggregations instead.",
            }
        )


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
