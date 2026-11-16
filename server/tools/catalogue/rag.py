import os
from pydantic import Field
from mcp.server import FastMCP
from helpers.http import request_json
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

        logger.debug(f"Sending query to Catalogue RAG: {query}")
        params = {"q": query, "topK": top_k}
        if use_reranker:
            params["useRerank"] = "true"
        if use_hybrid_search:
            params["useHybrid"] = "true"

        data = await request_json("GET", f"{CATALOGUE_API_URL.rstrip('/')}/rag", service="catalogue", params=params, headers=HEADERS, timeout=30)
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
