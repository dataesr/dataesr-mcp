from mcp.server.fastmcp import FastMCP
from tools.scanr import schema, search

INDEXES = {
    "scanr_publications": "Scientific publications (articles, theses, conference papers)",
    "scanr_organizations": "Research organizations and laboratories (universities, CNRS units, etc.)",
    "scanr_persons": "Researchers and authors with their affiliations and identifiers (ORCID, IdRef)",
    "scanr_projects": "Funded research projects (ANR, EU, etc.) with budget and partners",
    "scanr_patents": "Patents filed by French research institutions",
    "scanr_participations": "Participation links between organizations and projects",
}


def register(mcp: FastMCP):
    for index, description in INDEXES.items():
        schema.register(mcp, index, description)
        search.register(mcp, index, description)
