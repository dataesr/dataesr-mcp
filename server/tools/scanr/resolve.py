from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import FastMCPError
from helpers.elastic import es_search
from tools.scanr.schema import index_get_base_schema


def index_get_resolve(index: str) -> dict:
    """
    Get the resolve fields for an index.
    """
    schema = index_get_base_schema(index)
    return schema.get("resolve", {})


# TODO get label field from index
def register(mcp: FastMCP, index: str, index_description: str):
    @mcp.tool(
        name=f"{index}_resolve",
        description=f"""
        Quick lookup for the {index} index. Search by name and return only IDs + labels.
        Use this to resolve entity names to IDs before cross-index queries.
        Index content: {index_description}
        """,
    )
    async def resolve(query: str) -> dict:
        f"""
        Quick lookup for the {index} index.
        """
        resolve = index_get_resolve(index)
        search_fields = resolve.get("search_fields", [])
        source_fields = resolve.get("source_fields", [])
        if not search_fields or not source_fields:
            raise FastMCPError("No resolve fields found for this index.")

        body = {
            "query": {"multi_match": {"query": query, "fields": search_fields}},
            "_source": list(set(source_fields + ["id"])),
            "size": 5,
        }
        data = await es_search(index, body)
        return {
            "candidates": [hit["_source"] for hit in data.get("hits", {}).get("hits", [])],
            "instruction": "If multiple candidates are returned, you MUST present them to the user and ask which one to use. Never silently pick one.",
        }
