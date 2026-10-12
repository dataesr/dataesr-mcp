from helpers.elastic import es_search
from helpers.logger import get_logger

logger = get_logger(__name__)


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
