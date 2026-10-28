"""Minimal stateless OAuth 2.1 authorization server (PKCE + dynamic client registration).

Clients, codes and tokens are HMAC-signed with MCP_AUTH_TOKEN, so nothing is stored
and tokens survive restarts.

Two kinds of clients are supported:
- a pre-configured client: client_id MCP_OAUTH_CLIENT_ID (default "dataesr"),
  client_secret MCP_AUTH_TOKEN. Users only click "Allow" on the consent page.
- dynamically registered clients (no secret): the user must type MCP_AUTH_TOKEN on the consent page.
"""

import base64
import hashlib
import hmac
import html
import json
import os
import time
from urllib.parse import unquote_plus, urlencode, urlparse

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

SECRET = os.environ["MCP_AUTH_TOKEN"]
PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "").rstrip("/")
STATIC_CLIENT_ID = os.environ.get("MCP_OAUTH_CLIENT_ID", "dataesr")

CODE_TTL = 300
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600

PUBLIC_PREFIXES = ("/.well-known/", "/register", "/authorize", "/token", "/favicon.ico")


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
            "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
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
    name = str(data.get("client_name") or "")[:80]
    client_id = _sign({"typ": "client", "redirect_uris": redirect_uris, "name": name})
    return JSONResponse(
        {
            "client_id": client_id,
            "client_name": name or None,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Authorize - dataesr-mcp</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#f3f4f8;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#1b1b35}
.card{background:#fff;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.08);padding:32px;width:100%;max-width:420px;margin:16px}
h1{font-size:1.3rem;margin:0 0 4px}.sub{color:#555;margin:0 0 20px;font-size:.95rem}
.box{background:#f3f4f8;border-radius:8px;padding:12px 14px;margin-bottom:20px;font-size:.9rem;word-break:break-all}
.box b{display:block;font-size:.75rem;text-transform:uppercase;color:#666;margin-bottom:2px}
label{display:block;font-weight:600;font-size:.9rem;margin-bottom:6px}
.pw{display:flex;gap:8px;margin-bottom:16px}
input[type=password],input[type=text]{flex:1;padding:10px 12px;border:1px solid #c5c7d4;border-radius:8px;font-size:1rem}
input:focus{outline:2px solid #000091;border-color:#000091}
button{cursor:pointer;border-radius:8px;font-size:1rem;padding:10px 16px;border:1px solid #000091}
.primary{background:#000091;color:#fff;width:100%}.primary:hover{background:#1212ff}
.secondary{background:#fff;color:#000091}.row{display:flex;gap:8px}.row .primary{flex:2}.row .secondary{flex:1}
.err{background:#fde8e8;color:#9b1c1c;border-radius:8px;padding:10px 12px;margin-bottom:16px;font-size:.9rem}
.foot{margin:16px 0 0;font-size:.8rem;color:#777}
</style></head><body><main class="card">
<h1>Authorize access</h1>
<p class="sub"><b>__NAME__</b> wants to use the dataesr MCP tools (scanR, affiliation matcher, RAG, tableaux).</p>
<div class="box"><b>Will return to</b>__HOST__</div>
__ERR__
<form method="post">__HIDDEN__
__FIELD__
</form>
<p class="foot">Only continue if you started this connection yourself.</p>
</main>
<script>
var t=document.getElementById("t"),s=document.getElementById("show");
if(s)s.onclick=function(){t.type=t.type==="password"?"text":"password";s.textContent=t.type==="password"?"Show":"Hide"};
</script></body></html>"""

_TOKEN_FIELD = (
    '<label for="t">Access token</label><div class="pw">'
    '<input id="t" type="password" name="token" autocomplete="current-password" autofocus required>'
    '<button type="button" id="show" class="secondary">Show</button></div>'
    '<button type="submit" class="primary" name="action" value="allow">Authorize</button>'
)
_CONFIRM_FIELD = (
    '<div class="row"><button type="submit" class="secondary" name="action" value="deny">Deny</button>'
    '<button type="submit" class="primary" name="action" value="allow" autofocus>Allow</button></div>'
)


def _render_form(params: dict, client: dict, error: str = "") -> HTMLResponse:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in params.items()
    )
    host = urlparse(params["redirect_uri"]).netloc or params["redirect_uri"]
    page = (
        _PAGE.replace("__NAME__", html.escape(client["name"] or host))
        .replace("__HOST__", html.escape(host))
        .replace("__ERR__", f'<div class="err">{html.escape(error)}</div>' if error else "")
        .replace("__HIDDEN__", hidden)
        .replace("__FIELD__", _CONFIRM_FIELD if client["static"] else _TOKEN_FIELD)
    )
    return HTMLResponse(page, status_code=401 if error else 200)


def _get_client(client_id: str, redirect_uri: str) -> dict | None:
    if hmac.compare_digest(client_id, STATIC_CLIENT_ID):
        # The client_secret is required at the token endpoint, so any secure redirect is safe.
        parsed = urlparse(redirect_uri)
        local = parsed.hostname in ("localhost", "127.0.0.1")
        if parsed.scheme == "https" or (parsed.scheme == "http" and local):
            return {"static": True, "name": ""}
        return None
    client = _verify(client_id, "client")
    if client and redirect_uri in client["redirect_uris"]:
        return {"static": False, "name": client.get("name", "")}
    return None


_AUTH_FIELDS = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state")


async def authorize(request: Request) -> Response:
    source = request.query_params if request.method == "GET" else await request.form()
    params = {k: str(source.get(k, "")) for k in _AUTH_FIELDS}

    client = _get_client(params["client_id"], params["redirect_uri"])
    if not client:
        return HTMLResponse("Invalid client_id or redirect_uri", status_code=400)

    def redirect(query: dict) -> Response:
        if params["state"]:
            query["state"] = params["state"]
        separator = "&" if "?" in params["redirect_uri"] else "?"
        return RedirectResponse(f"{params['redirect_uri']}{separator}{urlencode(query)}", status_code=302)

    if params["response_type"] != "code":
        return redirect({"error": "unsupported_response_type"})
    if not params["code_challenge"] or params["code_challenge_method"] != "S256":
        return redirect({"error": "invalid_request"})

    if request.method == "GET":
        return _render_form(params, client)

    if source.get("action") == "deny":
        return redirect({"error": "access_denied"})
    if not client["static"] and not hmac.compare_digest(str(source.get("token", "")), SECRET):
        return _render_form(params, client, "Invalid token, please try again.")

    code = _sign(
        {
            "typ": "code",
            "exp": time.time() + CODE_TTL,
            "client_id": params["client_id"],
            "redirect_uri": params["redirect_uri"],
            "challenge": params["code_challenge"],
        }
    )
    return redirect({"code": code})


def _issue_tokens(client_id: str, refresh: bool = True) -> JSONResponse:
    now = time.time()
    body = {
        "access_token": _sign({"typ": "access", "exp": now + ACCESS_TTL, "client_id": client_id}),
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
    }
    if refresh:
        body["refresh_token"] = _sign({"typ": "refresh", "exp": now + REFRESH_TTL, "client_id": client_id})
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


def _client_credentials(request: Request, form) -> tuple[str, str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            cid, _, secret = base64.b64decode(header[6:]).decode().partition(":")
            return unquote_plus(cid), unquote_plus(secret)
        except Exception:
            return "", ""
    return str(form.get("client_id", "")), str(form.get("client_secret", ""))


async def token(request: Request) -> Response:
    form = await request.form()
    grant = form.get("grant_type")
    client_id, client_secret = _client_credentials(request, form)

    is_static = hmac.compare_digest(client_id, STATIC_CLIENT_ID)
    if is_static and not hmac.compare_digest(client_secret, SECRET):
        return _oauth_error("invalid_client", "invalid client_secret", 401)

    if grant == "client_credentials":
        if not is_static:
            return _oauth_error("unauthorized_client")
        return _issue_tokens(client_id, refresh=False)

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
        if not refresh or refresh["client_id"] != client_id:
            return _oauth_error("invalid_grant", "invalid or expired refresh token")
        return _issue_tokens(client_id)

    return _oauth_error("unsupported_grant_type")


async def favicon(request: Request) -> Response:
    return Response(status_code=204)


routes = [
    Route("/.well-known/oauth-protected-resource", protected_resource_metadata),
    Route("/.well-known/oauth-protected-resource/{resource:path}", protected_resource_metadata),
    Route("/.well-known/oauth-authorization-server", authorization_server_metadata),
    Route("/.well-known/oauth-authorization-server/{resource:path}", authorization_server_metadata),
    Route("/register", register, methods=["POST"]),
    Route("/authorize", authorize, methods=["GET", "POST"]),
    Route("/token", token, methods=["POST"]),
    Route("/favicon.ico", favicon),
]
