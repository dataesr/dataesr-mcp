from mcp.server.fastmcp import FastMCP
from helpers.elastic import es_get_flat_mapping
from helpers.logger import get_logger

logger = get_logger(__name__)


def register(mcp: FastMCP, index: str, index_description: str):

    @mcp.tool(
        name=f"{index}_get_schema",
        description=f"""
        Fetch and return the simplified field schema for the {index} Elasticsearch index.
        Index content: {index_description}
        Call this before building any query so you know which fields exist and their types.

        Returns a flat dict of dot-notation field paths with their types, e.g.:
          "title.default": {{"type": "text", "keyword": true}}
          "year":           {{"type": "long"}}
          "isOa":           {{"type": "boolean"}}

        Notes:
        - text fields  → use match / multi_match queries
        - keyword fields → use term / terms queries (exact match)
        - if "keyword": true → a .keyword sub-field exists for aggregations/exact match
        """,
    )
    def get_schema() -> dict:
        f"""
        Get simplified schema for the {index} Elasticsearch index.
        """
        fields = es_get_flat_mapping(index)
        # TODO: return primary fields by default (option to return "full" schema)
        logger.debug(f"{fields=}")
        return {"index": index, "fields": fields}
