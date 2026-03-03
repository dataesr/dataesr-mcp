from mcp.server.fastmcp import FastMCP
from tools.scanr.publications.helpers.api import request_scanr_publications, scanr_publication_to_string
from logger import get_logger

logger = get_logger(__name__)


def register_search_publications_tool(mcp: FastMCP):
    @mcp.tool()
    async def search_publications(query: str, size: int = 10) -> str:
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
        try:
            data = request_scanr_publications(payload)
            publications = data.get("hits", {}).get("hits", [])
            if len(publications) == 0:
                return f"No publications found for query '{query}'"
            contents = [f"Found {data['hits']['total']['value']} publications for query '{query}'"]
            for index, publication in enumerate(publications):
                publication_data = publication.get("_source")
                contents.append(f"{index + 1}. {scanr_publication_to_string(publication_data)}")
            content = "\n".join(contents)
            logger.debug(f"content: {content}")
            return content
        except Exception as error:
            logger.error(f"Error: {error}")
            return f"Error: {error}"
