from mcp.server.fastmcp.exceptions import FastMCPError
from helpers.elastic import es_search
from tools.scanr.registry import get_index
from tools.scanr.schema import index_get_base_schema, index_known_fields


async def index_get_resolve(index: str) -> dict:
    """
    Get the resolve fields for an index.
    """
    schema = await index_get_base_schema(index)
    return schema.get("resolve", {})


async def index_resolve(index: str, query: str, limit: int = 5) -> dict:
    """Resolve an entity name to candidate IDs and labels."""
    if not 1 <= limit <= 20:
        raise FastMCPError("limit must be between 1 and 20.")
    resolve_config = await index_get_resolve(index)
    search_fields = resolve_config.get("search_fields", [])
    source_fields = resolve_config.get("source_fields", [])
    if not search_fields or not source_fields:
        raise FastMCPError(f"No resolve fields found for {index}.")

    body = {
        "query": {"multi_match": {"query": query, "fields": search_fields}},
        "_source": list(dict.fromkeys([*source_fields, "id"])),
        "size": limit,
    }
    data, clamps = await es_search(get_index(index).es_index, body, await index_known_fields(index))
    result = {
        "candidates": [hit["_source"] for hit in data.get("hits", {}).get("hits", [])],
        "instruction": "If multiple candidates are returned, you MUST present them to the user and ask which one to use. Never silently pick one.",
    }
    if clamps:
        result["clamped"] = clamps
    return result
