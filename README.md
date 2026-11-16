# dataesr-mcp

Model Context Protocol (MCP) server for interacting with dataesr resources.

## Features

- **scanR**: Search across multiple scanR indexes (publications, persons, organizations, projects, participations, patents)
- **Affiliation Matcher**: Match affiliation strings against reference systems (ROR, GRID, RNSR, etc.)
- **Flash RAG**: Retrieve relevant documents from French Ministry of Higher Education and Research publications
- **Tableaux prototyping**: Serve the dashboard prototyping guidance of `dataesr/tableaux` (AGENTS.md files, README, skills), its board templates and data-source index, and validate a dashboard manifest against the repository's JSON Schema, without executing generated code.

The tableaux tools are registered at `/tableaux` and will be available after the service is deployed (using the same authentication as the other mounted MCP servers): `list_guidance`, `get_guidance`, `list_templates`, `get_template`, `list_data_sources`, `get_data_source_guide`, `list_dashboard_components`, `list_chart_examples`, `list_existing_boards`, `recommend_architecture`, `validate_dashboard_spec`, and `validate_board_bundle`.

Nothing about the tableaux conventions is stored in this repository. Each call reads the current files from GitHub through the contents API (cached for 5 minutes), starting from the index `docs/dashboard-prototype/prototype.index.json`, which lists the guidance documents, template paths, components and data sources. Change the content in `dataesr/tableaux`, not here. Configuration (environment variables):

| Variable | Default | Purpose |
| --- | --- | --- |
| `TABLEAUX_REPO` | `dataesr/tableaux` | Repository to read |
| `TABLEAUX_REF` | `staging` | Branch, tag, or commit to read |
| `TABLEAUX_PROTOTYPE_INDEX_PATH` | `docs/dashboard-prototype/prototype.index.json` | Location of the index in the repository |
| `GITHUB_TOKEN` | unset | Optional read-only token; raises the GitHub rate limit (60 requests/hour unauthenticated) and is required for a private repository |

`validate_dashboard_spec` checks the manifest against the repository's schema plus the rules JSON Schema cannot express (route paths belong to the board, data source ids exist in the index, duplicate routes), and warns on a board-id collision or a self-declared preview owner. `validate_board_bundle` runs static checks on a board's files in the repository (router mounted, folder names match the board id, `.http` tests present, no hard-coded hex colors, no browser `/elasticsearch` call or fixture import). Neither validates, builds, or runs a submitted project. Do not execute generated code in the MCP service; isolated project validation requires a separately deployed sandbox.

Chat workflow gap: these tools plan and validate but cannot produce a board file bundle from chat. A `scaffold_board(id, routes)` tool returning a bundle to import is a candidate future addition; it is not implemented.

## Authentication

All MCP endpoints require a bearer token: either a credential secret used directly, or an OAuth 2.1 access token (authorization code + PKCE, refresh tokens, `client_credentials`) obtained with one.

### Credentials and routes

Each route has its own credential, and the admin credential works on every route. A credential that calls a route outside its scope gets `403 insufficient_scope`.

| Credential | Secret (environment variable) | Routes |
| --- | --- | --- |
| scanR | `MCP_TOKEN_SCANR` | `/scanr` |
| Affiliation matcher | `MCP_TOKEN_MATCH` | `/match` |
| RAG | `MCP_TOKEN_RAG` | `/rag` |
| Tableaux | `MCP_TOKEN_TABLEAUX` | `/tableaux` |
| Admin | `MCP_AUTH_TOKEN` | all |

A secret is used directly as a bearer token, or as the OAuth client secret of the credential (see below). Set only the secrets you want to hand out. The configuration is read at startup: after removing or changing a secret, restart the server. OAuth tokens carry the credential id, which is checked again on each request, so removing a credential also stops its existing tokens.

### OAuth clients (e.g. Claude)

Tokens are HMAC-signed with `MCP_SIGNING_KEY` (`MCP_AUTH_TOKEN` when unset); nothing is stored, and changing the key revokes every OAuth token. Set `MCP_SIGNING_KEY` to a value different from every credential secret.

Two ways to connect an OAuth client:

- **Pre-configured client** (recommended): in the connector's advanced settings, set **OAuth Client ID** to the route name (`scanr`, `match`, `rag` or `tableaux`) and **OAuth Client Secret** to the matching `MCP_TOKEN_*` value. For the admin credential, the client id is `MCP_OAUTH_CLIENT_ID` (default `dataesr`) and the secret is `MCP_AUTH_TOKEN`. The user then only clicks "Allow" on the consent page, which lists the routes the credential gives access to.
- **Dynamic registration**: the client registers itself, and the user types a credential secret on the consent page. The resulting tokens have that credential's route.

Set `MCP_PUBLIC_URL` (e.g. `https://mcp.example.org`) if the server is behind a proxy that doesn't forward `Host`/`X-Forwarded-*` headers.

## Configuration

The server reads its configuration from environment variables (a local `.env` file is used by `docker-compose` and `--env-file`).

| Variable | Required | Purpose |
| --- | --- | --- |
| `MCP_AUTH_TOKEN` | one of `MCP_AUTH_TOKEN` / `MCP_SIGNING_KEY` | Secret of the `admin` credential (all routes) |
| `MCP_SIGNING_KEY` | one of `MCP_AUTH_TOKEN` / `MCP_SIGNING_KEY` | HMAC key signing OAuth clients, codes and tokens; defaults to `MCP_AUTH_TOKEN` |
| `MCP_TOKEN_SCANR` / `MCP_TOKEN_MATCH` / `MCP_TOKEN_RAG` / `MCP_TOKEN_TABLEAUX` | no | Secret of the credential limited to that route (see Authentication) |
| `MCP_OAUTH_CLIENT_ID` | no (default `dataesr`) | OAuth client ID of the admin credential |
| `MCP_PUBLIC_URL` | no | Public base URL, when behind a proxy that doesn't forward `Host`/`X-Forwarded-*` |
| `ES_URL` | scanR | Elasticsearch base URL hosting the `scanr-*` indexes |
| `ES_API_KEY` | no | Value sent in the `Authorization` header to Elasticsearch |
| `SCANR_SCHEMAS_URL` | scanR | Base URL of the `<index>.yaml` schema files |
| `AFFILIATION_MATCHER_URL` | affiliation matcher | Affiliation matcher endpoint |
| `CATALOGUE_API_URL` | RAG | Catalogue API base URL |
| `CATALOGUE_API_KEY` | RAG | Value sent in the `Authorization` header to the catalogue API |

The `TABLEAUX_*` and `GITHUB_TOKEN` variables are described in the tableaux section above.

## Setup

### Prerequisites
- Python 3.12+
- Docker (optional)

### Local Development

```bash
# Install dependencies
uv sync

# Create a .env file with the variables listed in Configuration

# Run server
uv run main.py
```

### Docker

```bash
# Build and run
make build
docker run -p 8000:8000 --env-file .env dataesr/dataesr-mcp:latest

# Or using docker-compose
docker-compose up
```

## Usage

Start MCP Inspector:
```bash
npx -y @modelcontextprotocol/inspector
```

The tools of each route (`/scanr`, `/match`, `/rag`, `/tableaux`), with example questions, arguments and responses, are described in [docs/tools.md](docs/tools.md).

## Tests

```bash
make test   # uv run --group dev pytest
```

The tests in [tests/](tests) run the real application and mock every upstream service (Elasticsearch, schema files, affiliation matcher, catalogue API, GitHub), so they need no credentials or network. Each route has a test file (`test_scanr.py`, `test_match.py`, `test_rag.py`, `test_tableaux.py`) that goes through the MCP protocol with `tests/mcp_client.py`: `initialize`, `tools/list`, `tools/call`. `test_auth.py` covers the bearer token and the OAuth flows.

## Deployment

The staging deployment is automated via GitHub Actions.

Or manually:
```bash
# Build and push
make build
make push
```
