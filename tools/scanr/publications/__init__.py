from mcp.server.fastmcp import FastMCP
from tools.scanr.publications.search_publications import register_search_publications_tool
from tools.scanr.publications.get_publication import register_get_publication_tool


def register_scanr_publications_tools(mcp: FastMCP):
    register_search_publications_tool(mcp)
    register_get_publication_tool(mcp)
