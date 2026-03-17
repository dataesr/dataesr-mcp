from mcp.server.fastmcp import FastMCP
from tools.scanr import publication, search, schema
from tools.affiliation_matcher import match

# Create MCP server
mcp = FastMCP("dataesr-mcp", json_response=True, host="0.0.0.0")

# Register tools
match.register(mcp)
publication.register(mcp)
search.register(mcp)
schema.register(mcp)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
