import os
import yaml
import httpx
from functools import lru_cache
from typing import Literal, Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from helpers.elastic import es_index_clean
from helpers.logger import get_logger

logger = get_logger(__name__)


def index_get_schema_url(index: str) -> str:
    """
    Get the schema url for an index.
    """
    es_index = es_index_clean(index)
    scanr_schema_url = os.getenv("SCANR_SCHEMAS_URL")
    url = f"{scanr_schema_url}/{es_index}.yaml"
    return url


@lru_cache
def index_get_base_schema(index: str) -> dict:
    """
    Get the schema for an index.
    """
    index_schema_url = index_get_schema_url(index)
    with httpx.Client() as client:
        response = client.get(index_schema_url, timeout=30)
        response.raise_for_status()
        schema = yaml.safe_load(response.text)
        return schema


def index_get_description(index: str) -> str:
    """
    Get the description for an index.
    """
    schema = index_get_base_schema(index)
    return schema.get("_meta", {}).get("description", "")


def field_get_infos(field: dict) -> dict:
    """
    Get the infos for the fields.
    """
    infos = {}
    # elastic type
    infos["type"] = field.get("type", "unknown")
    # elastic is keyword
    if field.get("has_keyword"):
        infos["keyword"] = True
    # field description
    if field.get("description"):
        infos["description"] = field["description"]
    else:
        if field.get("ai_suggestions", {}).get("description"):
            infos["description"] = field["ai_suggestions"]["description"]
    # additional notes
    if field.get("ai_suggestions", {}).get("notes"):
        infos["notes"] = field["ai_suggestions"]["notes"]
    # cross reference
    if field.get("cross_ref"):
        infos["cross_ref"] = field["cross_ref"]
    return infos


def index_get_fields(index: str, filter: Literal["all", "primary", "secondary"] = "primary") -> dict:
    """
    Get the schema for an index.
    """
    schema = index_get_base_schema(index)
    fields = schema.get("fields", {})
    return {
        key: field_get_infos(field)
        for key, field in fields.items()
        if not field.get("exclude", False)
        and (
            filter == "all"
            or (filter == "primary" and field.get("primary", False))
            or (filter == "secondary" and not field.get("primary", False))
        )
    }


def register(mcp: FastMCP, index: str, index_description: str):

    @mcp.tool(
        name=f"{index}_get_schema",
        description=f"""
        Fetch and return the simplified field schema for the {index} Elasticsearch index.
        Index content: {index_description}
        Call this before building any query so you know which fields exist and their types.
        Try first with filter="primary" to get the most relevant fields of the index.
        If you need more fields, use filter="secondary" or filter="all".

        Returns a flat dict of dot-notation field paths with their types, e.g.:
          "title.default": {{"type": "text", "keyword": true}}
          "year":           {{"type": "long"}}
          "isOa":           {{"type": "boolean"}}

        Notes:
        - text fields  → use match / multi_match queries
        - keyword fields → use term / terms queries (exact match)
        - if "keyword": true → a .keyword sub-field exists for aggregations/exact match
        """,
    )
    def get_schema(
        filter: Annotated[
            Literal["all", "primary", "secondary"],
            Field(default="primary", description="Filter schema fields"),
        ],
    ) -> dict:
        f"""
        Get simplified schema for the {index} Elasticsearch index.
        """
        fields = index_get_fields(index, filter)
        logger.debug(f"{fields=}")
        return {"index": index, "fields": fields}
