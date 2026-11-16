import os
import time
import yaml
from typing import Literal
from mcp.server.fastmcp.exceptions import FastMCPError
from helpers.http import request
from helpers.logger import get_logger
from tools.scanr.registry import schema_url

logger = get_logger(__name__)

SCHEMA_TTL = float(os.getenv("SCANR_SCHEMA_TTL", "3600"))
SCHEMA_RETRY_AFTER = 300

# index -> (expires_at, schema)
_schema_cache: dict[str, tuple[float, dict]] = {}


def clear_cache() -> None:
    _schema_cache.clear()


async def index_get_base_schema(index: str) -> dict:
    """
    Get the schema for an index, cached for SCHEMA_TTL seconds.
    If a refresh fails, the last good schema is served until the next retry.
    """

    now = time.monotonic()
    cached = _schema_cache.get(index)
    if cached and cached[0] > now:
        return cached[1]
    try:
        schema = await _fetch_schema(index)
    except FastMCPError:
        if cached is None:
            raise
        logger.warning(f"Schema refresh failed for {index}, serving the cached schema.")
        _schema_cache[index] = (now + SCHEMA_RETRY_AFTER, cached[1])
        return cached[1]
    _schema_cache[index] = (now + SCHEMA_TTL, schema)
    return schema


async def _fetch_schema(index: str) -> dict:
    response = await request("GET", schema_url(index), service="scanr-schemas", timeout=30)
    if not response.is_success:
        raise FastMCPError(
            {"error": "upstream_error", "service": "scanr-schemas", "status": response.status_code, "message": index}
        )
    return yaml.safe_load(response.text)


async def index_known_fields(index: str) -> set[str]:
    """Names of the fields an index exposes, used to validate queries."""
    fields = (await index_get_base_schema(index)).get("fields", {})
    return {name for name, field in fields.items() if not field.get("exclude", False)}


async def index_primary_fields(index: str) -> list[str]:
    """Primary fields, which are returned by default in search results."""
    fields = (await index_get_base_schema(index)).get("fields", {})
    return [name for name, field in fields.items() if field.get("primary") and not field.get("exclude", False)]


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


async def index_get_aggregation_field(index: str, field_name: str) -> str:
    """Return the exact Elasticsearch field path for a terms aggregation."""
    field = (await index_get_base_schema(index)).get("fields", {}).get(field_name)
    if not field or field.get("exclude", False):
        raise FastMCPError(f"Field {field_name!r} is not available in the {index} schema.")

    infos = field_get_infos(field, field_name)
    aggregation_field = infos.get("aggregation_field")
    if not aggregation_field:
        raise FastMCPError(
            f"Field {field_name!r} is not aggregatable according to the {index} schema."
        )
    return aggregation_field


async def index_get_fields(index: str, filter: Literal["all", "primary", "secondary"] = "primary") -> dict:
    """
    Get the schema for an index.
    """
    schema = await index_get_base_schema(index)
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
