import os
import uvicorn
import contextlib
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Mount
from tools.affiliation_matcher import match
from tools.scanr import scanr
from tools.flash_rag import rag

VALID_TOKEN = os.environ["MCP_AUTH_TOKEN"]

transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

# Create MCP servers
scanr_mcp = FastMCP("scanr-mcp", streamable_http_path="/", json_response=True, transport_security=transport_security)
match_mcp = FastMCP("match-mcp", streamable_http_path="/", json_response=True, transport_security=transport_security)
rag_mcp = FastMCP("rag-mcp", streamable_http_path="/", json_response=True, transport_security=transport_security)


# Register tools
scanr.register(scanr_mcp)
match.register(match_mcp)
rag.register(rag_mcp)


# Create lifespan context manager to manage MCP sessions
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(scanr_mcp.session_manager.run())
        await stack.enter_async_context(match_mcp.session_manager.run())
        await stack.enter_async_context(rag_mcp.session_manager.run())
        yield


# Middleware for bearer token authentication
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip()
        if auth_header.startswith("Bearer ") and token == VALID_TOKEN:
            return await call_next(request)
        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="mcp"'},
        )


# Create app
app = Starlette(
    routes=[
        Mount("/scanr", app=scanr_mcp.streamable_http_app()),
        Mount("/match", app=match_mcp.streamable_http_app()),
        Mount("/rag", app=rag_mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
    middleware=[Middleware(AuthMiddleware)],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
