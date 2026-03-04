from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from tools.scanr.publications.helpers.api import request_scanr_publications
from tools.scanr.publications.helpers.schemas import ScanRPublication, scanr_publication_to_model
from logger import get_logger

logger = get_logger(__name__)


def register_get_publication_tool(mcp: FastMCP):
    @mcp.tool()
    async def get_publication(publication_id: str) -> ScanRPublication:
        payload = {
            "_source": [
                "title",
                "summary",
                "authors.fullName",
                "authors.person",
                "authors.role",
                "authors.affiliations",
                "domains",
                "affiliations",
                "source",
                "isOa",
                "type",
                "id",
                "year",
                "projects",
                "software",
            ],
            "query": {"bool": {"filter": [{"term": {"id.keyword": publication_id}}]}},
        }
        data = request_scanr_publications(payload)
        publication = data.get("hits", {}).get("hits", [])[0].get("_source")
        if not publication:
            raise ToolError(f"No publication found for id '{publication_id}'")
        return scanr_publication_to_model(publication)
