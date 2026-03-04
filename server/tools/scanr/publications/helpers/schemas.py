from pydantic import BaseModel, Field
from logger import get_logger

logger = get_logger(__name__)


class Label(BaseModel):
    default: str = Field(description="default label")
    en: str | None = Field(description="english label", default=None)
    fr: str | None = Field(description="french label", default=None)


class ScanRAuthor(BaseModel):
    id: str | None = Field(description="id of the author", default=None)
    name: str = Field(description="full name of the author")


class ScanRAffiliation(BaseModel):
    id: str = Field(description="id of the structure")
    label: Label = Field(description="name of the structure")
    kind: list[str] = Field(description="kind of the structure", default_factory=list)


class ScanRDomain(BaseModel):
    code: str = Field(description="wikidata code of the domain")
    label: Label = Field(description="name of the domain")


class ScanRProject(BaseModel):
    id: str = Field(description="id of the project")
    label: Label = Field(description="name of the project")
    year: int = Field(description="year of the project")


class ScanRLightPublication(BaseModel):
    id: str = Field(description="id of the publication")
    title: str = Field(description="title of the publication")
    summary: str | None = Field(description="summary of the publication", default=None)


class ScanRPublication(ScanRLightPublication):
    authors: list[ScanRAuthor] = Field(description="authors of the publication")
    affiliations: list[ScanRAffiliation] = Field(
        description="affiliated structures of the publication", default_factory=list
    )
    domains: list[ScanRDomain] = Field(description="domains of the publication", default_factory=list)
    projects: list[ScanRProject] = Field(description="funding projects of the publication", default_factory=list)
    software: list[str] = Field(description="software of the publication", default_factory=list)
    type: str = Field(description="type of the publication")
    year: int = Field(description="year of the publication")
    open_access: bool = Field(description="is the publication open access")


def scanr_publication_to_model(publication: dict) -> ScanRPublication:
    return ScanRPublication(
        id=publication["id"],
        title=publication["title"].get("default"),
        summary=publication.get("summary", {}).get("default"),
        authors=[ScanRAuthor(id=author.get("person"), name=author["fullName"]) for author in publication.get("authors", [])],
        domains=[
            ScanRDomain(code=domain["code"], label=domain["label"])
            for domain in publication.get("domains", [])
            if domain.get("type") == "wikidata"
        ],
        affiliations=[
            ScanRAffiliation(id=affiliation["id"], label=affiliation["label"], kind=affiliation.get("kind"))
            for affiliation in publication.get("affiliations", [])
            if affiliation.get("label")
        ],
        projects=[
            ScanRProject(id=project["id"], label=project["label"], year=project["year"])
            for project in publication.get("projects", [])
        ],
        software=[software["softwareName"] for software in publication.get("software", [])],
        type=publication["type"],
        year=publication["year"],
        open_access=publication["isOa"],
    )
