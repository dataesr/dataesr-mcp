"""Minimal stateless OAuth 2.1 authorization server (PKCE + dynamic client registration).

Clients, codes and tokens are HMAC-signed with MCP_AUTH_TOKEN, so nothing is stored
and tokens survive restarts. The resource owner authorizes by entering MCP_AUTH_TOKEN.
"""

import base64
import hashlib
import hmac
import html
import json
import os
import time
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

SECRET = os.environ["MCP_AUTH_TOKEN"]
PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "").rstrip("/")

CODE_TTL = 300
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600

PUBLIC_PREFIXES = ("/.well-known/", "/register", "/authorize", "/token")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = _b64(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def _verify(value: str, kind: str) -> dict | None:
    try:
        body, mac = value.split(".")
        expected = _b64(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(mac, expected):
            return None
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if payload.get("typ") != kind:
        return None
    if "exp" in payload and payload["exp"] < time.time():
        return None
    return payload


def is_valid_access_token(token: str) -> bool:
    return _verify(token, "access") is not None


def is_public_path(path: str) -> bool:
    return path.startswith(PUBLIC_PREFIXES)


def base_url(request: Request) -> str:
    if PUBLIC_URL:
        return PUBLIC_URL
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}"


def _oauth_error(error: str, description: str = "", status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status)


async def protected_resource_metadata(request: Request) -> Response:
    base = base_url(request)
    suffix = request.path_params.get("resource", "")
    return JSONResponse(
        {
            "resource": f"{base}/{suffix}".rstrip("/"),
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
        }
    )


async def authorization_server_metadata(request: Request) -> Response:
    base = base_url(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "registration_endpoint": f"{base}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        }
    )


async def register(request: Request) -> Response:
    try:
        data = await request.json()
        redirect_uris = data["redirect_uris"]
        assert isinstance(redirect_uris, list) and redirect_uris
        assert all(isinstance(u, str) for u in redirect_uris)
    except Exception:
        return _oauth_error("invalid_client_metadata", "redirect_uris is required")
    client_id = _sign({"typ": "client", "redirect_uris": redirect_uris})
    return JSONResponse(
        {
            "client_id": client_id,
            "client_name": data.get("client_name"),
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


def _render_form(params: dict, error: str = "") -> HTMLResponse:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in params.items()
    )
    err = f'<p style="color:#b00">{html.escape(error)}</p>' if error else ""
    page = (
        "<!doctype html><html><head><meta charset='utf-8'><title>dataesr-mcp</title></head>"
        "<body style='font-family:sans-serif;max-width:420px;margin:4em auto'>"
        "<h2>Authorize access to dataesr-mcp</h2>"
        f"{err}<form method='post'>{hidden}"
        "<label>Access token<br><input type='password' name='token' autofocus required style='width:100%'></label>"
        "<p><button type='submit'>Authorize</button></p></form></body></html>"
    )
    return HTMLResponse(page, status_code=401 if error else 200)


_AUTH_FIELDS = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state")


async def authorize(request: Request) -> Response:
    source = request.query_params if request.method == "GET" else await request.form()
    params = {k: str(source.get(k, "")) for k in _AUTH_FIELDS}

    client = _verify(params["client_id"], "client")
    if not client or params["redirect_uri"] not in client["redirect_uris"]:
        return HTMLResponse("Invalid client_id or redirect_uri", status_code=400)

    def redirect_error(error: str) -> Response:
        query = {"error": error}
        if params["state"]:
            query["state"] = params["state"]
        return RedirectResponse(f"{params['redirect_uri']}?{urlencode(query)}", status_code=302)

    if params["response_type"] != "code":
        return redirect_error("unsupported_response_type")
    if not params["code_challenge"] or params["code_challenge_method"] != "S256":
        return redirect_error("invalid_request")

    if request.method == "GET":
        return _render_form(params)

    if not hmac.compare_digest(str(source.get("token", "")), SECRET):
        return _render_form(params, "Invalid token")

    code = _sign(
        {
            "typ": "code",
            "exp": time.time() + CODE_TTL,
            "client_id": params["client_id"],
            "redirect_uri": params["redirect_uri"],
            "challenge": params["code_challenge"],
        }
    )
    query = {"code": code}
    if params["state"]:
        query["state"] = params["state"]
    separator = "&" if "?" in params["redirect_uri"] else "?"
    return RedirectResponse(f"{params['redirect_uri']}{separator}{urlencode(query)}", status_code=302)


def _issue_tokens(client_id: str) -> JSONResponse:
    now = time.time()
    return JSONResponse(
        {
            "access_token": _sign({"typ": "access", "exp": now + ACCESS_TTL, "client_id": client_id}),
            "token_type": "Bearer",
            "expires_in": ACCESS_TTL,
            "refresh_token": _sign({"typ": "refresh", "exp": now + REFRESH_TTL, "client_id": client_id}),
        },
        headers={"Cache-Control": "no-store"},
    )


async def token(request: Request) -> Response:
    form = await request.form()
    grant = form.get("grant_type")
    client_id = str(form.get("client_id", ""))

    if grant == "authorization_code":
        code = _verify(str(form.get("code", "")), "code")
        if not code or code["client_id"] != client_id:
            return _oauth_error("invalid_grant", "invalid or expired code")
        if str(form.get("redirect_uri", "")) != code["redirect_uri"]:
            return _oauth_error("invalid_grant", "redirect_uri mismatch")
        challenge = _b64(hashlib.sha256(str(form.get("code_verifier", "")).encode()).digest())
        if not hmac.compare_digest(challenge, code["challenge"]):
            return _oauth_error("invalid_grant", "PKCE verification failed")
        return _issue_tokens(client_id)

    if grant == "refresh_token":
        refresh = _verify(str(form.get("refresh_token", "")), "refresh")
        if not refresh or (client_id and refresh["client_id"] != client_id):
            return _oauth_error("invalid_grant", "invalid or expired refresh token")
        return _issue_tokens(refresh["client_id"])

    return _oauth_error("unsupported_grant_type")


routes = [
    Route("/.well-known/oauth-protected-resource", protected_resource_metadata),
    Route("/.well-known/oauth-protected-resource/{resource:path}", protected_resource_metadata),
    Route("/.well-known/oauth-authorization-server", authorization_server_metadata),
    Route("/.well-known/oauth-authorization-server/{resource:path}", authorization_server_metadata),
    Route("/register", register, methods=["POST"]),
    Route("/authorize", authorize, methods=["GET", "POST"]),
    Route("/token", token, methods=["POST"]),
]
