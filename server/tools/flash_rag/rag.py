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
    ) -> list[dict]:
        """
        Get the sources of a query from flash notes RAG.
        """
        payload = {"question": query, top_k: top_k}
        logger.debug(f"Sending query to Flash RAG: {payload}")
        with httpx.Client() as client:
            response = client.post(QUERY_URL, json=payload, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Received response from Flash RAG: {data}")
            return data.get("sources", "No source found.")
