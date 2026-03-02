from mcp.server.fastmcp import FastMCP
from tools.scanr.search_publications import register_search_publications_tool


def register_scanr_tools(mcp: FastMCP):
    register_search_publications_tool(mcp)
