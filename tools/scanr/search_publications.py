import os
import requests
from mcp.server.fastmcp import FastMCP
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
            response = requests.get(
                "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
                json=payload,
                headers={"Authorization": os.getenv("SCANR_API_KEY")},
            )
            data = response.json()
            publications = data.get("hits", {}).get("hits", [])
            if len(publications) == 0:
                return f"No publications found for query '{query}'"
            contents = [f"Found {data['hits']['total']['value']} publications for query '{query}'"]
            for index, publication in enumerate(publications):
                publication_data = publication.get("_source")
                contents.append(f"{index + 1}. Title: {publication_data['title']['default']}")
                contents.append(f"  ID: {publication_data['id']}")
                if publication_data.get("summary"):
                    contents.append(f"  Summary: {publication_data['summary']['default']}")
                if publication_data.get("domains"):
                    contents.append(
                        f"  Topics: {', '.join([domain['label']['default'] for domain in publication_data['domains']])}\n"
                    )
            return "\n".join(contents)
        except Exception as error:
            return f"Error: {error}"
