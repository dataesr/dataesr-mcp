"""Dashboard prototyping tools backed by the tableaux repository."""

import json
import os
from jsonschema import Draft202012Validator
from pydantic import Field
from tools.tableaux.repository import GitHubRepo, RepoError

INDEX_PATH = os.environ.get("TABLEAUX_PROTOTYPE_INDEX_PATH", "docs/dashboard-prototype/prototype.index.json")
SCHEMA_TEMPLATE_ID = "manifest-schema"

repository = GitHubRepo()


async def load_index(repo) -> dict:
    try:
        return json.loads(await repo.get_file(INDEX_PATH))
    except json.JSONDecodeError as error:
        raise RepoError(f"{INDEX_PATH} is not valid JSON: {error}") from error


def _find(entries: list[dict], entry_id: str, kind: str) -> dict:
    for entry in entries:
        if entry["id"] == entry_id:
            return entry
    known = ", ".join(entry["id"] for entry in entries)
    raise RepoError(f"Unknown {kind} {entry_id!r}. Known: {known}")


def _source(repo) -> dict:
    return {"repository": repo.repo, "ref": repo.ref}


async def guidance_index(repo) -> dict:
    index = await load_index(repo)
    return {**_source(repo), "guidance": index["guidance"]}


async def guidance_document(repo, guidance_id: str) -> dict:
    index = await load_index(repo)
    entry = _find(index["guidance"], guidance_id, "guidance")
    return {**_source(repo), **entry, "content": await repo.get_file(entry["path"])}


async def template_index(repo) -> dict:
    index = await load_index(repo)
    return {**_source(repo), "templates": index["templates"]}


async def _template_files(repo, template: dict) -> dict[str, str]:
    paths: list[str] = []
    for path in template["paths"]:
        paths.extend(await repo.list_files(path) if path.endswith("/") else [path])
    return {path: await repo.get_file(path) for path in dict.fromkeys(paths)}


async def template_bundle(repo, template_id: str) -> dict:
    index = await load_index(repo)
    template = _find(index["templates"], template_id, "template")
    return {
        **_source(repo),
        "id": template["id"],
        "title": template["title"],
        "description": template["description"],
        "files": await _template_files(repo, template),
    }


async def data_source_index(repo) -> dict:
    index = await load_index(repo)
    return {**_source(repo), "data_sources": index["data_sources"]}


async def data_source_guide(repo, source_id: str) -> dict:
    index = await load_index(repo)
    return {**_source(repo), **_find(index["data_sources"], source_id, "data source")}


async def component_index(repo) -> dict:
    index = await load_index(repo)
    return {**_source(repo), "components": index["components"]}


async def recommendation(repo, data_sources: list[str]) -> dict:
    index = await load_index(repo)
    sources = [_find(index["data_sources"], s, "data source") for s in data_sources]
    pending = [s["id"] for s in sources if s["status"] != "allowed"]
    return {
        **_source(repo),
        "data_mode": "fixtures",
        "pending_approvals": pending,
        "requires_human_decision": bool(pending),
        "reason": (
            "Every board has its own server routes serving fixtures by default; the browser "
            "calls only those routes. A real source replaces the fixtures only after its owner "
            "approves it, without changing the route contract. See the 'prototyping' guidance."
        ),
    }


async def validation(repo, spec: dict) -> dict:
    """Validate a manifest against the repository's schema; never runs project code."""
    index = await load_index(repo)
    schema_template = _find(index["templates"], SCHEMA_TEMPLATE_ID, "template")
    schema = json.loads(await repo.get_file(schema_template["paths"][0]))

    errors = [
        {"path": ".".join(str(p) for p in error.absolute_path) or "manifest", "message": error.message}
        for error in Draft202012Validator(schema).iter_errors(spec)
    ]

    if isinstance(spec, dict):
        known = {s["id"] for s in index["data_sources"]}
        for source in spec.get("data_sources", []):
            if source not in known:
                errors.append({"path": "data_sources", "message": f"Unknown data source {source!r}"})
        # Not expressible in JSON Schema: a route must belong to its own board.
        prefix = f"/{spec.get('id')}/"
        for route in spec.get("routes", []):
            path = route.get("path", "") if isinstance(route, dict) else ""
            if not path.startswith(prefix):
                errors.append({"path": "routes", "message": f"route {path!r} must start with {prefix}"})

    preview = isinstance(spec, dict) and spec.get("data_mode") == "approved-read-only-preview"
    return {
        **_source(repo),
        "valid": not errors,
        "errors": errors,
        "warning": (
            "Manifest validation does not grant data access. A human must confirm the "
            "preview approval and access controls."
            if preview and not errors
            else None
        ),
    }


def register(mcp):
    @mcp.tool()
    async def list_guidance() -> dict:
        """List the repository guidance documents (AGENTS.md files, README, skills). Start here."""
        return await guidance_index(repository)

    @mcp.tool()
    async def get_guidance(
        guidance_id: str = Field(description="An id returned by list_guidance, e.g. 'agents'."),
    ) -> dict:
        """Return the current content of one guidance document from the repository."""
        return await guidance_document(repository, guidance_id)

    @mcp.tool()
    async def list_templates() -> dict:
        """List the board templates (client skeleton, server router with fixtures, chart, schema)."""
        return await template_index(repository)

    @mcp.tool()
    async def get_template(
        template_id: str = Field(description="An id returned by list_templates."),
    ) -> dict:
        """Return the template's files as they currently exist in the repository."""
        return await template_bundle(repository, template_id)

    @mcp.tool()
    async def list_data_sources() -> dict:
        """List data sources and whether a prototype may use them without approval."""
        return await data_source_index(repository)

    @mcp.tool()
    async def get_data_source_guide(
        source_id: str = Field(description="An id returned by list_data_sources."),
    ) -> dict:
        """Return usage and approval guidance for one data source."""
        return await data_source_guide(repository, source_id)

    @mcp.tool()
    async def list_dashboard_components() -> dict:
        """List reusable components found in the tableaux repository."""
        return await component_index(repository)

    @mcp.tool()
    async def recommend_architecture(
        data_sources: list[str] = Field(
            default_factory=list,
            description="Requested data source ids; use board-fixtures by default.",
        ),
    ) -> dict:
        """Recommend fixtures first and identify the human approvals a real source needs."""
        return await recommendation(repository, data_sources)

    @mcp.tool()
    async def validate_dashboard_spec(spec: dict) -> dict:
        """Validate a board.manifest.json against the repository schema; executes no code."""
        return await validation(repository, spec)
