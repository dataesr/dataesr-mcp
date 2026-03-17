from mcp.server.fastmcp import FastMCP
import json

SCHEMA_SUMMARY = {
    "index": "scanr-publications",
    "description": "French scientific publications index (scanR project)",
    "notes": [
        "Text fields use the 'light' analyzer (lowercase + ICU folding). Use match/multi_match for them.",
        "Keyword fields require exact values — use term/terms queries.",
        "Most text fields also have a '.keyword' sub-field for exact/aggregation use.",
        "Boost important fields with ^ in multi_match, e.g. 'title.default^3'.",
    ],
    "fields": {
        # --- Core metadata ---
        "id": {"type": "keyword", "description": "Unique publication ID"},
        "year": {"type": "long", "description": "Publication year"},
        "publicationDate": {"type": "date", "description": "Full publication date"},
        "productionType": {"type": "keyword", "description": "Type: article, thesis, conference, etc."},
        "type": {"type": "keyword", "description": "Raw type field"},
        "isOa": {"type": "boolean", "description": "True if open access"},
        # --- Title & abstract ---
        "title.default": {"type": "text", "description": "Main title (best field for full-text search)"},
        "title.fr": {"type": "text", "description": "French title"},
        "title.en": {"type": "text", "description": "English title"},
        "summary.default": {"type": "text", "description": "Abstract (default language)"},
        "summary.fr": {"type": "text", "description": "French abstract"},
        "summary.en": {"type": "text", "description": "English abstract"},
        "keywords.default": {"type": "text", "description": "Keywords"},
        "title_abs_text": {"type": "text", "description": "Combined title+abstract, uses heavy (stemmed) analyzer"},
        # --- Authors ---
        "authors.fullName": {"type": "text", "description": "Author full name (searchable)"},
        "authors.firstName": {"type": "text", "description": "Author first name"},
        "authors.lastName": {"type": "text", "description": "Author last name"},
        "authors.person": {"type": "keyword", "description": "Author person ID"},
        "authors.role": {"type": "keyword", "description": "Author role"},
        "authors.denormalized.id": {"type": "keyword", "description": "Denormalized author ID"},
        "authors.denormalized.orcid": {"type": "keyword", "description": "Author ORCID"},
        "authors.denormalized.idref": {"type": "keyword", "description": "Author IdRef"},
        "authorsCount": {"type": "long", "description": "Number of authors"},
        # --- Affiliations / structures ---
        "affiliations.id": {"type": "keyword", "description": "Affiliated structure ID"},
        "affiliations.label.default": {"type": "text", "description": "Affiliated structure name"},
        "affiliations.acronym.default": {"type": "text", "description": "Affiliated structure acronym"},
        "affiliations.country": {"type": "keyword", "description": "Affiliation country"},
        "affiliations.isFrench": {"type": "boolean", "description": "True if French affiliation"},
        "affiliations.kind": {"type": "keyword", "description": "Structure kind (lab, university, etc.)"},
        "affiliations.status": {"type": "keyword", "description": "Structure status"},
        # --- Source / journal ---
        "source.title": {"type": "text", "description": "Journal or venue title"},
        "source.publisher": {"type": "text", "description": "Publisher name"},
        "source.isOa": {"type": "boolean", "description": "True if source journal is OA"},
        "source.isInDoaj": {"type": "boolean", "description": "True if source is in DOAJ"},
        "source.journalIssns": {"type": "keyword", "description": "Journal ISSNs"},
        # --- External IDs & links ---
        "externalIds.id": {"type": "keyword", "description": "DOI or other external identifier value"},
        "externalIds.type": {"type": "keyword", "description": "ID type: doi, hal, pubmed, etc."},
        "doiUrl": {"type": "keyword", "description": "Full DOI URL"},
        "landingPage": {"type": "keyword", "description": "Landing page URL"},
        "pdfUrl": {"type": "keyword", "description": "Direct PDF URL"},
        # --- Open access evidence ---
        "oaEvidence.hostType": {"type": "keyword", "description": "OA host: publisher, repository, etc."},
        "oaEvidence.version": {"type": "keyword", "description": "OA version: publishedVersion, acceptedVersion, etc."},
        "oaEvidence.license": {"type": "keyword", "description": "OA license (e.g. cc-by)"},
        "oaEvidence.pdfUrl": {"type": "keyword", "description": "OA PDF URL"},
        # --- Scientific domains ---
        "domains.label.default": {"type": "text", "description": "Scientific domain label"},
        "domains.code": {"type": "keyword", "description": "Domain code"},
        "domains.type": {"type": "keyword", "description": "Domain type"},
        # --- Topics (OpenAlex-style) ---
        "topics.display_name": {"type": "keyword", "description": "Topic name"},
        "topics.score": {"type": "float", "description": "Topic relevance score"},
        "topics.domain.display_name": {"type": "keyword", "description": "Topic domain name"},
        "topics.field.display_name": {"type": "keyword", "description": "Topic field name"},
        "topics.subfield.display_name": {"type": "keyword", "description": "Topic subfield name"},
        # --- Projects / funding ---
        "projects.id": {"type": "keyword", "description": "Linked project ID"},
        "projects.label.fr": {"type": "text", "description": "Project label (French)"},
        "projects.label.en": {"type": "text", "description": "Project label (English)"},
        "projects.acronym.default": {"type": "keyword", "description": "Project acronym"},
        "projects.type": {"type": "keyword", "description": "Project type"},
        "projects.year": {"type": "long", "description": "Project year"},
        # --- Acknowledgments / funders ---
        "structured_acknowledgments.funders.entity": {"type": "text", "description": "Funder name"},
        "structured_acknowledgments.funders.grant_id": {"type": "keyword", "description": "Grant ID"},
        "structured_acknowledgments.funders.type": {"type": "keyword", "description": "Funder type"},
        # --- Software ---
        "software.softwareName": {"type": "keyword", "description": "Software name used in publication"},
        "software.wikidata": {"type": "keyword", "description": "Software Wikidata ID"},
        # --- Citation counts ---
        "cited_by_counts_by_year.2020": {"type": "long", "description": "Citations received in 2020"},
        "cited_by_counts_by_year.2021": {"type": "long", "description": "Citations received in 2021"},
        "cited_by_counts_by_year.2022": {"type": "long", "description": "Citations received in 2022"},
        "cited_by_counts_by_year.2023": {"type": "long", "description": "Citations received in 2023"},
        "cited_by_counts_by_year.2024": {"type": "long", "description": "Citations received in 2024"},
        # --- Co-* convenience fields ---
        "co_authors": {"type": "keyword", "description": "Co-author IDs (denormalized)"},
        "co_countries": {"type": "keyword", "description": "Co-author countries (denormalized)"},
        "co_institutions": {"type": "keyword", "description": "Co-institution IDs (denormalized)"},
        "co_structures": {"type": "keyword", "description": "Co-structure IDs (denormalized)"},
        "co_projects": {"type": "keyword", "description": "Co-project IDs (denormalized)"},
        "co_software": {"type": "keyword", "description": "Co-software names (denormalized)"},
        "bso_local_affiliations": {"type": "keyword", "description": "Local BSO affiliation tags"},
    },
}


def register(mcp: FastMCP):

    @mcp.tool()
    def get_schema() -> str:
        """
        Returns a summary of all available fields in the scanr-publications
        Elasticsearch index. Call this first before building any query.
        """
        return json.dumps(SCHEMA_SUMMARY, indent=2)
