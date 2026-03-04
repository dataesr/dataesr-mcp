from mcp.server.fastmcp import FastMCP
from tools.affiliation_matcher.get_affiliation_match import register_get_affiliation_match_tool


def register_affiliation_matcher_tools(mcp: FastMCP):
    register_get_affiliation_match_tool(mcp)
