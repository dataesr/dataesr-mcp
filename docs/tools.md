# Tools reference

The server exposes four MCP endpoints. Each is a separate MCP server with its own tools, reachable at `<server url>/<route>` with a bearer token (see [Authentication](../README.md#authentication)).

| Route | Purpose | Tools |
| --- | --- | --- |
| `/scanr` | Query the scanR indexes | `scanr_list_indexes`, `scanr_get_schema`, `scanr_describe_field`, `scanr_resolve`, `scanr_query`, `scanr_index_search`, `scanr_field_values` |
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

1. `scanr_list_indexes`: compare index descriptions, primary fields and document counts.
2. `scanr_get_schema`: discover the fields of an index. It defaults to primary fields; use `search`, `prefix`, `limit` and `offset` to find a field or page through a larger schema.
3. `scanr_describe_field`: inspect full notes, examples and cross-index links for an individual field.
4. `scanr_resolve`: turn a name ("Université de Lorraine") into an id, then filter another index with that id.
5. `scanr_field_values`: check the real values of a categorical field (for example a project type) before filtering on it.
6. `scanr_query`: use structured text, filters, sorting, cursors and aggregations for common searches. Use `scanr_index_search` for advanced Elasticsearch requests.

The workflow and disambiguation rules are sent to the assistant as server instructions and are also available as the `scanr_guide` prompt.

### Example questions

- "How many publications per year does scanR have for Université de Lorraine since 2015?"
- "Which organizations participate in the most projects funded by the ANR?"
- "List the patents whose applicant is CNRS, with title and filing date."

### `scanr_get_schema`

Arguments: `index`, and optionally `schema_filter` (`primary` by default, or `all` / `secondary`), `search` (case-insensitive substring in field names or descriptions), `prefix` (for example `authors.*`), `limit` (100 by default, maximum 500) and `offset` (0 by default). Results are compact and paginated. The schema is cached for one hour (`SCANR_SCHEMA_TTL` seconds); if a refresh fails, the last good copy is served.

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
      "aggregation_field": "title.default.keyword",
      "description": "Publication title"
    },
    "year": { "type": "integer", "aggregation_field": "year" }
  }
}
```

`aggregation_field` is the exact path to use in `terms` aggregations.

### `scanr_list_indexes`

Returns each index's description, primary fields and exact Elasticsearch document count.

### `scanr_describe_field`

Returns the full metadata for one field, including its description, notes, cross-index links and examples when present. Unknown fields include close name suggestions.

```json
{ "index": "scanr_publications", "field": "title.default" }
```

### `scanr_resolve`

Returns up to `limit` candidates (ids and labels, 5 by default, 20 at most) for a name. If several come back, the assistant is told to ask you which one is meant.

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
Use `contains` or `prefix` to filter string buckets. Set `mode` to `"stats"` for numeric/date field statistics (`count`, `min`, `max`, `avg`, `sum`).

### `scanr_query`

Builds a guarded Elasticsearch query from structured parameters. `filters` accepts exact scalar values, lists of exact values, or range objects using `gte`, `gt`, `lte` and `lt`. `sort` maps field names to `asc` or `desc`; use the returned `next_cursor` as `cursor` for the next page. Aggregations use `aggregate: {"group_by": "field", "metric": {"type": "avg", "field": "numeric_field"}}`; `count` is the default metric.

```json
{
  "index": "scanr_publications",
  "text": "climate",
  "filters": { "year": { "gte": 2020 } },
  "fields": ["id", "title.default", "year"],
  "sort": { "year": "desc" },
  "limit": 10
}
```

### `scanr_index_search`

Runs an Elasticsearch request body against one index. At most 20 hits are returned, and `_source` defaults to the index's primary fields. Requests are checked before they are sent: only top-level keys such as `query`, `aggs`, `sort`, `size` and `from` are accepted, `script`, `runtime_mappings`, `scroll` and `pit` are refused, `from + size` is limited to 1000, aggregation nesting to 3 levels and bucket sizes to 100, and unknown field names are rejected with a suggestion. Each value that was changed is reported under `clamped` (for example `"size_capped_from": 500`). Long strings and lists are truncated, and `truncated: true` with a hint appears when the response is cut to fit its size budget. For counts and distributions, set `size` to 0 and use `aggs`.

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
