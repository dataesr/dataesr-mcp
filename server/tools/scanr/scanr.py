from typing import Annotated, Literal
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import FastMCPError
from tools.scanr import resolve, schema, search

ScanrIndex = Literal[
    "scanr_publications",
    "scanr_persons",
    "scanr_organizations",
    "scanr_projects",
    "scanr_participations",
    "scanr_patents",
]

index_descriptions = {
    "scanr_publications": "Scientific publications and other research outputs.",
    "scanr_persons": "Researchers and other people in the research ecosystem.",
    "scanr_organizations": "Research organizations and institutions.",
    "scanr_projects": "Research project records. Choose this index when asking about the project itself, such as its title, description, dates, or identifiers.",
    "scanr_participations": "Relationships recording a person's or organization's participation in a research project. Choose this index to find who participated in a project, which projects an entity participated in, or participation-specific details.",
    "scanr_patents": "Patents and patent-related research outputs.",
}

def register(mcp: FastMCP):

    @mcp.tool(
        name="scanr_search",
        description=f"""
        Primary scanR tool. Use this single tool for schema discovery, entity resolution, and Elasticsearch searches.

        Choose an index by the kind of record being asked about:
        - publications: {index_descriptions["scanr_publications"]}
        - persons: {index_descriptions["scanr_persons"]}
        - organizations: {index_descriptions["scanr_organizations"]}
        - projects: {index_descriptions["scanr_projects"]}
        - participations: {index_descriptions["scanr_participations"]}
        - patents: {index_descriptions["scanr_patents"]}

        Before building a query, first call operation="schema". The default schema_filter
        is "all" so relevant fields are not silently omitted; use "primary" only to narrow
        the response. Then use only returned schema fields. The schema's aggregation_field is the exact
        Elasticsearch path to use for terms/cardinality aggregations.
        Use operation="resolve" to look up an entity by name before filtering another index by its ID.

        If the wording admits materially different interpretations (for example, whether
        "regional projects" means projects located in a region, funded by a regional body,
        or involving participants from that region), ask the user which meaning they intend
        before choosing filters or reporting a result. Also confirm the unit being counted
        when participations could represent multiple records per project.

        For an unclear categorical value or vocabulary, inspect operation="schema" with
        schema_filter="all", then operation="values" on the relevant aggregatable field.
        Values are the most frequent observed values, not guaranteed to be exhaustive;
        use them to inform a clarification, not to silently choose a meaning.

        For a count or distribution, use an Elasticsearch aggregation and set search_query.size to 0;

        Dedicated alternatives are also available as scanr_get_schema, scanr_resolve,
        scanr_field_values, and scanr_index_search.
        """,
    )
    async def scanr_search(
        operation: Annotated[
            Literal["schema", "search", "resolve", "values"],
            Field(description="Discover fields, search, resolve a name, or inspect frequent field values."),
        ],
        index: Annotated[
            ScanrIndex,
            Field(description="Index matching the requested record type."),
        ],
        search_query: Annotated[
            dict | None,
            Field(
                description=(
                    "Elasticsearch request body for operation='search'. Use only fields "
                    "returned by operation='schema'. For aggregation-only requests, set "
                    '"size": 0 and include an "aggs" object.'
                ),
            ),
        ] = None,
        resolve_query: Annotated[
            str | None,
            Field(
                description="Entity name for operation='resolve', such as a person or organization.",
            ),
        ] = None,
        values_field: Annotated[
            str | None,
            Field(description="Schema field for operation='values'."),
        ] = None,
        values_limit: Annotated[
            int,
            Field(ge=1, le=100, description="Maximum number of frequent values to return (1-100)."),
        ] = 20,
        values_filter: Annotated[
            dict | None,
            Field(description="Optional Elasticsearch query object to scope the value counts."),
        ] = None,
        schema_filter: Annotated[
            Literal["all", "primary", "secondary"],
            Field(description="Field subset returned by operation='schema'."),
        ] = "all",
    ) -> dict:
        """Discover a scanR schema, resolve an entity, or search an index."""

        if operation == "schema":
            return {
                "index": index,
                "description": index_descriptions[index],
                "fields": schema.index_get_fields(index, schema_filter),
            }

        if operation == "resolve":
            if not resolve_query:
                raise FastMCPError("operation='resolve' requires a non-empty query.")
            return await resolve.index_resolve(index, resolve_query)

        if operation == "values":
            if not values_field:
                raise FastMCPError("operation='values' requires a schema field.")
            return await search.index_field_values(index, values_field, values_limit, values_filter)

        if search_query is None:
            raise FastMCPError("operation='search' requires search_query.")
        return await search.index_search(index, search_query)

    @mcp.tool(
        name="scanr_get_schema",
        description="""
        Return the fields and types for one scanR index. 
        Use this before constructing an Elasticsearch query. 
        "all" is the default and avoids omitting relevant fields; use "primary" to
        narrow the response. Each field includes aggregation_field when it is safe to
        aggregate: use that exact path (for example, project_id.keyword).
        """,
    )
    def scanr_get_schema(
        index: ScanrIndex,
        schema_filter: Annotated[
            Literal["all", "primary", "secondary"],
            Field(description="Field subset to return."),
        ] = "all",
    ) -> dict:
        """Return the selected index's field schema."""

        return {
            "index": index,
            "description": index_descriptions[index],
            "fields": schema.index_get_fields(index, schema_filter),
        }

    @mcp.tool(
        name="scanr_resolve",
        description="""Look up a person, organization, project, publication, or other entity by name in the selected scanR index. 
        Returns candidate IDs and labels for use in exact cross-index filters.
        If multiple candidates are returned, ask the user to disambiguate rather than choosing silently.
        If the query is materially ambiguous, ask the user which meaning or scope they intend
        before resolving an entity or selecting filters.
        """,
    )
    async def scanr_resolve(index: ScanrIndex, resolve_query: str) -> dict:
        """Resolve a name to candidate IDs and labels."""
        return await resolve.index_resolve(index, resolve_query)

    @mcp.tool(
        name="scanr_index_search",
        description="""
        Execute an Elasticsearch request against one scanR index.
        First inspect the index with scanr_get_schema or scanr_search(operation="schema"); use only fields returned by the schema.
        Use match/multi_match for text, term/terms for exact values and IDs, and put exact filters in bool.filter.
        Limit hits with size (maximum 20) and _source.
        For aggregation-only requests set size to 0; response includes hit total and aggregations.
        If the requested field/value interpretation is unclear, inspect scanr_field_values and
        ask the user to confirm consequential assumptions before reporting a result.
        """,
    )
    async def scanr_index_search(index: ScanrIndex, search_query: dict) -> dict:
        """Execute an Elasticsearch query against the selected scanR index."""
        return await search.index_search(index, search_query)

    @mcp.tool(
        name="scanr_field_values",
        description="""
        Return the most frequent values for an aggregatable field in one scanR index.
        First inspect scanr_get_schema with schema_filter="all" and pass the base field
        name; the tool chooses the exact aggregation_field, including .keyword when needed.
        Use this when a categorical field's values or vocabulary are unclear, preferably
        before selecting a value as a filter. Optional filter_query can scope the counts.
        Results are bounded top values, not necessarily an exhaustive vocabulary; a
        non-zero sum_other_doc_count means additional values were omitted.
        """,
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
        """Inspect common values without guessing Elasticsearch keyword subfields."""
        return await search.index_field_values(index, values_field, values_limit, values_filter)
