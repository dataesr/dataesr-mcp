from mcp.server.fastmcp import FastMCP
from tools.scanr.publications.helpers.api import request_scanr_publications, scanr_publication_to_string
from logger import get_logger

logger = get_logger(__name__)


def register_get_publication_tool(mcp: FastMCP):
    @mcp.tool()
    async def get_publication(publication_id: str) -> str:
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
        try:
            data = request_scanr_publications(payload)
            publication = data.get("hits", {}).get("hits", [])[0].get("_source")
            if not publication:
                return f"No publication found for id '{publication_id}'"
            content = scanr_publication_to_string(publication)
            logger.debug(f"content: {content}")
            return content
        except Exception as error:
            logger.error(f"Error: {error}")
            return f"Error: {error}"
