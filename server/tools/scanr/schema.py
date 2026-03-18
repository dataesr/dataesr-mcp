from mcp.server.fastmcp import FastMCP
from helpers.elastic import es_get_flat_mapping
from helpers.logger import get_logger
import json

logger = get_logger(__name__)


def register(mcp: FastMCP, index: str, description: str):

    @mcp.tool(name=f"{index}_get_schema")
    def get_schema() -> str:
        f"""
        Fetch and return the simplified field schema for the {index} Elasticsearch index.
        Index content: {description}
        Call this before building any query so you know which fields exist and their types.

        Returns a flat dict of dot-notation field paths with their types, e.g.:
          "title.default": {{"type": "text", "keyword": true}}
          "year":           {{"type": "long"}}
          "isOa":           {{"type": "boolean"}}

        Notes:
        - text fields  → use match / multi_match queries
        - keyword fields → use term / terms queries (exact match)
        - if "keyword": true → a .keyword sub-field exists for aggregations/exact match
        """
        fields = es_get_flat_mapping(index)
        logger.debug(f"{fields=}")
        return json.dumps({"index": index, "fields": fields}, indent=2)
