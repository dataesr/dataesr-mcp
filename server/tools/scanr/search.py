from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from helpers.elastic import es_search, es_validate_fields, es_validate_size
from helpers.logger import get_logger

logger = get_logger(__name__)


def register(mcp: FastMCP, index: str, index_description: str):

    @mcp.tool(
        name=f"{index}_search",
        description=f"""
        Execute an Elasticsearch query against the {index} index.
        Index content: {index_description}
        Call {index}_get_schema() first to discover available fields.

        Tips:
            - Use match/multi_match for text fields, term/terms for keyword fields.
            - Always set _source to only the fields you need (keeps responses small).
            - Use 'fields' to specify the fields to search in. You can boost the fields by using the ^ operator.
            - Use 'size' to control result count (default ES is 10, max recommended 50).
            - Set 'size' to 0 for aggregations (counts and stats)
        """,
    )
    async def search(
        query: Annotated[
            dict,
            Field(
                description=(
                    f"A complete Elasticsearch request body for the {index} index. "
                    'Example: {"query": {"match": {"title.default": "climate change"}}, "_source": ["title.default", "year"], "fields": ["title.default^2", "abstract.*^1"], "size": 10}'
                    'Example for aggregation: {"aggs": {"projects": {"terms": {"field": "projects.id.keyword"}}}, "size": 0}'
                )
            ),
        ],
    ) -> dict:
        f"""
        Execute an Elasticsearch query against the {index} index.
        """
        es_validate_fields(query, index, raise_error=True)
        es_validate_size(query, index, raise_error=True)

        data = await es_search(index, query)
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        hits = [hit["_source"] for hit in data.get("hits", {}).get("hits", [])]
        result = {"total": total, "hits": hits}
        if "aggregations" in data:
            result["aggregations"] = data["aggregations"]

        logger.debug(f"{query=}")
        logger.debug(f"{result=}")

        return result
