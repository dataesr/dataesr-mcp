from mcp.server.fastmcp import FastMCP
from tools.get_affiliation_match import register_get_affiliation_match_tool


def register_tools(mcp: FastMCP):
    """Register all tools to the MCP server"""
    register_get_affiliation_match_tool(mcp)
