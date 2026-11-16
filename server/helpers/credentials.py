"""Credentials: one per route scope, plus the admin credential.

Each credential is a secret from the environment, used directly as a bearer token, or as the client_secret of
its pre-configured OAuth client (client_id = the credential id):

- MCP_TOKEN_SCANR, MCP_TOKEN_MATCH, MCP_TOKEN_RAG, MCP_TOKEN_TABLEAUX: valid on that route only.
- MCP_AUTH_TOKEN: the admin credential, valid on every route.

An unset variable means no credential. Credentials are read once at startup, so after removing one, restart
the server: its tokens are then rejected.
"""

import hmac
import os
from dataclasses import dataclass, field

ROUTE_SCOPES = ("scanr", "match", "rag", "tableaux")
ALL_SCOPES = "*"
ADMIN_ID = "admin"


@dataclass(frozen=True)
class Credential:
    id: str
    secret: str = field(repr=False)
    scopes: frozenset[str]

    def allows(self, scope: str) -> bool:
        return ALL_SCOPES in self.scopes or scope in self.scopes

    def routes(self) -> list[str]:
        return [route for route in ROUTE_SCOPES if self.allows(route)]

    def matches(self, secret: str) -> bool:
        return hmac.compare_digest(self.secret.encode(), secret.encode())


def load(env) -> dict[str, Credential]:
    """Build the credentials by id from an environment mapping."""
    credentials: dict[str, Credential] = {}
    if env.get("MCP_AUTH_TOKEN"):
        credentials[ADMIN_ID] = Credential(ADMIN_ID, env["MCP_AUTH_TOKEN"], frozenset({ALL_SCOPES}))
    for scope in ROUTE_SCOPES:
        secret = env.get(f"MCP_TOKEN_{scope.upper()}")
        if secret:
            credentials[scope] = Credential(scope, secret, frozenset({scope}))
    return credentials


LEGACY_CLIENT_ID = os.environ.get("MCP_OAUTH_CLIENT_ID", "dataesr")
CREDENTIALS = load(os.environ)


def by_id(credential_id: str) -> Credential | None:
    return CREDENTIALS.get(credential_id)


def by_secret(secret: str) -> Credential | None:
    """The credential whose secret this is, if any."""
    return next((credential for credential in CREDENTIALS.values() if credential.matches(secret)), None)


def client_credential(client_id: str) -> Credential | None:
    """The credential behind a pre-configured OAuth client: its id, or MCP_OAUTH_CLIENT_ID for the admin."""
    return by_id(ADMIN_ID if client_id == LEGACY_CLIENT_ID else client_id)
