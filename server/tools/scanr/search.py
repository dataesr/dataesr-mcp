import json
from mcp.server.fastmcp.exceptions import FastMCPError
from helpers.elastic import es_search
from helpers.logger import get_logger
from tools.scanr.registry import get_index
from tools.scanr.schema import index_get_aggregation_field, index_known_fields, index_primary_fields

logger = get_logger(__name__)

MAX_STRING_CHARS = 300
MAX_LIST_ITEMS = 20
MAX_RESPONSE_CHARS = 60_000


def _shape(value, notes: set[str]):
    """Shorten long strings and lists, recording each kind of truncation in notes."""
    if isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            notes.add("strings")
            return value[:MAX_STRING_CHARS] + "…"
        return value
    if isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS:
            notes.add("lists")
        return [_shape(item, notes) for item in value[:MAX_LIST_ITEMS]]
    if isinstance(value, dict):
        return {key: _shape(item, notes) for key, item in value.items()}
    return value


def _finalise(result: dict, notes: set[str]) -> dict:
    """Drop hits until the response fits the size budget, and tell the caller what was cut."""
    hints = []
    if notes:
        hints.append("Long values were shortened. Set _source to the fields you need to see them in full.")
    while len(json.dumps(result, ensure_ascii=False, default=str)) > MAX_RESPONSE_CHARS and result["hits"]:
        result["hits"].pop()
        result["truncated"] = True
    if result.get("truncated"):
        hints.append("The response was cut to fit the size budget. Narrow the query or reduce size.")
    if hints:
        result["truncated"] = True
        result["hint"] = " ".join(hints)
    return result


async def index_field_values(
    index: str,
    field: str,
    limit: int = 20,
    filter_query: dict | None = None,
) -> dict:
    """Return the most frequent terms for a schema-declared aggregatable field."""
    if not 1 <= limit <= 100:
        raise FastMCPError("limit must be between 1 and 100.")

    aggregation_field = await index_get_aggregation_field(index, field)
    body = {
        "size": 0,
        "query": filter_query or {"match_all": {}},
        "aggs": {
            "values": {
                "terms": {
                    "field": aggregation_field,
                    "size": limit,
                }
            }
        },
    }
    data, clamps = await es_search(get_index(index).es_index, body, await index_known_fields(index))
    aggregation = data.get("aggregations", {}).get("values", {})
    result = {
        "index": index,
        "field": field,
        "aggregation_field": aggregation_field,
        "buckets": aggregation.get("buckets", []),
        "sum_other_doc_count": aggregation.get("sum_other_doc_count", 0),
        "doc_count_error_upper_bound": aggregation.get("doc_count_error_upper_bound", 0),
        "note": (
            "These are the most frequent values, not necessarily the complete vocabulary. "
            "A non-zero sum_other_doc_count means documents with other values were omitted."
        ),
    }
    if clamps:
        result["clamped"] = clamps
    return result


async def index_search(index: str, query_body: dict) -> dict:
    """Run a search and normalize the Elasticsearch response. Without _source, returns the primary fields."""
    body = dict(query_body)
    if "_source" not in body:
        primary = await index_primary_fields(index)
        if primary:
            body["_source"] = primary

    data, clamps = await es_search(get_index(index).es_index, body, await index_known_fields(index))
    hit_data = data.get("hits", {})
    total_data = hit_data.get("total", 0)
    total = total_data.get("value", 0) if isinstance(total_data, dict) else total_data

    notes: set[str] = set()
    hits = []
    for hit in hit_data.get("hits", []):
        item = {"_id": hit.get("_id"), **_shape(hit.get("_source", {}), notes)}
        if hit.get("_score") is not None:
            item["_score"] = hit["_score"]
        hits.append(item)

    result = {"total": total, "hits": hits}
    if "aggregations" in data:
        result["aggregations"] = data["aggregations"]
    if clamps:
        result["clamped"] = clamps

    logger.debug(f"{body=}")
    return _finalise(result, notes)
