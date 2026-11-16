"""Minimal MCP client over streamable HTTP (JSON responses), usable with a Starlette TestClient or httpx.Client.

Each call is a plain JSON-RPC POST, which makes the protocol visible: initialize, notify, tools/list, tools/call.
"""

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """Raised on a JSON-RPC error or an unexpected HTTP status."""


@dataclass
class ToolResult:
    is_error: bool
    text: str
    structured: Any = None

    @property
    def data(self) -> Any:
        """Structured content when available, otherwise the text parsed as JSON."""
        if self.structured is not None:
            return self.structured.get("result", self.structured) if isinstance(self.structured, dict) else self.structured
        return json.loads(self.text)


class McpSession:
    def __init__(self, http, route: str, token: str | None):
        self.http = http
        self.route = route
        self.token = token
        self.session_id: str | None = None
        self._next_id = 0

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return headers

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def post(self, payload: dict):
        """Send a raw JSON-RPC message and return the HTTP response."""
        return self.http.post(self.route, json=payload, headers=self._headers())

    def initialize(self) -> dict:
        response = self.post(
            {
                "jsonrpc": "2.0",
                "id": self._new_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "tests", "version": "0"},
                },
            }
        )
        if response.status_code != 200:
            raise McpError(f"initialize failed: {response.status_code} {response.text}")
        self.session_id = response.headers.get("mcp-session-id")
        self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return response.json()["result"]

    def rpc(self, method: str, params: dict | None = None) -> dict:
        response = self.post({"jsonrpc": "2.0", "id": self._new_id(), "method": method, "params": params or {}})
        if response.status_code != 200:
            raise McpError(f"{method} failed: {response.status_code} {response.text}")
        body = response.json()
        if "error" in body:
            raise McpError(f"{method} failed: {body['error']}")
        return body["result"]

    def tool_names(self) -> list[str]:
        return [tool["name"] for tool in self.rpc("tools/list")["tools"]]

    def call(self, name: str, arguments: dict | None = None) -> ToolResult:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        text = "".join(block.get("text", "") for block in result.get("content", []) if block.get("type") == "text")
        return ToolResult(is_error=result.get("isError", False), text=text, structured=result.get("structuredContent"))
