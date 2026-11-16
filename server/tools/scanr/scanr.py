from typing import Annotated, Literal
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from tools.scanr import resolve, schema, search
from tools.scanr.registry import INDEXES, ScanrIndex

INSTRUCTIONS = """
scanR is a French research information database. Pick the index matching the record type:
""" + "\n".join(f"- {name}: {spec.description}" for name, spec in INDEXES.items()) + """

Workflow:
1. Call scanr_get_schema for the index before building any query. Use only returned fields.
   Use the field's aggregation_field for terms or cardinality aggregations.
2. To look up an entity by name before filtering another index by its ID, call scanr_resolve.
3. To check which values a categorical field holds, call scanr_field_values.
4. Call scanr_index_search for Elasticsearch requests. For counts or distributions, set size to 0.

Ask the user before proceeding when a request admits materially different meanings (for example,
"regional projects" may mean located in a region, funded by a regional body, or involving participants
from that region). Also confirm the unit being counted when participations may repeat per project.
Field values are the most frequent observed values, not an exhaustive vocabulary.
""".strip()


def register(mcp: FastMCP):

    @mcp.prompt(
        name="scanr_guide",
        description="Workflow and disambiguation rules for querying scanR.",
    )
    def scanr_guide() -> str:
        return INSTRUCTIONS

    @mcp.tool(
        name="scanr_get_schema",
        description="Return the fields and types of one scanR index. Call before building any query. Use aggregation_field for aggregations.",
    )
    async def scanr_get_schema(
        index: ScanrIndex,
        schema_filter: Annotated[
            Literal["all", "primary", "secondary"],
            Field(description="Field subset to return. Use all for every field."),
        ] = "primary",
    ) -> dict:
        """Return the selected index's field schema."""
        return {
            "index": index,
            "description": INDEXES[index].description,
            "fields": await schema.index_get_fields(index, schema_filter),
        }

    @mcp.tool(
        name="scanr_resolve",
        description="Look up a person, organization, project or other entity by name. Returns candidate IDs for exact filters. If several candidates match, ask the user which one is meant.",
    )
    async def scanr_resolve(
        index: ScanrIndex,
        resolve_query: str,
        limit: Annotated[
            int,
            Field(ge=1, le=20, description="Maximum candidates, from 1 to 20."),
        ] = 5,
    ) -> dict:
        """Resolve a name to candidate IDs and labels."""
        return await resolve.index_resolve(index, resolve_query, limit)

    @mcp.tool(
        name="scanr_index_search",
        description="Execute a raw Elasticsearch request against one scanR index. Use only fields from scanr_get_schema. Hits are capped at 20 and _source defaults to primary fields.",
    )
    async def scanr_index_search(index: ScanrIndex, search_query: dict) -> dict:
        """Execute an Elasticsearch query against the selected scanR index."""
        return await search.index_search(index, search_query)

    @mcp.tool(
        name="scanr_field_values",
        description="Return the most frequent values of a field in one scanR index. Pass the base field name; the exact aggregation field is chosen automatically. Results are top values, not an exhaustive list.",
    )
    async def scanr_field_values(
        index: ScanrIndex,
        values_field: str,
        values_limit: Annotated[
            int,
            Field(ge=1, le=100, description="Maximum buckets, from 1 to 100."),
        ] = 20,
        values_filter: Annotated[
            dict | None,
            Field(description="Optional Elasticsearch query object to scope the value counts."),
        ] = None,
    ) -> dict:
        """Inspect common values of a categorical field."""
        return await search.index_field_values(index, values_field, values_limit, values_filter)
