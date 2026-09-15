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
        - reference (str): Source reference - 'eesr' (Etat de l'Enseignement Superieur et de la Recherche) or 'ssmesr' (Service Statistique du Ministere de l'Enseignement Superieur et de la Recherche)
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
            return data.get("sources", "No source found.")
