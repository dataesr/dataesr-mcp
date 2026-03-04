from mcp.server.fastmcp import FastMCP
from tools.affiliation_matcher import register_affiliation_matcher_tools
from tools.scanr import register_scanr_tools


def register_tools(mcp: FastMCP):
    """Register all tools to the MCP server"""
    register_affiliation_matcher_tools(mcp)
    register_scanr_tools(mcp)
