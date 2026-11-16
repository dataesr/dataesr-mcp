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


async def index_field_values(
    index: str,
    field: str,
    limit: int = 20,
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


def _escape_lucene_regex(value: str) -> str:
    return re.sub(r'([.+*?()|{}\[\]\\\"#@&<>~])', r"\\\1", value)


async def index_query(
    index: str,
    text: str | None = None,
    filters: dict | None = None,
    fields: list[str] | None = None,
    sort: dict[str, str] | None = None,
    limit: int = 10,
    cursor: list | None = None,
    aggregate: dict | None = None,
) -> dict:
    """Build and run a constrained search from structured scanR query options."""
    if not 1 <= limit <= 20:
        raise FastMCPError("limit must be between 1 and 20.")
    if cursor is not None and not sort:
        raise FastMCPError("cursor requires an explicit sort so search_after remains stable.")
    if cursor is not None and aggregate:
        raise FastMCPError("cursor cannot be combined with aggregation.")
    if cursor is not None and not cursor:
        raise FastMCPError("cursor must contain at least one sort value.")

    raw_schema = await schema.index_get_base_schema(index)
    declared_fields = raw_schema.get("fields", {})
    bool_query: dict = {}

    if text:
        text_fields = [
            name for name, metadata in declared_fields.items()
            if not metadata.get("exclude", False) and metadata.get("type") == "text"
        ]
        if not text_fields:
            raise FastMCPError(f"No searchable text fields are declared for {index}.")
        bool_query["must"] = [{"multi_match": {"query": text, "fields": text_fields}}]

    filter_clauses = []
    for field, value in (filters or {}).items():
        field_meta = schema.require_known_field(index, field, declared_fields)
        if isinstance(value, dict):
            if not value or set(value) - {"gte", "gt", "lte", "lt"}:
                raise FastMCPError(f"Range filter for {field!r} must use gte, gt, lte or lt.")
            if field_meta.get("type") not in {
                "byte", "short", "integer", "long", "unsigned_long",
                "half_float", "float", "double", "scaled_float", "date", "date_nanos",
            }:
                raise FastMCPError(f"Range filters require a numeric or date field; {field!r} is {field_meta.get('type')!r}.")
            filter_clauses.append({"range": {field: value}})
        elif isinstance(value, list):
            if not value:
                raise FastMCPError(f"Filter values for {field!r} cannot be empty.")
            if field_meta.get("type") == "text" and not field_meta.get("has_keyword"):
                raise FastMCPError(f"Exact filters require a keyword subfield for text field {field!r}.")
            target = await index_get_aggregation_field(index, field) if field_meta.get("has_keyword") else field
            filter_clauses.append({"terms": {target: value}})
        elif value is not None:
            if field_meta.get("type") == "text" and not field_meta.get("has_keyword"):
                raise FastMCPError(f"Exact filters require a keyword subfield for text field {field!r}.")
            target = await index_get_aggregation_field(index, field) if field_meta.get("has_keyword") else field
            filter_clauses.append({"term": {target: value}})
        else:
            raise FastMCPError(f"Filter value for {field!r} cannot be null.")
    if filter_clauses:
        bool_query["filter"] = filter_clauses

    query = {"bool": bool_query} if bool_query else {"match_all": {}}
    body = {"query": query, "size": 0 if aggregate else limit}

    if fields is not None and not aggregate:
        if not fields:
            raise FastMCPError("fields must contain at least one field.")
        body["_source"] = fields
    if sort:
        sort_fields = []
        for field, order in sort.items():
            metadata = schema.require_known_field(index, field, declared_fields)
            if order not in {"asc", "desc"}:
                raise FastMCPError("Sort directions must be 'asc' or 'desc'.")
            if metadata.get("type") == "text":
                if not metadata.get("has_keyword"):
                    raise FastMCPError(f"Text field {field!r} is not sortable according to the schema.")
                field = await index_get_aggregation_field(index, field)
            sort_fields.append({field: {"order": order}})
        body["sort"] = sort_fields
    if cursor is not None:
        body["search_after"] = cursor
    if aggregate:
        body["aggs"] = await _build_aggregate(index, aggregate, declared_fields)

    return await index_search(index, body)


async def _build_aggregate(index: str, aggregate: dict, declared_fields: dict) -> dict:
    if set(aggregate) - {"group_by", "metric"}:
        raise FastMCPError("aggregate supports only group_by and metric.")
    group_by = aggregate.get("group_by")
    if isinstance(group_by, str):
        group_by = [group_by]
    if not isinstance(group_by, list) or not group_by or any(not isinstance(field, str) for field in group_by):
        raise FastMCPError("aggregate.group_by must be a field name or a non-empty list of field names.")
    metric = aggregate.get("metric", {"type": "count"})
    if isinstance(metric, str):
        metric = {"type": metric}
    if not isinstance(metric, dict) or set(metric) - {"type", "field"}:
        raise FastMCPError("aggregate.metric must be a metric name or an object with type and field.")
    metric_type = metric.get("type", "count")
    if metric_type not in {"count", "avg", "sum", "min", "max"}:
        raise FastMCPError("Supported metrics are count, avg, sum, min and max.")
    if metric_type == "count":
        if metric.get("field"):
            raise FastMCPError("The count metric counts documents; do not provide a metric field.")
        if len(group_by) > 3:
            raise FastMCPError("At most three group_by fields are supported.")
    else:
        metric_field = metric.get("field")
        if not isinstance(metric_field, str):
            raise FastMCPError(f"Metric {metric_type!r} requires a declared metric field.")
        if len(group_by) > 2:
            raise FastMCPError("At most two group_by fields are supported with a metric.")
        metric_meta = schema.require_known_field(index, metric_field, declared_fields)
        numeric_types = {
            "byte", "short", "integer", "long", "unsigned_long",
            "half_float", "float", "double", "scaled_float",
        }
        date_types = {"date", "date_nanos"}
        valid_types = numeric_types | date_types if metric_type in {"min", "max"} else numeric_types
        if metric_meta.get("type") not in valid_types:
            required_types = "numeric or date" if metric_type in {"min", "max"} else "numeric"
            raise FastMCPError(f"Metric field {metric_field!r} must be {required_types}.")
        metric_field = await index_get_aggregation_field(index, metric_field)

    aggregation = {}
    current = aggregation
    for level, field in enumerate(group_by, start=1):
        aggregation_field = await index_get_aggregation_field(index, field)
        name = "group_by" if level == 1 else f"group_by_{level}"
        node = {"terms": {"field": aggregation_field, "size": 100}}
        current[name] = node  # ty: ignore[invalid-assignment]
        current = node.setdefault("aggs", {})
    if metric_type != "count":
        current["metric"] = {metric_type: {"field": metric_field}}  # ty: ignore[invalid-assignment]
    return aggregation


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
