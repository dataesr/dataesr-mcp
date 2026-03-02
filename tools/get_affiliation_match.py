from mcp.server.fastmcp import FastMCP
from typing import Literal
import requests


def register_get_affiliation_match_tool(mcp: FastMCP):
    """Register the affiliation matcher tool"""

    @mcp.tool()
    async def get_affiliation_match(
        affiliation: str, reference: Literal["country", "grid", "ror", "rnsr", "paysage"]
    ) -> str:
        """Get the match of an affiliation string to a reference system including country, grid, ROR, RNSR, paysage"""
        payload = {
            "query": affiliation,
            "type": reference,
        }
        try:
            response = requests.post("https://affiliation-matcher.staging.dataesr.ovh/match", json=payload)
            data = response.json()
            results = data.get("results", [])
            if len(results) == 0:
                return "No match found"
            return f"{reference} ids: {', '.join([id for id in results])}"
        except Exception as error:
            return f"Error: {error}"
