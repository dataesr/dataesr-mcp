from mcp.server.fastmcp import FastMCP
from tools.affiliation_matcher import match
from tools.scanr import scanr

# Create MCP server
mcp = FastMCP("dataesr-mcp", streamable_http_path="/", json_response=True, host="0.0.0.0", port=8000)

# Register tools
match.register(mcp)
scanr.register(mcp)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
