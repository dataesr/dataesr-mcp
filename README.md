# dataesr-mcp

Model Context Protocol (MCP) server for interacting with dataesr resources.

## Features

- **scanR**: Search across multiple scanR indexes (publications, persons, organizations, projects, participations, patents)
- **Affiliation Matcher**: Match affiliation strings against reference systems (ROR, GRID, RNSR, etc.)
- **Flash RAG**: Retrieve relevant documents from French Ministry of Higher Education and Research publications

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
