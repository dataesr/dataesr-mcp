import json
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from helpers.elastic import es_search
from logger import get_logger

logger = get_logger(__name__)

def register(mcp: FastMCP):

    @mcp.tool()
    def get_publication_by_id(
        id: Annotated[str | None, Field(description="The scanR publication ID (id field)")] = None,
        doi: Annotated[
            str | None, Field(description="DOI without the https://doi.org/ prefix, e.g. '10.1038/s41586-021-03819-2'")
        ] = None,
    ) -> str:
        """
        Fetch a single publication by its scanR ID or by DOI.
        Provide exactly one of 'id' or 'doi'.
        """
        if not id and not doi:
            return json.dumps({"error": "Provide either 'id' or 'doi'."})

        query = {"term": {"id.keyword": id}} if id else {"term": {"externalIds.id.keyword": doi}}
        logger.debug(f"{query=}")
        data = es_search({"size": 1, "query": query})
        hits = data.get("hits", {}).get("hits", [])
        logger.debug(f"{hits=}")
        if not hits:
            return json.dumps({"error": "Publication not found."})
        return json.dumps(hits[0]["_source"], indent=2)
