# Tools reference

The server exposes four MCP endpoints. Each is a separate MCP server with its own tools, reachable at `<server url>/<route>` with a bearer token (see [Authentication](../README.md#authentication)).

| Route | Purpose | Tools |
| --- | --- | --- |
| `/scanr` | Query the scanR indexes | `scanr_get_schema`, `scanr_resolve`, `scanr_index_search`, `scanr_field_values`, `scanr_search` |
| `/match` | Match affiliation strings to reference systems | `get_affiliation_match` |
| `/rag` | Search Ministry publications | `flash_rag` |
| `/tableaux` | Dashboard prototyping guidance | `list_guidance`, `get_guidance`, `list_templates`, `get_template`, `list_data_sources`, `get_data_source_guide`, `list_dashboard_components`, `list_chart_examples`, `list_existing_boards`, `recommend_architecture`, `validate_dashboard_spec`, `validate_board_bundle` |

You normally don't call these tools yourself: an AI assistant connected to the endpoint picks them. The examples below show what you can ask and what the tools receive and return (responses are shortened and illustrative).

## /scanr

### Indexes

| Index | Content |
| --- | --- |
| `scanr_publications` | Scientific publications and other research outputs |
| `scanr_persons` | Researchers and other people in the research ecosystem |
| `scanr_organizations` | Research organizations and institutions |
| `scanr_projects` | Research projects: title, description, dates, identifiers |
| `scanr_participations` | A person's or organization's participation in a project (who took part, in which projects) |
| `scanr_patents` | Patents and patent-related research outputs |

### Typical workflow

1. `scanr_get_schema`: discover the fields of an index. Only use fields it returns.
2. `scanr_resolve`: turn a name ("Université de Lorraine") into an id, then filter another index with that id.
3. `scanr_field_values`: check the real values of a categorical field (for example a project type) before filtering on it.
4. `scanr_index_search`: run the actual query or aggregation.

`scanr_search` does all four through its `operation` argument (`schema`, `resolve`, `values`, `search`). The dedicated tools are equivalent.

### Example questions

- "How many publications per year does scanR have for Université de Lorraine since 2015?"
- "Which organizations participate in the most projects funded by the ANR?"
- "List the patents whose applicant is CNRS, with title and filing date."

### `scanr_get_schema`

Arguments: `index`, and optionally `schema_filter` (`all` by default, or `primary` / `secondary` to narrow).

```json
{ "index": "scanr_publications", "schema_filter": "primary" }
```

```json
{
  "index": "scanr_publications",
  "description": "Scientific publications and other research outputs.",
  "fields": {
    "title.default": {
      "type": "text",
      "keyword": true,
      "aggregation_field": "title.default.keyword",
      "description": "Publication title"
    },
    "year": { "type": "integer", "aggregation_field": "year" }
  }
}
```

`aggregation_field` is the exact path to use in `terms` aggregations.

### `scanr_resolve`

Returns up to 5 candidates (ids and labels) for a name. If several come back, the assistant is told to ask you which one is meant.

```json
{ "index": "scanr_organizations", "resolve_query": "Université de Lorraine" }
```

```json
{
  "candidates": [{ "id": "193819125", "label": { "default": "Université de Lorraine" } }],
  "instruction": "If multiple candidates are returned, you MUST present them to the user and ask which one to use. Never silently pick one."
}
```

### `scanr_field_values`

Most frequent values of an aggregatable field (1 to 100, 20 by default). `values_filter` optionally restricts the documents counted.

```json
{ "index": "scanr_projects", "values_field": "type", "values_limit": 5 }
```

```json
{
  "index": "scanr_projects",
  "field": "type",
  "aggregation_field": "type.keyword",
  "buckets": [{ "key": "ANR", "doc_count": 12000 }],
  "sum_other_doc_count": 3400
}
```

A non-zero `sum_other_doc_count` means other values exist that are not listed.

### `scanr_index_search`

Runs an Elasticsearch request body against one index. At most 20 hits are returned (larger `size` values are lowered to 20). For counts and distributions, set `size` to 0 and use `aggs`.

Publications per year:

```json
{
  "index": "scanr_publications",
  "search_query": {
    "size": 0,
    "query": { "bool": { "filter": [{ "range": { "year": { "gte": 2015 } } }] } },
    "aggs": { "per_year": { "terms": { "field": "year", "size": 10 } } }
  }
}
```

```json
{
  "total": 154320,
  "hits": [],
  "aggregations": { "per_year": { "buckets": [{ "key": 2023, "doc_count": 17000 }] } }
}
```

Titles matching a text query:

```json
{
  "index": "scanr_publications",
  "search_query": {
    "query": { "match": { "title.default": "climate" } },
    "_source": ["id", "title.default", "year"],
    "size": 5
  }
}
```

```json
{ "total": 8421, "hits": [{ "id": "doi10.1000/xyz", "title": { "default": "Climate ..." }, "year": 2024 }] }
```

Invalid queries return an error with a hint (for example `parsing_exception`: "The query syntax is invalid. Check the query structure.").

## /match

### `get_affiliation_match`

Matches an affiliation string against a reference system: `ror` (default), `grid`, `rnsr`, `paysage` or `country`. Use it to harmonize affiliations in a corpus (e.g. "Laboratoire de physique, Univ. Lorraine, Nancy" → a ROR or RNSR id).

```json
{ "affiliation": "Laboratoire de physique, Université de Lorraine, Nancy", "reference": "rnsr" }
```

```json
{
  "results": ["200711885X"],
  "enriched_results": [
    { "id": "200711885X", "name": ["Institut Jean Lamour"], "acronyms": ["IJL"], "cities": ["Nancy"], "countries": ["fr"] }
  ]
}
```

`results` is the list of matched ids (empty when nothing matches). `enriched_results` gives names, acronyms, cities and countries to check the match.

## /rag

### `flash_rag`

Finds the passages of French Ministry of Higher Education and Research publications (statistics, figures, reports) closest to a question.

| Argument | Default | Meaning |
| --- | --- | --- |
| `query` | required | The question |
| `top_k` | 5 | Number of passages returned |
| `use_hybrid_search` | true | Combine embeddings with keyword (BM25) search |
| `use_reranker` | true | Rerank the results |

```json
{ "query": "Quelle est la dépense intérieure de R&D en France ?", "top_k": 3 }
```

```json
[
  {
    "distance": 0.12,
    "document": "En 2023, la DIRD s'élève à ...",
    "metadata": {
      "title": "L'état de l'Enseignement supérieur, de la Recherche et de l'Innovation",
      "section_title": "...",
      "publication_date": "2024-06-01",
      "publication_type": "...",
      "file_access": "...",
      "file_url": "https://...",
      "chunk_type": "..."
    }
  }
]
```

A smaller `distance` means a closer match.

## /tableaux

These tools read the prototyping conventions of the `dataesr/tableaux` repository (cached 5 minutes) and validate dashboard manifests. They never run code.

| Tool | Use |
| --- | --- |
| `list_guidance` | Start here: lists the guidance documents |
| `get_guidance(guidance_id)` | Content of one document |
| `list_templates` / `get_template(template_id)` | Board templates and their files |
| `list_data_sources` / `get_data_source_guide(source_id)` | Data sources and whether a prototype may use them without approval |
| `list_dashboard_components` | Reusable components |
| `list_chart_examples` | Chart examples (which to copy, which to avoid) |
| `list_existing_boards` | Existing board ids, to avoid a collision |
| `recommend_architecture(data_sources)` | Fixtures first, plus the approvals a real source needs |
| `validate_dashboard_spec(spec)` | Validate a `board.manifest.json` against the repository schema |
| `validate_board_bundle(board_id)` | Static checks on a board's files in the repository |

Example: `get_guidance`

```json
{ "guidance_id": "agents" }
```

```json
{ "repository": "dataesr/tableaux", "ref": "staging", "id": "agents", "title": "Agents", "path": "AGENTS.md", "content": "# ..." }
```

Example: `validate_dashboard_spec`

```json
{
  "spec": {
    "schema_version": 1,
    "id": "research-funding",
    "name": "Research funding",
    "description": "Funding overview",
    "data_mode": "fixtures-dummy",
    "data_sources": ["board-fixtures"],
    "routes": [{ "method": "GET", "path": "/research-funding/overview/summary", "description": "Summary" }],
    "features": ["filters"]
  }
}
```

```json
{ "repository": "dataesr/tableaux", "ref": "staging", "valid": true, "errors": [], "warnings": [] }
```
