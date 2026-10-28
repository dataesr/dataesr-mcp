# dataesr-mcp

Model Context Protocol (MCP) server for interacting with dataesr resources.

## Features

- **scanR**: Search across multiple scanR indexes (publications, persons, organizations, projects, participations, patents)
- **Affiliation Matcher**: Match affiliation strings against reference systems (ROR, GRID, RNSR, etc.)
- **Flash RAG**: Retrieve relevant documents from French Ministry of Higher Education and Research publications
- **Tableaux prototyping**: Serve the dashboard prototyping guidance of `dataesr/tableaux` (AGENTS.md files, README, skills), its board templates and data-source index, and validate a dashboard manifest against the repository's JSON Schema, without executing generated code.

The tableaux tools are registered at `/tableaux` and will be available after the service is deployed (using the same authentication as the other mounted MCP servers): `list_guidance`, `get_guidance`, `list_templates`, `get_template`, `list_data_sources`, `get_data_source_guide`, `list_dashboard_components`, `recommend_architecture`, and `validate_dashboard_spec`.

Nothing about the tableaux conventions is stored in this repository. Each call reads the current files from GitHub through the contents API (cached for 5 minutes), starting from the index `docs/dashboard-prototype/prototype.index.json`, which lists the guidance documents, template paths, components and data sources. Change the content in `dataesr/tableaux`, not here. Configuration (environment variables):

| Variable | Default | Purpose |
| --- | --- | --- |
| `TABLEAUX_REPO` | `dataesr/tableaux` | Repository to read |
| `TABLEAUX_REF` | `staging` | Branch, tag, or commit to read |
| `TABLEAUX_PROTOTYPE_INDEX_PATH` | `docs/dashboard-prototype/prototype.index.json` | Location of the index in the repository |
| `GITHUB_TOKEN` | unset | Optional read-only token; raises the GitHub rate limit (60 requests/hour unauthenticated) and is required for a private repository |

`validate_dashboard_spec` checks the manifest against the repository's schema plus the rules JSON Schema cannot express (route paths belong to the board, data source ids exist in the index). It does not validate, build, or run a submitted project. Do not execute generated code in the MCP service; isolated project validation requires a separately deployed sandbox.
## Setup

### Prerequisites
- Python 3.12+
- Docker (optional)

### Local Development

```bash
# Install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your credentials

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

## Deployment

The staging deployment is automated via GitHub Actions.

Or manually:
```bash
# Build and push
make build
make push
```
