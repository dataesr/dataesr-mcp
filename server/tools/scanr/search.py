import json
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from helpers.elastic import es_search
from logger import get_logger

logger = get_logger(__name__)

def register(mcp: FastMCP):

    @mcp.tool()
    def search_publications(
        query: Annotated[
            dict,
            Field(
                description=(
                    "A complete Elasticsearch request body. Example: "
                    '{"query": {"match": {"title.default": "climate"}}, '
                    '"_source": ["title.default", "year", "isOa"], "size": 10}'
                )
            ),
        ],
    ) -> str:
        """
        Execute an Elasticsearch query against the scanr-publications index.
        Call get_schema() first to know available fields and their types.

        Tips:
        - Use match/multi_match for text fields, term/terms for keyword fields.
        - Always set _source to only the fields you need (keeps responses small).
        - Use 'size' to control result count (default ES is 10, max recommended 50).
        - For aggregations (counts, stats), set size: 0 and use the 'aggs' key.
        - For sorting, 'year' and 'cited_by_counts_by_year.*' are useful numeric fields.
        """
        logger.debug(f"{query=}")
        data = es_search(query)
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        hits = [hit["_source"] for hit in data.get("hits", {}).get("hits", [])]
        result = {"total": total, "hits": hits}
        if "aggregations" in data:
            result["aggregations"] = data["aggregations"]
        logger.debug(f"{result=}")
        return json.dumps(result, indent=2)
