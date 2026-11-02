"""Dashboard prototyping tools backed by the tableaux repository."""

import json
import os
import re
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


async def chart_examples(repo) -> dict:
    index = await load_index(repo)
    return {**_source(repo), "chart_examples": index.get("chart_examples", [])}


async def existing_board_ids(repo) -> list[str]:
    """Board ids from existing client board folders, for id-collision checks."""
    files = await repo.list_files("client/src/boards/")
    ids = {p.split("/")[3] for p in files if len(p.split("/")) > 4}
    ids.discard("integration")
    return sorted(ids)


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
    source = _find(index["data_sources"], source_id, "data source")
    guide_path = source.get("guide")
    guide = None
    if isinstance(guide_path, str):
        guide = await repo.get_file(guide_path)
    return {**_source(repo), **source, "guide": guide}


async def component_index(repo) -> dict:
    index = await load_index(repo)
    return {**_source(repo), "components": index["components"]}


async def recommendation(repo, data_sources: list[str]) -> dict:
    index = await load_index(repo)
    sources = [_find(index["data_sources"], s, "data source") for s in data_sources]
    pending = [s["id"] for s in sources if s["status"] != "allowed"]
    mode = "fixtures-public-snapshot" if any(s["id"] == "external" for s in sources) else "fixtures-dummy"
    return {
        **_source(repo),
        "data_mode": mode,
        "pending_approvals": pending,
        "requires_human_decision": bool(pending),
        "reason": (
            "Every board has its own server routes serving fixtures by default; the browser "
            "calls only those routes. A real source replaces the fixtures only after its owner "
            "approves it, without changing the route contract. An external public source is "
            "prototyped as a fixtures-public-snapshot (record license, retrieval date, URL) or, "
            "for a live call, external-live with server-side caching and a platform egress "
            "decision. See the 'prototyping' guidance and the source's guide."
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
        seen_paths: set[str] = set()
        for route in spec.get("routes", []):
            path = route.get("path", "") if isinstance(route, dict) else ""
            if not path.startswith(prefix):
                errors.append({"path": "routes", "message": f"route {path!r} must start with {prefix}"})
            key = f"{route.get('method', 'GET') if isinstance(route, dict) else 'GET'} {path}"
            if key in seen_paths:
                errors.append({"path": "routes", "message": f"duplicate route {key!r}"})
            seen_paths.add(key)

    warnings: list[str] = []
    if isinstance(spec, dict):
        existing = set(await existing_board_ids(repo))
        board_id = spec.get("id")
        if isinstance(board_id, str) and board_id in existing:
            warnings.append(
                f"Board id {board_id!r} already exists in the repository; promotion would collide with it."
            )

    preview = isinstance(spec, dict) and spec.get("data_mode") == "approved-read-only-preview"
    if preview and not errors:
        approval = spec.get("preview_approval") if isinstance(spec.get("preview_approval"), dict) else {}
        owner = approval.get("owner", "")
        if not owner or owner.strip().lower() in ("me", "myself", "self"):
            warnings.append(
                "preview_approval.owner is self-declared; a named data owner must confirm the approval and access controls."
            )
        else:
            warnings.append(
                "Manifest validation does not grant data access. A human must confirm the "
                "preview approval and access controls."
            )
    return {
        **_source(repo),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


BUNDLE_RULES = (
    "router_mounted_in_server_router",
    "folder_names_match_board_id",
    "api_tests_http_present",
    "no_hardcoded_hex_colors_in_client",
    "no_elasticsearch_call_or_fixture_import_in_client",
)


async def bundle_validation(repo, board_id: str) -> dict:
    """Check a board's files in the repository; static checks only, executes no code."""
    errors: list[dict] = []
    warnings: list[str] = []
    try:
        client_files = await repo.list_files(f"client/src/boards/{board_id}/")
    except RepoError:
        client_files = []
        errors.append({"path": "client", "message": f"client/src/boards/{board_id}/ not found"})
    try:
        server_files = await repo.list_files(f"server/src/routes/boards/{board_id}/")
    except RepoError:
        server_files = []
        errors.append({"path": "server", "message": f"server/src/routes/boards/{board_id}/ not found"})

    # Router mounted in server/src/router.js
    try:
        router_js = await repo.get_file("server/src/router.js")
        if f"routes/boards/{board_id}" not in router_js and f"boards/{board_id}" not in router_js:
            errors.append({"path": "server/src/router.js", "message": f"board router for '{board_id}' is not mounted"})
    except RepoError as e:
        warnings.append(f"could not read server/src/router.js: {e}")

    # api-tests present
    if server_files and not any(p.endswith(".http") for p in server_files):
        warnings.append("no api-tests/*.http request file under the board's server folder")

    # Client checks
    hex_color = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    for path in client_files:
        if not path.endswith((".ts", ".tsx", ".js", ".jsx")):
            continue
        content = await repo.get_file(path)
        if hex_color.search(content):
            errors.append({"path": path, "message": "hard-coded hex color in client code"})
        if "/elasticsearch" in content:
            errors.append({"path": path, "message": "client calls /elasticsearch directly"})
        if "fixtures" in content and ("import" in content or "require" in content):
            errors.append({"path": path, "message": "client may be importing a fixture"})

    return {
        **_source(repo),
        "board_id": board_id,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "rules": list(BUNDLE_RULES),
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

    @mcp.tool()
    async def list_chart_examples() -> dict:
        """List chart examples, marking the server-routed one to copy and legacy ones to avoid."""
        return await chart_examples(repository)

    @mcp.tool()
    async def list_existing_boards() -> dict:
        """List the board ids already in the repository, to avoid a collision."""
        return {**_source(repository), "board_ids": await existing_board_ids(repository)}

    @mcp.tool()
    async def validate_board_bundle(
        board_id: str = Field(description="The board folder name, e.g. 'research-funding'."),
    ) -> dict:
        """Static checks on a board's files in the repository (router mount, folder names, .http tests, no hard-coded colors, no browser /elasticsearch). Executes no code."""
        return await bundle_validation(repository, board_id)
