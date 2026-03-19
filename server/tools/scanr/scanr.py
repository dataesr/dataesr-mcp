import json
from mcp.server.fastmcp import FastMCP
from tools.scanr import schema, search

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

    # register orchestrator
    @mcp.tool(name="scanr_search")
    def scanr_search(
        query: str,
    ) -> str:
        """
        ALWAYS call this tool first before any scanR search.
        It returns the mandatory workflow to follow for any scanR query.
        Do not skip this step.
        """
        return json.dumps(
            {
                "workflow": [
                    "Step 1 — Identify relevant indexes: based on the user query, "
                    "pick one or more indexes from the 'available_indexes' list below.",
                    "Step 2 — Get schema: for each selected index, call "
                    "{index}_get_schema to retrieve the exact list of available fields. "
                    "Never skip this step, never guess field names.",
                    "Step 3 — Build query: construct a valid Elasticsearch query using "
                    "ONLY fields returned by {index}_get_schema. "
                    "Use match/multi_match for text fields, term/terms for keyword fields. "
                    "Always set _source to only the fields you need.",
                    "Step 4 — Execute search: call {index}_search with your query.",
                    "Step 5 — Evaluate results: "
                    "if results are empty or an 'unknown_fields' error is returned, "
                    "go back to Step 2, re-read the schema carefully and fix your query. "
                    "Never return empty results without retrying at least once.",
                    "Step 6 — Synthesize: return a clear structured answer to the user " "based on the search results.",
                ],
                "rules": [
                    "Never call {index}_search before calling {index}_get_schema",
                    "Never use field names not present in the schema",
                    "If an 'unknown_fields' error is returned, you MUST call {index}_get_schema again",
                    "You may search multiple indexes if the question spans several domains",
                    "Always prefer specific field matches over generic full-text when possible",
                ],
                "available_indexes": INDEXES,
                "user_query": query,
            },
            indent=2,
        )
