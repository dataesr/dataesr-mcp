"""Credentials per route scope: bearer tokens, OAuth with a credential, revocation and configuration loading."""

import base64
import hashlib
import hmac
import json
import time

import pytest

from conftest import SCOPE_SECRETS, TOKEN
from helpers import credentials, oauth
from mcp_client import PROTOCOL_VERSION, McpSession
from test_auth import REDIRECT_URI, authorize, code_from, pkce_pair

ROUTES = ["scanr", "match", "rag", "tableaux"]


def open_route(http, route: str, token: str):
    """POST an MCP initialize on a route: 200 when the token may use it."""
    return McpSession(http, f"/{route}", token).post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
        }
    )


def dynamic_client_tokens(http, secret: str) -> dict:
    """OAuth tokens for a dynamically registered client whose user typed `secret` on the consent page."""
    client_id = http.post("/register", json={"redirect_uris": [REDIRECT_URI]}).json()["client_id"]
    verifier, challenge = pkce_pair()
    code = code_from(authorize(http, client_id, challenge, token=secret))
    response = http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    return {"client_id": client_id, **response.json()}


def client_credentials_token(http, client_id: str, secret: str):
    return http.post("/token", data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret})


@pytest.mark.parametrize("route", ROUTES)
def test_a_scope_credential_reaches_only_its_route(http, upstream, route):
    assert open_route(http, route, SCOPE_SECRETS[route]).status_code == 200
    other = next(r for r in ROUTES if r != route)
    response = open_route(http, other, SCOPE_SECRETS[route])
    assert response.status_code == 403
    assert response.headers["www-authenticate"] == f'Bearer error="insufficient_scope", scope="{other}"'


@pytest.mark.parametrize("route", ROUTES)
def test_the_admin_reaches_every_route(http, upstream, route):
    assert open_route(http, route, TOKEN).status_code == 200


def test_dynamic_client_gets_the_scope_of_the_secret_typed_on_the_consent_page(http, upstream):
    tokens = dynamic_client_tokens(http, SCOPE_SECRETS["scanr"])
    assert open_route(http, "scanr", tokens["access_token"]).status_code == 200
    assert open_route(http, "tableaux", tokens["access_token"]).status_code == 403


def test_preconfigured_client_uses_the_scope_as_client_id_and_its_secret(http, upstream):
    token = client_credentials_token(http, "scanr", SCOPE_SECRETS["scanr"]).json()["access_token"]
    assert open_route(http, "scanr", token).status_code == 200
    assert open_route(http, "match", token).status_code == 403


@pytest.mark.parametrize(
    ("client_id", "secret", "status"),
    [
        ("scanr", SCOPE_SECRETS["match"], 401),
        ("scanr", TOKEN, 401),
        ("unknown-client", SCOPE_SECRETS["scanr"], 400),
    ],
)
def test_preconfigured_client_is_refused_without_its_own_secret(http, client_id, secret, status):
    assert client_credentials_token(http, client_id, secret).status_code == status


def test_consent_page_lists_only_the_route_of_the_credential(http):
    _, challenge = pkce_pair()
    page = http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "scanr",
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    ).text
    assert "scanR" in page
    assert "tableaux" not in page
    assert "affiliation matcher" not in page


def test_removing_a_credential_revokes_its_tokens(http, upstream, monkeypatch):
    tokens = dynamic_client_tokens(http, SCOPE_SECRETS["scanr"])
    assert open_route(http, "scanr", tokens["access_token"]).status_code == 200

    monkeypatch.setattr(credentials, "CREDENTIALS", {k: v for k, v in credentials.CREDENTIALS.items() if k != "scanr"})

    assert open_route(http, "scanr", tokens["access_token"]).status_code == 401
    refreshed = http.post(
        "/token",
        data={"grant_type": "refresh_token", "client_id": tokens["client_id"], "refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 400
    assert refreshed.json()["error"] == "invalid_grant"


def test_tokens_issued_before_credentials_existed_belong_to_the_admin(http, upstream):
    legacy = oauth._sign({"typ": "access", "exp": time.time() + 60, "client_id": "dataesr"})
    assert open_route(http, "tableaux", legacy).status_code == 200


def test_a_credential_secret_cannot_forge_oauth_tokens(http, upstream):
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    body = b64(json.dumps({"typ": "access", "exp": time.time() + 60, "cred": "admin"}).encode())
    forged = f"{body}.{b64(hmac.new(TOKEN.encode(), body.encode(), hashlib.sha256).digest())}"
    assert open_route(http, "tableaux", forged).status_code == 401


def test_without_secrets_no_credential_exists():
    assert credentials.load({}) == {}


def test_the_admin_credential_is_valid_on_every_route():
    loaded = credentials.load({"MCP_AUTH_TOKEN": "x"})
    assert list(loaded) == ["admin"]
    assert loaded["admin"].routes() == ROUTES


def test_each_scope_secret_gives_a_credential_for_that_route_only():
    loaded = credentials.load({"MCP_TOKEN_RAG": "r", "MCP_TOKEN_TABLEAUX": "t"})
    assert loaded["rag"].routes() == ["rag"]
    assert loaded["tableaux"].routes() == ["tableaux"]
    assert loaded["rag"].matches("r")
    assert not loaded["rag"].matches("t")
