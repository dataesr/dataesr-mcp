"""One shared async HTTP client for every upstream service, with uniform error reporting."""

import httpx
from typing import Any
from mcp.server.fastmcp.exceptions import FastMCPError

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def request(method: str, url: str, *, service: str, **kwargs) -> httpx.Response:
    """Send a request. Transport failures become tool errors; HTTP status is left to the caller."""
    try:
        return await get_client().request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise FastMCPError({"error": "upstream_unavailable", "service": service, "message": str(exc)}) from exc


async def request_json(method: str, url: str, *, service: str, **kwargs) -> Any:
    """Send a request and return the decoded JSON body, or raise a tool error on a non-2xx status."""
    response = await request(method, url, service=service, **kwargs)
    if not response.is_success:
        raise FastMCPError(
            {"error": "upstream_error", "service": service, "status": response.status_code, "message": response.text[:500]}
        )
    return response.json()
