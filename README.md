# dataesr-mcp

Model Context Protocol (MCP) server for interacting with dataesr resources.

## Features

- **scanR**: Search across multiple scanR indexes (publications, persons, organizations, projects, participations, patents)
- **Affiliation Matcher**: Match affiliation strings against reference systems (ROR, GRID, RNSR, etc.)
- **Flash RAG**: Retrieve relevant documents from French Ministry of Higher Education and Research publications
- **Tableaux prototyping**: work in progress

The tools of each route (`/scanr`, `/match`, `/rag`, `/tableaux`), with example questions, arguments and responses, are described in [docs/tools.md](docs/tools.md).

## Authentication

All MCP endpoints require a bearer token: either a credential secret used directly, or an OAuth 2.1 access token (authorization code + PKCE, refresh tokens, `client_credentials`) obtained with one.

### OAuth clients (e.g. Claude)

Two ways to connect an OAuth client:

- **Pre-configured client** (recommended): in the connector's advanced settings, set **OAuth Client ID** to the route name (`scanr`, `match`, `rag` or `tableaux`) and **OAuth Client Secret** to the matching token value. The user then only clicks "Allow" on the consent page, which lists the routes the credential gives access to.
- **Dynamic registration**: the client registers itself, and the user types a credential secret on the consent page. The resulting tokens have that credential's route.


## Setup

### Connect an AI assistant

You can use these tools from an AI assistant that supports custom connectors (for example Claude, ChatGPT or Mistral Le Chat), without installing anything. The menu names below may change depending on the assistant and its version.

**What you need**
- The server address, for example `https://mcp.staging.dataesr.ovh/` (ask the dataesr team for the address to use).
- Access to a route: `scanr`, `match`, `rag` or `tableaux`. Ask the dataesr team for a credential for the route(s) you need.

**Steps**
1. Open your assistant's settings and find the section for connectors, apps or integrations (for example *Settings > Connectors > Add custom connector* in Claude).
2. Add a custom connector and enter the route URL, which is the server address followed by the route name, for example `https://mcp.staging.dataesr.ovh/scanr`.
3. If the assistant asks for OAuth details, use the pre-configured client described in [OAuth clients](#oauth-clients-eg-claude): the client ID is the route name (`scanr`, `match`, `rag` or `tableaux`) and the client secret is the credential you received. Then click *Allow* on the consent page.
4. If the assistant does not ask for OAuth details, it may only accept a bearer token. In that case, enter the credential you received as the token, if the assistant offers that option.
5. Start a new conversation and ask a question, for example: *"Search scanR for publications from Université de Lyon in 2023."* The assistant should show that it is calling a dataesr tool.

**Troubleshooting**
- *Authentication failed*: check that the client ID is the route name and that the secret is copied without extra spaces.
- *The assistant does not see any tool*: remove the connector, add it again with the exact URL, then start a new conversation.
- *Access denied for a route*: your credential does not include that route. Ask the dataesr team for one that does.


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

## Inspect

Start MCP Inspector:
```bash
npx -y @modelcontextprotocol/inspector
```

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
