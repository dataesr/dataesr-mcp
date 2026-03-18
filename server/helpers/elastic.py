import os
import httpx
from functools import lru_cache
from mcp.server.fastmcp.exceptions import FastMCPError

ES_URL = os.environ.get("ES_URL")
ES_API_KEY = os.environ.get("ES_API_KEY")


def es_index_clean(index: str) -> str:
    return index.replace("_", "-")


def es_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if ES_API_KEY:
        headers["Authorization"] = ES_API_KEY
    return headers


def es_search(index: str, query: dict) -> dict:
    """
    Execute an Elasticsearch query against an index.
    """
    es_index = es_index_clean(index)
    url = f"{ES_URL}/{es_index}/_search"
    with httpx.Client() as client:
        response = client.post(url, headers=es_headers(), json=query, timeout=30)
        response.raise_for_status()
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


@lru_cache(maxsize=10)
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


def _flatten_mapping(properties: dict, prefix: str = "") -> dict:
    """Recursively flatten nested ES properties into dot-notation field paths."""
    fields = {}
    for field_name, field_def in properties.items():
        full_path = f"{prefix}.{field_name}" if prefix else field_name
        if field_def.get("type"):
            entry = {"type": field_def["type"]}
            if "keyword" in field_def.get("fields", {}):
                entry["keyword"] = True
            fields[full_path] = entry
        if "properties" in field_def:
            fields.update(_flatten_mapping(field_def["properties"], full_path))
    return fields


def _extract_fields_from_query(obj, found=None) -> set[str]:
    """
    Recursively walk the ES query dict and extract any field names used.
    Handles: match, term, terms, range, multi_match, _source, sort, aggs, etc.
    """
    if found is None:
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
            elif key == "_source" and isinstance(value, list):
                found.update(value)
            elif key == "sort" and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        found.update(item.keys())
            else:
                _extract_fields_from_query(value, found)

    elif isinstance(obj, list):
        for item in obj:
            _extract_fields_from_query(item, found)

    return found
