"""Authentication: static bearer token and the OAuth 2.1 flows (dynamic client, pre-configured client)."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import TOKEN
from mcp_client import McpSession

REDIRECT_URI = "https://client.test/callback"
ROUTES = ["/scanr", "/match", "/rag", "/tableaux"]


def pkce_pair(verifier: str = "v" * 64) -> tuple[str, str]:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize(http, client_id: str, challenge: str, **form):
    return http.post(
        "/authorize",
        data={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "action": "allow",
            **form,
        },
        follow_redirects=False,
    )


def code_from(response) -> str:
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["state"] == ["xyz"]
    return query["code"][0]


@pytest.mark.parametrize("route", ROUTES)
def test_static_token_opens_every_route(connect, route):
    assert connect(route).tool_names()


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_missing_or_wrong_token_is_rejected(http, token):
    response = McpSession(http, "/scanr", token).post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
    assert 'resource_metadata="https://mcp.test/.well-known/oauth-protected-resource/scanr"' in response.headers["www-authenticate"]


def test_discovery_documents_are_public(http):
    resource = http.get("/.well-known/oauth-protected-resource/scanr").json()
    assert resource["resource"] == "https://mcp.test/scanr"
    server = http.get("/.well-known/oauth-authorization-server").json()
    assert server["token_endpoint"] == "https://mcp.test/token"
    assert "S256" in server["code_challenge_methods_supported"]


def test_dynamic_client_authorization_code_flow(http, connect):
    registration = http.post("/register", json={"redirect_uris": [REDIRECT_URI], "client_name": "Example"})
    assert registration.status_code == 201
    client_id = registration.json()["client_id"]
    verifier, challenge = pkce_pair()

    # A dynamic client has no secret: the user proves access by typing the token on the consent page.
    assert authorize(http, client_id, challenge, token="wrong-token").status_code == 401
    code = code_from(authorize(http, client_id, challenge, token=TOKEN))

    tokens = http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    ).json()
    assert tokens["token_type"] == "Bearer"
    assert connect("/scanr", tokens["access_token"]).tool_names()

    refreshed = http.post(
        "/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens["refresh_token"]}
    ).json()
    assert connect("/match", refreshed["access_token"]).tool_names()


def test_authorization_code_requires_the_pkce_verifier(http):
    client_id = http.post("/register", json={"redirect_uris": [REDIRECT_URI]}).json()["client_id"]
    _, challenge = pkce_pair()
    code = code_from(authorize(http, client_id, challenge, token=TOKEN))
    response = http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": "not-the-verifier",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_preconfigured_client_confirms_without_typing_the_token(http, connect):
    verifier, challenge = pkce_pair()
    # No `token` field: only the client_secret, checked at the token endpoint, authenticates the client.
    code = code_from(authorize(http, "dataesr", challenge))
    tokens = http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "dataesr",
            "client_secret": TOKEN,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    ).json()
    assert connect("/rag", tokens["access_token"]).tool_names()


def test_client_credentials_grant(http, connect):
    response = http.post(
        "/token", data={"grant_type": "client_credentials", "client_id": "dataesr", "client_secret": TOKEN}
    )
    assert response.status_code == 200
    assert "refresh_token" not in response.json()
    assert connect("/tableaux", response.json()["access_token"]).tool_names()

    wrong = http.post("/token", data={"grant_type": "client_credentials", "client_id": "dataesr", "client_secret": "nope"})
    assert wrong.status_code == 401
