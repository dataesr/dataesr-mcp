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

        Elasticsearch Query Building Guide:
        1. Contexts (inside a 'bool' query):
           - 'must': Conditions that MUST match, contributes to search score. Used for text search (match/multi_match).
           - 'filter': Conditions that MUST match, but do NOT contribute to score. Used for exact matches, IDs, booleans, and dates (term/terms/range).
           - 'should': Conditions that are OPTIONAL, but boost the score if they match.
           - 'must_not': Conditions that MUST NOT match.
        2. Field Types & Queries:
           - text fields: Use 'match' (single field) or 'multi_match' (multiple fields).
           - keyword fields / IDs: Use 'term' (one exact value) or 'terms' (array of exact values). Use these inside the 'filter' context.
           - numbers / dates / booleans: Use 'range' or 'term' inside the 'filter' context.
        3. Performance & Size:
           - Always set '_source' to a list of the fields you actually need to keep responses small.
           - Set 'size' to limit results (max 20). If only doing aggregations, set "size": 0.

        Example Complex Query:
        {{
            "query": {{
                "bool": {{
                    "must": [
                        {{"multi_match": {{"query": "climate change", "fields": ["title.default^3", "abstract.*"]}}}}
                    ],
                    "filter": [
                        {{"term": {{"isOa": true}}}},
                        {{"terms": {{"affiliations.id.keyword": ["123456789"]}}}}
                    ]
                }}
            }},
            "_source": ["id", "title.default", "year"],
            "size": 10
        }}
        """,
    )
    async def search(
        query: Annotated[
            dict,
            Field(
                description=(
                    f"A complete Elasticsearch request body for the {index} index. "
                    "Use 'bool' with 'must' for text matching and 'filter' for exact/ID matching. "
                    'Example text search + filter: {"query": {"bool": {"must": [{"multi_match": {"query": "AI", "fields": ["title.*"]}}], "filter": [{"term": {"isOa": true}}]}}, "_source": ["id", "title.default"], "size": 10} '
                    'Example aggregation: {"size": 0, "query": {"bool": {"must": [{"term": {"projects.id.keyword": "123456789"}}]}}, "aggs": {"projects": {"terms": {"field": "projects.id.keyword"}}}}'
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
