from mcp.server.fastmcp import FastMCP
from helpers.elastic import es_search


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
        body = {
            "query": {"multi_match": {"query": query, "fields": ["label.*", "title.*", "fullName"]}},
            "_source": ["id", "label.default", "title.default", "fullName"],
            "size": 5,
        }
        data = await es_search(index, body)
        return {
            "candidates": [
                {
                    "id": hit["_source"].get("id"),
                    "label": hit["_source"].get("label", {}).get("default")
                    or hit["_source"].get("title", {}).get("default")
                    or hit["_source"].get("fullName"),
                }
                for hit in data.get("hits", {}).get("hits", [])
            ],
            "instruction": "If multiple candidates are returned, you MUST present them to the user and ask which one to use. Never silently pick one.",
        }
