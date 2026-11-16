import difflib
import os
import time
from typing import Literal

import yaml
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
    notes = field.get("notes", field.get("ai_suggestion", {}).get("notes"))
    if notes:
        infos["notes"] = notes
    # cross reference
    cross_index = field.get("cross_index", field.get("ai_suggestion", {}).get("cross_index"))
    if cross_index:
        infos["cross_index"] = cross_index
    examples = field.get("examples", field.get("example_values", field.get("example")))
    if examples is None:
        suggestion = field.get("ai_suggestion", {})
        examples = suggestion.get("examples", suggestion.get("example_values", suggestion.get("example")))
    if examples is not None:
        infos["examples"] = examples
    return infos


async def index_describe_field(index: str, field_name: str) -> dict:
    """Return full schema metadata for a single field."""
    fields = (await index_get_base_schema(index)).get("fields", {})
    field = require_known_field(index, field_name, fields)
    return {
        "index": index,
        "field": field_name,
        **field_get_infos(field, field_name),
    }


def require_known_field(index: str, field_name: str, fields: dict) -> dict:
    field = fields.get(field_name)
    if not field or field.get("exclude", False):
        suggestions = difflib.get_close_matches(field_name, index_known_fields_from(fields), n=3, cutoff=0.6)
        raise FastMCPError(
            {
                "error": "unknown_field",
                "message": f"Field {field_name!r} is not available in the {index} schema.",
                "did_you_mean": suggestions,
                "hint": "Use a field from scanr_get_schema or one of the suggested names.",
            }
        )
    return field


def index_known_fields_from(fields: dict) -> list[str]:
    return [name for name, metadata in fields.items() if not metadata.get("exclude", False)]


async def index_get_aggregation_field(index: str, field_name: str) -> str:
    """Return the exact Elasticsearch field path for a terms aggregation."""
    fields = (await index_get_base_schema(index)).get("fields", {})
    field = require_known_field(index, field_name, fields)

    infos = field_get_infos(field, field_name)
    aggregation_field = infos.get("aggregation_field")
    if not aggregation_field:
        raise FastMCPError(
            f"Field {field_name!r} is not aggregatable according to the {index} schema."
        )
    return aggregation_field


async def index_get_fields(
    index: str,
    filter: Literal["all", "primary", "secondary"] = "primary",
    search: str | None = None,
    prefix: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    Get a compact, filtered page of the schema for an index.
    """
    if not 1 <= limit <= 500:
        raise FastMCPError("limit must be between 1 and 500.")
    if offset < 0:
        raise FastMCPError("offset must be non-negative.")
    normalized_prefix = prefix.removesuffix("*").removesuffix(".") if prefix else None
    search_text = search.casefold().strip() if search else None
    schema = await index_get_base_schema(index)
    fields = schema.get("fields", {})
    matches = []
    for key, field in fields.items():
        if field.get("exclude", False):
            continue
        if filter == "primary" and not field.get("primary", False):
            continue
        if filter == "secondary" and field.get("primary", False):
            continue
        if normalized_prefix and not (key == normalized_prefix or key.startswith(normalized_prefix + ".")):
            continue
        infos = field_get_infos(field, key)
        description = infos.get("description", "")
        if search_text and search_text not in key.casefold() and search_text not in description.casefold():
            continue
        compact = {"type": infos["type"]}
        if infos.get("aggregation_field"):
            compact["aggregation_field"] = infos["aggregation_field"]
        if description:
            compact["description"] = description[:160] + ("…" if len(description) > 160 else "")
        matches.append((key, compact))
    return dict(matches[offset : offset + limit])
