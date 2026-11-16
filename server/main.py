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
from helpers import credentials, oauth
from helpers.http import close_client
from tools.affiliation_matcher import match
from tools.scanr import scanr
from tools.catalogue import rag
from tools.tableaux import prototype as tableaux

transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

# Create MCP servers
scanr_mcp = FastMCP("scanr-mcp", instructions=scanr.INSTRUCTIONS, streamable_http_path="/", json_response=True, transport_security=transport_security)
matcher_mcp = FastMCP("matcher-mcp", streamable_http_path="/", json_response=True, transport_security=transport_security)
rag_mcp = FastMCP("rag-mcp", streamable_http_path="/", json_response=True, transport_security=transport_security)
tableaux_mcp = FastMCP("tableaux-mcp", streamable_http_path="/", json_response=True, transport_security=transport_security)


# Register tools
scanr.register(scanr_mcp)
match.register(matcher_mcp)
rag.register(rag_mcp)
tableaux.register(tableaux_mcp)


# Create lifespan context manager to manage MCP sessions
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(scanr_mcp.session_manager.run())
        await stack.enter_async_context(matcher_mcp.session_manager.run())
        await stack.enter_async_context(rag_mcp.session_manager.run())
        await stack.enter_async_context(tableaux_mcp.session_manager.run())
        try:
            yield
        finally:
            await close_client()


# Middleware for bearer token authentication and per-route authorization
def _bearer_credential(request: Request) -> credentials.Credential | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    return credentials.by_secret(token) or oauth.access_credential(token)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if oauth.is_public_path(request.url.path):
            return await call_next(request)
        credential = _bearer_credential(request)
        if credential is None:
            metadata = f"{oauth.base_url(request)}/.well-known/oauth-protected-resource{request.url.path.rstrip('/')}"
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": f'Bearer realm="mcp", resource_metadata="{metadata}"'},
            )
        scope = request.url.path.lstrip("/").split("/", 1)[0]
        if scope in credentials.ROUTE_SCOPES and not credential.allows(scope):
            return Response(
                content=f"Forbidden: this credential has no access to /{scope}",
                status_code=403,
                headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'},
            )
        return await call_next(request)


# Create app
app = Starlette(
    routes=[
        *oauth.routes,
        Mount("/scanr", app=scanr_mcp.streamable_http_app()),
        Mount("/match", app=matcher_mcp.streamable_http_app()),
        Mount("/rag", app=rag_mcp.streamable_http_app()),
        Mount("/tableaux", app=tableaux_mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
    middleware=[Middleware(AuthMiddleware)],
)

# Serve each mount at both "/scanr" and "/scanr/" without a redirect: MCP clients may POST to the
# path without the trailing slash, and do not re-send the request after a 307.
class MountPathNormalizer:
    def __init__(self, wrapped: Starlette, prefixes: tuple[str, ...]):
        self.wrapped = wrapped
        self.prefixes = prefixes

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and scope["path"] in self.prefixes:
            scope = {**scope, "path": scope["path"] + "/"}
            if scope.get("raw_path") is not None:
                scope["raw_path"] = scope["raw_path"] + b"/"
        await self.wrapped(scope, receive, send)


app = MountPathNormalizer(app, ("/scanr", "/match", "/rag", "/tableaux"))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
