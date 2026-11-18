import json
import re
from typing import Literal
from mcp.server.fastmcp.exceptions import FastMCPError
from helpers.elastic import es_search
from helpers.logger import get_logger
from tools.scanr.registry import get_index
from tools.scanr import schema
from tools.scanr.schema import index_get_aggregation_field, index_known_fields, index_primary_fields

logger = get_logger(__name__)

MAX_STRING_CHARS = 300
MAX_LIST_ITEMS = 50
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


def _shape_aggregation(value, notes: set[str]):
    if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
        notes.add("aggregation strings")
        return value[:MAX_STRING_CHARS] + "…"
    if isinstance(value, list):
        return [_shape_aggregation(item, notes) for item in value]
    if isinstance(value, dict):
        return {key: _shape_aggregation(item, notes) for key, item in value.items()}
    return value


def _drop_last_bucket(value) -> bool:
    if isinstance(value, dict):
        buckets = value.get("buckets")
        if isinstance(buckets, list):
            for bucket in reversed(buckets):
                if _drop_last_bucket(bucket):
                    return True
            if buckets:
                buckets.pop()
                return True
        for item in value.values():
            if _drop_last_bucket(item):
                return True
    elif isinstance(value, list):
        for item in reversed(value):
            if _drop_last_bucket(item):
                return True
    return False


def _finalise(result: dict, notes: set[str]) -> dict:
    """Trim hits or aggregation buckets until the response fits the size budget."""
    hints = []
    if "strings" in notes:
        hints.append("Long hit strings were shortened. Set _source to the fields you need to see them in full.")
    if "lists" in notes:
        hints.append("Long hit arrays were shortened. Narrow _source to the fields you need to see.")
    if "aggregation strings" in notes:
        hints.append("Long aggregation values were shortened.")
    while len(json.dumps(result, ensure_ascii=False, default=str)) > MAX_RESPONSE_CHARS and result.get("hits"):
        result["hits"].pop()
        result["truncated"] = True
    while len(json.dumps(result, ensure_ascii=False, default=str)) > MAX_RESPONSE_CHARS and result.get("buckets"):
        result["buckets"].pop()
        result["truncated"] = True
    while (
        len(json.dumps(result, ensure_ascii=False, default=str)) > MAX_RESPONSE_CHARS
        and _drop_last_bucket(result.get("aggregations"))
    ):
        result["truncated"] = True
    if len(json.dumps(result, ensure_ascii=False, default=str)) > MAX_RESPONSE_CHARS and "aggregations" in result:
        del result["aggregations"]
        result["aggregations_truncated"] = True
        result["truncated"] = True
    if result.get("truncated"):
        hints.append("The response was cut to fit the size budget. Narrow the query or reduce size.")
    if hints:
        result["truncated"] = True
        result["hint"] = " ".join(hints)
    return result


def _escape_lucene_regex(value: str) -> str:
    return re.sub(r'([.+*?()|{}\[\]\\\"#@&<>~])', r"\\\1", value)


async def index_field_values(
    index: str,
    field: str,
    limit: int = 50,
    filter_query: dict | None = None,
    contains: str | None = None,
    prefix: str | None = None,
    mode: Literal["values", "stats"] = "values",
) -> dict:
    """Return common values or numeric/date statistics for a schema-declared field."""
    if not 1 <= limit <= 100:
        raise FastMCPError("limit must be between 1 and 100.")
    if contains is not None and prefix is not None:
        raise FastMCPError("Use either contains or prefix, not both.")

    aggregation_field = await index_get_aggregation_field(index, field)
    field_schema = (await schema.index_get_base_schema(index)).get("fields", {}).get(field, {})
    field_type = field_schema.get("type")
    if (contains is not None or prefix is not None) and field_type not in {
        "text", "keyword", "constant_keyword", "wildcard",
    }:
        raise FastMCPError("contains and prefix filters require a string field.")
    if mode == "stats":
        if contains is not None or prefix is not None:
            raise FastMCPError("contains and prefix filters are only available in values mode.")
        if field_type not in {
            "byte", "short", "integer", "long", "unsigned_long",
            "half_float", "float", "double", "scaled_float", "date", "date_nanos",
        }:
            raise FastMCPError(f"Statistics are only available for numeric and date fields, not {field_type!r}.")
        body = {
            "size": 0,
            "query": filter_query or {"match_all": {}},
            "aggs": {"stats": {"stats": {"field": aggregation_field}}},
        }
        data, clamps = await es_search(get_index(index).es_index, body, await index_known_fields(index))
        result = {
            "index": index,
            "field": field,
            "aggregation_field": aggregation_field,
            "stats": data.get("aggregations", {}).get("stats", {}),
        }
        if clamps:
            result["clamped"] = clamps
        return result

    terms = {"field": aggregation_field, "size": limit}
    if contains is not None:
        terms["include"] = f".*{_escape_lucene_regex(contains)}.*"
    elif prefix is not None:
        terms["include"] = f"{_escape_lucene_regex(prefix)}.*"
    body = {
        "size": 0,
        "query": filter_query or {"match_all": {}},
        "aggs": {
            "values": {
                "terms": terms
            }
        },
    }
    data, clamps = await es_search(get_index(index).es_index, body, await index_known_fields(index))
    aggregation = data.get("aggregations", {}).get("values", {})
    notes: set[str] = set()
    result = {
        "index": index,
        "field": field,
        "aggregation_field": aggregation_field,
        "buckets": _shape_aggregation(aggregation.get("buckets", []), notes),
        "sum_other_doc_count": aggregation.get("sum_other_doc_count", 0),
        "doc_count_error_upper_bound": aggregation.get("doc_count_error_upper_bound", 0),
        "note": (
            "These are the most frequent values, not necessarily the complete vocabulary. "
            "A non-zero sum_other_doc_count means documents with other values were omitted."
        ),
    }
    if clamps:
        result["clamped"] = clamps
    return _finalise(result, notes)




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
        result["aggregations"] = _shape_aggregation(data["aggregations"], notes)
    response_hits = hit_data.get("hits", [])
    if body.get("sort") and response_hits and response_hits[-1].get("sort") is not None:
        result["next_cursor"] = response_hits[-1]["sort"]
    if clamps:
        result["clamped"] = clamps

    logger.debug(f"{body=}")
    return _finalise(result, notes)
