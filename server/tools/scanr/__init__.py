from mcp.server.fastmcp import FastMCP
from tools.scanr.publications import register_scanr_publications_tools


def register_scanr_tools(mcp: FastMCP):
    register_scanr_publications_tools(mcp)
