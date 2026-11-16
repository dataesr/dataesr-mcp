"""The scanR indexes: tool-facing names, Elasticsearch targets and descriptions. Single source of truth."""

import os
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class IndexSpec:
    es_index: str
    description: str


INDEXES: dict[str, IndexSpec] = {
    "scanr_publications": IndexSpec(
        "scanr-publications",
        "Scientific publications and other research outputs.",
    ),
    "scanr_persons": IndexSpec(
        "scanr-persons",
        "Researchers and other people in the research ecosystem.",
    ),
    "scanr_organizations": IndexSpec(
        "scanr-organizations",
        "Research organizations and institutions.",
    ),
    "scanr_projects": IndexSpec(
        "scanr-projects",
        "Research project records. Choose this index when asking about the project itself, such as its title, description, dates, or identifiers.",
    ),
    "scanr_participations": IndexSpec(
        "scanr-participations",
        "Relationships recording a person's or organization's participation in a research project. Choose this index to find who participated in a project, which projects an entity participated in, or participation-specific details.",
    ),
    "scanr_patents": IndexSpec(
        "scanr-patents",
        "Patents and patent-related research outputs.",
    ),
}

ScanrIndex = Literal[tuple(INDEXES)]  # ty: ignore[invalid-type-form]


def get_index(name: str) -> IndexSpec:
    return INDEXES[name]


def schema_url(name: str) -> str:
    return f"{os.getenv('SCANR_SCHEMAS_URL')}/{INDEXES[name].es_index}.yaml"
