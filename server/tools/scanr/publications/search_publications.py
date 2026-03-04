from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from tools.scanr.publications.helpers.api import request_scanr_publications
from tools.scanr.publications.helpers.schemas import ScanRLightPublication
from logger import get_logger

logger = get_logger(__name__)


def register_search_publications_tool(mcp: FastMCP):
    @mcp.tool()
    async def search_publications(query: str, size: int = 10) -> list[ScanRLightPublication]:
        """Search for publications in ScanR by keywords"""
        search_fields = ["title.*^3", "summary.*^2", "domains.label.*^2"]
        source_fields = ["id", "title.default", "summary.default", "domains"]
        payload = {
            "size": size,
            "_source": source_fields,
            "query": {
                "bool": {
                    "must": [
                        {
                            "query_string": {
                                "query": query,
                                "fields": search_fields,
                            }
                        },
                    ]
                }
            },
        }
        logger.debug(f"payload: {payload}")

        data = request_scanr_publications(payload)
        publications = [hit["_source"] for hit in data.get("hits", {}).get("hits", [])]
        if len(publications) == 0:
            raise ToolError(f"No publications found for query '{query}'")
        return [
            ScanRLightPublication(
                id=publication["id"],
                title=publication["title"].get("default"),
                summary=publication.get("summary", {}).get("default"),
            )
            for publication in publications
        ]
