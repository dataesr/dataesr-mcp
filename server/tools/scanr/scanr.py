import asyncio
from typing import Annotated, Literal
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from helpers.elastic import es_search
from tools.scanr import resolve, schema, search
from tools.scanr.registry import INDEXES, ScanrIndex

INSTRUCTIONS = """
scanR is a French research information database. Pick the index matching the record type:
""" + "\n".join(f"- {name}: {spec.description}" for name, spec in INDEXES.items()) + """

Workflow:
1. Use scanr_list_indexes to compare index scopes when the correct index is unclear.
2. Call scanr_get_schema for the index before building any query. Use only returned fields.
   Use the field's aggregation_field for terms or cardinality aggregations.
   Call scanr_describe_field when full notes, examples or cross-index links are needed.
3. To look up an entity by name before filtering another index by its ID, call scanr_resolve.
4. To check which values a categorical field holds, call scanr_field_values.
5. Prefer scanr_query for ordinary text searches, filters, sorting, pagination and aggregations.
   Use scanr_index_search for Elasticsearch requests that need advanced query features.
   For counts or distributions, use an aggregation.

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
        name="scanr_list_indexes",
        description="List scanR indexes with descriptions, primary fields and document counts.",
    )
    async def scanr_list_indexes() -> dict:
        """List available indexes and their basic metadata."""
        async def describe(name: str, spec) -> dict:
            data, _ = await es_search(
                spec.es_index,
                {"size": 0, "query": {"match_all": {}}, "track_total_hits": True},
            )
            total = data.get("hits", {}).get("total", 0)
            return {
                "index": name,
                "description": spec.description,
                "primary_fields": await schema.index_primary_fields(name),
                "doc_count": total.get("value", 0) if isinstance(total, dict) else total,
            }

        return {"indexes": await asyncio.gather(*(describe(name, spec) for name, spec in INDEXES.items()))}

    @mcp.tool(
        name="scanr_get_schema",
        description="Return a compact, searchable page of one index's fields. Filter by prefix or field name/description; use aggregation_field for aggregations.",
    )
    async def scanr_get_schema(
        index: ScanrIndex,
        schema_filter: Annotated[
            Literal["all", "primary", "secondary"],
            Field(description="Field subset to return. Use all for every field."),
        ] = "primary",
        search: Annotated[
            str | None,
            Field(description="Find fields whose name or description contains this text."),
        ] = None,
        prefix: Annotated[
            str | None,
            Field(description="Restrict to a field path prefix, such as authors.*."),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=500, description="Maximum fields to return, from 1 to 500."),
        ] = 100,
        offset: Annotated[
            int,
            Field(ge=0, description="Number of matching fields to skip."),
        ] = 0,
    ) -> dict:
        """Return the selected index's field schema."""
        return {
            "index": index,
            "description": INDEXES[index].description,
            "fields": await schema.index_get_fields(index, schema_filter, search, prefix, limit, offset),
        }

    @mcp.tool(
        name="scanr_describe_field",
        description="Return the full description, notes, cross-index links and examples for one schema field.",
    )
    async def scanr_describe_field(index: ScanrIndex, field: str) -> dict:
        """Return full metadata for a field in one scanR index."""
        return await schema.index_describe_field(index, field)

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
        name="scanr_query",
        description="Build a safe scanR query from text, exact/range filters, fields, sort, cursor and grouped metrics. Use scanr_index_search for advanced Elasticsearch features.",
    )
    async def scanr_query(
        index: ScanrIndex,
        text: Annotated[str | None, Field(description="Optional full-text search across declared text fields.")] = None,
        filters: Annotated[
            dict | None,
            Field(description="Field filters: scalar or list for exact values, or {gte, lte, gt, lt} for ranges."),
        ] = None,
        fields: Annotated[list[str] | None, Field(description="Fields to return; defaults to primary fields.")] = None,
        sort: Annotated[
            dict[str, Literal["asc", "desc"]] | None,
            Field(description="Sort fields mapped to asc or desc. Required when using cursor."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=20, description="Number of hits, from 1 to 20.")] = 10,
        cursor: Annotated[list | None, Field(description="search_after values returned as next_cursor by the previous page.")] = None,
        aggregate: Annotated[
            dict | None,
            Field(description="Optional {group_by: field or fields, metric: count or {type, field}} aggregation."),
        ] = None,
    ) -> dict:
        """Search scanR with structured filters and optional aggregations."""
        return await search.index_query(index, text, filters, fields, sort, limit, cursor, aggregate)  # ty: ignore[invalid-argument-type]

    @mcp.tool(
        name="scanr_field_values",
        description="Return common values or numeric/date statistics for a schema field. Optional contains/prefix filters narrow value buckets.",
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
        contains: Annotated[str | None, Field(description="Include only bucket values containing this text.")] = None,
        prefix: Annotated[str | None, Field(description="Include only bucket values starting with this text.")] = None,
        mode: Annotated[
            Literal["values", "stats"],
            Field(description="Return frequent terms or numeric/date statistics."),
        ] = "values",
    ) -> dict:
        """Inspect common values of a categorical field."""
        return await search.index_field_values(index, values_field, values_limit, values_filter, contains, prefix, mode)
