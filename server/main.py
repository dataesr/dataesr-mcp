from mcp.server.fastmcp import FastMCP
from tools import register_tools

# Create MCP server
mcp = FastMCP("dataesr-mcp", json_response=True, host="0.0.0.0")

# Register tools
register_tools(mcp)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
