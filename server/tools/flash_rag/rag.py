import os
import httpx
from pydantic import Field
from mcp.server import FastMCP
from helpers.logger import get_logger

logger = get_logger(__name__)

QUERY_URL = os.getenv("FLASH_RAG_URL", "")
HEADERS = {"Content-Type": "application/json", "Authorization": os.getenv("FLASH_RAG_API_KEY", "")}


def register(mcp: FastMCP):

    @mcp.tool()
    async def flash_rag(
        query: str = Field(description="The user query to search for relevant sources (embedding distance)."),
        top_k: int = Field(default=5, description="The number of top relevant sources to return."),
        use_reranker: bool = Field(default=True, description="Lightweight reranker that check title words and dates"),
        filters: dict[str, str | list[str]] = Field(default_factory=dict, description="Filter documents metadatas"),
    ) -> list[dict]:
        """
        Get the most relevant documents from a query using a ChromaDB RAG.
        The documents are publications from the French Ministry of Higher Education and Research.
        They contains data, statistics and numbers about the education and research french landscape.

        Available metadata filters:
        - publication_date (str): Publication date string
        - publication_epoch (int): Publication date as epoch timestamp
        - publication_type (str): Type of publication - 'book' or 'article'
        - chunk_type (str): Type of chunk - 'paragraph' or 'table'
        - chunk_len (int): Length of the chunk
        - keywords (list[str]): List of keywords
        - file_access (str): Access status - 'open' or 'close'
        """

        payload = {
            "query": query,
            "top_k": top_k,
            "use_reranker": use_reranker,
            "filters": filters,
        }
        logger.debug(f"Sending query to Flash RAG: {payload}")
        with httpx.Client() as client:
            response = client.post(QUERY_URL, json=payload, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Received response from Flash RAG: {data}")

            sources = [
                {
                    "distance": source.get("distance"),
                    "document": source.get("document"),
                    "metadata": {
                        "title": source.get("metadata", {}).get("title", ""),
                        "section_title": source.get("metadata", {}).get("section_title", ""),
                        "publication_date": source.get("metadata", {}).get("publication_date", ""),
                        "publication_type": source.get("metadata", {}).get("publication_type", ""),
                        "file_access": source.get("metadata", {}).get("file_access", ""),
                        "file_url": source.get("metadata", {}).get("file_url", ""),
                        "chunk_type": source.get("metadata", {}).get("chunk_type", ""),
                    },
                }
                for source in data.get("sources", [])
            ]
            return sources
