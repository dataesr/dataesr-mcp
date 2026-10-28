import os
import httpx
from pydantic import Field
from urllib.parse import quote
from mcp.server import FastMCP
from helpers.logger import get_logger

logger = get_logger(__name__)

CATALOGUE_API_URL = os.getenv("CATALOGUE_API_URL", "")
HEADERS = {"Content-Type": "application/json", "Authorization": os.getenv("CATALOGUE_API_KEY", "")}


def register(mcp: FastMCP):

    @mcp.tool()
    async def flash_rag(
        query: str = Field(description="The user query to search for relevant sources (embedding distance)."),
        top_k: int = Field(default=5, description="The number of top relevant sources to return."),
        use_hybrid_search: bool = Field(default=True, description="Enable hybrid search with BM25"),
        use_reranker: bool = Field(default=True, description="Enable results reranking"),
        # use_reranker: bool = Field(default=True, description="Enable lightweight reranker that check title words and dates"),
        # use_cross_encoder: bool = Field(default=True, description="Enable cross encoder reranker"),
        # use_mistral: bool = Field(default=True, description="Add mistral answer completion"),
        # filters: dict[str, str | list[str]] = Field(default_factory=dict, description="Filter documents metadatas"),
    ) -> list[dict]:
        """
        Get the most relevant documents from a query using the French Ministry RAG.
        The documents are publications from the French Ministry of Higher Education and Research.
        They contains data, statistics and numbers about the education and research french landscape.
        """

        query_url = os.path.join(CATALOGUE_API_URL, "rag")
        query_url += f"?q={quote(query)}"
        if top_k:
            query_url += f"&topK={top_k}"
        if use_reranker:
            query_url += "&useRerank=true"
        if use_hybrid_search:
            query_url += "&useHybrid=true"

        logger.debug(f"Sending query to Catalogue RAG: {query_url}")
        with httpx.Client() as client:
            response = client.get(query_url, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Received response from Catalogue RAG: {data}")

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
