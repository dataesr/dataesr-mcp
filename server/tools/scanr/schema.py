import os
import yaml
import httpx
from functools import lru_cache
from typing import Literal
from mcp.server.fastmcp.exceptions import FastMCPError
from helpers.elastic import es_index_clean


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


AGGREGATABLE_TYPES = {
    "byte",
    "short",
    "integer",
    "long",
    "unsigned_long",
    "half_float",
    "float",
    "double",
    "scaled_float",
    "date",
    "date_nanos",
    "boolean",
    "keyword",
    "constant_keyword",
    "wildcard",
    "ip",
}


def field_get_infos(field: dict, field_name: str | None = None) -> dict:
    """
    Get the infos for the fields.
    """
    infos = {}
    # elastic type
    infos["type"] = field.get("type", "unknown")
    # elastic is keyword
    if field.get("has_keyword"):
        infos["keyword"] = True
        if field_name:
            infos["aggregation_field"] = f"{field_name}.keyword"
    elif field_name and field.get("type") in AGGREGATABLE_TYPES:
        infos["aggregation_field"] = field_name
    # field description
    if field.get("description"):
        infos["description"] = field["description"]
    else:
        if field.get("ai_suggestion", {}).get("description"):
            infos["description"] = field["ai_suggestion"]["description"]
    # additional notes
    if field.get("ai_suggestion", {}).get("notes"):
        infos["notes"] = field["ai_suggestion"]["notes"]
    # cross reference
    if field.get("cross_index"):
        infos["cross_index"] = field["cross_index"]
    return infos


def index_get_aggregation_field(index: str, field_name: str) -> str:
    """Return the exact Elasticsearch field path for a terms aggregation."""
    field = index_get_base_schema(index).get("fields", {}).get(field_name)
    if not field or field.get("exclude", False):
        raise FastMCPError(f"Field {field_name!r} is not available in the {index} schema.")

    infos = field_get_infos(field, field_name)
    aggregation_field = infos.get("aggregation_field")
    if not aggregation_field:
        raise FastMCPError(
            f"Field {field_name!r} is not aggregatable according to the {index} schema."
        )
    return aggregation_field


def index_get_fields(index: str, filter: Literal["all", "primary", "secondary"] = "primary") -> dict:
    """
    Get the schema for an index.
    """
    schema = index_get_base_schema(index)
    fields = schema.get("fields", {})
    return {
        key: field_get_infos(field, key)
        for key, field in fields.items()
        if not field.get("exclude", False)
        and (
            filter == "all"
            or (filter == "primary" and field.get("primary", False))
            or (filter == "secondary" and not field.get("primary", False))
        )
    }
