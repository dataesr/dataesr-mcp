from helpers.elastic import es_search
from mcp.server.fastmcp.exceptions import FastMCPError
from tools.scanr.schema import index_get_aggregation_field
from helpers.logger import get_logger

logger = get_logger(__name__)


async def index_field_values(
    index: str,
    field: str,
    limit: int = 20,
    filter_query: dict | None = None,
) -> dict:
    """Return the most frequent terms for a schema-declared aggregatable field."""
    if not 1 <= limit <= 100:
        raise FastMCPError("limit must be between 1 and 100.")

    aggregation_field = index_get_aggregation_field(index, field)
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
    data = await es_search(index, body)
    aggregation = data.get("aggregations", {}).get("values", {})
    return {
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

async def index_search(index: str, query_body: dict) -> dict:
    """Run a search and normalize the Elasticsearch response."""
    data = await es_search(index, query_body)
    hit_data = data.get("hits", {})
    total_data = hit_data.get("total", 0)
    total = total_data.get("value", 0) if isinstance(total_data, dict) else total_data
    hits = [hit["_source"] for hit in hit_data.get("hits", [])]
    result = {"total": total, "hits": hits}
    if "aggregations" in data:
        result["aggregations"] = data["aggregations"]

    logger.debug(f"{query_body=}")
    logger.debug(f"{result=}")
    return result
