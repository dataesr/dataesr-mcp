"""Shared fixtures: the real ASGI app, with every upstream service mocked."""

import os

TOKEN = "test-token"
SCOPE_SECRETS = {
    "scanr": "scanr-secret",
    "match": "match-secret",
    "rag": "rag-secret",
    "tableaux": "tableaux-secret",
}


# The server reads its configuration at import time, so this must run before importing it.
os.environ.update(
    {
        "MCP_AUTH_TOKEN": TOKEN,
        "MCP_SIGNING_KEY": "signing-key",
        "MCP_OAUTH_CLIENT_ID": "dataesr",
        **{f"MCP_TOKEN_{scope.upper()}": secret for scope, secret in SCOPE_SECRETS.items()},
        "MCP_PUBLIC_URL": "https://mcp.test",
        "ES_URL": "https://es.test",
        "ES_API_KEY": "es-key",
        "SCANR_SCHEMAS_URL": "https://schemas.test",
        "AFFILIATION_MATCHER_URL": "https://matcher.test/match",
        "CATALOGUE_API_URL": "https://catalogue.test/api/",
        "CATALOGUE_API_KEY": "catalogue-key",
        "TABLEAUX_REPO": "dataesr/tableaux",
        "TABLEAUX_REF": "staging",
    }
)
os.environ.pop("GITHUB_TOKEN", None)

import pytest  # noqa: E402
import respx  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from helpers import elastic  # noqa: E402
from mcp_client import McpSession  # noqa: E402
from tools.scanr import schema  # noqa: E402
from tools.tableaux import prototype  # noqa: E402


@pytest.fixture(scope="session")
def http():
    """The app, with its lifespan running. MCP session managers can only be started once per process."""
    with TestClient(main.app, base_url="https://mcp.test") as client:
        yield client


@pytest.fixture
def upstream():
    """Mock router for every outgoing HTTP call; a call that is not mocked fails the test."""
    schema.index_get_base_schema.cache_clear()
    elastic.es_get_flat_mapping.cache_clear()
    prototype.repository._cache.clear()
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def connect(http, upstream):
    """Open an initialized MCP session on a route: connect("/scanr")."""

    def _connect(route: str, token: str | None = TOKEN) -> McpSession:
        session = McpSession(http, route, token)
        session.initialize()
        return session

    return _connect
