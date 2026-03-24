from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from tools.scanr import schema, search, resolve

INDEXES = {
    "scanr_publications": "Scientific publications (articles, theses, conference papers). One document is one publication.",
    "scanr_organizations": "Research organizations and laboratories (universities, CNRS units, etc.). One document is one organization.",
    "scanr_persons": "Researchers and authors with their affiliations and identifiers (ORCID, IdRef). One document is one person.",
    "scanr_projects": "Funded research projects (ANR, EU, etc.) with budget and partners. One document is one project.",
    "scanr_patents": "Patents filed by French research institutions. One document is one patent.",
    "scanr_participations": "Projects participations by organizations. One document is one project participation by an organization.",
}


def register(mcp: FastMCP):

    # register tools for each index
    for index, index_description in INDEXES.items():
        schema.register(mcp, index, index_description)
        search.register(mcp, index, index_description)
        resolve.register(mcp, index, index_description)

    # register orchestrator
    @mcp.tool(name="scanr_search")
    def scanr_search(
        query: Annotated[str, Field(description="The user query.")],
    ) -> dict:
        """
        ALWAYS call this tool first before any scanR search.
        It returns the mandatory workflow to follow for any scanR query.
        Do not skip this step.
        """
        return {
            "workflow": [
                "Step 1 — Identify relevant indexes: based on the user query, "
                "pick one or more indexes from the 'available_indexes' list below. "
                "Think about whether the query requires data from multiple indexes.",
                "Step 2 — Get schema: for each selected index, call "
                "{index}_get_schema to retrieve the exact list of available fields. "
                "Never skip this step, never guess field names.",
                "Step 3 — Build query: construct a valid Elasticsearch query using "
                "ONLY fields returned by {index}_get_schema. "
                "Use match/multi_match for text fields, term/terms for keyword fields. "
                "Always set _source to only the fields you need, INCLUDING any ID fields "
                "you will need to cross-reference another index.",
                "Step 4 — Cross-index enrichment (if needed): "
                "if the answer requires data from another index, first use the "
                "{index}_resolve tool to get the relevant IDs for the entities you need.",
                'WRONG: {"match": {"affiliations.name": "Sorbonne"}} '
                "RIGHT: First search scanr_organizations_resolve for 'Sorbonne', get id='org123', "
                'then search scanr_publications_search with {"term": {"affiliations.id": "org123"}} ',
                "Step 5 — Execute search: call {index}_search with your query.",
                "Step 6 — Evaluate results: "
                "if results are empty or an 'invalid_fields' error is returned, "
                "go back to Step 2, re-read the schema carefully and fix your query. "
                "Never return empty results without retrying at least once.",
                "Step 7 — Synthesize: return a clear structured answer to the user "
                "based on all collected results, merging data across indexes if needed.",
            ],
            "rules": [
                "Never call {index}_search before calling {index}_get_schema",
                "Never use field names not present in the schema",
                "If an 'invalid_fields' error is returned, you MUST call {index}_get_schema again",
                "For cross-index queries, always use term/terms on ID fields — never full-text match on IDs",
                "When chaining indexes, fetch only the ID fields you need in _source to keep responses small",
                "You may chain as many indexes as needed to fully answer the question",
                "Always prefer specific field matches over generic full-text when possible",
                "When resolve/search returns more than 1 candidate for an entity, ask the user to disambiguate",
            ],
            "available_indexes": INDEXES,
            "user_query": query,
        }
