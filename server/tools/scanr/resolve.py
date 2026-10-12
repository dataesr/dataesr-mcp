from mcp.server.fastmcp.exceptions import FastMCPError
from helpers.elastic import es_search
from tools.scanr.schema import index_get_base_schema


def index_get_resolve(index: str) -> dict:
    """
    Get the resolve fields for an index.
    """
    schema = index_get_base_schema(index)
    return schema.get("resolve", {})


async def index_resolve(index: str, query: str) -> dict:
    """Resolve an entity name to candidate IDs and labels."""
    resolve_config = index_get_resolve(index)
    search_fields = resolve_config.get("search_fields", [])
    source_fields = resolve_config.get("source_fields", [])
    if not search_fields or not source_fields:
        raise FastMCPError(f"No resolve fields found for {index}.")

    body = {
        "query": {"multi_match": {"query": query, "fields": search_fields}},
        "_source": list(set(source_fields + ["id"])),
        "size": 5,
    }
    data = await es_search(index, body, validate=False)
    return {
        "candidates": [hit["_source"] for hit in data.get("hits", {}).get("hits", [])],
        "instruction": "If multiple candidates are returned, you MUST present them to the user and ask which one to use. Never silently pick one.",
    }
