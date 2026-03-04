from mcp.server.fastmcp import FastMCP
from typing import Literal
from pydantic import Field
import requests
from .helpers.schemas import AffiliationMatch


def register_get_affiliation_match_tool(mcp: FastMCP):
    @mcp.tool()
    async def get_affiliation_match(
        affiliation: str = Field(description="Affiliation string to look for a match"),
        reference: Literal["country", "grid", "ror", "rnsr", "paysage"] = Field(
            description="Reference system to match against",
            default="ror",
        ),
    ) -> AffiliationMatch:
        """Get the ids of an affiliation string in a reference system including country, grid, ROR, RNSR and paysage"""
        payload = {
            "query": affiliation,
            "type": reference,
        }
        response = requests.post("https://affiliation-matcher.staging.dataesr.ovh/match", json=payload)
        response.raise_for_status()
        data = response.json()
        return AffiliationMatch(results=data["results"], enriched_results=data["enriched_results"])
