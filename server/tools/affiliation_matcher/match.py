import os
from mcp.server.fastmcp import FastMCP
from typing import Literal
from pydantic import Field
from .helpers.schemas import AffiliationMatch
from helpers.http import request_json

MATCH_URL: str = os.getenv("AFFILIATION_MATCHER_URL", "")

def register(mcp: FastMCP):

    @mcp.tool()
    async def get_affiliation_match(
        affiliation: str = Field(description="Affiliation string to look for a match"),
        reference: Literal["country", "grid", "ror", "rnsr"] = Field(
            description="Reference system to match against",
            default="ror",
        ),
    ) -> AffiliationMatch:
        """Get the ids of an affiliation string in a reference system including country, grid, ROR, RNSR and paysage"""
        payload = {
            "query": affiliation,
            "type": reference,
        }
        data = await request_json("POST", MATCH_URL, service="matcher", json=payload, timeout=15)
        return AffiliationMatch(results=data["results"], enriched_results=data["enriched_results"])
