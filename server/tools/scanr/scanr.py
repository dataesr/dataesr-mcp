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

        For a new search, first call operation="schema" with the selected index.
        Then call operation="search" using only schema fields.
        Use operation="resolve" to look up an entity by name before filtering another index by its ID.
        
        For a count or distribution, use an Elasticsearch aggregation and set search_query.size to 0;

        Dedicated alternatives are also available as scanr_get_schema, scanr_resolve, and scanr_index_search.
        """,
    )
    async def scanr_search(
        operation: Annotated[
            Literal["schema", "search", "resolve"],
            Field(description="Discover fields, execute a search, or resolve a name to IDs."),
        ],
        index: Annotated[
            ScanrIndex,
            Field(description=("Index matching the requested record type.")),
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
        schema_filter: Annotated[
            Literal["all", "primary", "secondary"],
            Field(description="Field subset returned by operation='schema'."),
        ] = "primary",
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

        if search_query is None:
            raise FastMCPError("operation='search' requires search_query.")
        return await search.index_search(index, search_query)

    @mcp.tool(
        name="scanr_get_schema",
        description="""
        Return the fields and types for one scanR index. 
        Use this before constructing an Elasticsearch query. 
        "primary" returns the most relevant fields; use "secondary" or "all" if needed.
        """,
    )
    def scanr_get_schema(
        index: ScanrIndex,
        schema_filter: Annotated[
            Literal["all", "primary", "secondary"],
            Field(description="Field subset to return."),
        ] = "primary",
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
        """,
    )
    async def scanr_index_search(index: ScanrIndex, search_query: dict) -> dict:
        """Execute an Elasticsearch query against the selected scanR index."""
        return await search.index_search(index, search_query)
